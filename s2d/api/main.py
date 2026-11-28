"""Story2Data HTTP API (contract: docs/API.md).

    uv run uvicorn s2d.api.main:app --port 8000
"""

from __future__ import annotations

import statistics
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from s2d.sim import pg

from . import bundle, pipeline, sandbox, store, sysmon
from . import match as rev_match
from .auth import User, current_user, staff_user
from .worker import worker


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker.recover()
    worker.start()
    monitor.start()
    yield
    monitor.stop()
    worker.stop()


app = FastAPI(title="Story2Data API", version="1.0", lifespan=lifespan,
              description="Company + story → a relational dataset in which the story happened, "
                          "with a statistical proof per event. Contract: docs/API.md.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])


# ---------------------------------------------------------------- models


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str | None = None
    story: str | None = None
    spec_yaml: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    seed: int | None = None
    n_customers: Annotated[int, Field(ge=500, le=pipeline.MAX_CUSTOMERS)] | None = None
    dirt: Literal["none", "low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def _one_input(self):
        if not self.spec_yaml and not ((self.company or "").strip() and (self.story or "").strip()):
            raise ValueError("give company and story, or spec_yaml")
        return self


World = Literal["story", "twin"]
ANALYST_DB = {"story": "analyst.duckdb", "twin": "analyst_twin.duckdb"}


class MatchCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int
    email: Annotated[str, Field(max_length=320)]


class MatchIn(BaseModel):
    """Rev story's fingerprint of uploaded data (the browser reads the ZIP, see s2d/api/match.py)."""
    model_config = ConfigDict(extra="forbid")
    customers: Annotated[int, Field(ge=1)]
    orders: Annotated[int, Field(ge=0)]
    sample: Annotated[list[MatchCustomer], Field(min_length=1, max_length=rev_match.SAMPLE_MAX)]


class QueryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: Annotated[str, Field(min_length=1, max_length=20_000)]
    world: World = "story"


# ---------------------------------------------------------------- helpers


def _visible(state: dict | None, user: User) -> bool:
    return bool(state) and (user.staff or state.get("owner") == user.name)


def _job(job_id: str, user: User) -> dict:
    state = store.load_job(job_id)
    if not _visible(state, user):
        raise HTTPException(404, "job not found")
    return state


def _done(job_id: str, user: User) -> dict:
    state = _job(job_id, user)
    if state["status"] != "done":
        raise HTTPException(409, f"job is {state['status']}, not done"
                            + (f": {state['error']}" if state.get("error") else ""))
    return state


def _queue_eta(kind: str, job_id: str) -> tuple[int, float]:
    """(position, seconds until it starts) of a waiting item; (0, 0) when not waiting."""
    ahead = worker.ahead(kind, job_id)
    if ahead is None:
        return 0, 0.0
    t = store.read_json(store.timings_path()) or {}
    wait = 0.0
    for k, jid in ahead:
        if k == "generate":
            st = store.load_job(jid)
            wait += store.remaining(st, timings=t)[0] if st else 0.0
        else:
            wait += store.detect_remaining(store.load_detect(jid))
    return len(ahead), wait


def _elapsed(state: dict) -> int:
    if not state.get("started"):
        return 0
    return round((state.get("finished") or time.time()) - state["started"])


def status_of(state: dict) -> dict:
    now = time.time()
    left, per = store.remaining(state, now)
    position, wait = _queue_eta("generate", state["job_id"]) if state["status"] == "queued" else (0, 0.0)
    steps, current = [], None
    for i, (st, l) in enumerate(zip(state["steps"], per)):
        if st["done"]:
            steps.append({"name": st["name"], "done": True, "s": st["s"], "note": st.get("note") or ""})
        else:
            steps.append({"name": st["name"], "done": False, "eta_s": round(l)})
            if current is None and state["status"] == "running":
                current = i
    elapsed = _elapsed(state)
    eta = left + wait
    if state["status"] == "done":
        progress, step_index = 1.0, len(store.STEPS)
    else:
        progress = elapsed / (elapsed + eta) if elapsed + eta > 0 else 0.0
        step_index = (current + 1) if current is not None else 0
    return {
        "job_id": state["job_id"], "status": state["status"], "position": position,
        "step": state["steps"][current]["name"] if current is not None else None,
        "step_index": step_index, "steps_total": len(store.STEPS),
        "progress": round(min(progress, 0.99) if state["status"] != "done" else 1.0, 3),
        "elapsed_s": elapsed, "eta_s": round(eta), "steps": steps, "error": state.get("error"),
    }


# ---------------------------------------------------------------- endpoints


@app.get("/v1/health")
def health():
    from s2d import llm
    backend = llm.backend_name()
    if backend == "ollama":
        reachable = bool(llm.ollama_status().get("up"))
    elif backend == "claude":
        reachable = llm.claude_available()
    else:
        reachable = True
    running = worker.running[1] if worker.running else None
    return {"ok": worker.alive(), "llm": {"backend": backend, "model": llm.current_model(), "reachable": reachable},
            "queue": {"running": running, "waiting": worker.waiting()}}


STATS_TTL_S = 5.0
_stats_lock = threading.Lock()
_stats_cache: dict = {"at": 0.0, "value": None}
_job_facts: dict[str, dict] = {}  # per done job, from result.json (which no longer changes)


def _facts(job_id: str) -> dict | None:
    if job_id not in _job_facts:
        res = store.read_json(pipeline.result_path(job_id))
        if res is None:
            return None
        tested = [r for r in res.get("verification") or [] if r.get("status") != "not_testable"]
        twin = [r for r in tested if r.get("twin_confirmed") is not None]
        rows = res.get("rows") or {}
        _job_facts[job_id] = {
            "tested": len(tested), "confirmed": sum(bool(r.get("confirmed")) for r in tested),
            "twin_tested": len(twin), "twin_false": sum(bool(r["twin_confirmed"]) for r in twin),
            "customers": int(rows.get("customers") or 0), "rows": sum(int(v or 0) for v in rows.values()),
            "summary": res.get("summary"),
        }
    return _job_facts[job_id]


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _median_s(xs: list[float]) -> int | None:
    return round(statistics.median(xs)) if xs else None


def _running() -> dict | None:
    item = worker.running
    if not item:
        return None
    kind, jid = item
    if kind == "generate":
        st = store.load_job(jid)
        if not st:
            return None
        s = status_of(st)
        return {"job_id": jid, "step": s["step"], "step_index": s["step_index"],
                "progress": s["progress"], "eta_s": s["eta_s"]}
    d = store.load_detect(jid)
    if not d:
        return None
    left, elapsed = store.detect_remaining(d), _elapsed(d)
    return {"job_id": jid, "step": "detektiv", "step_index": 0,
            "progress": round(min(elapsed / (elapsed + left), 0.99), 3) if elapsed + left else 0.0,
            "eta_s": round(left)}


def _pipeline_now() -> dict:
    """What the pipeline does this second, for the load monitor."""
    r = _running()
    st = store.load_job(r["job_id"]) if r and worker.running and worker.running[0] == "generate" else None
    return {"progress": r["progress"] if r else None, "step": r["step"] if r else None,
            "customers": int((st or {}).get("n_customers") or 0), "waiting": worker.waiting()}


monitor = sysmon.Monitor(_pipeline_now)


def compute_stats(now: float | None = None) -> dict:
    now = now or time.time()
    jobs = store.all_jobs()
    done = [st for st in jobs if st["status"] == "done" and st.get("started") and st.get("finished")]
    facts = {st["job_id"]: f for st in done if (f := _facts(st["job_id"]))}
    total = {k: sum(f[k] for f in facts.values())
             for k in ("tested", "confirmed", "twin_tested", "twin_false", "customers", "rows")}
    today = datetime.fromtimestamp(now).date()
    run_s = {st["job_id"]: st["finished"] - st["started"] for st in done}
    recent = sorted(done, key=lambda st: st["finished"], reverse=True)[:20]
    h0 = datetime.fromtimestamp(now).replace(minute=0, second=0, microsecond=0).timestamp() - 23 * 3600
    timeline = []
    for i in range(24):
        a = h0 + i * 3600
        xs = [run_s[st["job_id"]] for st in done if a <= st["finished"] < a + 3600]
        timeline.append({"hour": store.iso(a), "jobs": len(xs), "median_run_s": _median_s(xs)})
    return {
        "jobs_total": len(jobs), "jobs_done": len(done),
        "jobs_today": sum(datetime.fromtimestamp(st["created"]).date() == today for st in jobs),
        "running": _running(), "waiting": worker.waiting(),
        "median_run_s": _median_s(list(run_s.values())),
        "events_confirmed_pct": _pct(total["confirmed"], total["tested"]),
        "twin_false_pct": _pct(total["twin_false"], total["twin_tested"]),
        "events_tested": total["tested"], "events_confirmed": total["confirmed"],
        "twin_tested": total["twin_tested"], "twin_false": total["twin_false"],
        "customers_simulated": total["customers"], "rows_generated": total["rows"],
        "recent": [{"job_id": st["job_id"], "title": st.get("title", ""), "finished": store.iso(st["finished"]),
                    "elapsed_s": _elapsed(st), "summary": (facts.get(st["job_id"]) or {}).get("summary")}
                   for st in recent],
        "timeline": timeline,
    }


@app.get("/v1/stats")
def stats():
    with _stats_lock:
        if _stats_cache["value"] is None or time.time() - _stats_cache["at"] >= STATS_TTL_S:
            _stats_cache.update(value=compute_stats(), at=time.time())
        return _stats_cache["value"]


@app.get("/v1/system")
def system():
    return monitor.snapshot()


@app.post("/v1/jobs", status_code=202)
def create_job(body: JobIn, user: User = Depends(current_user)):
    params = body.model_dump()
    if body.spec_yaml:
        try:
            spec = pipeline.parse_spec(body.spec_yaml)
        except (ValidationError, ValueError, TypeError) as e:
            from s2d.compiler import format_errors
            msg = format_errors(e) if isinstance(e, ValidationError) else str(e)
            raise HTTPException(400, f"spec_yaml is not a valid spec: {msg}"[:2000]) from None
        params.update(company=None, story=None)
        title = spec.company.name
        params["n_customers"] = params["n_customers"] or spec.entities.customers.n
    else:
        params["spec_yaml"] = None
        title = body.company.strip().splitlines()[0][:60]
    state = store.new_job(user.name, user.role, params, title)
    position = worker.submit("generate", state["job_id"])
    return {"job_id": state["job_id"], "status": "queued", "position": position}


def _story_preview(state: dict) -> str | None:
    story = (state.get("params") or {}).get("story")
    return story.strip()[:120] if story else None


@app.get("/v1/jobs")
def list_jobs(user: User = Depends(current_user), scope: Literal["mine", "all"] = "mine"):
    if scope == "all" and not user.staff:
        raise HTTPException(403, "teacher or admin only")
    every = scope == "all" or user.role == "admin"
    out = []
    for st in store.all_jobs():
        if not (every or st.get("owner") == user.name):
            continue
        res = store.read_json(pipeline.result_path(st["job_id"])) if st["status"] == "done" else None
        out.append({"job_id": st["job_id"], "status": st["status"], "title": st.get("title", ""),
                    "owner": st.get("owner"), "created": store.iso(st["created"]),
                    "elapsed_s": _elapsed(st), "summary": res["summary"] if res else None,
                    "story_preview": _story_preview(st)})
    return {"jobs": out}


@app.post("/v1/jobs/match")
def match_jobs(body: MatchIn, user: User = Depends(current_user)):
    """Which finished jobs (that this user may see) made these data: Rev story's input."""
    seen = [st for st in store.all_jobs() if _visible(st, user)]
    hits = rev_match.find(seen, body.customers, body.orders, [(c.customer_id, c.email) for c in body.sample])
    return {"jobs": [{"job_id": st["job_id"], "title": st.get("title", ""), "created": store.iso(st["created"]),
                      "story_preview": _story_preview(st)} for st in hits]}


@app.get("/v1/jobs/{job_id}")
def job_status(job_id: str, user: User = Depends(current_user)):
    return status_of(_job(job_id, user))


@app.get("/v1/jobs/{job_id}/input")
def job_input(job_id: str, user: User = Depends(current_user)):
    p = _job(job_id, user).get("params") or {}
    return {"company": p.get("company"), "story": p.get("story"), "difficulty": p.get("difficulty"),
            "seed": p.get("seed"), "n_customers": p.get("n_customers"), "dirt": p.get("dirt"),
            "spec_given": bool(p.get("spec_yaml"))}


@app.get("/v1/jobs/{job_id}/result")
def job_result(job_id: str, user: User = Depends(current_user)):
    _done(job_id, user)
    res = store.read_json(pipeline.result_path(job_id))
    if res is None:
        raise HTTPException(404, "result not found")
    return res


_twin_lock = threading.Lock()


def _analyst(job_id: str, user: User, world: World = "story"):
    _done(job_id, user)
    jd = store.job_dir(job_id)
    db = jd / ANALYST_DB[world]
    if world == "twin" and not db.exists():
        # jobs finished before the twin was queryable: build it on the first request
        src = jd / "run" / "twin" / "story.duckdb"
        with _twin_lock:
            if not db.exists() and src.exists():
                sandbox.build_analyst(src, db)
    if not db.exists():
        raise HTTPException(404, "data not found")
    return db


@app.get("/v1/jobs/{job_id}/tables")
def job_tables(job_id: str, user: User = Depends(current_user)):
    tables = sandbox.tables(_analyst(job_id, user))
    fks = pg.foreign_keys(t["name"] for t in tables)
    for t in tables:
        t["primary_key"] = pg.primary_key(t["name"])
        t["foreign_keys"] = [{"column": col, "references": {"table": parent, "column": pcol}}
                             for child, col, parent, pcol in fks if child == t["name"]]
    return {"tables": tables}


@app.get("/v1/jobs/{job_id}/ddl", response_class=PlainTextResponse)
def job_ddl(job_id: str, user: User = Depends(current_user)):
    tables = sandbox.tables(_analyst(job_id, user))
    return pg.ddl({t["name"]: [(c["name"], c["type"]) for c in t["columns"]] for t in tables})


@app.get("/v1/jobs/{job_id}/tables/{name}")
def job_table(job_id: str, name: str, user: User = Depends(current_user),
              limit: Annotated[int, Query(ge=1, le=sandbox.MAX_ROWS)] = 100,
              offset: Annotated[int, Query(ge=0)] = 0, world: World = "story"):
    res = sandbox.page(_analyst(job_id, user, world), name, limit, offset)
    if res is None:
        raise HTTPException(404, "table not found")
    return res


@app.post("/v1/jobs/{job_id}/query")
def job_query(job_id: str, body: QueryIn, user: User = Depends(current_user)):
    db = _analyst(job_id, user, body.world)
    try:
        return sandbox.query(db, body.sql)
    except sandbox.QueryTimeout as e:
        raise HTTPException(408, str(e)) from None
    except sandbox.QueryError as e:
        raise HTTPException(400, str(e)[:2000]) from None


@app.get("/v1/jobs/{job_id}/download")
def job_download(job_id: str, user: User = Depends(current_user)):
    state = _done(job_id, user)
    path = bundle.build_zip(store.job_dir(job_id), job_id, state.get("title") or job_id)
    return FileResponse(path, media_type="application/zip", filename=f"story2data-{job_id}.zip")


def _truth(job_id: str, table: str) -> list[dict]:
    db = store.job_dir(job_id) / "run" / "story.duckdb"
    with duckdb.connect(str(db), read_only=True) as con:
        exists = con.execute("SELECT count(*) FROM information_schema.tables "
                             "WHERE table_schema = '_truth' AND table_name = ?", [table]).fetchone()[0]
        if not exists:
            return []
        cur = con.execute(f'SELECT * FROM _truth."{table}"')
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, (sandbox.jsonable(v) for v in r))) for r in cur.fetchall()]


@app.get("/v1/jobs/{job_id}/answer-key")
def job_answer_key(job_id: str, user: User = Depends(staff_user)):
    _done(job_id, user)
    res = store.read_json(pipeline.result_path(job_id)) or {}
    return {"job_id": job_id, "answer_key": _truth(job_id, "answer_key"), "decoys": _truth(job_id, "decoys"),
            "calibration": _truth(job_id, "calibration"), "verification": res.get("verification", []),
            "spec_yaml": res.get("spec_yaml")}


@app.post("/v1/jobs/{job_id}/detect", status_code=202)
def start_detect(job_id: str, user: User = Depends(current_user)):
    _done(job_id, user)
    d = store.load_detect(job_id)
    if d and d["status"] in ("queued", "running", "done"):
        position = _queue_eta("detect", job_id)[0] if d["status"] == "queued" else 0
        return JSONResponse({"job_id": job_id, "status": d["status"], "position": position}, status_code=202)
    store.save_detect({"job_id": job_id, "kind": "detect", "owner": user.name, "status": "queued",
                       "created": time.time(), "started": None, "finished": None, "error": None})
    (store.job_dir(job_id) / "detect_result.json").unlink(missing_ok=True)
    position = worker.submit("detect", job_id)
    return {"job_id": job_id, "status": "queued", "position": position}


@app.get("/v1/jobs/{job_id}/detect")
def get_detect(job_id: str, user: User = Depends(current_user)):
    _job(job_id, user)
    d = store.load_detect(job_id)
    if not d:
        raise HTTPException(404, "detective not run")
    res = store.read_json(store.job_dir(job_id) / "detect_result.json") if d["status"] == "done" else None
    if res and user.staff and "matching" not in res:
        try:
            res = pipeline.refresh_matching(job_id, res)
        except Exception:  # an old run without its tables: the page pairs the finds itself
            pass
    return {"job_id": job_id, "status": d["status"], "position": _queue_eta("detect", job_id)[0],
            "elapsed_s": _elapsed(d), "error": d.get("error"),
            "events": res["events"] if res else None, "narrative": res["narrative"] if res else None,
            "score": res["score"] if res and user.staff else None,
            "matching": res.get("matching") if res and user.staff else None,
            # the verifier's test of each find (story vs twin, SQL): charts, no answer key in them
            "charts": res.get("charts") if res else None}
