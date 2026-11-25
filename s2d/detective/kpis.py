"""Daily KPI series, overall and per segment.

A series is identified by (kpi, segment). `segment` is the text form the answer
key uses: '' for everyone, 'city=Brno', 'city=Brno;channel=store'. Every KPI maps
to one answer-key metric (METRIC). Tables that do not exist yet simply produce no
series, so the detective works on whatever the sim wrote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import duckdb
import numpy as np
import pandas as pd

from .data import tables

MIN_EVENTS = 30          # skip a segment series with fewer events in total
CHURN_MIN_DAYS = 60      # a customer is churned after max(60, 3 x median gap) idle days
CHURN_GAP_FACTOR = 3
CHURN_EDGE_DAYS = 90     # churn KPI: only customers with threshold <= 90 d, cut 90 d before the end

METRIC = {
    "orders": "purchase_rate",
    "revenue": "purchase_rate",
    "new_customers": "acquisition_rate",
    "churn_onsets": "churn_hazard",
    "late_rate": "delivery_days",
    "rating_mean": "rating_mean",
    "tickets": "ticket_rate",
}
# KPIs that are a ratio, not a count. Their segment value is not additive.
RATIO_KPIS = {"late_rate", "rating_mean"}


@dataclass
class KPISet:
    dates: pd.DatetimeIndex
    series: dict[tuple[str, str], pd.Series] = field(default_factory=dict)
    # Event-level frames kept for the drill-down: kpi -> DataFrame(date, dims..., value)
    events: dict[str, pd.DataFrame] = field(default_factory=dict)
    dims: dict[str, list[str]] = field(default_factory=dict)
    valid_until: dict[str, pd.Timestamp] = field(default_factory=dict)
    valid_from: dict[str, pd.Timestamp] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def get(self, kpi: str, segment: str = "") -> pd.Series | None:
        return self.series.get((kpi, segment))


def seg_text(keys: tuple[str, ...], values: tuple) -> str:
    return ";".join(f"{k}={v}" for k, v in zip(keys, values))


def _add_counts(ks: KPISet, kpi: str, ev: pd.DataFrame, dims: list[str], value: str | None = None,
                pairs: bool = True) -> None:
    """Daily sums of `value` (or counts) overall, per dim value and per pair of dims."""
    ev = ev.dropna(subset=["date"])
    ks.events[kpi] = ev
    ks.dims[kpi] = dims
    val = ev[value] if value else pd.Series(1.0, index=ev.index)
    ev = ev.assign(_v=val.astype(float), _n=1)
    end = ks.valid_until.get(kpi, ks.dates[-1])
    start = ks.valid_from.get(kpi, ks.dates[0])
    idx = ks.dates[(ks.dates <= end) & (ks.dates >= start)]

    def put(seg: str, g: pd.DataFrame) -> None:
        if g["_n"].sum() < MIN_EVENTS:
            return
        s = g.groupby("date")["_v"].sum().reindex(idx, fill_value=0.0)
        ks.series[(kpi, seg)] = s

    put("", ev)
    groups = [(d,) for d in dims]
    if pairs:
        groups += [c for c in combinations(dims, 2) if not (c[0] == c[1])]
    for keys in groups:
        for vals, g in ev.groupby(list(keys)):
            vals = vals if isinstance(vals, tuple) else (vals,)
            put(seg_text(keys, vals), g)


def build(con: duckdb.DuckDBPyConnection) -> KPISet:
    have = tables(con)
    if "orders" not in have:
        raise ValueError("no orders table: nothing to analyse")
    lo, hi = con.execute("SELECT min(order_date), max(order_date) FROM orders").fetchone()
    ks = KPISet(dates=pd.date_range(lo, hi, freq="D"))
    cust_cols = have.get("customers", set())
    seg_col = "c.segment" if "segment" in cust_cols else "NULL"
    pref_col = "c.preferred_channel" if "preferred_channel" in cust_cols else "o.channel"

    orders = con.execute(f"""
        SELECT o.order_id, o.customer_id, o.order_date AS date, o.city, o.channel,
               {seg_col} AS segment, o.total_czk
        FROM orders o LEFT JOIN customers c USING (customer_id)""").df()
    orders["date"] = pd.to_datetime(orders["date"])
    dims = ["city", "channel"] + (["segment"] if "segment" in cust_cols else [])

    _add_counts(ks, "orders", orders, dims)
    _add_counts(ks, "revenue", orders, dims, value="total_czk", pairs=False)

    if {"order_items", "products"} <= have.keys():
        by_cat = con.execute(f"""
            SELECT DISTINCT o.order_id, o.order_date AS date, o.city, o.channel,
                   {seg_col} AS segment, p.category
            FROM orders o JOIN order_items i USING (order_id) JOIN products p USING (product_id)
            LEFT JOIN customers c USING (customer_id)""").df()
        by_cat["date"] = pd.to_datetime(by_cat["date"])
        # Category series join the orders KPI: an order counts once per category it contains.
        _add_category(ks, by_cat, dims)

        units = con.execute("""
            SELECT p.sku, p.category, p.supplier_id, o.order_date AS date, sum(i.quantity) AS units
            FROM orders o JOIN order_items i USING (order_id) JOIN products p USING (product_id)
            GROUP BY ALL""").df()
        units["date"] = pd.to_datetime(units["date"])
        ks.events["sku_units"] = units

    if {"product_prices", "products"} <= have.keys():
        # Every new price row after the first one per product is a price change.
        pc = con.execute("""
            WITH p AS (SELECT pp.product_id, pp.valid_from, pp.price, pr.category,
                              lag(pp.price) OVER (PARTITION BY pp.product_id ORDER BY pp.valid_from) AS prev
                       FROM product_prices pp JOIN products pr USING (product_id))
            SELECT valid_from, category, 100 * (price / prev - 1) AS pct FROM p
            WHERE prev IS NOT NULL AND price <> prev""").df()
        pc["valid_from"] = pd.to_datetime(pc["valid_from"])
        ks.events["price_changes"] = pc

    _acquisition(ks, con, cust_cols, dims, pref_col)
    _churn(ks, con, cust_cols, dims, pref_col)
    _later_tables(ks, con, have)
    return ks


def _add_category(ks: KPISet, by_cat: pd.DataFrame, dims: list[str]) -> None:
    ks.events["orders_by_category"] = by_cat
    idx = ks.dates
    for keys in [("category",)] + [("category", d) for d in dims]:
        for vals, g in by_cat.groupby(list(keys)):
            vals = vals if isinstance(vals, tuple) else (vals,)
            if len(g) < MIN_EVENTS:
                continue
            ks.series[("orders", seg_text(keys, vals))] = g.groupby("date").size().reindex(idx, fill_value=0).astype(float)


def _acquisition(ks: KPISet, con, cust_cols: set, dims: list[str], pref_col: str) -> None:
    """New customers per day = first order in the data. Customers who signed up
    before the data starts are not new, so they are left out (if signup_date exists)."""
    signup = "c.signup_date >= (SELECT min(order_date) FROM orders)" if "signup_date" in cust_cols else "TRUE"
    seg_col = "c.segment" if "segment" in cust_cols else "NULL"
    first = con.execute(f"""
        WITH f AS (SELECT customer_id, min(order_date) AS date, arg_min(city, order_date) AS city,
                          arg_min(channel, order_date) AS channel
                   FROM orders GROUP BY customer_id)
        SELECT f.date, f.city, f.channel, {seg_col} AS segment
        FROM f LEFT JOIN customers c USING (customer_id) WHERE {signup}""").df()
    first["date"] = pd.to_datetime(first["date"])
    # Warm-up: a customer who signs up places the first order about one gap later,
    # so the first weeks are short of first orders. Same edge rule as churn.
    ks.valid_from["new_customers"] = ks.dates[0] + pd.Timedelta(days=CHURN_EDGE_DAYS)
    first = first[first["date"] >= ks.valid_from["new_customers"]]
    if len(first) >= MIN_EVENTS:
        _add_counts(ks, "new_customers", first, dims)


def churn_table(con, cust_cols: set | None = None) -> pd.DataFrame:
    """One row per customer: last order, median gap, churned flag and onset date.

    Churned = no order for max(60, 3 x median gap) days before the end of the data.
    The onset is the last order plus the customer's mean gap: with memoryless
    ordering, the expected time from the last order to the churn day is one mean gap.
    """
    cust_cols = cust_cols if cust_cols is not None else tables(con).get("customers", set())
    seg_col = "c.segment" if "segment" in cust_cols else "NULL"
    pref = "c.preferred_channel" if "preferred_channel" in cust_cols else "NULL"
    df = con.execute(f"""
        WITH g AS (
            SELECT customer_id, order_date,
                   order_date - lag(order_date) OVER (PARTITION BY customer_id ORDER BY order_date) AS gap
            FROM orders)
        SELECT g.customer_id, max(order_date) AS last_order, count(*) AS n_orders,
               median(gap) AS median_gap, avg(gap) AS mean_gap,
               any_value(c.city) AS city, any_value({seg_col}) AS segment, any_value({pref}) AS channel
        FROM g LEFT JOIN customers c USING (customer_id) GROUP BY g.customer_id""").df()
    end = pd.Timestamp(con.execute("SELECT max(order_date) FROM orders").fetchone()[0])
    df["last_order"] = pd.to_datetime(df["last_order"])
    gap = pd.to_numeric(df["median_gap"], errors="coerce")
    gap = gap.fillna(gap.median() if gap.notna().any() else 30.0)
    df["median_gap"] = gap
    df["threshold"] = np.maximum(CHURN_MIN_DAYS, CHURN_GAP_FACTOR * gap)
    df["churned"] = (end - df["last_order"]).dt.days > df["threshold"]
    mean_gap = pd.to_numeric(df["mean_gap"], errors="coerce").fillna(gap)
    df["date"] = df["last_order"] + pd.to_timedelta(mean_gap.round(), unit="D")
    df.loc[~df["churned"], "date"] = pd.NaT
    df.attrs["end"] = end
    return df


def _churn(ks: KPISet, con, cust_cols: set, dims: list[str], pref_col: str) -> None:
    ct = churn_table(con, cust_cols)
    # Right edge: a customer whose last order is closer to the end than their
    # threshold cannot be called churned yet, so the last `threshold` days are
    # biased low. Count only customers with threshold <= CHURN_EDGE_DAYS and cut
    # the series CHURN_EDGE_DAYS before the end: for them the edge is complete.
    cut = CHURN_EDGE_DAYS
    ks.valid_until["churn_onsets"] = ct.attrs["end"] - pd.Timedelta(days=cut)
    regular = ct["threshold"] <= cut
    ks.notes.append(f"churn: {regular.mean():.0%} of customers are regular enough "
                    f"(threshold <= {cut} d); series cut {cut} days before the end")
    # Left edge, the mirror image: a customer who churned in the first weeks had
    # their last order before the data starts and is invisible. Drop the first
    # CHURN_EDGE_DAYS too.
    start = ks.dates[0] + pd.Timedelta(days=cut)
    ev = ct[ct["churned"] & regular][["date", "city", "segment", "channel"]]
    ev = ev[(ev["date"] <= ks.valid_until["churn_onsets"]) & (ev["date"] >= start)]
    ks.valid_from["churn_onsets"] = start
    if len(ev) >= MIN_EVENTS:
        _add_counts(ks, "churn_onsets", ev, dims)


def _later_tables(ks: KPISet, con, have: dict[str, set[str]]) -> None:
    """KPIs for tables the full sim will add. Column names are guessed from the
    report's table list; anything missing just turns the KPI off."""
    def date_col(cols: set[str], *names: str) -> str | None:
        return next((n for n in names if n in cols), None)

    d = have.get("deliveries")
    if d and (dc := date_col(d, "delivered_date", "delivery_date", "date")) and "order_id" in d:
        late = "late" if "late" in d else ("(delivered_date > promised_date)" if {"delivered_date", "promised_date"} <= d else None)
        if late:
            courier = ", d.courier" if "courier" in d else ""
            ev = con.execute(f"""SELECT d.{dc} AS date, o.city, o.channel{courier}, CAST({late} AS DOUBLE) AS late
                                 FROM deliveries d JOIN orders o USING (order_id)""").df()
            ev["date"] = pd.to_datetime(ev["date"])
            _add_ratio(ks, "late_rate", ev, ["city", "channel"] + (["courier"] if courier else []), "late")
    r = have.get("reviews")
    if r and "rating" in r and (dc := date_col(r, "review_date", "created_date", "date")):
        join = "JOIN orders o USING (order_id)" if "order_id" in r else ""
        dims = ["city", "channel"] if join else []
        ev = con.execute(f"SELECT r.{dc} AS date, r.rating{', o.city, o.channel' if join else ''} "
                         f"FROM reviews r {join}").df()
        ev["date"] = pd.to_datetime(ev["date"])
        _add_ratio(ks, "rating_mean", ev, dims, "rating")
    t = have.get("tickets")
    if t and (dc := date_col(t, "created_date", "ticket_date", "date")):
        topic = "t.topic" if "topic" in t else "NULL"
        ev = con.execute(f"SELECT t.{dc} AS date, {topic} AS topic FROM tickets t").df()
        ev["date"] = pd.to_datetime(ev["date"])
        _add_counts(ks, "tickets", ev, ["topic"] if "topic" in t else [], pairs=False)


def _add_ratio(ks: KPISet, kpi: str, ev: pd.DataFrame, dims: list[str], value: str) -> None:
    """Daily mean of `value`, overall and per dim value. Days without events are
    filled from the neighbours, so a quiet day is not a zero rating."""
    ks.events[kpi] = ev
    ks.dims[kpi] = dims
    for keys in [()] + [(x,) for x in dims]:
        groups = [((), ev)] if not keys else list(ev.groupby(list(keys)))
        for vals, g in groups:
            if len(g) < MIN_EVENTS:
                continue
            vals = vals if isinstance(vals, tuple) else (vals,)
            s = g.groupby("date")[value].mean().reindex(ks.dates).interpolate(limit_direction="both")
            ks.series[(kpi, seg_text(keys, vals) if keys else "")] = s
