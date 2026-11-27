"""Recoverability gate: make every answer-key effect confirmable before the story is simulated.

    from s2d.calibrate import calibrate
    spec, table = calibrate(spec, seed)     # spec with sizes scaled where needed

The story must be visible in the data. Each effect is measured in noise units of
the verifier's test for it (s2d/verify.py: the event's KPI in its target against
the other values of the same dimension, 28 days after start + lag vs 28 before):

    sigma  = robust SD of that DiD over every date more than 56 days from T, on a
             no-story twin (the placebo-in-time null of the test)
    effect = the DiD at T, story run minus twin run with the same seed (paired,
             so nearly noise-free)
    d      = |effect| / sigma, the placebo z the verifier expects

Difficulty sets the target d (TARGET_D). An effect below its target has its
`size` (churn_shock: `churn_pct`) scaled up, keeping its direction; one far above
it is scaled back down, never below the story's own size. Stated facts such as
`price_change_pct` and a size the story gives (`effect.size_stated`, DECISIONS 90)
are never touched: such an effect is only measured, and below its target it is
reported as below_target with a warning. Drops are capped at realistic sizes. If
even the cap is far from the target, the event's target is widened by dropping
one key, before any scaling. Whatever still cannot reach its target is left as
it is and listed with a warning.

This module only edits the spec. It runs the simulator as a black box (feat/sim-full
changes the sim's internals, not this).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from s2d import verify
from s2d.detective import scan
from s2d.sim import simulate, without_story
from s2d.sim.events import mechanism, size_scale
from s2d.spec import Difficulty, EventType, StorySpec, Target

# Target d of the verifier's single test (DECISIONS 62). verify.Z_CONFIRM is 3:
# medium sits half a noise unit above it, hard half a unit below.
TARGET_D = {Difficulty.easy: 5.0, Difficulty.medium: 3.5, Difficulty.hard: 2.5}
# Plausibility caps on the simulated size (relative multiplier - 1, or churn_pct).
SIZE_CAP = {"down": -0.85, "up": 4.0}
CHURN_PCT_CAP = 60.0
# Realism caps on a drop, the same at every difficulty. A price response is at most
# PRICE_ELASTICITY_CAP x the price change (15 % dearer -> at most -20 % orders); any
# other purchase or acquisition drop at most DROP_CAP.
PRICE_ELASTICITY_CAP = 4 / 3
DROP_CAP = -0.30
WIDEN_BELOW = 0.5            # widen only if even at the cap d < WIDEN_BELOW x target
ITERATIONS = 6
BAND = 1.25                  # above goal * BAND a scaled size steps back down
OVERSHOOT = 1.05             # aim 5 % above the target, d is not exactly linear in size
SEED_OFFSET = 7919           # calibrate on another seed than the run itself
KEY_ORDER = ("category", "city", "channel", "segment")  # how the KPI series name pairs


def target_d(difficulty: Difficulty) -> float:
    return TARGET_D[difficulty]


def kpi_segment(target: Target) -> str:
    """The target as a KPI series name: 'city=Brno;channel=store' (keys in KPI order)."""
    parts = []
    for key in KEY_ORDER:
        values = getattr(target, key)
        if values:
            parts.append(f"{key}={','.join(v.value if hasattr(v, 'value') else v for v in values)}")
    return ";".join(parts)


@dataclass
class Measure:
    kpi: str | None
    effect: float | None     # DiD statistic, story - twin
    sigma: float | None
    d: float | None          # None: the verifier has no test for this target


class Twin:
    """The no-story twin's tables, with each test's daily series cached."""

    def __init__(self, world):
        self.con = verify.world_con(world)
        self.lo, self.hi = verify._range(self.con)
        self._cache: dict[str, pd.DataFrame] = {}
        self._resolved: dict[tuple, verify.Hypothesis] = {}

    def resolve(self, h: verify.Hypothesis) -> verify.Hypothesis:
        """Control and unit as the verifier picks them (on the twin: no effect in it)."""
        k = (h.event_id, h.metric, h.kpi)
        if k not in self._resolved:
            self._resolved[k] = verify.resolve(self.con, h, self.lo, self.hi)
        r = self._resolved[k]
        return verify.replace(h, vary=r.vary, treated=r.treated, fixed=r.fixed,
                              control_mode=r.control_mode, absolute=r.absolute)

    def series(self, h: verify.Hypothesis) -> pd.DataFrame:
        k = verify._ctes(h, self.lo, self.hi)
        if k not in self._cache:
            self._cache[k] = verify.series(self.con, h, self.lo, self.hi)
        return self._cache[k]


def _measure(twin: Twin, story_con, h: verify.Hypothesis | None) -> Measure:
    if h is None:
        return Measure(None, None, None, None)
    h = twin.resolve(h)  # the verifier's control and unit for this test
    tw = verify.statistic(twin.series(h), h)
    st = verify.statistic(verify.series(story_con, h, twin.lo, twin.hi), h)
    if tw is None or st is None:
        return Measure(h.kpi, None, None, None)
    seg_tw, rest_tw, iT, na = tw
    seg_st, rest_st = st[0], st[1]
    t, e_tw = scan.did_effects(seg_tw, rest_tw, 0, scan.WINDOW, na, h.ratio)
    _, e_st = scan.did_effects(seg_st, rest_st, 0, scan.WINDOW, na, h.ratio)
    at = np.flatnonzero(t == iT)
    if not len(at) or np.isnan(e_st[at[0]]) or np.isnan(e_tw[at[0]]):
        return Measure(h.kpi, None, None, None)
    sigma = scan.robust_sd(verify.null_effects(seg_tw, rest_tw, iT, na, h.ratio))
    effect = float(e_st[at[0]] - e_tw[at[0]])
    want = 1 if h.direction == "up" else -1
    return Measure(h.kpi, effect, sigma, max(0.0, want * effect) / sigma)


def _slots(spec: StorySpec) -> list[tuple[int, int]]:
    """(event index, effect index) of every effect the simulator applies as a curve.
    Courier switches are stated facts and emergent effects have no size to scale."""
    out = []
    for i, ev in enumerate(spec.events):
        for j, eff in enumerate(ev.effects):
            try:
                if mechanism(spec, ev, eff) == "curve":
                    out.append((i, j))
            except NotImplementedError:
                pass
    return out


def _sim_size(spec: StorySpec, i: int, j: int) -> float:
    ev = spec.events[i]
    if ev.type == EventType.churn_shock:
        return ev.params.churn_pct
    return ev.effects[j].size * size_scale(spec, ev.effects[j])


def stated(spec: StorySpec, i: int, j: int) -> bool:
    """Is the simulated size of this effect a number the story states (DECISIONS 90)?
    A churn_shock's size is its churn_pct, stated if any of its effects says so."""
    ev = spec.events[i]
    if ev.type == EventType.churn_shock:
        return any(e.size_stated for e in ev.effects)
    return ev.effects[j].size_stated


def size_cap(spec: StorySpec, i: int, j: int, up: bool) -> float:
    """The largest simulated size (after difficulty scaling) calibration may set."""
    if up:
        return SIZE_CAP["up"]
    ev = spec.events[i]
    pct = ev.params.price_change_pct if ev.type == EventType.price_change else None
    realistic = -PRICE_ELASTICITY_CAP * abs(pct) / 100 if pct else DROP_CAP
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
    ev.effects[j].size = round(v / size_scale(spec, ev.effects[j]), 4)
    return capped


def _measure_all(spec: StorySpec, seed: int, twin: Twin) -> dict[tuple[int, int], Measure]:
    story_con = verify.world_con(simulate(spec, seed=seed))
    return {(i, j): _measure(twin, story_con, verify.hypothesis(spec, spec.events[i], spec.events[i].effects[j]))
            for i, j in _slots(spec)}


def _at_cap(spec: StorySpec, i: int) -> StorySpec:
    """A copy of the spec with every simulated effect of event i at its size cap."""
    out = spec.model_copy(deep=True)
    for k in _slots(out):
        if k[0] == i and not stated(out, *k):
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
            "simulated_size", "factor", "sigma", "cv_eff", "effect", "d_original", "d", "target_d", "status",
            "stated"]
    slots = _slots(spec)
    if not slots:
        return spec, pd.DataFrame(columns=cols)

    goal = target_d(spec.meta.difficulty)
    twin = Twin(simulate(without_story(spec), seed=seed))
    orig_size = {(i, j): (spec.events[i].params.churn_pct if spec.events[i].type == EventType.churn_shock
                          else spec.events[i].effects[j].size) for i, j in slots}
    story_size = {k: _sim_size(spec, *k) for k in slots}
    orig_target = {i: spec.events[i].target for i, _ in slots}
    capped: set[tuple[int, int]] = set()
    widened: set[int] = set()
    fixed = {k for k in slots if stated(spec, *k)}  # the story's own numbers: measured, never changed

    first = _measure_all(spec, seed, twin)

    # 1. Widen first. An event whose target stays below half the goal even at the
    # size cap (or is not visible in any scanned KPI) loses one key, the option with the
    # largest d at the cap. Judged at the cap, before any scaling, so a later
    # widening cannot leave another event's earlier scaling stale (DECISIONS 56).
    for i in sorted({i for i, _ in slots}):
        own = [k for k in slots if k[0] == i]
        if any(k in fixed for k in own):
            continue  # a stated size in a wider segment would be another story
        at_cap = _at_cap(spec, i)
        m_cap = _measure_all(at_cap, seed, twin)
        here = min((m_cap[k].d or 0.0) for k in own)
        if all(first[k].d is not None for k in own) and here >= WIDEN_BELOW * goal:
            continue  # reachable, or a near miss: a near miss stays below_target, not a new story
        best = None
        for opt in _widen_options(spec.events[i].target):
            trial = at_cap.model_copy(deep=True)
            trial.events[i].target = opt
            mt = _measure_all(trial, seed, twin)
            d = min((mt[k].d or 0.0) for k in own)
            if best is None or d > best[0]:
                best = (d, opt)
        if best is not None and best[0] > here:
            spec.events[i].target = best[1]
            widened.add(i)

    # 2. Scale, both ways. Below the goal a size grows; above goal * BAND it steps
    # back down, but never below the story's own size and never past the cap.
    m = _measure_all(spec, seed, twin)
    for _ in range(ITERATIONS):
        off = [k for k in slots if k not in fixed and m[k].d is not None and (
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
        m = _measure_all(spec, seed, twin)

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
                + ("the size is stated by the story and stays as it is; " if k in fixed else "")
                + "it may not be detectable")
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
            "target_d": goal, "status": status, "stated": k in fixed,
        })
    return spec, pd.DataFrame(rows, columns=cols)


def format_table(table: pd.DataFrame) -> str:
    lines = ["calibration (d = effect in noise units; target from difficulty):"]
    for r in table.itertuples():
        seg = r.segment if r.segment == r.original_segment else f"{r.original_segment} -> {r.segment}"
        lines.append(f"  {r.event_id:<4} {r.metric:<16} {seg:<36} size {r.story_size:+.3g} -> {r.simulated_size:+.3g}"
                     f"  d {r.d_original} -> {r.d} (target {r.target_d:.1f}, via {r.kpi})  {r.status}"
                     + ("  (stated size)" if getattr(r, "stated", False) else ""))
    return "\n".join(lines)
