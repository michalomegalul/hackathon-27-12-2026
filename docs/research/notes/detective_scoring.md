# Blind Detective: Statistical Toolkit and Objective Recovery Score

## Changepoint detection: which library and settings for ~700-point daily KPI series?

### Takeaway
Use `ruptures` (latest PyPI 1.1.10, uploaded 2025-09-10) with PELT or Binseg, an L2/"rbf" cost, and a BIC-style penalty (about `2*sigma^2*log(n)` on the standardized series). In the largest independent benchmark (TCPDBench), plain binary segmentation with default settings scored best on univariate series. Prophet's changepoints scored near the bottom, and a "no changepoints" baseline beat many methods, which shows that false positives are the main failure mode.

### Cited Findings
- `ruptures` latest release on PyPI is 1.1.10 (uploaded 2025-09-10), from the PyPI JSON API (`https://pypi.org/pypi/ruptures/json`, queried 2026-11-24). A Rust port also exists. — [PyPI ruptures](https://pypi.org/project/ruptures/); [ruptures-rs](https://pypi.org/project/ruptures-rs/)
- TCPDBench (van den Burg & Williams): 37 real series plus 5 quality-control series, each annotated by 5 people. Average length is 327.7 points (max 991), so it is close to the 700-point daily-KPI regime. — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)
- Default-parameter results (univariate, Cover / F1): binseg 0.672/0.698, pelt 0.652/0.674, amoc 0.668/0.653, bocpd 0.594/0.662, prophet 0.522/0.472, **zero (no changepoints) 0.566/0.645**. kcpa scored 0.069/0.124 and wbs 0.264/0.365. — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)
- Oracle (grid-searched) results: bocpd 0.783/0.886, binseg 0.774/0.873, pelt 0.772/0.864, prophet only 0.554/0.502. — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)
- The authors say "the zero method outperforms many of the other methods, especially in the Default experiment … suggests that many methods return a large number of false positives". For Prophet, "only the maximum number of change points can be tuned … insufficient to achieve competitive performance". — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)
- Conclusion: binseg performs best on univariate series with default parameters, but it is not statistically significantly different from several others (segneigh, rfpop, pelt). With tuning, bocpd wins, again without a significant margin. — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)
- TCPDBench evaluation: F1 with margin M=5 (only one true positive per true changepoint, to avoid double counting) and the segmentation covering metric. Series are standardized to zero mean and unit variance. — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3); [TCPDBench GitHub](https://github.com/alan-turing-institute/TCPDBench)
- BIC penalty for L2 cost is `sigma^2 * log(T)` per change. AIC is `2*sigma^2` per change. — [Truong, Oudre, Vayatis, "Selective review of offline change point detection methods"](https://arxiv.org/pdf/1801.00718)
- Penalty design is discussed in the ruptures repository. — [ruptures discussion #131](https://github.com/deepcharles/ruptures/discussions/131)
- The `hildensia/bayesian_changepoint_detection` repository has a pending PR benchmarking it on TCPD, so the package is still maintained enough to receive benchmark contributions. — [GitHub PR #107](https://github.com/hildensia/bayesian_changepoint_detection/pull/107)

### Inferences
- **Recommended recipe for each daily KPI series:**
  1. Remove weekly seasonality first, for example STL with `period=7, robust=True`, then work on trend+residual. Alternatively aggregate to weekly values.
  2. Standardize the series robustly: (x - median) / (1.4826 * MAD).
  3. Run `rpt.Pelt(model="l2", min_size=7, jump=1).fit(y).predict(pen=k*np.log(n))` with k in about [2, 4]. On 700 points this runs in milliseconds.
  4. As a cross-check, run `rpt.Binseg(model="l2").predict(pen=...)`. Keep only breaks that both methods find (within ±3 days).
- Use `model="l2"` for level shifts such as a price increase or a churn level. Use `model="rbf"` or `"normal"` when variance also changes. Treat short spikes (a viral campaign, a stockout) as anomalies, not changepoints, because PELT with `min_size=7` will place two breaks around them.
- Skip Prophet for detection. It was among the worst methods in TCPDBench, and its changepoints are trend-slope knots, not level shifts.
- A good demo talking point: "a detector that says nothing beats most detectors", so we report false-positive control (see the null test below).
- Scale: one series of n=700 runs in under 10 ms with PELT and L2 cost. Expected cost is linear, and quadratic in the worst case. With 50 segments × 10 KPIs = 500 series, a full scan takes a few seconds.

### Gaps
- `changepoint_online`: I found no current release information. I did not verify it.
- I did not benchmark run times locally, because ruptures is not installed in this environment. The millisecond figures above are an expectation, not a measurement.

## Anomaly detection: PyOD vs STUMPY vs robust z-score/STL vs Isolation Forest

### Takeaway
For a 24-hour build, use STL decomposition with `robust=True`, then a robust z-score (median/MAD) on the residual, with threshold |z| > 3.5 and a minimum run length. This is transparent, deterministic, and fast. Keep STUMPY (matrix-profile discords) as an optional "shape anomaly" detector. PyOD is overkill for univariate KPIs, but it is the default if you need multivariate per-row outliers (orders, tickets).

### Cited Findings
- PyOD 3.6.9 (released 2026-11-22) has 61 detectors across tabular, time-series, graph, text, image and audio data, and keeps the classic fit/predict API. V3 adds "ADEngine" for automatic detector selection, plus an agentic "od-expert skill" and MCP tools for Claude Code / Codex. — [PyPI pyod](https://pypi.org/project/pyod/)
- STUMPY 1.14.1 (released 2026-02-08, Python 3.10+) computes the matrix profile, the nearest-neighbour distance for every subsequence. It supports motif discovery and discord (anomaly) discovery and depends on NumPy, Numba and SciPy. — [PyPI stumpy](https://pypi.org/project/stumpy/)

### Inferences
- **Stockout:** sales of a SKU or category drop to about 0 for k consecutive days while traffic or views stay normal. Detect it as a run of residual z < -3.5 lasting ≥3 days, or directly as zero units for ≥3 days on a SKU with a non-zero baseline.
- **Viral spike:** a run of residual z > +4 lasting ≥1 day, with decay afterwards. Report the peak date and the full width at half maximum.
- **Isolation Forest / PyOD:** use them only on entity-level feature tables, for example per customer per month. They add little to a univariate daily KPI.
- **STUMPY:** the Numba JIT compile on first call adds seconds. Warm it up before the live demo. For n=700, use window m=7 or 14.

### Gaps
- I did not find a head-to-head benchmark of STL+MAD vs matrix profile on short business KPIs.

## Segment drill-down / root cause: which segment drives the change?

### Takeaway
Implement a simple Adtributor-style drill-down. For each dimension (city, category, channel, tier), compare the before-window and after-window around a detected changepoint. Score each segment value by **explanatory power** (its share of the total delta) and **surprise** (JS divergence between expected and observed share). Report the dimension with the most concentrated explanation, then confirm the finding with a difference-in-differences effect estimate against the other segments. DoWhy-gcm `distribution_change` is the "causal" upgrade if you have a graph.

### Cited Findings
- Adtributor (Microsoft Research, NSDI 2014) uses explanatory power, succinctness and surprise to find the dimension most likely to blame for a change in a fundamental or derived measure. — [Microsoft Research paper](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/main-14.pdf); [USENIX](https://www.usenix.org/node/179770)
- Adtributor sorts values within each dimension by Jensen-Shannon divergence between real and expected values. It stops by cumulative explanatory power thresholds (T_EEP = 0.3 per element, T_EP = 0.8 cumulative). It assumes the root cause lies in a single dimension. "Recursive Adtributor" calls it repeatedly to handle multi-dimension causes. — [CMMD, arXiv 2203.16280](https://ar5iv.labs.arxiv.org/html/2203.16280)
- RiskLoc is a later method for multi-dimensional root-cause localization by weighted risk. — [arXiv 2205.10004](https://arxiv.org/pdf/2205.10004)
- DoWhy `gcm.distribution_change(causal_model, data_old, data_new, target)` swaps causal mechanisms fitted on old and new data one node at a time. It attributes the change in the target's distribution to each node with Shapley values (KL divergence by default). `distribution_change_robust` attributes mean changes. — [DoWhy docs](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/root_causing_and_explaining/distribution_change.html)

### Inferences
- **Concrete algorithm (about 40 lines of pandas):**
  - Take changepoint τ, pre window [τ-W, τ), post window [τ+L, τ+L+W). Use W=28 and lag L in {0, 7, 14, 28, 42} days, so the drill-down can test lagged effects such as "price increase → churn after 6 weeks".
  - For each dimension d and value v: Δ_v = post_v − pre_v and EP_v = Δ_v / Δ_total.
  - Surprise is the JS divergence between pre-share p_v and post-share q_v.
  - Pick the dimension whose top 1–2 values reach EP ≥ 0.8 with the highest summed surprise.
  - Confirm with DiD: (post_v − pre_v) − (post_rest − pre_rest). Get a CI from a block bootstrap over days (7-day blocks).
- **Lagged cause → effect** (price increase in segment X, churn later): find a changepoint in the price series and one in the churn series. Search lags with cross-correlation of the first differences, or by fitting the DiD at each candidate lag and taking the maximum |t|.
- DoWhy gcm needs a causal graph and fits models. Use it for a single "explain this KPI" slide only, not as the main pipeline, because it is slower and harder to explain to judges.
- ThirdEye (LinkedIn) and WhyLabs: not researched in depth here. Adtributor plus DiD covers the need.

### Gaps
- I did not check whether ThirdEye or WhyLabs offer a reusable local Python library for this.

## How do LLM data-analysis benchmarks score planted insights?

### Takeaway
InsightBench plants insights with explicit generators and scores recall-only matching (LLaMA-3-Eval G-Eval plus ROUGE-1). Later work (InsightEval) criticizes this and adds precision and F1. DiscoveryBench uses a structured multiplicative score (context × variables × relation). BLADE matches structured analysis decisions. DSBench uses exact-answer accuracy. Lesson for us: plant structured events and score them with structured, deterministic matching, using an LLM only to parse free text into slots.

### Cited Findings
- InsightBench (ICLR 2025): 100 datasets built from ServiceNow-style tables. Insights are planted with mathematical models, for example a time-to-resolution trend TTR = 1 + slope·(open_date − start_date). Insights are typed as descriptive, diagnostic, predictive or prescriptive. — [arXiv 2407.06423](https://arxiv.org/html/2407.06423v1)
- InsightBench scoring: each ground-truth insight is matched to its best (argmax) predicted insight by LLaMA-3-Eval (a G-Eval variant on LLaMA-3-70b), then averaged. The summary-level score compares summaries. ROUGE-1 is also reported. — [arXiv 2407.06423](https://arxiv.org/html/2407.06423v1)
- Criticism: InsightBench relies only on LLaMA-3-Eval, which risks evaluator bias. It counts matched ground-truth insights but ignores erroneous generated insights, so it has no precision. — [InsightEval arXiv 2511.22884](https://arxiv.org/html/2511.22884v2)
- InsightEval defines Recall = E_gt[max_i S(gt,i)], Precision = E_i[max_gt S(i,gt)], and F1 as their harmonic mean. It adds a novelty score validated by ≥2 of 3 LLM judges. — [arXiv 2511.22884](https://arxiv.org/html/2511.22884v2)
- DiscoveryBench: HMS = ctx_alignment × var_F1 × rel_acc (0–100). An LLM judge decomposes each hypothesis into "under context c, variables v have relationship r". — [arXiv 2407.01725](https://arxiv.org/pdf/2407.01725)
- BLADE (EMNLP 2024 Findings): 536 ground-truth analysis decisions across 12 datasets. It matches agent analyses to expert ground truth through data-flow graphs (transformations) and semantic matching (conceptual variables, models). — [arXiv 2408.09667](https://arxiv.org/html/2408.09667v2); [GitHub](https://github.com/behavioral-data/BLADE)
- DSBench (ICLR 2025): task-level accuracy on data-analysis questions. The best agent scored 34.12% vs 64.06% for humans. Modeling tasks use the Relative Performance Gap. — [arXiv 2409.07703](https://arxiv.org/pdf/2409.07703)

### Inferences
- The DiscoveryBench "context × variables × relationship" factorization maps directly onto our event slots: segment = context, metric = variable, direction/magnitude/date = relationship. The multiplicative form (a wrong segment zeros the credit) is a defensible precedent to cite to judges.
- Report precision as well as recall (the InsightEval criticism). Otherwise a detective that lists 50 events gets full marks.
- Avoid an LLM judge in the core score. If the detective outputs free text, have an LLM extract a JSON event schema, then score deterministically. Show the extracted JSON on screen.

### Gaps
- "DAgent" scoring was not researched. I found no source in this session.

## Designing the objective recovery score

### Takeaway
Score events, not text. Each story event becomes a structured tuple, and so does each detective claim. Pair them with Hungarian matching on a slot-similarity score. Report precision, recall and F1, plus a per-slot breakdown and the ruptures-style time-tolerance metrics. Calibrate with a null dataset (no story) and with placebo/permutation runs.

### Cited Findings
- `ruptures.metrics.precision_recall(true, pred, margin=10)` counts a true break as detected if a prediction lies within `margin` samples (default 10). `hausdorff` gives the worst-case localization distance and `randindex` gives segmentation agreement. — [ruptures docs](https://centre-borelli.github.io/ruptures-docs/user-guide/metrics/precisionrecall/)
- TCPDBench uses margin M=5 and allows only one true positive per true changepoint. It reports F1 together with covering, because they measure classification vs segmentation agreement. — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)
- In TCPDBench quality-control series, all human annotators placed known changepoints within 3 time steps, which supports a tolerance of a few steps. — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)

### Inferences (proposed design)
- **Event schema:** `{type ∈ {level_shift, spike, outage/stockout, trend_change, lagged_effect}, metric, segment {dim: value}, start_date, end_date?, direction ∈ {+,-}, magnitude_pct, cause_event_id?, lag_days?}`.
- **Pair score** s(gt, pred) ∈ [0, 1], with gates and weights:
  - Gate: same metric family and same direction, or s = 0. These are binary and easy to explain.
  - Timing: t = max(0, 1 − |Δdays| / τ) with τ = 7 days for shifts and τ = 2 days for spikes. Matching works like the ruptures margin, but with partial credit.
  - Segment: Jaccard of the predicted vs true segment sets. An exact city earns 1, "all cities" earns 1/|cities|.
  - Magnitude: m = max(0, 1 − |log(pred_effect / true_effect)| / log 2), so full credit at exact value and 0 at a factor of 2 off.
  - Combination: s = gate × (0.4·t + 0.4·seg + 0.2·m).
  - Causal-link bonus for lagged events: +credit if the cause is correctly linked and the lag is within ±7 days.
- **Matching:** run Hungarian assignment (`scipy.optimize.linear_sum_assignment`) on −s, so each prediction matches at most one GT event, as in TCPDBench's no-double-count rule. A pair counts as TP if s ≥ 0.5.
- **Reported numbers:**
  - Recovery Precision = Σ s_matched / |pred|.
  - Recovery Recall = Σ s_matched / |GT|.
  - Recovery F1 = harmonic mean of the two, as in InsightEval but deterministic.
  - Per-slot breakdown: date hit-rate, segment hit-rate, median |Δdays|, median magnitude error.
  - Raw changepoint P/R from `ruptures.metrics.precision_recall` (margin=7) and Hausdorff in days, as a familiar sanity metric.
- **Null / control test (critical for credibility):**
  1. **No-story twin:** generate the same world with the same seed and no injected events. Run the detective and report false events per year. Target ≤ 1. Precision on the twin is undefined, so show the false-alarm count.
  2. **Placebo dates:** shuffle event dates or plant "fake GT" at random dates, and score the detective's real output against them. The F1 against random placebo GT gives a chance baseline. Show the real F1 against the histogram of 200 placebo F1s and report an empirical p-value.
  3. **Seed sweep:** run 20 seeds × {story, no-story} and show a 2-row box plot. This takes seconds if each run is under 2 s.
  4. Also show the "zero detector" baseline (predicts nothing → F1 = 0, FP = 0) and a "spray" baseline (predicts a changepoint every 30 days). This mirrors TCPDBench's lesson that trivial baselines are strong.
- **SNR calibration (non-trivial but feasible):**
  - Define each event's effect in noise units: d = effect / (σ_noise of the segment-level daily series). For segment-level level shifts, d ≈ 1–1.5 per day over ≥4 weeks is invisible to the eye on the raw aggregate. CUSUM/PELT on the segment series still recovers it, because the pooled SNR grows with √(duration).
  - Dilute by segment share. A 20% churn rise in a city that is 10% of customers is a 2% aggregate change, invisible at top level and obvious after drill-down. This is the "detective" moment.
  - Add realistic confounders: weekly seasonality, holidays, a decoy one-day spike, and a gradual trend. The detector then has to discriminate, and the null test shows it does not cry wolf.
  - Sweep a difficulty knob (effect size d ∈ {0.25, 0.5, 1, 2}) and plot recovery F1 vs d. This gives a "detection curve" judges understand, with a 50% recall point at roughly d ≈ 0.5–1 (to verify empirically).

### Gaps
- No published standard exists for "story-recovery" scoring of planted business events. The formula above is a synthesis of the TCPDBench margin/no-double-count rules, InsightEval P/R/F1 and the DiscoveryBench factorization. Its weights (0.4/0.4/0.2) and τ values are design choices, not literature values.
- I did not measure the detection-curve thresholds (d values). Verify them with a quick simulation during the build.
