"""The simulator: spec -> clean tables + answer key.

    from s2d.sim import simulate
    world = simulate(spec, seed=42)
    world.tables["orders"]          # analyst tables
    world.truth["answer_key"]       # hidden truth
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import yaml

from s2d.spec import StorySpec

from .calendar import Calendar, build_calendar
from .catalog import Catalog, build_catalog, product_prices_table
from .engine import SimResult, run_day_loop
from .events import CompiledStory, compile_story
from .population import Population, build_population
from .rng import make_streams


@dataclass
class World:
    spec: StorySpec
    seed: int
    calendar: Calendar
    story: CompiledStory
    population: Population
    catalog: Catalog
    result: SimResult
    tables: dict[str, pd.DataFrame]  # analyst-visible (DuckDB schema main)
    truth: dict[str, pd.DataFrame]   # hidden (DuckDB schema _truth)


def without_story(spec: StorySpec) -> StorySpec:
    """The 'no-story twin': same company and seed, all events removed (decoys stay)."""
    return spec.model_copy(update={"events": []})


def simulate(spec: StorySpec, seed: int | None = None, strict: bool = False) -> World:
    seed = spec.meta.seed if seed is None else seed
    streams = make_streams(seed)

    cal = build_calendar(spec)
    story = compile_story(spec, cal, strict=strict)
    catalog = build_catalog(spec, cal, story.price_changes, streams["catalog"])
    pop = build_population(spec, cal, story, streams)
    result = run_day_loop(spec, cal, story, pop, catalog, streams)

    tables = {
        "customers": pop.table,
        "products": catalog.products,
        "product_prices": product_prices_table(catalog, cal),
        "orders": result.orders,
        "order_items": result.order_items,
        "payments": result.payments,
        **result.service,
    }

    start = np.datetime64(cal.dates[0], "D")
    churned = result.churn_day >= 0
    churn_date = np.where(churned, start + result.churn_day.astype("timedelta64[D]"), np.datetime64("NaT", "D"))
    truth = {
        "answer_key": story.answer_key,
        "decoys": story.decoys,
        "customer_state": pd.DataFrame({
            "customer_id": pop.table["customer_id"],
            "churn_date": churn_date,
            "churn_cause": result.churn_cause,
            "base_orders_per_day": pop.base_rate,
        }),
        "spec_yaml": pd.DataFrame({
            "seed": [seed],
            "spec_yaml": [yaml.safe_dump(spec.model_dump(mode="json"), allow_unicode=True, sort_keys=False)],
        }),
    }
    return World(spec, seed, cal, story, pop, catalog, result, tables, truth)
