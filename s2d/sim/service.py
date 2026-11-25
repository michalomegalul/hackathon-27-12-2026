"""After the order: deliveries, tickets, reviews, and how they come back as churn.

Everything here runs inside the day loop, because a bad experience changes what
THAT customer does next (customer-level, not segment-level):

    order -> delivery (courier of the customer's city; promised vs delivered date)
          -> satisfaction  u = delay_days + noise        (higher = angrier)
               -> review   rating falls with u            (some orders get one)
               -> ticket   more likely the later it is    (support queue, may stay unresolved)
               -> upset    P(leave instead of buying at the next purchase occasion)
          -> open ticket   multiplies the daily churn hazard until it is resolved

Nothing here knows about the story. A courier_change event only changes which
courier delivers in its cities and how late that courier is (`CourierPlan`). The
worse ratings, the tickets and the churn about one purchase gap later all follow
from these rules, and the same rules run in the no-story twin.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from s2d.spec import EventType, Metric, StorySpec

from .calendar import Calendar
from .events import compile_curve

# Fictional couriers. Each city gets one baseline courier (by city index).
BASE_COURIERS = ("Balík Expres", "RychloKurýr", "DoDveří")
BASE_LATE_P = (0.04, 0.05, 0.06)     # share of late parcels per baseline courier
LATE_EXTRA_MEAN = 0.2                # delay | late = 1 + Poisson(this): mostly 1 day
NEW_COURIERS = ("Levná Doprava", "Kurýr Úspora", "Zásilka Plus")
NEW_LATE_P = 0.6                     # share of late parcels of a story's new courier at full strength
# Promise: delivered 2 days after the order, 3 for orders on Friday and Saturday.
PROMISE_DAYS = np.array([2, 2, 2, 2, 3, 3, 2])

# Satisfaction of one delivery: u = delay + N(0, U_NOISE). On time u ~ 0.
U_NOISE = 0.8
RATING_TOP = 4.6                     # rating = round(RATING_TOP - RATING_PER_U * u + N(0, RATING_NOISE))
RATING_PER_U = 0.75
RATING_NOISE = 0.6
# Upset = P(the customer leaves instead of ordering at their next purchase occasion), only
# after a late parcel. A day late is mostly tolerated, three days is not:
# upset = DEFECT_MAX * clip((u - FROM) / SPAN).
DEFECT_MAX = 0.5
DEFECT_FROM = 2.0
DEFECT_SPAN = 3.0
UPSET_HALFLIFE = 45                  # days; an old disappointment fades

# Tickets. Base rate from the spec (any topic); a late parcel adds TICKET_PER_LATE_DAY per day late.
TICKET_PER_LATE_DAY = 0.12
TICKET_LATE_MAX = 0.6
TICKET_TOPICS = ("kvalita", "obsluha", "cena", "zpoždění", "vyprodáno")
TICKET_TOPIC_P = (0.35, 0.2, 0.15, 0.2, 0.1)
UNRESOLVED_P = 0.04                  # tickets that are never resolved (resolved_at NULL)
GIVE_UP_DAYS = 60                    # an unresolved ticket weighs on the customer this long
OPEN_TICKET_HAZARD = 4.0             # daily churn hazard x (1 + this) while a ticket is open

# Reviews. A late parcel makes a review more likely (people complain).
REVIEW_LATE_BOOST = 1.5
REVIEW_TOPICS_GOOD = ("kvalita", "obsluha", "cena")
REVIEW_TOPICS_GOOD_P = (0.5, 0.3, 0.2)
REVIEW_TOPICS_BAD = ("kvalita", "obsluha", "cena", "zpoždění")
REVIEW_TOPICS_BAD_P = (0.45, 0.25, 0.2, 0.1)


def upset_from(u: np.ndarray) -> np.ndarray:
    return DEFECT_MAX * np.clip((u - DEFECT_FROM) / DEFECT_SPAN, 0, 1)


def rating_from(u: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    r = np.rint(RATING_TOP - RATING_PER_U * u + rng.normal(0, RATING_NOISE, len(u)))
    return np.clip(r, 1, 5).astype(np.int64)


# ---------------------------------------------------------------- couriers


@dataclass
class CourierPlan:
    names: list[str]              # courier index -> name
    of_city: np.ndarray           # [day, city] -> courier index
    late_p: np.ndarray            # [day, city] share of late parcels
    late_mean: np.ndarray         # [day, city] mean delay of a late parcel (days)


def courier_plan(spec: StorySpec, cal: Calendar) -> CourierPlan:
    """Baseline courier per city; a courier_change event with a delivery delay switches
    its target cities to a new courier while its delivery_days curve is on."""
    cities = [c.name for c in spec.company.cities]
    n_days, n_c = cal.n_days, len(cities)
    names = list(BASE_COURIERS)
    base = np.arange(n_c) % len(BASE_COURIERS)
    of_city = np.tile(base, (n_days, 1))
    late_p = np.tile(np.array(BASE_LATE_P)[base], (n_days, 1))
    late_mean = np.full((n_days, n_c), 1 + LATE_EXTRA_MEAN)
    for event in spec.events:
        delay = courier_delay(event)
        if event.type != EventType.courier_change or delay is None:
            continue
        eff = next((e for e in event.effects if e.metric == Metric.delivery_days), None)
        start = cal.index_of(event.start)
        if eff is None:
            curve = np.zeros(n_days)
            curve[max(start, 0):] = 1.0
        else:
            curve = compile_curve(start, eff, n_days)
        name = NEW_COURIERS[sum(1 for n in names if n in NEW_COURIERS) % len(NEW_COURIERS)]
        names.append(name)
        k = len(names) - 1
        hit = np.array([not event.target.city or c in event.target.city for c in cities])
        on = curve > 0
        # The new courier at strength s = delay * curve(t): late with NEW_LATE_P (less while
        # ramping), and a late parcel is late by about s / NEW_LATE_P days on average.
        s = delay * curve
        p = np.minimum(NEW_LATE_P, s)
        mean = np.where(p > 0, np.maximum(s / np.maximum(p, 1e-9), 1.0), 1.0)
        for c in np.flatnonzero(hit):
            of_city[on, c] = k
            late_p[on, c] = np.maximum(p[on], late_p[on, c])
            late_mean[on, c] = mean[on]
    return CourierPlan(names, of_city, late_p, late_mean)


def courier_delay(event) -> float | None:
    """Extra delivery days a courier_change event causes, None if it does not switch couriers
    (a follow-up event that only describes consequences, like Example B's E2)."""
    if event.type != EventType.courier_change:
        return None
    if event.params.delivery_delay_days is not None:
        return float(event.params.delivery_delay_days)
    eff = next((e for e in event.effects if e.metric == Metric.delivery_days), None)
    return None if eff is None else float(eff.size)


# ---------------------------------------------------------------- state


class Service:
    """Per-customer service state plus the rows of deliveries, tickets and reviews."""

    def __init__(self, spec: StorySpec, cal: Calendar, n_customers: int, city: np.ndarray,
                 rngs: dict[str, np.random.Generator]):
        self.spec, self.cal = spec, cal
        self.city = city
        self.plan = courier_plan(spec, cal)
        self.rng_d, self.rng_t, self.rng_r = rngs["deliveries"], rngs["tickets"], rngs["reviews"]
        self.rng_s = rngs["service"]
        self.upset = np.zeros(n_customers)
        self.open_tickets = np.zeros(n_customers, dtype=np.int64)
        self.decay = 0.5 ** (1 / UPSET_HALFLIFE)
        self.capacity = max(int(spec.entities.employees.support_agents
                                * spec.entities.employees.tickets_per_agent_day), 1)
        self._upset_at: dict[int, list] = defaultdict(list)    # day -> [(customers, upset)]
        self._tickets_at: dict[int, list] = defaultdict(list)  # day -> [ticket row indices]
        self._release_at: dict[int, list] = defaultdict(list)  # day -> [customers whose ticket closes]
        self.queue: list[np.ndarray] = []
        self.deliveries: list[dict] = []
        self.tickets: list[dict] = []
        self.reviews: list[dict] = []
        self._n_tickets = 0

    # -- the day loop calls these

    def hazard_factor(self) -> np.ndarray:
        return 1 + OPEN_TICKET_HAZARD * (self.open_tickets > 0)

    def start_day(self, t: int) -> None:
        """Apply what became known today: delivered parcels, opened and resolved tickets."""
        self.upset *= self.decay
        for cust, up in self._upset_at.pop(t, []):
            np.maximum.at(self.upset, cust, up)
        for cust in self._release_at.pop(t, []):
            np.subtract.at(self.open_tickets, cust, 1)
        new = self._tickets_at.pop(t, [])
        if new:
            idx = np.concatenate(new)
            np.add.at(self.open_tickets, self._t_customer[idx], 1)
            never = self._t_never[idx]
            for i in idx[never]:
                self._release_at[t + GIVE_UP_DAYS].append(np.array([self._t_customer[i]]))
            self.queue.append(idx[~never])
        # Support works through the queue in order, `capacity` tickets a day.
        if self.queue:
            q = np.concatenate(self.queue)
            done, rest = q[:self.capacity], q[self.capacity:]
            self.queue = [rest] if len(rest) else []
            handle = self.rng_t.integers(0, 3, len(done))
            self._t_resolved[done] = t + handle
            for d in np.unique(handle):
                self._release_at[t + int(d) + 1].append(self._t_customer[done[handle == d]])

    def defect(self, buyers: np.ndarray) -> np.ndarray:
        """Of the customers about to order, who leaves instead. The others give the shop
        another chance, which clears their upset."""
        up = self.upset[buyers]
        leave = self.rng_s.random(len(buyers)) < up
        self.upset[buyers[~leave]] = 0.0
        return leave

    def lost_orders(self, t: int, customer: np.ndarray, product: np.ndarray) -> None:
        """Orders that could not be served (out of stock): a `vyprodáno` ticket now and then,
        and a little upset."""
        from .inventory import LOST_TICKET_P, LOST_UPSET
        self._upset_at[t + 1].append((customer, np.full(len(customer), LOST_UPSET)))
        w = self.rng_t.random(len(customer)) < LOST_TICKET_P
        self.add_tickets(np.full(w.sum(), -1), customer[w], t + self.rng_t.geometric(0.7, w.sum()) - 1,
                         np.full(w.sum(), "vyprodáno", dtype=object), self.cal.n_days, product[w])

    def on_orders(self, t: int, order_id: np.ndarray, customer: np.ndarray, is_store: np.ndarray,
                  cancelled: np.ndarray, main_product: np.ndarray) -> None:
        """Deliveries, reviews and tickets for today's orders (cancelled ones get nothing)."""
        ok = ~cancelled
        self._main_product = getattr(self, "_main_product", [])
        self._main_product.append(main_product)
        ship = ok & ~is_store
        n_days = self.cal.n_days
        rng = self.rng_d

        # Deliveries
        o, c = order_id[ship], customer[ship]
        city = self.city[c]
        p_late = self.plan.late_p[t, city]
        late = rng.random(len(o)) < p_late
        extra = self.plan.late_mean[t, city] - 1
        delay = np.where(late, 1 + rng.poisson(np.maximum(extra, 0)), 0)
        promised = t + PROMISE_DAYS[self.cal.dates[t].weekday()]
        delivered = promised + delay
        u_ship = delay + rng.normal(0, U_NOISE, len(o))
        self.deliveries.append({"order_id": o, "courier": self.plan.of_city[t, city],
                                "shipped": np.full(len(o), t + 1), "promised": np.full(len(o), promised),
                                "delivered": delivered, "delay": delay})
        up = np.where(delay > 0, upset_from(u_ship), 0.0)
        bad = up > 0
        for d in np.unique(delivered[bad]):
            sel = bad & (delivered == d)
            self._upset_at[int(d)].append((c[sel], up[sel]))

        # Store orders: satisfaction without a delivery (u is noise only).
        so, sc = order_id[ok & is_store], customer[ok & is_store]
        u_store = rng.normal(0, U_NOISE, len(so))

        all_o = np.concatenate([o, so])
        all_c = np.concatenate([c, sc])
        all_u = np.concatenate([u_ship, u_store])
        all_delay = np.concatenate([delay, np.zeros(len(so), dtype=np.int64)])
        experienced = np.concatenate([delivered, np.full(len(so), t)])  # day the customer judges it
        self._reviews(all_o, all_c, all_u, all_delay, experienced, n_days)
        self._new_tickets(all_o, all_c, all_delay, experienced,
                          np.concatenate([np.full(len(o), promised), np.full(len(so), t)]), n_days)

    # -- rows

    def _reviews(self, o, c, u, delay, day, n_days):
        rng = self.rng_r
        rate = self.spec.baseline.review_rate
        p = np.minimum(rate * (1 + REVIEW_LATE_BOOST * (delay > 0)), 1.0)
        hit = rng.random(len(o)) < p
        o, c, u, delay = o[hit], c[hit], u[hit], delay[hit]
        rday = day[hit] + rng.geometric(0.4, len(o)) - 1
        rating = rating_from(u, rng)
        good = rng.choice(len(REVIEW_TOPICS_GOOD), len(o), p=REVIEW_TOPICS_GOOD_P)
        bad = rng.choice(len(REVIEW_TOPICS_BAD), len(o), p=REVIEW_TOPICS_BAD_P)
        topic = np.where(rating >= 4, np.array(REVIEW_TOPICS_GOOD, dtype=object)[good],
                         np.array(REVIEW_TOPICS_BAD, dtype=object)[bad])
        topic = np.where((delay > 0) & (rating <= 3) & (rng.random(len(o)) < 0.85), "zpoždění", topic)
        keep = rday < n_days
        self.reviews.append({"order_id": o[keep], "customer": c[keep], "day": rday[keep],
                             "rating": rating[keep], "topic": topic[keep]})

    def _new_tickets(self, o, c, delay, day, promised, n_days):
        rng = self.rng_t
        base = self.spec.baseline.ticket_rate_per_order
        p_late = np.minimum(TICKET_PER_LATE_DAY * delay, TICKET_LATE_MAX)
        late_t = rng.random(len(o)) < p_late
        base_t = ~late_t & (rng.random(len(o)) < base)
        # A late parcel: the customer writes the day after the promised date (or a bit later).
        lday = promised[late_t] + rng.geometric(0.6, late_t.sum())
        bday = day[base_t] + rng.geometric(0.5, base_t.sum()) - 1
        topic_b = np.array(TICKET_TOPICS, dtype=object)[rng.choice(len(TICKET_TOPICS), base_t.sum(), p=TICKET_TOPIC_P)]
        self.add_tickets(np.concatenate([o[late_t], o[base_t]]), np.concatenate([c[late_t], c[base_t]]),
                         np.concatenate([lday, bday]),
                         np.concatenate([np.full(late_t.sum(), "zpoždění", dtype=object), topic_b]), n_days)

    def add_tickets(self, order_id, customer, day, topic, n_days, product=None) -> None:
        """Queue tickets to be opened on `day` (order_id -1 = no order; product -1 = the
        order's main product, filled in when the tables are built)."""
        if product is None:
            product = np.full(len(order_id), -1)
        keep = day < n_days
        order_id, customer, day, topic, product = order_id[keep], customer[keep], day[keep], topic[keep], product[keep]
        n = len(order_id)
        if not n:
            return
        k0 = self._n_tickets
        idx = np.arange(k0, k0 + n)
        self._n_tickets += n
        never = self.rng_t.random(n) < UNRESOLVED_P
        self.tickets.append({"order_id": order_id, "customer": customer, "day": day, "topic": topic,
                             "never": never, "product": product})
        self._grow(k0 + n)
        self._t_customer[idx] = customer
        self._t_never[idx] = never
        for d in np.unique(day):
            self._tickets_at[int(d)].append(idx[day == d])

    def _grow(self, n: int) -> None:
        cur = len(getattr(self, "_t_customer", ()))
        if n <= cur:
            return
        size = max(n, 2 * cur, 1024)
        for name, dtype, fill in (("_t_customer", np.int64, 0), ("_t_never", bool, False),
                                  ("_t_resolved", np.int64, -1)):
            new = np.full(size, fill, dtype=dtype)
            if cur:
                new[:cur] = getattr(self, name)
            setattr(self, name, new)

    # -- tables

    def tables(self, start: np.datetime64, orders: pd.DataFrame, rng: np.random.Generator) -> dict[str, pd.DataFrame]:
        n_days = self.cal.n_days
        day0 = np.datetime64(start, "D")
        main = np.concatenate(getattr(self, "_main_product", [np.zeros(0, dtype=np.int64)]))  # per order

        def dates(days, valid):
            out = day0 + days.astype("timedelta64[D]")
            return np.where(valid, out, np.datetime64("NaT"))

        d = _cat(self.deliveries, ["order_id", "courier", "shipped", "promised", "delivered", "delay"])
        arrived = d["delivered"] < n_days
        deliveries = pd.DataFrame({
            "delivery_id": np.arange(1, len(d["order_id"]) + 1),
            "order_id": d["order_id"] + 1,
            "courier": np.array(self.plan.names, dtype=object)[d["courier"]],
            "shipped_date": dates(d["shipped"], d["shipped"] < n_days),
            "promised_date": day0 + d["promised"].astype("timedelta64[D]"),
            "delivered_date": dates(d["delivered"], arrived),
            "delay_days": pd.array(np.where(arrived, d["delay"], 0), dtype="Int64"),
            "late": pd.array(d["delay"] > 0, dtype="boolean"),
        })
        deliveries.loc[~arrived, "delay_days"] = pd.NA
        # In transit at the end of the data: late only if the promise has already passed.
        deliveries.loc[~arrived & (d["promised"] >= n_days - 1), "late"] = pd.NA

        r = _cat(self.reviews, ["order_id", "customer", "day", "rating", "topic"])
        order = np.argsort(r["day"], kind="stable")
        rts = day0 + r["day"][order].astype("timedelta64[D]") + _seconds(rng, len(order), 8, 23)
        reviews = pd.DataFrame({
            "review_id": np.arange(1, len(order) + 1),
            "customer_id": r["customer"][order] + 1,
            "order_id": r["order_id"][order] + 1,
            "product_id": main[r["order_id"][order]] + 1,
            "created_at": rts,
            "review_date": rts.astype("datetime64[D]"),
            "rating": r["rating"][order],
            "topic": r["topic"][order],
            "text": "",
        })

        t = _cat(self.tickets, ["order_id", "customer", "day", "topic", "never", "product"])
        if len(t["product"]):
            t["product"] = np.where(t["product"] >= 0, t["product"], main[np.maximum(t["order_id"], 0)])
        n_t = len(t["day"])
        resolved = self._t_resolved[:n_t] if n_t else np.zeros(0, dtype=np.int64)
        opened_ts = day0 + t["day"].astype("timedelta64[D]") + _seconds(rng, n_t, 7, 22)
        res_ts = day0 + resolved.astype("timedelta64[D]") + _seconds(rng, n_t, 8, 18)
        res_ok = (resolved >= 0) & (resolved < n_days) & ~t["never"]
        res_ts = np.where(res_ok, np.maximum(res_ts, opened_ts + np.timedelta64(600, "s")), np.datetime64("NaT"))
        order = np.lexsort((t["order_id"], t["day"]))
        tickets = pd.DataFrame({
            "ticket_id": np.arange(1, n_t + 1),
            "customer_id": t["customer"][order] + 1,
            "order_id": pd.array(np.where(t["order_id"][order] >= 0, t["order_id"][order] + 1, 0), dtype="Int64"),
            "product_id": t["product"][order] + 1,
            "topic": t["topic"][order],
            "opened_at": opened_ts[order],
            "resolved_at": res_ts[order],
        })
        tickets.loc[t["order_id"][order] < 0, "order_id"] = pd.NA
        return {"deliveries": deliveries, "reviews": reviews, "tickets": tickets}


def _cat(parts: list[dict], keys: list[str]) -> dict[str, np.ndarray]:
    if not parts:
        return {k: np.zeros(0, dtype=np.int64) for k in keys}
    return {k: np.concatenate([p[k] for p in parts]) for k in keys}


def _seconds(rng: np.random.Generator, n: int, h0: int, h1: int) -> np.ndarray:
    return (rng.integers(h0 * 3600, h1 * 3600, n)).astype("timedelta64[s]")
