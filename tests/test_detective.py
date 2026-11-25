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


# ---------------------------------------------------------------- calendar and ramp onset on a synthetic store world


def _store_world(seed: int, onset="2026-09-07", ramp=30, size=-0.2):
    """Daily store and e-shop orders in three cities. Brno stores lose `size`
    over a linear `ramp` from `onset`. Every store is closed on 28 Sept (a CZ
    holiday), so a fit on the Brno series alone sees a zero day right there."""
    from s2d.detective.kpis import KPISet
    dates = pd.date_range("2025-06-01", "2026-12-31", freq="D")
    rng = np.random.default_rng(seed)
    weekly = np.tile([0.95, 0.95, 1.0, 1.0, 1.1, 1.2, 0.8], len(dates) // 7 + 1)[:len(dates)]
    k = (dates - pd.Timestamp(onset)).days.to_numpy()
    effect = 1 + size * np.clip((k + 1) / ramp, 0, 1) * (k >= 0)
    closed = (dates == pd.Timestamp("2026-09-28")).astype(float)
    base = {"Brno": 60, "Praha": 120, "Ostrava": 50}
    ks = KPISet(dates=dates)
    for city, mean in base.items():
        lam_store = mean * weekly * (effect if city == "Brno" else 1) * (1 - closed)
        ks.series[("orders", f"city={city};channel=store")] = pd.Series(rng.poisson(lam_store).astype(float), dates)
        ks.series[("orders", f"city={city};channel=eshop")] = pd.Series(rng.poisson(mean * weekly).astype(float), dates)
    for city in base:
        ks.series[("orders", f"city={city}")] = sum(ks.series[("orders", f"city={city};channel={ch}")]
                                                     for ch in ("store", "eshop"))
    for ch in ("store", "eshop"):
        ks.series[("orders", f"channel={ch}")] = sum(ks.series[("orders", f"city={c};channel={ch}")] for c in base)
    ks.series[("orders", "")] = ks.series[("orders", "channel=store")] + ks.series[("orders", "channel=eshop")]
    ks.dims["orders"] = ["city", "channel"]
    return ks


def _brno_store(cands):
    return [c for c in cands if c.segment == "city=Brno;channel=store" and c.kind == "shift"
            and c.start_date >= "2026-08-01" and c.status not in ("merged",)]


def test_calendar_only_explains_spikes_and_short_changes():
    assert scan.calendar_applies("spike", "2026-09-28", "2026-09-29", has_control=True)
    assert scan.calendar_applies("shift", "2026-09-25", "2026-09-30", has_control=True)   # 5-day change
    assert scan.calendar_applies("shift", "2026-09-25", None, has_control=False)          # no control
    assert not scan.calendar_applies("shift", "2026-09-25", None, has_control=True)
    assert not scan.calendar_applies("shift", "2026-09-25", "2026-12-01", has_control=True)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_lasting_store_drop_near_a_holiday_is_reported(seed):
    """Fix for Example A E5: a confirmed DiD shift vs the other cities' stores
    must not be thrown out because 28 Sept is a holiday."""
    found = _brno_store(scan.scan(_store_world(seed, size=-0.5)))
    assert found, "Brno store drop not found"
    assert not any(c.status == "explained_by_calendar" for c in found)
    # the DiD confirms the drop; whether it is reported is a matter of power (Z_REPORT), not of the calendar
    assert any(c.direction == "down" and c.ci[1] < 0 for c in found), [(c.status, c.ci, c.confidence) for c in found]


def test_ramp_onset_is_ramp_start_and_scores_on_start_plus_lag():
    """The reported start of a 30-day ramp is its first day, not its end and not
    the holiday in the middle of it, and the scorer measures it against start + lag.
    Over 10 seeds: the median error is within 3 days and 7 of 10 score a match."""
    from s2d import score
    key = pd.Series({"start_date": pd.Timestamp("2026-08-24"), "lag_days": 14, "segment": "city=Brno;channel=store",
                     "metric": "purchase_rate", "direction": "down", "magnitude_pct": -50.0})
    errs, matched = [], 0
    for seed in range(1, 11):
        rep = [c for c in _brno_store(scan.scan(_store_world(seed, size=-0.5))) if c.status == "reported"]
        if not rep:
            continue
        c = rep[0]
        errs.append((pd.Timestamp(c.start_date) - pd.Timestamp("2026-09-07")).days)
        sl = score.slots(c.row(), key)  # truth start 08-24 + lag 14 = ramp start 09-07
        assert sl["delta_days"] == errs[-1]
        matched += score.pair_score(sl) >= score.MATCH
        # a prediction at the end of the ramp is 30 days late: no timing credit, no match
        late = score.slots({**c.row(), "start_date": "2026-10-07"}, key)
        assert late["timing"] == 0.0 and score.pair_score(late) == 0.0
    assert abs(np.median(errs)) <= 3, errs
    assert matched >= 7, errs


# ---------------------------------------------------------------- repeat-purchase rate


def _churn_world(seed: int, mult: float = 3.0, onset: int = 300, days: int = 600):
    """Two segments x two cities, 3000 customers each, 1.5 orders a month and 3 % monthly
    churn. Students get `mult` x the churn hazard for 60 days from `onset`."""
    rng = np.random.default_rng(seed)
    n = 3000
    seg = np.repeat(["student", "bezny"], 2 * n)
    city = np.tile(np.repeat(["Praha", "Brno"], n), 2)
    h = np.full((len(seg), days), 1 - 0.97 ** (1 / 30.4))
    h[seg == "student", onset:onset + 60] *= mult
    alive = np.cumprod(rng.random(h.shape) >= h, axis=1).astype(bool)
    buys = alive & (rng.random(h.shape) < 1.5 / 30.4)
    ci, di = np.nonzero(buys)
    dates = pd.Timestamp("2025-01-01") + pd.to_timedelta(di, unit="D")
    con = duckdb.connect()
    con.register("c_df", pd.DataFrame({"customer_id": np.arange(len(seg)), "city": city, "segment": seg}))
    con.register("o_df", pd.DataFrame({"order_id": np.arange(len(ci)), "customer_id": ci, "order_date": dates.date,
                                       "city": city[ci], "channel": "eshop", "total_czk": 300.0}))
    con.execute("CREATE TABLE customers AS SELECT * FROM c_df")
    con.execute("CREATE TABLE orders AS SELECT * FROM o_df")
    from s2d.detective import kpis
    return kpis.build(con), pd.Timestamp("2025-01-01") + pd.Timedelta(days=onset)


def test_repeat_rate_drops_when_a_segment_churns():
    ks, onset = _churn_world(1)
    stu, rest = ks.get("repeat_rate", "segment=student"), ks.get("repeat_rate", "segment=bezny")
    gap = stu - rest
    before = gap[onset - pd.Timedelta(days=60):onset - pd.Timedelta(days=1)].mean()
    after = gap[onset + pd.Timedelta(days=60):onset + pd.Timedelta(days=88)].mean()
    assert after < before - 0.02, (before, after)
    num, den = ks.parts[("repeat_rate", "segment=student")]
    assert np.allclose((num / den).dropna(), stu.dropna())


def test_repeat_rate_is_reported_as_more_churn():
    """Fewer repeat buyers maps to churn_hazard going up, not down."""
    ks, onset = _churn_world(2, mult=5.0)
    found = [c for c in scan.scan(ks) if c.kpi == "repeat_rate" and c.segment == "segment=student"
             and c.status == "reported"]
    assert found, "student churn not found in the repeat rate"
    c = found[0]
    assert c.metric == "churn_hazard" and c.direction == "up" and c.magnitude_pct > 0
    assert abs((pd.Timestamp(c.start_date) - onset).days) <= 21, c.start_date


def test_pairs_are_only_drilled_under_a_confirmed_parent():
    """Hierarchical scan: city=Brno;channel=store is tested because city=Brno has a
    confirmed drop at the same time; without a story no pair is scanned at all."""
    st = {}
    found = _brno_store(scan.scan(_store_world(1, size=-0.5), stats=st))
    assert st["tests"][2] >= 1 and any(c.status == "reported" for c in found)
    st = {}
    scan.scan(_store_world(1, size=0.0), stats=st)
    assert st["scanned"][2] == 0 and st["tests"][2] == 0, st
