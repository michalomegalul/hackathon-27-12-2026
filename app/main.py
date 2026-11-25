"""Story2Data UI: Story -> Spec -> Data -> Detective -> Score.

    uv run streamlit run app/main.py

Every slow step (LLM, simulation) runs as a background job (app/jobs.py) and a
fragment polls it, because Cloudflare drops requests that take over ~100 s.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import yaml  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import jobs  # noqa: E402
from s2d import llm  # noqa: E402
from s2d.compiler import compile_story, format_errors, load_story_file  # noqa: E402
from s2d.spec import StorySpec  # noqa: E402

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
STORIES = sorted((ROOT / "examples" / "stories").glob("*.yaml"))
MODELS = ["gemma4:26b", "gemma4:12b"]

st.set_page_config(page_title="Story2Data", layout="wide")


@st.cache_resource
def _startup() -> bool:
    jobs.mark_orphans()
    return True


_startup()
ss = st.session_state
ss.setdefault("spec_yaml", "")
ss.setdefault("seen_jobs", set())


# ---------------------------------------------------------------- job runners


def run_compile(company: str, story: str, seed: int | None):
    def work(job: jobs.Job):
        job.log(f"{llm.describe()}: compiling")
        res = compile_story(company, story, seed=seed, on_status=job.log)
        attempts = [a.__dict__ for a in res.attempts]
        if not res.ok:
            raise RuntimeError("no valid spec after retries:\n" + "\n".join(a["error"] for a in attempts))
        job.log(f"valid spec after {len(attempts)} attempt(s)")
        return {"yaml": res.yaml(), "attempts": attempts, "retries": res.retries,
                "first_try_valid": res.first_try_valid}
    return jobs.start("compile", work, title="Story to spec")


def run_sim(spec_yaml: str, n_customers: int | None):
    def work(job: jobs.Job):
        from s2d.sim import simulate, without_story
        from s2d.sim.output import write_world

        spec = StorySpec.model_validate(yaml.safe_load(spec_yaml))
        if n_customers:
            spec.entities.customers.n = n_customers
        job.log(f"simulating {spec.meta.days} days, {spec.entities.customers.n} customers")
        t0 = time.perf_counter()
        table = None
        if spec.events:
            from s2d.calibrate import calibrate, format_table
            job.log("recoverability gate: measuring every event in noise units")
            spec, table = calibrate(spec, log=job.log)
            job.log(format_table(table))
        world = simulate(spec)
        if table is not None:
            world.truth["calibration"] = table
        for reason in world.story.skipped:
            job.log(f"skipped {reason}")
        out = DATA_DIR / "runs" / job.id
        db = write_world(world, out)
        job.log("no-story twin (same seed, no events)")
        write_world(simulate(without_story(spec)), out / "twin")
        from s2d import verify
        job.log("verification: one test per event, story and twin")
        ver = verify.verify(out, out / "twin")
        (out / "verify.json").write_text(json.dumps(ver, ensure_ascii=False, default=str), "utf-8")
        job.log(verify.summary_line(ver))
        job.log(f"done in {time.perf_counter() - t0:.1f} s")
        return {"dir": str(out), "db": str(db), "twin": str(out / "twin"),
                "rows": {name: len(df) for name, df in world.tables.items()},
                "skipped": list(world.story.skipped)}
    return jobs.start("sim", work, title="Simulation")


def run_detective(run_dir: str, twin_dir: str | None):
    def work(job: jobs.Job):
        from s2d import detective, score

        res = detective.run(run_dir, narrate=True, on_status=job.log)
        detective.save(res, Path(run_dir) / "detective.json")
        job.log(f"{len(res['events'])} events, scan {res['timing']['scan_s']} s")
        if twin_dir and Path(twin_dir).exists():
            job.log("same scan on the no-story twin")
            tw = detective.run(twin_dir, narrate=False)
            detective.save(tw, Path(twin_dir) / "detective.json")
        job.log("scoring against the answer key")
        card = score.scorecard(run_dir, twin_dir if twin_dir and Path(twin_dir).exists() else None)
        (Path(run_dir) / "scorecard.json").write_text(json.dumps(card, ensure_ascii=False, default=str), "utf-8")
        return {"run_dir": run_dir}
    return jobs.start("detective", work, title="Detective")


def _set_job(slot: str, job_id: str) -> None:
    ss[slot] = job_id
    st.query_params[slot] = job_id


def _job_id(slot: str) -> str | None:
    return ss.get(slot) or st.query_params.get(slot)


@st.fragment(run_every=2)
def job_panel(slot: str) -> None:
    """Poll one job. On the first poll after it finishes, rerun the whole app so
    the other tabs pick up the result."""
    job_id = _job_id(slot)
    if not job_id:
        return
    state = jobs.read(job_id)
    if state is None:
        st.caption(f"job {job_id} not found")
        return
    status = state["status"]
    line = f"{state['title']}: {status}, {jobs.elapsed(state):.0f} s"
    if status in ("queued", "running"):
        st.info(line)
    elif status == "done":
        st.success(line)
    else:
        st.error(f"{line}. {state.get('error', '')}")
    if state["log"]:
        st.code("\n".join(f"{t:>6.1f}s  {m}" for t, m in state["log"][-12:]), language=None)
    if status in ("done", "error") and job_id not in ss.seen_jobs:
        ss.seen_jobs.add(job_id)
        if status == "done" and slot == "compile_job":
            ss.spec_yaml = state["result"]["yaml"]
            ss.spec_editor = ss.spec_yaml
        st.rerun(scope="app")


# ---------------------------------------------------------------- sidebar


with st.sidebar:
    st.subheader("LLM")
    backends = ["ollama", "claude", "replay"]
    backend = st.selectbox("Backend", backends, index=backends.index(llm.backend_name())
                           if llm.backend_name() in backends else 0)
    os.environ["LLM_BACKEND"] = backend
    if backend == "ollama":
        current = llm.ollama_model()
        model = st.selectbox("Model", MODELS if current in MODELS else [current, *MODELS],
                             index=(MODELS if current in MODELS else [current, *MODELS]).index(current),
                             help="Only one model fits in VRAM. Switching costs a ~10 s reload.")
        os.environ["OLLAMA_MODEL"] = model
        status = llm.ollama_status()
        if not status["up"]:
            st.error(f"Ollama unreachable at {llm.ollama_url()}")
        else:
            hot = "in VRAM" if status["loaded"] else "not loaded (first call loads it)"
            st.caption(f"Ollama {status['version']} at {llm.ollama_url()}  \n{model}: {hot}"
                       + (f", ctx {status['context_length']}" if status["context_length"] else ""))
        if os.environ.get("OLLAMA_DESKTOP_URL"):
            st.caption(f"Desktop worker: {os.environ['OLLAMA_DESKTOP_URL']} (texts only, skipped when down)")
    elif backend == "claude":
        st.caption(f"Model {llm.claude_model()}  \n"
                   + ("API key set" if llm.claude_available() else "ANTHROPIC_API_KEY is not set"))
    else:
        st.caption("Offline. Only cached stories work.")
    st.caption(f"In use: {llm.describe()}")
    if backend != "claude":
        st.caption("Claude fallback: " + ("on" if llm.claude_available() else "off (no key)"))


# ---------------------------------------------------------------- tabs


st.title("Story2Data")
t_story, t_spec, t_data, t_detective, t_score = st.tabs(["Story", "Spec", "Data", "Detective", "Score"])

with t_story:
    names = ["(own story)"] + [yaml.safe_load(p.read_text("utf-8")).get("title", p.stem) for p in STORIES]
    pick = st.selectbox("Demo story", names, key="demo_story")
    preset = load_story_file(STORIES[names.index(pick) - 1]) if pick != "(own story)" else {"company": "", "story": ""}
    company = st.text_area("Company (Czech)", preset["company"], height=120, key=f"company_{pick}")
    story = st.text_area("Story (Czech)", preset["story"], height=160, key=f"story_{pick}")
    col1, col2 = st.columns([1, 3])
    seed = col1.number_input("Seed", value=42, step=1)
    running = (s := jobs.read(_job_id("compile_job") or "")) and s["status"] in ("queued", "running")
    if col2.button("Compile spec", type="primary", disabled=bool(running) or not company.strip() or not story.strip()):
        _set_job("compile_job", run_compile(company, story, int(seed)))
    job_panel("compile_job")
    state = jobs.read(_job_id("compile_job") or "")
    if state and state["status"] == "done":
        r = state["result"]
        st.write(f"Retries: {r['retries']}. Valid on first try: {'yes' if r['first_try_valid'] else 'no'}.")
        st.dataframe([{k: a[k] for k in ("backend", "model", "seconds", "ok", "cached", "tokens_per_s", "error")}
                      for a in r["attempts"]], hide_index=True)

with t_spec:
    if not ss.spec_yaml:
        st.write("Compile a story first, or paste a spec below.")
    ss.setdefault("spec_editor", ss.spec_yaml)
    text = st.text_area("Spec (YAML, editable)", key="spec_editor", height=600)
    c1, c2 = st.columns([1, 5])
    if c1.button("Validate"):
        try:
            spec = StorySpec.model_validate(yaml.safe_load(text))
            ss.spec_yaml = text
            st.success(f"Valid: {len(spec.events)} events, {len(spec.decoys)} decoys, "
                       f"{spec.meta.start} + {spec.meta.days} days.")
        except ValidationError as e:
            st.error(format_errors(e))
        except (yaml.YAMLError, ValueError) as e:
            st.error(str(e))
    c2.download_button("Download spec.yaml", text, file_name="spec.yaml", disabled=not text)

with t_data:
    if not ss.spec_yaml:
        st.write("Validate a spec first.")
    else:
        n = st.number_input("Customers (0 = from spec)", value=40000, step=1000, min_value=0)
        sim_state = jobs.read(_job_id("sim_job") or "")
        busy = sim_state and sim_state["status"] in ("queued", "running")
        if st.button("Simulate", type="primary", disabled=bool(busy)):
            _set_job("sim_job", run_sim(ss.spec_yaml, int(n) or None))
        job_panel("sim_job")
        if sim_state and sim_state["status"] == "done":
            r = sim_state["result"]
            st.dataframe([{"table": k, "rows": v} for k, v in r["rows"].items()], hide_index=True)
            orders = Path(r["dir"]) / "orders.parquet"
            if orders.exists():
                daily = duckdb.sql(f"select order_date, count(*) as orders from '{orders}' "
                                   "group by 1 order by 1").df()
                st.line_chart(daily, x="order_date", y="orders")

def _run_dir() -> str | None:
    sim_state = jobs.read(_job_id("sim_job") or "")
    if sim_state and sim_state["status"] == "done":
        return sim_state["result"]["dir"]
    return None


def _event_chart(run_dir: str, events: list[dict], truth: list[dict] | None = None):
    """KPI series of the events, with dashed lines at detected starts and solid red
    lines at the true start + lag (Score tab only)."""
    import altair as alt
    from s2d import detective

    names = list(dict.fromkeys(e["series"] for e in events))[:6]
    if not names:
        return None
    df = detective.series_frame(run_dir, names)
    if df.empty:
        return None
    long = df.rolling(7, center=True, min_periods=1).mean().reset_index(names="date").melt(
        "date", var_name="series", value_name="value (7-day mean)")
    base = alt.Chart(long).mark_line().encode(x="date:T", y="value (7-day mean):Q", color="series:N")
    rules = [alt.Chart(pd.DataFrame({"date": pd.to_datetime([e["start_date"] for e in events]),
                                     "id": [e["id"] for e in events]}))
             .mark_rule(strokeDash=[4, 3], color="#555").encode(x="date:T", tooltip=["id", "date:T"])]
    if truth:
        t = pd.DataFrame(truth)
        t["date"] = pd.to_datetime(t["start_date"]) + pd.to_timedelta(t["lag_days"].fillna(0), unit="D")
        rules.append(alt.Chart(t).mark_rule(color="#c0392b").encode(x="date:T", tooltip=["event_id", "date:T"]))
    return alt.layer(base, *rules).properties(height=360)


with t_detective:
    run_dir = _run_dir()
    if not run_dir:
        st.write("Simulate data first.")
    else:
        st.caption("The detective reads only the analyst tables. It never sees the spec, the seed or the answer key.")
        det_state = jobs.read(_job_id("det_job") or "")
        busy = det_state and det_state["status"] in ("queued", "running")
        if st.button("Run detective", type="primary", disabled=bool(busy)):
            twin = str(Path(run_dir) / "twin")
            _set_job("det_job", run_detective(run_dir, twin))
        job_panel("det_job")
        det_path = Path(run_dir) / "detective.json"
        if det_path.exists():
            from s2d import detective
            res = detective.load(det_path)
            st.write(f"{res['n_series']} series, {len(res['candidates'])} candidates, "
                     f"{len(res['events'])} events. Scan {res['timing']['total_s']} s.")
            chart = _event_chart(run_dir, res["events"])
            if chart is not None:
                st.altair_chart(chart, width="stretch")
            if "narration" in res:
                st.subheader("Příběh podle dat")
                st.write(res["narration"]["narrative_cs"])
                st.caption(f"Narrator: {res['narration']['source']}")
            cols = ["id", "metric", "segment", "start_date", "end_date", "direction", "magnitude_pct",
                    "lag_days", "caused_by", "kind", "confidence", "evidence"]
            st.dataframe(pd.DataFrame(res["events"], columns=cols), hide_index=True)
            with st.expander("All candidates, including rejected ones"):
                st.dataframe(pd.DataFrame(res["candidates"])[cols + ["status"]], hide_index=True)

def _verify_chart(r: dict):
    """Treated series and the control scaled to the treated level before T (7-day means),
    with the before and after windows shaded."""
    import altair as alt

    sr = r["series"]
    df = pd.DataFrame({"date": pd.to_datetime(sr["day"]), "cílová skupina": sr["treated"]})
    b0, b1 = pd.Timestamp(r["before"][0]), pd.Timestamp(r["before"][1])
    if sr["control"] is not None:
        ctl = pd.Series(sr["control"], index=df.index)
        in_before = (df["date"] >= b0) & (df["date"] <= b1)
        scale = df.loc[in_before, "cílová skupina"].mean() / max(ctl[in_before].mean(), 1e-9)
        df["kontrola (přeškálovaná)"] = ctl * scale
    long = df.set_index("date").rolling(7, center=True, min_periods=1).mean().reset_index().melt(
        "date", var_name="řada", value_name="7denní průměr")
    lines = alt.Chart(long).mark_line().encode(x="date:T", y="7denní průměr:Q",
                                               color=alt.Color("řada:N", legend=alt.Legend(orient="bottom")))
    win = pd.DataFrame({"start": pd.to_datetime([r["before"][0], r["after"][0]]),
                        "end": pd.to_datetime([r["before"][1], r["after"][1]]),
                        "okno": ["před", "po"]})
    band = alt.Chart(win).mark_rect(opacity=0.15).encode(
        x="start:T", x2="end:T", color=alt.Color("okno:N", scale=alt.Scale(range=["#888", "#c0392b"]), legend=None))
    return alt.layer(band, lines).properties(height=260)


def _verify_section(run_dir: str) -> None:
    path = Path(run_dir) / "verify.json"
    if not path.exists():
        st.write("No verification for this run (simulate again).")
        return
    ver = json.loads(path.read_text("utf-8"))
    st.subheader("Ověření příběhu")
    c1, c2 = st.columns(2)
    c1.metric("Příběh: potvrzeno", f"{ver['confirmed']}/{ver['n']}")
    if "twin_confirmed" in ver:
        c2.metric("Dvojče bez příběhu: potvrzeno", f"{ver['twin_confirmed']}/{ver['n']}",
                  help="the same tests on a run with the same seed and no events: should be 0")
    st.caption("One test per event, built from the event itself: its KPI in its target vs the other values "
               "of the same dimension, 28 days after start + lag vs 28 before. Confirmed = 95 % CI excludes 0, "
               "direction as in the story, placebo z ≥ 3.")

    def fmt(v):
        return "–" if v is None else f"{v:+.1f} %"
    rows = []
    for r in ver["tests"]:
        tw = r.get("twin", {})
        rows.append({
            "událost": r["event_id"], "tvrzení": r["claim_cs"],
            "test": f"{r['kpi']} · {r['segment'] or 'všichni'} · od {r['T']}",
            "příběh": fmt(r["story_pct"]), "v okně": fmt(r["expected_pct"]),
            "naměřeno": fmt(r.get("measured_pct")),
            "95% CI": (f"[{r['ci_pct'][0]:+.1f}, {r['ci_pct'][1]:+.1f}]" if r.get("ci_pct") else "–"),
            "z": r.get("z"), "p (placebo)": r.get("p_placebo"),
            "příběh ✓": "✅" if r["confirmed"] else "❌",
            "dvojče z": tw.get("z"), "dvojče ✓": ("✅" if tw.get("confirmed") else "❌") if tw else "",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    from s2d import verify
    st.write(ver["narration"]["text"] if "narration" in ver else verify.narrative_cs(ver))
    st.caption("Only confirmed events are told. " + (f"Narrator: {ver['narration']['source']}"
                                                      if "narration" in ver else "Template, no LLM."))
    for r in ver["tests"]:
        if "series" not in r:
            continue
        mark = "✅" if r["confirmed"] else "❌"
        with st.expander(f"{mark} {r['event_id']}: {r['claim_cs']}"):
            st.altair_chart(_verify_chart(r), width="stretch")
            if "price" in r:
                st.write(f"Ceny dotčených produktů: {fmt(r['price']['measured_pct'])} "
                         f"(příběh {fmt(r['price']['story_pct'])}, {r['price']['products']} produktů)")
            ok = "same DiD as the test" if r.get("sql_matches") else "DIFFERENT from the test"
            st.caption(f"Run it on story.duckdb (DuckDB). Gives did_pct = {r['sql_result']['did_pct']:+.2f} %: {ok}.")
            st.code(r["sql"], language="sql")
            if "price" in r:
                st.code(r["price"]["sql"], language="sql")


def _detective_section(run_dir: str, card_path: Path) -> None:
    if not card_path.exists():
        st.write("Run the detective (Detective tab) to score it.")
        return
    card = json.loads(card_path.read_text("utf-8"))
    sc = card["score"]
    c1, c2, c3, c4 = st.columns(4)
    has_cons = "precision_cons" in sc  # scorecards written before the consequence status
    c1.metric("Precision", f"{sc['precision']:.2f}",
              help="strict: every unmatched detection is a false positive")
    if has_cons:
        c1.caption(f"s důsledky: {sc['precision_cons']:.2f}")
    c2.metric("Recall", f"{sc['recall']:.2f}")
    c3.metric("F1", f"{sc['f1']:.2f}")
    if has_cons:
        c3.caption(f"s důsledky: {sc['f1_cons']:.2f}")
    if "twin" in card:
        c4.metric("Twin: false events / year", card["twin"]["false_events_per_year"])
    st.caption(f"Placebo (200 shuffles of the answer-key dates): p = {card['placebo']['p_value']}. "
               f"Bonus caused_by: {sc['caused_by_bonus']['hit']}/{sc['caused_by_bonus']['possible']}.")

    by_true = {m["event_id"]: m for m in sc["matches"]}
    events = {e["id"]: e for e in card["events"]}
    rows = []
    for t in card["answer_key"]:
        m = by_true.get(t["event_id"])
        e = events.get(m["pred_id"]) if m else None
        rows.append({
            "event": t["event_id"], "true": f"{t['metric']} {t['direction']} {t['segment']}",
            "true start+lag": str((pd.Timestamp(t["start_date"]) + pd.Timedelta(days=int(t["lag_days"] or 0))).date()),
            "true size %": t["magnitude_pct"],
            "found": f"{e['id']} {e['segment'] or 'vše'}" if e else ("not simulated" if not t["simulated"] else "missed"),
            "date": m["timing"] if m else None, "segment": m["segment"] if m else None,
            "magnitude": m["magnitude"] if m else None, "lag": m["lag"] if m else None,
            "score": m["score"] if m else None})
    table = pd.DataFrame(rows)

    def color(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return "background-color: #d5f0d5" if v >= 0.5 else "background-color: #f6d5d5"
    st.dataframe(table.style.map(color, subset=["date", "segment", "magnitude", "lag", "score"]),
                 hide_index=True)
    if sc.get("consequences"):
        st.write("Důsledky (consequences of a matched event: neither TP nor FP in the second variant)")
        st.dataframe(pd.DataFrame(sc["consequences"]), hide_index=True)
    if sc["false_positives"]:
        st.write("False positives")
        st.dataframe(pd.DataFrame(sc["false_positives"]), hide_index=True)
    chart = _event_chart(run_dir, card["events"], card["answer_key"])
    if chart is not None:
        st.altair_chart(chart, width="stretch")
    st.write("Placebo F1 distribution (random answer-key dates) vs the real F1")
    hist = pd.Series(card["placebo"]["placebo_f1"]).value_counts().sort_index()
    st.bar_chart(hist.rename_axis("F1").rename("count"))


with t_score:
    run_dir = _run_dir()
    if not run_dir:
        st.write("Simulate data first.")
    else:
        _verify_section(run_dir)
        st.divider()
        st.subheader("Slepý detektiv (bonus)")
        st.caption("Hard mode: the detective searches every KPI and segment without the answer key.")
        _detective_section(run_dir, Path(run_dir) / "scorecard.json")
