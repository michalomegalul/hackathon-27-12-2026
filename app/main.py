"""Story2Data UI: Story -> Spec -> Data -> Detective -> Score.

    uv run streamlit run app/main.py

Every slow step (LLM, simulation) runs as a background job (app/jobs.py) and a
fragment polls it, because Cloudflare drops requests that take over ~100 s.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402
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
        from s2d.sim import simulate
        from s2d.sim.output import write_world

        spec = StorySpec.model_validate(yaml.safe_load(spec_yaml))
        if n_customers:
            spec.entities.customers.n = n_customers
        job.log(f"simulating {spec.meta.days} days, {spec.entities.customers.n} customers")
        t0 = time.perf_counter()
        world = simulate(spec)
        for reason in world.story.skipped:
            job.log(f"skipped {reason}")
        out = DATA_DIR / "runs" / job.id
        db = write_world(world, out)
        job.log(f"done in {time.perf_counter() - t0:.1f} s")
        return {"dir": str(out), "db": str(db),
                "rows": {name: len(df) for name, df in world.tables.items()},
                "skipped": list(world.story.skipped)}
    return jobs.start("sim", work, title="Simulation")


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
        n = st.number_input("Customers (0 = from spec)", value=0, step=1000, min_value=0)
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

with t_detective:
    st.write("Detective: not built yet. It will read only the analyst tables and propose events.")

with t_score:
    st.write("Score: not built yet. It will match detected events against the answer key.")
