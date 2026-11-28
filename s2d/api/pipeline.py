"""What one job does: the pipeline of app/main.py run_sim, in the five steps the status shows.

compile (unless spec_yaml) -> calibrate -> simulate -> fill_reviews (if a pool exists) ->
write_world -> twin -> verify -> narrate (template fallback) -> analyst.duckdb, analyst_twin.duckdb
+ result.json.
The detective is a separate job on a finished one.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

import yaml

from . import sandbox, store

MAX_CUSTOMERS = 100_000


class Steps:
    """Marks the job's steps as they run and records their durations for the ETA."""

    def __init__(self, state: dict):
        self.state = state

    def log(self, msg: str) -> None:
        t = round(time.time() - (self.state["started"] or time.time()), 1)
        self.state["log"] = (self.state["log"] + [[t, str(msg)]])[-200:]
        store.save_job(self.state)

    @contextmanager
    def step(self, i: int):
        st = self.state["steps"][i]
        st["started"] = time.time()
        store.save_job(self.state)
        yield st
        st["s"] = round(time.time() - st["started"], 1)
        st["done"] = True
        store.save_job(self.state)
        if st.pop("record", True):  # a cached LLM answer or the template says nothing about the GPU
            store.record_timing(st["name"], st["s"], self.state.get("n_customers") or store.DEFAULT_N)


def parse_spec(spec_yaml: str):
    from s2d.spec import StorySpec
    try:
        data = yaml.safe_load(spec_yaml)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("spec_yaml must be a YAML mapping")
    return StorySpec.model_validate(data)


def _attempt_note(res) -> str:
    n = len(res.attempts)
    via = res.attempts[-1].backend if res.attempts else "?"
    cached = " (z cache)" if res.attempts and res.attempts[-1].cached else ""
    return f"platná na {n}. pokus{cached}" + ("" if via != "claude" else ", záložní Claude")


def apply_params(spec, p: dict):
    from s2d.spec import Difficulty
    spec = spec.model_copy(deep=True)
    if p.get("seed") is not None:
        spec.meta.seed = int(p["seed"])
    if p.get("difficulty"):
        spec.meta.difficulty = Difficulty(p["difficulty"])
    if p.get("n_customers"):
        spec.entities.customers.n = min(int(p["n_customers"]), MAX_CUSTOMERS)
    return spec


def verification_rows(ver: dict) -> list[dict]:
    rows = []
    for r in ver["tests"]:
        tw = r.get("twin") or {}
        rows.append({
            "event_id": r["event_id"], "claim_cs": r.get("claim_cs") or "", "kpi": r["kpi"],
            "metric": r.get("metric"), "target": r.get("segment") or "", "start": r.get("T"),
            "direction": r.get("direction"),
            "story_size": r.get("story_pct"), "story_unit": r.get("unit", "%"),
            "expected_size": r.get("expected_pct"),
            "measured": r.get("measured_pct"), "measured_unit": r.get("measured_unit", "%"),
            "ci": r.get("ci_pct"), "z": r.get("z"), "p_placebo": r.get("p_placebo"),
            "confirmed": bool(r["confirmed"]), "status": r.get("status"),
            "reason": r.get("reason") or r.get("note") or "",
            "control_mode": r.get("control_mode"), "control": r.get("control"),
            "twin_measured": tw.get("measured_pct"), "twin_z": tw.get("z"),
            "twin_confirmed": bool(tw.get("confirmed")) if tw else None,
            "sql": r.get("sql"), "sql_result": r.get("sql_result"), "sql_matches": r.get("sql_matches"),
        })
    return rows


def summary(ver: dict) -> dict:
    out = {"story": f"{ver['confirmed']}/{ver['n']}"}
    if "twin_confirmed" in ver:
        out["twin"] = f"{ver['twin_confirmed']}/{ver['n']}"
    return out


def _calibrate(spec, s: "Steps", say):
    """Calibration; if a size the story states is too weak to confirm, more customers
    (up to MAX_CUSTOMERS, DECISIONS 129) and every d measured again at that count, with
    the sizes as calibrated. The first pass's warnings are dropped then (only logged),
    they were about the smaller world."""
    from s2d.calibrate import calibrate, customers_for_stated, remeasure
    said: list[str] = []
    out, table = calibrate(spec, log=said.append)
    n0 = spec.entities.customers.n
    n1 = customers_for_stated(spec, table, MAX_CUSTOMERS)
    if n1 is None:
        for m in said:
            say(m)
        return out, table
    for m in said:
        s.log(m.removeprefix("WARNING "))
    short = ", ".join(r.event_id for r in table.itertuples() if r.stated and r.status == "below_target")
    say(f"WARNING počet zákazníků zvýšen z {_num(n0)} na {_num(n1)}: velikost {short} je daná příběhem "
        f"a při {_num(n0)} zákaznících by nešla ověřit")
    out.entities.customers.n = n1  # the calibrated sizes stay: more customers only raise d
    return out, remeasure(out, table, log=say)


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def run_generate(state: dict) -> None:
    """Runs a queued job to the end; raises on failure (the worker records the error)."""
    from s2d import llm, texts, verify
    from s2d.sim import simulate, without_story
    from s2d.sim.dirt import FROM_SPEC
    from s2d.sim.output import write_world

    s = Steps(state)
    p = state["params"]
    jd = store.job_dir(state["job_id"])
    run = jd / "run"
    warnings: list[str] = []

    def say(msg):
        msg = str(msg)
        if msg.startswith("WARNING "):
            warnings.append(msg.removeprefix("WARNING ").strip())
        s.log(msg)

    # 1. spec
    if p.get("spec_yaml"):
        spec = parse_spec(p["spec_yaml"])
    else:
        from s2d.compiler import compile_story
        with s.step(0) as st:
            s.log(f"{llm.describe()}: compiling")
            res = compile_story(p["company"], p["story"], seed=p.get("seed"), on_status=say)
            if not res.ok:
                errs = "; ".join(a.error.splitlines()[0] for a in res.attempts if a.error)
                raise RuntimeError(f"no valid spec after {len(res.attempts)} attempt(s): {errs}"[:600])
            spec = res.spec
            st["note"] = _attempt_note(res)
            st["record"] = not res.attempts[-1].cached
    spec = apply_params(spec, p)
    from s2d.verify import fit_windows
    spec, fw = fit_windows(spec)
    for w in fw:
        say(f"WARNING {w}")
    state["n_customers"] = spec.entities.customers.n
    state["title"] = spec.company.name or state["title"]
    store.save_job(state)

    # 2. calibration + simulation (+ review texts) + files
    with s.step(1) as st:
        s.log(f"simulating {spec.meta.days} days, {spec.entities.customers.n} customers")
        table = None
        if spec.events:
            spec, table = _calibrate(spec, s, say)
            state["n_customers"] = spec.entities.customers.n
            store.save_job(state)
        world = simulate(spec)
        if table is not None:
            world.truth["calibration"] = table
        for reason in world.story.skipped:
            warnings.append(f"skipped {reason}")
        notes = [f"{spec.entities.customers.n} zákazníků, {spec.meta.days} dní"]
        pool = texts.find_pool(spec)
        if pool is not None:
            n = texts.fill_reviews(world.tables, texts.load_pool(pool), spec.meta.seed)
            notes.append(f"texty recenzí: {pool.stem} ({n})")
        dirt = p.get("dirt") or FROM_SPEC[spec.noise.messiness.value]
        write_world(world, run, dirt=dirt)
        rows = {name: int(len(df)) for name, df in world.tables.items()}
        del world
        st["note"] = ", ".join(notes)

    # 3. twin
    with s.step(2):
        write_world(simulate(without_story(spec)), run / "twin")

    # 4. verification
    with s.step(3) as st:
        ver = verify.verify(run, run / "twin")
        st["note"] = verify.summary_line(ver)

    # 5. narrative
    with s.step(4) as st:
        ver["narration"] = verify.narrate(ver, on_status=s.log)
        st["note"] = ver["narration"]["source"]
        st["record"] = not st["note"].startswith("template") and "(cache)" not in st["note"]
    (run / "verify.json").write_text(json.dumps(ver, ensure_ascii=False, default=str), "utf-8")

    sandbox.build_analyst(run / "story.duckdb", jd / "analyst.duckdb")
    sandbox.build_analyst(run / "twin" / "story.duckdb", jd / "analyst_twin.duckdb")
    from s2d.compiler import spec_to_yaml
    result = {
        "job_id": state["job_id"], "spec_yaml": spec_to_yaml(spec), "summary": summary(ver),
        "narrative": {"text": ver["narration"]["text"], "source": ver["narration"]["source"]},
        "verification": verification_rows(ver), "untested": ver.get("untested", []),
        "warnings": list(dict.fromkeys(warnings)), "rows": rows,
    }
    store.write_json(jd / "result.json", result)


def run_detect(state: dict) -> None:
    from s2d import detective, score, verify

    jd = store.job_dir(state["job_id"])
    run, twin = jd / "run", jd / "run" / "twin"
    for f in (run / "detective.json", twin / "detective.json", run / "scorecard.json"):
        f.unlink(missing_ok=True)
    res = detective.run(run, narrate=True)
    detective.save(res, run / "detective.json")
    tw = detective.run(twin, narrate=False)
    detective.save(tw, twin / "detective.json")
    # the verifier's test of every find (story against twin, with its SQL): the page charts a
    # find the prompt never told like a planted event
    words = {n["candidate_id"]: n for n in (res.get("narration") or {}).get("events", [])}
    tested = verify.check_finds(run, twin, [{**e, **words.get(e["id"], {})} for e in res["events"]])
    card = score.scorecard(run, twin)
    store.write_json(run / "scorecard.json", card)
    cols = ["id", "metric", "segment", "start_date", "end_date", "direction", "magnitude_pct",
            "lag_days", "caused_by", "kind", "confidence", "evidence"]
    narr = res.get("narration") or {}
    # the narrator's words per find: what is odd and its hypothesis (the web sets it beside
    # the planted event's narrative_cs)
    words = {n["candidate_id"]: n for n in narr.get("events", [])}
    texts = ("label_cs", "observation_cs", "hypothesis_cs")
    out = {
        "events": [{**{k: e.get(k) for k in cols}, **{k: words.get(e["id"], {}).get(k, "") for k in texts}}
                   for e in res["events"]],
        "narrative": {"text": narr.get("narrative_cs", ""), "source": narr.get("source", "")},
        "score": _score_summary(card["score"], card.get("twin", {}).get("false_events_per_year"),
                                card["placebo"]["p_value"]),
        "matching": matching(card["score"]),
        "charts": verification_rows({"tests": list(tested.values())}),
    }
    store.write_json(jd / "detect_result.json", json.loads(json.dumps(out, default=str)))


def _score_summary(sc: dict, twin_per_year, placebo_p) -> dict:
    return {"precision": sc["precision"], "recall": sc["recall"], "f1": sc["f1"],
            "precision_cons": sc["precision_cons"], "f1_cons": sc["f1_cons"],
            "twin_false_events_per_year": twin_per_year, "placebo_p": placebo_p}


def matching(sc: dict) -> dict:
    """Which find is which planted event, as s2d/score.py decided it (the web draws these)."""
    return {
        "pairs": [{"found_id": m["pred_id"], "event_id": m["event_id"], "score": m["score"],
                   "timing": m["timing"], "delta_days": m["delta_days"], "segment": m["segment"],
                   "magnitude": m["magnitude"]} for m in sc["matches"]],
        "missed": list(sc["missed"]),
        "false_finds": [{"found_id": f["pred_id"], "decoy": f["decoy"]} for f in sc["false_positives"]],
        "consequences": [{"found_id": c["pred_id"], "of": c["of"]} for c in sc["consequences"]],
        "background": [{"found_id": b["pred_id"], "twin_id": b["twin_id"], "twin_start_date": b["twin_start_date"]}
                       for b in sc.get("background", [])],
    }


def refresh_matching(job_id: str, res: dict) -> dict:
    """A detective result saved before `matching` existed: score its events again with the
    current scorer (no placebo, it is kept from the run) and save the result once."""
    from s2d import detective, score

    run = store.job_dir(job_id) / "run"
    twin_path = run / "twin" / "detective.json"
    twin_events = detective.load(twin_path)["events"] if twin_path.exists() else None
    sc = score.score(res["events"], score.load_truth(run), twin_events)
    old = res.get("score") or {}
    res = {**res, "score": _score_summary(sc, old.get("twin_false_events_per_year"), old.get("placebo_p")),
           "matching": matching(sc)}
    store.write_json(store.job_dir(job_id) / "detect_result.json", json.loads(json.dumps(res, default=str)))
    return res


def result_path(job_id: str) -> Path:
    return store.job_dir(job_id) / "result.json"
