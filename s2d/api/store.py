"""Job files and step timings.

    $DATA_DIR/api/jobs/<id>/job.json      state of a generate job (status, steps, params)
    $DATA_DIR/api/jobs/<id>/detect.json   state of its detective run, if one was asked for
    $DATA_DIR/api/jobs/<id>/run/          the simulated world (story.duckdb, twin/, verify.json)
    $DATA_DIR/api/jobs/<id>/result.json   what GET /result returns
    $DATA_DIR/api/jobs/<id>/analyst.duckdb  main schema only, for /query, /tables and the ZIP
    $DATA_DIR/api/jobs/<id>/analyst_twin.duckdb  the same of run/twin/, for "world": "twin"
    $DATA_DIR/api/timings.json            seconds of earlier runs per step, for the ETA

Everything is a file, so a restart loses nothing but the running job.
"""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

STEPS = ["specifikace (AI)", "kalibrace a simulace", "dvojče bez příběhu", "ověření", "český příběh (AI)"]
# no history yet: (fixed seconds, seconds per customer), measured on the notebook (DECISIONS 94).
# The simulation steps grow with the customer count; calibration also has a fixed part.
PRIORS = {"specifikace (AI)": (35.0, 0.0), "kalibrace a simulace": (12.0, 2e-3),
          "dvojče bez příběhu": (0.3, 1.5e-4), "ověření": (0.3, 3e-5), "český příběh (AI)": (15.0, 0.0)}
DETECT_PRIOR_S = 40.0
DEFAULT_N = 20_000   # customer count to assume before the spec is known
HISTORY = 30         # timings kept per step

_lock = threading.RLock()


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data"))


def api_dir() -> Path:
    return data_dir() / "api"


def jobs_dir() -> Path:
    return api_dir() / "jobs"


def job_dir(job_id: str) -> Path:
    return jobs_dir() / job_id


def new_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- JSON files


def write_json(path: Path, obj: Any) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(path)


def read_json(path: Path) -> Any | None:
    with _lock:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def load_job(job_id: str) -> dict | None:
    if not job_id or "/" in job_id or job_id.startswith("."):
        return None
    return read_json(job_dir(job_id) / "job.json")


def save_job(state: dict) -> None:
    write_json(job_dir(state["job_id"]) / "job.json", state)


def load_detect(job_id: str) -> dict | None:
    return read_json(job_dir(job_id) / "detect.json")


def save_detect(state: dict) -> None:
    write_json(job_dir(state["job_id"]) / "detect.json", state)


def all_jobs() -> list[dict]:
    out = []
    if jobs_dir().exists():
        for p in jobs_dir().iterdir():
            s = read_json(p / "job.json")
            if s:
                out.append(s)
    return sorted(out, key=lambda s: s["created"], reverse=True)


def new_job(owner: str, role: str, params: dict, title: str) -> dict:
    steps = [{"name": n, "done": False, "s": None, "note": "", "started": None} for n in STEPS]
    if params.get("spec_yaml"):
        steps[0].update(done=True, s=0, note="spec zadán (bez AI)")
    state = {"job_id": new_id(), "kind": "generate", "owner": owner, "role": role, "title": title,
             "status": "queued", "created": time.time(), "started": None, "finished": None,
             "params": params, "n_customers": params.get("n_customers") or None,
             "steps": steps, "error": None, "log": []}
    save_job(state)
    return state


# ---------------------------------------------------------------- timings and ETA


def timings_path() -> Path:
    return api_dir() / "timings.json"


def record_timing(step: str, seconds: float, n: int) -> None:
    with _lock:
        t = read_json(timings_path()) or {}
        t.setdefault(step, []).append({"s": round(seconds, 2), "n": int(n), "at": int(time.time())})
        t[step] = t[step][-HISTORY:]
        write_json(timings_path(), t)


def prior(step: str, n: int) -> float:
    fixed, per = PRIORS[step]
    return fixed + per * n


def estimate(step: str, n: int | None, timings: dict | None = None) -> float:
    """Seconds one step should take: the prior's shape (fixed + per customer) scaled by the
    median of earlier runs' measured / prior, so a 40k run teaches the estimate for 10k."""
    n = n or DEFAULT_N
    hist = (timings if timings is not None else read_json(timings_path()) or {}).get(step) or []
    ratios = [h["s"] / prior(step, h.get("n") or DEFAULT_N) for h in hist]
    return prior(step, n) * (statistics.median(ratios) if ratios else 1.0)


def remaining(state: dict, now: float | None = None, timings: dict | None = None) -> tuple[float, list[float]]:
    """(seconds left for the job, seconds left per step) for a generate job."""
    if state["status"] in ("done", "error"):
        return 0.0, [0.0] * len(STEPS)
    now = now or time.time()
    timings = timings if timings is not None else read_json(timings_path()) or {}
    left = []
    for st in state["steps"]:
        if st["done"]:
            left.append(0.0)
            continue
        est = estimate(st["name"], state.get("n_customers"), timings)
        if st.get("started"):
            est = max(est - (now - st["started"]), 1.0)
        left.append(est)
    return sum(left), left


def detect_remaining(state: dict | None, now: float | None = None) -> float:
    if not state or state["status"] in ("done", "error"):
        return 0.0
    if state.get("started"):
        return max(DETECT_PRIOR_S - ((now or time.time()) - state["started"]), 1.0)
    return DETECT_PRIOR_S
