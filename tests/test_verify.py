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
    e3 = [h for h in verify.hypotheses(spec) if h.event_id == "E3"]
    assert [(h.kpi, h.vary, h.treated, h.topic) for h in e3] == [
        ("tickets", "supplier", ["S_ETH"], "vyprodáno"), ("stockout_days", "supplier", ["S_ETH"], None)]
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
    assert len(tested) == 6
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


# ---------------------------------------------------------------- Example B: courier, JOIN + lag


@pytest.fixture(scope="module")
def courier_worlds():
    """Example B at 40k customers (its own difficulty, no calibration: the courier events
    are stated facts and emergent effects, which calibration does not scale)."""
    spec = load_spec("examples/b.yaml")
    spec.entities.customers.n = 40000
    story = simulate(spec, seed=11)
    twin = simulate(without_story(spec), seed=11)
    return spec, story, verify.verify_con(verify.world_con(story), spec, story.truth["answer_key"],
                                          verify.world_con(twin))


def test_courier_hypotheses():
    spec = load_spec("examples/b.yaml")
    hs = [(h.event_id, h.kpi) for h in verify.hypotheses(spec)]
    assert hs[:4] == [("E1", "late_share"), ("E1", "rating"), ("E2", "leavers"), ("E2", "late_churn")]
    lc = verify.hypotheses(spec)[3]
    assert lc.fixed == {"city": ["Ostrava", "Olomouc"]} and lc.on_days == 120 and str(lc.start) == "2026-02-02"


def test_courier_story_is_confirmed_and_the_twin_is_not(courier_worlds):
    _, _, res = courier_worlds
    rows = {(r["event_id"], r["kpi"]): r for r in res["tests"]}
    for k in [("E1", "late_share"), ("E1", "rating"), ("E2", "late_churn")]:
        assert rows[k]["confirmed"], (k, rows[k].get("z"), rows[k].get("measured_pct"))
        assert not rows[k]["twin"]["confirmed"], k
        assert rows[k]["sql_matches"] and rows[k]["twin"]["sql_matches"], k
    assert rows[("E1", "late_share")]["measured_pct"] > 30            # pp more late parcels
    assert rows[("E1", "rating")]["measured_pct"] < -0.5             # rating points
    lc = rows[("E2", "late_churn")]
    assert lc["groups"]["ratio"] > 1.4                                # late parcels: customers leave more often
    assert lc["placebo_before"]["z"] < verify.Z_CONFIRM               # not before the switch
    assert res["twin_confirmed"] == 0


def test_courier_churn_is_customer_level(courier_worlds):
    """The new courier changes nothing in the churn curves: the extra leavers are
    customers whose own parcel was late (no segment-level hazard is applied)."""
    _, story, _ = courier_worlds
    from s2d.spec import Metric
    assert not any(e.event_id in ("E1", "E2") for e in story.story.for_metric(Metric.churn_hazard))
    cause = story.truth["customer_state"]["churn_cause"]
    assert (cause == "zpoždění").sum() > 0


# ---------------------------------------------------------------- a new story (Psí Bouda): no A/B special cases


@pytest.fixture(scope="module")
def psi_worlds():
    """The story that broke the verifier: a courier switch 3 months before the data ends,
    subscriptions in one segment only, a stockout of all of one supplier's categories."""
    spec = load_spec("tests/fixtures/psi_spec.yaml")
    spec.entities.customers.n = 6000
    story = simulate(spec, seed=7)
    twin = simulate(without_story(spec), seed=7)
    return verify.verify_con(verify.world_con(story), spec, story.truth["answer_key"], verify.world_con(twin))


def test_psi_every_number_is_finite_and_sane(psi_worlds):
    import math
    for r in psi_worlds["tests"]:
        if r["status"] == "not_testable":
            assert r["reason"], r["event_id"]
            continue
        for v in [r["measured_pct"], *r["ci_pct"], r["z"]]:
            assert math.isfinite(v) and abs(v) < 1000, (r["event_id"], r["kpi"], v)
        assert r["sql_matches"], (r["event_id"], r["kpi"])


def test_psi_fallbacks(psi_worlds):
    rows = {(r["event_id"], r["kpi"]): r for r in psi_worlds["tests"]}
    # late share and rating are measurable up to the end of the data (not cut like leavers)
    assert rows[("E3", "late_share")]["confirmed"] and rows[("E3", "rating")]["status"] != "not_testable"
    # no other supplier sells kibble: the control is every other product
    so = rows[("E1", "stockout_days")]
    assert so["confirmed"] and so["control"].startswith("mimo cíl")
    # only breeders subscribe: no control, a rate per 1000 active subscriptions
    c = rows[("E2", "cancellations")]
    assert c["measured_unit"] == "‰/den" and c["control"] is None and c["confirmed"]
    assert c["expected_pct"] == pytest.approx(c["measured_pct"], rel=0.6)
    # E4 starts 70 days before the end: leavers are not measurable, and it says why
    assert "too close to the end" in rows[("E4", "leavers")]["reason"]
    assert psi_worlds["twin_confirmed"] == 0


def test_fit_windows_extends_the_data_for_a_late_event():
    spec = load_spec("tests/fixtures/psi_spec.yaml")
    fitted, warnings = verify.fit_windows(spec)
    assert spec.meta.days == 669                      # the input is not changed
    assert fitted.meta.end == verify.date(2027, 1, 16)  # E4: T 2026-08-22 + 28 d + 120 d leaver edge
    assert any("E4" in w for w in warnings)
    for h, first, last in verify.needed_span(fitted):
        assert fitted.meta.start <= first and last <= fitted.meta.end, h.event_id
    assert verify.fit_windows(load_spec("examples/a.yaml"))[1] == []  # A and B already fit
    assert verify.fit_windows(load_spec("examples/b.yaml"))[1] == []


TICKETS = {"event_id": "E1", "kpi": "tickets", "segment": "supplier=S_POL", "T": "2026-04-01", "measured_pct": 5.04,
           "ci_pct": [3.0, 7.4], "z": 19.16, "measured_unit": "/den", "claim_cs": "Kamion stál na hranicích.",
           "confirmed": True, "direction": "up"}


def test_narrator_gets_the_unit_and_the_template_uses_it():
    assert verify._fact(TICKETS)["zmena"] == "+5.04 tiketu denně"
    assert "5.04 tiketu denně" in verify.narrative_cs({"tests": [TICKETS]})


def test_check_numbers_catches_a_wrong_unit_and_invented_numbers():
    assert verify.check_numbers("Od 1. 4. 2026 přibylo 5,04 tiketu denně (z = 19,2).", [TICKETS]) == []
    assert "wrong unit" in verify.check_numbers("Tikety vzrostly o +5.04 %.", [TICKETS])[0]
    assert verify.check_numbers("Tržby klesly o 37 %.", [TICKETS])


def test_narrate_falls_back_when_the_llm_mixes_units(monkeypatch):
    from s2d import llm
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Od 1. 4. 2026 vzrostly tikety o 5,04 %.")
    out = verify.narrate({"tests": [TICKETS]})
    assert out["source"].startswith("template (LLM failed: numbers do not match")
    assert "5.04 tiketu denně" in out["text"]
