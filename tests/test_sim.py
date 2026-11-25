import hashlib
from datetime import date

import numpy as np
import pytest

from s2d.spec import Effect, Event, load_spec
from s2d.sim import simulate, without_story
from s2d.sim.events import compile_curve, daily_hazard
from s2d.sim.output import write_world
from s2d.sim.report import churn_report, format_report


def small_spec(n=3000):
    spec = load_spec("examples/a.yaml")
    spec.entities.customers.n = n
    return spec


# ---------------------------------------------------------------- building blocks


def test_daily_hazard_hits_target():
    h = daily_hazard(0.15, 30)
    assert 1 - (1 - h) ** 30 == pytest.approx(0.15)


def test_curve_shape():
    eff = Effect(metric="churn_hazard", size=1, lag_days=5, ramp_days=4, duration_days=10, decay_halflife_days=3)
    c = compile_curve(start_idx=10, effect=eff, n_days=60)
    assert c[:15].sum() == 0                       # nothing before start + lag
    assert c[15:19].tolist() == [0.25, 0.5, 0.75, 1.0]  # linear ramp
    assert (c[19:29] == 1).all()                   # plateau
    assert c[29] == 1 and c[32] == pytest.approx(0.5)  # half-life decay


def test_unimplemented_event_type():
    spec = small_spec()
    with pytest.raises(NotImplementedError, match="supplier_delay"):
        simulate(spec, strict=True)
    world = simulate(spec)  # non-strict: skipped and flagged in the answer key
    key = world.truth["answer_key"].set_index("event_id")
    assert not key.loc["E3", "simulated"] and key.loc["E1", "simulated"]


# ---------------------------------------------------------------- determinism + integrity


def _hashes(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*.parquet"))}


def test_same_seed_same_parquet(tmp_path):
    spec = small_spec()
    write_world(simulate(spec, seed=7), tmp_path / "one")
    write_world(simulate(spec, seed=7), tmp_path / "two")
    write_world(simulate(spec, seed=8), tmp_path / "other")
    one, two = _hashes(tmp_path / "one"), _hashes(tmp_path / "two")
    assert {"deliveries.parquet", "reviews.parquet", "tickets.parquet"} <= set(one)
    assert one == two
    assert one["orders.parquet"] != _hashes(tmp_path / "other")["orders.parquet"]


def test_foreign_keys():
    t = simulate(small_spec(), seed=3).tables
    for table, pk in [("customers", "customer_id"), ("products", "product_id"), ("orders", "order_id"),
                      ("order_items", "order_item_id"), ("payments", "payment_id"),
                      ("product_prices", "price_id"), ("deliveries", "delivery_id"),
                      ("reviews", "review_id"), ("tickets", "ticket_id")]:
        assert t[table][pk].is_unique, f"{table}.{pk} not unique"
    for child, col, parent, pk in [("orders", "customer_id", "customers", "customer_id"),
                                   ("order_items", "order_id", "orders", "order_id"),
                                   ("order_items", "product_id", "products", "product_id"),
                                   ("payments", "order_id", "orders", "order_id"),
                                   ("product_prices", "product_id", "products", "product_id"),
                                   ("deliveries", "order_id", "orders", "order_id"),
                                   ("reviews", "order_id", "orders", "order_id"),
                                   ("reviews", "customer_id", "customers", "customer_id"),
                                   ("tickets", "order_id", "orders", "order_id"),
                                   ("tickets", "customer_id", "customers", "customer_id")]:
        assert t[child][col].dropna().isin(t[parent][pk]).all(), f"{child}.{col} -> {parent}.{pk} broken"
    # a review or ticket belongs to the customer of its order; only completed, non-store orders ship
    orders = t["orders"].set_index("order_id")
    for name in ("reviews", "tickets"):
        df = t[name].dropna(subset=["order_id"])
        assert (orders.loc[df["order_id"].astype(int), "customer_id"].to_numpy() == df["customer_id"].to_numpy()).all()
    shipped = orders.loc[t["deliveries"]["order_id"]]
    assert (shipped["status"] == "completed").all() and (shipped["channel"] != "store").all()
    assert t["deliveries"]["order_id"].is_unique
    # every order has at least one item, and its total matches the items
    items = t["order_items"].assign(line=lambda d: d.quantity * d.unit_price)
    totals = items.groupby("order_id")["line"].sum()
    assert np.allclose(t["orders"].set_index("order_id")["total_czk"], totals)


def test_no_orders_after_churn_or_before_signup():
    world = simulate(small_spec(), seed=3)
    orders = world.tables["orders"]
    cust = orders["customer_id"].to_numpy() - 1
    day = (orders["order_date"].to_numpy() - np.datetime64(world.calendar.dates[0], "D")).astype("timedelta64[D]").astype(int)
    churn = world.result.churn_day[cust]
    assert (day >= world.population.signup_day[cust]).all()
    assert ((churn < 0) | (day < churn)).all()


def test_price_change_lands_in_price_table():
    world = simulate(small_spec(), seed=3)
    prices = world.tables["product_prices"]
    products = world.tables["products"].set_index("product_id")
    changed = prices[prices["valid_from"] == date(2026, 3, 1)]
    assert set(products.loc[changed["product_id"], "category"]) == {"etiopie", "kolumbie", "espresso"}


# ---------------------------------------------------------------- the story comes back out


@pytest.fixture(scope="module")
def example_a():
    spec = load_spec("examples/a.yaml")
    return simulate(spec), simulate(without_story(spec))


def test_example_a_churn_matches_target(example_a):
    report = churn_report(*example_a)
    print("\nExample A\n" + format_report(report))
    assert set(report["event_id"]) == {"E2", "E4"}
    for r in report.itertuples():
        assert abs(r.realized - r.expected) < 0.03
        assert abs(r.realized_excess - r.expected_excess) < 0.02
        assert r.realized_excess > 0.01  # the story is visible over the no-story twin


def test_churn_shock_hits_stated_target():
    spec = small_spec(n=20_000)
    spec.events = [Event(
        id="S1", type="churn_shock", start=date(2026, 3, 2), target={"segment": ["bezny"]},
        params={"churn_pct": 15, "churn_window_days": 30},
        effects=[{"metric": "churn_hazard", "size": 0}],
        narrative_cs="15 % běžných zákazníků odejde do 30 dnů.",
    )]
    report = churn_report(simulate(spec), simulate(without_story(spec)))
    print("\nchurn_shock\n" + format_report(report))
    r = report.iloc[0]
    assert r.stated_p == 0.15
    assert abs(r.realized_p - 0.15) < 0.02
