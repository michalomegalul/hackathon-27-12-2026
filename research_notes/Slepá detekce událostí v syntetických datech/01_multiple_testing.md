# Multiple-testing control for large hierarchical change-point / anomaly searches over many correlated KPI series

Scope: the detective scans ~150-300 correlated daily KPI series in a tree (overall -> single dimension -> dimension pairs). It finds candidate dates with STL + PELT/Binseg, scores each candidate with a 28-day relative DiD (target vs rest), and keeps only candidates at placebo-in-time z >= 5.25. That threshold was tuned on no-story twins to about one false event per year. Misses sit at z 3-5. These notes compare FDR, hierarchical, online, weighted and max-statistic methods with that fixed-z rule.

Recommended shortlist (details below):
1. Turn each candidate's placebo-in-time DiD into an empirical rank p-value, then use BH with a BY fallback, or e-BH. Use one p-value per (series, candidate window), not one per day.
2. Test the series tree top-down with TreeBH (Bogomolov et al., Biometrika 2021) or the p-filter. This tests far fewer pair-level hypotheses, which is what makes a lower bar affordable.
3. Use weighted BH (Genovese-Roeder-Wasserman 2006) with pre-specified weights that favour overall and single-dimension series and give pairs less weight.
4. Use a Westfall-Young max-statistic over all series, taken from the same placebo dates, as the strict FWER alternative to a fixed z. It calibrates itself to the actual correlation between series, so it needs no no-story twin.

---

## 1. FDR control for change points (BH/BY, e-BH, knockoffs, data splitting, post-selection inference)

### Takeaway
BH on candidate-level p-values is the simplest change. It moves from about one false event per year (FWER-like) to a controlled false-discovery proportion, which accepts more borderline (z 3-5) finds while bounding the share that are false. BY and e-BH keep that guarantee under any dependence between series, at some cost in power. Change-point-specific FDR methods exist (dSTEM, data splitting, knockoffs, post-selection p-values, permutation interval selection), but they are built for one sequence or one multivariate sequence with a single mean-shift model. They are more complex than this project needs. Their useful ideas are "one p-value per candidate location" and "split detection from testing".

### Cited Findings
- **BH / BY in Python.** `statsmodels.stats.multitest.multipletests` offers `fdr_bh`, `fdr_by` (Benjamini/Yekutieli, documented as the variant for negative dependence) and the two-stage adaptive `fdr_tsbh` / `fdrcorrection_twostage` (Benjamini-Krieger-Yekutieli 2006, `method='bky'`). With the two-stage methods, decisions must be made against the same alpha that was passed in. — [statsmodels multipletests](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html); [fdrcorrection_twostage](https://statsmodels.org/stable/generated/statsmodels.stats.multitest.fdrcorrection_twostage.html)
- `scipy.stats.false_discovery_control(ps, method='bh'|'by')` gives adjusted p-values. 'by' is Benjamini-Yekutieli Theorem 1.3, valid under arbitrary dependence. — [SciPy docs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html)
- **e-BH (Wang & Ramdas, JRSS-B 2022).** Unlike BH, e-BH controls FDR at the nominal level with no correction for any dependence among the e-values. Base e-BH equals BH applied to p = 1/e. The paper also shows e-BH is optimal among FDR procedures on arbitrarily dependent e-values. — [arXiv 2009.02824](https://arxiv.org/abs/2009.02824); [JRSS-B PDF](https://sas.uwaterloo.ca/~wang/papers/2021Wang-Ramdas-JRSSB.pdf)
- Later work (reported in secondary descriptions; I did not open the originals) claims that every FDR-controlling procedure is an instance of e-BH (Ignatiadis et al. 2024). A closed e-BH (Fischer & Ramdas 2025) usually strictly improves on e-BH. — [arXiv 2504.11759](https://arxiv.org/html/2504.11759v1)
- **dSTEM (Cheng, He & Schwartzman, EJS 2020).** The method smooths and differentiates the sequence, so change points become local extrema. It then computes p-values for those extrema from peak-height distributions and applies BH, giving asymptotic strong FDR control over detected change points. The authors call it the first multiple-testing method that controls the FDR of detected change points. An R package `dSTEM` (v2.0-1, 2023) is on CRAN. — [arXiv 1504.06384](https://arxiv.org/abs/1504.06384v2); [EJS](https://projecteuclid.org/euclid.ejs/1602036132); [dSTEM manual](https://ftp.fau.de/cran/web/packages/dSTEM/refman/dSTEM.html)
- **FDRSeg (Li, Munk & Sieling, EJS 2016).** Changes the SMUCE multiscale segmentation from FWER to FDR control. Gives a non-asymptotic FDR bound for the Gaussian case and clearly more detection power than SMUCE. — [arXiv 1412.5844](https://arxiv.org/abs/1412.5844v2)
- Niu, Hao & Zhang's overview frames multiple change-point detection as testing each candidate location separately. It notes that the sequential structure makes this an atypical multiple-testing problem. — [arXiv 1512.04093](https://arxiv.org/pdf/1512.04093)
- **Data splitting (Chen, Ren, Yao & Zou, JASA 2023).** Order-preserving sample splitting plus a symmetry ("mirror") statistic gives a data-driven threshold for the number of change points. It works with most existing change-point methods and controls FDR asymptotically. — [IDEAS/JASA 118(542):1415-1428](https://ideas.repec.org/a/taf/jnlasa/v118y2023i542p1415-1428.html)
- Data splitting loses power because only half the data is used. Sun, Bi & Liu (Statistics Innovation 2026) propose a "Synthetic Data Filter" with a Gaussian-multiplier-bootstrap mirror statistic to recover that power. — [Maxapress](https://maxapress.com/article/doi/10.48130/stati-0026-0002)
- **Knockoffs for structural change (GKnockoff; Liu, Sun & Ke, J. Econometrics 2024).** A generalized knockoff with pairwise exchangeability controls exact finite-sample FDR for change-point identification. A data-splitting screen comes first. — [arXiv 2108.10595](https://arxiv.org/abs/2108.10595)
- **Post-selection inference (Jewell, Fearnhead & Witten, JRSS-B 2022).** Tests the change in mean near an estimated change point while conditioning on far less than Hyun et al. (2018, 2021), which gives more powerful selective p-values. R package `ChangepointInference`. — [arXiv 1910.04291](https://arxiv.org/pdf/1910.04291); [JRSS-B 84(4):1082-1104](https://ideas.repec.org/a/bla/jorssb/v84y2022i4p1082-1104.html)
- Carrington & Fearnhead extend this by conditioning on even less. They report more significant changepoints than Jewell et al. on genomic data. — [arXiv 2301.05636](https://arxiv.org/html/2301.05636v3)
- **POIS / POIS+ (Wei, Bao, Ren & Chen, arXiv Oct 2026).** Treats intervals reported by any detector as hypotheses. Order-preserving sample splitting plus permutation tests give finite-sample interval-level FDR control. POIS+ reuses detection-step evidence as e-value weights on the permutation p-values to gain power. I found no code. — [arXiv 2610.10271](https://arxiv.org/abs/2610.10271)
- **ARM (Peng et al., arXiv Aug 2026).** A wrapper around any detector that certifies which coordinates of a multivariate series changed. FWER uses a Westfall-Young joint permutation that keeps cross-coordinate dependence. FDR uses BY or e-BH under arbitrary dependence. In simulations, naive per-coordinate testing at the estimated changepoint had FWER > 0.66. Python code (`arm_core.py`) is in the arXiv ancillary files. — [arXiv 2608.01691](https://arxiv.org/abs/2608.01691)

### Inferences
- **What it is (BH on candidate p-values).** Sort the m candidate p-values and reject the k smallest, where k is the largest index with p_(k) <= q·k/m. The threshold therefore adapts: when many real effects are present, borderline ones get through.
- **Why it helps.** The current z >= 5.25 is an FWER-style bar (about one false event per year). With m ≈ 300-1000 candidates, BH at q = 0.1-0.2 needs a nominal p of roughly 1e-3 or less for the first rejection. Each true rejection loosens the bar for the next, so a true z ≈ 4 effect can pass once one or two strong effects are found. Under pure noise, BH controls FWER at q (it reduces to Simes), so the no-story false rate stays bounded.
- **The p-value floor (crucial).** A rank p-value from P placebo dates cannot go below 1/(P+1). With ~600 placebo dates, the floor is ≈ 1.7e-3, which is too coarse for BH over hundreds of tests. Two fixes are possible. (a) Use the placebo distribution only to standardize: z = (DiD − mean_placebo)/sd_placebo with a normal or t tail, or a tail fit (GPD) beyond the empirical range. (b) Pool placebo DiDs across series from the same tree level, after each is standardized by its own placebo sd, so the null sample is P × n_series.
- **BY versus e-BH.** BY divides q by H_m = Σ1/i, about 6.3 for m = 300. Effectively that is BH at q/6, which loses much of the gain. Positive correlation between overlapping series (overall vs segment, segment vs pair) is the PRDS-type case where plain BH is generally held to stay valid. This is standard BY 2001 theory, not verified in a fetched source here. Plain BH plus an empirical check on no-story twins (offline, not at runtime) is therefore the pragmatic choice.
- **Hypothesis unit.** Collapse PELT/Binseg hits within ±7-14 days in one series into a single candidate before testing. Otherwise one effect creates several "discoveries" and FDR is diluted. POIS uses intervals as hypotheses for the same reason.
- dSTEM, GKnockoff, data splitting and Jewell et al. are each per-series and mean-shift-specific, and mostly in R. Porting them would cost more than the hackathon budget and would be hard to explain. Data splitting halves an effect's information (d = 3.5 becomes ~2.5), which is bad for the z 3-5 misses. ARM is the closest match to the "which series/segment changed" question and ships Python code. It is worth reading for its Westfall-Young implementation.

### Gaps
- I found no paper that applies FDR to DiD-vs-rest effect estimates on a tree of aggregated, overlapping KPI series. The proposed design is an inference from the general methods.
- I did not fetch Benjamini-Yekutieli 2001 directly. The PRDS claim for positively correlated one-sided test statistics is from standard knowledge, and "target vs rest" contrasts can induce negative correlation between siblings.
- I could not verify the Chen et al. 2023 simulation details or the full Sun-Bi-Liu text (paywalled or preview only).

---

## 2. Hierarchical / tree-structured testing (Yekutieli 2008, Meinshausen 2008, Goeman-Solari, TreeBH, p-filter)

### Takeaway
The KPI series already form a tree: overall -> single dimension (city, channel, segment, SKU group) -> dimension pairs. TreeBH and the p-filter use this to test pair-level hypotheses only under parents that passed, with selection-adjusted levels. That cuts the effective number of tests at the deepest level, where most false finds and most of the multiplicity sit. Power is kept for effects that show up at a parent level. The planted competitor-entry event (one city × channel) does show up in the city and channel series, only diluted.

### Cited Findings
- **TreeBH (Bogomolov, Peterson, Benjamini & Sabatti, Biometrika 2021; arXiv "Testing hypotheses on a tree").** A multiple-testing procedure that controls error rates at several levels of resolution at once. In simulations it keeps its guarantees under a range of dependence structures, including GWAS-like dependence, and can gain power. A modified version controls the error rates under any dependence. — [arXiv 1705.07529](https://arxiv.org/abs/1705.07529v2); [Biometrika PDF](https://odin.mdacc.tmc.edu/~cbpeterson/Bogomolov_Peterson_Biometrika_2021.pdf)
- TreeBH builds on Benjamini & Bogomolov (2014), which defines an FDR that accounts for selecting families first. The authors' earlier TreeQTL R package implements a related hierarchical procedure. — [PMC4978936](https://pmc.ncbi.nlm.nih.gov/articles/PMC4978936)
- **Yekutieli (2008), JASA 103:309-316.** Described as a general FDR method for hierarchically ordered hypotheses. It builds on BH and is only shown to control FDR under independence. — [Lynch & Guo 2016, arXiv 1612.04467](https://arxiv.org/pdf/1612.04467)
- Lynch & Guo (2016) give further procedures that control FDR for hierarchically ordered hypotheses. — [arXiv 1612.04467](https://arxiv.org/pdf/1612.04467)
- **Meinshausen (2008)** is a hierarchical FWER procedure that tests clusters of predictors top-down for variable selection in regression. — [Lynch & Guo 2016](https://arxiv.org/pdf/1612.04467)
- **p-filter (Barber & Ramdas; Ramdas, Barber, Wainwright & Jordan, Annals of Statistics 2019).** Controls FDR at the individual level and at the group level at once, for several partitions that need not be nested. It generalizes BH and Simes. The unified version also handles p-value weights, penalty weights, null-proportion adaptivity and group structure together, with guarantees under three dependence settings. — [arXiv 1512.03397](https://arxiv.org/abs/1512.03397); [arXiv 1703.06222](https://web3.arxiv.org/pdf/1703.06222v5); [AOS PDF](https://people.eecs.berkeley.edu/~jordan/papers/AOS1765.pdf)
- A rejection set can also be filtered after the fact (e.g. to one hypothesis per group) while keeping FDR control. — [arXiv 1809.01792](https://arxiv.org/pdf/1809.01792)

### Inferences
- **How to apply TreeBH here (the procedure as I understand it from the paper; check the indexing against the PDF):**
  1. Leaves are (pair series × candidate window) p-values. Each single-dimension node gets a Simes-combined p-value of its own test and its children, and the root gets one for the overall series.
  2. Level 1: test the root, or the set of dimension families, at q.
  3. Level 2: within each selected dimension family, run BH at q·(#selected families / #families). This is the Benjamini-Bogomolov selection adjustment.
  4. Level 3: within each selected single-dimension node, run BH over its pair children at a level shrunk again by the selected fraction.
  Each step is a sort, so cost is O(m log m) and negligible.
- **Why it helps.** Suppose ~200 of 300 series are pairs. A flat test has to beat ~300-way multiplicity. In the tree, a pair is only tested inside the few parent families that already showed signal, and BH then runs over perhaps 5-20 children. A real city × channel effect at z ≈ 4 that also shows (weaker) in its city series can be confirmed at the pair level. Noise-only pair spikes under unremarkable parents are never tested, which removes the main source of false finds. This also formalizes the existing Adtributor-style drill-down.
- **Caveat: the tree is not a clean partition.** A pair (city × channel) has two parents (city and channel). Options are to attach each pair to its parent with the smaller p-value (pick a rule before seeing the data, e.g. alphabetical, to keep validity), or to use the p-filter, which explicitly allows several non-nested partitions ("by city", "by channel", "by pair"). The p-filter fits the DAG better. TreeBH is simpler to explain.
- **Caveat: diluted parents.** Effects confined to a small cell (one SKU, one city × channel) may not show at the parent. The Simes combination helps, since one strong child makes the parent significant. TreeBH would still miss a weak child under a weak parent. That is the intended trade-off.
- Goeman & Solari (closed testing / all-resolutions inference; "only closed testing procedures are admissible for FDP", [arXiv 1901.04885](https://arxiv.org/pdf/1901.04885)) give simultaneous FDP bounds for any chosen subset. This suits post-hoc drill-down, but it is more complex to explain and is not implemented in Python (R `hommel`/`sumSome`).

### Gaps
- No Python package for TreeBH or the p-filter turned up in my searches. Both are short to implement with numpy (Simes + BH per node).
- I did not verify the exact level-adjustment formula of TreeBH from the full text.
- I did not find focused BH (Katsevich, Sabatti & Bogomolov) in these searches.

---

## 3. Online / sequential FDR (alpha investing, LORD, SAFFRON)

### Takeaway
Online FDR procedures are built for hypotheses that arrive one at a time, with decisions that cannot wait. The detective scans the whole 670-day history in one batch, so batch BH, TreeBH or e-BH are uniformly preferable. Online methods matter only for a future streaming or monitoring mode.

### Cited Findings
- The lineage runs from alpha investing (Foster & Stine) to generalized alpha investing (Aharoni & Rosset) to LORD (Javanmard & Montanari, Annals of Statistics 2018). Ramdas et al. improved these to LORD++. — [SAFFRON arXiv 1802.09098](https://arxiv.org/abs/1802.09098); [Javanmard & Montanari AOS](https://projecteuclid.org/journals/annals-of-statistics/volume-46/issue-2/Online-rules-for-control-of-false-discovery-rate-and-false/10.1214/17-AOS1559.pdf)
- SAFFRON (Ramdas et al., ICML 2018) adapts to the null proportion and beats LORD and other generalized-alpha-investing rules in power. Online FDR control for GAI rules needs null p-values to be independent of the others. Later work shows LORD and SAFFRON also control online FDR under nonnegative dependence. — [arXiv 1802.09098](https://arxiv.org/pdf/1802.09098v2.pdf)
- e-GAI (Zhang, Wei, Ren & Zou 2025) gives e-LORD and e-SAFFRON and addresses "alpha-death". — [arXiv 2506.01452](https://www.arxiv.org/pdf/2506.01452)
- Python: `online-fdr` on PyPI implements LORD variants, LOND, GAI, SAFFRON and ADDIS with a sequential API, validated against the R/Bioconductor `onlineFDR`. — [PyPI online-fdr](https://pypi.org/project/online-fdr/); [docs](https://oliverhennhoefer.github.io/online-fdr)

### Inferences
- In batch mode, any online rule is applied in some arbitrary order and wastes alpha on early tests ("alpha-death" after a long run of nulls). It cannot be more powerful than BH on the same p-values. Do not use it for the hackathon scan.
- A possible use is a "live" demo that processes days in time order: alpha-investing over candidate dates is easy to explain ("each discovery earns back alpha").

### Gaps
- None material for the batch use case.

---

## 4. Weighted BH / p-value weighting with priors (Genovese-Roeder-Wasserman 2006; IHW)

### Takeaway
Weighted BH with fixed, pre-registered weights (mean 1) lets the detective spend more of its error budget on hypotheses where planted-style events are a priori likely: overall and single-dimension series, and the business-meaningful KPIs (revenue, orders, stock-outs, cancellations). It spends less on hundreds of thin pair series. This raises power for z 3-5 effects in favoured tests at little cost when the weights are moderate. Data-driven IHW is overkill for a few hundred tests.

### Cited Findings
- **Genovese, Roeder & Wasserman (Biometrika 2006, 93(3):509-524).** Weighted BH keeps FDR control while using prior information as p-value weights. Even poor weights lose only a little power as long as they are not too large. Any nonnegative weights that average to one are valid. — [IDEAS](https://ideas.repec.org/a/oup/biomet/v93y2006i3p509-524.html); [CMU TR 811](https://www.stat.cmu.edu/tr/tr811/tr811.pdf); [Roeder & Wasserman, arXiv 1010.4637](https://ar5iv.arxiv.org/html/1010.4637)
- **IHW (Ignatiadis et al., Nature Methods 2016; Ignatiadis & Huber, JRSS-B 2021).** Learns weights as a step function of a covariate that is independent of the p-value under the null. Cross-weighting (data splitting across folds) avoids overfitting. Available as the Bioconductor R package `IHW` (no Python port found). — [Nature Methods](https://www.nature.com/articles/nmeth.3885); [JRSS-B 83(4):720-751](https://ideas.repec.org/a/bla/jorssb/v83y2021i4p720-751.html); [Bioconductor](https://bioconductor.org/packages/devel/bioc/html/IHW.html)
- The unified p-filter accepts p-value weights together with group structure. — [arXiv 1703.06222](https://web3.arxiv.org/pdf/1703.06222v5)

### Inferences
- **Implementation.** Replace p_i with p_i / w_i (where Σw_i = m) and run ordinary BH, a one-line change to `multipletests(p/w, method='fdr_bh')`. Example weights: overall and single-dimension series w = 3, pair series w = 0.5, rescaled to mean 1. Or set the weight from the series' base volume: high-volume series have lower noise, so a planted d of 3.5-5 is more detectable there.
- **Where the gain comes from.** With w = 3, a hypothesis needs only one third of the BH p-threshold. That is roughly a 0.4-0.5 drop in the required z near z ≈ 4-5 (normal tail), often enough to recover a z ≈ 4.5 miss.
- **Validity.** The weights must be fixed without looking at the outcome data (by tree level, KPI type, series volume). A "covariate" such as the PELT cost of the same window is not independent of the null p-value and would break validity.
- **Explainability.** Students can understand "we trust the top of the tree more, so it gets a bigger share of the alpha budget."

### Gaps
- No empirical guidance found on weight values for business-KPI trees. They would need tuning on no-story and story twins offline, which is allowed since the twins are not used at runtime.

---

## 5. Placebo-in-time p-values, how to combine them with BH, and Westfall-Young max-statistic as an alternative to a fixed z

### Takeaway
The current placebo z is already a permutation-in-time test (the "structural-breaks/conformal" logic of Chernozhukov-Wüthrich-Zhu). It can become a valid per-test p-value as a rank, with the +1 correction. Neighbouring placebo dates are strongly autocorrelated (28-day windows overlap), so the effective number of placebo draws is about P/28 rather than P. That makes raw ranks too coarse for BH. Standardizing with the placebo sd, or pooling standardized placebos across series, fixes this. The cleanest substitute for the hand-tuned z = 5.25 is a Westfall-Young max-T threshold from the same placebo dates across all series simultaneously. It controls FWER at any chosen level under the real cross-series correlation, adapts to the run's data, and needs no no-story twin at runtime.

### Cited Findings
- **Chernozhukov, Wüthrich & Zhu (JASA 2021, 116(536)).** Recast counterfactual/synthetic-control inference as counterfactual prediction plus a structural-break test, giving permutation inference (including moving-block and i.i.d. permutations of time). The test is exact when residuals are exchangeable and only approximately valid under serial dependence, given weak conditions on the counterfactual estimator. — [arXiv 1712.09089](https://arxiv.org/abs/1712.09089v8); [MIT DSpace](https://dspace.mit.edu/handle/1721.1/144458)
- **Phipson & Smyth (SAGMB 2010).** Permutation p-values should never be zero. With randomly drawn permutations, use (b+1)/(B+1) or their exact method; implemented in R `statmod::permp`. — [arXiv 1603.05766](https://arxiv.org/pdf/1603.05766); [SAGMB](https://www.degruyterbrill.com/document/doi/10.2202/1544-6115.1585)
- **Westfall-Young max-T.** Under subset pivotality, the permutation max-T method strongly controls FWER under any dependence. The step-down version is more powerful, just as Holm improves Bonferroni. Its power advantage over Bonferroni/Holm is large when tests are positively and strongly dependent. — [Meinshausen, Maathuis & Bühlmann, AoS 2011, arXiv 1106.2068](https://arxiv.org/pdf/1106.2068)
- The single-step Westfall-Young threshold asymptotically matches the oracle threshold under block dependence and sparsity. — [arXiv 1106.2068](https://arxiv.org/pdf/1106.2068)
- ARM uses a Westfall-Young joint permutation that keeps cross-coordinate dependence for changepoint attribution, with BY or e-BH for FDR. Python code is in the arXiv ancillary files. — [arXiv 2608.01691](https://arxiv.org/abs/2608.01691)
- e-BH controls FDR under arbitrary dependence among e-values. — [arXiv 2009.02824](https://arxiv.org/abs/2009.02824)

### Inferences
- **(a) Rank p-value.** For series s and candidate date t, compute DiD_s(t) and the placebo set {DiD_s(u): u admissible, |u − t| > 28, not in holiday or Black Friday windows unless t is}. Then p = (1 + #{|DiD_s(u)| ≥ |DiD_s(t)|}) / (1 + P). This is valid if placebo dates are exchangeable with t under the null (approximate, given seasonality; it follows the Chernozhukov et al. logic). With 670 days and 28+28 windows, P ≈ 600 placebo dates but only about 20 independent ones, so the floor of about 1/600 is not trustworthy in the tail.
- **(b) Standardized p-value.** Turn the placebo z into p = 2·(1 − Φ(z)), or a t-tail, or a GPD tail fitted to the top placebo values. Use the robust scale (MAD) of the placebo DiDs. This gives the resolution BH needs at p ≈ 1e-4. The validity check is offline: on no-story twins, the p-values should be roughly uniform.
- **(c) Combine with BH.** One p per (series, candidate window), weighted by tree level, then BH at q = 0.1 or TreeBH at q = 0.1. Expected effect: with ~300-600 candidates, the first rejection needs p < q/m ≈ 2e-4 (z ≈ 3.7), not z ≥ 5.25. Each extra true discovery lowers the bar further. In a no-story run, BH gives at most about a q chance of any false find. q = 0.1 therefore roughly matches "about one false event in ten runs" rather than one per year. Tune q offline on the twins.
- **(d) Westfall-Young max-T over all series (FWER alternative to z = 5.25).** For each placebo date u, compute T_max(u) = max_s |z_s(u)| over all series. That is one vector of length P, built from DiD values the detective already computes. The FWER-α threshold is the (1 − α) quantile of T_max(u). Step-down: remove the largest rejected series and recompute. Because KPI series are strongly positively correlated (overall contains segments, pairs nest in singles), the effective number of independent tests is far below 300. The data-driven threshold will likely be below 5.25 on noise-only data. It is also recalculated for each dataset, so it stays blind, since it uses no twins or answer key. Caveat: placebo dates are themselves autocorrelated, so use only every 7th or 14th date, or a block bootstrap, for the quantile. Report the effective P.
- **(e) e-values.** For a likelihood-ratio-like e-value, use e_s = exp(λ z_s − λ²/2) (a Gaussian e-value, valid if z is approximately N(0,1) under the null), or the calibrator e = κ·p^(κ−1). Then apply e-BH. This is dependence-proof, but e-values from calibrated p-values are less powerful than BH. Use e-BH only if the PRDS assumption for BH is in doubt.
- **(f) Compute.** Rank and standardized p-values reuse existing DiD computations, so the cost is O(series × candidates × P), which is vectorizable with numpy cumulative sums for the 28-day means. Max-T adds O(series × P) for z at every placebo date: about 300 × 600 = 180k DiDs, under 1 s vectorized. BH, BY, TreeBH and weighted BH are O(m log m). All fit easily in the 60 s budget. Data splitting, knockoffs and selective inference (R `ChangepointInference`) would add cost and complexity with less benefit.
- **Comparison with the current approach.** A fixed z = 5.25 is effectively Bonferroni-type FWER control tuned on twins. It ignores that many tests are correlated, where max-T is less strict, and it ignores the signal present in a given run, where BH loosens. It also spends the same alpha on pairs as on overall series, where weights or a tree would not. That is exactly why z 3-5 effects are lost.

### Gaps
- I found no paper that studies FDR/BH validity specifically for placebo-in-time p-values with overlapping windows across many series. The block-thinning advice is an inference.
- I did not find a mature Python library for Westfall-Young step-down permutation (`multipy` was not verified in these searches). It is about 20 lines of numpy.
- The exact BH thresholds above are back-of-envelope (normal tail). They need empirical confirmation on the no-story and story twins.
