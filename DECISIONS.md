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
6. **The recoverability gate runs before the sim, in `s2d/calibrate.py`**, not as a spec
   validation rule (it needs a simulation). See decision 54 for what a noise unit is and
   why the targets are far above the report's d ≥ 0.5.

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
    - With extra mechanics: `price_change`, `courier_change` (decisions 67–69),
      `supplier_delay` and `stockout` (decision 73).
    - Effects-only (they just apply their curves): `churn_shock`, `competitor_entry`,
      `campaign`, `quality_issue`.
    - Stubs that raise `NotImplementedError` (out of scope): `service_outage`,
      `staff_shortage`, `viral_spike`.

    The metrics `purchase_rate`, `churn_hazard` and `acquisition_rate` are simulated as
    curves; `delivery_days` drives a courier switch; `rating_mean`, `ticket_rate` (and churn
    or purchases of the event types above) are emergent (decision 69). Any other metric
    raises. By default the runner skips the whole event, prints a warning and writes
    `simulated = false` in `_answer_key`. Use `--strict` to fail instead. In examples A and
    B every event runs now.
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
25. **No PK/FK DDL in DuckDB.** Tests check key integrity instead. The Postgres export
    adds the constraints (decision 76).

## Detective

Everything below is global: the same code and the same numbers run on every
dataset, on every no-story twin and on every seed. Thresholds were set by looking
at no-story twins (null data) only, never at an answer key. The constants are at
the top of `s2d/detective/scan.py`.

### Blindness

26. **The detective holds an in-memory DuckDB with copies of the `main` tables only.**
    `data.open_analyst` attaches the run read-only, copies schema `main`, and detaches.
    `tests/test_detective.py` fails if any file in `s2d/detective/` names the hidden
    schema, the answer key or the spec. `s2d/score.py` is the only reader of `_truth`.

### KPIs

27. **Orders and revenue → `purchase_rate`; first orders → `acquisition_rate`; churn
    onsets → `churn_hazard`.** Series run overall, per value of city, channel and
    segment, per pair of those dimensions, and per category (alone and paired with each
    dimension). An order counts once for every category it contains.
28. **A segment series needs ≥ 30 events in total; shifts are only scanned on count
    series with ≥ 2 events a day.** Below that the relative change of a 28-day mean is
    dominated by Poisson noise. This rules out e.g. Brno × predplatitel churn
    (0.6/day), which is where Example A's E4 lives.
29. **Churn is inferred:** no order for max(60, 3 × median gap) days. **The onset is the
    last order plus the customer's mean gap, not the last order.** With memoryless
    ordering the expected time from the last order to the real churn day is one mean
    gap; using the last order would put every churn wave ~3 weeks early.
30. **Churn edges.** Only customers whose threshold is ≤ 90 days feed the churn KPI
    (73 % in Example A), and the series drops the first and the last 90 days. At the
    right edge these customers cannot be called churned yet; at the left edge their
    last order was before the data. A data-driven cut (90th percentile of thresholds)
    was tried first and cut 183 days, which hid every 2026 event.
31. **Acquisition drops the first 90 days** for the same warm-up reason (a new
    customer's first order comes about one gap after signup), and counts only
    customers whose `signup_date` is inside the data.

### Scan

32. **Noise scale from first differences:** `1.4826 · MAD(diff(x)) / √2` on
    x = STL trend + residual. The STL residual alone underestimates the noise in x
    (the trend absorbs the slow part), which made PELT fire on pure Poisson noise.
33. **Binseg confirms with half the PELT penalty.** Deviation from the brief. On a
    gradual rise the greedy Binseg puts its top break elsewhere (Example A student
    churn: PELT 2026-04-26, Binseg 2026-04-11) but does find the PELT break at lower
    rank. "Both algorithms agree on the location" is the test, ±3 days unchanged.
34. **Onset = start of a fitted ramp,** not the PELT location. Each break is refit as
    level → linear ramp (0-35 days) → level, all (t0, t1) solved in closed form; the
    reported start is t0. PELT puts a ramp's break in its middle.
    **The fit runs on the segment relative to its control** (share of segment + control
    for counts, difference for ratios; 0/0 days interpolated), not on the segment alone.
    Example A E5 (Brno stores −20 % over a 30-day ramp from 09-07): every store is closed
    on 28 Sept, PELT put the break on that zero day and the fit on the Brno series locked
    onto it (onset 09-25). Relative to the other cities' stores the closure cancels and
    the onset is 09-09. **Same-direction breaks closer than 35 days are one ramp**
    starting at the first: PELT cuts a long ramp into two steps, and the second one's fit
    could not reach back past the first. Synthetic check (`_store_world` in the tests,
    20 seeds): −35 % over 30 days → median onset error 0 d, 84 % within ±6 d; −20 % over
    30 days → median +5 d, 46 % within ±6 d (a weak long ramp cannot be dated better
    than that; a step at its midpoint fits almost as well). A CUSUM onset estimator was
    tried and was worse on ramps.
35. **An up break followed by a down break in the same series within 150 days is one
    temporary event** (end_date = the second break), not two events. **If that pair is not
    confirmed, its end break is evaluated again as an onset of its own.** Otherwise a noise
    break eats the real one: in Example A seed 42 an up break on 06-25 paired with the E5
    break on 09-28, the pair failed the DiD, and E5 was never tested.
36. **Seasonality cannot be removed from an everyone-level series** (< 2 years of data).
    So every reported shift needs a control group: Adtributor picks the segment for an
    overall break (EP ≥ 0.3 per value up to 0.8, dimension with the highest JS
    surprise); if the surprise is < 0.002 the change is uniform and is not reported
    (`uniform_change`). Price: a story event that hits literally everyone is invisible.
37. **Control group.** Single-key segment: everyone else. Pair segment
    (city=Brno;channel=store): the same second key in the other values of the first
    key (stores in other cities), so channel- or segment-specific seasonality (store
    holiday closures) cancels too.
38. **Confirmation = DiD CI excludes 0 AND placebo-in-time z ≥ 4.** Deviation: the
    7-day block bootstrap on 28 + 28 days is kept for the CI, but alone it was
    overconfident (twin: ~10 false events a year), because the series wander on a
    monthly scale that 7-day blocks do not see. The placebo test computes the same DiD
    statistic at every other date of the same series (> 56 days away) and asks how
    unusual this one is (robust z). It carries each series' own autocorrelation and
    sparsity. confidence = clip((z − 2)/4, 0, 1); reported events need ≥ 0.5.
39. **Magnitude is the DiD effect** (relative change vs the control), not the raw
    28-day before/after change. The raw change is kept as `raw_change_pct`.
40. **Merging.** Candidates with the same metric and direction within 14 days are one
    event. Start from the broadest segment; move to a narrower one only if it contains
    the broader one's values and its effect is ≥ 1.5× larger. A price-response
    candidate wins its group.
41. **Price changes in `product_prices` are visible data.** For each change date the
    orders of the repriced categories are tested against the other categories (DiD,
    one week to settle). They are also anchors for the lag search.
42. **Lag search** for churn and rating events: anchors are earlier reported events and
    price changes; lags {0, 7, 14, 28, 42}; keep the (anchor, lag) with the largest
    |t| in the event's direction, if |t| ≥ 3 and anchor + lag is within 14 days of the
    onset.
43. **Calendar:** CZ public holidays ±3 days, Black Friday −7…+4 days, and 1 Dec –
    7 Jan. December is the whole season, not just its end: the sim's December
    multiplier starts on the 1st. **It only explains spikes, stockouts and temporary
    changes shorter than 10 days, or a shift without a control group.** A lasting shift
    with a control and a confirmed DiD is never `explained_by_calendar`: the control has
    the same holidays, so the DiD has already removed them. Before this, Example A E5
    (found at −17.7 %, CI [−23.5, −12.3], confidence 0.72) was discarded because its
    onset was within 3 days of 28 Sept.
44. **Spikes** are runs of residual |z| > 3.5. One- and two-day blips are `transient`
    and not reported (story events are lasting changes). Churn spikes are never
    reported: churn dates are estimates. **Three-day spikes are reported, so the
    Example A viral-spike decoy (a 1-day ×2.5 with a 2-day half-life, 4 days above
    3.5) is a false positive.** Raising the minimum run to 5 days would hide it, but
    that would be fitting the decoy, so it stays.
45. **Stockouts:** ≥ 3 days without a sale of a SKU that sold ≥ 5 units a day over the
    previous 28 days; several SKUs of one category at once are one stockout.
46. **Tables of the full sim** (deliveries, reviews, tickets) are picked up if they
    exist; their column names are guessed (`delivered_date`/`promised_date`/`late`,
    `courier`, `rating`, `topic`). Check them when feat/sim-full lands.

### Narrator

47. **One LLM call** (`step="detective"`, temperature 0.1, think false, schema). It
    sees only the reported candidates and may accept, reject or merge them and write
    `narrative_cs`. Unknown ids → the whole answer is rejected and the template
    narrative is used (every candidate with confidence ≥ 0.5). Ids the model skips
    keep the scan's decision.

### Scoring

48. **Gate = metric and direction match AND timing > 0.** Deviation from the brief.
    With 0.4 timing + 0.4 segment + 0.2 magnitude and a match at 0.5, a detection with
    the right segment and size on a completely wrong date scored 0.6 and matched. The
    date-shuffle placebo found it: its p-value could never fall below 1. Set
    `score.TIME_GATE = False` for the original formula.
49. **The scorecard scores the scan's reported events** (`--llm` to score after the
    narrator), so it does not depend on the LLM. Decoys are not excluded; a reported
    decoy is a false positive and is labelled as one.
50. **Twin** = same spec and seed with `--no-story`. The sim keeps decoys in the twin,
    so a reported decoy counts against the twin too.

## Detective, round 2: churn power, recoverability, false-positive budget

51. **Second churn KPI: repeat-purchase rate** (`repeat_rate`). Of the customers with an
    order in the 60 days before an anchor day, the share who order again in the next 30
    days, dated at the last day of those 30. It does not depend on the inactivity
    estimate of decision 29. Same segments as the other KPIs, skipped below 100 active
    customers on an average day. It maps to `churn_hazard` in the **opposite** direction
    (fewer repeat buyers = more churn). The reported magnitude is the DiD relative change
    of the lapse share (1 − repeat rate); the CI and z are those of the repeat-rate DiD.
    Both churn KPIs are scanned; when both see the same event, the merge keeps the one
    with the larger placebo z (decision 40 now sorts by z, not confidence).
    - **Control** for a ratio KPI with numerator and denominator is the same ratio over
      the complement (not over everyone, which contains the segment).
    - **The DiD runs on cloglog(share).** For a Poisson buyer P(buy in 30 d) =
      1 − exp(−30·rate), so cloglog is log(30·rate) and a seasonal multiplier common to
      all segments cancels whatever the segment's base rate.
    - **Calendar smear:** a holiday moves a 30-day rolling KPI for 30 days, so the
      "change shorter than 10 days" rule of decision 43 subtracts the 30 days.
    - Spikes are never reported on it (it is a rolling mean).
52. **Shift statistics on counts leave out spike days and CZ public holidays.** Spike days
    (|STL residual z| > 3.5) are replaced by trend + seasonal before the DiD and the
    placebo, so a few days of a viral spike inside a 28-day window are not a level shift
    (the spike has its own detector). Holidays are NaN in both segment and control:
    stores close and the e-shop does not, so a channel's control has a different holiday
    response and the DiD alone does not cancel it.
53. **Detector fixes found while making Example A recoverable.** Each is structural; none
    was fitted to an answer key, and the false-positive budget is re-set afterwards on
    twins (decision 55).
    - **Break confirmation ±17 days** (`CONFIRM_DAYS = RAMP_MAX // 2`, was ±3). On a 30-day
      ramp PELT and Binseg cut at different points (Example A E5, calibrated: PELT 09-28,
      Binseg 09-18), so the ramp was never a candidate. The ramp fit decides the onset anyway.
    - **Break search ignores spike days** (x = trend there). A one-day store closure on a
      holiday is not the location of a level shift.
    - **Noise scale of a rolling KPI** (repeat rate) from differences 30 days apart, where
      the windows do not overlap. Day-to-day differences of a 30-day rolling share are
      tiny, and PELT then put a break every ten days.
    - **Category control = the other categories.** An order counts once per category it
      contains, so "everyone minus these categories" is not a count of anything. The price
      test uses the same arrays as the shift test (spike days and holidays cleaned).
    - **Mirrors.** A big drop in one segment makes its siblings look up against a control
      that contains it (calibrated E5: Brno stores −39 % → Praha stores "+24.5 %"). Of two
      reported shifts on one KPI, opposite directions, ≤ 14 days apart, each in the other's
      control, only the one with the larger z is kept (`mirror`).
    - **Churn consequences.** Customers who leave stop buying. A purchase drop that starts
      21 days before to 60 days after a confirmed churn rise in an overlapping segment is
      `explained_by_churn`, not an event of its own.
    - **Price corroboration.** A price response whose CI excludes 0 but whose z is below
      the threshold is reported if a confirmed shift with the same metric and direction in
      the same 14-day group backs it (two independent tests agree). It then wins the group.
    - **Spikes:** not on series too sparse for shifts (mean < 2/day: 1 → 5 new customers is
      not a spike), spikes starting ≤ 2 days apart are one, and they need the global
      confidence ≥ 0.5 like everything else (max |z| ≥ 5.5).
    - **`z` is in every candidate row** (detective.json), next to the confidence.
54. **Recoverability gate (`s2d/calibrate.py`, decision 6).** The runner (CLI and app) calls
    it before simulating; `--no-calibrate` skips it. Per answer-key effect:
    - **Noise unit** σ = robust SD, over every date, of the 28/28-day DiD statistic of the
      effect's KPI in its target segment against its control, on a no-story twin. The KPIs,
      controls and statistic are the detective's own (`kpis.build`, `scan.test_arrays`,
      `scan.did_effects`), read-only. In the brief's terms d = |effect|·√28 / CV with
      CV = σ·√28, an *effective* daily CV: autocorrelation and the control's noise are in it.
      The analytic Poisson CV was rejected: it puts every Example A event at d ≥ 3 while
      the detective found none of them, because the real noise of the statistic is 2–3×
      Poisson for counts and 14–26× for the rolling repeat rate.
    - **Effect** = the same statistic at start + lag (after-window from the end of the
      ramp; for the repeat rate 30 days later still), story run minus twin run with the
      same seed, so nearly noise-free. churn_hazard is measured in both churn KPIs and the
      stronger counts. d = |effect| / σ is the placebo z a detector expects.
    - **Seed:** calibration runs on seed + 7919, not on the run's own seed, so sizes are
      not tailored to the noise the detective will see.
    - **Targets** are relative to the detective's threshold: d ≥ Z_REPORT + 4.0 / 2.5 / 0.5
      (easy / medium / hard; 10.5 / 9.0 / 7.0 with Z_REPORT = 6.5). The brief's 1.5 / 1.0 /
      0.6 cannot be detected at ≤ 1 false event a year: the detector needs z ≥ 6.5 for that
      budget, so a d = 1 event is pure noise to it (agreed with the user, 2026-11-25). The
      offsets come from synthetic store series only (24 seeds; reported with the right onset
      within ±7 days): d = 6.5 → 38 % (step) / 54 % (30-day ramp), 7.5 → 54 / 71 %,
      8.5 → 58 / 79 %, 9.5 → 67 / 92 %.
    - **Scaling.** Below target, `size` (churn_shock: `churn_pct`) is multiplied by
      1.05·target/d (at most 8× per step, 4 iterations), direction kept, only ever up.
      `price_change_pct` is a stated fact and never changes. Caps: −0.85 / +4.0 relative,
      churn_pct 60. Difficulty's ×1.5/×1/×0.5 (decision 9) still applies first; calibration
      lifts what is left below the target.
    - **Widening.** At the cap and still short, or not visible in any KPI the detective
      scans (segment too small), the event's target loses one key, the one that gives the
      largest d, and is scaled again. Example A E4 (Brno × predplatitel churn): d = 0 even at
      5× hazard, widened to all of Brno.
    - **Output:** `_truth.calibration`, one row per effect: original and simulated size and
      segment, σ, CV, effect, d before and after, target, status (`ok`, `scaled`, `widened`,
      `below_target`, `not_measurable`). Anything that does not reach its target is printed
      as a WARNING and stays as it is. The answer key shows the simulated size and segment.
    - It only edits the spec and runs the sim as a black box, so feat/sim-full can change
      the sim's internals without touching it. Cost: ~20 s for 10k customers.
55. **Global threshold: placebo z ≥ 6.5** (`scan.Z_REPORT`; confidence 0.5 at Z_REPORT, so
    `MIN_CONFIDENCE` stays 0.5). Set on 10 no-story twins of Example A only (seeds 1–10,
    10k customers, 18.3 twin-years), after decisions 51–54:

    | Z_REPORT | false events / year |
    |---|---|
    | 4.0 | 6.6 (before the spike rules of 53: 6.0 with 51–52 only) |
    | 6.0 | 1.15 |
    | **6.5** | **0.82** |

    At 6.5 the 15 false events are: the viral-spike **decoy on 2025-10-14 in all 10 twins**
    (0.55 / year; the sim keeps decoys in the twin, decision 50), two new-customer shifts in
    Praha in Nov 2025 (z 8.7 and 9.9: the Black Friday week moves first orders by channel and
    segment differently), one category shift (etiopie, z 7.0) and two spikes. The decoy is a
    real one-day ×2.5 spike and stays reported rather than being filtered by a rule written
    for it (decision 44). Spike confidence keeps its own scale ((max |z| − 3.5) / 4).
    Tests that check calendar, onset and direction logic use effects above this threshold
    (store drop −50 %, churn ×5); whether a −35 % drop is reported is now a power question.
56. **Results after round 2 (2026-11-25, commits up to decision 55). Target F1 ≥ 0.7 on
    medium is NOT reached.** Example A, 10k customers, calibrated, scan output (no LLM).
    - **Seed 42, medium:** precision 0.17, recall 0.25, **F1 0.20** (was 0). E1 matched
      (timing +0 d, segment 1.0). Date-shuffle placebo p = 0.050. Twin: 1 event in 670 days
      = 0.55 / year (the decoy). Twins seeds 1–10: 0.82 / year.
    - **Detection curve** (`docs/detection_curve_a.png`, seeds 1–5):

      | difficulty | F1 | precision | recall | E1 | E2 | E4 | E5 | false pos. / run |
      |---|---|---|---|---|---|---|---|---|
      | easy | 0.165 | 0.11 | 0.35 | 5/5 | 0/5 | 0/5 | 2/5 | 11.6 |
      | medium | 0.246 | 0.17 | 0.45 | 5/5 | 0/5 | 1/5 | 3/5 | 8.6 |
      | hard | 0.244 | 0.18 | 0.40 | 5/5 | 0/5 | 0/5 | 3/5 | 7.6 |

    Why, per event:
    - **E1 (price −6 %)** is found every time, through the price test, at its price date.
      But reaching d ≥ 9 takes −37 % to −61 % (students, sensitivity 2.0, lose up to ~86 %).
    - **E2 (student churn +60 %, lag 42) is never matched.** E1 lowers students' purchase
      frequency from 03-01, so the repeat rate falls and gaps grow, which both churn KPIs
      read as churn. The detective dates "student churn" around 03-08 to 03-11, five weeks
      before E2's 04-12. Same-direction breaks within 35 days are one ramp (decision 34),
      so E2's own onset is absorbed. A rule "churn at the time of a purchase drop is the
      purchase drop" was tried and reverted: churn also lowers orders at the same time, so
      the two rules explain each other away (synthetic churn world).
    - **E4 (Brno subscribers' churn)** cannot be seen in its segment at all: d = 0 even at
      5× hazard. It is widened to all of Brno and still ends below target (d 4.8–6.1 at
      medium and easy). When found, the repeat rate dates it ~20 days late (a 30-day
      rolling KPI plus a 7-day ramp is longer than the 35-day ramp fit), and the merge
      prefers Brno × students, where E2's tail adds to it.
    - **E5 (Brno stores −20 %)** needs −50 % to −58 %. Found on time but in about half the
      runs with z 5–6, below 6.5, although calibration measured d ≈ 8–11 on its own seed.
      Calibration's d is measured at the true onset; the detective has to find the onset
      on a 30-day ramp, which costs z.
    - **Precision** is the larger problem: 8–12 false positives a run, against 1.5 a run
      on twins. They are side effects of the large calibrated events, real in the data but
      not in the answer key: accessories × students "up" against a control of coffee that
      fell 40–80 % (a mirror the sibling-only mirror rule does not cover), segment-level
      purchase shifts around E1, and Brno × student churn. Easier stories score worse,
      because their effects are bigger. A general mirror rule (any confirmed opposite shift
      in the control, larger z wins) was tried and reverted: the mirror often has the
      larger z (accessories z 15.9 vs the coffee price drop z 7.4), so it removed E1.

    - **Calibration overshoots when events interact.** At hard, E5 ends at −84 % (d 17,
      target 7): E4 is widened to all of Brno in the same loop, its churn lowers Brno store
      orders, and E5's paired measurement saw less effect in the earlier iterations. Sizes
      only ever go up, so the overshoot stays. Widening before scaling, and allowing a step
      back down, would fix it.

    What this says about the plan: with a detector that keeps ≤ 1 false event a year over
    ~1000 series, an event must be ~9 noise units to be found reliably. Effects that big
    leak into neighbouring KPIs and segments, and the scorer counts each leak as a false
    positive. Fixing that needs either a scorer that accepts consequences of a true event
    (same segment family and window, linked by caused_by), or a detector that attributes
    them (control-group contamination, churn vs frequency), not more threshold tuning.

## Detective, round 3: hierarchy, realistic sizes, consequences

57. **Hierarchical scan** (`scan.scan`). Level 0 (everyone) and level 1 (one dimension:
    city, channel, segment, category; courier once deliveries exist) are always scanned.
    A pair (city=Brno;channel=store, category × dimension) is scanned only under a
    level-0/1 change of the **same metric** that is *confirmed* in decision 38's sense
    (DiD CI excludes 0 and placebo z ≥ `Z_DRILL` = 4), and only its shifts whose ramp
    [t0, t1] lies within `DRILL_DAYS` = 21 days of that change are tested. The parent
    does not have to be reportable: it is diluted by its other half (Brno stores −50 %
    is Brno −24 %, z 5.85 against the pair's 11), and requiring z ≥ Z_REPORT for it
    hid pair events. The ±21 days are measured to the ramp interval, not its start: a
    long ramp's fitted start can lie 26 days before the parent's onset that it contains.
    - **Tests actually run** (per no-story twin, Example A, 10k customers; `scan_stats`
      in detective.json): flat scan ~143 series, ~670 DiD tests; hierarchical ~76 series,
      ~293 tests (~265 at level 1, ~27 pair tests).
    - **Threshold reset on twins seeds 1–10 (18.3 twin-years): `Z_REPORT` = 5.25,
      0.98 false events a year** (was 6.5). Not the 4–4.5 hoped for: level-1 series carry
      ~90 % of the tests (about six PELT breaks each), so dropping pairs cuts the test count
      ~2.3×, not 5×, and the placebo null has a heavy tail. Grid (pair gate at z ≥ 4):

      | Z_REPORT | 4.5 | 5.0 | **5.25** | 5.5 | 6.0 |
      |---|---|---|---|---|---|
      | false events / year | 1.91 | 1.14 | **0.98** | 0.98 | 0.87 |

      With the stricter gate (parent must be reported) 5.0 gave 0.98; the looser gate costs
      0.25 in z and buys pair recall. 10 of the 18 events are the viral-spike decoy (one in
      every twin, 0.55 / year); the rest are level-1 shifts in Sept–Dec 2025 (Black Friday
      and Christmas move first orders and churn estimates by segment differently).
    - Shifts compare z with Z_REPORT directly. Before, the rounded confidence was compared
      with 0.5, so z 4.99 passed at a threshold of 5.
58. **Calibration, round 3** (`s2d/calibrate.py`).
    - **Targets d = Z_REPORT + 1.5 / 0 / −1.25** (easy / medium / hard: 6.75 / 5.25 / 4.0).
      On Example A at 10k customers d ≈ 5 corresponds to E1 −20 to −25 % and E5 −25 to
      −30 %; the old medium target (9.0) needed −37 to −61 %.
    - **Realism caps on drops**, times the difficulty scale (×1.5 / ×1 / ×0.5): a price
      response at most 4/3 of the price change (15 % dearer → −20 % at medium), any other
      purchase or acquisition drop −30 % at medium. An event that cannot reach its target
      under its cap stays `below_target` and is listed as such. Rises keep the old cap (×5).
    - **Widen first, then scale.** Widening is judged with the event at its cap, before any
      scaling, and only if even then d < ½ target (a near miss is not a new story). Then
      scaling runs both ways: d > 1.25 × target steps the size back down, never below the
      story's own size. This fixes the overshoot of decision 56 (E5 at −84 % at hard).
    - Measured d is noisy (same seed, size −0.25 → d 5.9, −0.30 → d 4.7 for E5): the
      paired story − twin difference is not noise-free once other events move the same
      customers. Medium sizes over seeds 42, 1–5: E1 −20 % in all (d 2.5–5.5), E5 −28 to
      −30 % (d 4.0–5.7; once widened to all stores), E2 ×2.7–4.4 hazard, E4 ×2.9–5 on
      all of Brno.
59. **Scorer: consequences ("důsledky").** An unmatched reported detection is a consequence
    of a matched answer-key event, not an FP, if it starts in [start, start + lag + 60 d]
    and either shares a key=value with it (or one side is everyone) and moves the bad way
    for its metric (fewer orders, more churn, ...), or is its mirror control (same
    dimension, other value, same metric, opposite direction: accessories up while coffee
    falls). Strict precision = TP / reported; with consequences = TP / (TP + FP). Both F1s
    and both placebo p values are in the scorecard, sweep, curve and app. A reported decoy
    stays an FP unless it falls in a matched event's family and window (in Example A it is
    in Oct 2025, before every event).
60. **What the simulator would need for E2 and E4 to be distinguishable** (not done here;
    `s2d/sim/` belongs to feat/sim-full).
    - **Churn is never observed, only inferred** (decision 29: inactivity; decision 51:
      repeat rate). Both read *buying less often* as *leaving*. E1 makes students buy less
      from 03-01, so "student churn" appears five weeks before E2 (04-12) and E2's own onset
      is absorbed into that ramp. No detector on orders alone can tell "still a customer,
      buys less" from "gone" within a few weeks; it needs many months of gaps.
    - **A `subscriptions` table** (subscription_id, customer_id, plan, started_at,
      cancelled_at, cancel_reason) for the predplatitel segment, with subscription orders
      generated on schedule and stopping at cancelled_at. Churn of subscribers becomes a
      dated, observed count: cancellations / active subscriptions per day, per city. E4
      (Brno subscribers) becomes directly measurable instead of d = 0. Rough power: Brno
      subscribers ≈ 750 at 10k customers, 2 %/month → 0.5 cancellations a day; a ×1.8
      hazard for 30 days gives z ≈ 2–3. It still needs ~40k customers or ×3 hazard for
      z ≥ 5.25, but it is a power problem then, not an identification problem.
    - **For non-subscribers (E2, students):** an explicit exit signal for some share of the
      churners, e.g. `customers.closed_at` / account deletion or a `newsletter_unsubscribes`
      table (customer_id, unsubscribed_at) written for, say, 30 % of churners at their churn
      date plus noise. A frequency drop (E1) produces no such events, so the two separate.
    - **Tickets and reviews with customer_id and topic** (E3 → E4): lets the detective
      condition churn on customers who complained, which is the causal chain the story
      tells, and gives the lag search a customer-level anchor.
    - Keep `_truth.customer_state.churn_date` as it is: the scorer can then check that a
      `cancelled_at` table agrees with the hidden churn dates.
61. **Results after round 3 (2026-11-25). Worse than round 2; target F1 ≥ 0.7 is further
    away.** Example A, 10k customers, calibrated with decision 58, scan output (no LLM).
    - **Seed 42, medium:** 0 of 4 matched, 3 reported (all false: Plzeň churn 2025-07, the
      viral-spike decoy twice); F1 0 strict and with consequences, placebo p = 1.0 for both.
      Twin seed 42: 1 event = 0.55 / year (the decoy). Twins seeds 1–10: 0.98 / year.
    - **Detection curve** (`docs/detection_curve_a.png`, seeds 1–5):

      | difficulty | F1 strict | F1 with důsledky | precision (strict / cons.) | recall | E1 | E2 | E4 | E5 | FP / run | důsledky / run |
      |---|---|---|---|---|---|---|---|---|---|---|
      | easy | 0.187 | 0.209 | 0.13 / 0.16 | 0.35 | 5/5 | 1/5 | 0/5 | 1/5 | 8.0 | 1.4 |
      | medium | 0.040 | 0.040 | 0.03 / 0.03 | 0.05 | 1/5 | 0/5 | 0/5 | 0/5 | 4.8 | 0.0 |
      | hard | 0.036 | 0.036 | 0.03 / 0.03 | 0.05 | 0/5 | 0/5 | 1/5 | 0/5 | 4.2 | 0.0 |

    Why, per event (seed 42 candidates):
    - **The core conflict:** realistic sizes (E1 −20 %, E5 −30 %) put the events at a
      calibrated d ≈ 5, but the detector sees less than calibration measures (onset found on
      a ramp, other seed), so real events land at z 3–5, under Z_REPORT 5.25. Seed 42: E1's
      price test z 3.57 (CI excludes 0), students' purchase drop z 5.11, student churn z 4.24.
      At ≤ 1 false event a year and 10k customers, realistic medium events are below the
      noise. Round 2 found them only because they were 2–3× larger.
    - **E5 is now hidden by the hierarchy.** −30 % of Brno stores is about −13 % of Brno over
      a 30-day ramp: PELT finds no break in city=Brno or channel=store, so the pair is never
      opened. The flat scan of round 2 tested the pair directly.
    - **E2** still overlaps E1 (decision 60); **E4** is widened to all of Brno and stays weak.
    - **Precision** got no better: 4–8 false positives a run against ~1.8 a run on twins. At
      medium and hard none of them is a consequence of a matched event, because nothing is
      matched; the consequence variant only helps when the parent event is found.
    - **Left to try:** (a) more customers: d grows with √N, so 40k customers gives ×2 d at
      the same sizes (the sim's cost, not the detector's); (b) let a pair open under a
      parent *candidate* (CI excludes 0, any z) or under level-1 series with no break but a
      DiD shift, and re-set Z_REPORT on twins; (c) calibrate on the path the detector
      takes: for a pair, d = min(d_pair, d of its best parent); (d) the sim tables of
      decision 60 for churn.

## Verifier: the story is in the data (round 4)

62. **Change of strategy: the main proof is a verifier, not the detective** (`s2d/verify.py`).
    The blind detective stays as a bonus ("hard mode", below the verification in the
    Score tab). The verifier is not blind and does not search: for every answer-key row
    with `simulated = true` it builds **one** test from the event itself, so there is no
    multiple-testing budget to pay and z ≥ 3 is enough.
    - **KPI from the metric:** purchase_rate → orders per day (orders containing the
      target categories for a category target), churn_hazard → leavers per day (63),
      acquisition_rate → new customers per day (signed up during the data, dated at the
      first order). A `price_change` with `price_change_pct` also reads `product_prices`
      (mean price of the target's products on start vs the day before).
    - **Treated = the target; control = the same KPI in the other values of the same
      dimension** (decision 37). The first key in the order category, city, channel, segment
      is varied, the rest stays fixed: Brno stores vs stores in the other cities, Brno
      subscribers vs subscribers elsewhere, coffee vs the other categories. A target with
      no key is a plain before/after test.
    - **Windows: [T, T+28) vs [T−28, T), T = start + lag.** Not "28 days before start": E2
      starts on 2026-03-01 together with E1 and has lag 42, so the window before the start
      would credit E1's effect on students to E2. Before start + lag the event's curve is 0
      (decision 7). For lag 0 the two are the same.
    - **Test:** relative DiD, 95 % CI from the 7-day block bootstrap (`scan.did`), placebo-
      in-time z (`scan.placebo_z`, the DiD at every date more than 56 days from T); all on
      the raw daily series (no despiking, no holiday mask), so a student's SQL gives the
      same numbers. **Confirmed = CI excludes 0, direction as in the story, z ≥ 3**
      (`Z_CONFIRM`). The result also shows the story's plateau size and its mean over the
      after-window (`expected_pct`: size × mean curve; E5's 30-day ramp puts only ~half of
      −25 % into the window).
    - **SQL:** every test is one readable DuckDB query on `story.duckdb` (events → days →
      daily treated/control → window means → `did_pct`). The verifier runs that query and
      checks that `did_pct` equals the Python DiD (to 0.01 pp); its daily CTE is the series
      the Python test runs on.
    - **Twin:** the same hypotheses (built from the story's spec) run on the no-story twin.
63. **Churn KPI for the verifier: leavers, not the repeat rate.** The detective's churn KPIs
    read "buys less often" as churn (decision 60), so E1's frequency drop for students would
    pass as E2. A leaver is a regular buyer (≥ 2 order days, average gap ≤ 45 days) with no
    order in the last 120 days of the data, dated at last order + their average gap. A
    frequency drop creates no permanent leavers, and the relative DiD of leavers is the
    hazard multiplier, comparable with the story's size. The series runs from day 90 to
    120 days before the end. It is a weak KPI: on seed 42 (40k, story sizes) the DiD on the
    hidden churn dates is +30 %, on estimated dates +10 % (date error IQR −19..+16 days,
    15 % of leavers are only sparse buyers). The gap ≤ 45 filter raised E2's z from 3.3 to
    4.0 at calibrated size. Churn events therefore need large hazards (64).
64. **Calibration targets the verifier's test** (`calibrate.TARGET_D`: easy / medium / hard
    = 5 / 3.5 / 2.5). d = (DiD at T, story − twin, same seed) / robust SD of the twin's
    placebo null, i.e. the z the verifier expects. Caps no longer scale with difficulty:
    a price response at most 4/3 of the price change (E1 ≤ −20 %), any other drop at most
    −30 % (E5); rises keep ×5. **Default 40k customers** (Example A, app, sweeps): the sim
    takes 3.4 s (+1.3 s writing) at 40k, calibration ~55 s.
    Sizes after calibration, Example A seed 42, medium: E1 −9.5 %, E5 −26 %, E2 hazard
    ×4.4, E4 ×2.2 (d 3.35, `below_target`). **The churn sizes are far above the story's
    +60 % / +80 %.** That is the price of churn being inferred from orders (decision 60);
    a subscriptions or unsubscribe table would make it a power problem with sizes nearer
    the story. Calibrated d is noisy and not monotone in size (medium E4 ends at the cap
    with d 6.2, easy E4 at ×3.7 with d 5.2).
65. **Results (2026-11-25), Example A, 40k customers, seeds 1–5, calibrated once per level
    on seed 0 + 7919** (`python -m s2d.verify curve`, `docs/verify_curve_a.png`):

    | difficulty | story confirmed | twin confirmed | E1 | E2 | E4 | E5 |
    |---|---|---|---|---|---|---|
    | easy | **90 %** (18/20) | 0 % | 4/5 | 5/5 | 4/5 | 5/5 |
    | medium | **90 %** (18/20) | **0 %** | 3/5 | 5/5 | 5/5 | 5/5 |
    | hard | 55 % (11/20) | 0 % | 0/5 | 3/5 | 3/5 | 5/5 |

    Target (medium ≥ 90 % story, ≤ 10 % twin) is met. The twin does not depend on the
    difficulty, so it is 20 distinct tests (4 events × 5 seeds), not 60; the largest twin z
    is 2.15. E1 is the weakest: an order counts for coffee if it has any coffee item, and
    extra basket items come from overall popularity, so a −7 % main-category effect shows
    as about −4 %, and calibration's d (4.0) overstates the runs' z (2.5–5.3). Calibrating
    once per level instead of per seed is the same procedure (another seed than the runs)
    at a fifth of the cost.

    **Seed 42, medium** (`python -m s2d.verify RUN --twin TWIN --narrate`): **story 3/4, twin
    0/4.** E1 −4.1 % [−6.8, −3.5] z 3.5 ✅ (prices +14.8 %, story +15 %); E2 leavers +52 %
    z 4.0 ✅; E4 +39 % [−3.7, +114.5] z 2.1 ❌ (its calibrated d was already below target);
    E5 −12.5 % [−19.0, −5.3] z 6.2 ✅. Every SQL gives the same DiD. The narrator gets only
    the confirmed rows: "Od 1. 3. 2026 po zdražení kávy o 15 % klesly objednávky v kategoriích
    Etiopie, Kolumbie a Espresso o 4,1 %. K 12. 4. 2026 došlo u studentů k nárůstu odchodů
    o 52,19 %. Dne 7. 9. 2026 po otevření konkurenční kavárny v Brně klesly objednávky v
    brněnských prodejnách o 12,52 %." (gemma4:26b).
66. **What the verifier does not show.** It confirms that each event moved its KPI in its
    target against its control at its date; it does not show that nothing else did (that is
    the detective's job) and it does not separate causes that share target and date: E2
    (student churn) is tested 42 days after E1 and with a KPI that frequency drops do not
    move. Checked on seed 42 (medium, calibrated spec): a world **without E2** gives E2's test
    −8.4 %, z 0.8, not confirmed (E1 alone does not pass as E2); a world **without E1** gives
    E2 +52 %, z 4.2, confirmed, and E1's test +0.4 %, z 0.3. One seed only. The detective
    (bonus) now runs on data calibrated for the verifier, i.e. smaller effects in its terms
    than in rounds 2–3.

## Full simulator (feat/sim-full)

67. **Service layer in the day loop** (`s2d/sim/service.py`). Deliveries, reviews and tickets are
    drawn the day an order is placed, so a bad experience can change what *that* customer does
    next. Payment failure is now decided in the loop too (same rule as decision 20), so a
    cancelled order is never shipped, reviewed or ticketed. Store orders get no delivery. The
    day step is: service state of the day (parcels arriving, tickets opening and closing) →
    churn → purchases (with defection, 68) → payment → delivery, review, ticket. New RNG
    streams are appended (`deliveries`, `tickets`, `reviews`, `service`, `subscriptions`,
    `inventory`, `dirt`, `timestamps`), so every dataset changed once with this commit.
    - **Couriers** are fictional (Balík Expres, RychloKurýr, DoDveří; a story's new courier is
      Levná Doprava). Each city has one baseline courier, late 4–6 % of the time, a late parcel
      1 + Poisson(0.2) days late. Promise: 2 days after the order, 3 on Friday and Saturday.
    - **`courier_change`** with `params.delivery_delay_days` (or a `delivery_days` effect) switches
      its target cities to a new courier while its `delivery_days` curve is on. At strength
      s = delay × curve(t) the new courier is late with p = min(0.6, s), by s / p days on average,
      so the mean extra delay is s. `delivery_delay_days` is a stated fact: not scaled by
      difficulty, not touched by calibration (like `price_change_pct`, decision 9).
    - **Satisfaction of an order** u = delay_days + N(0, 0.8) (store orders: noise only).
      **Rating** = round(4.6 − 0.75·u + N(0, 0.6)), clipped to 1–5 (on-time mean ≈ 4.3).
      **Review** probability = review_rate × (1 + 1.5 if late); date = delivered + Geometric(0.4) − 1;
      a late parcel rated ≤ 3 gets topic `zpoždění` with p 0.85, otherwise the topic is drawn
      by rating. `text` is empty; `s2d/texts.py` fills it from the pools.
    - **Tickets**: the spec's base rate per order (topics kvalita / obsluha / cena / zpoždění /
      vyprodáno 35/20/15/20/10 %), plus 0.12 per day late (at most 0.6) with topic `zpoždění`,
      opened a day or two after the promised date. Support resolves them in order of opening,
      `support_agents × tickets_per_agent_day` a day, each in 0–2 days; 4 % are never resolved
      (`resolved_at` NULL), and the customer gives up on those after 60 days.
68. **Churn after a bad experience is customer-level and emerges, nothing is lagged by hand.**
    - **Upset** = P(leave instead of ordering at the next purchase occasion) =
      0.5 × clip((u − 1.5) / 3, 0, 1), set when the parcel arrives, fading with a 45-day
      half-life, cleared when the customer orders again. A day late is mostly tolerated
      (upset ≈ 0.02), three days late is not (≈ 0.25). The customer acts at their next
      *purchase occasion* (the Poisson draw that would have been an order), so the departure
      comes about one purchase gap after the parcel: in Example B ~30–60 days, matching the
      story's "~5 weeks" without a lag parameter.
    - **An open ticket** multiplies that customer's daily hazard by 5 until it is resolved
      (never-resolved: for 60 days).
    - **The same rules run in the no-story twin.** The twin has late parcels too (4–6 %, nearly
      all one day), and they barely move churn, which is why the twin's JOIN + lag test stays
      at z < 2 while the story's is z ≈ 9–10.
    - `_truth.customer_state.churn_cause`: why each leaver left, one cause drawn in proportion
      to its share of the hazard (`jiné` baseline, the story event's type → cena / kvalita /
      konkurence / vyprodáno / zpoždění, `podpora` for an open ticket; defection = zpoždění).
69. **Effects of a `courier_change` are classified** (`events.mechanism`, answer-key column
    `mechanism`): `delivery_days` = `courier` (the switch itself); `rating_mean`, `churn_hazard`,
    `ticket_rate` = `emergent` (not applied; they follow from 67–68 and their size is the
    story's expectation, not an input). An emergent effect needs a courier switch whose cities
    cover it (Example B's E2 is caused by E1), otherwise it is not simulated. Answer-key
    `magnitude_pct` of `delivery_days` and `rating_mean` is in their own units (days, rating
    points: the report says sizes of these two are absolute). Calibration only scales `curve`
    effects. The emergent sizes are not controlled: Example B's rating drop comes out at about
    −1.8 points in the target cities against the story's −0.9.
70. **Verifier for couriers** (`s2d/verify.py`).
    - `delivery_days` → **late share** (deliveries dated at the promised day, 100 if late) and
      `rating_mean` → **mean rating** (by review date): ratio KPIs, daily mean, DiD as a
      difference in their own units (pp, rating points) with `scan.did(ratio=True)` and the
      placebo on the same statistic. Treated = target cities, control = the other cities. The
      late-share row also reports the DiD of the mean delay in days, next to the story's days.
    - `churn_hazard` of a courier_change gets **two** tests: the usual city-level leavers
      (decision 63), and **`late_churn`, the JOIN + lag test**: every parcel delivered in the
      target cities while the new courier runs (start .. start + ramp + duration, at most
      120 days before the data end), late vs on time, outcome "left 30–60 days later" = this
      order was the customer's last, and one average gap after it (the customer's own gap up
      to this order, ≥ 2 order days) falls 30–60 days after the parcel (decision 63's leaver
      date, per parcel). Statistic: difference of the two shares in pp, 95 % CI and SE from a
      bootstrap over customers (their parcels are not independent), z = diff / SE. Confirmed =
      CI excludes 0, late higher, z ≥ 3. The same comparison over the same length *before* the
      switch is shown as a placebo.
    - **Unit = the parcel, not the customer.** A customer-level split ("had any late parcel")
      compares heavy and light buyers: heavy buyers are more likely to get some late parcel and
      also more likely to come back. On seed 42 it made late customers look *more* loyal
      (lapse 40 % vs 49 %). Per parcel, lateness is random given the city and the date.
    - **Result, Example B, 40k customers, seed 42 (calibrated, hard): story 6/6, twin 0/6.**
      Late share +49.2 pp (z 83.6), mean delay +2.17 d (story 2.5), rating −1.79 (z 21.7),
      city-level leavers +58 % (z 3.3), **JOIN + lag: 7.4 % of 6569 late parcels vs 3.8 % of
      4927 on time (×1.96, +3.64 pp [2.8, 4.4], z 9.0); before the switch +0.68 pp, z 1.1.**
      Seeds 1–5 (no calibration): JOIN + lag z 8.9–10.6, twin ≤ 1.9; city-level leavers z
      2.0–3.8 (4/5): the aggregate barely shows it, the JOIN does.
71. **`stores` table** (store_id, city, name, opened_date): `per_city_with_store` stores in every
    city with a store. `orders.store_id` is set for store orders: the customer's home store,
    customer_id modulo the city's stores (no RNG).
72. **Subscriptions** (`s2d/sim/subscriptions.py`, decision 60). A segment holds subscriptions if
    `segment.subscription` is true, or, when the field is left out, if its id looks like one
    (predplat…, subscri…, abonent): LLM-written specs get them without knowing the field.
    Example A sets it on `predplatitel`.
    - Every subscriber has one subscription from signup (`started_at` = signup date, also before
      the data). The plan (týdenní 7 / dvoutýdenní 14 / měsíční 30 / dvouměsíční 61 days) is
      the one nearest to carrying 70 % of the customer's own orders; the other 30 % stay
      ad-hoc Poisson orders. Scheduled orders come every plan interval from a random phase,
      are shipped through the e-shop (if the shop has one), and carry `orders.subscription_id`.
      Purchase-rate events do not change scheduled orders (a contract); churn does.
    - A scheduled order is a purchase occasion: an upset customer may leave instead (68).
      When a subscriber leaves for any reason, `cancelled_at` = that day and `cancel_reason` =
      the churn cause (68; baseline churn becomes `už nepotřebuji` / `finance` / `jiné`).
      Scheduled orders stop at cancellation (tested).
    - **Upset only after a late parcel** (refines 68). With upset drawn for every parcel, the
      noise term alone made on-time parcels cause defections, and in Example A 18 % of all
      cancellations said `zpoždění` with no story behind them (5 % after this change). Upset
      now starts at u ≥ 2 (a one-day delay gives ≈ 0.007, four days ≈ 0.33).
    - **Verifier:** a churn effect whose target segments all hold subscriptions is tested on
      **cancellations per day** (`subscriptions.cancelled_at`), not on inferred leavers.
      Example A seed 42 (40k, medium, calibrated): **E4 is calibrated to +85.5 % hazard on its
      own target (story +80 %), was ×2.2 widened to all of Brno; measured +93 % [49, 145],
      z 4.7, twin z 0.2.** E2 (students, leavers) missed at z 2.95 this run: story 3/4, twin 0/4.
73. **Inventory and supply** (`s2d/sim/inventory.py`; tables `suppliers`, `shipments_in`,
    `inventory_daily`). Baskets are now drawn inside the day loop (same rules as decision 18,
    plus `is_main`), so they can be served from stock.
    - **Replenishment:** each supplier is reviewed once a week (its own weekday), order-up-to
      S = demand × (lead time + 7 + safety), safety = 4 days + 0.3 × lead time, minus stock
      and what is on its way. `demand` is a running estimate (28-day half-life) of units sold
      *plus lost*, started from the expected demand of the starting base. A shipment arrives
      after the lead time; with probability 1 − reliability another 0.3–1.0 lead times later.
      Warm start: the weekly orders of the last lead time are already on their way. One
      shipment = one supplier's weekly order; `shipments_in` has one row per product line
      (`shipment_line_id`, `shipment_id`, ordered / expected / received date, quantity).
      Baseline (Example A, 40k): 0.8 % of product-days at zero stock, 1.1 % of units lost,
      all from unreliable suppliers.
    - **Serving:** lines are served in order while stock lasts. A failed main item is replaced
      by another product of its category in stock with p 0.6, or, if the whole category is
      out, by any product in stock with p 0.3. **An order with no line left is lost: it is not
      in `orders` at all** (an e-shop shows "vyprodáno" before checkout), the customer writes a
      `vyprodáno` ticket with p 0.08 (no order_id; `tickets.product_id` = the wanted product)
      and gets upset 0.05 (decision 68).
    - **`supplier_delay`** (needs `params.lead_time_multiplier` and a target supplier or
      category): every shipment of the target's products that would arrive while the event is
      on (start .. start + the longest lag + ramp + duration of its effects, 30 days if none is
      finite) and was ordered before its end takes multiplier × lead time from its order date,
      also those already on their way. Sales stop only when the shelf runs empty.
    - **`stockout`**: the target's products cannot be sold while its first effect is on.
    - Their effects (`ticket_rate`, `purchase_rate`, `churn_hazard`) are **emergent** (decision 69):
      lost orders, `vyprodáno` tickets, upset. Example A seed 42, 40k: S_ETH shelves are empty
      from about 05-12 (start 05-04; the story said lag 10) to mid-June, `vyprodáno` tickets go
      from ~15 to ~100 a week, nothing in the twin.
    - `tickets.product_id` and `reviews.product_id`: the order's main product (or the wanted one).
74. **Verifier for supply events.** `ticket_rate` → **tickets per day** with the topic the event
    is about (`vyprodáno` for supplier_delay / stockout, `zpoždění` for courier_change), joined to
    products, so a supplier target varies `p.supplier_id` (`supplier` is now first in KEY_ORDER;
    KPIs without a supplier column drop it). The DiD is a **difference in tickets a day**, not
    relative: before a stockout the target may have no sold-out ticket at all (6k customers:
    0.0 a day before, so the relative DiD was 10^11 %). A supplier_delay / stockout also gets a
    **zero-stock test**: share of the target's products with `stock_units = 0` per day
    (inventory_daily), pp DiD against the other products, at the same T as its first effect.
    Example A seed 42 (40k, uncalibrated): E3 zero-stock +78 pp (twin 0.00), sold-out tickets
    confirmed z ≈ 50 (twin z 0.2). Calibration does not touch emergent effects (decision 69).
75. **Dirt layer** (`s2d/sim/dirt.py`). `--dirt none|low|medium|high`, default from
    `noise.messiness` (light → low, heavy → high). It writes a **separate copy**
    (`out/export/*.parquet`, `out/export.duckdb` with `_truth.dirt_log`: table, column, kind,
    rows); `story.duckdb` stays clean, because the verifier, the detective and the scorer
    read it. Seeded from the `dirt` stream: same seed, same dirt.
    - Per level, the share of rows touched (low / medium / high): missing diacritics 1 / 5 /
      15 %, typos (swap, drop, double, neighbouring QWERTZ key) 0.5 / 2 / 5 %, NULLs 0.5 / 2 /
      5 % (phone 3×, review text 2×), duplicates 0.2 / 1 / 3 %, format variants 5 / 15 / 35 %.
    - Where: customer names, cities (also `praha`, `PRAHA`, `Brno ` with a trailing space),
      phone formats (`777123456`, `00420…`, `+420…` without spaces), NULL phone / e-mail /
      gender; orders.city; duplicate customers (new id, e-mail in capitals or with `+1`) and
      duplicate payments (a double submit, new id); couriers, review and ticket topics and
      cancel reasons without diacritics; NULL review text.
    - **Keys stay valid**: a duplicate gets a new id, NULLs only go into nullable non-key
      columns, so the export keeps PK/FK constraints (decision 76). The `data_outage` decoy
      (Example B) is still not simulated: in the clean data it would be a real gap the
      detective should see, and the dirt layer does not reach the clean data.
76. **Postgres export** (`s2d/sim/pg.py`; `python -m s2d.sim run … --pg URL`, or
    `python -m s2d.sim pg RUN_DIR --pg URL` for an existing run). DuckDB's postgres extension
    (`ATTACH … (TYPE postgres)`, binary COPY), so no new Python dependency; psycopg is not
    installed. Analyst tables go to `--pg-schema` (default `public`), the hidden ones to
    `_truth` (answer key, spec, customer state, calibration, dirt log). Tables of the same names
    are dropped first (CASCADE), so a re-export replaces. Then every table gets its primary
    key (`inventory_daily`: product_id + date) and the 19 foreign keys of `pg.FOREIGN_KEYS`;
    Postgres validates them against the data when they are added. With a dirt level the
    dirty copy is exported (its keys stay valid, decision 75), else the clean one.
    `export.duckdb` now also carries the `_truth` tables so the Postgres copy has them.
    - An empty `stores` table (Example B) is typed explicitly: an empty DataFrame column is
      VARCHAR, and Postgres refused the `orders.store_id` FK (bigint vs varchar).
    - Tested against an embedded Postgres 16 (`uv run --with pgserver`, not a project
      dependency; Docker's daemon was not running): Example B, 40k customers, dirt medium:
      19 tables in 1.3 s, row counts equal to DuckDB. `tests/test_pg.py` runs when
      `S2D_TEST_PG` is set and is skipped otherwise.
77. **Review texts.** `python -m s2d.sim run` fills `reviews.text` from a text pool (`--texts POOL`; by default `data/text_pools/<company>.json`, else `generic.json`, if one exists; `--texts none` skips) with `texts.fill_reviews`: the pool key is the review's rating, topic and its product's category; `{produkt}` = product name, `{dny}` = the parcel's delay, `{objednavka}` = order id. No pool on disk yet (the overnight batch has not run), so the column stays empty until one exists. Tickets get no text.
78. **Final check, Example B (2026-11-25): `python -m s2d.sim run examples/b.yaml --seed 42
    --n-customers 40000` (calibrated, hard, dirt medium) and its twin, `python -m s2d.verify`:
    story 6/6 confirmed, twin 0/6.** Sim 3.6 s per run at 40k (A: 4.8 s).

    | test | measured | z | twin | twin z |
    |---|---|---|---|---|
    | E1 late share, Ostrava + Olomouc vs other cities | +49.5 pp (mean delay +2.17 d, story 2.5) | 70.2 | +0.4 pp | 0.4 |
    | E1 mean rating | −1.54 points (story −0.9) | 14.0 | −0.17 | 1.6 |
    | E2 leavers, city level | +87 % | 5.6 | −1.6 % | 0.3 |
    | **E2 JOIN + lag** | **late 7.8 % of 6742 parcels vs on time 3.7 % of 5010, ×2.09, +4.05 pp [3.2, 4.9]** | **9.6** | −0.96 pp | 1.6 |
    | E3 new customers (geek, mobily) | +44.5 % | 5.3 | −7.0 % | 0.6 |
    | E3 orders | +16.9 % | 6.0 | +5.9 % | 2.1 |

    Before the switch the same JOIN comparison gives −0.26 pp (z 0.6). The city-level leaver
    test is confirmed on this seed (z 5.6) but not reliably (z 2.0–3.8 on seeds 1–5; 2.5 on
    seed 42 at 30k); the JOIN test is (z 6.8–10.6). `scripts/late_churn_chart.py` draws
    `docs/late_churn_b.png` from the verifier JSON (`offsets`): % of parcels after which the
    customer left, by days to the estimated departure. The excess after a late parcel peaks
    at about 10–40 days and fades by ~70; the 30–60-day window catches its middle, not all
    of it. The app's Score tab shows the test with its SQL and this chart.
79. **The verifier on any story, not only A/B (2026-11-26).** A full run on a new story
    (Psí Bouda: supplier delay, breeders' churn, courier switch, churn after it) confirmed
    2/6 and printed NaN and +616666666566.7 %. Causes and fixes, all in `s2d/verify.py`:
    - **Span.** `_span()` gave every KPI it did not list (late share, rating) the leavers'
      span, which drops the last 120 days. Example B's switch was in February, so it never
      showed; Psí Bouda's in August fell outside. Now only leavers (warm-up + 120-day edge)
      and new customers (warm-up) are cut; anything dated by its own row runs to the end.
    - **Control fallback** (`resolve`). The control is the other values of the varied key
      with the same fixed keys. When that group has no data in the before-window it falls
      back to *everything outside the target*, then to *no control* (plain before/after),
      and says so in `note`. Psí Bouda: no other supplier sells kibble and canned food, so
      the stockout's control is all other products; only breeders subscribe, so their
      cancellations have no control at all. `resolve` runs on the story and the twin reuses
      the result, so both run the same test; calibration resolves on its twin too.
    - **Cancellations are a rate**: cancellations per 1000 subscriptions active that day
      (`‰/den`), DiD as a difference. The story's expectation is 1000 × the added daily
      hazard (churn_shock) or base hazard × relative size, in the same unit.
    - **Small baselines.** A count KPI (orders, leavers, new customers) with fewer than
      `MIN_BASE_EVENTS` = 20 events in a group's before-window is tested and reported as a
      difference in events a day (`/den`), not a relative change. Chosen over a floor on
      the denominator: a capped % is still a made-up number, a difference is what happened.
    - **NaN never reaches the table.** A non-finite DiD, CI or z makes the row
      `not_testable` with a `reason` (too close to the data end/start, empty KPI), shown in
      the CLI table and the app. The placebo null drops NaN anchors.
    Psí Bouda (seed 7) after the fixes: 5/6, twin 0/6; with decision 80 6/6, twin 0/6.
80. **Every event gets its full measurement window** (`verify.needed_span`, `fit_windows`).
    From the spec alone (no data): each test needs [T − 28, T + 27], leavers + 120 days at
    the end and + 90 warm-up at the start, new customers + 90 at the start, the JOIN + lag
    test a 28-day cohort + 120 days. If the data is shorter, `meta.days` is extended (or
    `meta.start` moved back) and a warning names the event. The story's dates are kept,
    not shifted: they are what the narrator tells, and an August churn really cannot be
    measured in data that ends in October. Capped at the schema's 1095 days (then a
    warning that some tests will not be measurable). Runs in the compiler (after
    validation, `CompileResult.warnings`, shown in the app), in `python -m s2d.sim run`
    (`--no-fit` to keep the spec as is; before `--no-story`, so the twin covers the same
    days) and in the app's simulation job. Examples A and B already fit (unchanged data).
81. **Narrator units.** The LLM got `measured_pct` without a unit and wrote "+5.04 %" for
    +5.04 tickets a day. Each fact now carries `jednotka` and `zmena` (the change as Czech
    text with its unit: "+5.04 tiketu denně", "+4.17 zrušení na 1000 aktivních předplatných
    denně"), and the template uses the same `size_cs`. `check_numbers` validates the LLM
    text: every number must be in the confirmed rows at the precision it is written
    (measured, CI, z, date parts, price, JOIN shares, numbers in claim_cs, the window
    constants, 0–10), and a number written with `%` must be one whose unit is %. A failed
    check falls back to the template, with the reason in `source`.
82. **A story with no events.** The LLM grammar required ≥ 1 event (gemma emitted lazy
    `events: []`), so "nothing happens, only the school start and Christmas" came back as
    two invented campaigns with budget 0. Now `events` may be empty in the grammar; an
    empty list is answered once with "every change must be an event, seasonal peaks are
    not; if there really is none, send the same spec with events: []", and a second empty
    list is accepted. New rule in the prompt: seasonal peaks are baseline.seasonality.
83. **Unsupported events and effects.** The sim now skips an unsupported *effect* alone, not
    its whole event: a quality_issue with a rating drop (ratings only move through a
    courier switch) and lost orders keeps its lost orders (answer key: `simulated` per
    effect). An unsupported event *type* (service_outage, staff_shortage, viral_spike as an
    event) is still skipped whole. `verify.untested` lists both, with the reason in Czech;
    the CLI table prints them and the app shows a warning per event, and "no event to
    verify" when nothing is testable. `--strict` still fails on either.
84. **`scripts/e2e.py`** runs compiler (real Ollama, no LLM cache unless `--cache`, no Claude
    fallback) → fit → calibration → sim → twin → verifier → narrator for every story in
    `examples/stories/`, and writes spec, verify table/JSON and a summary to `data/e2e/`.
    Goals checked per story: no crash, no NaN, no |x| > 1000 in a % column, twin ≤ 10 %,
    story ≥ 80 % of the tests of supported effects. 8 new stories: lékárna (price change,
    campaign), hračky (stockout, churn), zahrada (supplier delay, courier switch + churn),
    kavárny (quality issue, competitor), fitness (price change, subscriber churn,
    campaign), PC servis (outage, staff shortage, viral video: unsupported, + a price cut),
    víno (events in the last two months of the data) and papírnictví (no events).
85. **New customers are dated at signup** (`customers.signup_date`), not at their first
    order (decision 31 keeps the first order for the blind detective). The first order
    comes weeks after signup, so a 3-week campaign was smeared past the 28-day window: on
    the fitness story the Brno campaign read +6 % (story − twin) by first order and +52 %
    by signup, against +46 % in the story. Signup is an ordinary column of the analyst's
    table, and dated by its own row it needs no warm-up cut.
86. **Story and twin stay paired** (`s2d/sim/rng.py` `DailyRng`, `population._acquisitions`).
    Calibration measures an effect as story − twin at T with the same seed, assuming the
    two runs draw the same numbers except where the story acts. They did not: the day
    loop's streams are consumed in variable amounts (baskets per order, a draw per
    delivery or review), so one extra order on day T shifted every later draw, and numpy's
    Poisson sampler uses a rate-dependent number of uniforms, so a campaign in one cell
    reshuffled all later acquisition counts. The "noise-free" effect carried about √2
    noise units: on lékárna d went 2.9 → 2.4 → 3.9 for sizes 0.6 → 1.0 → 1.86, and
    calibration stepped the wrong way. Now the eight day-loop streams are re-seeded from
    (stream, day) every day (a difference cannot leak into the next day; within a day
    arrays run over customers in signup order, so the starting base draws the same), and
    acquisition counts are the inverse Poisson CDF of common uniforms (a higher rate only
    adds customers). d is monotone in size and an effect of E3 no longer moves E1's d.
    Fitness, calibrated, seeds 1–4: 14/16 tests confirmed, twin 0/16 (before: E3 orders
    z 0.55 on seed 7 after calibration predicted 4.5). Every dataset's realization changed
    (same seed, different numbers): Examples A and B at 40k, seed 42, calibrated: A 5/6
    (E2 student leavers z 2.8), B 5/6 (E2 city-level leavers z 0.8, the unreliable test of
    decision 78; its JOIN + lag test z 8.7), twins 0/6.
87. **Known limits** found by the e2e run, not fixed here:
    - An event for *everyone* has no control group: a plain before/after, whose bootstrap CI
      is wide when the window crosses Christmas or New Year (fitness E1: placebo z 5, CI
      touching 0 before decision 86 scaled it). A year-over-year control (same dates 364
      days earlier) would need a year more data before the event.
    - "In window" for orders assumes every order responds to purchase_rate. Subscribers'
      scheduled orders do not (`SCHEDULED_SHARE`), so in an all-subscription business the
      measured change is smaller than the stated one. Calibration measures the real effect,
      so this only affects the expectation column, not whether the test confirms.
    - Calibration measures d on one seed. For a small cell (pekárna: Prostějov × families,
      6000 customers) *which* customers leave is binomial noise inside the effect, which
      pairing cannot remove: calibrated d 5.4, realized z 1.1–4.7 over seeds 1–5 and 7
      (mean 2.9). Measuring d on 2–3 seeds would fix it at about twice the calibration time.
    - A small count cell can confirm on the twin by chance: lékárna's seniors × app new
      customers (≈1.4 a day) read +69 %, z 3.7, on the no-story twin.
    - gemma sometimes returns an empty narration (vino, zahrada); the template is used.
88. **E2E results (2026-11-26, `scripts/e2e.py`, gemma4:26b, no LLM cache, seed 7, each
    spec's own customer count).** 11 stories (8 new + 3 old), no crash, 0 NaN, 0 values
    above 1000 %. Story tests confirmed 23/28 (82 %), twin 1/28 (3.6 %). Valid spec on the
    first try 8/11; the 3 others on the second (papírnictví: the empty-events challenge
    of decision 82, as intended).

    | story | 1st try | types (* unsupported) | story | twin | notes |
    |---|---|---|---|---|---|
    | fitness | yes | price_change, churn_shock, campaign | 4/4 | 0/4 | |
    | hračky | yes | supplier_delay*, churn_shock | 0/1 | 0/1 | LLM left out lead_time_multiplier: now a validation error (decision 89); rerun 3/3, twin 0/3 |
    | kavárny | yes | quality_issue, competitor_entry | 2/2 | 0/2 | rating effect untested (decision 83) |
    | kola | no (2) | supplier_delay, churn_shock, competitor_entry | 3/4 | 0/4 | data extended 5 days |
    | kosmetika | yes | campaign, churn_shock, supplier_delay | 4/5 | 0/5 | |
    | lékárna | yes | price_change, campaign | 3/3 | 1/3 | twin false positive (decision 87) |
    | papírnictví | no (2) | – (no events) | 0/0 | 0/0 | |
    | PC servis | no (2) | price_change, service_outage*, staff_shortage* | 1/1 | 0/1 | viral video went to decoys |
    | pekárna | yes | quality_issue*, churn_shock, price_change | 0/2 | 0/2 | E3 capped by the price-elasticity cap (below_target); E2 one-seed calibration (decision 87) |
    | víno | yes | competitor_entry, campaign | 2/2 | 0/2 | data extended 12 days for the 15 Oct campaign |
    | zahrada | yes | supplier_delay, courier_change, churn_shock | 4/4 | 0/4 | |

    With the hračky rerun: 26/30 (87 %), twin 1/30. Per-story goals: 7/11 met (≥ 80 %
    story, ≤ 10 % twin); a story with 1–3 tests misses on a single test either way.
    Compile 20–50 s, calibration + sim + twin 2–48 s, verification 0.4–2.4 s per story.
89. **Supply events need their params at validation.** `supplier_delay` without
    `lead_time_multiplier`, or a supply event without a supplier/category target, is now a
    StorySpec error (the LLM retries with the message) instead of an event the simulator
    silently skips. Unsupported event *types* stay valid: they are real story content.

## Stated sizes and a year-over-year control (feat/stated-sizes, 2026-11-27)

90. **A size the story states is a fact** (`effect.size_stated`, default false). The
    hackathon brief "tržby klesly o 5 %" compiled to purchase_rate −0.05 and calibration
    (Gemma had picked easy) made it −30 %. Now:
    - The compiler sets `size_stated: true` when the story text gives the effect's number
      (rule in the prompt; few-shot Example A's E5 "klesnou o pětinu" and Example B's
      "o 2–3 dny později" are marked; "mírně klesnou" stays false). `llm_schema` requires
      the key like every other, so the model has to decide. A spec without it validates
      (the three gemma fixtures have none) and means false.
    - `DIFFICULTY_SCALE` skips it (`events.size_scale`: 1 for a stated size), in the sim,
      the answer key and the verifier's `story_pct`. Decision 9 still holds for the rest.
    - Calibration measures it (d, σ, effect in `_truth.calibration`, new column `stated`)
      but never scales it, never caps it and never widens its event (a stated −20 % in Brno
      is not a −20 % in all stores). Below target it is `below_target` with a WARNING that
      says the size is the story's and stays; the expected z is the row's `d`. For a
      churn_shock, a stated effect protects `churn_pct`.
    - Consequence for Example A: E5 now stays at the story's −20 % (it was calibrated to
      about −26 %).
91. **Year-over-year control for an event with no group to compare with** (`verify.resolve`,
    `control_mode = "yoy"`). An event for everyone (empty target), or one whose keys the KPI
    cannot split by, had a plain before/after, and that measures the season too: the brief
    story's −5 % read −10 to −14 % over seeds 1–5 at 20k customers, its twin −5 to −9 %
    (retail_cz: March → April is a seasonal drop). Now:
    - **Treated** = the KPI around T, **control** = the same KPI over the same calendar
      window 364 days earlier (52 weeks, same weekday). DiD = (after/before at T) /
      (after/before a year earlier) − 1, the same statistic, bootstrap CI and placebo-in-
      time z as every other test: the series is the KPI joined to itself 364 days back, so
      it starts a year after the data and the placebo null runs over that last year.
    - **A public holiday in either year counts in neither** (NULL that day in both series;
      `avg` and `nanmean` skip it). Easter moves (Good Friday 2025-04-18, 2026-04-03) and
      stores close on holidays, so without the mask the after-windows of the two years held
      the holidays on different days and the block bootstrap's CI was ±8 % at any customer
      count (−5 % never excluded 0). The holiday list (the sim's `holidays.CZ`) is inlined
      in the SQL as a `holidays` CTE.
    - **Only with a year of data**: the KPI must exist from T − 28 − 364 (leavers: after
      their warm-up). Otherwise the test stays a plain before/after, `control_mode` none,
      and `control_reason` says what date the year-over-year control would need. The data
      is not extended for it (`fit_windows` is unchanged).
    - **Not for a target that has a dimension but no other group with data** (Psí Bouda:
      only breeders subscribe). That stays plain before/after, as asked: the target is a
      group, and on Psí Bouda's cancellations a YoY control measured +4.07 ‰/den
      (story +3.86) but at z 2.95 instead of a confirmed plain test, because a year earlier
      the subscription base was young and its rate noisy.
    - The SQL (example in the result's `sql`): `kpi_daily` (one group, as before), then
      `daily` = `kpi_daily k JOIN kpi_daily prev ON prev.day = k.day - 364` with the two
      holiday LEFT JOINs; the `windows` and `did_pct` parts are unchanged. `sql_matches`
      holds on story and twin. Calibration uses the same `resolve` and series, so it
      measures d with this test. The narrator says "oproti stejnému období před rokem"
      (template and the LLM's `kontrola` field), the app labels the line "před rokem".
92. **The brief story, checked without the LLM (2026-11-27).** `examples/brief/sport.yaml`,
    written by hand: SportMax, sporting goods, e-shop 0.6 + stores in Praha and Brno,
    20 000 customers, data 2025-01-01 .. 2026-12-31, retail_cz season, one event for
    everyone from 2026-04-01: purchase_rate −0.05, ramp 7, permanent, `size_stated: true`,
    medium. Calibration keeps −5 % (d 2.9 on seed 1 + 7919, `below_target`, warning).
    Sim → twin → verify, seeds 1–5, orders, year-over-year control:

    | seed | story | 95 % CI | z | ok | twin | 95 % CI | z | ok |
    |---|---|---|---|---|---|---|---|---|
    | 1 | −5.43 % | [−10.6, −2.4] | 1.62 | no | +0.01 % | [−4.9, +4.0] | 0.13 | no |
    | 2 | −5.00 % | [−8.2, −0.4] | 3.70 | yes | +0.08 % | [−2.2, +4.4] | 0.04 | no |
    | 3 | −7.42 % | [−9.4, −4.3] | 2.44 | no | −2.66 % | [−4.2, +0.5] | 1.14 | no |
    | 4 | −2.80 % | [−6.5, +1.3] | 1.06 | no | +0.90 % | [−2.8, +5.8] | 0.55 | no |
    | 5 | −6.78 % | [−10.1, −5.0] | 4.42 | yes | −2.07 % | [−5.8, +0.9] | 0.82 | no |

    Mean −5.49 % (twin −0.75 %). Before (main, plain before/after, same seeds): −10.1 to
    −13.9 % (mean −11.7 %), twin −5.3 to −9.2 % (mean −7.1 %), 0/5 confirmed.
    **At 20k customers −5 % for everyone is measured right but not confirmable**: the
    year-over-year statistic has a placebo SD of about 3 % (two noisy years instead of
    one), so −5 % is z ≈ 1.6–2 on average. By customer count (seeds 1–5, story / twin
    confirmed, mean measured): 40k 3/5 / 0/5 (−5.2 %); 60k 3/5 / 0/5 (−5.0 %); 80k 4/5 / 0/5
    (−5.1 %, z 2.95–6.2); 120k 4/5 / 0/5 (−4.8 %, seed 1 z 2.92); **160k 5/5 / 0/5** (−4.6 %,
    z 4.6–7.2; largest twin z 3.07, CI includes 0). So about 80k for "usually", 160k for
    "every seed". The size is not inflated to get there. The twin sits slightly below 0
    (mean −0.1 to −1.1 % by count; the placebo null's median is −0.2 %), not explained.
    The test suite runs the 80k seed 2 case (confirmed −5.33 %, twin −1.04 %).
    Gemma (gemma4:26b, one compile of the brief, no cache) now writes `size_stated: true`
    and −0.05; it picked difficulty easy, and the size stays −5 % (before: −30 %).
93. **Regression (2026-11-27)**, `python -m s2d.sim run … --seed 42` (calibrated) + twin +
    `python -m s2d.verify`, main vs this branch: Example A and B at 40k, and the three gemma
    fixture specs (`tests/fixtures/spec_{pekarna,kosmetika,kola}.yaml`, the hand-free path,
    own customer counts). **Every verify table is identical**: A 5/6, twin 0/6; B 5/6, twin
    0/6; kola 3/4, 0/4; kosmetika 4/5, 0/5; pekárna 1/2, 0/2; every SQL matches. None of
    them has an event for everyone, and A's E5 (now stated, −20 %) was already calibrated
    to −20 % on seed 42. The fixtures have no `size_stated`, so kola's "čtvrtinu tržeb" is
    still scaled −25 → −30 % there. `scripts/e2e.py` (Ollama reachable) on fitness, kola,
    lékárna, seed 7: fitness 3/3 / 0/3 (its E1 for everyone starts 2026-01-01, a year of
    data is missing, so plain before/after with the reason in the note); kola 3/4 / 0/4 with
    E3 now stated by gemma at −25 % (confirmed, z 6.3); lékárna 2/3 / 1/3 (the known twin
    false positive of decision 87). New LLM outputs, so not a like-for-like comparison with
    decision 88.

## The HTTP API (feat/api, 2026-11-27)

94. **One process, one worker thread, jobs as files** (`s2d/api/`, contract `docs/API.md`).
    The queue is in memory but rebuilt from `$DATA_DIR/api/jobs/*/job.json` at startup:
    `running` → `error: "server restarted"`, `queued` runs again in creation order. Detective
    runs (`detect.json` next to the job) share the same FIFO queue, so the GPU never gets two
    AI calls at once. Uvicorn must run with one worker process (`--workers > 1` would start
    two queues). The pipeline is `run_sim`'s, plus what the app does elsewhere: reviews from a
    text pool when `texts.find_pool` finds one, the dirty export from `noise.messiness` (or
    `dirt`), and `verify.narrate` (template when the LLM fails or replay has no cache).
    `fit_windows` runs after the overrides, as in the app.
95. **ETA = prior shape × median ratio.** Each step has a prior `fixed + per_customer · n`
    (measured on the notebook, example A: calibration + simulation 17.6 s at 3k, 57 s at 20k,
    92 s at 40k → 12 s + 2 ms/customer; twin 0.7 / 3.3 / 6.2 s → 0.15 ms/customer; AI steps
    fixed 35 s and 15 s). Every finished step stores `{s, n}` in `timings.json` (last 30);
    the estimate is `prior(n) · median(s_i / prior(n_i))`, so one 40k run corrects the
    estimate for 10k too, and the calibration's fixed part is not scaled away. A step answered
    from the LLM cache, or the narrator's template, records nothing: 0 s says nothing about
    the GPU. While queued, `eta_s` includes what is left of every job ahead.
96. **The sandbox is a separate file, not a filtered view.** `analyst.duckdb` is a copy of
    schema `main` only, built when the job finishes, so `_truth` does not exist in it. Each
    query opens it `read_only` with `enable_external_access=false`, extension auto-load/install
    off, `lock_configuration=true` (set last), 2 threads, 2 GB; a `threading.Timer` calls
    `con.interrupt()` after 20 s (408); at most 1000 rows (`truncated`). Checked in
    `tests/test_api.py`: `_truth.*`, `read_parquet`/`read_csv`/`read_text`/`glob` on real
    paths, `ATTACH` of the job's own story.duckdb, `COPY TO`, `SET` of either option,
    `INSTALL`/`LOAD`, `CREATE`/`DROP` all fail. The same file feeds `/tables` and the ZIP.
97. **Visibility**: a student sees only own jobs, teacher and admin every job (they hand
    datasets out); `GET /v1/jobs` lists everyone's only for admin. A job you may not see is
    404, not 403, so ids do not leak. `/result` carries the spec and the verifier's SQL (the
    person who wrote the story knows it); `/answer-key` (teacher/admin) adds the hidden
    tables `answer_key`, `decoys`, `calibration`, and the detective's `score` is staff-only.
98. **Not done in the API**: the ZIP has no Postgres SQL dump and no ERD (PLAN mentions them;
    `s2d/sim/pg.py` exports to a live Postgres, not to a file); no rate limit per token; no
    job deletion or cleanup (a 40k job is ~60 MB on disk, the ZIP ~25 MB more).
