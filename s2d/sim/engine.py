"""The vectorized day loop.

State is a handful of numpy arrays with one entry per customer. Each day:

  1. churn:     who leaves today       (daily hazard, Bernoulli draw)
  2. purchases: how many orders each   (Poisson with rate λ[i,t])
  3. baskets:   what is in each order  (Zipf popularity, geometric size)
then, after the loop, payments for every order.

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


@dataclass
class SimResult:
    churn_day: np.ndarray        # day index the customer left, -1 = still active
    orders: pd.DataFrame
    order_items: pd.DataFrame
    payments: pd.DataFrame


def _prepare_effects(spec: StorySpec, story: CompiledStory, pop: Population, cat: Catalog, metric: Metric):
    out = []
    for eff in story.for_metric(metric):
        cats = None
        if eff.target.category:
            cats = np.isin(cat.category_ids, eff.target.category)
        out.append(_ActiveEffect(
            eff.size, eff.curve,
            target_mask(eff.target, spec, pop.segment, pop.city, pop.channel),
            cats, eff.price_sensitive, eff.additive,
        ))
    return out


def churn_hazard_on_day(t: int, pop: Population, churn_effects: list[_ActiveEffect]) -> np.ndarray:
    """Daily probability of leaving, per customer, on day t (ignores who is alive)."""
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
    return np.minimum(pop.base_hazard * relative + additive, 1.0)


def _holiday_factor(spec: StorySpec, pop: Population, cal: Calendar) -> np.ndarray:
    """Multiplier per customer for a public holiday, by their home channel."""
    is_store = np.array([c.channel == Channel.store for c in spec.company.channels])[pop.channel]
    return np.where(is_store, cal.store_holiday_factor, HOLIDAY_FACTOR_ONLINE)


def run_day_loop(spec: StorySpec, cal: Calendar, story: CompiledStory, pop: Population,
                 cat: Catalog, streams: dict[str, np.random.Generator]) -> SimResult:
    rng_churn = streams["churn"]
    rng_buy = streams["purchases"]
    n_cats = len(cat.category_ids)

    churn_effects = _prepare_effects(spec, story, pop, cat, Metric.churn_hazard)
    buy_effects = _prepare_effects(spec, story, pop, cat, Metric.purchase_rate)
    holiday_factor = _holiday_factor(spec, pop, cal)

    churn_day = np.full(pop.n, -1)
    order_customer, order_day, order_category = [], [], []

    for t in range(cal.n_days):
        alive = (pop.signup_day <= t) & (churn_day < 0)

        # 1. churn. Draw one uniform per customer (alive or not) so that the
        #    random numbers line up between runs with and without the story.
        hazard = churn_hazard_on_day(t, pop, churn_effects)
        leaves = alive & (rng_churn.random(pop.n) < hazard)
        churn_day[leaves] = t
        alive &= ~leaves

        # 2. purchases. rate[i, c] = expected orders of customer i whose main item is in category c.
        lam = pop.base_rate * cal.day_factor[t] * alive
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
        buyers = np.flatnonzero(n_orders)
        who = np.repeat(buyers, n_orders[buyers])

        # main category of each order, in proportion to rate[i, c]
        cdf = np.cumsum(rate[who], axis=1) / total[who][:, None]
        u = rng_buy.random(len(who))
        main_cat = np.minimum((cdf < u[:, None]).sum(axis=1), n_cats - 1)

        order_customer.append(who)
        order_day.append(np.full(len(who), t))
        order_category.append(main_cat)

    orders, items = _build_orders(spec, cal, pop, cat,
                                  np.concatenate(order_customer), np.concatenate(order_day),
                                  np.concatenate(order_category), rng_buy)
    payments, cancelled = _build_payments(spec, orders, streams["payments"])
    orders["status"] = np.where(cancelled, "cancelled", "completed")
    return SimResult(churn_day, orders, items, payments)


def _build_orders(spec, cal, pop, cat, customer, day, main_cat, rng):
    n = len(customer)
    chan_names = np.array([c.channel.value for c in spec.company.channels], dtype=object)
    city_names = np.array([c.name for c in spec.company.cities], dtype=object)
    channel = chan_names[pop.channel[customer]]

    # Order time: stores are open 7:00-19:59, online follows ONLINE_HOURS.
    is_store = channel == Channel.store.value
    hour = np.where(is_store, rng.integers(7, 20, n), rng.choice(24, size=n, p=ONLINE_HOURS))
    seconds = hour * 3600 + rng.integers(0, 3600, n)
    start = np.datetime64(cal.dates[0], "s")
    ts = start + (day * 86400 + seconds).astype("timedelta64[s]")

    # Baskets: first item from the main category, extra items from overall popularity.
    size = rng.geometric(BASKET_EXTRA_ITEM_P, n)
    item_order = np.repeat(np.arange(n), size)
    first = np.zeros(len(item_order), dtype=bool)
    first[np.concatenate([[0], np.cumsum(size)[:-1]])] = True

    product = np.empty(len(item_order), dtype=np.int64)
    u = rng.random(len(item_order))
    first_cat = main_cat[item_order[first]]
    first_u = u[first]
    first_product = np.empty(first.sum(), dtype=np.int64)
    for c in range(len(cat.category_ids)):
        sel = first_cat == c
        pos = np.searchsorted(cat.within_cdf[c], first_u[sel] * cat.within_cdf[c][-1])
        first_product[sel] = cat.within_index[c][np.minimum(pos, len(cat.within_index[c]) - 1)]
    product[first] = first_product
    pos = np.searchsorted(cat.global_cdf, u[~first] * cat.global_cdf[-1])
    product[~first] = np.minimum(pos, len(cat.global_cdf) - 1)
    quantity = rng.geometric(QUANTITY_P, len(item_order))

    # Merge repeated products inside one order into a single line.
    key = item_order * len(cat.global_cdf) + product
    key, inverse = np.unique(key, return_inverse=True)
    quantity = np.bincount(inverse, weights=quantity).astype(np.int64)
    item_order = key // len(cat.global_cdf)
    product = key % len(cat.global_cdf)
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


def _build_payments(spec: StorySpec, orders: pd.DataFrame, rng: np.random.Generator):
    """One payment attempt per order. A failed attempt is retried once, which
    succeeds with RETRY_SUCCESS_P. If the retry also fails the order is cancelled."""
    n = len(orders)
    is_store = (orders["channel"] == Channel.store.value).to_numpy()
    method = np.empty(n, dtype=object)
    for kind, sel in (("store", is_store), ("online", ~is_store)):
        names, p = PAYMENT_METHODS[kind]
        method[sel] = np.array(names, dtype=object)[rng.choice(len(names), size=sel.sum(), p=p)]

    failed = rng.random(n) < spec.baseline.payment_failure_rate
    retry_ok = rng.random(n) < RETRY_SUCCESS_P
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
