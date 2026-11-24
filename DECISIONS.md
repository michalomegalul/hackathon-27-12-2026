# Decisions

Places where the report's DSL (`reports/Story2Data hackathon winning plan.md`) was
ambiguous or silent, and what the code does about it. Change the code and this
file together.

## Spec / DSL

1. **`channels` short form.** The report writes `channels: [{eshop: 0.55}, {store: 0.45}]`.
   We accept that, but the canonical form (and the JSON Schema) is
   `[{channel: eshop, weight: 0.55}]`. A single-key dict is hard to express in a flat schema.
2. **The schema is inlined.** `export-schema` replaces every `$ref` with its definition,
   so there are no `$ref`, `$defs` or `oneOf`. Optional fields still use `anyOf: [X, null]`.
3. **Unknown keys are errors** (`extra="forbid"`), so typos fail loudly.
4. **City weights must sum to 1**, like segment shares (±0.01).
5. **New event type `churn_shock`.** It was not in the report's list, but the task asked for
   it. It needs `params.churn_pct` and `params.churn_window_days`, and its effects must
   use `metric: churn_hazard`. Its effect `size`, `ramp_days` and `duration_days` are
   ignored. Only `lag_days` is used.
6. **The recoverability gate (d ≥ 0.5 noise units) is not implemented yet.** It is marked as a TODO in `spec.py`.

## Effects and curves

7. **Curve timing.** The curve is 0 before `start + lag_days`, then ramps linearly over
   `ramp_days` (the first ramp day is already `1/ramp_days`), then holds a plateau for
   `duration_days`, which comes **after** the ramp. After that it decays with
   `decay_halflife_days`, or drops straight to 0 if that is null. `duration_days: null`
   means it never ends. Decay tails below 0.01 are cut to 0.
8. **Relative sizes.** For `purchase_rate`, `churn_hazard` and `acquisition_rate`, the
   multiplier is `1 + size · curve(t)`. Overlapping events multiply.
9. **`difficulty`** scales every relative `size` (×1.5 / ×1.0 / ×0.5). It does not scale
   `price_change_pct` or `churn_pct`, because those are stated facts or targets.
   `_answer_key.magnitude_pct` shows the size that was actually simulated.
10. **Churn targets.** A monthly churn rate `p` becomes a daily hazard with
    `h = 1-(1-p)^(1/30.4)`. A `churn_shock` with `churn_pct = p` over `W` days adds
    `h = 1-(1-p)^(1/W)` to the daily hazard for exactly `W` days. So `p` is the share
    that leaves *because of the shock*, on top of normal churn. The report checks it with
    `1 - (1-story)/(1-twin)`.
11. **Target matching.** `city`, `segment` and `channel` pick out customers.
    `category` picks out products. If an effect has both, it applies only to that
    customer group's purchases in those categories. `supplier` is not used yet, because
    the only events that need it are stubs. For `acquisition_rate`, `category` is ignored.
12. **`price_change` and price sensitivity.** A `price_change` event with
    `price_change_pct` writes new `product_prices` rows (`valid_from = start`) for the
    target categories, or for all categories if none are given. City, segment and
    channel filters do not create city-specific prices. The `purchase_rate` effect of a
    `price_change` is scaled per customer by `price_sensitivity / share-weighted mean`,
    so the population average is still `size` but students react more. A
    `price_change` without a pct (like E2 in example A) only carries effects.
13. **Which events run today.**
    - With extra mechanics: `price_change`.
    - Effects-only (they just apply their curves): `churn_shock`, `competitor_entry`,
      `campaign`, `quality_issue`.
    - Stubs that raise `NotImplementedError`: `supplier_delay`, `stockout`,
      `courier_change`, `service_outage`, `staff_shortage`, `viral_spike`.

    Only the metrics `purchase_rate`, `churn_hazard` and `acquisition_rate` are
    simulated. Any other metric also raises. By default the runner skips the whole
    event, prints a warning and writes `simulated = false` in `_answer_key`. Use
    `--strict` to fail instead. In example A, E3 is skipped. In example B, only E3 runs.
14. **The answer key has one row per effect, not one per event.** An event with two
    effects (example B, E1) gets two rows, because `metric` is a scored slot.
    `segment` is the whole target written as text, e.g. `city=Brno;segment=predplatitel`.
15. **Decoys** are simulated as short purchase spikes. `size` is the peak multiplier
    (2.5 = 2.5× demand on that day). The spike lasts 1 day, then decays with a 2-day
    half-life. They are listed in `_truth.decoys`, not in the answer key.
    `data_outage` is a dirt-layer job, so it is skipped for now.

## Simulation model

16. **Customers are created up front.** `n` is the active base on day 0. Their signup
    dates are spread over the 2 years before the sim. Each day, new customers arrive by
    Poisson per (segment, city, channel) cell, at
    `n · cell_share · (growth_per_year + annual_churn) / 365 · day_factor`, so that the
    base grows at roughly `growth_per_year`.
17. **Every customer has one home channel**, and all of their orders use it. This keeps
    channel-targeted events (example A, E5: store orders in Brno) clean. The `store`
    channel is only possible in cities with `has_store: true`.
18. **Categories.** An order's main category is drawn in proportion to
    `rate[i, c] = λ[i] · category_weight[c] · event multipliers`, where `category_weight`
    is proportional to `√n_skus`. The first basket item comes from that category, and
    extra items come from overall popularity. Basket size is geometric (p=0.6, mean ≈1.7),
    and quantity is geometric (p=0.8).
19. **Seasonality.** The weekly factors are normalised to mean 1. The yearly profile is a
    cosine (`winter_peak` peaks at New Year, `summer_peak` in July, `retail_cz` in
    December, amplitude 8-15%). Black Friday is ×1.8, the following weekend through
    Cyber Monday ×1.4, and the week before ×1.15. December is ×1.25 until the 20th, then
    drops over 24-26. On CZ public holidays (`holidays.CZ`), online demand is ×0.8. Store
    demand is ×0 if `cz_holidays_closed`, else ×0.5.
20. **Payments.** Each order gets one attempt, which fails with `payment_failure_rate`.
    A failed attempt is retried once with 60% success. If the retry also fails, the order
    is `cancelled`.
21. **Names.** Faker `cs_CZ` fills pools of up to 400 first and last names per gender.
    Customers sample from the pools with numpy, gender first. This is faster than calling
    Faker per row and keeps female surnames female. They end in "-ová", or "-á" for
    adjectival names such as Černá, which is correct Czech.
22. **RNG streams.** The streams are spawned from one `SeedSequence` in the fixed order of
    `STREAM_NAMES`, and new streams are only ever appended. Churn draws one uniform per
    customer per day, alive or not, so a story run and its no-story twin use the same
    churn randomness. That gives a paired comparison.
23. **Churn is a `_truth` fact.** `customers` has no churn column. Analysts must infer
    churn from inactivity. The real churn dates are in `_truth.customer_state`.
24. **Parquet files have no pandas metadata**, so file hashes depend only on the data.
    Columns named `*_date`, `valid_from` and `valid_to` are stored as `DATE`.
25. **No PK/FK DDL in DuckDB yet.** Tests check key integrity instead. Constraints come
    with the exporter (stage 5).
