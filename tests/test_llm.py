"""LLM layer without a GPU: replay needs no network, the Ollama request follows the
hard rules, and the cache is keyed by model."""

import httpx
import pytest

from s2d import llm

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.invalid:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:26b")
    monkeypatch.delenv("OLLAMA_DESKTOP_URL", raising=False)
    monkeypatch.delenv("REPLAY_MODEL", raising=False)
    llm._workers.clear()


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")
    for name in ("get", "post", "request", "stream"):
        monkeypatch.setattr(httpx, name, boom)
    monkeypatch.setattr(httpx.Client, "send", boom)


def test_replay_serves_cache_without_network(no_network, monkeypatch):
    llm.cache_put("spec", "p", SCHEMA, "gemma4:26b", {"x": 1}, {})
    llm.cache_put("texts", "t", None, "gemma4:12b", "ahoj", {})
    monkeypatch.setenv("LLM_BACKEND", "replay")
    assert llm.complete("spec", "p", SCHEMA) == {"x": 1}
    assert llm.last_call().cached and llm.last_call().model == "gemma4:26b"
    # no answer from the preferred model: any cached model will do
    assert llm.complete("texts", "t") == "ahoj"
    assert llm.last_call().model == "gemma4:12b"


def test_replay_miss_raises(no_network, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "replay")
    with pytest.raises(llm.CacheMiss):
        llm.complete("spec", "never seen", SCHEMA)


def test_cache_key_depends_on_every_part():
    base = llm.cache_key("spec", "p", SCHEMA, "m")
    assert base != llm.cache_key("texts", "p", SCHEMA, "m")
    assert base != llm.cache_key("spec", "p2", SCHEMA, "m")
    assert base != llm.cache_key("spec", "p", None, "m")
    assert base != llm.cache_key("spec", "p", SCHEMA, "m2")


class FakeOllama:
    def __init__(self, content='{"x": 3}'):
        self.content = content
        self.posts = []

    def get(self, url, **kw):
        if url.endswith("/api/ps"):
            return httpx.Response(200, json={"models": [
                {"name": "gemma4:26b", "context_length": llm.NUM_CTX}]})
        return httpx.Response(200, json={"models": []})

    def post(self, url, json=None, **kw):
        self.posts.append((url, json, kw))
        return httpx.Response(200, json={"message": {"content": self.content},
                                         "eval_count": 30, "eval_duration": 1e9})


@pytest.fixture
def ollama(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(httpx, "get", fake.get)
    monkeypatch.setattr(httpx, "post", fake.post)
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    return fake


def test_ollama_request_follows_the_rules(ollama):
    assert llm.complete("spec", "p", SCHEMA) == {"x": 3}
    url, body, kw = ollama.posts[0]
    assert url.endswith("/api/chat")
    assert body["options"]["num_ctx"] == 16384
    assert body["options"]["temperature"] == 0.1
    assert body["think"] is False and body["format"] == SCHEMA
    assert body["keep_alive"] == -1 and body["stream"] is False
    assert kw["timeout"].read == 300
    assert not llm.last_call().cold_load and llm.last_call().tokens_per_s == 30


def test_text_step_sampling_and_no_format(ollama):
    ollama.content = "volný text"
    assert llm.complete("texts", "napiš") == "volný text"
    body = ollama.posts[0][1]
    assert body["options"] == {"num_ctx": 16384, "temperature": 1.0, "top_p": 0.95, "top_k": 64}
    assert "format" not in body and "think" not in body


def test_second_call_is_a_cache_hit(ollama):
    llm.complete("spec", "p", SCHEMA)
    llm.complete("spec", "p", SCHEMA)
    assert len(ollama.posts) == 1 and llm.last_call().cached


def test_model_switch_misses_cache(ollama, monkeypatch):
    llm.complete("spec", "p", SCHEMA)
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b")
    llm.complete("spec", "p", SCHEMA)
    assert [p[1]["model"] for p in ollama.posts] == ["gemma4:26b", "gemma4:12b"]


def test_invalid_json_is_an_llm_error(ollama):
    ollama.content = "{not json"
    with pytest.raises(llm.LLMError, match="invalid JSON"):
        llm.complete("spec", "p", SCHEMA)


def test_unreachable_ollama_is_an_llm_error(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    with pytest.raises(llm.LLMError, match="unreachable"):
        llm.complete("spec", "p", SCHEMA)


def test_desktop_worker_skipped_when_down(ollama, monkeypatch):
    monkeypatch.setenv("OLLAMA_DESKTOP_URL", "http://desktop.invalid:11434")

    def get(url, **kw):
        if "desktop" in url:
            raise httpx.ConnectError("off")
        return ollama.get(url, **kw)
    monkeypatch.setattr(httpx, "get", get)
    ollama.content = "text"
    llm.complete("texts", "napiš")
    assert ollama.posts[0][0].startswith("http://ollama.invalid")
