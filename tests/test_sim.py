import hashlib
from datetime import date

import numpy as np
import pandas as pd
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
    from s2d.spec import EventType
    spec.events[2].type = EventType.service_outage  # out of scope: still a stub
    with pytest.raises(NotImplementedError, match="service_outage"):
        simulate(spec, strict=True)
    world = simulate(spec)  # non-strict: skipped and flagged in the answer key
    key = world.truth["answer_key"].set_index("event_id")
    assert not key.loc["E3", "simulated"] and key.loc["E1", "simulated"]


def test_supplier_delay_empties_the_shelf():
    """E3 of Example A: shipments from S_ETH take 3x as long; the shelf runs empty some days
    later and `vyprodáno` tickets about those products follow. Nothing of it in the twin."""
    spec = small_spec(6000)
    story, twin = simulate(spec, seed=4), simulate(without_story(spec), seed=4)
    assert story.truth["answer_key"].set_index("event_id").loc["E3", "mechanism"] == "emergent"

    def zero_share(w, lo, hi):
        inv = w.tables["inventory_daily"].merge(w.tables["products"][["product_id", "supplier_id"]])
        inv = inv[(inv.supplier_id == "S_ETH") & (inv.date >= lo) & (inv.date < hi)]
        return (inv.stock_units == 0).mean()
    lo, hi = np.datetime64("2026-05-14"), np.datetime64("2026-06-11")
    assert zero_share(story, lo, hi) > 0.5 and zero_share(twin, lo, hi) < 0.05
    assert zero_share(story, np.datetime64("2026-04-01"), np.datetime64("2026-05-04")) < 0.05

    def sold_out_tickets(w):
        t = w.tables["tickets"].merge(w.tables["products"][["product_id", "supplier_id"]])
        t = t[(t.topic == "vyprodáno") & (t.supplier_id == "S_ETH")]
        d = t.opened_at.dt.date.astype("datetime64[ns]")
        return ((d >= lo) & (d < hi)).sum()
    assert sold_out_tickets(story) > 5 * max(sold_out_tickets(twin), 1)
    # stock is never negative, and inventory flows add up
    inv = story.tables["inventory_daily"].sort_values(["product_id", "date"])
    assert (inv.stock_units >= 0).all()
    prev = inv.groupby("product_id").stock_units.shift()
    flow = (prev + inv.received_units - inv.sold_units - inv.stock_units).dropna()
    assert (flow == 0).all()


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
                      ("reviews", "review_id"), ("tickets", "ticket_id"),
                      ("subscriptions", "subscription_id"), ("stores", "store_id"),
                      ("suppliers", "supplier_id"), ("shipments_in", "shipment_line_id")]:
        assert t[table][pk].is_unique, f"{table}.{pk} not unique"
    for child, col, parent, pk in [("orders", "customer_id", "customers", "customer_id"),
                                   ("order_items", "order_id", "orders", "order_id"),
                                   ("order_items", "product_id", "products", "product_id"),
                                   ("payments", "order_id", "orders", "order_id"),
                                   ("product_prices", "product_id", "products", "product_id"),
                                   ("deliveries", "order_id", "orders", "order_id"),
                                   ("orders", "store_id", "stores", "store_id"),
                                   ("orders", "subscription_id", "subscriptions", "subscription_id"),
                                   ("subscriptions", "customer_id", "customers", "customer_id"),
                                   ("tickets", "product_id", "products", "product_id"),
                                   ("reviews", "product_id", "products", "product_id"),
                                   ("products", "supplier_id", "suppliers", "supplier_id"),
                                   ("shipments_in", "product_id", "products", "product_id"),
                                   ("shipments_in", "supplier_id", "suppliers", "supplier_id"),
                                   ("inventory_daily", "product_id", "products", "product_id"),
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
    assert (orders["store_id"].notna() == (orders["channel"] == "store")).all()


def test_subscriptions_stop_at_cancellation():
    t = simulate(small_spec(), seed=3).tables
    subs, orders = t["subscriptions"], t["orders"]
    customers = t["customers"].set_index("customer_id")
    assert (customers.loc[subs["customer_id"], "segment"] == "predplatitel").all()
    assert subs["customer_id"].is_unique and len(subs) == (customers["segment"] == "predplatitel").sum()
    m = orders.dropna(subset=["subscription_id"]).merge(subs, on="subscription_id", suffixes=("", "_s"))
    assert (m["customer_id"] == m["customer_id_s"]).all()
    assert not (m["order_date"] > m["cancelled_at"]).any()      # no scheduled order after cancelling
    assert (subs["cancelled_at"].isna() == subs["cancel_reason"].isna()).all()
    # an active subscriber gets an order about every plan interval
    days = {"týdenní": 7, "dvoutýdenní": 14, "měsíční": 30, "dvouměsíční": 61}
    gaps = m.sort_values("order_date").groupby("subscription_id")["order_date"].diff().dt.days.dropna()
    plan = m.loc[gaps.index, "plan"].map(days)
    assert (gaps == plan).mean() > 0.9
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


def test_dirt_only_touches_the_export_copy():
    from s2d.sim.output import export_tables
    world = simulate(small_spec(), seed=3)
    clean = {k: v.copy() for k, v in world.tables.items()}
    low, log_low = export_tables(world, "low")
    high, log_high = export_tables(world, "high")
    again, _ = export_tables(world, "high")
    for k, v in clean.items():                       # the clean tables are untouched
        pd.testing.assert_frame_equal(world.tables[k], v)
    assert log_high["rows"].sum() > 3 * log_low["rows"].sum()
    for k in high:                                   # same seed, same dirt
        pd.testing.assert_frame_equal(high[k], again[k])
    # keys stay valid: duplicates get new ids, NULLs never go into keys
    assert high["customers"]["customer_id"].is_unique and high["payments"]["payment_id"].is_unique
    assert len(high["customers"]) > len(clean["customers"])
    assert high["orders"]["customer_id"].isin(high["customers"]["customer_id"]).all()
    assert high["payments"]["order_id"].isin(high["orders"]["order_id"]).all()
    assert (high["customers"]["city"] != clean["customers"]["city"].reindex(high["customers"].index)).any()
