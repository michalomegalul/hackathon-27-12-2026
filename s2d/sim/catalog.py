"""Products, their popularity, and their prices over time."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from s2d.spec import StorySpec

from .calendar import Calendar
from .events import PriceChange


@dataclass
class Catalog:
    products: pd.DataFrame        # analyst table
    category_of: np.ndarray       # category index per product
    category_ids: list[str]
    category_weight: np.ndarray   # share of orders whose main item is from each category
    within_cdf: list[np.ndarray]  # per category: cumulative popularity of its products
    within_index: list[np.ndarray]  # per category: product indices, same order as within_cdf
    global_cdf: np.ndarray        # cumulative popularity over all products
    price: np.ndarray             # [day, product] shelf price in CZK


def czech_round(x: np.ndarray) -> np.ndarray:
    """Shop-style prices: 347.2 -> 349, 4912 -> 4909."""
    return np.maximum(np.round(np.asarray(x) / 10) * 10 - 1, 9)


def build_catalog(spec: StorySpec, cal: Calendar, price_changes: list[PriceChange],
                  rng: np.random.Generator) -> Catalog:
    cats = spec.entities.products.categories
    rows, category_of, base_price, popularity = [], [], [], []
    for c_idx, cat in enumerate(cats):
        # Lognormal prices: the range [price_min, price_max] covers about ±2 sigma.
        lo, hi = np.log(cat.price_min), np.log(cat.price_max)
        prices = np.exp(rng.normal((lo + hi) / 2, max((hi - lo) / 4, 1e-6), cat.n_skus))
        prices = czech_round(np.clip(prices, cat.price_min, cat.price_max))

        # Zipf popularity: the r-th most popular product gets weight 1 / r^s.
        # Ranks are shuffled so product #1 is not always the best seller.
        ranks = rng.permutation(cat.n_skus) + 1
        weights = 1.0 / ranks ** cat.zipf_s

        for j in range(cat.n_skus):
            rows.append({
                "product_id": len(rows) + 1,
                "sku": f"{cat.id[:3].upper()}-{j + 1:03d}",
                "name": f"{cat.id.replace('_', ' ').capitalize()} {j + 1:02d}",
                "category": cat.id,
                "supplier_id": cat.supplier,
                "base_price": float(prices[j]),
            })
        category_of += [c_idx] * cat.n_skus
        base_price += list(prices)
        popularity += list(weights / weights.sum())

    category_of = np.array(category_of)
    popularity = np.array(popularity)
    # Bigger categories sell more, but less than proportionally (see DECISIONS.md).
    category_weight = np.sqrt([c.n_skus for c in cats])
    category_weight = category_weight / category_weight.sum()

    within_index = [np.flatnonzero(category_of == c) for c in range(len(cats))]
    within_cdf = [np.cumsum(popularity[idx]) for idx in within_index]
    global_weight = popularity * category_weight[category_of]
    global_cdf = np.cumsum(global_weight / global_weight.sum())

    # Price per day and product: start from base price, apply each price change
    # from its start day onwards.
    factor = np.ones((cal.n_days, len(rows)))
    cat_ids = [c.id for c in cats]
    for change in price_changes:
        hit = np.ones(len(rows), dtype=bool)
        if change.categories:
            hit = np.isin(category_of, [cat_ids.index(c) for c in change.categories])
        factor[max(change.start_idx, 0):, hit] *= 1 + change.pct / 100
    price = czech_round(np.array(base_price)[None, :] * factor)

    return Catalog(pd.DataFrame(rows), category_of, cat_ids, category_weight,
                   within_cdf, within_index, global_cdf, price)


def product_prices_table(cat: Catalog, cal: Calendar) -> pd.DataFrame:
    """SCD-2 style price history: one row per (product, price period)."""
    rows = []
    n_days, n_products = cat.price.shape
    for p in range(n_products):
        series = cat.price[:, p]
        change_days = [0] + list(np.flatnonzero(np.diff(series) != 0) + 1)
        for k, day in enumerate(change_days):
            end_day = change_days[k + 1] - 1 if k + 1 < len(change_days) else None
            rows.append({
                "price_id": len(rows) + 1,
                "product_id": p + 1,
                "price": float(series[day]),
                "valid_from": cal.dates[day],
                "valid_to": cal.dates[end_day] if end_day is not None else None,
            })
    df = pd.DataFrame(rows)
    df["valid_to"] = pd.to_datetime(df["valid_to"])
    return df
