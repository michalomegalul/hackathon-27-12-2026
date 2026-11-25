import pandas as pd
import pytest

from s2d import score


def _truth():
    key = pd.DataFrame([
        {"event_id": "E1", "type": "price_change", "metric": "purchase_rate",
         "segment": "category=etiopie,kolumbie", "start_date": pd.Timestamp("2026-03-01"), "lag_days": 0,
         "direction": "down", "magnitude_pct": -6.0, "caused_by": None, "simulated": True},
        {"event_id": "E2", "type": "price_change", "metric": "churn_hazard", "segment": "segment=student",
         "start_date": pd.Timestamp("2026-03-01"), "lag_days": 42, "direction": "up", "magnitude_pct": 60.0,
         "caused_by": "E1", "simulated": True},
        {"event_id": "E3", "type": "supplier_delay", "metric": "ticket_rate", "segment": "supplier=S_ETH",
         "start_date": pd.Timestamp("2026-05-04"), "lag_days": 10, "direction": "up", "magnitude_pct": 150.0,
         "caused_by": None, "simulated": False},
    ])
    decoys = pd.DataFrame([{"type": "viral_spike", "date": pd.Timestamp("2025-10-14"), "segment": "", "size": 2.5,
                            "simulated": True}])
    return {"key": key, "scored": key[key["simulated"]].reset_index(drop=True), "decoys": decoys,
            "start": pd.Timestamp("2025-01-01"), "end": pd.Timestamp("2026-11-01")}


def _ev(id_, metric, seg, start, direction, mag, lag=None, caused_by=None, kind="shift"):
    return {"id": id_, "metric": metric, "segment": seg, "start_date": start, "direction": direction,
            "magnitude_pct": mag, "lag_days": lag, "caused_by": caused_by, "kind": kind}


def test_perfect_detection():
    ev = [_ev("C1", "purchase_rate", "category=etiopie,kolumbie", "2026-03-01", "down", -6.0),
          _ev("C2", "churn_hazard", "segment=student", "2026-04-12", "up", 60.0, lag=42, caused_by="C1")]
    s = score.score(ev, _truth())
    assert s["f1"] == 1.0 and s["excluded"] == ["E3"]
    assert s["caused_by_bonus"] == {"hit": 1, "possible": 1}
    assert all(m["score"] == 1.0 for m in s["matches"])


def test_timing_is_measured_from_start_plus_lag():
    ev = [_ev("C2", "churn_hazard", "segment=student", "2026-03-01", "up", 60.0)]
    sl = score.slots(ev[0], _truth()["scored"].iloc[1])
    assert sl["delta_days"] == -42 and sl["timing"] == 0.0


def test_gate_direction_and_metric():
    ev = [_ev("C1", "purchase_rate", "category=etiopie,kolumbie", "2026-03-01", "up", 6.0)]
    assert score.score(ev, _truth())["tp"] == 0


@pytest.mark.parametrize("pred, true, expected", [
    ("category=etiopie", "category=etiopie,kolumbie", 0.5),
    ("city=Brno", "city=Brno;channel=store", 0.5),
    ("", "", 1.0),
    ("", "city=Brno", 0.0),
])
def test_segment_jaccard(pred, true, expected):
    a, b = score.seg_pairs(pred), score.seg_pairs(true)
    jac = 1.0 if not a and not b else len(a & b) / len(a | b)
    assert jac == expected


def test_magnitude_slot():
    t = _truth()["scored"].iloc[1]
    assert score.slots(_ev("x", "churn_hazard", "", "2026-04-12", "up", 120.0), t)["magnitude"] == 0.0
    assert score.slots(_ev("x", "churn_hazard", "", "2026-04-12", "up", 60.0), t)["magnitude"] == 1.0


def test_decoy_is_a_labelled_false_positive():
    ev = [_ev("C9", "purchase_rate", "", "2025-10-14", "up", 150.0, kind="spike")]
    s = score.score(ev, _truth())
    assert s["precision"] == 0.0 and s["false_positives"][0]["decoy"] == "viral_spike"


def test_placebo_p_value_is_small_for_a_perfect_detector():
    ev = [_ev("C1", "purchase_rate", "category=etiopie,kolumbie", "2026-03-01", "down", -6.0),
          _ev("C2", "churn_hazard", "segment=student", "2026-04-12", "up", 60.0, lag=42)]
    p = score.placebo(ev, _truth(), n=200)
    assert p["f1"] == 1.0 and p["p_value"] < 0.05


def test_twin_rate():
    assert score.twin_rate([{}] * 2, 730) == pytest.approx(1.0, abs=0.01)
