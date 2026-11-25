"""Subscriptions: customers of a subscription segment get coffee (or whatever the shop
sells) on a schedule, and churn shows up as a dated cancellation.

Each subscriber has one plan, chosen from their own purchase rate so that the plan
carries about SCHEDULED_SHARE of their orders; the rest are ad-hoc orders (the
Poisson draw, scaled down). A scheduled order is a purchase occasion like any other:
an upset customer may cancel instead (service.py). When a subscriber leaves, for any
reason, the subscription is cancelled that day with the cause of leaving as the
reason, and the scheduled orders stop.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from s2d.spec import StorySpec

PLANS = (("týdenní", 7), ("dvoutýdenní", 14), ("měsíční", 30), ("dvouměsíční", 61))
SCHEDULED_SHARE = 0.7        # share of a subscriber's orders that come on schedule
REASON_OTHER = ("už nepotřebuji", "finance", "jiné")  # baseline churn: no story cause
REASON_OTHER_P = (0.4, 0.3, 0.3)


@dataclass
class Plans:
    is_sub: np.ndarray        # bool per customer
    plan: np.ndarray          # index into PLANS, -1 = none
    days: np.ndarray          # interval in days, 0 = none
    next_due: np.ndarray      # next scheduled day
    sub_id: np.ndarray        # subscription_id per customer (0 = none)


def build_plans(spec: StorySpec, segment: np.ndarray, base_rate: np.ndarray, signup_day: np.ndarray,
                rng: np.random.Generator) -> Plans:
    subs = np.array([s.has_subscription for s in spec.entities.customers.segments])
    is_sub = subs[segment]
    n = len(segment)
    plan = np.full(n, -1)
    days = np.zeros(n, dtype=np.int64)
    if is_sub.any():
        want = 1 / np.maximum(SCHEDULED_SHARE * base_rate[is_sub], 1e-9)  # days between scheduled orders
        lengths = np.array([d for _, d in PLANS])
        pick = np.abs(np.log(want)[:, None] - np.log(lengths)[None, :]).argmin(axis=1)
        plan[is_sub] = pick
        days[is_sub] = lengths[pick]
    # first delivery: a random day of the first interval after signup, then every interval
    phase = (rng.random(n) * np.maximum(days, 1)).astype(np.int64)
    first = signup_day + phase
    behind = np.where(days > 0, np.maximum(0, -first + days - 1) // np.maximum(days, 1), 0)
    next_due = first + behind * days      # the first due day >= 0 for pre-sim subscribers
    sub_id = np.zeros(n, dtype=np.int64)
    sub_id[is_sub] = np.arange(1, is_sub.sum() + 1)
    return Plans(is_sub, plan, days, next_due, sub_id)


def subscriptions_table(plans: Plans, signup_date: pd.Series, churn_day: np.ndarray, cause: np.ndarray,
                        start: np.datetime64, rng: np.random.Generator) -> pd.DataFrame:
    idx = np.flatnonzero(plans.is_sub)
    gone = churn_day[idx] >= 0
    cancelled = np.where(gone, start + churn_day[idx].astype("timedelta64[D]"), np.datetime64("NaT"))
    reason = cause[idx].astype(object)
    other = gone & (reason == "jiné")
    reason[other] = np.array(REASON_OTHER, dtype=object)[rng.choice(len(REASON_OTHER), other.sum(), p=REASON_OTHER_P)]
    reason[~gone] = None
    return pd.DataFrame({
        "subscription_id": plans.sub_id[idx],
        "customer_id": idx + 1,
        "plan": np.array([p for p, _ in PLANS], dtype=object)[plans.plan[idx]],
        "started_at": signup_date.to_numpy()[idx],
        "cancelled_at": cancelled,
        "cancel_reason": reason,
    })
