"""One interface for every LLM call: `complete(step, prompt, schema=None)`.

The backend is picked by LLM_BACKEND:

    ollama   OLLAMA_URL + OLLAMA_MODEL (homelab Radeon). If OLLAMA_DESKTOP_URL is set
             and answers GET /api/tags, it also takes bulk text steps.
    claude   ANTHROPIC_API_KEY, model claude-sonnet-5 (ANTHROPIC_MODEL overrides).
    replay   serves cached responses only, never touches the network.

Every response is cached in LLM_CACHE_DIR (default data/llm_cache) under
hash(step, prompt, schema, model). The ollama and claude backends read the cache
first too, so a demo story never waits on the GPU twice.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

NUM_CTX = 16384  # any other value makes Ollama reload the model (~10 s)
TIMEOUT_S = 300
HEALTH_TTL_S = 60
CLAUDE_MODEL = "claude-sonnet-5"

# Sampling per step. Spec and detective want determinism, texts want variety.
STEP_OPTIONS: dict[str, dict[str, float]] = {
    "spec": {"temperature": 0.1},
    "detective": {"temperature": 0.1},
    "texts": {"temperature": 1.0, "top_p": 0.95, "top_k": 64},
}
BULK_STEPS = {"texts"}  # steps the optional desktop worker may take


class LLMError(RuntimeError):
    pass


class CacheMiss(LLMError):
    """Replay backend has no cached answer for this prompt."""


@dataclass
class CallInfo:
    """What the last call on this thread did. The UI shows it."""

    backend: str = ""
    model: str = ""
    host: str = ""
    cached: bool = False
    seconds: float = 0.0
    eval_tokens: int | None = None
    tokens_per_s: float | None = None
    cold_load: bool = False


_local = threading.local()


def last_call() -> CallInfo:
    return getattr(_local, "info", CallInfo())


# ---------------------------------------------------------------- config


def backend_name() -> str:
    return os.environ.get("LLM_BACKEND", "ollama").strip().lower()


def ollama_url() -> str:
    return os.environ.get("OLLAMA_URL", "http://192.168.4.19:11434").rstrip("/")


def ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL", "gemma4:26b")


def claude_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", CLAUDE_MODEL)


def cache_dir() -> Path:
    return Path(os.environ.get("LLM_CACHE_DIR", "data/llm_cache"))


def claude_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def current_model() -> str:
    b = backend_name()
    if b == "claude":
        return claude_model()
    if b == "replay":
        return os.environ.get("REPLAY_MODEL", ollama_model())
    return ollama_model()


def describe() -> str:
    """Short label for the UI, e.g. 'ollama · gemma4:26b'."""
    return f"{backend_name()} · {current_model()}"


# ---------------------------------------------------------------- cache


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(*parts: Any) -> str:
    return hashlib.sha256(_canon(parts).encode("utf-8")).hexdigest()


def cache_key(step: str, prompt: str, schema: dict | None, model: str) -> str:
    return _hash(step, prompt, schema, model)


def _cache_path(step: str, prompt: str, schema: dict | None, model: str) -> Path:
    # File name = <hash without model>_<full hash>, so replay can find an answer
    # cached by any model without knowing which one produced it.
    base = _hash(step, prompt, schema)[:16]
    return cache_dir() / step / f"{base}_{cache_key(step, prompt, schema, model)[:16]}.json"


def cache_get(step: str, prompt: str, schema: dict | None, model: str):
    path = _cache_path(step, prompt, schema, model)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["response"]
    return None


def cache_put(step: str, prompt: str, schema: dict | None, model: str, response, meta: dict) -> None:
    path = _cache_path(step, prompt, schema, model)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"step": step, "model": model, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "meta": meta, "prompt": prompt, "response": response}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def cache_find_any(step: str, prompt: str, schema: dict | None, prefer: str | None = None):
    """Any cached answer for (step, prompt, schema), preferring model `prefer`."""
    if prefer is not None:
        hit = cache_get(step, prompt, schema, prefer)
        if hit is not None:
            return hit, prefer
    base = _hash(step, prompt, schema)[:16]
    for path in sorted((cache_dir() / step).glob(f"{base}_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        return record["response"], record["model"]
    return None, None


# ---------------------------------------------------------------- ollama


@dataclass
class _Worker:
    name: str
    url: str
    model: str
    optional: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    healthy: bool | None = None
    checked_at: float = 0.0

    def is_up(self) -> bool:
        if not self.optional:
            return True
        if self.healthy is None or time.monotonic() - self.checked_at > HEALTH_TTL_S:
            try:
                self.healthy = httpx.get(f"{self.url}/api/tags", timeout=2).status_code == 200
            except httpx.HTTPError:
                self.healthy = False
            self.checked_at = time.monotonic()
        return bool(self.healthy)


_workers: dict[str, _Worker] = {}
_workers_lock = threading.Lock()


def _get_workers() -> list[_Worker]:
    """Primary first, then the desktop worker if configured. Re-read env each time
    so the UI can switch OLLAMA_MODEL without a restart."""
    wanted = [("primary", ollama_url(), ollama_model(), False)]
    desktop = os.environ.get("OLLAMA_DESKTOP_URL", "").rstrip("/")
    if desktop:
        wanted.append(("desktop", desktop, os.environ.get("OLLAMA_DESKTOP_MODEL", "gemma4:12b"), True))
    with _workers_lock:
        out = []
        for name, url, model, optional in wanted:
            w = _workers.get(name)
            if w is None or (w.url, w.model) != (url, model):
                w = _workers[name] = _Worker(name, url, model, optional)
            out.append(w)
        return out


def _acquire_worker(step: str) -> _Worker:
    """Block until a worker is free. Bulk steps may use the desktop; others wait for
    the primary (Ollama runs NUM_PARALLEL=1, so queueing here is honest)."""
    workers = _get_workers()
    if step not in BULK_STEPS:
        workers[0].lock.acquire()
        return workers[0]
    while True:
        for w in workers:
            if w.is_up() and w.lock.acquire(blocking=False):
                return w
        time.sleep(0.2)


def model_loaded(url: str | None = None, model: str | None = None) -> dict | None:
    """The /api/ps entry for `model`, or None if it is not in VRAM (or Ollama is down)."""
    url, model = url or ollama_url(), model or ollama_model()
    try:
        ps = httpx.get(f"{url}/api/ps", timeout=3).json()
    except (httpx.HTTPError, ValueError):
        return None
    for m in ps.get("models", []):
        if m.get("name") == model or m.get("model") == model:
            return m
    return None


def ollama_status() -> dict:
    """For the UI sidebar: is Ollama up, is the model hot, at which context."""
    try:
        version = httpx.get(f"{ollama_url()}/api/version", timeout=3).json().get("version")
    except (httpx.HTTPError, ValueError):
        return {"up": False}
    m = model_loaded()
    return {"up": True, "version": version, "loaded": m is not None,
            "context_length": m.get("context_length") if m else None}


def _ollama_call(w: _Worker, step: str, prompt: str, schema: dict | None,
                 on_status: Callable[[str], None] | None) -> tuple[Any, dict]:
    loaded = model_loaded(w.url, w.model)
    cold = loaded is None or loaded.get("context_length") != NUM_CTX
    if cold and on_status:
        on_status(f"loading {w.model} on {w.name} (cold start, ~10-30 s)")
    body: dict[str, Any] = {
        "model": w.model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": -1,
        "options": {"num_ctx": NUM_CTX, **STEP_OPTIONS.get(step, {"temperature": 0.1})},
    }
    if schema is not None:
        body["think"] = False  # never combine think:true with format
        body["format"] = schema
    try:
        r = httpx.post(f"{w.url}/api/chat", json=body, timeout=httpx.Timeout(TIMEOUT_S, connect=10))
    except httpx.TimeoutException as e:
        raise LLMError(f"Ollama at {w.url} did not answer within {TIMEOUT_S} s") from e
    except httpx.HTTPError as e:
        raise LLMError(f"Ollama at {w.url} unreachable: {e}") from e
    if r.status_code != 200:
        raise LLMError(f"Ollama {r.status_code}: {r.text[:300]}")
    data = r.json()
    text = data["message"]["content"]
    meta = {"host": w.name, "cold_load": cold,
            "eval_tokens": data.get("eval_count"),
            "load_s": (data.get("load_duration") or 0) / 1e9}
    if data.get("eval_count") and data.get("eval_duration"):
        meta["tokens_per_s"] = data["eval_count"] / (data["eval_duration"] / 1e9)
    if schema is None:
        return text, meta
    try:
        return json.loads(text), meta
    except json.JSONDecodeError as e:
        raise LLMError(f"model returned invalid JSON: {e}") from e


# ---------------------------------------------------------------- claude


def _claude_call(step: str, prompt: str, schema: dict | None) -> tuple[Any, dict]:
    import anthropic

    if not claude_available():
        raise LLMError("LLM_BACKEND=claude but ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic(timeout=TIMEOUT_S)
    # Sonnet 5 rejects temperature/top_p/top_k, so step sampling is not sent.
    kwargs: dict[str, Any] = {
        "model": claude_model(),
        "max_tokens": 16000,
        "messages": [{"role": "user", "content": prompt}],
    }
    if schema is not None:
        # A forced, non-strict tool accepts our full JSON Schema (bounds, anyOf
        # defaults); Pydantic validates the result afterwards. Forced tool choice
        # needs thinking off.
        kwargs["tools"] = [{"name": "submit", "description": f"Submit the {step} result.",
                            "input_schema": schema}]
        kwargs["tool_choice"] = {"type": "tool", "name": "submit"}
        kwargs["thinking"] = {"type": "disabled"}
    try:
        msg = client.messages.create(**kwargs)
    except anthropic.APIConnectionError as e:
        raise LLMError(f"Claude unreachable: {e}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Claude {e.status_code}: {e.message}") from e
    if msg.stop_reason == "refusal":
        raise LLMError("Claude refused the request")
    meta = {"host": "anthropic", "eval_tokens": msg.usage.output_tokens}
    if schema is not None:
        for block in msg.content:
            if block.type == "tool_use":
                return block.input, meta
        raise LLMError(f"Claude did not call the tool (stop_reason={msg.stop_reason})")
    return "".join(b.text for b in msg.content if b.type == "text"), meta


# ---------------------------------------------------------------- the interface


def complete(step: str, prompt: str, schema: dict | None = None, *,
             backend: str | None = None, cache: bool = True,
             on_status: Callable[[str], None] | None = None) -> dict | str:
    """Run one LLM step. Returns parsed JSON (dict) when `schema` is given, else text.

    `backend` overrides LLM_BACKEND for this call (the compiler uses it to fall
    back to claude). `cache=False` skips the cache read but still writes.
    """
    b = backend or backend_name()
    t0 = time.perf_counter()

    if b == "replay":
        hit, model = cache_find_any(step, prompt, schema, prefer=current_model())
        if hit is None:
            raise CacheMiss("offline: no cached answer for this prompt (cached stories only)")
        _local.info = CallInfo("replay", model, "cache", True, time.perf_counter() - t0)
        return hit

    if b == "ollama":
        workers = _get_workers()
        models = [w.model for w in (workers if step in BULK_STEPS else workers[:1])]
    elif b == "claude":
        models = [claude_model()]
    else:
        raise LLMError(f"unknown LLM_BACKEND {b!r} (ollama | claude | replay)")

    if cache:  # before taking a worker, so cache hits never queue behind the GPU
        for model in models:
            hit = cache_get(step, prompt, schema, model)
            if hit is not None:
                _local.info = CallInfo(b, model, "cache", True, time.perf_counter() - t0)
                return hit

    worker = _acquire_worker(step) if b == "ollama" else None
    model = worker.model if worker else models[0]
    try:
        if worker is not None:
            response, meta = _ollama_call(worker, step, prompt, schema, on_status)
        else:
            response, meta = _claude_call(step, prompt, schema)
    finally:
        if worker is not None:
            worker.lock.release()

    seconds = time.perf_counter() - t0
    meta["seconds"] = round(seconds, 2)
    cache_put(step, prompt, schema, model, response, meta)
    _local.info = CallInfo(b, model, meta.get("host", ""), False, seconds,
                           meta.get("eval_tokens"), meta.get("tokens_per_s"),
                           bool(meta.get("cold_load")))
    return response


def warm() -> None:
    """Load the primary model at NUM_CTX and pin it (keep_alive -1). Safe to repeat."""
    httpx.post(f"{ollama_url()}/api/generate",
               json={"model": ollama_model(), "prompt": "", "keep_alive": -1,
                     "options": {"num_ctx": NUM_CTX}},
               timeout=TIMEOUT_S)
