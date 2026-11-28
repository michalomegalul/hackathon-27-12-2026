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


def test_pairs_are_only_drilled_under_a_confirmed_parent(monkeypatch):
    """Hierarchical scan (DECISIONS 57, PAIRS_GATED): city=Brno;channel=store is tested because
    city=Brno has a confirmed drop at the same time; without a story no pair is scanned at all."""
    monkeypatch.setattr(scan, "PAIRS_GATED", True)
    st = {}
    found = _brno_store(scan.scan(_store_world(1, size=-0.5), stats=st))
    assert st["tests"][2] >= 1 and any(c.status == "reported" for c in found)
    st = {}
    scan.scan(_store_world(1, size=0.0), stats=st)
    assert st["scanned"][2] == 0 and st["tests"][2] == 0, st


def test_city_channel_cells_are_scanned_without_a_parent():
    """DECISIONS 137: orders of a city x channel cell are scanned even when no parent moved, and
    a quiet world reports nothing there; the store drop is still found."""
    st = {}
    out = scan.scan(_store_world(1, size=0.0), stats=st)
    assert st["scanned"][2] >= 1, st
    assert not [c for c in out if c.status == "reported" and ";" in c.segment and c.kind == "shift"]
    assert any(c.status == "reported" for c in _brno_store(scan.scan(_store_world(1, size=-0.5))))


def _sku_units(outages: dict[str, tuple[int, int]], cat_skus: dict[str, list[str]], n=200):
    """Daily units: 10 a day per SKU, zero on its outage days [a, b)."""
    from s2d.detective.kpis import KPISet
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    rows = []
    for cat, skus in cat_skus.items():
        for sku in skus:
            a, b = outages.get(sku, (n, n))
            rows += [{"sku": sku, "category": cat, "supplier_id": "S1", "date": d, "units": 0 if a <= i < b else 10}
                     for i, d in enumerate(dates)]
    ks = KPISet(dates=dates)
    ks.events["sku_units"] = pd.DataFrame(rows)
    return ks


def test_overlapping_stockouts_of_one_category_are_one_event():
    ks = _sku_units({"A1": (100, 120), "A2": (101, 118), "A3": (103, 125)}, {"a": ["A1", "A2", "A3", "A4"]})
    rep = [c for c in scan.stockouts(ks) if c.status == "reported"]
    assert len(rep) == 1 and rep[0].start_date == "2026-04-11" and rep[0].end_date == "2026-05-05"
    assert "3 z 4 SKU" in rep[0].evidence


def test_one_sku_out_while_its_category_sells_is_routine():
    ks = _sku_units({"A1": (100, 106)}, {"a": ["A1", "A2", "A3"], "b": ["B1"]})
    st = {c.series: c.status for c in scan.stockouts(ks)}
    assert st == {"sku_units|A1": "routine"}
    # a category with a single SKU: that SKU out is the whole category out
    ks = _sku_units({"B1": (100, 106)}, {"a": ["A1", "A2"], "b": ["B1"]})
    assert [c.status for c in scan.stockouts(ks)] == ["reported"]


def test_shift_whose_own_series_moved_the_other_way_is_control():
    def cand(direction, raw, **kw):
        return scan.Candidate(id="", metric="purchase_rate", segment="category=a", kpi="orders", start_date="2026-05-01",
                              end_date=None, direction=direction, magnitude_pct=20.0, lag_days=None, caused_by=None,
                              kind="shift", confidence=1.0, evidence="", series="orders|category=a",
                              raw_change_pct=raw, **kw)
    up_but_fell, up_and_rose = cand("up", -15.0), cand("up", 12.0)
    price = cand("down", 3.0, extra={"source": "price"})
    scan.control_moved([up_but_fell, up_and_rose, price])
    assert [c.status for c in (up_but_fell, up_and_rose, price)] == ["control_moved", "reported", "reported"]


def test_a_change_that_happened_last_year_too_is_seasonal():
    n = 800
    rng = np.random.default_rng(3)
    rest = 100 + rng.normal(0, 2, n)
    seg = 50 + rng.normal(0, 1, n)
    t = 600
    seg[t:t + 28] *= 1.3            # +30 % this year
    seg[t - 364:t - 364 + 28] *= 1.3  # and the same days a year before
    before, after = slice(t - 28, t), slice(t, t + 28)
    g = np.random.default_rng(0)
    assert scan.last_year(seg, rest, before, after, g, False, 0.3) is not None
    seg2 = seg.copy()
    seg2[t - 364:t - 364 + 28] /= 1.3   # last year flat: an event, not the season
    assert scan.last_year(seg2, rest, before, after, g, False, 0.3) is None


# ---------------------------------------------------------------- round 5 (DECISIONS 133-137)


def _cand(segment, start="2026-06-01", metric="churn_hazard", kpi="churn_onsets", direction="up", **kw):
    return scan.Candidate(id="", metric=metric, segment=segment, kpi=kpi, start_date=start, end_date=None,
                          direction=direction, magnitude_pct=50.0, lag_days=None, caused_by=None, kind=kw.pop("kind", "shift"),
                          confidence=1.0, evidence="", series=f"{kpi}|{segment}", **kw)


def test_merge_keeps_unrelated_segments_apart():
    """Brno subscribers' churn and regular customers' churn in the same week are two events."""
    a, b = _cand("city=Brno", extra={"z": 6.0}), _cand("segment=bezny", start="2026-06-05", extra={"z": 9.0})
    scan.merge([a, b])
    assert a.status == "reported" and b.status == "reported"
    c, d = _cand("city=Brno", extra={"z": 6.0}), _cand("city=Brno", start="2026-06-08", extra={"z": 9.0})
    scan.merge([c, d])
    assert sorted([c.status, d.status]) == ["merged", "reported"]


def test_anchor_catalogue_reads_only_treatment_tables():
    from s2d.detective.kpis import KPISet
    dates = pd.date_range("2026-01-01", periods=200, freq="D")
    ks = KPISet(dates=dates)
    ks.events["price_changes"] = pd.DataFrame({"valid_from": [pd.Timestamp("2026-03-01")] * 2,
                                               "category": ["a", "b"], "pct": [10.0, 12.0]})
    rows = []
    for i, d in enumerate(dates):
        for city in ("X", "Y", "Z"):
            new = city in ("X", "Y") and 60 <= i < 150
            rows += [{"date": d, "city": city, "courier": "New" if new else "Old", "n": 50}]
    ks.events["courier_assign"] = pd.DataFrame(rows)
    an = scan.anchor_catalogue(ks)
    assert [(a["kind"], str(a["date"].date()), a["segment"]) for a in an] == [
        ("price", "2026-03-01", "category=a,b"), ("courier", "2026-03-02", "city=X,Y"),
        ("courier", "2026-05-31", "city=X,Y")]
    assert an[1]["courier"] == "New"


def test_anchored_churn_family_finds_and_dates_a_lagged_churn():
    """A churn rise 42 days after a price change is found by the anchored family below the scan's
    bar, dated within a week, and a world without the rise reports nothing."""
    ks, onset = _churn_world(4, mult=3.0)
    day = onset - pd.Timedelta(days=42)
    ks.events["price_changes"] = pd.DataFrame({"valid_from": [day], "category": ["a"], "pct": [15.0]})
    an = scan.anchor_catalogue(ks)
    out = scan.anchored_candidates(ks, an, [], np.random.default_rng(0), {})
    rep = [c for c in out if c.status == "reported"]
    assert len(rep) == 1 and rep[0].segment == "segment=student" and rep[0].direction == "up", out
    assert abs((pd.Timestamp(rep[0].start_date) - onset).days) <= 7, rep[0].start_date
    assert rep[0].extra["p_anchor"] <= rep[0].extra["alpha"]
    ks0, _ = _churn_world(4, mult=1.0)
    ks0.events["price_changes"] = ks.events["price_changes"]
    out0 = scan.anchored_candidates(ks0, scan.anchor_catalogue(ks0), [], np.random.default_rng(0), {})
    assert not [c for c in out0 if c.status == "reported"], out0


def test_churn_gap_is_measured_against_the_new_rate():
    """After a rate step of 0.5 a customer's usual gap doubles, so 70 idle days is not churn."""
    from s2d.detective import kpis
    con = duckdb.connect()
    days = [pd.Timestamp("2026-01-01") + pd.Timedelta(days=20 * i) for i in range(10)]
    con.register("o_df", pd.DataFrame({"customer_id": 1, "order_date": [d.date() for d in days]}))
    con.register("c_df", pd.DataFrame({"customer_id": [1], "city": ["Brno"], "segment": ["student"]}))
    con.execute("CREATE TABLE orders AS SELECT * FROM o_df")
    con.execute("CREATE TABLE customers AS SELECT * FROM c_df")
    con.execute("INSERT INTO orders VALUES (2, DATE '2026-09-07')")  # the data runs on 70 days
    old = kpis.churn_table(con).set_index("customer_id").loc[1]
    new = kpis.churn_table(con, steps=[("student", pd.Timestamp("2026-03-01"), 0.5)]).set_index("customer_id").loc[1]
    assert old["churned"] and not new["churned"]
    assert new["median_gap"] == 2 * old["median_gap"]


def test_pooled_ratio_test_skips_windows_without_events():
    """A courier that only delivers for a few weeks: before it, its share has no parcels at all,
    so the pooled test does not run (the old daily-mean DiD gave z of 40-150 there)."""
    from s2d.detective.kpis import KPISet
    dates = pd.date_range("2026-01-01", periods=300, freq="D")
    ks = KPISet(dates=dates)
    rng = np.random.default_rng(1)
    den = np.where((np.arange(300) >= 150) & (np.arange(300) < 200), 40.0, 0.0)
    num = rng.binomial(den.astype(int), 0.3).astype(float)
    tot_d = den + 400
    tot_n = num + rng.binomial(400, 0.1, 300)
    ks.parts[("late_rate", "courier=New")] = (pd.Series(num, dates), pd.Series(den, dates))
    ks.parts[("late_rate", "")] = (pd.Series(tot_n, dates), pd.Series(tot_d, dates))
    assert scan.pooled_test(ks, "late_rate", "courier=New", 150, 150)["valid"] is False
    assert scan.pooled_test(ks, "late_rate", "courier=New", 175, 175)["valid"] is False  # after-window runs past 200


def test_overdispersion_is_one_for_binomial_days_and_more_for_batches():
    rng = np.random.default_rng(2)
    den = np.full(400, 200.0)
    assert scan.overdispersion(rng.binomial(200, 0.1, 400).astype(float), den) < 1.3
    p = np.clip(0.1 + rng.normal(0, 0.05, 400), 0.01, 0.9)  # some days much worse than others
    assert scan.overdispersion(rng.binomial(200, p).astype(float), den) > 2


def test_pooled_ratio_test_sees_a_step_and_not_noise():
    from s2d.detective.kpis import KPISet
    dates = pd.date_range("2026-01-01", periods=400, freq="D")
    rng = np.random.default_rng(5)
    ks = KPISet(dates=dates)
    p = np.where(np.arange(400) >= 250, 0.3, 0.1)
    n_a = rng.binomial(150, p).astype(float)
    n_b = rng.binomial(600, 0.1, 400).astype(float)
    ks.parts[("late_rate", "city=A")] = (pd.Series(n_a, dates), pd.Series(150.0, dates))
    ks.parts[("late_rate", "")] = (pd.Series(n_a + n_b, dates), pd.Series(750.0, dates))
    hit = scan.pooled_test(ks, "late_rate", "city=A", 250, 250)
    assert hit["valid"] and hit["excludes"] and hit["z"] > 8 and abs(hit["size"] - 0.2) < 0.03
    quiet = scan.pooled_test(ks, "late_rate", "city=A", 120, 120)
    assert quiet["z"] < 4


def _orders_ks(series: dict):
    from s2d.detective.kpis import KPISet
    dates = pd.date_range("2026-01-01", periods=200, freq="D")
    ks = KPISet(dates=dates)
    for seg, v in series.items():
        ks.series[("orders", seg)] = pd.Series(np.asarray(v, float), dates)
    return ks


def test_a_rise_next_to_a_stockout_is_substitution():
    """Category b gains 20 orders a day while category a's shelf is empty and a loses 60."""
    a = np.r_[np.full(100, 100.0), np.full(100, 40.0)]
    b = np.r_[np.full(100, 50.0), np.full(100, 70.0)]
    ks = _orders_ks({"category=a": a, "category=b": b})
    out = _cand("category=a;supplier=S", start="2026-04-12", metric="purchase_rate", kpi="sku_units",
                direction="down", kind="stockout")
    rise = _cand("category=b", start="2026-04-11", metric="purchase_rate", kpi="orders",
                 extra={"before": slice(72, 100), "after": slice(100, 128)})
    big = _cand("category=b", start="2026-04-11", metric="purchase_rate", kpi="orders",
                extra={"before": slice(72, 100), "after": slice(100, 128)})
    scan.substitution([out, rise], ks)
    assert rise.status == "substitution"
    ks.series[("orders", "category=b")] = pd.Series(np.r_[np.full(100, 50.0), np.full(100, 150.0)], ks.dates)
    scan.substitution([out, big], ks)  # gains more than a lost: not only switching customers
    assert big.status == "reported"


def test_a_donor_with_its_own_event_is_taken_out_of_the_control():
    """Regular customers' churn looks up only because students (in its control) fall back after
    their own churn wave; without students in the control nothing is left."""
    rng = np.random.default_rng(3)
    n = 200
    bez = rng.poisson(40, n).astype(float)
    stu = rng.poisson(np.r_[np.full(100, 80.0), np.full(100, 30.0)]).astype(float)
    oth = rng.poisson(40, n).astype(float)
    from s2d.detective.kpis import KPISet
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    ks = KPISet(dates=dates)
    for seg, v in (("segment=bezny", bez), ("segment=student", stu), ("segment=jiny", oth), ("", bez + stu + oth)):
        ks.series[("churn_onsets", seg)] = pd.Series(v, dates)
    c = _cand("segment=bezny", start="2026-04-11", extra={"before": slice(72, 100), "after": slice(100, 128)})
    wave = _cand("segment=student", start="2026-02-01")
    scan.contaminated_control([c, wave], ks, np.random.default_rng(0))
    assert c.status == "contaminated_control" and "segment=student" in c.evidence


def test_a_december_stockout_explains_its_category_drop():
    """The Christmas rush empties shelves: a stock-out the calendar explains still explains the
    category's drop, and so do "sold out" tickets during it."""
    so = _cand("category=a;supplier=S", start="2025-12-14", metric="purchase_rate", kpi="sku_units",
               direction="down", kind="stockout", status="explained_by_calendar", extra={"share": 0.3})
    so.end_date = "2025-12-21"
    drop = _cand("category=a", start="2025-12-01", metric="purchase_rate", kpi="orders", direction="down")
    tick = _cand("topic=vyprodáno", start="2025-12-10", metric="ticket_rate", kpi="tickets")
    small = _cand("category=a;supplier=S", start="2025-12-14", metric="purchase_rate", kpi="sku_units",
                  direction="down", kind="stockout", status="routine", extra={"share": 0.02})
    small.end_date = "2025-12-21"
    scan.explained_by_stockout([so, drop, tick])
    assert drop.status == "explained_by_stockout" and tick.status == "explained_by_stockout"
    drop2 = _cand("category=a", start="2025-12-01", metric="purchase_rate", kpi="orders", direction="down")
    scan.explained_by_stockout([small, drop2])  # a SKU with 2 % of the category explains nothing
    assert drop2.status == "reported"


def test_maxt_bar_is_never_below_the_floor():
    bars = scan.maxt_bars(*(lambda w: (w, {k: p for k in w.series if (p := scan.prepare(w.series[k])) is not None}))(
        _store_world(1, size=0.0)), {})
    assert all(b >= scan.MAXT_FLOOR for b in bars.values()), bars
