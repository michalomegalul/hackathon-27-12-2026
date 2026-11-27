"""One worker thread, FIFO: only one job runs at a time (one GPU, one AI call at once).

Queue items are (kind, job_id) with kind "generate" or "detect". The state lives in the
job files, so the queue is rebuilt from them at startup: a job that was running is dead
("server restarted"), queued ones run again in the order they came.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque

from . import pipeline, store

RESTARTED = "server restarted"


class Worker:
    def __init__(self):
        self._cv = threading.Condition()
        self._queue: deque[tuple[str, str]] = deque()
        self.running: tuple[str, str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = False

    # ------------------------------------------------------------ queue

    def submit(self, kind: str, job_id: str) -> int:
        with self._cv:
            self._queue.append((kind, job_id))
            pos = len(self._queue) - 1 + (1 if self.running else 0)
            self._cv.notify()
            return pos

    def ahead(self, kind: str, job_id: str) -> list[tuple[str, str]] | None:
        """Items ahead of this one (the running one first), or None if it is not waiting."""
        with self._cv:
            q = list(self._queue)
            if (kind, job_id) not in q:
                return None
            return ([self.running] if self.running else []) + q[:q.index((kind, job_id))]

    def waiting(self) -> int:
        with self._cv:
            return len(self._queue)

    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------ lifecycle

    def recover(self) -> None:
        """Rebuild the queue from the job files after a (re)start."""
        items = []
        for st in store.all_jobs():
            if st["status"] == "running":
                st.update(status="error", error=RESTARTED, finished=time.time())
                store.save_job(st)
            elif st["status"] == "queued":
                items.append((st["created"], "generate", st["job_id"]))
            d = store.load_detect(st["job_id"])
            if d and d["status"] == "running":
                d.update(status="error", error=RESTARTED, finished=time.time())
                store.save_detect(d)
            elif d and d["status"] == "queued":
                items.append((d["created"], "detect", d["job_id"]))
        for _, kind, jid in sorted(items):
            self.submit(kind, jid)

    def start(self) -> None:
        if self.alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="s2d-api-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 0.0) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._thread and timeout:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                self.running = self._queue.popleft()
            try:
                self._run(*self.running)
            except Exception:  # noqa: BLE001 - the worker must survive anything
                traceback.print_exc()
            finally:
                with self._cv:
                    self.running = None

    def _run(self, kind: str, job_id: str) -> None:
        load, save, fn = ((store.load_job, store.save_job, pipeline.run_generate) if kind == "generate"
                          else (store.load_detect, store.save_detect, pipeline.run_detect))
        state = load(job_id)
        if not state or state["status"] != "queued":
            return
        state.update(status="running", started=time.time())
        save(state)
        try:
            fn(state)
            state.update(status="done", error=None)
        except Exception as e:  # noqa: BLE001 - reported in the job
            state["status"] = "error"
            state["error"] = f"{type(e).__name__}: {e}"[:2000]
            state["traceback"] = traceback.format_exc()[-8000:]
        state["finished"] = time.time()
        save(state)


worker = Worker()
