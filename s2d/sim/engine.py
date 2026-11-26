"""The vectorized day loop.

State is a handful of numpy arrays with one entry per customer. Each day:

  1. churn:     who leaves today       (daily hazard, Bernoulli draw)
  2. purchases: how many orders each   (Poisson with rate λ[i,t])
  3. baskets:   what is in each order  (Zipf popularity, geometric size)
  4. payment:   paid or cancelled      (decided the same day)
  5. service:   delivery, review, ticket (s2d/sim/service.py; feeds back into 1 and 2)

    λ[i,t] = base_rate[i] · day_factor[t] · holiday[i,t] · Π_e (1 + size_e · curve_e[t]) · alive[i]
    h[i,t] = base_hazard[i] · Π_e (1 + size_e · curve_e[t]) + Σ_shocks h_e · curve_e[t]

where each product Π / sum only includes events whose target matches customer i.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from s2d.spec import Channel, Metric, StorySpec

from .calendar import HOLIDAY_FACTOR_ONLINE, Calendar
from .catalog import Catalog
from .events import CompiledStory
from .population import Population, target_mask
from .rng import DAILY_STREAMS, daily
from .service import Service
from .inventory import OTHER_P, SUBSTITUTE_P, Inventory
from .subscriptions import SCHEDULED_SHARE, build_plans, subscriptions_table

BASKET_EXTRA_ITEM_P = 0.6   # geometric basket size: mean 1/0.6 ≈ 1.7 items
QUANTITY_P = 0.8            # geometric quantity per line: mean 1.25

# Share of online orders by hour of day (store orders are 7:00-19:59, uniform).
ONLINE_HOURS = np.array([1, 0.5, 0.3, 0.2, 0.2, 0.4, 1, 2, 3, 4, 4.5, 5,
                         5, 5, 4.5, 4.5, 5, 5.5, 6.5, 7.5, 8, 7, 5, 2.5])
ONLINE_HOURS = ONLINE_HOURS / ONLINE_HOURS.sum()


@dataclass
class _ActiveEffect:
    """A compiled effect plus the customers (and categories) it applies to."""
    size: float
    curve: np.ndarray
    customers: np.ndarray        # bool per customer
    categories: np.ndarray | None  # bool per category, None = all categories
    price_sensitive: bool
    additive: bool
    event_type: str = ""


@dataclass
class SimResult:
    churn_day: np.ndarray        # day index the customer left, -1 = still active
    orders: pd.DataFrame
    order_items: pd.DataFrame
    payments: pd.DataFrame
    service: dict[str, pd.DataFrame]  # deliveries, reviews, tickets
    churn_cause: np.ndarray           # why each leaver left ('' = still active)


def _prepare_effects(spec: StorySpec, story: CompiledStory, pop: Population, cat: Catalog, metric: Metric):
    out = []
    for eff in story.for_metric(metric):
        cats = None
        if eff.target.category:
            cats = np.isin(cat.category_ids, eff.target.category)
        out.append(_ActiveEffect(
            eff.size, eff.curve,
            target_mask(eff.target, spec, pop.segment, pop.city, pop.channel),
            cats, eff.price_sensitive, eff.additive, eff.event_type,
        ))
    return out


def churn_hazard_on_day(t: int, pop: Population, churn_effects: list[_ActiveEffect]) -> np.ndarray:
    """Daily probability of leaving from the story's churn effects, per customer, on day t
    (ignores who is alive and the service state: open tickets, upset after a late parcel)."""
    relative, additive = churn_multipliers(t, pop, churn_effects)
    return np.minimum(pop.base_hazard * relative + additive, 1.0)


def _holiday_factor(spec: StorySpec, pop: Population, cal: Calendar) -> np.ndarray:
    """Multiplier per customer for a public holiday, by their home channel."""
    is_store = np.array([c.channel == Channel.store for c in spec.company.channels])[pop.channel]
    return np.where(is_store, cal.store_holiday_factor, HOLIDAY_FACTOR_ONLINE)


def run_day_loop(spec: StorySpec, cal: Calendar, story: CompiledStory, pop: Population,
                 cat: Catalog, streams: dict[str, np.random.Generator]) -> SimResult:
    streams = daily(streams)  # re-seeded each day: story and twin stay paired (rng.DailyRng)
    rng_churn = streams["churn"]
    rng_buy = streams["purchases"]
    rng_pay = streams["payments"]
    n_cats = len(cat.category_ids)

    churn_effects = _prepare_effects(spec, story, pop, cat, Metric.churn_hazard)
    buy_effects = _prepare_effects(spec, story, pop, cat, Metric.purchase_rate)
    holiday_factor = _holiday_factor(spec, pop, cal)
    chan_is_store = np.array([c.channel == Channel.store for c in spec.company.channels])
    svc = Service(spec, cal, pop.n, pop.city, streams)
    plans = build_plans(spec, pop.segment, pop.base_rate, pop.signup_day, streams["subscriptions"])
    adhoc = np.where(plans.is_sub, 1 - SCHEDULED_SHARE, 1.0)  # subscribers: the rest is on schedule
    chans = [c.channel for c in spec.company.channels]
    # Scheduled orders are shipped: the e-shop if the shop has one, else the home channel.
    sub_channel = chans.index(Channel.eshop) if Channel.eshop in chans else None

    churn_day = np.full(pop.n, -1)
    churn_cause = np.full(pop.n, "", dtype=object)
    order_customer, order_day, order_category, order_failed, order_retry = [], [], [], [], []
    order_channel, order_sub = [], []
    item_order, item_product, item_qty = [], [], []
    alive0 = (pop.signup_day <= 0)
    inv = Inventory(spec, cal, cat, float(pop.base_rate[alive0].sum() * cal.day_factor.mean()),
                    streams["inventory"])
    n_orders_so_far = 0

    for t in range(cal.n_days):
        for name in DAILY_STREAMS:
            streams[name].day(t)
        svc.start_day(t)
        alive = (pop.signup_day <= t) & (churn_day < 0)

        # 1. churn. Draw one uniform per customer (alive or not) so that the
        #    random numbers line up between runs with and without the story.
        relative, additive = churn_multipliers(t, pop, churn_effects)
        ticket = svc.hazard_factor()
        hazard = np.minimum(pop.base_hazard * relative * ticket + additive, 1.0)
        leaves = alive & (rng_churn.random(pop.n) < hazard)
        churn_day[leaves] = t
        alive &= ~leaves
        if leaves.any():
            churn_cause[leaves] = _churn_causes(np.flatnonzero(leaves), t, pop, churn_effects, ticket,
                                                svc.rng_s)

        # 2. purchases. rate[i, c] = expected orders of customer i whose main item is in category c.
        lam = pop.base_rate * adhoc * cal.day_factor[t] * alive
        if cal.is_holiday[t]:
            lam = lam * holiday_factor
        rate = lam[:, None] * cat.category_weight[None, :]
        for e in buy_effects:
            strength = e.size * e.curve[t]
            if strength == 0:
                continue
            factor = np.ones(pop.n)
            sens = pop.price_sensitivity[e.customers] if e.price_sensitive else 1.0
            factor[e.customers] = np.maximum(1 + strength * sens, 0)
            columns = e.categories if e.categories is not None else np.ones(n_cats, dtype=bool)
            rate[:, columns] *= factor[:, None]

        total = rate.sum(axis=1)
        n_orders = rng_buy.poisson(total)
        due = plans.days > 0
        due &= plans.next_due == t
        plans.next_due[due] += plans.days[due]
        due &= alive
        n_orders += due
        buyers = np.flatnonzero(n_orders)
        # An upset customer may leave at this purchase occasion instead of ordering.
        gone = buyers[svc.defect(buyers)]
        if len(gone):
            churn_day[gone] = t
            churn_cause[gone] = "zpoždění"
            n_orders[gone] = 0
            due[gone] = False
            buyers = np.flatnonzero(n_orders)
        who = np.repeat(buyers, n_orders[buyers])
        # the first order of a due subscriber today is the scheduled one
        first_of = np.concatenate([[0], np.cumsum(n_orders[buyers])[:-1]]).astype(np.int64)
        is_sub = np.zeros(len(who), dtype=bool)
        is_sub[first_of[due[buyers]]] = True
        channel = pop.channel[who].copy()
        if sub_channel is not None:
            channel[is_sub] = sub_channel

        # main category of each order, in proportion to rate[i, c] (a scheduled order on a
        # day the customer's store is closed still follows the usual category mix)
        w = rate[who] + 1e-12 * cat.category_weight[None, :]
        cdf = np.cumsum(w, axis=1) / w.sum(axis=1)[:, None]
        u = rng_buy.random(len(who))
        main_cat = np.minimum((cdf < u[:, None]).sum(axis=1), n_cats - 1)

        # 3. baskets, served from stock. An order with nothing left is lost (never recorded).
        inv.start_day(t)
        line_order, product, qty, is_main = _draw_baskets(len(who), main_cat, cat, rng_buy)
        line_order, product, qty, is_main, main_product, kept = _serve(
            t, inv, cat, line_order, product, qty, is_main, main_cat, rng_buy)
        lost = ~kept
        if lost.any():
            svc.lost_orders(t, who[lost], main_product[lost])
            remap = np.cumsum(kept) - 1
            line_order = remap[line_order]
            who, main_cat, channel, is_sub = who[kept], main_cat[kept], channel[kept], is_sub[kept]
            main_product = main_product[kept]
        inv.end_day(t)

        # 4. payment (decided today, so a cancelled order is never shipped), then service.
        failed = rng_pay.random(len(who)) < spec.baseline.payment_failure_rate
        retry_ok = rng_pay.random(len(who)) < RETRY_SUCCESS_P
        ids = np.arange(n_orders_so_far, n_orders_so_far + len(who))
        svc.on_orders(t, ids, who, chan_is_store[channel], failed & ~retry_ok, main_product)
        item_order.append(line_order + n_orders_so_far)
        item_product.append(product)
        item_qty.append(qty)
        n_orders_so_far += len(who)

        order_customer.append(who)
        order_day.append(np.full(len(who), t))
        order_category.append(main_cat)
        order_failed.append(failed)
        order_retry.append(retry_ok)
        order_channel.append(channel)
        order_sub.append(is_sub)

    customer = np.concatenate(order_customer)
    for name in DAILY_STREAMS:  # what is drawn after the loop
        streams[name].day(cal.n_days)
    orders, items = _build_orders(spec, cal, pop, cat, customer, np.concatenate(order_day), rng_buy,
                                  np.concatenate(order_channel), np.concatenate(item_order),
                                  np.concatenate(item_product), np.concatenate(item_qty))
    sub = np.concatenate(order_sub)
    orders.insert(orders.columns.get_loc("channel") + 1, "subscription_id",
                  pd.array(np.where(sub, plans.sub_id[customer], 0), dtype="Int64"))
    orders.loc[~sub, "subscription_id"] = pd.NA
    payments, cancelled = _build_payments(spec, orders, rng_pay,
                                          np.concatenate(order_failed), np.concatenate(order_retry))
    orders["status"] = np.where(cancelled, "cancelled", "completed")
    start = np.datetime64(cal.dates[0], "D")
    service = svc.tables(start, orders, streams["timestamps"])
    service.update(inv.tables(start))
    service["subscriptions"] = subscriptions_table(plans, pop.table["signup_date"], churn_day, churn_cause,
                                                   start, streams["subscriptions"])
    return SimResult(churn_day, orders, items, payments, service, churn_cause)


CAUSE_OF_EVENT = {
    "price_change": "cena", "quality_issue": "kvalita", "competitor_entry": "konkurence",
    "courier_change": "zpoždění", "supplier_delay": "vyprodáno", "stockout": "vyprodáno",
}


def churn_multipliers(t: int, pop: Population, churn_effects: list[_ActiveEffect]) -> tuple[np.ndarray, np.ndarray]:
    relative = np.ones(pop.n)
    additive = np.zeros(pop.n)
    for e in churn_effects:
        strength = e.size * e.curve[t]
        if strength == 0:
            continue
        if e.additive:
            additive[e.customers] += strength
        else:
            relative[e.customers] *= max(1 + strength, 0)
    return relative, additive


def _churn_causes(idx: np.ndarray, t: int, pop: Population, churn_effects: list[_ActiveEffect],
                  ticket: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Why each leaver left: one cause drawn in proportion to its share of their hazard
    (baseline, each story event, an open ticket). Becomes subscriptions.cancel_reason."""
    base = pop.base_hazard[idx]
    parts = [("jiné", base)]
    rel = np.ones(len(idx))
    for e in churn_effects:
        strength = e.size * e.curve[t]
        if strength == 0:
            continue
        hit = e.customers[idx]
        if e.additive:
            parts.append((CAUSE_OF_EVENT.get(e.event_type, "jiné"), np.where(hit, strength, 0.0)))
        else:
            parts.append((CAUSE_OF_EVENT.get(e.event_type, "jiné"),
                          np.where(hit, base * rel * max(strength, 0), 0.0)))
            rel = rel * np.where(hit, max(1 + strength, 0), 1.0)
    tk = ticket[idx]
    parts.append(("podpora", base * rel * (tk - 1)))
    w = np.stack([p for _, p in parts], axis=1)
    w = w / np.maximum(w.sum(axis=1, keepdims=True), 1e-12)
    pick = (w.cumsum(axis=1) < rng.random(len(idx))[:, None]).sum(axis=1)
    names = np.array([n for n, _ in parts], dtype=object)
    return names[np.minimum(pick, len(parts) - 1)]


def _draw_baskets(n: int, main_cat: np.ndarray, cat: Catalog, rng: np.random.Generator):
    """Baskets of n orders: first item from the main category, extra items from overall
    popularity, geometric size and quantity. Repeated products in one order are one line.
    Returns (order index, product, quantity, is_main) per line, sorted by order."""
    size = rng.geometric(BASKET_EXTRA_ITEM_P, n)
    item_order = np.repeat(np.arange(n), size)
    first = np.zeros(len(item_order), dtype=bool)
    first[np.concatenate([[0], np.cumsum(size)[:-1]]).astype(np.int64)[:n]] = True

    product = np.empty(len(item_order), dtype=np.int64)
    u = rng.random(len(item_order))
    product[first] = _pick_in_category(main_cat, u[first], cat)
    pos = np.searchsorted(cat.global_cdf, u[~first] * cat.global_cdf[-1])
    product[~first] = np.minimum(pos, len(cat.global_cdf) - 1)
    quantity = rng.geometric(QUANTITY_P, len(item_order))

    n_p = len(cat.global_cdf)
    key = item_order * n_p + product
    key, inverse = np.unique(key, return_inverse=True)
    quantity = np.bincount(inverse, weights=quantity).astype(np.int64)
    is_main = np.bincount(inverse, weights=first).astype(bool)
    return key // n_p, key % n_p, quantity, is_main


def _pick_in_category(category: np.ndarray, u: np.ndarray, cat: Catalog, allowed: np.ndarray | None = None):
    """One product per row from its category by popularity (only `allowed` products; -1 if none)."""
    out = np.full(len(category), -1, dtype=np.int64)
    for c in np.unique(category):
        sel = category == c
        idx = cat.within_index[c]
        w = np.diff(np.concatenate([[0], cat.within_cdf[c]]))
        if allowed is not None:
            w = w * allowed[idx]
        if w.sum() <= 0:
            continue
        cdf = np.cumsum(w)
        pos = np.searchsorted(cdf, u[sel] * cdf[-1], side="right")
        out[sel] = idx[np.minimum(pos, len(idx) - 1)]
    return out


def _serve(t, inv: Inventory, cat: Catalog, line_order, product, qty, is_main, main_cat, rng):
    """Serve lines from stock. A failed main item may be replaced by another product of its
    category, or by any product if the category is out. Returns the kept lines, the main
    product per order (the wanted one if the order is lost) and which orders survive."""
    n = len(main_cat)
    main_product = np.full(n, -1, dtype=np.int64)
    main_product[line_order[is_main]] = product[is_main]
    ok = inv.fulfil(t, product, qty)
    fail_main = is_main & ~ok
    if fail_main.any():
        avail = inv.available(t) & (inv.stock > 0)
        o = line_order[fail_main]
        u1, u2 = rng.random(len(o)), rng.random(len(o))
        sub = _pick_in_category(main_cat[o], u2, cat, avail)
        none_in_cat = sub < 0
        take = np.where(none_in_cat, u1 < OTHER_P, u1 < SUBSTITUTE_P)
        if none_in_cat.any() and avail.any():
            g = np.diff(np.concatenate([[0], cat.global_cdf])) * avail
            cdf = np.cumsum(g)
            pos = np.searchsorted(cdf, u2[none_in_cat] * cdf[-1], side="right")
            sub[none_in_cat] = np.minimum(pos, len(cdf) - 1)
        take &= sub >= 0
        if take.any():
            s_order, s_prod, s_qty = o[take], sub[take], qty[fail_main][take]
            s_ok = inv.fulfil(t, s_prod, s_qty)
            line_order = np.concatenate([line_order, s_order[s_ok]])
            product = np.concatenate([product, s_prod[s_ok]])
            qty = np.concatenate([qty, s_qty[s_ok]])
            is_main = np.concatenate([is_main, np.ones(s_ok.sum(), dtype=bool)])
            ok = np.concatenate([ok, np.ones(s_ok.sum(), dtype=bool)])
            main_product[s_order[s_ok]] = s_prod[s_ok]
    line_order, product, qty, is_main = line_order[ok], product[ok], qty[ok], is_main[ok]
    # merge a substitute that is already in the order, keep lines sorted by order
    n_p = len(cat.global_cdf)
    key, inverse = np.unique(line_order * n_p + product, return_inverse=True)
    qty = np.bincount(inverse, weights=qty).astype(np.int64)
    is_main = np.bincount(inverse, weights=is_main).astype(bool)
    line_order, product = key // n_p, key % n_p
    kept = np.bincount(line_order, minlength=n) > 0
    return line_order, product, qty, is_main, main_product, kept


def _build_orders(spec, cal, pop, cat, customer, day, rng, channel_idx, item_order, product, quantity):
    n = len(customer)
    chan_names = np.array([c.channel.value for c in spec.company.channels], dtype=object)
    city_names = np.array([c.name for c in spec.company.cities], dtype=object)
    channel = chan_names[channel_idx]

    # Order time: stores are open 7:00-19:59, online follows ONLINE_HOURS.
    is_store = channel == Channel.store.value
    hour = np.where(is_store, rng.integers(7, 20, n), rng.choice(24, size=n, p=ONLINE_HOURS))
    seconds = hour * 3600 + rng.integers(0, 3600, n)
    start = np.datetime64(cal.dates[0], "s")
    ts = start + (day * 86400 + seconds).astype("timedelta64[s]")

    unit_price = cat.price[day[item_order], product]
    line_total = unit_price * quantity

    order_total = np.bincount(item_order, weights=line_total, minlength=n)
    orders = pd.DataFrame({
        "order_id": np.arange(1, n + 1),
        "customer_id": customer + 1,
        "order_ts": ts,
        "order_date": ts.astype("datetime64[D]"),
        "channel": channel,
        "city": city_names[pop.city[customer]],
        "total_czk": np.round(order_total, 2),
    })
    items = pd.DataFrame({
        "order_item_id": np.arange(1, len(item_order) + 1),
        "order_id": item_order + 1,
        "product_id": product + 1,
        "quantity": quantity,
        "unit_price": unit_price,
    })
    return orders, items


PAYMENT_METHODS = {
    "store": (["card", "cash"], [0.75, 0.25]),
    "online": (["card", "bank_transfer", "cash_on_delivery", "apple_pay"], [0.55, 0.15, 0.2, 0.1]),
}
RETRY_SUCCESS_P = 0.6


def _build_payments(spec: StorySpec, orders: pd.DataFrame, rng: np.random.Generator,
                    failed: np.ndarray, retry_ok: np.ndarray):
    """One payment attempt per order. A failed attempt is retried once, which
    succeeds with RETRY_SUCCESS_P. If the retry also fails the order is cancelled.
    `failed` and `retry_ok` were drawn in the day loop."""
    n = len(orders)
    is_store = (orders["channel"] == Channel.store.value).to_numpy()
    method = np.empty(n, dtype=object)
    for kind, sel in (("store", is_store), ("online", ~is_store)):
        names, p = PAYMENT_METHODS[kind]
        method[sel] = np.array(names, dtype=object)[rng.choice(len(names), size=sel.sum(), p=p)]

    delay = rng.integers(60, 6 * 3600, n).astype("timedelta64[s]")

    ts = orders["order_ts"].to_numpy()
    first = pd.DataFrame({"order_id": orders["order_id"], "attempt": 1, "paid_ts": ts,
                          "method": method, "amount_czk": orders["total_czk"],
                          "status": np.where(failed, "failed", "paid")})
    r = failed
    retry = pd.DataFrame({"order_id": orders["order_id"].to_numpy()[r], "attempt": 2,
                          "paid_ts": ts[r] + delay[r], "method": method[r],
                          "amount_czk": orders["total_czk"].to_numpy()[r],
                          "status": np.where(retry_ok[r], "paid", "failed")})
    payments = pd.concat([first, retry], ignore_index=True).sort_values(["order_id", "attempt"], kind="stable")
    payments.insert(0, "payment_id", np.arange(1, len(payments) + 1))
    cancelled = failed & ~retry_ok
    return payments.reset_index(drop=True), cancelled
