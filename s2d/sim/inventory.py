"""Stock: what is on the shelf, what is on its way from the suppliers, and what
happens when something runs out.

Every supplier is reviewed once a week (periodic review, order-up-to): for each of its
products it orders up to

    S = demand · (lead_time + REVIEW_DAYS + safety_days)      minus stock and what is on its way

where `demand` is a running estimate of units a day (sold plus lost, so a stockout does
not hide demand). A shipment arrives after the supplier's lead time; with probability
1 - reliability it is late by another 0.3-1.0 lead times.

Story events:
    supplier_delay   shipments of the target suppliers arriving while it is on take
                     lead_time_multiplier x as long (also those already on their way).
                     It does not stop sales by itself: the shelf runs empty when the
                     stock and the pipeline run out, a few days to weeks later.
    stockout         the target products cannot be sold while its first effect is on.

When a product is out, a line for it fails. A failed main item is replaced by another
product of the same category that is in stock (SUBSTITUTE_P), or by any product in stock
(OTHER_P) if the whole category is out. An order with no line left is lost: it never
appears in `orders`, the customer may write a `vyprodáno` ticket, and is a little upset.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from s2d.spec import EventType, StorySpec

from .calendar import Calendar
from .catalog import Catalog

REVIEW_DAYS = 7
SAFETY_DAYS_BASE = 4             # safety stock: base + share of the lead time, in days of demand
SAFETY_LEAD_SHARE = 0.3
DEMAND_HALFLIFE = 28             # days, running demand estimate
SUBSTITUTE_P = 0.6               # main item out: take another product of the category
OTHER_P = 0.3                    # the whole category out: take any product in stock
LOST_TICKET_P = 0.08             # a lost order: the customer writes to support (topic vyprodáno)
LOST_UPSET = 0.05                # and leaves at the next occasion with this probability
DEFAULT_EVENT_DAYS = 30          # an event without a finite effect lasts this long


@dataclass
class Window:
    start: int
    end: int                     # exclusive
    products: np.ndarray         # bool per product
    multiplier: float = 1.0      # supplier_delay


def _event_days(event) -> int:
    ends = [e.lag_days + e.ramp_days + e.duration_days for e in event.effects if e.duration_days is not None]
    return max(ends) if ends else DEFAULT_EVENT_DAYS


def _target_products(event, spec: StorySpec, products: pd.DataFrame) -> np.ndarray:
    hit = np.ones(len(products), dtype=bool)
    if event.target.category:
        hit &= products["category"].isin(event.target.category).to_numpy()
    if event.target.supplier:
        hit &= products["supplier_id"].isin(event.target.supplier).to_numpy()
    return hit


def supply_windows(spec: StorySpec, cal: Calendar, products: pd.DataFrame) -> tuple[list[Window], list[Window]]:
    delays, outs = [], []
    for ev in spec.events:
        if ev.type == EventType.supplier_delay and ev.params.lead_time_multiplier:
            s = cal.index_of(ev.start)
            delays.append(Window(s, s + _event_days(ev), _target_products(ev, spec, products),
                                 float(ev.params.lead_time_multiplier)))
        elif ev.type == EventType.stockout:
            e = ev.effects[0]
            s = cal.index_of(ev.start) + e.lag_days
            days = e.ramp_days + (e.duration_days if e.duration_days is not None else DEFAULT_EVENT_DAYS)
            outs.append(Window(s, s + max(days, 1), _target_products(ev, spec, products)))
    return delays, outs


class Inventory:
    def __init__(self, spec: StorySpec, cal: Calendar, cat: Catalog, expected_orders_per_day: float,
                 rng: np.random.Generator):
        self.spec, self.cal, self.cat, self.rng = spec, cal, cat, rng
        products = cat.products
        n_p = len(products)
        sup = {s.id: s for s in spec.entities.suppliers}
        self.supplier_ids = products["supplier_id"].to_numpy()
        self.lead = np.array([sup[s].lead_time_days for s in self.supplier_ids], dtype=float)
        self.reliability = np.array([sup[s].reliability for s in self.supplier_ids])
        self.review_day = {s: i % REVIEW_DAYS for i, s in enumerate(sup)}  # each supplier its own weekday
        self.delays, self.outs = supply_windows(spec, cal, products)

        # Expected units a day per product: main items by category weight and popularity,
        # extra items by overall popularity; mean quantity 1/0.8.
        within = np.zeros(n_p)
        for c, idx in enumerate(cat.within_index):
            pop = np.diff(np.concatenate([[0], cat.within_cdf[c]]))
            within[idx] = cat.category_weight[c] * pop / pop.sum()
        glob = np.diff(np.concatenate([[0], cat.global_cdf]))
        extra = 1 / 0.6 - 1
        self.demand = expected_orders_per_day * (within + extra * glob) * 1.25
        self.safety = SAFETY_DAYS_BASE + SAFETY_LEAD_SHARE * self.lead
        self.stock = np.ceil(self.demand * (REVIEW_DAYS + self.safety)).astype(np.int64)
        self.arrivals: dict[int, list[int]] = {}           # day -> shipment row indices
        self.ship_rows: list[list] = []                    # [supplier, product, ordered, expected, received, qty]
        # Warm start: the weekly orders of the last lead time are on their way.
        for p in range(n_p):
            for back in range(REVIEW_DAYS, int(self.lead[p]) + REVIEW_DAYS, REVIEW_DAYS):
                self._ship(p, -back + self.review_day[self.supplier_ids[p]],
                           int(np.ceil(self.demand[p] * REVIEW_DAYS)), delayable=False)
        self.daily: list[np.ndarray] = []                  # per day: stock_end, sold, received, lost

        self._sold = np.zeros(n_p, dtype=np.int64)
        self._lost = np.zeros(n_p, dtype=np.int64)
        self._received = np.zeros(n_p, dtype=np.int64)

    # -- supply

    def _lead_time(self, p: int, ordered: int) -> tuple[int, int]:
        # at least the next day: orders go out at the end of a day, after that day's
        # arrivals were unpacked, so a lead time of 0 (digital goods) never refilled the
        # shelf and sales stopped after the starting stock (DECISIONS 132)
        expected = ordered + max(int(self.lead[p]), 1)
        late = self.rng.random() > self.reliability[p]
        received = expected + (int(np.ceil(self.lead[p] * self.rng.uniform(0.3, 1.0))) if late else 0)
        return expected, received

    def _ship(self, p: int, ordered: int, qty: int, delayable: bool = True) -> None:
        if qty <= 0:
            return
        expected, received = self._lead_time(p, ordered)
        if delayable or received >= 0:
            for w in self.delays:
                if w.products[p] and received >= w.start and ordered < w.end:
                    received = max(received, ordered + int(np.ceil(self.lead[p] * w.multiplier)))
        k = len(self.ship_rows)
        self.ship_rows.append([self.supplier_ids[p], p, ordered, expected, received, qty])
        if received >= 0:  # one received before day 0 is part of the starting stock
            self.arrivals.setdefault(received, []).append(k)

    def on_order(self, p: np.ndarray, t: int) -> np.ndarray:
        """Units on their way per product (ordered, not yet received by day t)."""
        out = np.zeros(len(self.stock), dtype=np.int64)
        for d, ks in self.arrivals.items():
            if d > t:
                for k in ks:
                    out[self.ship_rows[k][1]] += self.ship_rows[k][5]
        return out[p]

    # -- the day loop

    def start_day(self, t: int) -> None:
        self._sold[:] = 0
        self._lost[:] = 0
        self._received[:] = 0
        for k in self.arrivals.pop(t, []):
            p, q = self.ship_rows[k][1], self.ship_rows[k][5]
            self.stock[p] += q
            self._received[p] += q

    def available(self, t: int) -> np.ndarray:
        ok = self.stock > 0
        for w in self.outs:
            if w.start <= t < w.end:
                ok &= ~w.products
        return ok

    def fulfil(self, t: int, product: np.ndarray, qty: np.ndarray) -> np.ndarray:
        """Which lines can be served from stock (in the given order), and take them."""
        ok_p = self.available(t)
        order = np.argsort(product, kind="stable")
        p_sorted, q_sorted = product[order], qty[order]
        csum = np.cumsum(q_sorted)
        start_of = np.searchsorted(p_sorted, p_sorted, side="left")
        before = csum - q_sorted - np.where(start_of > 0, csum[start_of - 1], 0)  # units of earlier lines, same product
        fits = ok_p[p_sorted] & (before + q_sorted <= self.stock[p_sorted])
        ok = np.empty(len(product), dtype=bool)
        ok[order] = fits
        np.add.at(self.stock, product[ok], -qty[ok])
        np.add.at(self._sold, product[ok], qty[ok])
        np.add.at(self._lost, product[~ok], qty[~ok])
        return ok

    def end_day(self, t: int) -> None:
        a = 0.5 ** (1 / DEMAND_HALFLIFE)
        self.demand = a * self.demand + (1 - a) * (self._sold + self._lost)
        self.daily.append(np.stack([self.stock.copy(), self._sold.copy(), self._received.copy(), self._lost.copy()]))
        wd = t % REVIEW_DAYS
        due = [p for p in range(len(self.stock)) if self.review_day[self.supplier_ids[p]] == wd]
        if not due:
            return
        due = np.array(due)
        pipe = self.on_order(due, t)
        target = np.ceil(self.demand[due] * (self.lead[due] + REVIEW_DAYS + self.safety[due])).astype(np.int64)
        for p, q in zip(due, target - self.stock[due] - pipe):
            self._ship(int(p), t, int(q))

    # -- tables

    def tables(self, start: np.datetime64) -> dict[str, pd.DataFrame]:
        day0 = np.datetime64(start, "D")
        d = np.stack(self.daily)                    # [day, 4, product]
        n_days, _, n_p = d.shape
        inv = pd.DataFrame({
            "date": np.repeat(day0 + np.arange(n_days).astype("timedelta64[D]"), n_p),
            "product_id": np.tile(np.arange(1, n_p + 1), n_days),
            "stock_units": d[:, 0, :].ravel(),
            "sold_units": d[:, 1, :].ravel(),
            "received_units": d[:, 2, :].ravel(),
            "lost_units": d[:, 3, :].ravel(),
        })
        rows = [r for r in self.ship_rows if r[4] >= 0 and r[2] < n_days]
        sh = pd.DataFrame(rows, columns=["supplier_id", "product", "ordered", "expected", "received", "quantity"])
        sh = sh.sort_values(["ordered", "supplier_id", "product"], kind="stable").reset_index(drop=True)

        def dates(v, valid=None):
            out = day0 + v.to_numpy().astype("timedelta64[D]")
            return out if valid is None else np.where(valid, out, np.datetime64("NaT"))
        # One shipment = one supplier's weekly order; one row per product line.
        sid = sh.groupby(["supplier_id", "ordered"], sort=False).ngroup() + 1
        shipments = pd.DataFrame({
            "shipment_line_id": np.arange(1, len(sh) + 1),
            "shipment_id": sid.to_numpy(),
            "supplier_id": sh["supplier_id"].to_numpy(),
            "product_id": sh["product"].to_numpy() + 1,
            "ordered_date": dates(sh["ordered"]),
            "expected_date": dates(sh["expected"]),
            "received_date": dates(sh["received"], (sh["received"] < n_days).to_numpy()),
            "quantity": sh["quantity"].to_numpy(),
        })
        suppliers = pd.DataFrame([{"supplier_id": s.id, "name": s.name, "lead_time_days": s.lead_time_days,
                                   "reliability": s.reliability} for s in self.spec.entities.suppliers])
        return {"suppliers": suppliers, "shipments_in": shipments, "inventory_daily": inv}
