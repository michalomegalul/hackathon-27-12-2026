"""The story DSL as Pydantic models.

Every field is an enum, a bounded number, or free text the simulator ignores.
The JSON Schema exported from these models is later passed to Ollama as `format`.

    python -m s2d.spec export-schema            # writes schema/story.schema.json
    python -m s2d.spec validate examples/a.yaml # checks a spec file
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    """Base model: unknown keys are an error, so typos in YAML are caught."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- enums


class Currency(str, Enum):
    CZK = "CZK"
    EUR = "EUR"


class Difficulty(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class LegalForm(str, Enum):
    sro = "s.r.o."
    as_ = "a.s."
    other = "other"


class Industry(str, Enum):
    retail = "retail"
    eshop = "eshop"
    cafe_chain = "cafe_chain"
    subscription = "subscription"
    services = "services"


class Channel(str, Enum):
    eshop = "eshop"
    store = "store"
    app = "app"
    phone = "phone"


class SeasonProfile(str, Enum):
    retail_cz = "retail_cz"
    flat = "flat"
    summer_peak = "summer_peak"
    winter_peak = "winter_peak"


class EventType(str, Enum):
    price_change = "price_change"
    churn_shock = "churn_shock"  # not in the report's list; see DECISIONS.md
    competitor_entry = "competitor_entry"
    campaign = "campaign"
    supplier_delay = "supplier_delay"
    stockout = "stockout"
    courier_change = "courier_change"
    service_outage = "service_outage"
    quality_issue = "quality_issue"
    staff_shortage = "staff_shortage"
    viral_spike = "viral_spike"


class Metric(str, Enum):
    purchase_rate = "purchase_rate"
    churn_hazard = "churn_hazard"
    acquisition_rate = "acquisition_rate"
    basket_size = "basket_size"
    ticket_rate = "ticket_rate"
    rating_mean = "rating_mean"
    return_rate = "return_rate"
    payment_failure_rate = "payment_failure_rate"
    delivery_days = "delivery_days"


class DecoyType(str, Enum):
    viral_spike = "viral_spike"
    seasonal_peak = "seasonal_peak"
    data_outage = "data_outage"


class Messiness(str, Enum):
    none = "none"
    light = "light"
    medium = "medium"
    heavy = "heavy"


# ---------------------------------------------------------------- meta + company


class Meta(Strict):
    seed: int
    start: date
    days: Annotated[int, Field(ge=90, le=1095)]
    currency: Currency = Currency.CZK
    locale: str = "cs_CZ"
    difficulty: Difficulty = Difficulty.medium

    @property
    def end(self) -> date:
        """Last simulated day (inclusive)."""
        return self.start + timedelta(days=self.days - 1)


class ChannelWeight(Strict):
    channel: Channel
    weight: Annotated[float, Field(gt=0, le=1)]


class City(Strict):
    name: str
    weight: Annotated[float, Field(gt=0, le=1)]
    has_store: bool = False


class Company(Strict):
    name: str
    legal_form: LegalForm = LegalForm.sro
    industry: Industry
    channels: list[ChannelWeight] = Field(min_length=1)
    cities: list[City] = Field(min_length=1)
    description: str = ""

    @field_validator("channels", mode="before")
    @classmethod
    def _short_channel_form(cls, value):
        # The report writes channels as [{eshop: 0.55}, {store: 0.45}].
        # Accept that and turn it into [{channel: eshop, weight: 0.55}, ...].
        out = []
        for item in value:
            if isinstance(item, dict) and len(item) == 1 and "channel" not in item:
                (name, weight), = item.items()
                out.append({"channel": name, "weight": weight})
            else:
                out.append(item)
        return out


# ---------------------------------------------------------------- entities


class Segment(Strict):
    id: str
    share: Annotated[float, Field(gt=0, le=1)]
    base_orders_per_month: Annotated[float, Field(gt=0, le=60)]
    price_sensitivity: Annotated[float, Field(ge=0, le=3)] = 1.0
    base_churn_per_month: Annotated[float, Field(ge=0, lt=1)]
    # Customers of this segment hold a subscription (orders on schedule). None = guess from
    # the id (predplatitel, subscriber, ...), so LLM-written specs get it without the field.
    subscription: bool | None = None

    @property
    def has_subscription(self) -> bool:
        if self.subscription is not None:
            return self.subscription
        low = self.id.lower()
        return any(k in low for k in ("predplat", "předplat", "subscri", "abonent"))


class Customers(Strict):
    n: Annotated[int, Field(ge=500, le=200_000)]
    growth_per_year: Annotated[float, Field(ge=-0.5, le=3)] = 0.0
    segments: list[Segment] = Field(min_length=1)


class Category(Strict):
    id: str
    n_skus: Annotated[int, Field(ge=1, le=2000)]
    price_min: Annotated[float, Field(gt=0)]
    price_max: Annotated[float, Field(gt=0)]
    supplier: str
    zipf_s: Annotated[float, Field(ge=0.8, le=1.4)] = 1.1


class Products(Strict):
    categories: list[Category] = Field(min_length=1)


class Supplier(Strict):
    id: str
    name: str
    lead_time_days: Annotated[int, Field(ge=0, le=365)]
    reliability: Annotated[float, Field(ge=0, le=1)] = 0.97


class Stores(Strict):
    per_city_with_store: Annotated[int, Field(ge=0, le=50)] = 1


class Employees(Strict):
    support_agents: Annotated[int, Field(ge=0, le=1000)] = 2
    tickets_per_agent_day: Annotated[float, Field(gt=0, le=500)] = 25


class Entities(Strict):
    customers: Customers
    products: Products
    suppliers: list[Supplier] = Field(min_length=1)
    stores: Stores = Stores()
    employees: Employees = Employees()


# ---------------------------------------------------------------- baseline


class Seasonality(Strict):
    weekly: list[Annotated[float, Field(ge=0, le=5)]] = Field(
        default=[1, 1, 1, 1, 1, 1, 1], min_length=7, max_length=7
    )  # Monday first
    profile: SeasonProfile = SeasonProfile.flat
    black_friday: bool = False
    christmas: bool = False
    cz_holidays_closed: bool = False


class Baseline(Strict):
    seasonality: Seasonality = Seasonality()
    payment_failure_rate: Annotated[float, Field(ge=0, le=0.5)] = 0.02
    return_rate: Annotated[float, Field(ge=0, le=0.5)] = 0.02
    review_rate: Annotated[float, Field(ge=0, le=1)] = 0.1
    ticket_rate_per_order: Annotated[float, Field(ge=0, le=1)] = 0.02


# ---------------------------------------------------------------- events


class Target(Strict):
    """Who/what an event hits. An empty list or missing key means 'everyone'."""

    city: list[str] | None = None
    segment: list[str] | None = None
    category: list[str] | None = None
    channel: list[Channel] | None = None
    supplier: list[str] | None = None

    def describe(self) -> str:
        """Stable text form, e.g. 'city=Brno;segment=predplatitel'. '' = everyone."""
        parts = []
        for key in ("city", "segment", "category", "channel", "supplier"):
            values = getattr(self, key)
            if values:
                values = [v.value if isinstance(v, Enum) else v for v in values]
                parts.append(f"{key}={','.join(values)}")
        return ";".join(parts)


class Params(Strict):
    price_change_pct: Annotated[float, Field(ge=-90, le=300)] | None = None
    lead_time_multiplier: Annotated[float, Field(gt=0, le=20)] | None = None
    delivery_delay_days: Annotated[float, Field(ge=0, le=60)] | None = None
    budget_czk: Annotated[float, Field(ge=0)] | None = None
    # churn_shock only: "churn_pct % of the target leaves within churn_window_days"
    churn_pct: Annotated[float, Field(gt=0, lt=100)] | None = None
    churn_window_days: Annotated[int, Field(ge=1, le=365)] | None = None


class Effect(Strict):
    metric: Metric
    size: Annotated[float, Field(ge=-1, le=10)]  # relative: +0.15 = +15 %
    # True when the story text gives this number ("tržby klesly o 5 %"): a stated fact that
    # neither difficulty nor calibration may change (DECISIONS 90).
    size_stated: bool = False
    lag_days: Annotated[int, Field(ge=0, le=120)] = 0
    ramp_days: Annotated[int, Field(ge=0, le=60)] = 0
    duration_days: Annotated[int, Field(ge=0, le=1095)] | None = None  # None = permanent
    decay_halflife_days: Annotated[int, Field(ge=1, le=365)] | None = None


class Event(Strict):
    id: str
    type: EventType
    start: date
    target: Target = Target()
    params: Params = Params()
    effects: list[Effect] = Field(min_length=1)
    caused_by: str | None = None
    narrative_cs: str = ""  # long text last; ignored by the simulator


class Decoy(Strict):
    type: DecoyType
    date: date
    target: Target = Target()
    size: Annotated[float, Field(ge=-1, le=10)]


class Noise(Strict):
    messiness: Messiness = Messiness.none


# ---------------------------------------------------------------- the whole spec


class StorySpec(Strict):
    version: int = 1
    meta: Meta
    company: Company
    entities: Entities
    baseline: Baseline = Baseline()
    events: list[Event] = []
    decoys: list[Decoy] = []
    noise: Noise = Noise()

    @model_validator(mode="after")
    def _semantic_checks(self) -> StorySpec:
        """Checks that JSON Schema cannot express. Errors are plain sentences so
        they can be sent back to the LLM verbatim."""
        errors: list[str] = []
        start, end = self.meta.start, self.meta.end

        shares = sum(s.share for s in self.entities.customers.segments)
        if abs(shares - 1) > 0.01:
            errors.append(f"segment shares sum to {shares:.3f}, must be 1 (±0.01)")
        city_w = sum(c.weight for c in self.company.cities)
        if abs(city_w - 1) > 0.01:
            errors.append(f"city weights sum to {city_w:.3f}, must be 1 (±0.01)")
        if len({c.channel for c in self.company.channels}) != len(self.company.channels):
            errors.append("a channel is listed twice")
        has_store = any(c.has_store for c in self.company.cities)
        if any(c.channel == Channel.store for c in self.company.channels) and not has_store:
            errors.append("channel 'store' is used but no city has_store")

        segment_ids = {s.id for s in self.entities.customers.segments}
        city_names = {c.name for c in self.company.cities}
        category_ids = {c.id for c in self.entities.products.categories}
        supplier_ids = {s.id for s in self.entities.suppliers}
        channels = {c.channel for c in self.company.channels}

        for cat in self.entities.products.categories:
            if cat.price_min > cat.price_max:
                errors.append(f"category {cat.id}: price_min > price_max")
            if cat.supplier not in supplier_ids:
                errors.append(f"category {cat.id}: unknown supplier {cat.supplier!r}")

        def check_target(where: str, t: Target) -> None:
            for key, known in (
                ("city", city_names),
                ("segment", segment_ids),
                ("category", category_ids),
                ("supplier", supplier_ids),
                ("channel", channels),
            ):
                for value in getattr(t, key) or []:
                    if value not in known:
                        shown = value.value if isinstance(value, Enum) else value
                        errors.append(f"{where}: unknown {key} {shown!r}")

        seen: list[str] = []
        for ev in self.events:
            where = f"event {ev.id}"
            if ev.id in seen:
                errors.append(f"{where}: duplicate id")
            if not start <= ev.start <= end:
                errors.append(f"{where}: start {ev.start} is outside {start}..{end}")
            if ev.caused_by is not None and ev.caused_by not in seen:
                errors.append(f"{where}: caused_by {ev.caused_by!r} is not an earlier event")
            check_target(where, ev.target)
            # Params the simulator needs to run these types (s2d/sim/events.mechanism); a
            # missing one is the model's mistake to fix, not an unsupported event.
            if ev.type == EventType.supplier_delay and not ev.params.lead_time_multiplier:
                errors.append(f"{where}: supplier_delay needs params.lead_time_multiplier "
                              "(how many times longer the supplier's lead time gets, e.g. 3)")
            if ev.type in (EventType.supplier_delay, EventType.stockout) and not (
                    ev.target.supplier or ev.target.category):
                errors.append(f"{where}: {ev.type.value} needs a target supplier or category")
            if ev.type == EventType.churn_shock:
                if ev.params.churn_pct is None or ev.params.churn_window_days is None:
                    errors.append(f"{where}: churn_shock needs params.churn_pct and churn_window_days")
                if any(e.metric != Metric.churn_hazard for e in ev.effects):
                    errors.append(f"{where}: churn_shock effects must use metric churn_hazard")
            seen.append(ev.id)

        for i, d in enumerate(self.decoys):
            if not start <= d.date <= end:
                errors.append(f"decoy {i}: date {d.date} is outside {start}..{end}")
            check_target(f"decoy {i}", d.target)

        # The recoverability gate (every effect findable) needs a simulation, so it is
        # not a validation rule: s2d/calibrate.py runs it before the sim (DECISIONS 6, 54).
        if errors:
            raise ValueError("; ".join(errors))
        return self


def load_spec(path: str | Path) -> StorySpec:
    with open(path, encoding="utf-8") as fh:
        return StorySpec.model_validate(yaml.safe_load(fh))


# ---------------------------------------------------------------- JSON Schema export


def _inline_refs(node, defs: dict):
    """Replace every {"$ref": "#/$defs/X"} with the definition itself.

    The report asks for a flat schema without $ref, because Ollama's grammar
    converter may not support it. Our models are not recursive, so this ends.
    """
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            merged = {**defs[name], **{k: v for k, v in node.items() if k != "$ref"}}
            return _inline_refs(merged, defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def story_json_schema() -> dict:
    raw = StorySpec.model_json_schema()
    return _inline_refs(raw, raw.get("$defs", {}))


def main(argv: list[str]) -> int:
    if argv[:1] == ["export-schema"]:
        out = Path(argv[1] if len(argv) > 1 else "schema/story.schema.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(story_json_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")
        return 0
    if argv[:1] == ["validate"] and len(argv) > 1:
        for path in argv[1:]:
            spec = load_spec(path)
            print(f"{path}: OK ({len(spec.events)} events, {len(spec.decoys)} decoys)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
