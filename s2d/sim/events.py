"""Turn the spec's events into things the day loop can use.

Each effect becomes a `CompiledEffect`: a curve over all simulated days (how
strong the effect is on day t, between 0 and 1) plus who it applies to.

Event *types* can also have side effects outside the multipliers. For example,
`price_change` writes new rows into product_prices. Types we have not built yet
raise NotImplementedError. The runner catches that, skips the event, and marks
it `simulated = False` in the answer key (or stops, with --strict).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from s2d.spec import Decoy, DecoyType, Difficulty, Effect, Event, EventType, Metric, StorySpec, Target

from .calendar import Calendar

# The spec's `difficulty` scales every relative effect size.
DIFFICULTY_SCALE = {Difficulty.easy: 1.5, Difficulty.medium: 1.0, Difficulty.hard: 0.5}

# Metrics the day loop knows how to apply today.
IMPLEMENTED_METRICS = {Metric.purchase_rate, Metric.churn_hazard, Metric.acquisition_rate}

# Curves below this value are treated as "over" (keeps decay tails short).
CURVE_EPSILON = 0.01


def daily_hazard(p: float, window_days: float) -> float:
    """Daily probability h such that P(leave within window_days) = p.

    Surviving W days at daily hazard h has probability (1-h)^W, so
    1 - (1-h)^W = p  =>  h = 1 - (1-p)^(1/W).
    """
    return 1 - (1 - p) ** (1 / window_days)


def compile_curve(start_idx: int, effect: Effect, n_days: int) -> np.ndarray:
    """Effect strength per day, between 0 and 1.

        0 ........ before start + lag
        ramp ..... rises linearly to 1 over ramp_days
        plateau .. stays at 1 for duration_days (None = forever)
        decay .... halves every decay_halflife_days (None = drops to 0 at once)
    """
    t = np.arange(n_days)
    k = t - (start_idx + effect.lag_days)  # days since the effect began
    curve = np.zeros(n_days)

    if effect.ramp_days > 0:
        curve[k >= 0] = np.minimum((k[k >= 0] + 1) / effect.ramp_days, 1.0)
    else:
        curve[k >= 0] = 1.0

    if effect.duration_days is not None:
        plateau_end = effect.ramp_days + effect.duration_days  # in "k" units
        after = k >= plateau_end
        if effect.decay_halflife_days:
            curve[after] = 0.5 ** ((k[after] - plateau_end) / effect.decay_halflife_days)
            curve[curve < CURVE_EPSILON] = 0.0
        else:
            curve[after] = 0.0
    return curve


@dataclass
class CompiledEffect:
    event_id: str
    event_type: str
    metric: Metric
    size: float                # relative size after difficulty scaling, or daily hazard if additive
    curve: np.ndarray          # 0..1 per day
    target: Target
    additive: bool = False     # True: churn_shock, adds `size` to the daily hazard
    price_sensitive: bool = False  # True: scale per customer by segment price_sensitivity
    is_decoy: bool = False


@dataclass
class PriceChange:
    start_idx: int
    categories: list[str] | None  # None = every category
    pct: float


@dataclass
class CompiledStory:
    effects: list[CompiledEffect] = field(default_factory=list)
    price_changes: list[PriceChange] = field(default_factory=list)
    answer_key: pd.DataFrame | None = None
    decoys: pd.DataFrame | None = None
    skipped: list[str] = field(default_factory=list)  # human-readable reasons

    def for_metric(self, metric: Metric) -> list[CompiledEffect]:
        return [e for e in self.effects if e.metric == metric]


# ---------------------------------------------------------------- event type handlers
#
# A handler gets the event and returns any side effects (price changes).
# Handlers that only need the generic effect curves just return nothing.


def _effects_only(event: Event, start_idx: int) -> list[PriceChange]:
    return []


def _price_change(event: Event, start_idx: int) -> list[PriceChange]:
    # An event without price_change_pct is a follow-up (like E2 in example A):
    # it only carries effects, the price itself changed in another event.
    if event.params.price_change_pct is None:
        return []
    return [PriceChange(start_idx, event.target.category, event.params.price_change_pct)]


def _not_implemented(event: Event, start_idx: int) -> list[PriceChange]:
    raise NotImplementedError(f"event type '{event.type.value}' is not simulated yet")


TYPE_HANDLERS = {
    EventType.price_change: _price_change,
    EventType.churn_shock: _effects_only,
    EventType.competitor_entry: _effects_only,
    EventType.campaign: _effects_only,
    EventType.quality_issue: _effects_only,
    EventType.supplier_delay: _not_implemented,
    EventType.stockout: _not_implemented,
    EventType.courier_change: _not_implemented,
    EventType.service_outage: _not_implemented,
    EventType.staff_shortage: _not_implemented,
    EventType.viral_spike: _not_implemented,
}


def _compile_event(event: Event, spec: StorySpec, cal: Calendar) -> tuple[list[CompiledEffect], list[PriceChange]]:
    """Compile one event. Raises NotImplementedError for anything unsupported."""
    start_idx = cal.index_of(event.start)
    side_effects = TYPE_HANDLERS[event.type](event, start_idx)

    scale = DIFFICULTY_SCALE[spec.meta.difficulty]
    compiled = []
    for eff in event.effects:
        if eff.metric not in IMPLEMENTED_METRICS:
            raise NotImplementedError(f"metric '{eff.metric.value}' is not simulated yet")

        if event.type == EventType.churn_shock:
            # "churn_pct % of the target leaves within churn_window_days":
            # an extra daily hazard for exactly that window. Not difficulty-scaled,
            # because it is a stated target.
            window = event.params.churn_window_days
            h = daily_hazard(event.params.churn_pct / 100, window)
            flat = Effect(metric=eff.metric, size=0, lag_days=eff.lag_days, ramp_days=0, duration_days=window)
            compiled.append(
                CompiledEffect(event.id, event.type.value, eff.metric, h,
                               compile_curve(start_idx, flat, cal.n_days), event.target, additive=True)
            )
            continue

        compiled.append(
            CompiledEffect(
                event.id, event.type.value, eff.metric, eff.size * scale,
                compile_curve(start_idx, eff, cal.n_days), event.target,
                price_sensitive=(event.type == EventType.price_change and eff.metric == Metric.purchase_rate),
            )
        )
    return compiled, side_effects


def _compile_decoy(decoy: Decoy, cal: Calendar) -> CompiledEffect:
    """Decoys are short purchase spikes that are NOT part of the story.
    `size` is the peak multiplier (2.5 = 2.5x normal demand)."""
    if decoy.type == DecoyType.data_outage:
        raise NotImplementedError("decoy 'data_outage' belongs to the dirt layer, not simulated yet")
    spike = Effect(metric=Metric.purchase_rate, size=0, duration_days=1, decay_halflife_days=2)
    return CompiledEffect(
        f"decoy_{decoy.type.value}_{decoy.date}", decoy.type.value, Metric.purchase_rate,
        decoy.size - 1, compile_curve(cal.index_of(decoy.date), spike, cal.n_days),
        decoy.target, is_decoy=True,
    )


def compile_story(spec: StorySpec, cal: Calendar, strict: bool = False) -> CompiledStory:
    story = CompiledStory()
    scale = DIFFICULTY_SCALE[spec.meta.difficulty]
    rows = []
    for event in spec.events:
        try:
            effects, side_effects = _compile_event(event, spec, cal)
            story.effects += effects
            story.price_changes += side_effects
            simulated = True
        except NotImplementedError as err:
            if strict:
                raise
            story.skipped.append(f"{event.id} ({event.type.value}): {err}")
            simulated = False

        for eff in event.effects:
            if event.type == EventType.churn_shock:
                magnitude = event.params.churn_pct
            else:
                magnitude = eff.size * scale * 100
            rows.append({
                "event_id": event.id,
                "type": event.type.value,
                "metric": eff.metric.value,
                "segment": event.target.describe(),
                "start_date": event.start,
                "lag_days": eff.lag_days,
                "direction": "up" if magnitude > 0 else "down",
                "magnitude_pct": round(magnitude, 4),
                "caused_by": event.caused_by,
                "simulated": simulated,
                "narrative_cs": event.narrative_cs,
            })
    story.answer_key = pd.DataFrame(rows, columns=[
        "event_id", "type", "metric", "segment", "start_date", "lag_days",
        "direction", "magnitude_pct", "caused_by", "simulated", "narrative_cs",
    ])

    decoy_rows = []
    for decoy in spec.decoys:
        try:
            story.effects.append(_compile_decoy(decoy, cal))
            simulated = True
        except NotImplementedError as err:
            if strict:
                raise
            story.skipped.append(f"decoy {decoy.type.value} {decoy.date}: {err}")
            simulated = False
        decoy_rows.append({"type": decoy.type.value, "date": decoy.date,
                           "segment": decoy.target.describe(), "size": decoy.size, "simulated": simulated})
    story.decoys = pd.DataFrame(decoy_rows, columns=["type", "date", "segment", "size", "simulated"])
    return story
