import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from s2d.detective import narrate, scan
from s2d.detective.data import open_analyst

DETECTIVE = Path("s2d/detective")


def test_detective_code_never_names_truth():
    """The detective package must not mention the hidden schema anywhere."""
    for path in DETECTIVE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"_truth|answer_key|spec_yaml", text), f"{path} mentions hidden data"


def test_loader_exposes_only_main_tables(tmp_path):
    db = tmp_path / "story.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE orders AS SELECT 1 AS order_id")
        con.execute("CREATE SCHEMA hidden")
        con.execute("CREATE TABLE hidden.secret AS SELECT 42 AS x")
    con = open_analyst(tmp_path)
    names = {r[0] for r in con.execute("SELECT table_schema || '.' || table_name FROM information_schema.tables").fetchall()}
    assert names == {"main.orders"}
    assert not con.execute("SELECT count(*) FROM duckdb_databases() WHERE database_name = 'src'").fetchone()[0]


def _series(values, start="2025-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def _noise(n, seed, mean=100.0):
    rng = np.random.default_rng(seed)
    weekly = np.tile([1.0, 1.0, 1.0, 1.0, 1.1, 1.2, 0.7], n // 7 + 1)[:n]
    return rng.poisson(mean * weekly).astype(float)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_known_jump_is_found_within_3_days(seed):
    v = _noise(400, seed)
    v[250:] *= 1.3
    pr = scan.prepare(_series(v))
    bks = scan.breakpoints(pr.z)
    assert any(abs(b - 250) <= 3 for b in bks), bks


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_pure_noise_has_no_break(seed):
    pr = scan.prepare(_series(_noise(400, seed)))
    assert scan.breakpoints(pr.z) == []


def test_ramp_onset_finds_ramp_start():
    x = np.r_[np.zeros(100), np.linspace(0, 10, 21)[1:], np.full(80, 10.0)]
    x += np.random.default_rng(0).normal(0, 0.5, len(x))
    t0, t1 = scan.ramp_onset(x, 110, 40, 180)
    assert abs(t0 - 100) <= 3 and abs(t1 - 120) <= 4


def test_did_sees_segment_change_and_not_common_change():
    rng = np.random.default_rng(0)
    rest = rng.poisson(200, 120).astype(float)
    seg = rng.poisson(50, 120).astype(float)
    seg[60:] *= 0.8
    rest_common = rest.copy()
    rest_common[60:] *= 0.8
    b, a = slice(32, 60), slice(60, 88)
    point, ci, _ = scan.did(seg, rest, b, a, np.random.default_rng(1))
    assert point < -0.12 and ci[1] < 0
    point2, ci2, _ = scan.did(seg, rest_common, b, a, np.random.default_rng(1))
    assert ci2[0] <= 0 <= ci2[1]


def test_calendar_explains_black_friday_and_holidays():
    assert scan.calendar_reason(pd.Timestamp("2025-11-28")) == "Black Friday"
    assert scan.calendar_reason(pd.Timestamp("2025-12-27"))
    assert "svátek" in scan.calendar_reason(pd.Timestamp("2026-05-08"))
    assert scan.calendar_reason(pd.Timestamp("2026-03-10")) is None


# ---------------------------------------------------------------- narrator


def _result(n=2):
    ev = [{"id": f"C00{i}", "metric": "purchase_rate", "segment": "city=Brno", "start_date": "2026-09-07",
           "end_date": None, "direction": "down", "magnitude_pct": -20.0, "lag_days": None, "caused_by": None,
           "kind": "shift", "confidence": 0.9 if i == 1 else 0.3, "evidence": "x"} for i in range(1, n + 1)]
    return {"events": ev, "n_series": 10, "data_start": "2025-01-01", "data_end": "2026-11-01",
            "status_counts": {}}


def test_narrator_rejects_invented_ids(monkeypatch):
    monkeypatch.setattr(narrate.llm, "complete", lambda *a, **k: {
        "events": [{"candidate_id": "C999", "accept": True, "merged_into": None, "label_cs": "x"}],
        "narrative_cs": "Vymyšlená událost."})
    out = narrate.narrate(_result())
    assert out["source"].startswith("template")
    assert [e["accept"] for e in out["events"]] == [True, False]  # fallback: confidence >= 0.5


def test_narrator_keeps_valid_answer(monkeypatch):
    monkeypatch.setattr(narrate.llm, "complete", lambda *a, **k: {
        "events": [{"candidate_id": "C001", "accept": True, "merged_into": None, "label_cs": "Pokles v Brně"},
                   {"candidate_id": "C002", "accept": True, "merged_into": "C001", "label_cs": "duplicita"}],
        "narrative_cs": "V září klesly objednávky v Brně."})
    out = narrate.narrate(_result())
    assert out["narrative_cs"].startswith("V září")
    assert [e["accept"] for e in out["events"]] == [True, False]  # merged means not accepted


def test_narrator_survives_llm_failure(monkeypatch):
    def boom(*a, **k):
        raise narrate.llm.LLMError("down")
    monkeypatch.setattr(narrate.llm, "complete", boom)
    out = narrate.narrate(_result())
    assert "LLM failed" in out["source"] and "klesají o 20 %" in out["narrative_cs"]


def test_narrator_uses_detective_step_with_schema(monkeypatch):
    seen = {}

    def fake(step, prompt, schema=None, **k):
        seen.update(step=step, schema=schema, prompt=prompt)
        return {"events": [], "narrative_cs": "Nic."}
    monkeypatch.setattr(narrate.llm, "complete", fake)
    narrate.narrate(_result())
    assert seen["step"] == "detective" and seen["schema"] is narrate.SCHEMA
    assert "C001" in seen["prompt"] and "Nevymýšlej" in seen["prompt"]
