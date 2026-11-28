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

from s2d import rustk

from .data import tables

MIN_EVENTS = 30          # skip a segment series with fewer events in total
CHURN_MIN_DAYS = 60      # a customer is churned after max(60, 3 x median gap) idle days
CHURN_GAP_FACTOR = 3
CHURN_EDGE_DAYS = 90     # churn KPI: only customers with threshold <= 90 d, cut 90 d before the end
REPEAT_ACTIVE_DAYS = 60  # repeat rate: customers with an order in the 60 days before the anchor ...
REPEAT_NEXT_DAYS = 30    # ... who order again in the 30 days after it
REPEAT_MIN_ACTIVE = 100  # skip a repeat-rate segment with fewer active customers on an average day

METRIC = {
    "orders": "purchase_rate",
    "revenue": "purchase_rate",
    "new_customers": "acquisition_rate",
    "churn_onsets": "churn_hazard",
    "cancellations": "churn_hazard",
    "repeat_rate": "churn_hazard",
    "late_rate": "delivery_days",
    "rating_mean": "rating_mean",
    "low_rating": "rating_mean",
    "tickets": "ticket_rate",
}
# KPIs that are a ratio, not a count. Their segment value is not additive.
RATIO_KPIS = {"late_rate", "rating_mean", "low_rating", "repeat_rate"}
# Ratio KPIs whose DiD is computed from pooled window sums of numerator and denominator
# (scan.pooled_test, DECISIONS 138): a share of events (log-odds) or a mean of values.
POOLED_KPIS = {"late_rate": "share", "low_rating": "share", "rating_mean": "mean"}
# KPIs that move the opposite way to their metric without a transform: more 1-2 star reviews
# is a lower rating
FLIP_KPIS = {"low_rating"}
# KPIs that move the opposite way to their metric: fewer repeat buyers = more churn.
INVERSE_KPIS = {"repeat_rate"}
# Rolling KPIs: one day's event moves them for this many days.
SMEAR_DAYS = {"repeat_rate": REPEAT_NEXT_DAYS}
# Shares of "bought within N days": the DiD runs on cloglog(share) (see scan.cloglog).
CLOGLOG_KPIS = {"repeat_rate"}


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
    # Numerator and denominator of ratio KPIs that have them: (kpi, segment) -> (num, den).
    # Lets the DiD compare a segment with the complement instead of with everyone.
    parts: dict[tuple[str, str], tuple[pd.Series, pd.Series]] = field(default_factory=dict)

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

    groups = [(d,) for d in dims]
    if pairs:
        groups += [c for c in combinations(dims, 2) if not (c[0] == c[1])]
    if rustk.LIB is not None and np.isfinite(ev["_v"].to_numpy()).all():
        _counts_fast(ks, kpi, ev, idx, groups, None if not value else ev["_v"].to_numpy())
        return
    put("", ev)
    for keys in groups:
        for vals, g in ev.groupby(list(keys)):
            vals = vals if isinstance(vals, tuple) else (vals,)
            put(seg_text(keys, vals), g)


def _group_codes(df: pd.DataFrame, keys: tuple[str, ...]) -> tuple[np.ndarray, list[tuple], np.ndarray]:
    """Group code per row (-1 for a row with a missing key), the key tuples and the sizes, in the
    sorted order `df.groupby(list(keys))` iterates in."""
    grp = df.groupby(list(keys))
    codes = np.nan_to_num(grp.ngroup().to_numpy(dtype=float), nan=-1).astype(np.int64)
    sizes = grp.size()
    labels = [v if isinstance(v, tuple) else (v,) for v in sizes.index]
    return codes, labels, sizes.to_numpy()


def _counts_fast(ks: KPISet, kpi: str, ev: pd.DataFrame, idx: pd.DatetimeIndex, groups: list[tuple[str, ...]],
                 vals: np.ndarray | None) -> None:
    """`_add_counts.put` for every group at once (Rust kernel), same series in the same order."""
    pos = idx.get_indexer(ev["date"])
    passes = [((), np.zeros(len(ev), dtype=np.int64), [()], np.array([len(ev)]))]
    passes += [(keys, *_group_codes(ev, keys)) for keys in groups]
    for keys, codes, labels, sizes in passes:
        sums = rustk.group_sums(codes, pos, vals, len(labels), len(idx))
        for g, (label, size) in enumerate(zip(labels, sizes)):
            if size < MIN_EVENTS:
                continue
            ks.series[(kpi, seg_text(keys, label) if keys else "")] = pd.Series(sums[g], index=idx, name="_v")


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
    _repeat(ks, con, cust_cols, dims, pref_col)
    _later_tables(ks, con, have)
    return ks


def _add_category(ks: KPISet, by_cat: pd.DataFrame, dims: list[str]) -> None:
    ks.events["orders_by_category"] = by_cat
    idx = ks.dates
    if rustk.LIB is not None:
        pos = idx.get_indexer(by_cat["date"])
        for keys in [("category",)] + [("category", d) for d in dims]:
            codes, labels, sizes = _group_codes(by_cat, keys)
            sums = rustk.group_sums(codes, pos, None, len(labels), len(idx))
            for g, (label, size) in enumerate(zip(labels, sizes)):
                if size >= MIN_EVENTS:
                    ks.series[("orders", seg_text(keys, label))] = pd.Series(sums[g], index=idx)
        return
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


def rate_steps(ks: KPISet, rng: np.random.Generator | None = None) -> list[tuple[str, pd.Timestamp, float]]:
    """Customer segments whose purchase rate stepped at a price change (DECISIONS 137).

    The dates come from product_prices only (a treatment table). At each date, the orders
    of every customer segment are compared with the other segments (scan.did, windows
    [T-28, T) and [T, T+28)). A step is kept when the DiD's 95 % CI excludes 0. It is not a
    finding, only the rate a customer is measured against, so it needs no placebo bar: segment
    seasonality puts its placebo z at 1-2 even for a -10 % step. Returns (segment value, date,
    rate ratio)."""
    pc = ks.events.get("price_changes")
    if pc is None or pc.empty:
        return []
    from . import scan  # scan imports this module
    rng = rng or np.random.default_rng(0)
    out = []
    for day in sorted(pd.to_datetime(pc["valid_from"]).unique()):
        day = pd.Timestamp(day)
        for (kpi, seg), s in ks.series.items():
            if kpi != "orders" or not seg.startswith("segment=") or ";" in seg:
                continue
            rest = scan._rest(ks, kpi, seg, s)
            t0 = int(s.index.get_indexer([day])[0])
            w = scan._windows(len(s), t0, t0) if t0 >= 0 else None
            if rest is None or w is None:
                continue
            sv, rv = s.to_numpy(float), rest.reindex(s.index).to_numpy(float)
            point, ci, _ = scan.did(sv, rv, *w, rng)
            if not ci[0] <= 0 <= ci[1] and point > -0.9:
                out.append((seg.split("=", 1)[1], day, 1 + point))
    return out


def churn_table(con, cust_cols: set | None = None,
                steps: list[tuple[str, pd.Timestamp, float]] | None = None) -> pd.DataFrame:
    """One row per customer: last order, median gap, churned flag and onset date.

    Churned = no order for max(60, 3 x median gap) days before the end of the data.
    The onset is the last order plus the customer's mean gap: with memoryless
    ordering, the expected time from the last order to the churn day is one mean gap.

    `steps` (see rate_steps): a customer of a segment whose purchase rate stepped by the
    ratio r at a price change, and whose last order is after it, is measured against the
    new rate: both gaps are divided by r. A student who now buys every 22 days instead of
    every 20 is not idle for longer than usual after 61 days (DECISIONS 137).
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
    mean_gap = pd.to_numeric(df["mean_gap"], errors="coerce").fillna(gap)
    for value, day, ratio in steps or []:
        new = (df["segment"] == value) & (df["last_order"] >= day)
        gap = gap.where(~new, gap / ratio)
        mean_gap = mean_gap.where(~new, mean_gap / ratio)
    df["median_gap"] = gap
    df["threshold"] = np.maximum(CHURN_MIN_DAYS, CHURN_GAP_FACTOR * gap)
    df["churned"] = (end - df["last_order"]).dt.days > df["threshold"]
    df["date"] = df["last_order"] + pd.to_timedelta(mean_gap.round(), unit="D")
    df.loc[~df["churned"], "date"] = pd.NaT
    df.attrs["end"] = end
    return df


def _churn(ks: KPISet, con, cust_cols: set, dims: list[str], pref_col: str) -> None:
    steps = rate_steps(ks)
    ks.events["rate_steps"] = pd.DataFrame(steps, columns=["segment", "date", "ratio"])
    for value, day, ratio in steps:
        ks.notes.append(f"churn: segment {value} buys {ratio - 1:+.0%} from the price change on {day.date()}; "
                        f"its gaps after it are measured against the new rate")
    ct = churn_table(con, cust_cols, steps)
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
    subscribers = _cancellations(ks, con, dims, pref_col)
    # a subscriber's churn is observed (cancelled_at), so it is not guessed from order gaps:
    # an empty shelf stops a subscriber's orders too, and the guess would read it as churn
    ev = ct[ct["churned"] & regular & ~ct["customer_id"].isin(subscribers)][["date", "city", "segment", "channel"]]
    ev = ev[(ev["date"] <= ks.valid_until["churn_onsets"]) & (ev["date"] >= start)]
    ks.valid_from["churn_onsets"] = start
    if len(ev) >= MIN_EVENTS:
        _add_counts(ks, "churn_onsets", ev, dims)


def _cancellations(ks: KPISet, con, dims: list[str], pref_col: str) -> set:
    """Subscriptions cancelled per day (`subscriptions.cancelled_at`): churn of subscribers,
    observed instead of inferred (DECISIONS 60, 135). Returns the subscribers' customer ids."""
    have = tables(con)
    sub = have.get("subscriptions", set())
    if not {"customer_id", "cancelled_at"} <= sub:
        return set()
    cust = have.get("customers", set())
    seg = "c.segment" if "segment" in cust else "NULL"
    pref = pref_col if "preferred_channel" in cust else "NULL"
    df = con.execute(f"""
        SELECT s.customer_id, s.cancelled_at AS date, c.city, {seg} AS segment, {pref} AS channel
        FROM subscriptions s LEFT JOIN customers c USING (customer_id)""").df()
    df["date"] = pd.to_datetime(df["date"])
    ev = df.dropna(subset=["date"])
    # a dim with one value among subscribers (segment: all are 'predplatitel') is everyone
    # again, with an empty control
    dims = [d for d in dims if ev[d].nunique() > 1]
    if len(ev) >= MIN_EVENTS:
        _add_counts(ks, "cancellations", ev[["date", *dims]], dims)
    return set(df["customer_id"])


def _repeat(ks: KPISet, con, cust_cols: set, dims: list[str], pref_col: str) -> None:
    """Repeat-purchase rate: of the customers with an order in [d-90, d-30), the
    share who order again in [d-30, d). A churn KPI that does not depend on the
    inactivity estimate. It is dated at the end of the 30-day window, so a churn
    increase on day T starts to lower it on T, not 30 days earlier."""
    seg_col = "c.segment" if "segment" in cust_cols else "NULL"
    df = con.execute(f"""
        SELECT o.customer_id, o.order_date AS date, any_value(c.city) AS city,
               any_value({pref_col}) AS channel, any_value({seg_col}) AS segment
        FROM orders o LEFT JOIN customers c USING (customer_id) GROUP BY ALL""").df()
    if df.empty:
        return
    a, f = REPEAT_ACTIVE_DAYS, REPEAT_NEXT_DAYS
    n_days = len(ks.dates)
    if n_days <= a + f + 28:
        return
    cust, ci = np.unique(df["customer_id"].to_numpy(), return_inverse=True)
    day = (pd.to_datetime(df["date"]) - ks.dates[0]).dt.days.to_numpy()
    t = np.arange(a, n_days - f + 1)              # anchor: active in [t-a, t), buys in [t, t+f)
    idx = ks.dates[t + f - 1]                     # dated at the last day of the 30-day window
    info = df.groupby("customer_id")[[d for d in dims]].first().reindex(cust)

    ks.dims["repeat_rate"] = dims
    ks.valid_from["repeat_rate"] = idx[0]
    groups = [("", np.arange(len(cust)))]
    for keys in [(d,) for d in dims] + list(combinations(dims, 2)):
        for vals, g in info.groupby(list(keys)):
            vals = vals if isinstance(vals, tuple) else (vals,)
            groups.append((seg_text(keys, vals), np.flatnonzero(info.index.isin(g.index))))
    for (seg, rows), (num, den) in zip(groups, _repeat_counts(ci, day, len(cust), n_days, a, f, [r for _, r in groups])):
        if not len(rows) or den.mean() < REPEAT_MIN_ACTIVE:
            continue
        num_s, den_s = pd.Series(num, idx), pd.Series(den, idx)
        ks.parts[("repeat_rate", seg)] = (num_s, den_s)
        ks.series[("repeat_rate", seg)] = (num_s / den_s.where(den_s > 0)).interpolate(limit_direction="both")


def _repeat_counts(ci: np.ndarray, day: np.ndarray, n_cust: int, n_days: int, a: int, f: int,
                   groups: list[np.ndarray]):
    """(numerator, denominator) per group: customers with an order in [t-a, t) and those of them
    who order again in [t, t+f), for every anchor day t."""
    if rustk.LIB is not None:
        try:
            num, den = rustk.repeat_counts(ci, day, n_cust, n_days, a, f, groups)
        except ValueError:
            pass  # out-of-range input: the numpy path below raises its own error
        else:
            yield from zip(num, den)
            return
    # cum[i, t] = number of order days of customer i before day t
    cum = np.zeros((n_cust, n_days + 1), dtype=np.int16)
    np.add.at(cum, (ci, day + 1), 1)
    np.cumsum(cum, axis=1, out=cum)
    t = np.arange(a, n_days - f + 1)
    active = (cum[:, t] - cum[:, t - a]) > 0
    again = active & ((cum[:, t + f] - cum[:, t]) > 0)
    for rows in groups:
        yield again[rows].sum(0).astype(float), active[rows].sum(0).astype(float)


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
            if courier:
                # who delivers where, by order day: the courier assignment is a treatment
                # table, read for the anchor catalogue (scan.anchor_catalogue)
                ks.events["courier_assign"] = con.execute(
                    "SELECT o.order_date AS date, o.city, d.courier, count(*) AS n "
                    "FROM deliveries d JOIN orders o USING (order_id) GROUP BY ALL").df()
    r = have.get("reviews")
    if r and "rating" in r and (dc := date_col(r, "review_date", "created_date", "date")):
        join = "JOIN orders o USING (order_id)" if "order_id" in r else ""
        dims = ["city", "channel"] if join else []
        ev = con.execute(f"SELECT r.{dc} AS date, r.rating{', o.city, o.channel' if join else ''} "
                         f"FROM reviews r {join}").df()
        ev["date"] = pd.to_datetime(ev["date"])
        _add_ratio(ks, "rating_mean", ev, dims, "rating")
        # the share of 1-2 star reviews: a count of bad reviews out of all, so the DiD is a
        # binomial one (pooled log-odds) instead of a mean of a 1-5 scale
        _add_ratio(ks, "low_rating", ev.assign(low=(ev["rating"] <= 2).astype(float)), dims, "low")
    t = have.get("tickets")
    if t and (dc := date_col(t, "created_date", "ticket_date", "date", "opened_at")):
        topic = "t.topic" if "topic" in t else "NULL"
        ev = con.execute(f"SELECT CAST(t.{dc} AS DATE) AS date, {topic} AS topic FROM tickets t").df()
        ev["date"] = pd.to_datetime(ev["date"])
        _add_counts(ks, "tickets", ev, ["topic"] if "topic" in t else [], pairs=False)


def _add_ratio(ks: KPISet, kpi: str, ev: pd.DataFrame, dims: list[str], value: str) -> None:
    """Daily mean of `value`, overall and per dim value. Days without events are
    filled from the neighbours, so a quiet day is not a zero rating; that series is only
    for finding breaks. The tests use the parts: daily sum of `value` and number of events,
    0 on a day without events (DECISIONS 138)."""
    ks.events[kpi] = ev
    ks.dims[kpi] = dims
    for keys in [()] + [(x,) for x in dims]:
        groups = [((), ev)] if not keys else list(ev.groupby(list(keys)))
        for vals, g in groups:
            if len(g) < MIN_EVENTS:
                continue
            vals = vals if isinstance(vals, tuple) else (vals,)
            seg = seg_text(keys, vals) if keys else ""
            daily = g.groupby("date")[value].agg(["sum", "count"]).reindex(ks.dates, fill_value=0)
            ks.parts[(kpi, seg)] = (daily["sum"].astype(float), daily["count"].astype(float))
            s = g.groupby("date")[value].mean().reindex(ks.dates).interpolate(limit_direction="both")
            ks.series[(kpi, seg)] = s
