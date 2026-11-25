"""The verifier: is the story in the data? One specific hypothesis test per event.

    python -m s2d.verify data/a/ --twin data/a_nostory/      # table + SQL per event
    python -m s2d.verify curve examples/a.yaml --seeds 5     # confirmed share by difficulty

Unlike the detective, the verifier is not blind and does not search. For every
answer-key effect that was simulated it builds one test from the event itself:

    KPI      purchase_rate -> orders, churn_hazard -> leavers, acquisition_rate ->
             new customers (price_change also checks product_prices)
    treated  the event's target
    control  the same KPI in the other values of the same dimension (DECISIONS 37):
             Brno stores vs stores in the other cities, coffee vs the other categories
    windows  [T, T+28) vs [T-28, T), T = start + lag
    test     relative DiD, 95 % CI from a 7-day block bootstrap, placebo-in-time z
             (scan.did / scan.placebo_z, the detective's own functions)

Confirmed = CI excludes 0, direction as in the story, placebo z >= Z_CONFIRM.
Every test also comes as a readable DuckDB query a student can run on story.duckdb;
the verifier runs that query and checks it gives the same DiD as the Python test.
The same tests on the no-story twin should confirm nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

from s2d.detective import scan
from s2d.sim.events import ABSOLUTE_METRICS, DIFFICULTY_SCALE, compile_curve, daily_hazard
from s2d.spec import Effect, Event, EventType, StorySpec

WINDOW = scan.WINDOW          # 28 days before and after
MIN_AFTER = scan.MIN_AFTER    # an after-window shorter than this (data end) is not testable
Z_CONFIRM = 3.0               # placebo z needed to confirm
WARMUP_DAYS = 90              # leavers / new customers: the first days of the data are incomplete
LEAVER_EDGE_DAYS = 120        # a leaver has no order in the last 120 days of the data
LEAVER_MAX_GAP = 45          # leavers: only regular buyers (average gap <= 45 d); sparse ones blur the date
KEY_ORDER = ("supplier", "category", "city", "channel", "segment")  # the first key of a target is the one varied

KPI = {"purchase_rate": "orders", "churn_hazard": "leavers", "acquisition_rate": "new_customers",
       "delivery_days": "late_share", "rating_mean": "rating", "ticket_rate": "tickets"}
KPI_CS = {"orders": "objednávky", "leavers": "odchody zákazníků", "new_customers": "noví zákazníci",
          "late_share": "podíl pozdních zásilek", "rating": "průměrné hodnocení",
          "late_churn": "odchody po pozdní zásilce", "cancellations": "zrušená předplatná",
          "tickets": "tikety na podporu", "stockout_days": "podíl vyprodaných produktů"}
# Ratio KPIs: the daily value is a mean (late share in %, rating in points) and the DiD is a
# difference in those units, not a relative change (scan.did(ratio=True)).
RATIO = {"late_share": "pp", "rating": "b.", "stockout_days": "pp", "tickets": "/den"}
# Of those, the KPIs whose daily value is a mean of `val` (the rest are daily counts). Tickets
# are counts with a difference DiD: before a stockout there may be no sold-out ticket at all.
MEAN_KPIS = {"late_share", "rating", "stockout_days"}
# The ticket topic an emergent ticket_rate effect is about.
TICKET_TOPIC = {"supplier_delay": "vyprodáno", "stockout": "vyprodáno", "courier_change": "zpoždění"}
# Customer-level KPIs read city and channel from the customer (home channel, decision 17).
COLUMNS = {
    "orders": {"city": "o.city", "channel": "o.channel", "segment": "c.segment", "category": "p.category"},
    "leavers": {"city": "c.city", "channel": "c.preferred_channel", "segment": "c.segment"},
    "new_customers": {"city": "c.city", "channel": "c.preferred_channel", "segment": "c.segment"},
    "late_share": {"city": "c.city", "channel": "o.channel", "segment": "c.segment"},
    "rating": {"city": "c.city", "channel": "o.channel", "segment": "c.segment"},
    "cancellations": {"city": "c.city", "channel": "c.preferred_channel", "segment": "c.segment"},
    "tickets": {"supplier": "p.supplier_id", "category": "p.category", "city": "c.city",
                "channel": "c.preferred_channel", "segment": "c.segment"},
    "stockout_days": {"supplier": "p.supplier_id", "category": "p.category"},
}
# JOIN + lag (DECISIONS 70): a late parcel, then the customer leaves 30-60 days later.
LAG_FROM, LAG_TO = 30, 60
JOIN_BOOT = 400              # cluster bootstrap over customers


@dataclass
class Hypothesis:
    event_id: str
    type: str
    metric: str
    kpi: str
    segment: str                    # the target in answer-key form
    vary: str | None                # dimension whose other values are the control (None: no control)
    treated: list[str]              # values of `vary` in the treated group
    fixed: dict[str, list[str]]     # the rest of the target, the same in both groups
    start: date
    lag: int
    direction: str                  # expected direction of the KPI: up / down
    story_pct: float                # simulated plateau size, % (churn_shock: churn_pct)
    expected_pct: float | None      # the story's mean effect over the after-window, % of the KPI
    claim_cs: str
    price_pct: float | None = None
    dropped: list[str] = field(default_factory=list)  # target keys the KPI cannot split by
    unit: str = "%"                 # unit of story_pct / measured_pct: '%' relative, 'pp', 'b.' (points), 'd'
    on_days: int | None = None      # late_churn: days the courier switch lasts (cohort window)
    topic: str | None = None        # tickets: only this topic

    @property
    def T(self) -> date:
        return self.start + timedelta(days=self.lag)

    @property
    def ratio(self) -> bool:
        return self.kpi in RATIO


# ---------------------------------------------------------------- hypotheses


def _values(target, key: str) -> list[str]:
    return [v.value if hasattr(v, "value") else v for v in (getattr(target, key) or [])]


def hypothesis(spec: StorySpec, event: Event, effect: Effect) -> Hypothesis | None:
    metric = effect.metric.value
    kpi = KPI.get(metric)
    if kpi is None:
        return None
    subs = {sg.id for sg in spec.entities.customers.segments if sg.has_subscription}
    if kpi == "leavers" and event.target.segment and set(event.target.segment) <= subs:
        kpi = "cancellations"  # subscribers' churn is observed directly (DECISIONS 72)
    keys = [k for k in KEY_ORDER if _values(event.target, k)]
    dropped = [k for k in keys if k not in COLUMNS[kpi]]
    keys = [k for k in keys if k in COLUMNS[kpi]]
    vary = keys[0] if keys else None
    scale = DIFFICULTY_SCALE[spec.meta.difficulty]
    unit = "%"
    if event.type == EventType.churn_shock:
        story_pct = float(event.params.churn_pct)
        direction = "up"
    elif effect.metric in ABSOLUTE_METRICS:
        story_pct = float(effect.size)  # days late / rating points, not scaled (DECISIONS 67)
        direction = "up" if story_pct > 0 else "down"
        unit = "d" if kpi == "late_share" else "b."
    elif event.type in (EventType.courier_change, EventType.supplier_delay, EventType.stockout):
        story_pct = round(100 * effect.size, 4)  # emergent: the story's expectation, not scaled
        direction = "up" if story_pct > 0 else "down"
    else:
        story_pct = round(100 * effect.size * scale, 4)
        direction = "up" if story_pct > 0 else "down"
    h = Hypothesis(
        event_id=event.id, type=event.type.value, metric=metric, kpi=kpi,
        segment=event.target.describe(), vary=vary,
        treated=_values(event.target, vary) if vary else [],
        fixed={k: _values(event.target, k) for k in keys[1:]},
        start=event.start, lag=effect.lag_days, direction=direction, story_pct=story_pct,
        expected_pct=None, claim_cs=event.narrative_cs or "",
        price_pct=event.params.price_change_pct if event.type == EventType.price_change else None,
        dropped=dropped, unit=unit, topic=TICKET_TOPIC.get(event.type.value) if kpi == "tickets" else None)
    emergent = event.type in (EventType.courier_change, EventType.supplier_delay, EventType.stockout)
    h.expected_pct = None if h.ratio or emergent else _expected(spec, event, effect, h)
    return h


def stock_hypothesis(spec: StorySpec, event: Event, effect: Effect) -> Hypothesis | None:
    """A supplier_delay or stockout empties the shelves of its products: the share of the
    target products with zero stock (inventory_daily), against the other products. Built
    once per event (its first effect), at the same date as that effect's test."""
    if event.type not in (EventType.supplier_delay, EventType.stockout) or effect is not event.effects[0]:
        return None
    keys = [k for k in ("supplier", "category") if _values(event.target, k)]
    if not keys:
        return None
    return Hypothesis(
        event_id=event.id, type=event.type.value, metric="stock", kpi="stockout_days",
        segment=event.target.describe(), vary=keys[0], treated=_values(event.target, keys[0]),
        fixed={k: _values(event.target, k) for k in keys[1:]},
        start=event.start, lag=effect.lag_days, direction="up", story_pct=None, expected_pct=None,
        claim_cs=event.narrative_cs or "", unit="pp")


def join_lag_hypothesis(spec: StorySpec, event: Event, effect: Effect) -> Hypothesis | None:
    """A courier_change's churn effect, tested where it happens: deliveries in the target
    cities while the new courier runs, late vs on time, and whether the customer leaves
    30-60 days after that parcel (customers JOIN orders JOIN deliveries)."""
    if event.type != EventType.courier_change or effect.metric.value != "churn_hazard":
        return None
    from s2d.sim.service import courier_delay
    switch = next((e for e in [event] + [x for x in spec.events if x.id == event.caused_by]
                   if courier_delay(e) is not None), None)
    if switch is None:
        switch = next((e for e in spec.events if courier_delay(e) is not None
                       and (not e.target.city or set(event.target.city or []) <= set(e.target.city))), None)
    if switch is None:
        return None
    dd = next((e for e in switch.effects if e.metric.value == "delivery_days"), None)
    on = None if dd is None or dd.duration_days is None else dd.lag_days + dd.ramp_days + dd.duration_days
    return Hypothesis(
        event_id=event.id, type=event.type.value, metric=effect.metric.value, kpi="late_churn",
        segment=event.target.describe(), vary=None, treated=[],
        fixed={"city": _values(event.target, "city")} if event.target.city else {},
        start=switch.start, lag=0, direction="up", story_pct=round(100 * effect.size, 4),
        expected_pct=None, claim_cs=event.narrative_cs or "", unit="pp", on_days=on)


def _expected(spec: StorySpec, event: Event, effect: Effect, h: Hypothesis) -> float:
    """Mean effect of the story's curve over the after-window [T, T+28), in % of the KPI.
    Relative effects: size x mean(curve). churn_shock: added hazard / base hazard."""
    n = spec.meta.days
    i0 = (event.start - spec.meta.start).days
    iT = i0 + effect.lag_days
    if event.type == EventType.churn_shock:
        w = event.params.churn_window_days
        added = daily_hazard(event.params.churn_pct / 100, w)
        segs = [s for s in spec.entities.customers.segments
                if not event.target.segment or s.id in event.target.segment]
        share = sum(s.share for s in segs)
        p = sum(s.share * s.base_churn_per_month for s in segs) / share
        base = daily_hazard(p, 30.4)
        on = np.zeros(n)
        on[iT:iT + int(w)] = 1.0
        return round(100 * added / base * float(on[iT:iT + WINDOW].mean()), 2)
    curve = compile_curve(i0, effect, n)
    return round(h.story_pct * float(curve[iT:iT + WINDOW].mean()), 2)


def hypotheses(spec: StorySpec, key: pd.DataFrame | None = None) -> list[Hypothesis]:
    """One hypothesis per answer-key row with simulated = true (one per effect)."""
    simulated = None
    if key is not None:
        simulated = {(r.event_id, r.metric) for r in key.itertuples() if bool(r.simulated)}
    out = []
    for ev in spec.events:
        for eff in ev.effects:
            if simulated is not None and (ev.id, eff.metric.value) not in simulated:
                continue
            for h in (hypothesis(spec, ev, eff), join_lag_hypothesis(spec, ev, eff), stock_hypothesis(spec, ev, eff)):
                if h is not None:
                    out.append(h)
    return out


# ---------------------------------------------------------------- SQL


def _lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _in(col: str, values: list[str]) -> str:
    return f"{col} IN ({', '.join(_lit(v) for v in values)})"


def _d(x: date) -> str:
    return f"DATE '{x.isoformat()}'"


def _span(kpi: str, lo: date, hi: date) -> tuple[date, date]:
    """Days on which the KPI is complete."""
    if kpi == "orders":
        return lo, hi
    if kpi == "new_customers":
        return lo + timedelta(days=WARMUP_DAYS), hi
    if kpi in ("cancellations", "tickets", "stockout_days"):
        return lo, hi
    return lo + timedelta(days=WARMUP_DAYS), hi - timedelta(days=LEAVER_EDGE_DAYS)


def _group(h: Hypothesis) -> tuple[str, str]:
    """(CASE expression for the group, WHERE clause for the fixed part)."""
    cols = COLUMNS[h.kpi]
    grp = (f"CASE WHEN {_in(cols[h.vary], h.treated)} THEN 'treated' ELSE 'control' END"
           if h.vary else "'treated'")
    where = " AND ".join(_in(cols[k], v) for k, v in h.fixed.items()) or "TRUE"
    return grp, where


def _events_cte(h: Hypothesis, lo: date, hi: date) -> str:
    grp, where = _group(h)
    if h.kpi == "late_share":
        return f"""events AS (   -- one row per delivery, dated at the promised day; val = 100 if late
  SELECT d.promised_date AS day, 100.0 * CAST(d.late AS INTEGER) AS val,
         {grp} AS grp
  FROM deliveries d
  JOIN orders o USING (order_id)
  JOIN customers c USING (customer_id)
  WHERE d.late IS NOT NULL AND {where}
)"""
    if h.kpi == "rating":
        return f"""events AS (   -- one row per review
  SELECT r.review_date AS day, r.rating AS val,
         {grp} AS grp
  FROM reviews r
  JOIN orders o USING (order_id)
  JOIN customers c ON c.customer_id = r.customer_id
  WHERE {where}
)"""
    if h.kpi == "orders":
        uses_cat = h.vary == "category" or "category" in h.fixed
        if uses_cat:
            return f"""events AS (   -- one row per order and group (an order with coffee and accessories is in both)
  SELECT DISTINCT o.order_id, o.order_date AS day,
         {grp} AS grp
  FROM orders o
  JOIN order_items i USING (order_id)
  JOIN products p USING (product_id)
  JOIN customers c USING (customer_id)
  WHERE {where}
)"""
        return f"""events AS (   -- one row per order
  SELECT o.order_date AS day,
         {grp} AS grp
  FROM orders o
  JOIN customers c USING (customer_id)
  WHERE {where}
)"""
    if h.kpi == "tickets":
        topic = f"t.topic = {_lit(h.topic)}" if h.topic else "TRUE"
        return f"""events AS (   -- one row per ticket{f" about '{h.topic}'" if h.topic else ""}, dated at opening
  SELECT CAST(t.opened_at AS DATE) AS day,
         {grp} AS grp
  FROM tickets t
  JOIN customers c USING (customer_id)
  LEFT JOIN products p USING (product_id)
  WHERE {topic} AND {where}
)"""
    if h.kpi == "stockout_days":
        return f"""events AS (   -- one row per product and day; val = 100 if the product had no stock that day
  SELECT i.date AS day, 100.0 * CAST(i.stock_units = 0 AS INTEGER) AS val,
         {grp} AS grp
  FROM inventory_daily i
  JOIN products p USING (product_id)
  WHERE {where}
)"""
    if h.kpi == "cancellations":
        return f"""events AS (   -- one row per cancelled subscription, dated at cancellation
  SELECT s.cancelled_at AS day,
         {grp} AS grp
  FROM subscriptions s
  JOIN customers c USING (customer_id)
  WHERE s.cancelled_at IS NOT NULL AND {where}
)"""
    if h.kpi == "new_customers":
        return f"""events AS (   -- a new customer (signed up during the data), dated at the first order
  SELECT min(o.order_date) AS day,
         any_value({grp}) AS grp
  FROM orders o
  JOIN customers c USING (customer_id)
  WHERE c.signup_date >= {_d(lo)} AND {where}
  GROUP BY o.customer_id
)"""
    edge = hi - timedelta(days=LEAVER_EDGE_DAYS)
    return f"""per_customer AS (   -- last order and average gap between order days
  SELECT customer_id,
         max(order_date) AS last_order,
         (max(order_date) - min(order_date)) / nullif(count(DISTINCT order_date) - 1, 0) AS avg_gap
  FROM orders
  GROUP BY customer_id
),
events AS (   -- a leaver: a regular buyer (average gap <= {LEAVER_MAX_GAP} days) with no order in the
              -- last {LEAVER_EDGE_DAYS} days of the data; left one average gap after the last order
  SELECT CAST(p.last_order + CAST(round(p.avg_gap) AS INTEGER) AS DATE) AS day,
         {grp} AS grp
  FROM per_customer p
  JOIN customers c USING (customer_id)
  WHERE p.last_order < {_d(edge)} AND p.avg_gap <= {LEAVER_MAX_GAP} AND {where}
)"""


def _ctes(h: Hypothesis, lo: date, hi: date) -> str:
    s0, s1 = _span(h.kpi, lo, hi)
    agg = "avg(e.val)" if h.kpi in MEAN_KPIS else "count(e.grp)"
    control = (f"{agg} FILTER (WHERE e.grp = 'control')" if h.vary else "NULL")
    return f"""WITH {_events_cte(h, lo, hi)},
days AS (
  SELECT CAST(d AS DATE) AS day FROM range({_d(s0)}, {_d(s1 + timedelta(days=1))}, INTERVAL 1 DAY) t(d)
),
daily AS (   -- {KPI_CS[h.kpi]} per day: treated group and control group
  SELECT days.day,
         {agg} FILTER (WHERE e.grp = 'treated') AS treated,
         {control} AS control
  FROM days LEFT JOIN events e ON e.day = days.day
  GROUP BY days.day
)"""


def _windows(h: Hypothesis, s1: date) -> tuple[date, date, date]:
    T = h.T
    return T - timedelta(days=WINDOW), T, min(T + timedelta(days=WINDOW), s1 + timedelta(days=1))


def sql(h: Hypothesis, lo: date, hi: date) -> str:
    """The whole test as one query: daily series, window means, DiD in %."""
    b0, T, a1 = _windows(h, _span(h.kpi, lo, hi)[1])
    target = h.segment or "everyone"
    ctl = (f"{h.vary} not in ({', '.join(h.treated)})" + (f", same {', '.join(h.fixed)}" if h.fixed else "")
           if h.vary else "none: plain before/after")
    if h.ratio:  # difference in the KPI's own units (pp of late parcels, rating points, tickets a day)
        did = ("round((treated_after - treated_before) - (control_after - control_before), 2)"
               if h.vary else "round(treated_after - treated_before, 2)")
    else:
        did = ("round(100 * ((treated_after / treated_before) / (control_after / control_before) - 1), 2)"
               if h.vary else "round(100 * (treated_after / treated_before - 1), 2)")
    return f"""-- {h.event_id} ({h.type}): {KPI_CS[h.kpi]}, {target}
-- control: {ctl}
-- before {b0} .. {T - timedelta(days=1)}, after {T} .. {a1 - timedelta(days=1)}
{_ctes(h, lo, hi)},
windows AS (
  SELECT avg(treated) FILTER (WHERE day >= {_d(b0)} AND day < {_d(T)}) AS treated_before,
         avg(treated) FILTER (WHERE day >= {_d(T)} AND day < {_d(a1)}) AS treated_after,
         avg(control) FILTER (WHERE day >= {_d(b0)} AND day < {_d(T)}) AS control_before,
         avg(control) FILTER (WHERE day >= {_d(T)} AND day < {_d(a1)}) AS control_after
  FROM daily
)
SELECT round(treated_before, 2) AS treated_before, round(treated_after, 2) AS treated_after,
       round(control_before, 2) AS control_before, round(control_after, 2) AS control_after,
       round(100 * (treated_after / treated_before - 1), 2) AS treated_change_pct,
       round(100 * (control_after / control_before - 1), 2) AS control_change_pct,
       {did} AS did_pct
FROM windows"""


def price_sql(h: Hypothesis) -> str:
    """Mean price change of the target's products from the day before start to start."""
    cats = f"WHERE {_in('pr.category', h.treated)}" if h.vary == "category" else ""
    day0, day1 = h.start - timedelta(days=1), h.start
    return f"""-- {h.event_id}: prices of the affected products, day before vs start
WITH p AS (
  SELECT pr.product_id,
         max(pp.price) FILTER (WHERE {_d(day0)} BETWEEN pp.valid_from AND coalesce(pp.valid_to, DATE '9999-12-31')) AS before,
         max(pp.price) FILTER (WHERE {_d(day1)} BETWEEN pp.valid_from AND coalesce(pp.valid_to, DATE '9999-12-31')) AS after
  FROM products pr JOIN product_prices pp USING (product_id)
  {cats}
  GROUP BY pr.product_id
)
SELECT count(*) AS products, round(100 * (avg(after / before) - 1), 2) AS price_change_pct FROM p"""


def delay_sql(h: Hypothesis) -> str:
    """Mean delay (delivered - promised, days) of the target's deliveries vs the others,
    28 days after start vs 28 before: comparable with the story's delivery_days."""
    grp, where = _group(h)
    T = h.T
    b0, a1 = T - timedelta(days=WINDOW), T + timedelta(days=WINDOW)
    return f"""-- {h.event_id}: mean delay in days, after vs before {T}
WITH d AS (
  SELECT {grp} AS grp, d.promised_date >= {_d(T)} AS after, d.delivered_date - d.promised_date AS delay
  FROM deliveries d JOIN orders o USING (order_id) JOIN customers c USING (customer_id)
  WHERE d.delivered_date IS NOT NULL AND d.promised_date >= {_d(b0)} AND d.promised_date < {_d(a1)} AND {where}
), m AS (
  SELECT avg(delay) FILTER (WHERE grp = 'treated' AND after) - avg(delay) FILTER (WHERE grp = 'treated' AND NOT after) AS t,
         avg(delay) FILTER (WHERE grp = 'control' AND after) - avg(delay) FILTER (WHERE grp = 'control' AND NOT after) AS c
  FROM d
)
SELECT round(t, 2) AS treated_change_days, round(c, 2) AS control_change_days, round(t - coalesce(c, 0), 2) AS did_days FROM m"""


def _join_windows(h: Hypothesis, hi: date) -> tuple[date, date, date]:
    """(before start, switch start, after end): deliveries in [start, end) are the cohort, the
    same length before it is the placebo period. The data must run LEAVER_EDGE_DAYS past end
    so that "no later order" means something."""
    days = h.on_days or 120
    end = min(h.start + timedelta(days=days), hi - timedelta(days=LEAVER_EDGE_DAYS))
    length = (end - h.start).days
    return h.start - timedelta(days=length), h.start, end


def join_lag_cte(h: Hypothesis, hi: date) -> str:
    b0, s0, a1 = _join_windows(h, hi)
    where = " AND ".join(_in(f"c.{k}", v) for k, v in h.fixed.items()) or "TRUE"
    return f"""WITH ranked AS (   -- each order with the customer's first and last order day and order days so far
  SELECT o.order_id, o.customer_id, o.order_date,
         min(o.order_date) OVER (PARTITION BY o.customer_id) AS first_order,
         max(o.order_date) OVER (PARTITION BY o.customer_id) AS last_order,
         dense_rank() OVER (PARTITION BY o.customer_id ORDER BY o.order_date) AS order_days
  FROM orders o
),
cohort AS (   -- customers JOIN orders JOIN deliveries: one row per delivered parcel
  SELECT d.delivery_id, r.customer_id, d.delivered_date, d.late,
         CASE WHEN d.delivered_date >= {_d(s0)} THEN 'after' ELSE 'before' END AS period,
         -- left {LAG_FROM}-{LAG_TO} days later: this was the customer's last order, and one average
         -- gap after it (when the next order was due) falls {LAG_FROM}-{LAG_TO} days after the parcel
         CASE WHEN r.order_date = r.last_order AND r.order_days >= 2
                   AND r.order_date + CAST(round((r.order_date - r.first_order) / nullif(r.order_days - 1, 0)) AS INTEGER)
                       BETWEEN d.delivered_date + {LAG_FROM} AND d.delivered_date + {LAG_TO}
              THEN 1 ELSE 0 END AS left_{LAG_FROM}_{LAG_TO}
  FROM deliveries d
  JOIN ranked r USING (order_id)
  JOIN customers c ON c.customer_id = r.customer_id
  WHERE d.late IS NOT NULL AND {where}
    AND d.delivered_date >= {_d(b0)} AND d.delivered_date < {_d(a1)}
)"""


def join_lag_sql(h: Hypothesis, hi: date) -> str:
    b0, s0, a1 = _join_windows(h, hi)
    target = h.segment or "everyone"
    col = f"left_{LAG_FROM}_{LAG_TO}"
    return f"""-- {h.event_id} ({h.type}): did a late parcel make its customer leave {LAG_FROM}-{LAG_TO} days later?
-- target: {target}; parcels delivered {s0} .. {a1 - timedelta(days=1)} (new courier),
-- placebo: the same comparison {b0} .. {s0 - timedelta(days=1)} (old courier)
{join_lag_cte(h, hi)},
groups AS (
  SELECT period,
         count(*) FILTER (WHERE late) AS late_parcels,
         100 * avg({col}) FILTER (WHERE late) AS late_left_pct,
         count(*) FILTER (WHERE NOT late) AS on_time_parcels,
         100 * avg({col}) FILTER (WHERE NOT late) AS on_time_left_pct
  FROM cohort GROUP BY period
)
SELECT period, late_parcels, round(late_left_pct, 2) AS late_left_pct,
       on_time_parcels, round(on_time_left_pct, 2) AS on_time_left_pct,
       round(late_left_pct - on_time_left_pct, 2) AS did_pct,     -- difference, percentage points
       round(late_left_pct / nullif(on_time_left_pct, 0), 2) AS ratio
FROM groups ORDER BY period DESC"""


def _diff_stats(df: pd.DataFrame, rng: np.random.Generator) -> tuple[float, float, float, float]:
    """Late minus on-time share leaving (pp), 95 % CI and SE from a bootstrap over customers
    (a customer's parcels are not independent)."""
    col = f"left_{LAG_FROM}_{LAG_TO}"
    late = df["late"].to_numpy(bool)
    y = df[col].to_numpy(float)
    point = 100 * (y[late].mean() - y[~late].mean()) if late.any() and (~late).any() else float("nan")
    cust, inv = np.unique(df["customer_id"].to_numpy(), return_inverse=True)
    # per customer sums, so one bootstrap draw is a weighted sum over customers
    sl = np.bincount(inv, weights=y * late, minlength=len(cust))
    nl = np.bincount(inv, weights=late.astype(float), minlength=len(cust))
    so = np.bincount(inv, weights=y * ~late, minlength=len(cust))
    no = np.bincount(inv, weights=(~late).astype(float), minlength=len(cust))
    w = rng.multinomial(len(cust), np.full(len(cust), 1 / len(cust)), size=JOIN_BOOT).astype(float)
    boot = 100 * (w @ sl / np.maximum(w @ nl, 1) - w @ so / np.maximum(w @ no, 1))
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(point), float(lo), float(hi), float(np.std(boot)) or 1e-9


def test_join_lag(con, h: Hypothesis, lo: date, hi: date, seed: int = 0, check_sql: bool = True) -> dict:
    b0, s0, a1 = _join_windows(h, hi)
    out = {"event_id": h.event_id, "metric": h.metric, "kpi": h.kpi, "segment": h.segment,
           "control": "včas doručené zásilky (on-time parcels)", "T": h.start.isoformat(), "direction": h.direction,
           "story_pct": h.story_pct, "expected_pct": None, "claim_cs": h.claim_cs,
           "unit": "%", "measured_unit": "pp", "confirmed": False, "status": "not_testable"}
    if a1 <= s0:
        return out
    df = con.execute(join_lag_cte(h, hi) + "\nSELECT customer_id, period, late, delivered_date, "
                     f"left_{LAG_FROM}_{LAG_TO} FROM cohort").df()
    rng = np.random.default_rng(seed)
    after, before = df[df["period"] == "after"], df[df["period"] == "before"]
    if after["late"].sum() < 30 or (~after["late"].astype(bool)).sum() < 30:
        return out
    point, lo_ci, hi_ci, se = _diff_stats(after, rng)
    z = abs(point) / se
    b_point, b_lo, b_hi, b_se = _diff_stats(before, rng) if before["late"].sum() >= 30 else (float("nan"),) * 4
    excludes = lo_ci > 0 or hi_ci < 0
    confirmed = bool(point > 0 and excludes and z >= Z_CONFIRM)
    col = f"left_{LAG_FROM}_{LAG_TO}"
    a_late = after[after["late"].astype(bool)][col]
    a_on = after[~after["late"].astype(bool)][col]
    out.update(
        measured_pct=round(point, 2), ci_pct=[round(lo_ci, 2), round(hi_ci, 2)], z=round(z, 2),
        right_direction=bool(point > 0), ci_excludes_0=bool(excludes), confirmed=confirmed,
        status="confirmed" if confirmed else "not_confirmed",
        before=[b0.isoformat(), (s0 - timedelta(days=1)).isoformat()],
        after=[s0.isoformat(), (a1 - timedelta(days=1)).isoformat()],
        groups={"late_parcels": int(len(a_late)), "late_left_pct": round(100 * a_late.mean(), 2),
                "on_time_parcels": int(len(a_on)), "on_time_left_pct": round(100 * a_on.mean(), 2),
                "ratio": round(a_late.mean() / a_on.mean(), 2) if a_on.mean() > 0 else None},
        placebo_before={"diff_pp": None if np.isnan(b_point) else round(b_point, 2),
                        "ci_pct": None if np.isnan(b_point) else [round(b_lo, 2), round(b_hi, 2)],
                        "z": None if np.isnan(b_point) else round(abs(b_point) / b_se, 2)},
        sql=join_lag_sql(h, hi), offsets=offset_histogram(con, h, hi))
    if check_sql:
        res = con.execute(out["sql"]).df()
        row = res[res["period"] == "after"].iloc[0]
        out["sql_result"] = {k: (None if pd.isna(v) else (v if isinstance(v, str) else float(v)))
                             for k, v in row.items()}
        out["sql_rows"] = res.to_dict("records")
        out["sql_matches"] = bool(abs(float(row["did_pct"]) - point) < 0.006)
    return out


OFFSET_BIN = 10
OFFSET_MAX = 150


def offset_histogram(con, h: Hypothesis, hi: date) -> dict:
    """% of parcels (per group) after which the customer left, by days from the parcel to the
    estimated departure, in OFFSET_BIN-day bins: where the 30-60 days come from."""
    df = departure_offsets(con, h, hi)
    edges = np.arange(0, OFFSET_MAX + OFFSET_BIN, OFFSET_BIN)
    out = {"bin_start": edges[:-1].tolist()}
    for name, late in (("late", True), ("on_time", False)):
        g = df[df["late"].astype(bool) == late]
        n = len(g)
        counts, _ = np.histogram(g["offset"].dropna(), bins=edges)
        out[name] = (100 * counts / max(n, 1)).round(3).tolist()
        out[f"{name}_parcels"] = n
    return out


def departure_offsets(con, h: Hypothesis, hi: date) -> pd.DataFrame:
    """For the chart: days from each parcel (cohort, after period) to the customer's estimated
    departure (last order + one average gap), for parcels after which the customer never ordered
    again. Columns: late, offset, parcels_in_group."""
    q = join_lag_cte(h, hi) + """,
est AS (
  SELECT d.delivery_id, d.late,
         r.order_date + CAST(round((r.order_date - r.first_order) / nullif(r.order_days - 1, 0)) AS INTEGER) - d.delivered_date AS offset
  FROM cohort k JOIN deliveries d USING (delivery_id) JOIN ranked r USING (order_id)
  WHERE k.period = 'after' AND r.order_date = r.last_order AND r.order_days >= 2
)
SELECT k.late, e.offset, count(*) OVER (PARTITION BY k.late) AS parcels_in_group
FROM cohort k LEFT JOIN est e USING (delivery_id) WHERE k.period = 'after'"""
    return con.execute(q).df()


# ---------------------------------------------------------------- the test


def series(con, h: Hypothesis, lo: date, hi: date) -> pd.DataFrame:
    df = con.execute(_ctes(h, lo, hi) + "\nSELECT day, treated, control FROM daily ORDER BY day").df()
    df["day"] = pd.to_datetime(df["day"])
    return df


def statistic(df: pd.DataFrame, h: Hypothesis) -> tuple[np.ndarray, np.ndarray | None, int, int] | None:
    """(treated, control, index of T, after-window length) or None if not testable."""
    seg = df["treated"].to_numpy(float)
    rest = df["control"].to_numpy(float) if h.vary else None
    hit = np.flatnonzero(df["day"].to_numpy() == np.datetime64(h.T))
    if not len(hit):
        return None
    iT = int(hit[0])
    na = min(WINDOW, len(seg) - iT)
    if iT < WINDOW or na < MIN_AFTER:
        return None
    return seg, rest, iT, na


def null_effects(seg, rest, iT: int, na: int, ratio: bool = False) -> np.ndarray:
    """The DiD at every anchor more than 2 windows away from T: the placebo-in-time null."""
    t, e = scan.did_effects(seg, rest, 0, WINDOW, na, ratio)
    return e[np.abs(t - iT) > 2 * WINDOW]


def test(con, h: Hypothesis, lo: date, hi: date, seed: int = 0, check_sql: bool = True) -> dict:
    if h.kpi == "late_churn":
        return test_join_lag(con, h, lo, hi, seed, check_sql)
    df = series(con, h, lo, hi)
    out = {"event_id": h.event_id, "metric": h.metric, "kpi": h.kpi, "segment": h.segment,
           "control": (f"{h.vary} ∉ {{{', '.join(h.treated)}}}" if h.vary else None),
           "T": h.T.isoformat(), "direction": h.direction,
           "story_pct": h.story_pct, "expected_pct": h.expected_pct, "claim_cs": h.claim_cs,
           "unit": h.unit, "measured_unit": RATIO.get(h.kpi, "%"),
           "confirmed": False, "status": "not_testable"}
    st = statistic(df, h)
    if st is None:
        return out
    seg, rest, iT, na = st
    before, after = slice(iT - WINDOW, iT), slice(iT, iT + na)
    k = 1.0 if h.ratio else 100.0
    point, (lo_ci, hi_ci), _ = scan.did(seg, rest, before, after, np.random.default_rng(seed), ratio=h.ratio)
    z = scan.placebo_z(seg, rest, iT, iT, WINDOW, na, ratio=h.ratio)
    sign = 1 if h.direction == "up" else -1
    right_way = sign * point > 0
    excludes = lo_ci > 0 or hi_ci < 0
    confirmed = bool(right_way and excludes and z >= Z_CONFIRM)
    null = null_effects(seg, rest, iT, na, h.ratio)
    med = np.median(null)
    p = float(np.mean(np.abs(null - med) >= abs(point - med)))  # share of placebo dates at least as extreme
    out.update(
        measured_pct=round(k * point, 2), ci_pct=[round(k * lo_ci, 2), round(k * hi_ci, 2)],
        z=round(z, 2), p_placebo=round(p, 4), right_direction=bool(right_way), ci_excludes_0=bool(excludes),
        confirmed=confirmed, status="confirmed" if confirmed else "not_confirmed",
        before=[str(df["day"].iloc[iT - WINDOW].date()), str(df["day"].iloc[iT - 1].date())],
        after=[str(df["day"].iloc[iT].date()), str(df["day"].iloc[iT + na - 1].date())],
        series={"day": [str(d.date()) for d in df["day"]], "treated": seg.tolist(),
                "control": None if rest is None else rest.tolist()},
        sql=sql(h, lo, hi))
    if check_sql:
        row = con.execute(out["sql"]).df().iloc[0]
        out["sql_result"] = {k: (None if pd.isna(v) else float(v)) for k, v in row.items()}
        out["sql_matches"] = bool(abs(float(row["did_pct"]) - k * point) < 0.006)
    if h.price_pct is not None and h.vary == "category":
        q = price_sql(h)
        r = con.execute(q).fetchone()
        out["price"] = {"story_pct": h.price_pct, "measured_pct": r[1], "products": r[0], "sql": q}
    if h.kpi == "late_share":
        q = delay_sql(h)
        r = con.execute(q).fetchone()
        out["delay"] = {"story_days": h.story_pct, "treated_days": r[0], "control_days": r[1],
                        "did_days": r[2], "sql": q}
    return out


# ---------------------------------------------------------------- runs


def _range(con) -> tuple[date, date]:
    lo, hi = con.execute("SELECT min(order_date), max(order_date) FROM orders").fetchone()
    return lo, hi


def verify_con(con, spec: StorySpec, key: pd.DataFrame | None, twin_con=None, check_sql: bool = True) -> dict:
    hyps = hypotheses(spec, key)
    lo, hi = _range(con)
    rows = [test(con, h, lo, hi, check_sql=check_sql) for h in hyps]
    res = {"tests": rows, "n": len(rows), "confirmed": sum(r["confirmed"] for r in rows)}
    if twin_con is not None:
        tlo, thi = _range(twin_con)
        twin = [test(twin_con, h, tlo, thi, check_sql=check_sql) for h in hyps]
        for r, t in zip(rows, twin):
            r["twin"] = {k: t.get(k) for k in ("measured_pct", "ci_pct", "z", "p_placebo", "confirmed",
                                                 "status", "series", "sql_matches", "groups", "offsets",
                                                 "placebo_before", "sql_result")}
        res["twin_confirmed"] = sum(t["confirmed"] for t in twin)
    return res


def load_run(run_dir: str | Path) -> tuple[duckdb.DuckDBPyConnection, StorySpec, pd.DataFrame]:
    con = duckdb.connect(str(Path(run_dir) / "story.duckdb"), read_only=True)
    spec_yaml = con.execute("SELECT spec_yaml FROM _truth.spec_yaml").fetchone()[0]
    spec = StorySpec.model_validate(yaml.safe_load(spec_yaml))
    key = con.execute("SELECT * FROM _truth.answer_key").df()
    return con, spec, key


def verify(run_dir: str | Path, twin_dir: str | Path | None = None) -> dict:
    con, spec, key = load_run(run_dir)
    twin_con = duckdb.connect(str(Path(twin_dir) / "story.duckdb"), read_only=True) if twin_dir else None
    res = verify_con(con, spec, key, twin_con)
    res["run_dir"] = str(run_dir)
    res["twin_dir"] = str(twin_dir) if twin_dir else None
    return res


def world_con(world) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with a simulated world's analyst tables (no files)."""
    from s2d.sim.output import DATE_COLUMNS
    con = duckdb.connect()
    for name, df in world.tables.items():
        df = df.copy()
        for col in DATE_COLUMNS & set(df.columns):
            df[col] = pd.to_datetime(df[col]).dt.date
        con.register("_df", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _df")
        con.unregister("_df")
    return con


# ---------------------------------------------------------------- text


def _fmt(v, unit=" %") -> str:
    return "–" if v is None else f"{v:+.1f}{unit}"


def summary_line(res: dict) -> str:
    line = f"story: {res['confirmed']}/{res['n']} confirmed"
    if "twin_confirmed" in res:
        line += f", twin: {res['twin_confirmed']}/{res['n']}"
    return line


def _u(v, unit: str) -> str:
    if v is None:
        return "–"
    return f"{v:+.1f} %" if unit == "%" else f"{v:+.2f} {unit}"


def format_table(res: dict) -> str:
    head = f"{'event':<5} {'KPI':<14} {'target':<30} {'T':<10} {'story':>9} {'in window':>9} " \
           f"{'measured':>10} {'95% CI':>17} {'z':>6}  {'':2} {'twin':>10} {'twin z':>6} {'':2}"
    lines = [head, "-" * len(head)]
    for r in res["tests"]:
        mu = r.get("measured_unit", "%")
        ci = f"[{r['ci_pct'][0]:+.1f}, {r['ci_pct'][1]:+.1f}]" if r.get("ci_pct") else "–"
        tw = r.get("twin", {})
        lines.append(
            f"{r['event_id']:<5} {r['kpi']:<14} {r['segment'] or 'everyone':<30} {r['T']:<10} "
            f"{_u(r['story_pct'], r.get('unit', '%')):>9} {_u(r['expected_pct'], '%'):>9} "
            f"{_u(r.get('measured_pct'), mu):>10} {ci:>17} "
            f"{r.get('z', float('nan')):>6.2f}  {'✅' if r['confirmed'] else '❌'} "
            f"{_u(tw.get('measured_pct'), mu) if tw else '':>10} "
            f"{tw.get('z') if tw.get('z') is not None else float('nan'):>6.2f} "
            f"{('✅' if tw.get('confirmed') else '❌') if tw else ''}")
        if "price" in r:
            lines.append(f"      prices of {r['segment']}: {_fmt(r['price']['measured_pct'])} "
                         f"(story {_fmt(r['price']['story_pct'])}, {r['price']['products']} products)")
        if "delay" in r:
            lines.append(f"      mean delay: {_u(r['delay']['did_days'], 'd')} against the control "
                         f"(story {_u(r['delay']['story_days'], 'd')})")
        if "groups" in r:
            g, pb = r["groups"], r["placebo_before"]
            lines.append(f"      left {LAG_FROM}-{LAG_TO} d after the parcel: late {g['late_left_pct']:.1f} % "
                         f"of {g['late_parcels']}, on time {g['on_time_left_pct']:.1f} % of {g['on_time_parcels']} "
                         f"(x{g['ratio']}); same test before the switch: {_u(pb['diff_pp'], 'pp')} z {pb['z']}")
        if "sql_matches" in r and r["sql_result"].get("did_pct") is None:
            m = r.get("measured_pct")
            lines.append("      SQL gives no result " + ("(the event window is not measurable)" if m is None or m != m
                                                         else f"but the test measured {_u(m, mu)}: MISMATCH"))
        elif "sql_matches" in r:
            lines.append(f"      SQL gives {r['sql_result']['did_pct']:+.2f} {mu}: "
                         f"{'same as the test' if r['sql_matches'] else 'MISMATCH'}")
    lines.append(summary_line(res))
    return "\n".join(lines)


def narrative_cs(res: dict) -> str:
    """Czech description of the confirmed events only (template: every number from the table)."""
    verbs = {("orders", "down"): "klesly", ("orders", "up"): "vzrostly",
             ("late_share", "up"): "přibylo pozdních zásilek", ("late_share", "down"): "ubylo pozdních zásilek",
             ("rating", "down"): "kleslo průměrné hodnocení", ("rating", "up"): "stouplo průměrné hodnocení",
             ("late_churn", "up"): "odcházelo víc zákazníků po pozdní zásilce",
             ("cancellations", "up"): "přibylo zrušených předplatných",
             ("tickets", "up"): "přibylo tiketů na podporu", ("tickets", "down"): "ubylo tiketů na podporu",
             ("stockout_days", "up"): "přibylo vyprodaných produktů",
             ("cancellations", "down"): "ubylo zrušených předplatných",
             ("leavers", "up"): "přibylo odchodů zákazníků", ("leavers", "down"): "ubylo odchodů zákazníků",
             ("new_customers", "up"): "přibylo nových zákazníků", ("new_customers", "down"): "ubylo nových zákazníků"}
    out = []
    for r in sorted((r for r in res["tests"] if r["confirmed"]), key=lambda r: r["T"]):
        who = _segment_cs(r["segment"])
        what = verbs[(r["kpi"], r["direction"])]
        mu = r.get("measured_unit", "%")
        size = (f"o {abs(r['measured_pct']):.0f} %" if mu == "%" else
                f"o {abs(r['measured_pct']):.1f} p. b." if mu == "pp" else f"o {abs(r['measured_pct']):.2f} bodu")
        if r["kpi"] == "late_churn":
            g = r["groups"]
            s = (f"Od {_date_cs(r['T'])} {_segment_cs(r['segment'])} odešlo {LAG_FROM}–{LAG_TO} dní po pozdní zásilce "
                 f"{g['late_left_pct']:.1f} % zákazníků, po včasné {g['on_time_left_pct']:.1f} % (z = {r['z']:.1f}). "
                 f"{r['claim_cs']}".rstrip())
            out.append(s)
            continue
        if r["kpi"] == "orders":
            s = f"Od {_date_cs(r['T'])} {what} objednávky {who} {size} oproti kontrolní skupině"
        else:
            s = f"Od {_date_cs(r['T'])} {what} {who} ({size} oproti kontrolní skupině)"
        s += f" (z = {r['z']:.1f}). {r['claim_cs']}".rstrip()
        if "price" in r:
            s += f" Ceny dotčených produktů vzrostly o {r['price']['measured_pct']:.0f} %."
        out.append(s)
    return " ".join(out) if out else "Žádná událost příběhu se v datech nepotvrdila."


def narrate(res: dict, on_status=None) -> dict:
    """The narrator for confirmed events only: one LLM call that rewrites the template
    into a short Czech story. Only the confirmed rows go into the prompt, so nothing
    else can be told. Falls back to the template."""
    from s2d import llm
    template = narrative_cs(res)
    rows = [r for r in res["tests"] if r["confirmed"]]
    if not rows:
        return {"text": template, "source": "template (nothing confirmed)"}
    facts = "\n".join(json.dumps({k: r.get(k) for k in ("event_id", "claim_cs", "kpi", "segment", "T",
                                                         "measured_pct", "ci_pct", "z")}
                                   | ({"price_pct": r["price"]["measured_pct"]} if "price" in r else {}),
                                   ensure_ascii=False) for r in rows)
    prompt = f"""Jsi datový analytik. Tyto události příběhu firmy byly v datech potvrzeny testem
(rozdíl v rozdílech proti kontrolní skupině, 28 dní po vs. 28 dní před):
{facts}

Napiš 3 až 5 vět česky: co se stalo, kdy, u koho a jak velký byl naměřený efekt.
Pravidla: jen tyto události, žádné jiné. Každé datum a číslo musí pocházet z tabulky.
Nevymýšlej příčiny, které nejsou v claim_cs. Odpověz jen textem."""
    try:
        text = str(llm.complete("detective", prompt, on_status=on_status)).strip()
        if not text:
            raise ValueError("empty")
        info = llm.last_call()
        return {"text": text, "source": f"{info.backend} {info.model}" + (" (cache)" if info.cached else ""),
                "template": template}
    except (llm.LLMError, ValueError) as e:
        return {"text": template, "source": f"template (LLM failed: {e})"}


def _date_cs(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day}. {d.month}. {d.year}"


def _segment_cs(seg: str) -> str:
    if not seg:
        return "u všech zákazníků"
    parts = []
    for p in seg.split(";"):
        k, v = p.split("=", 1)
        v = v.replace(",", ", ")
        parts.append({"city": f"ve městě {v}", "segment": f"v segmentu {v}", "category": f"v kategoriích {v}",
                      "channel": f"v kanálu {v}"}.get(k, p))
    return " ".join(parts)


# ---------------------------------------------------------------- curve


def _curve_level(spec_path: str, level: str, seeds: list[int], n: int, cal_seed: int) -> dict:
    from s2d.calibrate import calibrate
    from s2d.sim import simulate, without_story
    from s2d.spec import Difficulty, load_spec
    spec = load_spec(spec_path)
    spec.entities.customers.n = n
    spec.meta.difficulty = Difficulty(level)
    spec, table = calibrate(spec, seed=cal_seed, log=lambda m: None)
    runs = []
    for seed in seeds:
        world = simulate(spec, seed=seed)
        twin = simulate(without_story(spec), seed=seed)
        res = verify_con(world_con(world), spec, world.truth["answer_key"], world_con(twin), check_sql=False)
        runs.append({"seed": seed, **{r["event_id"] + "_" + r["kpi"]: (r["confirmed"], r.get("z"),
                                                                     r["twin"]["confirmed"], r["twin"].get("z"))
                                      for r in res["tests"]},
                     "story": res["confirmed"], "twin": res["twin_confirmed"], "n": res["n"]})
        print(json.dumps({"level": level, **runs[-1]}, default=str), file=sys.stderr)
    tot = sum(r["n"] for r in runs)
    return {"level": level, "runs": runs, "calibration": table.to_dict("records"),
            "story_share": round(sum(r["story"] for r in runs) / tot, 3),
            "twin_share": round(sum(r["twin"] for r in runs) / tot, 3)}


def curve(spec_path: str, out_png: str, seeds: list[int], n: int = 40000, cal_seed: int = 0) -> dict:
    """Confirmed share, story vs twin, per difficulty. Calibrated once per level (on
    cal_seed + calibrate.SEED_OFFSET, not one of the run seeds), then every seed is
    simulated with that spec."""
    from concurrent.futures import ProcessPoolExecutor
    levels = ["easy", "medium", "hard"]
    with ProcessPoolExecutor(len(levels)) as ex:
        res = dict(zip(levels, ex.map(_curve_level, [spec_path] * 3, levels, [seeds] * 3, [n] * 3, [cal_seed] * 3)))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(levels, [res[lv]["story_share"] for lv in levels], "o-", label="story")
    ax.plot(levels, [res[lv]["twin_share"] for lv in levels], "s--", label="no-story twin")
    ax.axhline(0.9, color="#999", lw=0.8, ls=":")
    ax.axhline(0.1, color="#999", lw=0.8, ls=":")
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("difficulty (target z 5 / 3.5 / 2.5)")
    ax.set_ylabel("share of event tests confirmed")
    ax.set_title(f"{Path(spec_path).stem}: verifier, {len(seeds)} seeds, {n} customers")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120)
    return res


# ---------------------------------------------------------------- CLI


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "curve":
        p = argparse.ArgumentParser(prog="python -m s2d.verify curve")
        p.add_argument("spec")
        p.add_argument("--seeds", type=int, default=5)
        p.add_argument("--first-seed", type=int, default=1)
        p.add_argument("--n-customers", type=int, default=40000)
        p.add_argument("--out", default="docs/verify_curve.png")
        p.add_argument("--json")
        a = p.parse_args(argv[1:])
        res = curve(a.spec, a.out, list(range(a.first_seed, a.first_seed + a.seeds)), a.n_customers)
        for lv, r in res.items():
            print(f"{lv:<7} story {r['story_share']:.0%}  twin {r['twin_share']:.0%}")
        if a.json:
            Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), "utf-8")
        print(f"wrote {a.out}")
        return 0
    p = argparse.ArgumentParser(prog="python -m s2d.verify")
    p.add_argument("run_dir")
    p.add_argument("--twin")
    p.add_argument("--sql", action="store_true", help="print the SQL of every test")
    p.add_argument("--out", help="write the result JSON here")
    p.add_argument("--narrate", action="store_true", help="Czech story of the confirmed events (LLM, template fallback)")
    a = p.parse_args(argv)
    res = verify(a.run_dir, a.twin)
    print(format_table(res))
    if a.narrate:
        res["narration"] = narrate(res)
        print(f"\n{res['narration']['text']}\n({res['narration']['source']})")
    if a.sql:
        for r in res["tests"]:
            if r.get("sql"):
                print("\n" + r["sql"] + ";")
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
