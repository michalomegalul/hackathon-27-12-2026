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
