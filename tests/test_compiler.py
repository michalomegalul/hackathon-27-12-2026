"""Spec compiler with a mocked LLM. The fixtures are real gemma4:26b outputs for
the three demo stories in examples/stories/."""

import copy

import pytest
import yaml

from s2d import compiler, llm
from s2d.compiler import compile_story, llm_schema, load_story_file

STORIES = ["pekarna", "kosmetika", "kola"]


def _story(name):
    return load_story_file(f"examples/stories/{name}.yaml")


def _spec(name):
    with open(f"tests/fixtures/spec_{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class FakeLLM:
    """Replaces llm.complete. Hands out the queued responses in order and records calls."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, step, prompt, schema=None, *, backend=None, cache=True, on_status=None):
        self.calls.append({"step": step, "prompt": prompt, "schema": schema, "backend": backend})
        llm._local.info = llm.CallInfo(backend or "ollama", "fake", "test", False, 0.5)
        out = self.responses.pop(0)
        if isinstance(out, Exception):
            raise out
        return copy.deepcopy(out)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BACKEND", "ollama")

    def install(*responses):
        f = FakeLLM(*responses)
        monkeypatch.setattr(compiler.llm, "complete", f)
        return f
    return install


@pytest.mark.parametrize("name", STORIES)
def test_valid_first_try(fake, name):
    f = fake(_spec(name))
    res = compile_story(**_story(name), seed=7)
    assert res.ok and res.first_try_valid and res.retries == 0
    assert res.spec.meta.seed == 7  # the UI seed wins over the model's
    assert res.spec.events
    call = f.calls[0]
    assert call["step"] == "spec" and call["schema"] == llm_schema()
    assert _story(name)["story"].strip() in call["prompt"]
    assert "## Example A" in call["prompt"] and "## Example B" in call["prompt"]


@pytest.mark.parametrize("name", STORIES)
def test_retry_feeds_error_back(fake, name):
    bad = _spec(name)
    bad["events"][0]["target"] = {"segment": ["nikdo"]}
    f = fake(bad, _spec(name))
    res = compile_story(**_story(name))
    assert res.ok and res.retries == 1 and not res.first_try_valid
    assert "unknown segment 'nikdo'" in res.attempts[0].error
    retry = f.calls[1]["prompt"]
    assert "unknown segment 'nikdo'" in retry and "previous spec was rejected" in retry


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["entities"]["customers"]["segments"][0].update(share=0.99), "shares sum"),
    (lambda d: d["events"][0].update(start="2031-01-01"), "outside"),
    (lambda d: d["company"]["cities"][0].update(weight=0.9), "city weights"),
    (lambda d: d.update(events=[]), "events is empty"),
    (lambda d: d["entities"]["products"]["categories"][0].update(zipf_s=2.0), "less than or equal to 1.4"),
])
def test_semantic_errors_are_retried(fake, mutate, message):
    bad = _spec("pekarna")
    mutate(bad)
    fake(bad, _spec("pekarna"))
    res = compile_story(**_story("pekarna"))
    assert res.ok and res.retries == 1
    assert message in res.attempts[0].error


def test_gives_up_after_two_retries_without_claude(fake):
    bad = _spec("kola")
    bad["entities"]["customers"]["segments"][0]["share"] = 0.99
    f = fake(bad, bad, bad)
    res = compile_story(**_story("kola"))
    assert not res.ok and len(res.attempts) == 3
    assert [c["backend"] for c in f.calls] == ["ollama"] * 3


def test_falls_back_to_claude(fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    bad = _spec("kosmetika")
    bad["decoys"] = [{"type": "viral_spike", "date": "1999-01-01", "size": 2}]
    f = fake(bad, bad, bad, _spec("kosmetika"))
    res = compile_story(**_story("kosmetika"))
    assert res.ok and res.retries == 3
    assert [c["backend"] for c in f.calls] == ["ollama", "ollama", "ollama", "claude"]
    assert res.attempts[-1].backend == "claude"


def test_llm_error_counts_as_attempt(fake):
    fake(llm.LLMError("Ollama did not answer within 300 s"), _spec("pekarna"))
    res = compile_story(**_story("pekarna"))
    assert res.ok and res.retries == 1
    assert "300 s" in res.attempts[0].error


def test_replay_miss_stops_immediately(fake, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "replay")
    f = fake(llm.CacheMiss("offline"))
    res = compile_story(**_story("pekarna"))
    assert not res.ok and len(f.calls) == 1


def test_llm_schema_requires_every_key():
    schema = llm_schema()
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["events"]["minItems"] == 1
    event = schema["properties"]["events"]["items"]
    assert "narrative_cs" in event["required"] and "caused_by" in event["required"]


@pytest.mark.parametrize("name", STORIES)
def test_yaml_roundtrip(name):
    spec = compiler.validate(_spec(name))
    assert compiler.validate(yaml.safe_load(compiler.spec_to_yaml(spec))) == spec
