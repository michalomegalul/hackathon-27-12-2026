"""Target vs realized: did the churn we asked for actually happen?

For every simulated churn effect we take the targeted customers who are still
active when the effect starts (the cohort) and measure what share of them leave
while the effect is on. We compare against:

  expected  - what the hazard model predicts for this cohort, and
  twin      - the same measurement in the no-story run (events removed),

so "excess" = story minus twin = the churn the story caused.
"""

import numpy as np
import pandas as pd

from s2d.spec import EventType, Metric

from .engine import _prepare_effects, churn_hazard_on_day
from .population import target_mask


def _cohort(world, target, w0: int) -> np.ndarray:
    pop, churn_day = world.population, world.result.churn_day
    alive_at_w0 = (pop.signup_day <= w0) & ((churn_day < 0) | (churn_day >= w0))
    return target_mask(target, world.spec, pop.segment, pop.city, pop.channel) & alive_at_w0


def _realized(world, cohort: np.ndarray, w0: int, w1: int) -> float:
    d = world.result.churn_day[cohort]
    return float(np.mean((d >= w0) & (d < w1)))


def _expected(world, cohort: np.ndarray, w0: int, w1: int) -> float:
    effects = _prepare_effects(world.spec, world.story, world.population, world.catalog, Metric.churn_hazard)
    survive = np.ones(cohort.sum())
    for t in range(w0, w1):
        survive *= 1 - churn_hazard_on_day(t, world.population, effects)[cohort]
    return float(1 - survive.mean())


def churn_report(world, twin) -> pd.DataFrame:
    """One row per simulated churn effect. `twin` is the no-story run."""
    rows = []
    for eff in world.story.for_metric(Metric.churn_hazard):
        if eff.is_decoy:
            continue
        on = np.flatnonzero(eff.curve > 0)
        w0, w1 = int(on[0]), int(on[-1]) + 1
        cohort = _cohort(world, eff.target, w0)
        twin_cohort = _cohort(twin, eff.target, w0)
        row = {
            "event_id": eff.event_id,
            "target": eff.target.describe() or "everyone",
            "window": f"{world.calendar.dates[w0]}..{world.calendar.dates[w1 - 1]}",
            "cohort": int(cohort.sum()),
            "expected": _expected(world, cohort, w0, w1),
            "realized": _realized(world, cohort, w0, w1),
            "twin_expected": _expected(twin, twin_cohort, w0, w1),
            "twin_realized": _realized(twin, twin_cohort, w0, w1),
        }
        row["expected_excess"] = row["expected"] - row["twin_expected"]
        row["realized_excess"] = row["realized"] - row["twin_realized"]
        # For churn_shock the spec states the target directly: "p of the segment
        # leaves within W days" on top of normal churn. Undo the baseline with
        # 1 - (1 - story) / (1 - twin) to compare against p.
        if eff.event_type == EventType.churn_shock.value:
            ev = next(e for e in world.spec.events if e.id == eff.event_id)
            row["stated_p"] = ev.params.churn_pct / 100
            row["realized_p"] = 1 - (1 - row["realized"]) / (1 - row["twin_realized"])
        rows.append(row)
    return pd.DataFrame(rows)


def format_report(df: pd.DataFrame) -> str:
    if df.empty:
        return "no simulated churn effects"
    lines = ["Churn: target vs realized (share of cohort leaving inside the effect window)"]
    for r in df.itertuples():
        lines.append(f"  {r.event_id:<4} {r.target:<28} {r.window}  cohort={r.cohort}")
        lines.append(f"       story    expected {r.expected:6.1%}  realized {r.realized:6.1%}")
        lines.append(f"       no-story expected {r.twin_expected:6.1%}  realized {r.twin_realized:6.1%}")
        lines.append(f"       excess   expected {r.expected_excess:+6.1%}  realized {r.realized_excess:+6.1%}")
        if "stated_p" in df.columns and not pd.isna(r.stated_p):
            lines.append(f"       stated target p {r.stated_p:6.1%}  realized p {r.realized_p:6.1%}")
    return "\n".join(lines)
