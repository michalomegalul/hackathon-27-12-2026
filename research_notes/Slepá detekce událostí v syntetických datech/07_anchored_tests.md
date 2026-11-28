# Anchored (pre-registered, data-derived) hypotheses with their own lower threshold inside a blind search

Context for the report writer: the detective currently reports shifts at placebo-in-time z ≥ 5.25 (`Z_REPORT` in `s2d/detective/scan.py`, set on no-story twins, DECISIONS 57). Price changes in `product_prices` are already used as anchors (DECISIONS 41), and the lag search tests churn/rating against anchors at lags {0, 7, 14, 28, 42} with |t| ≥ 3 (DECISIONS 42, `lag_search()` in `scan.py`). That threshold, however, only attaches a cause to an event that has already passed 5.25. It does not report new events. The proposal in these notes is to give anchors their **own reporting family** with its own α budget.

Numbers below were computed with scipy (`norm.isf`, `norm.cdf`) in this session, not taken from a source. They assume Gaussian z. The 5.25 threshold is an empirical placebo-in-time threshold with heavier-than-Gaussian tails, so the Gaussian figures are a guide only, and the real anchored threshold should be calibrated with the same placebo machinery (see Q5).

## Q1. Alpha splitting between a small anchored family and a large exploratory family (weighted Bonferroni/Holm, weighted BH, IHW, graphical/fallback/gatekeeping)

### Takeaway
Theory allows giving a small set of pre-specified hypotheses a much larger share of the error budget, provided the weights (or the split) are fixed before looking at the outcome p-values. Weighted Bonferroni needs weights that average to 1 (equivalently, the α shares sum to the total). Weighted BH (Genovese–Roeder–Wasserman) and IHW extend the same idea to FDR. The simplest version to explain to students is a **two-family Bonferroni split**: the anchored family gets α_A (for example 0.1 expected false events per run), and the exploratory family keeps the rest. Because the exploratory family is effectively millions of Gaussian-equivalent tests, moving 10 % of the budget out of it raises its threshold only from 5.25 to about 5.27. A graphical/fallback scheme (Bretz et al. 2009) can additionally pass unused anchored α back to the exploratory family.

### Cited findings
- Genovese, Roeder & Wasserman, "False discovery control with p-value weighting", *Biometrika* 93(3):509–524 (2006). The procedure keeps FDR control while bringing in prior information as p-value weights. Power improves when the weights are positively associated with the nulls being false, and "even if the assignment of weights is poor, power is only reduced slightly, as long as the weights are not too large". The paper also covers false discovery exceedance. — [IDEAS/RePEc](https://ideas.repec.org/a/oup/biomet/v93y2006i3p509-524.html); [CMU TR 811 preprint](https://www.stat.cmu.edu/tr/tr811/tr811.pdf); DOI 10.1093/biomet/93.3.509
- Roeder & Wasserman, "Genome-Wide Significance Levels and Weighted Hypothesis Testing", *Statistical Science* 24(4):398–413 (2009). It says "to control the overall error rate, a substantial penalty is required, making it difficult to detect signals of moderate strength". The authors derive optimal weights and show "the power is remarkably robust to misspecification of these weights". They distinguish external weighting (from prior information) from estimated weighting (from the data). — [arXiv:1010.4637](https://arxiv.org/abs/1010.4637)
- Ignatiadis, Klaus, Zaugg & Huber, "Data-driven hypothesis weighting increases detection power in genome-scale multiple testing", *Nature Methods* 13(7):577–580 (2016). IHW applies weighted BH with weights learned from a covariate that is **independent of the p-values under the null**. — [PubMed](https://pubmed.ncbi.nlm.nih.gov/27240256/); [Nature Methods](https://www.nature.com/articles/nmeth.3885); [PMC4930141](https://pmc.ncbi.nlm.nih.gov/articles/PMC4930141)
- Ignatiadis & Huber, "Covariate powered cross-weighted multiple testing", *JRSS-B* 83(4):720–751 (2021). It proves finite-sample FDR control for cross-weighting, a data-splitting scheme in which the weights for one fold are learned on the other folds. The 2016 paper had used cross-weighting only as a heuristic. — [arXiv:1701.05179](https://arxiv.org/pdf/1701.05179); [IDEAS](https://ideas.repec.org/a/bla/jorssb/v83y2021i4p720-751.html); [Bioconductor IHW](https://code.bioconductor.org/browse/IHW)
- Bretz, Maurer, Brannath & Posch, "A graphical approach to sequentially rejective multiple test procedures", *Statistics in Medicine* 28(4):586–604 (2009). It builds weighted Bonferroni-based procedures, including gatekeeping, fixed-sequence and fallback, as graphs. Hypotheses are nodes holding α shares, and edges say where α goes after a rejection. Strong FWER control holds, and the final rejection set does not depend on the order of rejections. — [secondary description, Bretz et al. Biometrical J. follow-up (PMC3427907)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3427907); [typeset copy](https://typeset.io/pdf/a-graphical-approach-to-sequentially-rejective-multiple-test-4qjcn1kz8v.pdf)
- The original graphical methods were built on weighted Bonferroni tests, and the weighting can be separated from the test used on each intersection hypothesis. — [PMC3427907](https://pmc.ncbi.nlm.nih.gov/articles/PMC3427907)
- The fallback procedure is Wiens & Dmitrienko (2005), *J. Biopharm. Stat.* The fixed-sequence Bonferroni procedure is Wiens (2003), *Pharmaceutical Statistics* 2(3):211–215. Dmitrienko, Tamhane & Wiens (2008) list fallback with Holm and Hochberg as standard procedures. — [reference list](https://informahealthcare.com/doi/ref/10.1080/03610926.2019.1691231); [Dmitrienko et al., General gatekeeping](https://users.iems.northwestern.edu/~ajit/papers/42)%20General%20Gatekeeping.pdf)
- Weighted Holm (Holm 1979) is the closure of weighted Bonferroni tests and is at least as powerful as weighted Bonferroni. — [arXiv:2610.42122 (citing Holm 1979)](https://arxiv.org/pdf/2610.42122)
- Li & Guo (arXiv, April 2026), "Weighted Holm Procedures: Theory, Properties, and Recommendations". The weighted Holm procedure on ordered *weighted* p-values (WHP) is uniformly more powerful than the alternative on ordered raw p-values (WAP). WHP's critical values "cannot be enlarged without violating FWER control", and the paper recommends WHP. It also gives graphical representations "for communicating with non-statisticians". This is a preprint, not peer-reviewed. — [arXiv:2604.20016](https://arxiv.org/abs/2604.20016)
- Foster & Stine, "α-investing", *JRSS-B* 70(2):429–444 (2008). It is a sequential procedure that controls the marginal FDR (mFDR). Each rejection earns back α-wealth for later tests, and the procedure can bring in domain knowledge through the order and size of the bets. — [IDEAS](https://ideas.repec.org/a/bla/jorssb/v70y2008i2p429-444.html); [Penn repository](https://repository.upenn.edu/handle/20.500.14332/47482)
- `statsmodels.stats.multitest.multipletests(pvals, alpha, method)` supports bonferroni, sidak, holm-sidak, holm, simes-hochberg, hommel, fdr_bh, fdr_by, fdr_tsbh, fdr_tsbky and fdr_gbs. It has **no weights argument**, so weighted Bonferroni, Holm or BH must be hand-coded (a few lines) or applied as p/w before calling it. — [statsmodels docs](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)

### Inferences (approaches for the design)
**Approach A: two-family Bonferroni split, optionally with weighted Holm inside the anchored family.**
- *What it is:* The budget is fixed before the scan: total expected false events per run = 1. The exploratory family gets 0.9 and keeps a placebo threshold of about 5.27. The anchored family gets 0.1 spread over m_A anchored tests, so each test is run at α_A/m_A.
- *Why it helps miss (c):* Planted events coinciding with a price change, courier change or stock-out need z ≈ 3.1–3.5 instead of 5.25 (see Q3).
- *Why it helps miss (b):* Churn after a price change is tested only in the repriced category and only over the lag grid, so the effective m is small.
- *Cost and implementation:* Negligible: a few hundred DiD t-statistics. Bonferroni is one line, and weighted Holm is a sort plus a loop.
- *Why it is easy to teach:* "We bet 10 % of our false-alarm budget on 60 questions we wrote down from the price list before looking at sales."

**Approach B: graphical or fallback scheme (Bretz 2009).**
- *What it is:* Same as A, but if an anchored test is rejected, its α is passed to that anchor's secondary outcomes. For example, a confirmed orders drop at a price change passes α to churn in that category at lags 14–42. Unused anchored α can also flow to the exploratory family.
- *Why it helps miss (b):* It matches the causal chain price → orders → churn. A gatekeeping order (primary outcome first) is the standard trial design for "primary endpoint, then secondary endpoints".
- *Cost:* Trivial. A small hand-coded graph is enough. The R package `gMCP` exists, but I found no maintained Python equivalent (gap).

**Approach C: weighted BH (Genovese–Roeder–Wasserman) or IHW with "anchor present" as the covariate.**
- *What it is:* If the team prefers FDR to "1 false event per year", all candidate tests go into one weighted BH. Weight w > 1 goes to anchored tests and w < 1 to exploratory ones, with weights averaging to 1.
- *Trade-off:* This is a stronger reallocation than A, because FDR scales with discoveries. It is harder to tie to the existing placebo-in-time calibration. IHW proper (learning weights) needs many hypotheses per covariate bin and is overkill for a binary covariate. A fixed weight from GRW 2006 is simpler, and its robustness result says a poor weight costs little "as long as the weights are not too large". In practice that means capping w (for example at 20–50).

**Approach D: α-investing over anchors ordered by time.**
- *What it is:* Anchors are tested chronologically, and each confirmed anchor earns α-wealth.
- *Assessment:* Elegant, but it controls mFDR rather than FWER and is harder to explain. Mention it as an option, not the primary design.

### Gaps
- I could not access the full texts of Bretz et al. 2009 or Wiens & Dmitrienko 2005. Their procedure definitions are reported from secondary sources.
- I found no maintained Python package for graphical multiple testing (gMCP is R). This was not verified exhaustively.
- I did not retrieve exact power-loss magnitudes for poor weights from Roeder & Wasserman (abstract only).

## Q2. Independent filtering: is "a price change happened on this date" a valid filter?

### Takeaway
Bourgon et al. (2010) show that filtering (or weighting) keeps type I error control if, for every true null, the filter statistic is independent of the test statistic, so the null distribution after filtering equals the one before. An anchor date taken from an **exogenous treatment table** (price list valid_from, courier assignment change) is fixed independently of the outcome noise. Under the null of "no effect on this KPI", the DiD at that date therefore has its usual null distribution, and the filter is valid. Anchors derived from **outcomes or near-outcomes** are not valid filters:
- spikes in `cancelled_at`, because they are churn itself;
- inventory hitting zero, because a stock-out is partly caused by demand, so it correlates with units sold under the null of "no story event".

These need extra care (see Q4).

### Cited findings
- Bourgon, Gentleman & Huber, "Independent filtering increases detection power for high-throughput experiments", *PNAS* 107(21):9546–9551 (2010). The authors filter first by a criterion independent of the test statistic, then test only the survivors. "The key requirement is that the null hypothesis distribution of the test statistics after filtering should be the same as the null distribution before filtering." With the overall variance filter, rejections increased by up to 50 % in the ALL microarray example. — [PMC2906865](https://pmc.ncbi.nlm.nih.gov/articles/PMC2906865); [PDF](https://www.huber.embl.de/pub/pdf/Bourgon_PNAS_2010.pdf)
- The required condition is marginal independence of the filter statistic U_I and the test statistic U_II for each true null. They may be correlated under the alternative, and that correlation is where the power comes from. Under i.i.d. normal data, overall variance is independent of the two-sample t-statistic. — [PMC2906865](https://pmc.ncbi.nlm.nih.gov/articles/PMC2906865)
- Filters that violate the condition:
  - Filtering on the maximum of within-class means makes the conditional null heavier-tailed, so p-values are "overly optimistic".
  - Filtering on clusters inferred from the same data loses type I control.
  - Even a valid variance filter breaks limma's moderated t, because it distorts the prior variance fit.
  — [PMC2906865](https://pmc.ncbi.nlm.nih.gov/articles/PMC2906865)
- IHW's validity likewise requires the covariate to be independent of the p-values under the null. — [PubMed 27240256](https://pubmed.ncbi.nlm.nih.gov/27240256/)

### Inferences
- **Valid anchors, independent of outcome noise:**
  - `product_prices.valid_from` per category;
  - courier assignment changes per city (from `deliveries.courier`, by the first date a city's dominant courier switches);
  - new SKUs or categories introduced.

  Under "the price change had no effect on orders in category k", the anchor date does not depend on the orders noise in the simulator, so the DiD t at that date is distributed as at any other date. A caveat: if the simulator (or reality) sets prices *in response to* demand, independence fails. In this synthetic DB prices are written by the story (DECISIONS 12), so they are exogenous.
- **Analogue of Bourgon's limma warning:** If the robust z normalisation (median and MAD from the placebo dates) is computed over all dates including anchors, it stays valid. If it is computed after dropping anchored dates differently per series, the null changes. Keep the placebo distribution identical for anchored and exploratory tests.
- **Invalid or weak anchors:**
  - A spike in `cancelled_at` is the outcome (churn), so using it as an anchor for churn is circular.
  - Inventory = 0 for a SKU is a function of past demand (sales deplete stock). Testing "units sold dropped after stock hit zero" is mechanically true even without any story event, because units are capped at 0 while stocked out. It is a valid anchor only for *downstream* outcomes that are not mechanically coupled, such as substitution into other SKUs of the same category or sold-out tickets. Even then, the null should be calibrated with placebo stock-outs (other zero-inventory runs, for example ordinary replenishment gaps).
- **Courier changes:** They are exogenous to rating and late share. However, the courier change may itself have been *caused* by a planted delivery problem (DECISIONS mention that `delivery_days` drives a courier switch). That is fine for validity under the null, which concerns noise, not story; it only affects interpretation.

### Gaps
- I found no paper that directly treats "event dates from a treatment table" as an independent filter in time series. The argument above is an inference from Bourgon's condition plus the event-study logic in Q3.

## Q3. Event studies, staggered DiD and interrupted time series as the template; how many anchored tests and what threshold

### Takeaway
Finance event studies (MacKinlay 1997) and interrupted time series (Bernal et al. 2017) are the canonical templates for testing at **known** event dates. The event date is defined from outside the outcome series, a normal model is fitted on an estimation window that does not overlap the event, and the abnormal change in a pre-specified event window is tested. Staggered DiD (Callaway & Sant'Anna 2021; Sun & Abraham 2021) covers price changes in different categories at different dates. Its main practical lesson for the detective: compare each repriced category with not-yet-treated or never-treated categories, not with already-treated ones, and do not pool into one two-way fixed-effects coefficient. With roughly 20–60 anchored tests and α_A = 0.05–0.1, the threshold is z ≈ 2.8–3.3 instead of 5.25. Under the Gaussian approximation, that raises power on a 3.5-unit effect from about 4 % to about 55–75 %.

### Cited findings
- MacKinlay, "Event Studies in Economics and Finance", *Journal of Economic Literature* 35(1):13–39 (1997). It is the standard reference for measuring the effect of an economic event using abnormal returns around a known event date. — [EconPapers](https://econpapers.repec.org/RePEc:aea:jeclit:v:35:y:1997:i:1:p:13-39); [BU copy (scan)](https://www.bu.edu/econ/files/2011/01/MacKinlay-1996-Event-Studies-in-Economics-and-Finance.pdf). The BU PDF is a scanned image. I could not extract its text, so details of its estimation window, event window and CAR test are not quoted here.
- Bernal, Cummins & Gasparrini, "Interrupted time series regression for the evaluation of public health interventions: a tutorial", *IJE* 46(1):348–355 (2017). It uses segmented regression, specifies the impact model **in advance**, and handles overdispersion, autocorrelation, seasonality and time-varying confounders. A 2020 corrigendum fixes the regression equation. — [PMC5407170](https://pmc.ncbi.nlm.nih.gov/articles/PMC5407170/); [corrigendum PMC7750921](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7750921/)
- Callaway & Sant'Anna, "Difference-in-differences with multiple time periods", *J. Econometrics* 225(2):200–230 (2021). Group-time average treatment effects are identified under staggered adoption, and aggregation schemes give summary effects. The R package is `did`. — [EconPapers](https://econpapers.repec.org/RePEc:eee:econom:v:225:y:2021:i:2:p:200-230); [arXiv:1803.09015](https://arxiv.org/abs/1803.09015v4); [did vignette](https://cran.r-project.org/web/packages/did/vignettes/multi-period-did.html)
- Sun & Abraham, "Estimating dynamic treatment effects in event studies with heterogeneous treatment effects", *J. Econometrics* 225(2):175–199 (2021).
  - In two-way fixed-effects event-study regressions, the coefficient on a lead or lag can be contaminated by effects from other periods.
  - Apparent pretrends can arise from heterogeneity alone.
  - The authors propose an interaction-weighted estimator.
  — [arXiv:1804.05785](https://arxiv.org/abs/1804.05785v1); [DOI](https://doi.org/10.1016/j.jeconom.2020.09.006)

### Computed numbers (scipy, Gaussian, two-sided; not from a source)
- At z = 5.25, the two-sided p is 1.5e-7. One false event per run therefore corresponds to about 6.6 million Gaussian-equivalent independent tests. This reflects the heavy-tailed placebo null and the scan over dates, series and segments, not a literal count.
- Exploratory threshold after giving part of the budget away:

  | Exploratory budget | Threshold z |
  |---|---|
  | 1.0 | 5.25 |
  | 0.9 | 5.27 |
  | 0.8 | 5.29 |
  | 0.5 | 5.38 |

  The exploratory family barely notices.
- Bonferroni threshold z for m anchored tests:

  | α_A | m = 10 | m = 20 | m = 30 | m = 60 | m = 120 | m = 240 |
  |---|---|---|---|---|---|---|
  | 0.05 | 2.81 | 3.02 | 3.14 | 3.34 | 3.53 | 3.71 |
  | 0.10 | 2.58 | 2.81 | 2.94 | 3.14 | 3.34 | 3.53 |
  | 0.20 | 2.33 | 2.58 | 2.71 | 2.94 | 3.14 | 3.34 |

- The brief's example "z ≈ 3 for α = 0.05 over 20 tests" is confirmed: 3.02.
- 20 price changes × 5 lags with full Bonferroni at α = 0.1: z = 3.29. Correlated lags make this conservative. A max-over-lags placebo calibration gives a lower threshold.
- Power P(z > threshold) for a true mean shift of μ noise units:

  | Threshold | μ = 3 | μ = 3.5 | μ = 4 | μ = 4.5 | μ = 5 |
  |---|---|---|---|---|---|
  | 5.25 | 0.01 | 0.04 | 0.11 | 0.23 | 0.40 |
  | 3.53 | 0.30 | 0.49 | 0.68 | 0.83 | 0.93 |
  | 3.34 | 0.37 | 0.56 | 0.75 | 0.88 | 0.95 |
  | 3.14 | 0.44 | 0.64 | 0.81 | 0.91 | 0.97 |
  | 2.81 | 0.58 | 0.75 | 0.88 | 0.95 | 0.99 |

  These figures assume the "noise units" of a planted effect equal the z of the anchored DiD. If the anchored DiD uses fewer days or a weaker control, the realised z is lower.

### Inferences
- **Plausible size of the anchor family** (my estimate, to be checked with SQL on the real DB):
  - Price changes: about 10–30 (category, date) pairs, each with outcomes {orders, churn} plus a lag grid of about 5.
  - Courier changes: a few (city, date) pairs, each with outcomes {late share, rating, churn} and about 3 lags.
  - Stock-out runs: possibly dozens to hundreds per SKU. These should be aggregated (category-level "share of SKUs out of stock" crossing a threshold) or left in the exploratory family, otherwise they blow up m.

  A realistic m_A is 60–200, which gives a threshold of z ≈ 3.1–3.5 at α_A = 0.1.
- **Design rule from Sun & Abraham and Callaway & Sant'Anna:** For each price anchor, use as control the categories *not repriced within ±(window + max lag)*. The existing DECISIONS 41 compares against "the other categories", which may include categories repriced shortly before. Exclude those.
- **Design rule from ITS and event studies:** Fit the pre-period (estimation window) strictly before the anchor, with a gap equal to the settle time (DECISIONS 41 already uses one week). Specify the event window (for example 28 days) and the lag grid before running.

### Gaps
- I could not extract MacKinlay's text (scanned PDF), so specific formulas (CAR, J-statistics) are not cited from the source.
- The real counts of anchors in the DB were not queried here.

## Q4. Data-driven hypothesis generation pitfalls (forking paths, selective inference) and how to keep anchors honest

### Takeaway
Gelman & Loken's "garden of forking paths" shows that a multiplicity problem exists even with one analysis if the analysis choices depend on the data. For anchors, the rule is that **everything that defines an anchored test must be computable without the outcome KPI**:
- the anchor date and unit (from the treatment table);
- the outcome family;
- the window lengths;
- the lag grid;
- the direction (one-sided, for example price up → orders down, churn up);
- the control group.

Any step that does use the outcome must be paid for, either by counting it in m or by sample splitting or data fission.

### Cited findings
- Gelman & Loken (2013), "The garden of forking paths". Researcher degrees of freedom create a multiple-comparisons problem even when only one analysis is performed, because the analysis "would not feel like fishing… it would all seem so reasonable". Gelman recommends running the whole set of comparisons of interest rather than adjusting only the best one. — [Wikipedia summary](https://en.wikipedia.org/wiki/Forking_paths_problem); [American Scientist, "The Statistical Crisis in Science" (2014)](https://www.americanscientist.org/node/3579); [Gelman blog 2024](https://statmodeling.stat.columbia.edu/2024/06/24/forking-paths-and-workflow-in-statistical-practice-and-communication/)
- Bourgon et al.: filters that use the outcome, such as the maximum of the class means or clusters built from the same data, produce anti-conservative p-values. — [PMC2906865](https://pmc.ncbi.nlm.nih.gov/articles/PMC2906865)
- Leiner, Duan, Wasserman & Ramdas, "Data fission: splitting a single data point", *JASA* 120(549):135–146 (2025). It splits each observation into two parts with a tractable joint distribution, so one part can be used for selection and the other for inference. One example is the Gaussian X + τZ and X − Z/τ, a generalisation of Rasines & Young's additive-noise approach. — [arXiv:2112.11079](https://arxiv.org/abs/2112.11079); [IDEAS](https://ideas.repec.org/a/taf/jnlasa/v120y2025i549p135-146.html)
- Ignatiadis & Huber 2021: cross-weighting (learning weights on other folds) is what makes data-driven weights provably valid. — [arXiv:1701.05179](https://arxiv.org/pdf/1701.05179)
- Bernal et al. 2017: the ITS impact model should be specified in advance. — [PMC5407170](https://pmc.ncbi.nlm.nih.gov/articles/PMC5407170/)

### Inferences (honesty rules for the detective)
1. **Anchor catalogue first:** Build it in a separate function that receives only treatment tables (`product_prices`, `deliveries.courier` assignments, `inventory`) and never the KPI series. Freeze it, write it to the report as the pre-registration, and only then run tests. Students can see that the list exists before the outcome.
2. **Lag grid:** Either count every lag in m (Bonferroni), or take max |t| over lags and calibrate that max against placebo anchors (see Q5). Do not pick the best lag and then test it at the single-test threshold. This is a real issue in the current `lag_search()`, which keeps the max-|t| (anchor, lag) and compares it with LAG_MIN_T = 3 without correcting for the number of anchors × lags. That is acceptable for attributing a cause to an already-reported event, but not for *reporting* new events.
3. **Direction:** Pre-specify one-sided directions where economics gives them (price up → orders down and churn up; worse courier → late share up and rating down). One-sided tests halve α per test, which lowers z by about 0.2.
4. **No anchors from outcomes:** Exclude `cancelled_at` spikes and stock-outs as anchors for units, or handle them with explicit placebo calibration (Q2).
5. **No re-use of anchored hits as exploratory confirmation:** An event reported via the anchored family must say so ("confirmed as a pre-registered price-change test, threshold z ≥ 3.2"). That keeps it explainable and auditable.
6. **Check the verifier analogy:** The known-answer verifier gets about 87 % at z ≥ 3 with about 3 % false alarms precisely because it tests one pre-specified hypothesis per event. Anchors recreate that situation blindly, with the price list playing the role of the answer key.

### Gaps
- The full Gelman & Loken paper was not retrieved. Claims come from its summaries and Gelman's own blog and article.

## Q5. Practical design: anchor catalogue via SQL, outcome families, lag search with multiplicity control, calibration

### Takeaway
Recommended combined design:
1. A DuckDB anchor catalogue built from treatment tables only.
2. For each anchor, a pre-specified outcome family with one-sided directions and a small lag grid.
3. Per-anchor max-|t| over its lags and outcomes, calibrated by **placebo anchors** (the same test at random non-anchor dates of the same unit). This reuses the existing placebo-in-time machinery and handles lag correlation and heavy tails.
4. A Bonferroni or weighted Holm split giving the anchored family α_A ≈ 0.1 of the 1-per-run budget.
5. Optionally, a Bretz-style graph passing α from a confirmed primary outcome (orders) to secondary outcomes (churn).

The whole procedure is a few hundred DiD computations plus about 1,000 placebo dates per anchor, well under 60 s in numpy. Each reported event keeps its DiD number and the SQL that defines its anchor.

### Inferences / design sketch (my synthesis from the sources above)
- **Anchor SQL (DuckDB), price changes:**
  ```sql
  SELECT p.category, pp.valid_from AS anchor_day,
         avg(pp.price / prev_price - 1) AS price_change_pct
  FROM (SELECT product_id, valid_from, price,
               lag(price) OVER (PARTITION BY product_id ORDER BY valid_from) AS prev_price
        FROM product_prices) pp
  JOIN products p USING (product_id)
  WHERE prev_price IS NOT NULL AND price <> prev_price
  GROUP BY 1, 2;
  ```
- **Anchor SQL (DuckDB), courier changes:** compute the dominant courier per (city, week) from `deliveries`, then take the first week where it differs from the previous 4 weeks.
- **Anchor SQL (DuckDB), stock-outs:** aggregate to category-day "share of SKUs with inventory = 0" and take the first day the share exceeds its 95th percentile. Treat this as a weaker anchor (Q2).
- **Outcome families (pre-specified; directions in brackets):**

  | Anchor | Outcome family |
  |---|---|
  | Price change in category k | orders/units in k (opposite sign to price, lag 0); churn hazard of customers who bought k (+, lags 14/28/42); revenue in k (report only) |
  | Courier change in city c | late-delivery share in c (±, lag 0); mean rating in c (lag 7/14); churn in c (lags 28/42); delivery-topic tickets in c |
  | Stock-out in category k or SKU s | substitution: units of the other SKUs in k (+); "sold out" topic tickets (+); not units of s itself (mechanical) |

- **Control group:** units not anchored within ±(window + max lag), following Callaway & Sant'Anna / Sun & Abraham ([CS 2021](https://arxiv.org/abs/1803.09015v4); [SA 2021](https://arxiv.org/abs/1804.05785v1)).
- **Statistic per anchor:** T_a = max over (outcome, lag) of the signed DiD t in the pre-specified direction. The null of T_a is obtained by computing the same max at all other admissible dates of the same unit and outcomes (placebo-in-time, as `placebo_z` already does). The anchored p_a is the rank of T_a among the placebos. For example, with 700 placebo days the smallest attainable p is about 1/700 ≈ 0.0014, which is adequate for m_A ≈ 50 at α_A = 0.1 (needs p ≤ 0.002). With fewer days, use the robust-z Gaussian tail as `placebo_z` does.
- **Multiplicity across anchors:** Bonferroni or weighted Holm at α_A over the m_A anchors. Weights can favour price anchors (exogenous, many planted effects) over stock-out anchors. Weighted Holm is a few lines in Python, since `multipletests` has no weights ([statsmodels](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)).
- **Gatekeeping (Bretz 2009):** If the orders test for anchor a is rejected, give its α share to churn at lags 14–42 for the same anchor. This directly targets miss (b). If it is not rejected, churn is still tested at its own small share (fallback, Wiens & Dmitrienko 2005).
- **Double reporting:** An event found by both families is reported once. Anchored status gives an "anchored, pre-registered" label in the explanation.
- **Calibration check:** On the no-story twins (used today to set 5.25), run the anchored family with the twins' own price lists. If the twins have no price changes, inject synthetic placebo anchors at random dates. Verify the anchored family yields at most about α_A false events per run. This is the empirical check that the Gaussian table in Q3 is not too optimistic.
- **Compute cost:** m_A ≈ 100 tests × about 10 (outcome, lag) cells × about 700 placebo dates is about 7·10^5 window means. Vectorised with cumulative sums, that takes well under a second.

### Gaps
- No source directly prescribes "placebo-anchor max-over-lags" for this setting. It combines the event-study placebo logic with the detective's existing placebo-in-time z.
- The real numbers of price, courier and stock-out anchors in the synthetic DB, and the realised z of planted events at their anchors, were not measured here. A quick DuckDB count and a rerun of the known-answer verifier restricted to anchored events would settle the expected gain.
