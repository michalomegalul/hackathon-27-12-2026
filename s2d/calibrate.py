"""Recoverability gate: make every answer-key effect findable before the story is simulated.

    from s2d.calibrate import calibrate
    spec, table = calibrate(spec, seed)     # spec with sizes scaled up where needed

The story must be visible in the data, or there is nothing to detect. Each effect
is measured in noise units of the statistic a detector tests:

    sigma  = robust SD, over every date, of the 28/28-day DiD of the effect's KPI in
             its target segment against its control, on a no-story twin
    effect = the same statistic at start + lag (after-window from the end of the
             ramp), story run minus twin run with the same seed (paired, so nearly
             noise-free)
    d      = |effect| / sigma  =  |effect| * sqrt(28) / CV,  CV = sigma * sqrt(28)

so CV is the effective daily CV (autocorrelation and the control's noise
included) and d is the placebo z a detector expects. The KPIs, controls and DiD
are the detective's own (s2d.detective.kpis / scan.test_arrays / scan.did_effects);
calibration only reads them, it never changes the detective.

Difficulty sets the target d relative to the detective's reporting threshold
scan.Z_REPORT (see TARGET_OFFSET). An effect below its target has its `size`
(churn_shock: `churn_pct`) scaled up, keeping its direction; one far above it is
scaled back down, never below the story's own size. Stated facts such as
`price_change_pct` are never touched. If even the plausibility cap cannot reach
the target, the event's target is widened by dropping one key, before any scaling. Whatever still cannot reach its
target is left as it is and listed with a warning.

This module only edits the spec. It runs the simulator as a black box (feat/sim-full
changes the sim's internals, not this).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from s2d.detective import kpis as kpis_mod
from s2d.detective import scan
from s2d.sim import simulate, without_story
from s2d.sim.events import DIFFICULTY_SCALE, IMPLEMENTED_METRICS
from s2d.sim.output import DATE_COLUMNS
from s2d.spec import Difficulty, EventType, Metric, StorySpec, Target

# target d = scan.Z_REPORT + offset. Chosen so medium sizes stay realistic (DECISIONS 57):
# on Example A at 10k customers, d = Z_REPORT means roughly a -20 to -25 % price
# response (E1) and a -25 to -30 % drop of Brno stores (E5). Easy is about 1.5x
# that size, hard sits below the threshold (found in a minority of runs).
TARGET_OFFSET = {Difficulty.easy: 1.5, Difficulty.medium: 0.0, Difficulty.hard: -1.25}
# The KPIs a detector can see a metric in. churn_hazard has two; the stronger counts.
KPIS = {
    Metric.purchase_rate: ["orders"],
    Metric.acquisition_rate: ["new_customers"],
    Metric.churn_hazard: ["churn_onsets", "repeat_rate"],
}
# Plausibility caps on the simulated size (relative multiplier - 1, or churn_pct).
SIZE_CAP = {"down": -0.85, "up": 4.0}
CHURN_PCT_CAP = 60.0
# Realism caps on a drop, at medium; times the difficulty scale (x1.5 / x1 / x0.5).
# A price response is at most PRICE_ELASTICITY_CAP x the price change (15 % dearer ->
# at most -20 % orders); any other purchase or acquisition drop at most DROP_CAP.
PRICE_ELASTICITY_CAP = 4 / 3
DROP_CAP = -0.30
WIDEN_BELOW = 0.5            # widen only if even at the cap d < WIDEN_BELOW x target
ITERATIONS = 6
BAND = 1.25                  # above goal * BAND a scaled size steps back down
OVERSHOOT = 1.05             # aim 5 % above the target, d is not exactly linear in size
SEED_OFFSET = 7919           # calibrate on another seed than the run itself
KEY_ORDER = ("category", "city", "channel", "segment")  # how the KPI series name pairs


def target_d(difficulty: Difficulty) -> float:
    return scan.Z_REPORT + TARGET_OFFSET[difficulty]


def kpi_segment(target: Target) -> str:
    """The target as a KPI series name: 'city=Brno;channel=store' (keys in KPI order)."""
    parts = []
    for key in KEY_ORDER:
        values = getattr(target, key)
        if values:
            parts.append(f"{key}={','.join(v.value if hasattr(v, 'value') else v for v in values)}")
    return ";".join(parts)


def world_kpis(world) -> kpis_mod.KPISet:
    """The detective's KPI series of a simulated world, from its analyst tables only."""
    con = duckdb.connect()
    for name, df in world.tables.items():
        df = df.copy()
        for col in DATE_COLUMNS & set(df.columns):
            df[col] = pd.to_datetime(df[col]).dt.date
        con.register("_df", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _df")
        con.unregister("_df")
    return kpis_mod.build(con)


@dataclass
class Measure:
    kpi: str | None
    effect: float | None     # DiD statistic, story - twin
    sigma: float | None
    d: float | None          # None: no KPI a detector scans covers this target


def _measure(twin: kpis_mod.KPISet, story: kpis_mod.KPISet, metric: Metric, seg: str,
             day: pd.Timestamp, ramp: int, up: bool) -> Measure:
    best = Measure(None, None, None, None)
    for kpi in KPIS.get(metric, []):
        tw = scan.test_arrays(twin, kpi, seg)
        st = scan.test_arrays(story, kpi, seg)
        if tw is None or st is None or tw.rest is None or st.rest is None:
            continue
        if not tw.ratio and np.nanmean(tw.raw_seg) < scan.MIN_MEAN:
            continue  # too sparse: the detective does not scan shifts on it
        gap = ramp + kpis_mod.SMEAR_DAYS.get(kpi, 0)
        anchor = int(tw.index.get_indexer([day])[0])
        # near the end of the data the after-window is shorter, as in the detective
        na = min(scan.WINDOW, len(tw.seg) - anchor - gap)
        if anchor < scan.WINDOW or na < scan.MIN_AFTER:
            continue
        t, e_tw = scan.did_effects(tw.seg, tw.rest, gap, na=na, ratio=tw.ratio)
        _, e_st = scan.did_effects(st.seg, st.rest, gap, na=na, ratio=st.ratio)
        at = np.flatnonzero(t == anchor)
        if not len(at) or np.isnan(e_st[at[0]]) or np.isnan(e_tw[at[0]]):
            continue
        sigma = scan.robust_sd(e_tw)
        effect = float(e_st[at[0]] - e_tw[at[0]])
        want = (1 if up else -1) * (-1 if kpi in kpis_mod.INVERSE_KPIS else 1)
        d = max(0.0, want * effect) / sigma
        if best.d is None or d > best.d:
            best = Measure(kpi, effect, sigma, d)
    return best


def _slots(spec: StorySpec) -> list[tuple[int, int]]:
    """(event index, effect index) of every effect the simulator implements."""
    out = []
    for i, ev in enumerate(spec.events):
        for j, eff in enumerate(ev.effects):
            if eff.metric in IMPLEMENTED_METRICS:
                out.append((i, j))
    return out


def _sim_size(spec: StorySpec, i: int, j: int) -> float:
    ev = spec.events[i]
    if ev.type == EventType.churn_shock:
        return ev.params.churn_pct
    return ev.effects[j].size * DIFFICULTY_SCALE[spec.meta.difficulty]


def size_cap(spec: StorySpec, i: int, j: int, up: bool) -> float:
    """The largest simulated size (after difficulty scaling) calibration may set."""
    if up:
        return SIZE_CAP["up"]
    ev = spec.events[i]
    scale = DIFFICULTY_SCALE[spec.meta.difficulty]
    pct = ev.params.price_change_pct if ev.type == EventType.price_change else None
    if pct:
        realistic = -PRICE_ELASTICITY_CAP * abs(pct) / 100 * scale
    else:
        realistic = DROP_CAP * scale
    return max(SIZE_CAP["down"], realistic)


def _set_sim_size(spec: StorySpec, i: int, j: int, value: float) -> bool:
    """Set the simulated size (after difficulty scaling). True if it hit the cap."""
    ev = spec.events[i]
    if ev.type == EventType.churn_shock:
        capped = value >= CHURN_PCT_CAP
        ev.params.churn_pct = round(min(value, CHURN_PCT_CAP), 2)
        return capped
    cap = size_cap(spec, i, j, up=value > 0)
    capped = abs(value) >= abs(cap)
    v = cap if capped else value
    ev.effects[j].size = round(v / DIFFICULTY_SCALE[spec.meta.difficulty], 4)
    return capped


def _measure_all(spec: StorySpec, seed: int, twin_ks) -> dict[tuple[int, int], Measure]:
    story_ks = world_kpis(simulate(spec, seed=seed))
    out = {}
    for i, j in _slots(spec):
        ev = spec.events[i]
        eff = ev.effects[j]
        day = pd.Timestamp(ev.start) + pd.Timedelta(days=eff.lag_days)
        ramp = 0 if ev.type == EventType.churn_shock else eff.ramp_days
        up = _sim_size(spec, i, j) > 0 if ev.type != EventType.churn_shock else True
        out[(i, j)] = _measure(twin_ks, story_ks, eff.metric, kpi_segment(ev.target), day, ramp, up)
    return out


def _at_cap(spec: StorySpec, i: int) -> StorySpec:
    """A copy of the spec with every simulated effect of event i at its size cap."""
    out = spec.model_copy(deep=True)
    for k in _slots(out):
        if k[0] == i:
            v = _sim_size(out, *k)
            _set_sim_size(out, *k, CHURN_PCT_CAP if out.events[i].type == EventType.churn_shock
                          else size_cap(out, *k, up=v > 0))
    return out


def _widen_options(target: Target) -> list[Target]:
    keys = [k for k in ("city", "segment", "channel", "category") if getattr(target, k)]
    if len(keys) < 2:
        return []
    return [target.model_copy(update={k: None}) for k in keys]


def calibrate(spec: StorySpec, seed: int | None = None, log=None) -> tuple[StorySpec, pd.DataFrame]:
    """Scale effects until each one has d in [target, target * BAND]. Returns the
    calibrated spec (a copy) and one row per effect for _truth.calibration."""
    say = log or (lambda m: print(m, file=sys.stderr))
    seed = (spec.meta.seed if seed is None else seed) + SEED_OFFSET
    spec = spec.model_copy(deep=True)
    cols = ["event_id", "metric", "kpi", "segment", "original_segment", "original_size", "story_size",
            "simulated_size", "factor", "sigma", "cv_eff", "effect", "d_original", "d", "target_d", "status"]
    slots = _slots(spec)
    if not slots:
        return spec, pd.DataFrame(columns=cols)

    goal = target_d(spec.meta.difficulty)
    twin_ks = world_kpis(simulate(without_story(spec), seed=seed))
    orig_size = {(i, j): (spec.events[i].params.churn_pct if spec.events[i].type == EventType.churn_shock
                          else spec.events[i].effects[j].size) for i, j in slots}
    story_size = {k: _sim_size(spec, *k) for k in slots}
    orig_target = {i: spec.events[i].target for i, _ in slots}
    capped: set[tuple[int, int]] = set()
    widened: set[int] = set()

    first = _measure_all(spec, seed, twin_ks)

    # 1. Widen first. An event whose target stays below half the goal even at the
    # size cap (or is not visible in any scanned KPI) loses one key, the option with the
    # largest d at the cap. Judged at the cap, before any scaling, so a later
    # widening cannot leave another event's earlier scaling stale (DECISIONS 56).
    for i in sorted({i for i, _ in slots}):
        own = [k for k in slots if k[0] == i]
        at_cap = _at_cap(spec, i)
        m_cap = _measure_all(at_cap, seed, twin_ks)
        here = min((m_cap[k].d or 0.0) for k in own)
        if all(first[k].d is not None for k in own) and here >= WIDEN_BELOW * goal:
            continue  # reachable, or a near miss: a near miss stays below_target, not a new story
        best = None
        for opt in _widen_options(spec.events[i].target):
            trial = at_cap.model_copy(deep=True)
            trial.events[i].target = opt
            mt = _measure_all(trial, seed, twin_ks)
            d = min((mt[k].d or 0.0) for k in own)
            if best is None or d > best[0]:
                best = (d, opt)
        if best is not None and best[0] > here:
            spec.events[i].target = best[1]
            widened.add(i)

    # 2. Scale, both ways. Below the goal a size grows; above goal * BAND it steps
    # back down, but never below the story's own size and never past the cap.
    m = _measure_all(spec, seed, twin_ks)
    for _ in range(ITERATIONS):
        off = [k for k in slots if m[k].d is not None and (
            (m[k].d < goal and k not in capped)
            or (m[k].d > goal * BAND and abs(_sim_size(spec, *k)) > abs(story_size[k]) + 1e-9))]
        if not off:
            break
        for k in off:
            factor = float(np.clip(goal * OVERSHOOT / max(m[k].d, 1e-9), 1 / 4, 8))
            new = _sim_size(spec, *k) * factor
            if abs(new) < abs(story_size[k]):
                new = story_size[k]
            if _set_sim_size(spec, *k, new):
                capped.add(k)
            else:
                capped.discard(k)
        m = _measure_all(spec, seed, twin_ks)

    rows = []
    for k in slots:
        i, j = k
        ev = spec.events[i]
        mk = m[k]
        if mk.d is None:
            status = "not_measurable"
        elif mk.d < goal:
            status = "below_target"
        elif i in widened:
            status = "widened"
        elif abs(_sim_size(spec, *k) - story_size[k]) > 1e-9:
            status = "scaled"
        else:
            status = "ok"
        if status in ("not_measurable", "below_target"):
            say(f"WARNING calibration: {ev.id} {ev.effects[j].metric.value} on '{kpi_segment(ev.target)}' "
                f"has d = {mk.d if mk.d is None else round(mk.d, 2)} < target {goal:.1f} ({status}); "
                f"it may not be detectable")
        rows.append({
            "event_id": ev.id, "metric": ev.effects[j].metric.value, "kpi": mk.kpi,
            "segment": ev.target.describe(), "original_segment": orig_target[i].describe(),
            "original_size": orig_size[k], "story_size": round(story_size[k], 4),
            "simulated_size": round(_sim_size(spec, *k), 4),
            "factor": round(_sim_size(spec, *k) / story_size[k], 3) if story_size[k] else None,
            "sigma": None if mk.sigma is None else round(mk.sigma, 5),
            "cv_eff": None if mk.sigma is None else round(mk.sigma * np.sqrt(scan.WINDOW), 4),
            "effect": None if mk.effect is None else round(mk.effect, 5),
            "d_original": None if first[k].d is None else round(first[k].d, 2),
            "d": None if mk.d is None else round(mk.d, 2),
            "target_d": goal, "status": status,
        })
    return spec, pd.DataFrame(rows, columns=cols)


def format_table(table: pd.DataFrame) -> str:
    lines = ["calibration (d = effect in noise units; target from difficulty):"]
    for r in table.itertuples():
        seg = r.segment if r.segment == r.original_segment else f"{r.original_segment} -> {r.segment}"
        lines.append(f"  {r.event_id:<4} {r.metric:<16} {seg:<36} size {r.story_size:+.3g} -> {r.simulated_size:+.3g}"
                     f"  d {r.d_original} -> {r.d} (target {r.target_d:.1f}, via {r.kpi})  {r.status}")
    return "\n".join(lines)
