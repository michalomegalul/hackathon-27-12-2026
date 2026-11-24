"""Against the real homelab Ollama. Skipped when it cannot be reached.

    uv run pytest -m integration -s
"""


import httpx
import pytest

from s2d import llm
from s2d.compiler import compile_story, load_story_file

pytestmark = pytest.mark.integration


def _reachable() -> bool:
    try:
        return httpx.get(f"{llm.ollama_url()}/api/version", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(autouse=True)
def real_ollama(tmp_path, monkeypatch):
    if not _reachable():
        pytest.skip(f"Ollama not reachable at {llm.ollama_url()}")
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))  # fresh cache: really hit the GPU
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_schema_call():
    out = llm.complete("spec", "Vrať JSON: mesto = hlavní město České republiky.",
                       {"type": "object", "properties": {"mesto": {"type": "string"}}, "required": ["mesto"]})
    assert out["mesto"].startswith("Praha")
    assert not llm.last_call().cached


def test_compile_demo_story():
    res = compile_story(**load_story_file("examples/stories/pekarna.yaml"), seed=1)
    for a in res.attempts:
        print(f"{a.model} {a.seconds:.1f}s ok={a.ok} {a.error}")
    assert res.ok, res.attempts
    assert res.retries <= 2
