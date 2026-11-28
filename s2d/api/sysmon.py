"""Server load for the live "Spec" page: one sample a second into a ring buffer.

CPU, memory and load come from /proc (no psutil, so no new dependency). Inside Docker /proc
shows the host, which is what the page calls "server". The GPU belongs to the Ollama host, which
the API container cannot read, so the model's VRAM comes from Ollama's /api/ps (every few
seconds, 1 s timeout; a failure is "unknown" and never stalls the sampler).
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

PERIOD_S = 1.0
KEEP = 900            # 15 minutes: the chart is already full when the page opens
GPU_PERIOD_S = 5.0
GPU_TIMEOUT_S = 1.0
PROC = Path("/proc")


def read_cpu_times(proc: Path = PROC) -> tuple[int, int] | None:
    """(busy, total) jiffies of all cores, or None without /proc/stat."""
    try:
        first = (proc / "stat").read_text().splitlines()[0].split()
        v = [int(x) for x in first[1:]]
    except (OSError, ValueError, IndexError):
        return None
    idle = v[3] + (v[4] if len(v) > 4 else 0)  # idle + iowait
    return sum(v) - idle, sum(v)


def read_memory(proc: Path = PROC) -> tuple[int, int] | None:
    """(used, total) bytes; used = total - available, as `free` counts it."""
    try:
        kb = {k: int(rest.split()[0]) for k, _, rest in
              (ln.partition(":") for ln in (proc / "meminfo").read_text().splitlines()) if rest.strip()}
        return (kb["MemTotal"] - kb["MemAvailable"]) * 1024, kb["MemTotal"] * 1024
    except (OSError, ValueError, KeyError):
        return None


def read_load(proc: Path = PROC) -> float | None:
    try:
        return float((proc / "loadavg").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def read_gpu() -> dict | None:
    """The loaded Ollama model and its VRAM, or None (not Ollama, down, or too slow)."""
    import httpx

    from s2d import llm
    if llm.backend_name() != "ollama":
        return None
    try:
        ps = httpx.get(f"{llm.ollama_url()}/api/ps", timeout=GPU_TIMEOUT_S).json()
        m = next((x for x in ps.get("models", []) if llm.ollama_model() in (x.get("name"), x.get("model"))), None)
    except (httpx.HTTPError, ValueError):
        return None
    if m is None:
        return {"loaded": False, "vram_gb": 0.0}
    gb = round(int(m.get("size") or 0) / 1e9, 2)  # whole model memory (size), not Ollama's partial size_vram
    return {"loaded": True, "vram_gb": gb, "model_gb": gb}


class Monitor:
    """Samples the server every PERIOD_S. `context()` returns what the pipeline does now:
    {"progress", "step", "customers", "waiting"} (the worker is in main.py, so it is injected)."""

    def __init__(self, context: Callable[[], dict] | None = None, proc: Path = PROC,
                 gpu: Callable[[], dict | None] = read_gpu):
        self.samples: deque[dict] = deque(maxlen=KEEP)
        self._context, self._proc, self._gpu = context or (lambda: {}), proc, gpu
        self._prev = read_cpu_times(proc)
        self._gpu_val: dict | None = None
        self._gpu_at = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        cur = read_cpu_times(self._proc)
        cpu = None
        if cur and self._prev and cur[1] > self._prev[1]:
            cpu = round(100 * (cur[0] - self._prev[0]) / (cur[1] - self._prev[1]), 1)
        self._prev = cur or self._prev
        mem = read_memory(self._proc)
        if now - self._gpu_at >= GPU_PERIOD_S:
            self._gpu_val, self._gpu_at = self._gpu(), now
        ctx = self._context()
        s = {"t": round(now, 1), "cpu": cpu, "mem_gb": round(mem[0] / 1e9, 2) if mem else None,
             "load": read_load(self._proc), "vram_gb": self._gpu_val["vram_gb"] if self._gpu_val else None,
             "progress": ctx.get("progress"), "customers": ctx.get("customers", 0)}
        with self._lock:
            self.samples.append(s)
        return s

    def snapshot(self) -> dict:
        with self._lock:
            samples = list(self.samples)
        mem = read_memory(self._proc)
        ctx = self._context()
        return {"cores": os.cpu_count(), "mem_total_gb": round(mem[1] / 1e9, 1) if mem else None,
                "period_s": PERIOD_S, "gpu": self._gpu_val, "step": ctx.get("step"),
                "customers_now": ctx.get("customers", 0), "waiting": ctx.get("waiting", 0), "samples": samples}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="sysmon", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(PERIOD_S):
            try:
                self.sample()
            except Exception:  # noqa: BLE001 - a bad reading must not end the sampler
                continue
