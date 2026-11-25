import pytest

from s2d import verify
from s2d.sim import simulate, without_story
from s2d.spec import load_spec


def _spec(n=6000):
    spec = load_spec("examples/a.yaml")
    spec.entities.customers.n = n
    return spec


def test_hypotheses_follow_the_event():
    spec = _spec()
    hs = {h.event_id: h for h in verify.hypotheses(spec)}
    assert "E3" not in hs  # ticket_rate: no test (and not simulated)
    e1, e2, e4, e5 = hs["E1"], hs["E2"], hs["E4"], hs["E5"]
    assert (e1.kpi, e1.vary, e1.treated, e1.fixed) == ("orders", "category", ["etiopie", "kolumbie", "espresso"], {})
    assert e1.price_pct == 15 and e1.direction == "down"
    assert (e2.kpi, e2.vary, e2.treated, e2.direction) == ("leavers", "segment", ["student"], "up")
    assert str(e2.T) == "2026-04-12"  # start + lag 42
    assert (e4.vary, e4.treated, e4.fixed) == ("city", ["Brno"], {"segment": ["predplatitel"]})
    assert (e5.vary, e5.treated, e5.fixed) == ("city", ["Brno"], {"channel": ["store"]})
    # a 30-day ramp: the 28-day window holds about half the plateau
    assert e5.expected_pct == pytest.approx(e5.story_pct * 14.5 / 30, abs=0.01)


@pytest.fixture(scope="module")
def worlds():
    spec = _spec()
    e5 = next(e for e in spec.events if e.id == "E5")
    e5.effects[0].size = -0.6  # far above the noise at 6k customers
    e5.effects[0].ramp_days = 0
    story = simulate(spec, seed=5)
    twin = simulate(without_story(spec), seed=5)
    return spec, verify.verify_con(verify.world_con(story), spec, story.truth["answer_key"], verify.world_con(twin))


def test_sql_gives_the_same_numbers(worlds):
    _, res = worlds
    tested = [r for r in res["tests"] if r["status"] != "not_testable"]
    assert len(tested) == 4
    for r in tested:
        assert r["sql_matches"], (r["event_id"], r["sql_result"], r["measured_pct"])
        assert r["twin"]["sql_matches"]


def test_a_large_effect_is_confirmed_and_the_twin_is_not(worlds):
    _, res = worlds
    e5 = next(r for r in res["tests"] if r["event_id"] == "E5")
    assert e5["confirmed"] and e5["measured_pct"] < -30 and e5["z"] >= verify.Z_CONFIRM
    assert not e5["twin"]["confirmed"]
    assert res["twin_confirmed"] == 0


def test_price_check_reads_product_prices(worlds):
    _, res = worlds
    e1 = next(r for r in res["tests"] if r["event_id"] == "E1")
    assert e1["price"]["measured_pct"] == pytest.approx(15, abs=1.0)  # Czech rounding of prices


def test_narrative_names_confirmed_events_only(worlds):
    _, res = worlds
    text = verify.narrative_cs(res)
    assert "Brno" in text
    for r in res["tests"]:
        if not r["confirmed"]:
            assert r["claim_cs"] not in text
