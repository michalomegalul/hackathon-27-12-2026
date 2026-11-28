# Anomaly and change detection for ratio KPIs with small daily denominators

Scope: late-delivery share, mean review rating, repeat rate and ticket rate per order, per city or per courier per day, with about 10–50 events per day. The current pipeline (s2d/detective/scan.py) runs STL(period 7, robust), then MAD z, then PELT on z, then DiD on daily ratio means with a 7-day block bootstrap and placebo z >= 5.25. `KPISet.parts` already stores (numerator, denominator) per (kpi, segment), so count-based methods can be added without new data plumbing.

**Recommended set (2–4 methods), in priority order:**
1. **Binomial GLM baseline with day-of-week and trend terms, plus a quasi-binomial dispersion φ.** Scale residuals as Pearson (or randomized quantile) residuals divided by √φ. This replaces STL + MAD z for ratio KPIs.
2. **Funnel-plot / Laney p′ limits with overdispersion adjustment.** A multiplicative φ or an additive τ² gives each day (or week) limits that widen when n is small. This is the "is this one point unusual" test.
3. **Binomial/Poisson log-likelihood change-point cost** (a custom `ruptures` cost or a Bernoulli/binomial CUSUM), so that PELT weights each day by its n.
4. **Pooled-count DiD:** sum the numerator and denominator over 28-day windows (a ratio of sums, not a mean of daily ratios), use a binomial/quasi-binomial likelihood-ratio or log-odds-ratio z, and inflate it by φ. Mean rating goes to a binomial "share of ≤2 stars" KPI or a count-weighted mean, with empirical-Bayes shrinkage and minimum-count gating.

---

## 1. Binomial / beta-binomial residuals and quasi-likelihood GLM as a replacement for STL + MAD z

### Takeaway
Fit a binomial GLM per ratio series: successes = late deliveries, trials = deliveries, logit link, with day-of-week dummies plus a smooth or piecewise trend. Estimate the extra-binomial dispersion φ from the Pearson χ²/df ("quasi-binomial"). Then use Pearson residuals / √φ, or Dunn–Smyth randomized quantile residuals, as the z-series. Unlike a MAD z on raw ratios, this puts a 2/10 day and a 20/100 day on the same noise scale. That is exactly the false-alarm mechanism described in the brief.

### Cited Findings
- statsmodels GLM accepts a binomial response as a 2-column array (successes, failures), or as proportions with `var_weights`/`n_trials`. Pearson residuals use `var_weights` and `n_trials`. `freq_weights` are equivalent to repeating records, while `var_weights` are equivalent to aggregating data. — [statsmodels GLM source](https://www.statsmodels.org/stable/_modules/statsmodels/genmod/generalized_linear_model.html); [statsmodels weighted GLM notebook](https://www.statsmodels.org/v0.14.4/examples/notebooks/generated/glm_weights.html)
- Binomial and Poisson families have a fixed scale = 1 by default. With variance weights, loglike/deviance are quasi-likelihood based. (`GLM.fit(scale="X2")` uses the Pearson χ²/df estimate. This is the documented `scale` option of `GLM.fit`, but I did not fetch that docstring page in this session.) — [statsmodels GLM docs](https://www.statsmodels.org/dev/generated/statsmodels.genmod.generalized_linear_model.GLM.html)
- Randomized quantile residuals (Dunn & Smyth 1996, *J. Comput. Graph. Stat.* 5(3):236–244, DOI 10.1080/10618600.1996.10474708). Each response is mapped through its fitted CDF and then through the standard-normal quantile. For discrete responses a uniform draw is taken inside the CDF jump, so the residuals are continuous and exactly N(0,1) under a correct model. — [Smyth publication page](https://gksmyth.github.io/pubs/residual.html); [preprint PDF](https://gksmyth.github.io/pubs/residual.pdf); [USC record](https://research.usc.edu.au/esploro/outputs/journalArticle/Randomized-quantile-residuals/99449465702621)
- Dunn & Smyth's motivation: ordinary (Pearson/deviance) residuals "can be of little use" in logistic or log-linear models, and discrete data create spurious parallel bands in residual plots. — [Smyth publication page](https://gksmyth.github.io/pubs/residual.html)
- Caveat: a later paper notes Dunn & Smyth gave no proof of normality or simulation study. — [arXiv 1708.08527](https://www.arxiv.org/pdf/1708.08527)
- Reference implementation: R `statmod::qresiduals`. — [statmod docs](https://search.r-project.org/CRAN/refmans/statmod/html/qresiduals.html)

### Inferences
- **Why it cuts false finds.** A MAD z of the daily ratio assumes constant variance. With binomial noise the variance is p(1−p)/n, so days or segments with n≈10 produce |z|>4 by chance much more often than days with n≈50. The GLM Pearson residual (y − n·p̂)/√(n·p̂(1−p̂)) removes this. Dividing by √φ also absorbs genuine extra-binomial day-to-day variation (weather, courier mix). Without φ, the binomial model would be *too* tight and would raise false alarms of its own; this is the Laney/Spiegelhalter point below.
- **Quantile residuals vs Pearson.** At n≈10 and p≈0.1 the Pearson residual is strongly skewed: one late delivery out of 10 is fine, three out of 10 gives z≈2.1, and zero gives z≈−1. Randomized quantile residuals are better calibrated in the tails. Implementing them takes about 3 lines of `scipy.stats.binom.cdf` plus `rng.uniform` (with a fixed seed for repeatability). For a deterministic alternative, the mid-p version (u = F(y−1) + 0.5·f(y)) avoids randomness. This is my suggestion; I did not find it in the sources fetched.
- **Beta-binomial version.** Instead of a quasi-likelihood, fit p ~ Beta(μ, ρ) per series by method of moments (ρ = intra-class correlation, φ ≈ 1 + (n−1)ρ). Then φ grows with n, which is more realistic than a constant φ when n varies a lot (as with the additive τ² below). For students, quasi-binomial φ is simpler to explain.
- **Formula sketch (for the report):** `X = [1, dow dummies(6), t/T, maybe spline(t, df=4)]`, `GLM(np.c_[k, n-k], X, family=Binomial()).fit(scale="X2")`, then `z = resid_pearson / sqrt(scale)`. Mean rating becomes a Gaussian GLM with `var_weights=n_reviews` (see section 4). Ticket rate per order becomes Poisson with `exposure=orders`. Note that the trend term must not absorb the step you want to detect. Either fit the baseline only on a pre-period, or keep the trend low-order (linear plus yearly harmonic) so PELT still sees steps in the residuals.
- **Compute cost:** one IRLS fit with about 670 rows and fewer than 15 columns takes about 2–5 ms. For 300 series that is about 1–2 s, cheaper than or comparable to STL(robust).

### Gaps
- I found no peer-reviewed head-to-head comparison of "GLM Pearson/quantile residual + changepoint" against "STL + MAD z" for small-count ratio series. The benefit argued above is analytic, not measured. It should be validated on the project's no-story twins (the same mechanism that set Z_REPORT=5.25).
- I could not verify the exact `scale="X2"` docstring text in this session.

---

## 2. Funnel plots, overdispersion-adjusted control limits, p-charts / Laney p′, daily vs weekly aggregation

### Takeaway
Funnel plots (Spiegelhalter 2005) and Laney p′ charts are the standard answer to "small units look extreme by chance". Limits depend on n through the binomial SE, and are then inflated by an overdispersion factor estimated from the data: a multiplicative φ (Laney σ_z², Spiegelhalter φ) or an additive between-unit variance τ². Without that inflation, large-n points are falsely flagged. Without the n-dependence, small-n points are falsely flagged. The detective has both problems at once: a courier×city segment has small n, and the overall series has large n.

### Cited Findings
- Spiegelhalter D.J. (2005), "Funnel plots for comparing institutional performance", *Statistics in Medicine* 24:1185–1202, DOI 10.1002/sim.1970. Plots the indicator against precision with control limits around a target. Avoids the spurious ranking of caterpillar plots. — [Wiley DOI landing via zendy](https://zendy.io/title/10.1002/sim.1970); [FunnelPlotR README](https://packages.oit.ncsu.edu/cran/web/packages/FunnelPlotR/readme/README.html)
- Spiegelhalter D.J. (2005), "Handling over-dispersion of performance indicators", *Qual Saf Health Care* 14:347–351. Uses multiplicative and additive random-effects approaches. Overdispersion arises from insufficient risk adjustment and unmeasured unit-level factors, and without adjustment "many institutions" are wrongly flagged. The UK Healthcare Commission adopted it. — [PMC1744077](https://pmc.ncbi.nlm.nih.gov/articles/PMC1744077); [scilit record](https://scilit.com/publications/36e9234d1e79af3f90b17f8d0b9f0f65)
- FunnelPlotR implementation notes: φ is estimated from the excess of observed over expected variance. Z-scores are **winsorised at 10% at each end** before estimating φ/τ² so that true outliers do not inflate the limits. The overdispersion is applied additively (τ²). The Spiegelhalter variant uses a square-root transform plus winsorisation, and the SHMI variant uses a log transform plus truncation. In the README example, unadjusted Poisson limits flagged **25** outliers and adjusted limits flagged **9**. — [FunnelPlotR README (rdrr)](https://rdrr.io/cran/FunnelPlotR/f/README.md)
- Spiegelhalter et al. (2012), "Statistical methods for healthcare regulation: rating, screening and surveillance", *JRSS-A* 175(1):1–47, DOI 10.1111/j.1467-985X.2011.01010.x. Proposes a common standardisation via "possibly overdispersed Z-scores" and monitors more than 200,000 indicators for excess mortality. This is the closest published analogue to scanning hundreds of KPI × segment series. — [RePEc](https://ideas.repec.org/a/bla/jorssa/v175y2012i1p1-47.html); [Nuffield Trust](https://nuffieldtrust.org.uk/research/statistical-methods-for-health-care-regulation-rating-screening-and-surveillance)
- Laney p′ chart. Compute z_i = (p_i − p̄)/√(p̄(1−p̄)/n_i). Estimate σ_z = mean moving range of z / 1.128. Limits are p̄ ± 3·σ_{p_i}·σ_z. If the data are purely binomial, σ_z≈1 and p′ equals the p-chart. With equal n, p′ equals an XmR chart. — [Laney, Quality Digest 2007](https://www.qualitydigest.com/feb07/departments/what_works.shtml)
- Traditional p-chart limits narrow as n grows, so overdispersion makes in-control large subgroups look out of control. Minitab's P-chart diagnostic flags overdispersion when observed/expected variation exceeds a 95% upper limit. In its example (n≈2,500) the p-chart flags several points while the Laney p′ chart flags none. — [Minitab support](https://support.minitab.com/minitab/help-and-how-to/quality-and-process-improvement/control-charts/supporting-topics/understanding-attributes-control-charts/overdispersion-and-underdispersion); [Minitab blog](https://blog.minitab.com/en/understanding-statistics/ready-for-prime-time-use-p-and-u-charts-to-avoid-false-alarms)
- Mohammed & Laney (2006) applied p′ to hospital readmission proportions in *Qual Saf Health Care* 15(5):383. — [BMJ QS PDF](https://qualitysafety.bmj.com/content/qhc/15/5/383.full.pdf) (full text was 403 to the fetcher; the claim comes from the search snippet)
- More recent work: beta-binomial p-type charts were compared against p and Laney p′ and reported as more useful under overdispersion ([KoreaScience 2017](https://koreascience.kr/article/JAKO201721948860093.page?lang=ko)). Laney p′ assumes that overdispersion comes from sample-to-sample variation in the true fraction ([Mathematics/MDPI 2023, DOI 10.3390/math11153411](https://doi.org/10.3390/math11153411)). Beta regression control chart for fractions ([arXiv 1804.01454](https://arxiv.org/pdf/1804.01454)).

### Inferences
- **Formulas (standard, as restated in the Spiegelhalter 2005 papers; I could not fetch the full text here to re-verify every symbol).** For unit/day i with target p₀ and s_i = √(p₀(1−p₀)/n_i), compute z_i = (y_i − p₀)/s_i. Then φ̂ = (1/I)·Σ z_{w,i}², with z winsorised at 10%/90%.
  - Multiplicative: the limits become p₀ ± z_α·√φ̂·s_i.
  - Additive: τ̂² = (I·φ̂ − (I−1)) / (Σw_i − Σw_i²/Σw_i), with w_i = 1/s_i². The limits become p₀ ± z_α·√(s_i² + τ̂²).
  - The additive version is better when n varies a lot: for large n the limit tends to ±z·τ instead of collapsing to 0.
- **Use in this pipeline.** Apply it in two places.
  - (a) **Across days within one series:** the funnel / Laney limit is the "is this day a spike" test, replacing the |MAD z| > SPIKE_Z rule in `despike`.
  - (b) **Across segments for one window (true funnel plot):** the after-vs-before log-odds ratio of each courier×city is plotted against its count. Only segments outside the τ²-adjusted funnel are candidates. This is the hierarchical scan's "which segment moved" step. It controls the "smallest segment always wins" false-find pattern directly.
- **Daily vs weekly.** With n≈10/day, a daily binomial SE of p=0.1 is ≈0.095, about as large as p itself, so no daily point can be significant for realistic effects. Weekly sums (n≈70) give an SE of ≈0.036, and 28-day sums (n≈280) give ≈0.018. Spike detection at daily resolution on these segments is mostly noise. A practical rule: run spike/funnel tests on weekly sums for segments with median daily n < 30, and keep daily resolution only for overall/large segments. This is my inference from the binomial SE arithmetic, not taken from a source.
- **Compute cost:** O(n) vectorised numpy, under 1 ms per series.
- **Explainability:** high. "A funnel: small groups get wider limits; we widen all limits by how noisy the groups really are."

### Gaps
- I did not retrieve the full Spiegelhalter 2005 texts (PMC and BMJ blocked automated fetch), so the formulas above come from standard restatement plus the FunnelPlotR description, not a line-checked quote.
- I found no Python package equivalent to FunnelPlotR. It is a roughly 20-line numpy implementation.

---

## 3. Change-point detection for binomial / Poisson data; CUSUMs; likelihood-ratio DiD with pooled counts

### Takeaway
Replace "PELT on MAD z of the daily ratio" with PELT under a binomial (or Poisson-with-exposure) segment log-likelihood cost, computed from cumulative sums of k and n. The cost is O(1) per segment, and days with more trials automatically weigh more. The cost must be divided by φ (quasi-likelihood), otherwise overdispersion creates spurious breaks. For confirmation, test the DiD on pooled counts with a log-odds-ratio z or a likelihood-ratio statistic, again φ-scaled. Bernoulli and risk-adjusted CUSUM are the sequential counterpart and give an explainable per-event score.

### Cited Findings
- `ruptures` supports user-defined costs. Subclass `BaseCost`, implement `.fit(signal)` and `.error(start, end)`, set `model` and `min_size`, and pass the class to `Pelt(custom_cost=...)`. No built-in Poisson/binomial cost turned up in the docs. — [ruptures custom cost docs](https://centre-borelli.github.io/ruptures-docs/user-guide/costs/costcustom); [creating a custom cost](https://centre-borelli.github.io/ruptures-docs/custom-cost-function); [Truong et al., ruptures paper, arXiv 1801.00826](https://arxiv.org/pdf/1801.00826)
- R `changepoint` (v2.3, 2024) supports `test.stat="Poisson"` in `cpt.meanvar` with PELT (the default method) and requires non-negative integer data. PELT: Killick, Fearnhead & Eckley (2012) JASA, linear cost. — [changepoint manual](https://cran.r-project.org/web/packages/changepoint/refman/changepoint.html); [CRAN PDF](https://search.r-project.org/CRAN/packages/changepoint/changepoint.pdf)
- A C# library (SignalSharp) ships `BinomialLikelihoodCostFunction` (k successes out of n) and `PoissonLikelihoodCostFunction` for PELT, showing that the binomial cost is a standard construction. — [SignalSharp docs](https://emmorts.github.io/SignalSharp/api/SignalSharp.CostFunctions.Cost.html)
- Steiner, Cook, Farewell & Treasure (2000), "Monitoring surgical performance using risk-adjusted CUSUM charts", *Biostatistics* 1(4):441–452, DOI 10.1093/biostatistics/1.4.441. Details below. — [Waterloo PDF](https://uwaterloo.ca/statistics-and-actuarial-science/sites/default/files/uploads/documents/2000_risk_adjusted_cusum_biostats_0.pdf)
  - The CUSUM is X_t = max(0, X_{t−1} + W_t), and it signals at X_t ≥ h.
  - Log-likelihood-ratio weights are optimal (Moustakides 1986).
  - Bernoulli weights are W = log(c_A/c₀) for an event and log((1−c_A)/(1−c₀)) for a non-event.
  - Risk-adjusted version: with predicted risk p_t and odds ratios R₀ (null) and R_A (alternative), W_t = log[(1−p_t+R₀p_t)·R_A / ((1−p_t+R_A p_t)·R₀)] if y=1, else log[(1−p_t+R₀p_t)/(1−p_t+R_A p_t)].
  - h is chosen from the in-control ARL.
  - In their cardiac example, risk adjustment removed a false "worse than expected" signal for an experienced surgeon.
- The RA-CUSUM is the most commonly used risk-adjusted chart (2011 comparison, *Stat Med*). — [Waterloo 2011 PDF](https://uwaterloo.ca/statistics-and-actuarial-science/sites/default/files/uploads/documents/2011_ra-cusum_comparison_stats_in_med.pdf); [search summary](https://pmc.ncbi.nlm.nih.gov/articles/PMC1743380)
- Reynolds & Stoumbos (1999), "A CUSUM chart for monitoring a proportion when inspecting continuously", *J. Quality Technology* 31(1):87–108. A Bernoulli CUSUM on individual items detects shifts in p substantially faster than a p-chart on grouped samples or a CUSUM on sample statistics. Bourke (2001) proposed it independently. — [JQT DOI](https://informahealthcare.com/doi/full/10.1080/00224065.1999.11979900); [VT tech report](https://www.stat.vt.edu/content/dam/stat_vt_edu/graphics-and-pdfs/research-papers/Technical_Reports/TechReport08-3.pdf)

### Inferences
- **Binomial PELT cost (implementation sketch).** Precompute cumulative sums K and N. For a segment [a,b): k = K[b]−K[a], m = N[b]−N[a], p̂ = k/m. Then cost = −2·[k·log p̂ + (m−k)·log(1−p̂)], with 0·log0 = 0, divided by φ̂ from step 1. Add a BIC-type penalty, e.g. β = c·log(T) with c tuned on the no-story twins. Poisson with exposure (tickets per order): cost = −2·[k·log(k/m) − k] / φ̂. Mean rating: a Gaussian cost with weights n_i, i.e. Σn_i(r̄_i − r̄_seg)² / σ̂², where σ̂² is the within-review variance. Each `error` call is O(1), so PELT on 670 points in Python takes about 10–50 ms. Removing seasonality first: divide by the GLM day-of-week fitted p, or pass the GLM-adjusted expected counts E_i as an offset (cost on k vs E·λ, Poisson-style). This is risk adjustment in the Steiner sense, with "risk" = day-of-week + trend.
- **Why it helps.** With the current approach, a run of 3 days at n=8 with 3/8 late gets the same weight in PELT as 3 days at n=60. The likelihood cost gives the small-n days roughly 8/60 of the evidence. Combined with φ, this is the main power-preserving false-alarm reduction: large segments keep their sensitivity, and small segments stop producing breaks from noise.
- **Pooled-count DiD instead of mean of daily ratios.** For segment S and complement R, before window B and after window A (28 days each), sum the counts to get k_SB, n_SB, k_SA, ... Compute the effect δ = logit(p_SA) − logit(p_SB) − [logit(p_RA) − logit(p_RB)]. Its Var ≈ φ̂·Σ 1/(n·p(1−p)) over the 4 cells (the Woolf log-odds-ratio variance), and z = δ/√Var. Equivalently, take the likelihood-ratio test of the interaction term in a 4-cell quasi-binomial GLM. Averaging daily ratios weights n=8 days the same as n=60 days and inflates variance. The ratio-of-sums estimator is the MLE under a constant p. This is my inference, consistent with the GLM framework above. Keep the existing placebo-in-time z, but feed it this pooled statistic. The placebo distribution then also absorbs the residual autocorrelation the formula ignores, so the 5.25 threshold may be retunable downward without raising false finds. That needs testing.
- **CUSUM.** Useful as an explainable "evidence accumulator" per segment. The Bernoulli CUSUM per delivery is too fine-grained for a daily-batch detective. A per-day binomial CUSUM with W_d = k_d·log(R_A) − n_d·log(1−p_d+R_A·p_d) (the daily sum of the Steiner weights with R₀=1, and p_d from the GLM baseline) is equivalent and O(T). The detective is offline, so PELT is the primary tool and the CUSUM is optional, e.g. for the student-facing explanation "the score crossed h on day X".

### Gaps
- I found no published Python implementation of binomial or Poisson PELT costs in `ruptures` (custom code of about 20 lines is required).
- I found no source quantifying false-alarm reduction from a φ-scaled binomial cost vs a Gaussian cost on z-scores. It needs calibration on no-story twins.
- I did not retrieve a specific paper on "likelihood-ratio DiD for proportions". The pooled log-odds-ratio DiD above is standard 2×2×2 GLM interaction testing, not a named method from the literature searched.

---

## 4. Mean rating: binomial "low-rating share", ordinal models, empirical Bayes shrinkage, minimum-count gating

### Takeaway
Mean rating from 1–10 reviews a day has very high variance, and a few 1-star reviews swing it. The two cheapest robust options are:
- (a) turn rating into a binomial KPI ("share of reviews ≤ 2 stars", or ≥ 4) and reuse the whole binomial pipeline above;
- (b) keep the mean but weight days by review count, with σ² estimated from individual reviews.

For small segments, shrink segment rates toward the parent (beta-binomial empirical Bayes, James–Stein). Gate any segment-day test on a minimum expected count.

### Cited Findings
- Efron & Morris (1975, *JASA*) used James–Stein shrinkage on batting averages from 45 at-bats of 18 players to predict the rest-of-season averages. They used an arcsine variance-stabilising transform so that the binomial estimates have about unit variance. — [Efron & Morris 1975 PDF (McGill)](https://www.medicine.mcgill.ca/epidemiology/hanley/bios602/MultilevelData/EfronMorrisJASA1975.pdf)
- Brown (2008, *Ann. Appl. Stat.*, DOI 10.1214/07-AOAS138) field-tested empirical Bayes and hierarchical Bayes estimators for batting averages. A nonparametric EB procedure performed best on the full data but less well on more homogeneous subsets. — [arXiv 0803.3697](https://arxiv.org/pdf/0803.3697); [DOI](https://doi.org/10.1214/07-aoas138)
- A Gaussian-prior EB on this data reduces MSE slightly but "enforces too strong shrinkage for the extremes". This is relevant because a true event *is* an extreme. — [arXiv 1709.04192](https://arxiv.org/pdf/1709.04192)
- Beta-prior (beta-binomial) EB fitted from the observed rates induces shrinkage. Informal tutorial, not peer-reviewed. — [M. Clark blog](https://m-clark.github.io/posts/2019-06-21-empirical-bayes)
- Spiegelhalter's additive τ² random-effects model (section 2) is itself a normal-normal EB model. Its shrunken estimate for unit i is w_i·y_i + (1−w_i)·p₀ with w_i = τ²/(τ²+s_i²). — [Spiegelhalter 2005 QSHC, PMC1744077](https://pmc.ncbi.nlm.nih.gov/articles/PMC1744077)

### Inferences
- **Binarise ratings.** "Share ≤ 2 stars" is a binomial KPI. It gets the GLM residuals, funnel, binomial PELT and pooled DiD for free, and it is easy to explain. A rating event in the sim (e.g. a quality drop) most likely moves the low tail. The binarised KPI loses some power if the sim shifts the whole distribution uniformly. Keeping both "mean (count-weighted)" and "≤2 share" is cheap, but adds tests and therefore multiplicity.
- **Ordinal (proportional-odds) model.** statsmodels has `statsmodels.miscmodels.ordinal_model.OrderedModel`, a cumulative logit with a shift parameter for "after" × "segment". It is the most efficient single test for a shift in a 1–5 rating. It is fine for one confirmatory DiD per candidate, but too slow and complex for scanning all series. I did not fetch its docs in this session.
- **Count-weighted mean.** For the daily mean rating r̄_d with n_d reviews, Var(r̄_d) = σ²/n_d, where σ² is the per-review variance (about 1–1.5 on a 1–5 scale). The z for a window is Σn_d(r̄_d − μ) / (σ·√Σn_d·√φ). This alone removes the "3 reviews gave 1.0" spikes.
- **EB shrinkage in the scan.** Before ranking segments (e.g. in `adtributor`, or when choosing which child segment explains a parent shift), replace raw segment effects with shrunken effects δ̂_i·τ²/(τ²+SE_i²). Tiny segments with huge raw effects then drop down the ranking unless their evidence is strong. Shrinkage should be used for ranking and attribution, not for the significance test itself: the funnel/z test already accounts for SE.
- **Minimum-count gating.** The existing MIN_EVENTS=30 is for total events. A better gate for a ratio series is on expected events in the test window: run the test only if n_window·p̂ ≥ ~10 and n_window·(1−p̂) ≥ ~10, the usual normal-approximation rule. Otherwise use exact binomial / LR tests or skip. With a 28-day window this is roughly 1–2 late deliveries a day at p≈0.1, n≈15/day. Also cap the reported effect size precision. The threshold numbers are conventional rules of thumb, not from a cited source here.

### Gaps
- I found no peer-reviewed source comparing "low-rating share" vs "mean rating" vs ordinal tests for detecting rating shifts with few reviews per day.
- I did not find an explicit peer-reviewed beta-binomial EB worked example in the searches. The beta-binomial MoM formula is standard textbook material, and only an informal tutorial was retrieved.

---

## 5. Compute cost and Python implementations

### Takeaway
All four recommended methods fit well inside the 60 s budget with numpy/scipy/statsmodels/ruptures. The heaviest piece is the GLM fit, at a few ms per series. The binomial PELT cost and funnel limits are O(T) with cumulative sums.

### Cited Findings
- PELT has linear expected cost when the number of changepoints grows with series length (Killick, Fearnhead & Eckley 2012), as cited in the R changepoint manual. — [changepoint manual](https://cran.r-project.org/web/packages/changepoint/refman/changepoint.html)
- `ruptures` custom costs plug into `Pelt` via `custom_cost`. — [ruptures custom cost docs](https://centre-borelli.github.io/ruptures-docs/user-guide/costs/costcustom)
- statsmodels GLM supports binomial 2-column responses, `var_weights`, `exposure`/`offset`, and Pearson residuals. — [statsmodels GLM source](https://www.statsmodels.org/stable/_modules/statsmodels/genmod/generalized_linear_model.html)
- Exact Markov-chain / diffusion approximations exist for Bernoulli CUSUM ARL. — [Reynolds & Stoumbos 1999 (JQT)](https://informahealthcare.com/doi/full/10.1080/00224065.1999.11979900)

### Inferences
Estimated costs for 300 series × 670 days (my estimates, not measured):

| Method | Python | Cost estimate |
|---|---|---|
| Quasi-binomial GLM, dow + trend, Pearson/quantile residuals | `sm.GLM(np.c_[k,n-k], X, family=sm.families.Binomial()).fit(scale="X2")`; `scipy.stats.binom.cdf` for quantile residuals | ~3 ms/series, about 1 s total |
| Funnel / Laney p′ limits (φ winsorised 10%, or τ²) | about 20 lines of numpy | <0.1 s total |
| Binomial/Poisson PELT cost (cumsum, φ-scaled) | `class CostBinom(rpt.base.BaseCost)` with `fit`/`error`; `rpt.Pelt(custom_cost=CostBinom(), min_size=7).fit(np.c_[k,n]).predict(pen=β)` | ~10–50 ms/series in pure Python, about 3–15 s total. Vectorise or reduce candidate breaks if needed |
| Pooled-count log-OR DiD + placebo-in-time | numpy sums over windows. The placebo needs one O(1) evaluation per placebo date using cumsums | negligible. Cheaper than the current 200× block bootstrap, which could be dropped for ratio KPIs |
| Ordinal model (confirmatory only) | `statsmodels.miscmodels.ordinal_model.OrderedModel` | ~50–200 ms per candidate |

- Replacing the block bootstrap (BOOT=200) with the analytic φ-scaled binomial variance for ratio KPIs probably *saves* time.
- Explainability for students: each method reduces to "expected count from a model, compare with observed count, widen by measured over-noise φ". That is one concept reused four times.

### Gaps
- Timing numbers are back-of-envelope estimates, not benchmarks on this codebase.
- I did not verify whether `ruptures`' Python loop overhead with a custom cost stays under 50 ms for T=670 at `min_size=7` and `jump=1`. If not, `jump=7` (weekly candidate breaks) cuts it by about 7×.
