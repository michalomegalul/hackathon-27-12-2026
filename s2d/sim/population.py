"""Customers: who exists, when they arrive, and what they look like.

All customers (the starting base plus everyone acquired during the sim) are
created up front, because acquisition does not depend on what customers do.
The day loop then only needs `signup_day` to know who is already around.
"""

import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd
from faker import Faker

from s2d.spec import Channel, Metric, StorySpec, Target

from .calendar import Calendar
from .events import CompiledStory, daily_hazard

# Gamma shape for each customer's base purchase rate. Shape 2 means a coefficient
# of variation of about 0.7: some loyal heavy buyers, many occasional ones.
BASE_RATE_GAMMA_SHAPE = 2.0
# Signup dates of the starting base are spread over this many days before the sim.
PRE_START_SIGNUP_DAYS = 730
FAKER_POOL_SIZE = 400
EMAIL_DOMAINS = (["seznam.cz", "gmail.com", "email.cz", "centrum.cz", "outlook.com"],
                 [0.38, 0.32, 0.14, 0.10, 0.06])


@dataclass
class Population:
    n: int
    segment: np.ndarray       # index into spec segments
    city: np.ndarray          # index into spec cities
    channel: np.ndarray       # index into spec channels ("home" channel)
    signup_day: np.ndarray    # day index; negative = signed up before the sim
    base_rate: np.ndarray     # expected orders per day at multiplier 1
    base_hazard: np.ndarray   # daily churn probability at multiplier 1
    price_sensitivity: np.ndarray  # relative to the average customer (mean 1)
    table: pd.DataFrame       # analyst-facing customers table


def target_mask(target: Target, spec: StorySpec, segment: np.ndarray, city: np.ndarray,
                channel: np.ndarray) -> np.ndarray:
    """True where a customer (or cell) matches the target's city/segment/channel.
    Category and supplier filters do not select customers, so they are ignored here."""
    mask = np.ones(len(segment), dtype=bool)
    if target.segment:
        ids = [s.id for s in spec.entities.customers.segments]
        mask &= np.isin(segment, [ids.index(s) for s in target.segment])
    if target.city:
        names = [c.name for c in spec.company.cities]
        mask &= np.isin(city, [names.index(c) for c in target.city])
    if target.channel:
        chans = [c.channel for c in spec.company.channels]
        mask &= np.isin(channel, [chans.index(c) for c in target.channel])
    return mask


def _cells(spec: StorySpec):
    """Every (segment, city, channel) combination with its share of customers.
    The store channel only exists in cities that have a store."""
    seg, city, chan, weight = [], [], [], []
    for s_idx, s in enumerate(spec.entities.customers.segments):
        for c_idx, c in enumerate(spec.company.cities):
            usable = [(k, ch) for k, ch in enumerate(spec.company.channels)
                      if ch.channel != Channel.store or c.has_store]
            total = sum(ch.weight for _, ch in usable)
            for k, ch in usable:
                seg.append(s_idx)
                city.append(c_idx)
                chan.append(k)
                weight.append(s.share * c.weight * ch.weight / total)
    w = np.array(weight)
    return np.array(seg), np.array(city), np.array(chan), w / w.sum()


def _acquisitions(spec: StorySpec, cal: Calendar, story: CompiledStory, rng: np.random.Generator):
    """New customers per day and cell: Poisson around a rate that replaces churned
    customers and adds `growth_per_year`, times seasonality and acquisition events."""
    seg, city, chan, w = _cells(spec)
    segments = spec.entities.customers.segments
    n0 = spec.entities.customers.n
    growth = spec.entities.customers.growth_per_year

    annual_churn = np.array([1 - (1 - s.base_churn_per_month) ** 12 for s in segments])
    per_day = np.maximum(n0 * w * (growth + annual_churn[seg]) / 365, 0)  # per cell

    rate = cal.day_factor[:, None] * per_day[None, :]  # [day, cell]
    for eff in story.for_metric(Metric.acquisition_rate):
        hit = target_mask(eff.target, spec, seg, city, chan)
        rate[:, hit] *= np.maximum(1 + eff.size * eff.curve[:, None], 0)

    counts = rng.poisson(rate)  # [day, cell]
    day_idx, cell_idx = np.nonzero(counts)
    reps = counts[day_idx, cell_idx]
    cell_of_new = np.repeat(cell_idx, reps)
    day_of_new = np.repeat(day_idx, reps)

    # Starting base: n0 customers spread over cells, signed up in the past.
    cell_of_old = rng.choice(len(w), size=n0, p=w)
    day_of_old = np.sort(-rng.integers(1, PRE_START_SIGNUP_DAYS + 1, size=n0))

    cells = np.concatenate([cell_of_old, cell_of_new])
    days = np.concatenate([day_of_old, day_of_new])
    return seg[cells], city[cells], chan[cells], days


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _people(n: int, rng: np.random.Generator, faker_seed: int) -> pd.DataFrame:
    """Czech names, e-mails and phones. Gender is chosen first so that female
    customers get female surnames (Nováková, Černá)."""
    fake = Faker("cs_CZ")
    fake.seed_instance(faker_seed)
    # dict.fromkeys keeps first-seen order (a set would not be deterministic).
    pools = {
        "first_F": list(dict.fromkeys(fake.first_name_female() for _ in range(FAKER_POOL_SIZE))),
        "last_F": list(dict.fromkeys(fake.last_name_female() for _ in range(FAKER_POOL_SIZE))),
        "first_M": list(dict.fromkeys(fake.first_name_male() for _ in range(FAKER_POOL_SIZE))),
        "last_M": list(dict.fromkeys(fake.last_name_male() for _ in range(FAKER_POOL_SIZE))),
    }
    gender = np.where(rng.random(n) < 0.52, "F", "M")
    first = np.empty(n, dtype=object)
    last = np.empty(n, dtype=object)
    for g in ("F", "M"):
        idx = np.flatnonzero(gender == g)
        first[idx] = np.array(pools[f"first_{g}"], dtype=object)[rng.integers(0, len(pools[f"first_{g}"]), len(idx))]
        last[idx] = np.array(pools[f"last_{g}"], dtype=object)[rng.integers(0, len(pools[f"last_{g}"]), len(idx))]

    domains = np.array(EMAIL_DOMAINS[0])[rng.choice(len(EMAIL_DOMAINS[0]), size=n, p=EMAIL_DOMAINS[1])]
    suffix = rng.integers(1, 100, size=n)
    email = [f"{_ascii(f)}.{_ascii(l)}{s}@{d}" for f, l, s, d in zip(first, last, suffix, domains)]

    mobile = rng.choice([6, 7], size=n) * 100 + rng.integers(0, 100, size=n)  # 6xx / 7xx
    rest = rng.integers(0, 1_000_000, size=n)
    phone = [f"+420 {m:03d} {r // 1000:03d} {r % 1000:03d}" for m, r in zip(mobile, rest)]

    return pd.DataFrame({"first_name": first, "last_name": last, "gender": gender,
                         "email": email, "phone": phone})


def build_population(spec: StorySpec, cal: Calendar, story: CompiledStory,
                     streams: dict[str, np.random.Generator]) -> Population:
    segment, city, channel, signup_day = _acquisitions(spec, cal, story, streams["acquisition"])
    n = len(segment)
    rng = streams["customers"]
    segments = spec.entities.customers.segments

    # Each customer's own purchase rate: Gamma around the segment's monthly orders.
    # Mixing Gamma rates with Poisson draws gives realistic negative-binomial counts.
    seg_mean = np.array([s.base_orders_per_month / 30.4 for s in segments])
    base_rate = rng.gamma(BASE_RATE_GAMMA_SHAPE, seg_mean[segment] / BASE_RATE_GAMMA_SHAPE)

    seg_hazard = np.array([daily_hazard(s.base_churn_per_month, 30.4) for s in segments])
    sens = np.array([s.price_sensitivity for s in segments])
    sens_mean = sum(s.share * s.price_sensitivity for s in segments)
    price_sensitivity = sens[segment] / sens_mean if sens_mean > 0 else np.ones(n)

    people = _people(n, rng, int(streams["faker"].integers(0, 2**31 - 1)))
    city_names = np.array([c.name for c in spec.company.cities], dtype=object)
    seg_ids = np.array([s.id for s in segments], dtype=object)
    chan_names = np.array([c.channel.value for c in spec.company.channels], dtype=object)
    start = np.datetime64(cal.dates[0], "D")

    table = pd.DataFrame({
        "customer_id": np.arange(1, n + 1),
        **people,
        "city": city_names[city],
        "segment": seg_ids[segment],
        "preferred_channel": chan_names[channel],
        "signup_date": (start + signup_day.astype("timedelta64[D]")),
    })
    return Population(n, segment, city, channel, signup_day, base_rate,
                      seg_hazard[segment], price_sensitivity, table)
