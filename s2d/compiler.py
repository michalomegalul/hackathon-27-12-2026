"""Spec compiler: Czech company description + story -> validated StorySpec.

    python -m s2d.compiler examples/stories/pekarna.yaml [--seed 7] [--out spec.yaml]

A story file is YAML with two keys, `company` and `story`, both Czech text.

The LLM fills the JSON Schema in schema/story.schema.json (passed to Ollama as
`format`). Pydantic then checks types and bounds, and StorySpec's validator does
the semantic checks (dates in range, known segments/cities/categories, shares
sum to 1). On failure the error text goes back to the model, up to MAX_RETRIES
times. If that still fails and ANTHROPIC_API_KEY is set, Claude gets one try.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

from s2d import llm
from s2d.spec import StorySpec, load_spec

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "story.schema.json"
MAX_RETRIES = 2

# Few-shot inputs for the two hand-written example specs. The outputs are the
# YAML files themselves, so editing an example updates the prompt.
EXAMPLES = [
    {
        "path": ROOT / "examples" / "a.yaml",
        "company": (
            "Pražírna Zrnko s.r.o. je pražírna výběrové kávy. Prodává přes e-shop s předplatným "
            "a ve 4 vlastních kavárnách v Praze, Brně, Ostravě a Plzni. Má asi 12 000 aktivních "
            "zákazníků: studenty, předplatitele a běžné zákazníky. Kávu dováží z Etiopie, Kolumbie "
            "a Brazílie, příslušenství od českého dodavatele."
        ),
        "story": (
            "Data od ledna 2025 do konce října 2026. 1. 3. 2026 zdražíme kávu o 15 %. Prodeje kávy "
            "mírně klesnou a studenti začnou zhruba po 6 týdnech odcházet. Začátkem května se zpozdí "
            "dodávka z Etiopie, etiopská zrna se vyprodají a přijdou stížnosti. Brněnští předplatitelé "
            "pak částečně odejdou. V září otevře v Brně konkurenční kavárna a prodeje v brněnské "
            "kavárně klesnou o pětinu. Pozor na falešné stopy: virální video o mlýncích v říjnu 2025 "
            "a Black Friday."
        ),
    },
    {
        "path": ROOT / "examples" / "b.yaml",
        "company": (
            "ElektroDomov a.s. je online prodejce domácí elektroniky s doručením po celé ČR, "
            "prodává přes web a mobilní aplikaci. Asi 30 000 zákazníků: rodiny, technické nadšence "
            "a seniory. Malé a velké spotřebiče a mobily od tří distributorů."
        ),
        "story": (
            "Data od března 2025, asi 20 měsíců, ať je to těžké. V únoru 2026 přejdeme na Moravě "
            "(Ostrava, Olomouc) na levnějšího přepravce. Zásilky chodí o 2-3 dny později, hodnocení "
            "padá a zákazníci tam po zhruba 5 týdnech odcházejí. V dubnu 2026 poběží kampaň na "
            "mobily pro geeky. V září 2025 vypadla na den data z aplikace."
        ),
    },
]

RULES = """\
You compile a Czech company description and a Czech story into a JSON spec for a
data simulator. Output only JSON that matches the schema.

Rules:
- Use only the enum values the schema allows. Ids (segments, categories, suppliers,
  events) are short ASCII snake_case; city names keep Czech diacritics.
- Segment shares must sum to 1. City weights must sum to 1. Channel weights should sum to 1.
- Every category.supplier must be a supplier id. Every event/decoy target must use
  cities, segments, categories, suppliers and channels defined in the spec.
- meta.start + meta.days must cover every event and decoy date. Pick days between 90
  and 1095. If the story gives no dates, start on {today_year}-01-01 and use 540 days.
- Effect size is relative: -0.06 means -6 %, 0.6 means +60 % on the metric.
  lag_days = delay before the effect starts, ramp_days = linear ramp,
  duration_days = plateau after the ramp (null = permanent),
  decay_halflife_days = tail after the plateau (null = stop at once).
- A consequence that starts later or hits another group is its own event with
  caused_by set to the id of an earlier event.
- A churn_shock needs params.churn_pct and params.churn_window_days, and its effects
  use metric churn_hazard.
- Things the story calls red herrings, one-off spikes or outages go to decoys, not events.
- Normal seasonal peaks (school start, Christmas, Black Friday, summer) are baseline.seasonality,
  never events. If the story says nothing changes, events is [].
- narrative_cs: one short Czech sentence per event.
- Keep numbers realistic for a Czech business of the described size and type.
"""


@dataclass
class Attempt:
    backend: str
    model: str
    seconds: float
    ok: bool
    error: str = ""
    cached: bool = False
    tokens_per_s: float | None = None


@dataclass
class CompileResult:
    spec: StorySpec | None
    attempts: list[Attempt] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # e.g. data extended to measure an event

    @property
    def ok(self) -> bool:
        return self.spec is not None

    @property
    def retries(self) -> int:
        return max(0, len(self.attempts) - 1)

    @property
    def first_try_valid(self) -> bool:
        return bool(self.attempts) and self.attempts[0].ok

    @property
    def seconds(self) -> float:
        return sum(a.seconds for a in self.attempts)

    def yaml(self) -> str:
        return spec_to_yaml(self.spec) if self.spec else ""


def load_story_file(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return {"company": data["company"], "story": data["story"]}


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _require_all(node):
    """Make every property required, recursively. Optional keys let the grammar
    skip them, and gemma4 then happily emits `events: []`. Nullable fields stay
    nullable, so this only forces the model to decide, not to invent."""
    if isinstance(node, dict):
        out = {k: _require_all(v) for k, v in node.items()}
        if isinstance(out.get("properties"), dict):
            out["required"] = list(out["properties"])
        return out
    if isinstance(node, list):
        return [_require_all(v) for v in node]
    return node


def llm_schema() -> dict:
    """schema/story.schema.json, tightened for generation: all keys required. `events`
    may be empty (a story where nothing happens); an empty list is challenged once
    in compile_story instead of being forbidden by the grammar."""
    return _require_all(load_schema())


def spec_to_yaml(spec: StorySpec) -> str:
    # Every nullable field defaults to None, so dropping nulls loses nothing.
    data = spec.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)


def _example_block(ex: dict) -> str:
    spec = load_spec(ex["path"])
    out = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"### Company\n{ex['company']}\n### Story\n{ex['story']}\n### Spec\n{out}\n"


def build_prompt(company: str, story: str) -> str:
    parts = [RULES.format(today_year=date.today().year), "## Examples\n"]
    for i, ex in enumerate(EXAMPLES):
        parts.append(f"## Example {'AB'[i]}\n{_example_block(ex)}")
    parts.append(f"## Your task\n### Company\n{company.strip()}\n### Story\n{story.strip()}\n### Spec\n")
    return "\n".join(parts)


def retry_prompt(base: str, bad_output, error: str) -> str:
    shown = bad_output if isinstance(bad_output, str) else json.dumps(bad_output, ensure_ascii=False)
    return (f"{base}{shown}\n\n## Your previous spec was rejected\n{error}\n\n"
            "Fix exactly these problems and output the whole corrected spec.\n### Spec\n")


def format_errors(err: Exception) -> str:
    """Validation errors as short lines the model can act on."""
    if isinstance(err, ValidationError):
        lines = []
        for e in err.errors():
            loc = ".".join(str(p) for p in e["loc"])
            msg = e["msg"].removeprefix("Value error, ")
            lines.append(f"- {loc}: {msg}" if loc else f"- {msg}")
        return "\n".join(lines[:20])
    return f"- {err}"


EMPTY_EVENTS = ("events is empty: every change the story describes (a price change, campaign, delay, "
                "churn, competitor, ...) must be an event. Seasonal peaks are not events. If the story "
                "really describes no change, output the same spec again with events: [].")


def validate(data, allow_empty: bool = False) -> StorySpec:
    """Pydantic types/bounds plus StorySpec's semantic checks. An empty `events` is an
    error unless allow_empty (the model already confirmed it once)."""
    if not isinstance(data, dict):
        raise ValueError("output is not a JSON object")
    spec = StorySpec.model_validate(data)
    if not spec.events and not allow_empty:
        raise ValueError(EMPTY_EVENTS)
    return spec


def compile_story(company: str, story: str, *, seed: int | None = None,
                  backend: str | None = None, fallback: bool = True,
                  on_status=None, cache: bool = True) -> CompileResult:
    schema = llm_schema()
    base = build_prompt(company, story)
    prompt = base
    result = CompileResult(spec=None)
    say = on_status or (lambda _msg: None)
    empty_seen = False  # gemma likes a lazy `events: []`: challenged once, accepted the second time

    plan = [backend or llm.backend_name()] * (1 + MAX_RETRIES)
    if fallback and plan[0] != "claude" and llm.claude_available():
        plan.append("claude")

    for i, b in enumerate(plan):
        say(f"attempt {i + 1}/{len(plan)} on {b}")
        t0 = time.perf_counter()
        try:
            data = llm.complete("spec", prompt, schema, backend=b, on_status=say, cache=cache)
        except llm.LLMError as e:
            info = llm.last_call()
            result.attempts.append(Attempt(b, info.model or "?", time.perf_counter() - t0, False, str(e)))
            if b == "replay" or isinstance(e, llm.CacheMiss):
                break  # nothing will change on retry
            continue
        info = llm.last_call()
        try:
            spec = validate(data, allow_empty=empty_seen)
        except (ValidationError, ValueError) as e:
            empty_seen = empty_seen or str(e) == EMPTY_EVENTS
            msg = format_errors(e)
            result.attempts.append(Attempt(b, info.model, info.seconds, False, msg,
                                           info.cached, info.tokens_per_s))
            say(f"attempt {i + 1} invalid:\n{msg}")
            prompt = retry_prompt(base, data, msg)
            continue
        if seed is not None:
            spec.meta.seed = seed
        from s2d.verify import fit_windows
        spec, result.warnings = fit_windows(spec)  # every event measurable before the data ends
        for w in result.warnings:
            say(f"WARNING {w}")
        result.attempts.append(Attempt(b, info.model, info.seconds, True, "", info.cached, info.tokens_per_s))
        result.spec = spec
        break
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m s2d.compiler")
    p.add_argument("story_file", help="YAML with `company` and `story` (Czech text)")
    p.add_argument("--seed", type=int)
    p.add_argument("--backend", choices=["ollama", "claude", "replay"])
    p.add_argument("--no-fallback", action="store_true")
    p.add_argument("--out", help="write the spec YAML here")
    args = p.parse_args(argv)

    src = load_story_file(args.story_file)
    res = compile_story(src["company"], src["story"],
                        seed=args.seed, backend=args.backend, fallback=not args.no_fallback,
                        on_status=lambda m: print(f"  {m}", file=sys.stderr))
    for i, a in enumerate(res.attempts, 1):
        speed = f", {a.tokens_per_s:.0f} tok/s" if a.tokens_per_s else ""
        state = "valid" if a.ok else "INVALID"
        print(f"attempt {i}: {a.backend}/{a.model} {a.seconds:.1f}s{speed}{' (cached)' if a.cached else ''} {state}")
        if a.error:
            print("  " + a.error.replace("\n", "\n  "))
    print(f"total {res.seconds:.1f}s, retries {res.retries}, first try valid: {res.first_try_valid}")
    for w in res.warnings:
        print(f"WARNING {w}")
    if not res.ok:
        return 1
    text = res.yaml()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
