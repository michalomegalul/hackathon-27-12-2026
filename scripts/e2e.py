"""End to end on every story: compiler (real LLM) -> calibration -> sim -> twin -> verifier.

    uv run python scripts/e2e.py                                  # examples/stories/*.yaml
    uv run python scripts/e2e.py examples/stories/vino.yaml --cache --n-customers 10000

The compiler runs without the LLM cache by default, so 'first try' is a real Ollama
call (--cache reuses cached specs). Each story's spec, verifier result and log go to
--out/<story>/. Prints one row per story and checks the goals:

    no crash, no NaN, no absurd value (|x| > 1000 in a % column), twin <= 10 %,
    story >= 80 % of the tests of supported events
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from s2d import llm, verify  # noqa: E402
from s2d.calibrate import calibrate  # noqa: E402
from s2d.compiler import compile_story, load_story_file  # noqa: E402
from s2d.sim import simulate, without_story  # noqa: E402
from s2d.sim.events import unsupported_reason  # noqa: E402

ABSURD = 1000.0
STORY_GOAL, TWIN_GOAL = 0.8, 0.1


def numbers(r: dict) -> list[tuple[float, str]]:
    """(value, unit) of every reported number of a test row, story and twin."""
    mu = r.get("measured_unit", "%")
    out = []
    for side in (r, r.get("twin") or {}):
        if side.get("status") == "not_testable" or "measured_pct" not in side:
            continue
        out += [(side["measured_pct"], mu), (side.get("z"), "z")]
        out += [(v, mu) for v in side.get("ci_pct") or []]
    return out


def bad_numbers(res: dict) -> tuple[int, int]:
    """(NaN or missing, absurd) over all tested rows."""
    nan = absurd = 0
    for r in res["tests"]:
        for v, unit in numbers(r):
            if v is None or not math.isfinite(v):
                nan += 1
            elif unit == "%" and abs(v) > ABSURD:
                absurd += 1
    return nan, absurd


def run_story(path: Path, out: Path, n_customers: int | None, cache: bool, seed: int) -> dict:
    row = {"story": path.stem, "stage": "compile", "crash": ""}
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    try:
        src = load_story_file(path)
        log = []
        res = compile_story(src["company"], src["story"], seed=seed, fallback=False, cache=cache,
                            on_status=log.append)
        row["t_compile"] = round(time.perf_counter() - t0, 1)
        row["first_try"] = res.first_try_valid
        row["attempts"] = len(res.attempts)
        row["warnings"] = res.warnings
        (out / "compile.log").write_text("\n".join(log), "utf-8")
        if not res.ok:
            row["crash"] = "no valid spec: " + (res.attempts[-1].error if res.attempts else "?")[:200]
            return row
        spec = res.spec
        (out / "spec.yaml").write_text(res.yaml(), "utf-8")
        if n_customers:
            spec.entities.customers.n = n_customers
        row["events"] = len(spec.events)
        row["types"] = sorted({e.type.value for e in spec.events})
        row["unsupported"] = sorted({e.type.value for e in spec.events if unsupported_reason(spec, e)})

        row["stage"] = "sim"
        t1 = time.perf_counter()
        if spec.events:
            spec, _ = calibrate(spec, seed=seed, log=lambda m: None)
        story = simulate(spec, seed=seed)
        twin = simulate(without_story(spec), seed=seed)
        row["t_sim"] = round(time.perf_counter() - t1, 1)

        row["stage"] = "verify"
        t2 = time.perf_counter()
        ver = verify.verify_con(verify.world_con(story), spec, story.truth["answer_key"], verify.world_con(twin))
        row["t_verify"] = round(time.perf_counter() - t2, 1)
        row["stage"] = "narrate"
        ver["narration"] = verify.narrate(ver)
        (out / "verify.json").write_text(json.dumps(ver, ensure_ascii=False, indent=1, default=str), "utf-8")
        (out / "verify.txt").write_text(verify.format_table(ver) + "\n\n" + ver["narration"]["text"]
                                        + f"\n({ver['narration']['source']})\n", "utf-8")
        row["stage"] = "done"
        row["n"] = ver["n"]
        row["not_testable"] = sum(r["status"] == "not_testable" for r in ver["tests"])
        row["confirmed"] = ver["confirmed"]
        row["twin_confirmed"] = ver["twin_confirmed"]
        row["untested"] = [f"{u['event_id']}: {u['reason']}" for u in ver["untested"]]
        row["nan"], row["absurd"] = bad_numbers(ver)
        row["narrator"] = ver["narration"]["source"]
    except Exception as e:  # noqa: BLE001 - the point is to report every crash
        row["crash"] = f"{type(e).__name__}: {e}"
        (out / "crash.txt").write_text(traceback.format_exc(), "utf-8")
    finally:
        row["t_total"] = round(time.perf_counter() - t0, 1)
    return row


def goals(row: dict) -> list[str]:
    """The goals this story misses (empty = all met)."""
    if row["crash"]:
        return [f"crash in {row['stage']}"]
    miss = []
    if row["nan"]:
        miss.append(f"{row['nan']} NaN")
    if row["absurd"]:
        miss.append(f"{row['absurd']} absurd")
    if row["n"]:
        if row["twin_confirmed"] / row["n"] > TWIN_GOAL:
            miss.append("twin > 10 %")
        if row["confirmed"] / row["n"] < STORY_GOAL:
            miss.append("story < 80 %")
    return miss


def table(rows: list[dict]) -> str:
    head = ("| story | 1st try | events | types | story | twin | not testable | NaN | > 1000 % | "
            "compile s | sim s | verify s | goals |")
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    for r in rows:
        miss = goals(r)
        if r["crash"] and "n" not in r:
            lines.append(f"| {r['story']} | {r.get('first_try', '–')} | {r.get('events', '–')} | "
                         f"{', '.join(r.get('types', []))} | – | – | – | – | – | {r.get('t_compile', '–')} | "
                         f"{r.get('t_sim', '–')} | – | ❌ {r['crash'][:80]} |")
            continue
        types = ", ".join(t + ("*" if t in r["unsupported"] else "") for t in r["types"])
        first = "yes" if r["first_try"] else f"no ({r['attempts']} attempts)"
        lines.append(
            f"| {r['story']} | {first} | "
            f"{r['events']} | {types} | {r['confirmed']}/{r['n']} | {r['twin_confirmed']}/{r['n']} | "
            f"{r['not_testable']} | {r['nan']} | {r['absurd']} | {r['t_compile']} | {r['t_sim']} | "
            f"{r['t_verify']} | {'✅' if not miss else '❌ ' + ', '.join(miss)} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scripts/e2e.py")
    p.add_argument("stories", nargs="*", help="story YAML files (default: examples/stories/*.yaml)")
    p.add_argument("--out", default=str(ROOT / "data" / "e2e"))
    p.add_argument("--n-customers", type=int, help="override entities.customers.n (faster)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--cache", action="store_true", help="reuse cached LLM answers")
    a = p.parse_args(argv)
    paths = [Path(s) for s in a.stories] or sorted((ROOT / "examples" / "stories").glob("*.yaml"))
    print(f"{llm.describe()}, {len(paths)} stories, cache {'on' if a.cache else 'off'}", file=sys.stderr)
    rows = []
    for path in paths:
        row = run_story(path, Path(a.out) / path.stem, a.n_customers, a.cache, a.seed)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False, default=str), file=sys.stderr)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), "utf-8")
    text = table(rows)
    notes = [f"- {r['story']}: {w}" for r in rows for w in r.get("warnings", []) + r.get("untested", [])]
    text += "\n\n\\* unsupported event type\n" + ("\n".join(notes) if notes else "")
    (Path(a.out) / "summary.md").write_text(text + "\n", "utf-8")
    print(text)
    return 0 if all(not goals(r) for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
