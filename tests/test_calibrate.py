import pandas as pd
import pytest

from s2d import calibrate
from s2d.spec import Difficulty, Target, load_spec


def test_kpi_segment_uses_the_detective_key_order():
    t = Target(segment=["predplatitel"], city=["Brno"])
    assert t.describe() == "city=Brno;segment=predplatitel"
    assert calibrate.kpi_segment(Target(channel=["store"], city=["Brno"])) == "city=Brno;channel=store"
    assert calibrate.kpi_segment(Target(city=["Brno"], category=["espresso"])) == "category=espresso;city=Brno"


def test_targets_straddle_the_verifier_threshold():
    from s2d import verify
    d = {lvl: calibrate.target_d(lvl) for lvl in Difficulty}
    assert d[Difficulty.medium] > verify.Z_CONFIRM > d[Difficulty.hard]
    assert d[Difficulty.easy] > d[Difficulty.medium] > d[Difficulty.hard]


@pytest.fixture(scope="module")
def example_a():
    spec = load_spec("examples/a.yaml")
    spec.entities.customers.n = 4000
    out, table = calibrate.calibrate(spec, seed=3, log=lambda m: None)
    return spec, out, table


def test_calibration_scales_up_and_keeps_facts(example_a):
    spec, out, table = example_a
    assert set(table["event_id"]) == {"E1", "E2", "E4", "E5"}  # E3 is not simulated
    assert out is not spec and spec.events[0].effects[0].size == -0.06  # input untouched
    for r in table.itertuples():
        assert r.simulated_size * r.story_size > 0, "direction kept"
        assert abs(r.simulated_size) >= abs(r.story_size) - 1e-9, "only ever scaled up"
        if r.status in ("ok", "scaled", "widened"):
            assert r.d >= r.target_d
        else:
            assert r.status in ("below_target", "not_measurable")
    assert out.events[0].params.price_change_pct == 15  # a stated fact stays


def test_calibrated_size_is_what_the_answer_key_shows(example_a):
    from s2d.sim import simulate
    _, out, table = example_a
    key = simulate(out, seed=3).truth["answer_key"].set_index("event_id")
    for r in table.itertuples():
        assert key.loc[r.event_id, "magnitude_pct"] == pytest.approx(100 * r.simulated_size, abs=0.05)
        assert key.loc[r.event_id, "segment"] == r.segment


def test_no_events_no_calibration():
    spec = load_spec("examples/a.yaml")
    spec.events = []
    out, table = calibrate.calibrate(spec, seed=1)
    assert table.empty and out.events == []
    assert isinstance(table, pd.DataFrame)


def test_realism_caps_are_the_same_at_every_difficulty():
    spec = load_spec("examples/a.yaml")
    e1 = next(i for i, e in enumerate(spec.events) if e.id == "E1")
    e5 = next(i for i, e in enumerate(spec.events) if e.id == "E5")
    assert calibrate.size_cap(spec, e1, 0, up=False) == pytest.approx(-0.20)  # 15 % dearer -> at most -20 %
    assert calibrate.size_cap(spec, e5, 0, up=False) == pytest.approx(-0.30)
    spec.meta.difficulty = Difficulty.easy
    assert calibrate.size_cap(spec, e5, 0, up=False) == pytest.approx(-0.30)
    assert calibrate.size_cap(spec, e1, 0, up=False) == pytest.approx(-0.20)


def test_calibration_steps_back_down_but_not_below_the_story(example_a):
    _, out, table = example_a
    for r in table.itertuples():
        if r.status == "scaled":
            assert r.d <= r.target_d * calibrate.BAND + 1e-9 or abs(r.simulated_size) == abs(r.story_size)


def test_a_stated_size_survives_calibration(example_a):
    """Example A's E5 ("prodeje klesnou o pětinu") is size_stated: calibration measures it
    but never changes it, and reports below_target instead of inflating it (DECISIONS 90)."""
    spec, out, table = example_a
    e5 = next(e for e in out.events if e.id == "E5")
    assert e5.effects[0].size == -0.20 and e5.target == next(e for e in spec.events if e.id == "E5").target
    row = table.set_index("event_id").loc["E5"]
    assert bool(row["stated"]) and row["simulated_size"] == pytest.approx(-0.20)
    assert row["status"] in ("ok", "below_target") and row["d"] is not None
    assert not table.set_index("event_id").loc["E1", "stated"]


def test_a_stated_size_below_target_warns_and_stays():
    spec = load_spec("examples/a.yaml")
    spec.entities.customers.n = 3000
    spec.events = [e for e in spec.events if e.id == "E1"]
    spec.events[0].effects[0].size_stated = True  # -6 %: far below target at 3000 customers
    said = []
    out, table = calibrate.calibrate(spec, seed=1, log=said.append)
    assert out.events[0].effects[0].size == -0.06
    r = table.iloc[0]
    assert r["status"] == "below_target" and r["d"] < r["target_d"] and r["factor"] == 1
    assert any("stated by the story" in m for m in said)


def test_difficulty_does_not_scale_a_stated_size():
    from s2d.sim import simulate
    spec = load_spec("examples/a.yaml")
    spec.entities.customers.n = 500
    spec.meta.difficulty = Difficulty.hard
    key = simulate(spec, seed=1).truth["answer_key"].set_index("event_id")
    assert key.loc["E5", "magnitude_pct"] == pytest.approx(-20)   # stated
    assert key.loc["E1", "magnitude_pct"] == pytest.approx(-3)    # -6 % x 0.5
    from s2d import verify
    hs = {h.event_id: h for h in verify.hypotheses(spec)}
    assert hs["E5"].story_pct == pytest.approx(-20) and hs["E1"].story_pct == pytest.approx(-3)


def test_d_is_the_weakest_calibration_seed(example_a):
    """d is measured on CAL_SEEDS seeds, none of them the run's, and the smallest counts."""
    _, _, table = example_a
    seeds = calibrate.calibration_seeds(3)
    assert len(seeds) == calibrate.CAL_SEEDS > 1 and 3 not in seeds
    assert calibrate.calibration_seeds(3, calibrate.PARALLEL_MAX_N + 1) == seeds[:1]  # the brief's 160k
    for r in table.itertuples():
        assert len(r.d_seeds) == calibrate.CAL_SEEDS
        known = [d for d in r.d_seeds if d is not None]
        if r.d is not None:
            assert r.d == pytest.approx(min(known), abs=0.01)


def test_customers_for_stated_grows_n_only_for_a_short_stated_size():
    spec = load_spec("examples/a.yaml")
    spec.entities.customers.n = 40000  # medium: goal 3.5 * OVERSHOOT

    def table(*rows):
        return pd.DataFrame([{"stated": s, "status": st, "d": d} for s, st, d in rows])

    assert calibrate.customers_for_stated(spec, table((False, "below_target", 1.0)), 100_000) is None
    assert calibrate.customers_for_stated(spec, table((True, "ok", 4.0)), 100_000) is None
    assert calibrate.customers_for_stated(spec, table((True, "not_measurable", None)), 100_000) is None
    # d 3.0 -> n * (3.675 / 3.0)^2 = 60 025 -> rounded up to 65 000
    assert calibrate.customers_for_stated(spec, table((True, "below_target", 3.0)), 100_000) == 65_000
    assert calibrate.customers_for_stated(spec, table((True, "below_target", 0.5)), 100_000) == 100_000
    assert calibrate.customers_for_stated(spec, table((True, "below_target", 0.0)), 100_000) == 100_000
    spec.entities.customers.n = 100_000
    assert calibrate.customers_for_stated(spec, table((True, "below_target", 1.0)), 100_000) is None
    assert calibrate.customers_for_stated(spec, pd.DataFrame(), 100_000) is None


def test_remeasure_keeps_sizes_and_measures_at_the_new_count(example_a):
    """After the customer raise (DECISIONS 129) the sizes stay as calibrated and every d is
    measured again, on the same seeds."""
    _, out, table = example_a
    bigger = out.model_copy(deep=True)
    bigger.entities.customers.n = 2 * out.entities.customers.n
    again = calibrate.remeasure(bigger, table, seed=3, log=lambda m: None)
    assert list(again["simulated_size"]) == list(table["simulated_size"])
    assert list(again["event_id"]) == list(table["event_id"])
    for r in again.itertuples():
        assert len(r.d_seeds) == calibrate.CAL_SEEDS
        if r.d is not None:
            assert r.d == pytest.approx(min(d for d in r.d_seeds if d is not None), abs=0.01)
            assert (r.status == "below_target") == (r.d < r.target_d)
