"""Background jobs: a thread does the work, a JSON file in data/jobs/ holds the state.

Cloudflare cuts a request after ~100 s, so nothing long runs inside a Streamlit
rerun. The UI starts a job and a fragment polls its file every 2 s. The file also
survives a page reload: the job id sits in the URL (?job=...).
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable

_lock = threading.Lock()


def jobs_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "jobs"


class Job:
    def __init__(self, job_id: str, kind: str, title: str = ""):
        self.id = job_id
        self.state: dict[str, Any] = {
            "id": job_id, "kind": kind, "title": title, "status": "queued",
            "created": time.time(), "started": None, "finished": None,
            "log": [], "result": None, "error": None,
        }

    @property
    def path(self) -> Path:
        return jobs_dir() / f"{self.id}.json"

    def save(self) -> None:
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, default=str), encoding="utf-8")
            tmp.replace(self.path)

    def log(self, msg: str) -> None:
        self.state["log"].append([round(time.time() - (self.state["started"] or time.time()), 1), msg])
        self.save()


def start(kind: str, fn: Callable[[Job], Any], title: str = "") -> str:
    """Run fn(job) in a daemon thread. Its return value becomes job.result."""
    job = Job(f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}", kind, title)
    job.save()

    def run():
        job.state.update(status="running", started=time.time())
        job.save()
        try:
            job.state["result"] = fn(job)
            job.state["status"] = "done"
        except Exception as e:  # the UI shows it; the thread must not die silently
            job.state["status"] = "error"
            job.state["error"] = f"{type(e).__name__}: {e}"
            job.state["traceback"] = traceback.format_exc()
        job.state["finished"] = time.time()
        job.save()

    threading.Thread(target=run, name=f"job-{job.id}", daemon=True).start()
    return job.id


def read(job_id: str) -> dict | None:
    path = jobs_dir() / f"{job_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def elapsed(state: dict) -> float:
    if not state.get("started"):
        return 0.0
    return (state.get("finished") or time.time()) - state["started"]


def mark_orphans() -> None:
    """Jobs left 'running' by a previous process (container restart) are dead."""
    alive = {t.name.removeprefix("job-") for t in threading.enumerate()}
    for path in jobs_dir().glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if state.get("status") in ("queued", "running") and state["id"] not in alive:
            state.update(status="error", error="interrupted (app restarted)", finished=time.time())
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
