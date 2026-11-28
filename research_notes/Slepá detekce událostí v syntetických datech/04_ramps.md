# Detecting and dating linear 7–30 day ramps in daily count series

Note on evidence: findings marked **[sim]** come from small simulations run for these notes (numpy/statsmodels/ruptures from the project's `uv` environment; scripts in the session scratchpad: sim2.py, sim3.py). They are illustrative, not peer-reviewed. Everything else has a link.

## Q1. How does STL (period 7, robust) affect ramp detection, and what should replace it?

### Takeaway
With period 7, statsmodels' default STL trend window is about 15 days. The trend takes in essentially all of a step *and* of a 7–30 day ramp, so the STL **residual** carries almost none of the planted effect. Change-point detection must run on the seasonally adjusted series (trend + residual, or the raw series divided by day-of-week factors), not on the residual alone. This is probably the biggest single cause of miss (a).

### Cited Findings
- statsmodels STL default: `seasonal=7`, and the trend window, when not given, is "the smallest odd integer greater than 1.5 * period / (1 - 1.5 / seasonal)". With period=7 and seasonal=7 that is 1.5·7/(1−1.5/7) ≈ 13.4, so trend = 15 days. Low-pass = smallest odd integer > period (= 9). — [statsmodels STL docs](https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.STL.html)
- STL works by iteration: it removes the seasonal part, smooths the remainder with LOESS to get the trend, and moves the level from the seasonal part into the trend. — [R stl docs](https://search.r-project.org/CRAN/refmans/stats/html/stl.html)
- RobustSTL authors: STL "cannot catch up with the abrupt trend changes" (it lags and smears them). — [Wen et al., RobustSTL, AAAI 2019 / arXiv 1812.01767](https://arxiv.org/abs/1812.01767)
- Decomposition methods "inadvertently incorporate" collective (multi-day) anomalies into the trend or seasonal components, which distorts the residuals. — [arXiv 2508.21128](https://arxiv.org/html/2508.21128v1)
- **[sim]** Poisson(150·DoW·(1−0.2·ramp)) series, 670 days, onset at day 400, 30 replications, `STL(period=7, robust=True)`:
  | ramp length L | true level drop | STL trend change | 28d-after − 28d-before mean of the **residual** (sd) |
  |---|---|---|---|
  | 0 (step) | −30 | −29.7 | −2.6 (2.2) |
  | 7 | −30 | −29.5 | −1.2 (2.5) |
  | 14 | −30 | −32.3 | −0.2 (2.6) |
  | 30 | −30 | −30.5 | −0.8 (2.5) |
  
  The residual keeps under 10 % of a step and almost nothing of a ramp.

### Inferences
- If the detective runs PELT on `resid` only, steps survive only as a short transient around the break (a few days of the 15-day LOESS window). Ramps of 14–30 days are smooth enough that the LOESS trend follows them almost exactly, so PELT on residuals cannot find them at any threshold. If the detective already uses trend+resid, this does not apply. Check `s2d/detective/scan.py`.
- Recommended preprocessing, simplest first:
  1. **Day-of-week factors only**: multiplicative DoW indices estimated robustly (median ratio of each weekday to a centred 7-day mean) over the whole series. Divide by them and keep trend and level changes in the series. This is easy to explain to students.
  2. **Cross-sectional reference (most important for this dataset)**: the winter peak, holidays, Black Friday and Christmas are shared across segments. Model each segment as log(y_seg) − log(y_reference), where the reference is the sum of the sibling segments, e.g. the other cities in the same channel, or the same city's other channel. This removes the shared seasonality without smoothing away the event, and it is a time-series form of the DiD the scorer already uses.
  3. If STL must stay, set a long trend window (e.g. `trend=181` or larger) so that a 30-day ramp is *faster* than the trend and remains in the residual, or detect on `trend + resid`.
- Holidays and Black Friday should be masked (set to NaN and interpolated, or given a dummy) before slope or ramp detectors run. Single-day spikes produce spurious kinks in piecewise-linear fits.

### Gaps
- I found no peer-reviewed paper that quantifies how much of a ramp STL's trend absorbs as a function of window length. The table above is my own simulation.

## Q2. Ramp-template matched filter / GLR scan (recommended detector #1)

### Takeaway
The likelihood-ratio statistic for "mean follows h(t; τ, L) = clip((t−τ)/L, 0, 1) times δ" is the correlation of the adjusted series with the centred ramp template, scanned over τ (every day) and a small L grid {1, 7, 14, 21, 30}. It is the optimal test for a known shape, it costs almost nothing, it is easy to explain ("slide a ramp-shaped stencil and see where it fits best"), and it dates the onset (τ̂) and ramp length (L̂) at the same time.

### Cited Findings
- Detection of a known-shape local signal in Gaussian noise by scanning a likelihood-ratio (matched filter) over location and scale, including sequential detection of slope changes, is treated in Siegmund and coauthors' work on local signal detection, which cites Krieger, Pollak & Yakir (2003) for slope changes. — [Detection and Estimation of Local Signals, arXiv 2004.08159](https://arxiv.org/abs/2004.08159)
- Hušková (1998): for a gradual (ramp-type) change in a location model, the change-time estimator converges at rate n^{1/2}δ_n^{-1}, against δ_n^{-2} for an abrupt change. Gradual changes are fundamentally harder to date, and the limit distribution differs from the abrupt case. — [Hušková, CMUC 39(1) 1998](https://dml.cz/handle/10338.dmlcz/118993)
- The same split appears online. For a jump the minimax localisation rate is log(n)/n. For a kink (slope change) it is (log n / n)^{1/3}. Kink detection uses a *weighted* mean of residuals from the pre-change line, with more weight on recent points, at O(1) cost per sample. — [Online jump and kink detection in segmented linear regression, arXiv 2503.05270](https://arxiv.org/html/2503.05270v2)
- Model of the gradual change used by Hušková (1999): μ(u) = μ̄ + δ·(u−u₀)^β·1(u>u₀) with known β ∈ [0,1]. — [cited in arXiv 1403.3808](https://arxiv.org/pdf/1403.3808)
- **[sim] Power arithmetic (noise sd = 1, 28-day pre window, unit drop δ).** z-score per unit δ of the current "28 d after vs 28 d before" contrast:
  | L | post window [0,28) | post window [L, L+28) |
  |---|---|---|
  | 1 (step) | 3.74 | 3.74 |
  | 7 | 3.21 (86 % of effect captured) | 3.74 |
  | 14 | 2.74 (73 %) | 3.74 |
  | 30 | **1.68 (45 %)** | 3.74 |
  
  A 30-day ramp scored with the current 28-day DiD from the true onset gives less than half the z of the same final drop as a step. A planted effect of about 4.5 "noise units" therefore lands near z ≈ 2, far below the 5.25 report bar.
- **[sim]** Correlation between the centred step template and the centred ramp template (±28 d window): 0.91 (L=7), 0.84 (L=14), 0.76 (L=30). Template-matched SNR per δ in the same window: 3.55 / 3.27 / 2.21, against 3.21 / 2.74 / 1.68 for the step template.
- **[sim] Cost.** 300 series × 670 days × 5 ramp lengths, with `np.correlate` per template: **0.03 s in total**.

### Inferences
- The biggest power gain is not a cleverer change-point method but **scoring the ramp with a ramp-aware contrast**: compare the 28 days before τ̂ with the 28 days after τ̂ + L̂, skipping the ramp. Alternatively, regress on the template and report δ̂/se. This recovers the full step-equivalent z (3.74δ) for every L. The placebo-in-time z must use the same (L̂, skip) contrast at placebo dates so that it stays calibrated. Choosing L̂ by maximum over the grid inflates the null, and the placebo distribution corrects for that only if each placebo also maximises over L.
- Minimal implementation, on DoW-adjusted, reference-normalised, holiday-masked log series `x` with robust noise scale σ (MAD of first differences / √2):
  ```python
  def ramp_scan(x, sigma, Ls=(1,7,14,21,30), W=28):
      best = (0, None, None)
      for L in Ls:
          pre  = -np.ones(W) / W
          post = np.clip(np.arange(1, W + L + 1) / L, 0, 1)   # ramp then plateau
          k = np.r_[pre, post]; k -= k.mean(); k /= np.linalg.norm(k)
          z = np.correlate(x, k, 'valid') / sigma              # z[i] -> onset at i+W
          i = np.argmax(np.abs(z))
          if abs(z[i]) > abs(best[0]): best = (z[i], i + W, L)
      return best   # (z, onset index, ramp length)
  ```
  Serial correlation in residuals inflates z. Calibrate with the existing placebo-in-time distribution, not a nominal N(0,1).

### Gaps
- No paper found that gives a closed-form power comparison of a ramp scan against PELT-on-residuals specifically. The numbers above are my own arithmetic and simulation.

## Q3. Hockey-stick / segmented regression with Davies test, and onset dating with a CI (recommended for dating)

### Takeaway
Once a candidate window is flagged, fit a local "flat → linear ramp → flat" (or the simpler continuous broken-line) model by grid search over the onset. The kink τ̂ is the onset estimate. A profile-likelihood or bootstrap interval over τ gives a CI, and the Davies test gives a p-value that is valid although the breakpoint is not identified under the null. In simulation this cut the onset error from about 15 days (step PELT) to about 5 days.

### Cited Findings
- `piecewise-regression` (Pilgrim 2021, JOSS 6(68):3859) is a Python implementation of Muggeo's iterative segmented-regression method. It gives breakpoint estimates with standard errors and confidence intervals, bootstrap restarting, and a **Davies test** for the existence of at least one breakpoint (a Wald statistic on the change in gradient, after Muggeo 2008). It installs with `pip install piecewise-regression`, and the main call is `Fit(x, y, n_breakpoints=k)`. — [JOSS paper](https://joss.theoj.org/papers/10.21105/joss.03859.pdf); [GitHub](https://www.github.com/chasmani/piecewise-regression); [docs](https://piecewise-regression.readthedocs.io/)
- Classic theory of two-phase / broken-line regression: Hinkley (1969, 1971) gives confidence intervals for the change point and joint regions, and notes that the change point is unidentifiable under the one-line null. Feder (1975) gives the asymptotics of the least-squares estimator. — [lm.br vignette (summary of the literature)](https://search.r-project.org/CRAN/packages/lm.br/vignettes/lm.br.pdf)
- R `segmented` provides the Davies test and a pseudo-score test that does not require fitting the segmented line. — [segmented manual](https://search.r-project.org/CRAN/packages/segmented/segmented.pdf)
- Bent-cable regression (Chiu et al.) relaxes the abrupt kink to a smooth quadratic bend. It is relevant if onsets are soft. — [Chiu, Lockhart & Routledge, JASA 2006](https://faculty.washington.edu/gchiu/Articles/bentcable-jasa.pdf)
- Fitting a single change to data that hold a slope change tends to place the change **near the middle** of the sloped section. — [Fearnhead & Grose, cpop JSS paper, arXiv 2208.11009](https://ar5iv.labs.arxiv.org/html/2208.11009), citing Baranowski et al. 2019
- **[sim] Onset dating on a 30-day ramp** (drop 1.34 σ, sized so that a step would give z ≈ 5; onset day 400; 100 replications; white noise):
  | method | median error | MAE | 90th pct abs error |
  |---|---|---|---|
  | PELT `l2` (mean shift) | **+15 d** (midpoint of ramp) | 15.8 d | 25 d |
  | ramp-template grid least squares (τ ∈ 300–500, L ∈ {7,14,21,30}) | +4.5 d | 6.7 d | 13 d |
  | PELT `clinear` (ruptures) | 0 d | 14.3 d | 30 d |

### Inferences
- The systematic misdating seen in the system (an onset reported about half a ramp late) is what a mean-shift detector should produce on a ramp. A simple correction: refit the onset locally with the ramp template over [cp − 45, cp + 15] and report τ̂ = argmin RSS.
- CI for the onset: (a) profile RSS over τ, keeping τ with RSS(τ) − RSS(τ̂) ≤ σ²·χ²₁(0.95) ≈ 3.84σ². This is approximate because the problem is non-regular. (b) Residual block bootstrap (block 7), refitting τ̂. Both are cheap: about 200 candidate τ × 4 L values of 2-column least squares, a few ms per series.
- Davies test p-values are useful as a teaching tool, but the project already has a placebo-in-time calibration, which handles autocorrelation better.

### Gaps
- No source compared Muggeo / Davies directly with PELT on daily retail series.

## Q4. Continuous piecewise-linear change-point methods: CPOP, NOT, IDetect, ruptures CostCLinear, trend filtering

### Takeaway
These methods target changes in slope with a continuous mean, so a ramp appears as two kinks (start, end). CPOP is the most accurate but exists only in R. NOT and IDetect are R-only. Ruptures' `clinear` cost is the Python option and is fast enough. L1 trend filtering (convex, needs cvxpy, or a custom ADMM) tends to split a kink into several small ones. None of these clearly beats a matched filter for the "ramp into a new level" shape. Their value is as an exploratory second opinion and for dating.

### Cited Findings
- **CPOP** (Maidstone/Fearnhead, Maidstone & Letchford, JCGS 28(2):265–275, 2019): dynamic programming for the best continuous piecewise-linear fit with an L0 penalty on slope changes. The L0 penalty gives consistent estimation of the number of changes and is more reliable than L1 penalties (trend filtering) at locating changes. — [arXiv 1701.01672](https://arxiv.org/abs/1701.01672v2); [Lancaster eprint](https://eprints.lancs.ac.uk/id/eprint/84114)
- cpop R package (Fearnhead & Grose, JSS 109(7), 2024): supports heterogeneous noise variance (a vector of per-observation sd). Assuming constant variance when it is not gave two false-positive changepoints in high-variance regions. Empirical cost is about n^2.5 with a fixed number of changes and about n^1.7 when changes grow with n. A 200-point candidate grid makes cost roughly constant, and a coarse-to-fine grid gave a 10–100× speed-up with at most a 2-point location difference. — [arXiv 2208.11009](https://ar5iv.labs.arxiv.org/html/2208.11009); [JSS](https://www.jstatsoft.org/article/download/v109i07/4577)
- The same paper: first-differencing turns slope changes into mean changes but "removes much of the information in the data about the location of changes", and PELT on the differences gives poor locations. Standard OP/PELT cannot be applied directly because continuity couples adjacent segments. L1 trend filtering may fit one slope change with several same-sign changes. — [arXiv 2208.11009](https://ar5iv.labs.arxiv.org/html/2208.11009)
- No Python CPOP was found. The options are rpy2 or reimplementing the DP. — [search summary, cpop CRAN](https://archive.linux.duke.edu/cran/web/packages/cpop/refman/cpop.html)
- **NOT** (Baranowski, Chen & Fryzlewicz, JRSS-B 81(3):649–672, 2019, doi 10.1111/rssb.12322): draws random intervals, keeps the *narrowest* ones whose contrast exceeds a threshold (so each contains one feature), and selects the threshold by strengthened SIC. It covers kinks in piecewise-linear signals. R package `not` with `contrast="pcwsLinContMean"` (continuous) or `"pcwsLinMean"`. — [arXiv 1609.00293](https://arxiv.org/abs/1609.00293v2); [not manual](https://cran.r-project.org/web/packages/not/refman/not.html); [LSE](https://researchonline.lse.ac.uk/id/eprint/100430)
- **Isolate-Detect** (Anastasiou & Fryzlewicz, Metrika 2022, doi 10.1007/s00184-021-00821-6): expands intervals from both ends so each change point is isolated before it is tested. It handles piecewise-constant and continuous piecewise-linear signals, including heavy-tailed noise. R `IDetect` (functions `cplm_ic`, `cplm_th`), v0.1.1 on CRAN 2026-05-07. — [arXiv 1901.10852](https://arxiv.org/pdf/1901.10852.pdf); [Springer](https://link.springer.com/article/10.1007/s00184-021-00821-6); [CRAN](https://cran.r-project.org/web/packages/IDetect/index.html)
- **ruptures `CostCLinear`** (`model="clinear"`): cost of a segment = squared error against the straight line joining y_{a−1} and y_{b−1} (a continuous linear spline through the data endpoints). Usable in any ruptures search (`Pelt`, `Binseg`, `Dynp`, …). — [ruptures docs](https://centre-borelli.github.io/ruptures-docs/user-guide/costs/costclinear/)
- **[sim]** `rpt.Pelt(model="clinear", min_size=7)` on n=670: about 0.035 s per series (so ~10 s for 300 series). `model="l2"`: ~0.06 s per series with ruptures' Python PELT at jump=5 default. In dating, clinear had median error 0 but a heavy tail (MAE 14 d) because its endpoints are anchored to single noisy observations.
- **Trend filtering**: ℓ1 trend filtering (Kim, Koh, Boyd & Gorinevsky, SIAM Review 51(2), 2009) and its theory and generalisation (Tibshirani, Annals of Statistics 42(1), 2014). — [Kim et al. 2009](https://doi.org/10.1137/070690274); [Tibshirani 2014, arXiv 1304.2986](https://arxiv.org/abs/1304.2986). (These are classic references cited from memory of the literature. No page was fetched for this note.) The over-segmentation critique is from the CPOP papers above.

### Inferences
- Best Python choice in this family: ruptures `Pelt(model="clinear")` on a weekly-aggregated or DoW-adjusted series. Aggregating to 7-day means (n≈96) also removes the weekly pattern and makes the noise less heavy-tailed. Alternatively, implement the "ramp into plateau" grid search from Q2/Q3, which is a constrained two-kink CPOP with known structure.
- The anchoring of `CostCLinear` to single noisy endpoints is a weakness on noisy daily counts. Smoothing first (7-day mean) or using a least-squares linear cost (`CostLinear`, i.e. `model="linear"` with a time regressor) helps.

### Gaps
- No published head-to-head power comparison of CPOP / NOT / ID against mean-shift PELT on ramps was found in the fetched pages. The cpop JSS paper refers to Fearnhead et al. (2019) for an empirical comparison, which I did not fetch.
- I could not confirm whether ruptures' `CostLinear` / `CostCLinear` exploit cumulative sums (the docs do not state complexity).

## Q5. CUSUM / GLR tests for slope changes (online and offline)

### Takeaway
GLR / CUSUM for a slope change uses residuals from the pre-change line weighted by time since the change. It reaches the kink rate (n^{-1/3}), which is worse than the jump rate, so ramps are intrinsically harder. For a ramp *into a new level*, the two-kink matched filter (Q2) is the natural offline GLR. Online slope CUSUMs are relevant only if the system must flag events as they happen.

### Cited Findings
- FLOC (arXiv 2503.05270): online detectors for jumps and kinks in segmented linear regression. The kink statistic is a weighted residual mean with bin size N_K ≍ n^{2/3}log^{1/3} n, at constant time and memory per sample. Minimax localisation is log(n)/n for a jump and (log n/n)^{1/3} for a kink. — [arXiv 2503.05270](https://arxiv.org/html/2503.05270v2)
- Mixture-GLR slope-change detection across many sensors that share a change time, with an online form. Relevant for pooling several city × channel series hit by the same event. — [Multi-Sensor Slope Change Detection, arXiv 1509.00114](https://arxiv.org/pdf/1509.00114)
- Review of single-changepoint likelihood-ratio tests for mean and trend-slope changes (climatology). — [Single Changepoint Procedures, arXiv 2511.17870](https://arxiv.org/html/2511.17870v1)
- Python online CUSUM: `changepoint-online` (FOCuS) solves the CUSUM likelihood-ratio test exactly in O(log n) per iteration for exponential-family **mean** changes (Gaussian, Poisson, …), plus non-parametric NPFOCuS. — [PyPI](https://pypi.org/project/changepoint-online/); [tutorial](https://lancaster.ac.uk/~romano/post/change_point_online_intro); [focus / focus-cpt, arXiv 2607.19961](https://arxiv.org/pdf/2607.19961)

### Inferences
- FOCuS on a Poisson model is a fast Python mean-change detector that suits counts directly (no STL), but it is still a mean-shift detector. On a ramp it fires part-way up the ramp and needs the Q3 local refit for dating.
- Multi-series pooling (the multi-sensor GLR idea) is a promising power lever: a city-wide competitor entry should move *all* that city's physical-store KPIs (orders, revenue, customers) with the same τ. Summing aligned ramp-scan z's across related KPIs raises power by about √k.

### Gaps
- No Python implementation of an offline slope-change CUSUM / GLR was found. It is about 20 lines of numpy (see Q2).

## Q6. Bayesian approaches: BOCPD with a trend model, and BEAST (Rbeast)

### Takeaway
BEAST has a Python wheel (`pip install Rbeast`) and directly models piecewise-linear trend changepoints with seasonal terms and posterior probabilities of changepoint location. It is the only off-the-shelf Python Bayesian trend-changepoint tool found, but MCMC makes it slower than everything above. BOCPD can use a conjugate Bayesian linear-regression segment model in principle, but I found no ready Python package with a trend observation model.

### Cited Findings
- BEAST (Zhao et al., Remote Sensing of Environment 232:111181, 2019, doi 10.1016/j.rse.2019.04.034): Bayesian model averaging over decomposition models with abrupt changes, seasonal changes and trend. Gives changepoint probabilities and uncertainty. — [NASA abstract](https://modis.gsfc.nasa.gov/sci_team/pubs/abstract_new.php?id=31458); [CRAN Rbeast](https://cran.case.edu/web/packages/Rbeast/index.html)
- Python: `pip install Rbeast`. `rb.beast(y, season="none")`, or with `period`/`deltat` set for seasonal data. It "can detect piecewise linear trends as well as more flexible nonlinear trends". The authors say it is fast for a Bayesian method but can be slower than non-Bayesian methods because of MCMC. — [GitHub zhaokg/Rbeast](https://github.com/zhaokg/Rbeast)
- BOCPD (Adams & MacKay 2007): exact online posterior over run length with a hazard prior; conjugate-exponential segment models are "particularly convenient". — [arXiv 0710.3742](https://arxiv.org/abs/0710.3742)

### Inferences
- A Bayesian linear-regression (Normal-Inverse-Gamma) segment model makes BOCPD detect slope changes. Cost is O(n²) per series without pruning (about 450k updates at n=670), which is fine in numpy at ~300 series if the run length is truncated (e.g. 120 d). Under BOCPD, however, a ramp into a plateau looks like two changepoints and needs post-processing.
- BEAST could be a useful offline "second opinion" on flagged series only (dozens, not 300), given the MCMC cost.

### Gaps
- No BEAST timing for n=670 was found. Benchmark locally before using it in the 60 s budget.
- No maintained Python BOCPD package with a linear-trend observation model was confirmed.

## Q7. Shortlist and compute budget (synthesis)

### Takeaway
Recommended stack, in order of expected gain for ramp misses and misdating:
1. Stop detecting on STL residuals. Use DoW-adjusted, reference-normalised (sibling-segment ratio) log series.
2. Ramp-template matched-filter scan (Q2).
3. Ramp-aware scoring contrast that skips the ramp, with the placebo z computed the same way.
4. Local ramp-template / hockey-stick refit with a profile CI for the onset (Q3).
Optional: ruptures `clinear` PELT or BEAST as a second opinion, and pooling across related KPIs.

### Cited Findings
- STL default trend window ≈ 15 d at period 7. — [statsmodels](https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.STL.html)
- Gradual changes are slower to localise than abrupt ones (Hušková; FLOC). — [Hušková 1998](https://dml.cz/handle/10338.dmlcz/118993); [arXiv 2503.05270](https://arxiv.org/html/2503.05270v2)
- Single-change fits on slope data land mid-ramp. — [arXiv 2208.11009](https://ar5iv.labs.arxiv.org/html/2208.11009)

### Inferences
- Compute (n=670, 300 series; [sim] timings on this machine):
  | method | per series | 300 series |
  |---|---|---|
  | ramp matched filter, 5 lengths | ~0.1 ms | 0.03 s |
  | local ramp grid refit (200 τ × 4 L) | a few ms | <2 s |
  | ruptures PELT `clinear` | ~35 ms | ~10 s |
  | ruptures PELT `l2` | ~60 ms | ~18 s |
  | piecewise-regression (Muggeo + bootstrap) | not measured; likely 10–100 ms | run only on candidates |
  | Rbeast | not measured (MCMC) | candidates only |
- Expected effect on miss (a), a 30-day −20 % ramp: with the current 28-day DiD from the true onset the z is about 0.45× the step-equivalent. With ramp-skipping scoring it is 1.0×. On top of that, if detection currently uses STL residuals, the signal available to PELT is about 0–3 % of the drop. Both fixes are needed.

### Gaps
- The magnitudes depend on the actual noise (overdispersion, autocorrelation) of the generator. Re-run the [sim] scripts against `s2d` series before finalising thresholds.
