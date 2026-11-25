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
