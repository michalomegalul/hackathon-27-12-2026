# Task: raise the blind detective's F1 toward its information limit

## Context
`s2d/detective/` is a blind detective. It scans ~150–300 daily KPI series of a synthetic e-commerce database (670 days) and reports planted business events. Each run plants 5 events at d ≈ 3.5–5 noise units. Today it finds about 2.5 of 5 with about 4 false finds per run (F1 ≈ 0.435). Background research is in `reports/Slepá detekce událostí v syntetických datech.md`; read its sections "Co už pipeline dělá" and "Pět změn" first.

Per that report's check of `scan.py` (verify this yourself), these already exist:
- detection on `trend + resid`
- `ramp_onset` with the DiD "after" window starting at the end of the ramp
- `price_candidates` (PRICE_Z = 3), but only for orders
- the rules `mirrors`, `explained_by_stockout`, `control_moved` and `churn_consequences`

Remaining losses:
- **(a)** A −20 % 30-day ramp in one city × channel. Pairs are opened only under a parent with z ≥ `Z_DRILL` = 4, and the cell effect dilutes to about −7 % in the city and −2 % in the channel.
- **(b)** Segment churn after a price rise is dated 5–6 weeks early, because order gaps are measured against the old purchase frequency.
- **(c)** Real effects at z 3–5 fall under the single fixed threshold of 5.25.
- **False finds** come from three places:
  - ratio KPIs with small denominators, whose DiD averages daily ratios
  - substitution into neighbouring categories
  - controls contaminated by other large events

## Hard constraints
- **The detective stays blind.** At runtime it may use only the analyst tables, never the answer key, the story or the no-story twin. Twins and the answer key may be used only offline, to calibrate and evaluate.
- **Anchors may come only from treatment tables**: price-list validity dates and courier assignment changes. Never derive an anchor from an outcome KPI: `cancelled_at` spikes are outcomes, and a stock-out cannot anchor sales of the same SKU.
- **Every reported event keeps** a DiD-style number (relative DiD with a CI) and, ideally, the SQL that reproduces it.
- **Runtime stays under ~60 s** on a few cores. Use only numpy, pandas, statsmodels, scipy, ruptures and DuckDB; no new heavy dependencies.
- The working tree has uncommitted changes in `s2d/` and `tests/`. Build on them; do not revert them.
- Explain every new threshold and rule in `DECISIONS.md`, in the existing style. Keep it explainable to students.

## Step 0 — diagnostic (do first, about 1 h)
For each planted event in several story runs, compute the **oracle-located z**: the detective's own DiD and placebo z on the correct series, date and window. Compare it with the verifier's d. Report a table with these columns: event, verifier d, oracle z, current detective z, found yes/no, reason missed (gate, threshold, dating, not tested).

This tells which events lack power and which only lack a lower threshold. Use it to re-rank the steps below if the data disagrees with the report.

## Changes, in order of expected F1 gain per hour
Measure each change separately on story runs **and** their no-story twins (several seeds). Report TP, FP, F1 and twin false finds before and after. Keep a change only if F1 rises and the twin false-find rate stays at about 1 per year.

1. **Anchored family with its own α** (misses b and c; estimated +0.06 to +0.12 F1).
   - Build an anchor catalogue in DuckDB from price changes and courier changes only. Write the catalogue into the report before any test runs, as a pre-registration.
   - Give each anchor a fixed, one-sided outcome family:
     - price → orders and churn in the repriced category, lags 14/28/42
     - courier → late share, rating and churn
   - Per anchor, take the max over outcomes × lags. Calibrate it against the same statistic at random non-anchor dates by reusing the placebo machinery.
   - Split the budget with Bonferroni or weighted Holm: α_A ≈ 0.1 of the yearly false-alarm budget for anchors, the rest for exploration. Optionally add a gatekeeping cascade, where a confirmed orders drop passes its α on to churn.
   - Exclude categories repriced within ± the window from the control.
   - Redefine churn onset after a rate change: first find when the segment's purchase rate steps down, then measure each customer's gap against the **new** rate.
   - Fix `lag_search` so it no longer applies |t| ≥ 3 to a max without correcting for multiplicity.
2. **Ratio KPIs from pooled counts** (false finds; estimated +0.04 to +0.07).
   - Compute the DiD as a pooled log-odds ratio (or a Poisson rate ratio for ticket rates) from 28-day sums of numerator and denominator.
   - Scale it by the overdispersion φ, estimated as Pearson χ²/df from a quasi-binomial GLM with day-of-week terms.
   - Require at least ~10 expected events and ~10 expected non-events per window.
   - For ratings, add a binomial KPI "share of reviews ≤ 2★".
3. **Substitution and contaminated controls** (false finds; estimated +0.03 to +0.07).
   - Add a rule: a positive shift in a neighbouring category that starts at the same time as a stock-out or shock, and is no larger than the loss, is substitution, not a new event.
   - Drop donors that have their own flagged window from the control. Report the estimate with and without them.
4. **Placebo max-T threshold per tree level** (miss c; estimated +0.03 to +0.08).
   - Replace the fixed 5.25 with a Westfall–Young max-T threshold: the upper quantile, over placebo dates (thinned to every 7th day), of the largest |z| across all series in the level.
   - Compute it separately for levels 0/1 and for pairs, recomputed on each dataset so no twin is needed at runtime.
   - Check on twins that the false-alarm rate holds.
5. **Pairs without the parent gate** (miss a; estimated +0.02 to +0.07). Do a 30-minute injected-effect power check first, and implement only if it shows power.
   - Test all depth-2 city × channel cells directly. Use an expectation-based Poisson or negative-binomial window score with a DiD-shaped baseline: the cell's pre-period share × the rest-of-population actuals.
   - Take candidates from the ramp template with lengths 7/14/21/30.
   - Give pairs their own max-T family, and deduplicate to the narrowest explaining node.

## Stop rule
Stop tuning once both of these hold:
- the remaining missed events without an anchor have an oracle z below about 4
- twins show at most 2 false finds per run

Beyond that point, every gain in recall is paid for with false finds, so it is the information limit. The report puts the realistic ceiling at F1 ≈ 0.68–0.74 with anchors and about 0.61 without them.

## Deliverables
- Code changes with tests in `tests/test_detective.py` and `tests/test_score.py`; all tests pass.
- The step 0 diagnostic table, and a before/after table per change across several seeds, with twin false-find rates.
- New `DECISIONS.md` entries.
- A short summary of what was kept, what was dropped and why, and how far the result is from the stop rule.
- Do not commit until I review.
