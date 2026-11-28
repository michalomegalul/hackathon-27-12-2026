# Benchmarks with planted events and the theoretical limit of blind detection

Context: a blind detective scans about 150–300 daily KPI series, plus pair-level series, with several candidate dates per series, over about 670 days (1.84 years). It reports at placebo z ≥ 5.25. Each story plants 5 events at verifier effect d ≈ 3.5 (medium) or 5 (easy). The detective finds 2–3 of 5 with 3–5 false finds per run. In F1 terms, 2.5 true positives and 4 false positives give precision ≈ 0.38, recall 0.50 and **F1 ≈ 0.43**.

Scripts and raw output:
- `/tmp/claude-1000/-home-mekysjos-hackathon-27-12-2026/4fca2120-1e48-4357-846a-52156f341b49/scratchpad/limits.py`
- `/tmp/claude-1000/-home-mekysjos-hackathon-27-12-2026/4fca2120-1e48-4357-846a-52156f341b49/scratchpad/limits2.py`

They were run with numpy and scipy through `uv run`. All numbers in the theory section come from these scripts.

## Q1. Published benchmarks with planted events and answer keys, and what blind methods score on them

### Takeaway
No published benchmark plants causal business events in a simulated commerce database and asks for blind detection; I found none. The nearest relatives are change-point, anomaly and root-cause benchmarks, and the best methods there typically reach F1 or top-1 accuracy of only about 0.4–0.7. That is despite much easier tasks: the anomaly time is usually given, or there is one series. Out-of-the-box change-point detectors do not beat a "no change points" baseline at all. An F1 of about 0.43 with no knowledge of time, target or series sits in the same band as the state of the art on these benchmarks.

### Cited Findings

**Change-point detection: TCPD (van den Burg & Williams 2020)**
- The benchmark has 37 annotated real series and 14 algorithms. It scores F1 with a margin of M = 5 points and the "Cover" segmentation metric. "Default" uses default parameters; "Oracle" is a grid search over hyperparameters for each series. — [van den Burg & Williams, arXiv 2003.06222](https://arxiv.org/abs/2003.06222)
- Default, univariate (Cover / F1):

  | Method | Cover | F1 |
  |---|---|---|
  | binseg | 0.672 | 0.698 |
  | pelt | 0.652 | 0.674 |
  | amoc | 0.668 | 0.653 |
  | bocpd | 0.594 | 0.662 |
  | **zero** (no change points) | 0.566 | 0.645 |
  | wbs | 0.264 | 0.365 |
  | kcpa | 0.069 | 0.124 |

  — [arXiv 2003.06222, Table 2](https://arxiv.org/pdf/2003.06222)
- Oracle, univariate F1: bocpd 0.886, segneigh 0.875, binseg 0.873. Oracle, multivariate F1: bocpd 0.941. — [arXiv 2003.06222, Table 2](https://arxiv.org/pdf/2003.06222)
- Direct quotes: "no method performs significantly better than the zero method on the Default experiment". The zero baseline beating many methods "suggests that many methods return a large number of false positives". — [arXiv 2003.06222](https://arxiv.org/pdf/2003.06222)

**Time-series anomaly detection: TSB-AD (Liu & Paparrizos, NeurIPS 2024 Datasets & Benchmarks)**
- The benchmark has 1,020 curated series (TSB-AD-U and TSB-AD-M) and 40 algorithms. It recommends VUS-PR as the metric. — [NeurIPS 2024 paper](https://proceedings.neurips.cc/paper_files/paper/2024/file/c3f3c690b7a99fba16d0efd35cb83b2c-Paper-Datasets_and_Benchmarks_Track.pdf)
- Best univariate methods, mean scores (Table 5):

  | Method | VUS-PR | AUC-PR | Standard-F1 | Event-based-F1 |
  |---|---|---|---|---|
  | Sub-PCA | 0.42 | 0.37 | 0.42 | 0.49 |
  | KShapeAD | 0.40 | – | 0.39 | – |
  | MOMENT (fine-tuned foundation model) | 0.39 | – | 0.35 | – |
  | AnomalyTransformer | 0.12 | – | 0.12 | – |

  Best multivariate: CNN, VUS-PR 0.31, Standard-F1 0.37. Point-adjusted F1 inflates the scores; for example SR gets PA-F1 0.87 against Standard-F1 0.38. — [NeurIPS 2024 paper, Table 5](https://proceedings.neurips.cc/paper_files/paper/2024/file/c3f3c690b7a99fba16d0efd35cb83b2c-Paper-Datasets_and_Benchmarks_Track.pdf)
- Its stated conclusion is that "simpler architectures and statistical methods" often beat complex neural models. — [same](https://proceedings.neurips.cc/paper_files/paper/2024/file/c3f3c690b7a99fba16d0efd35cb83b2c-Paper-Datasets_and_Benchmarks_Track.pdf)

**UCR anomaly archive (Wu & Keogh)**
- Wu & Keogh say most exemplars in Yahoo, Numenta (NAB), NASA and similar benchmarks have one or more of four flaws: triviality (solvable with one line of MATLAB), unrealistic anomaly density, mislabeled ground truth, and run-to-failure bias. They conclude that "much of the apparent progress in recent years may be illusionary", and they propose the UCR Anomaly Archive instead. — [Wu & Keogh, arXiv 2009.13807 / IEEE TKDE](https://arxiv.org/abs/2009.13807)

**Root-cause localization in multi-dimensional KPIs, with a known anomaly time: Squeeze, RiskLoc**
- RiskLoc (Kalander 2022) tests on two kinds of data. The first is the semi-synthetic sets A and B0–B4 from Squeeze (Li et al., ISSRE 2019), with 9 scenarios × 100 instances: root cause in layer 1–3, with 1–3 elements. The second is new synthetic sets S, L and H, with up to 24 million leaf elements in H. — [RiskLoc, arXiv 2205.10004](https://arxiv.org/abs/2205.10004)
- How the synthetic sets are generated:
  - Normal leaves get the forecast f = v·N(1, σ), with σ ~ U[0, 0.25] (U[0, 0.10] for L).
  - Anomalies scale x by (1 − N(s, d)), with severity s ~ U[0.25, 1.0] and deviation d ~ U[0, 0.1].
  - Leaves are zeroed with probability U[0, 0.25].
  - "there is no guarantee that the root causes are significant".
  - Source: [arXiv 2205.10004, App. A](https://arxiv.org/pdf/2205.10004)
- F1 by noise level is the cleanest "F1 against SNR" table I found. In the B0→B4 series, the residual noise of normal leaves rises 0.80% → 3.19% → 6.38% → 9.55% → 12.7% (mean anomaly significance 0.06 → 0.14):
  - Squeeze, scenario (3,3): 0.95 / 0.93 / 0.86 / 0.77 / 0.72.
  - AutoRoot, scenario (3,3): 0.81 / 0.80 / 0.72 / 0.83 / 0.71.
  - RiskLoc stays at about 0.94–0.99 on B0–B3.
  - HotSpot falls to about 0.24–0.33 in layer 3.
  - Source: [arXiv 2205.10004, Table 6](https://arxiv.org/pdf/2205.10004)
- On the harder sets, F1 for the best method (RiskLoc) against the next best:

  | Dataset | RiskLoc | Next best |
  |---|---|---|
  | A★ | 0.464 ± 0.10 | Squeeze 0.295 |
  | S | 0.635 | AutoRoot 0.448 |
  | L | 0.677 | AutoRoot 0.527 |
  | H | 0.491 | AutoRoot 0.349 |

  Adtributor and R-Adtributor score ≤ 0.07. These numbers are for localization only: the anomalous timestamp is given. — [arXiv 2205.10004, Table 3](https://arxiv.org/pdf/2205.10004)
- The official Squeeze repository warns of "two known severe issues" in its code (a calculation error, and weights that can go negative), so Squeeze baselines vary between papers. — [Squeeze GitHub](https://github.com/netmanaiops/squeeze)

**Microservice root-cause analysis: RCAEval, PetShop and a later critique**
- RCAEval (Pham et al., WWW'25 companion) has 735 failure cases with injected faults in three sub-sets: RE1 has 375 cases with metrics only; RE2 has 270 multi-source cases; RE3 has 90 code-level faults. It defines 11 fault types and 15 baselines. Faults are injected with stress-ng and tc. — [RCAEval, arXiv 2412.17015](https://arxiv.org/html/2412.17015v5)
- On RE2 (Train Ticket), the best methods score:

  | Method | AC@1 | AC@3 |
  |---|---|---|
  | BARO multi-source | 0.69 | 0.82 |
  | TraceRCA | 0.66 | 0.79 |
  | CIRCA | 0.32 | 0.47 |
  | RCD | 0.10 | 0.64 |

  BARO is near-perfect on disk faults but weak on network delay and loss. — [arXiv 2412.17015v5](https://arxiv.org/html/2412.17015v5)
- PetShop (Hardt et al., CLeaR 2024) has 68 injected issues (36 latency, 32 availability). Latency issues add 0.25–2 s; misconfigurations affect 1–10% of requests. — [PetShop, arXiv 2311.04806](https://arxiv.org/html/2311.04806v2)
  - Top-1 recall ranges from 0.00 for ε-diagnosis to 0.83 for plain correlation (high traffic, availability).
  - CIRCA scores 0.00–0.75 top-1. RCD scores 0.00–0.58 top-1.
  - Simple correlation ranking is the strongest top-1 baseline overall.
  - "all methods produce false root causes during normal operation".
  - Source: [arXiv 2311.04806](https://arxiv.org/html/2311.04806v2)
- Fang et al. (2025) argue that popular RCA benchmarks oversimplify fault propagation. On their more realistic benchmark, 11 state-of-the-art models average Top@1 0.21 and the best reaches 0.37. — [arXiv 2510.04711](https://arxiv.org/abs/2510.04711v2)

**Causal discovery: CausalRivers (ICLR 2025)**
- It uses real river-discharge data with known flow graphs: 666 stations in eastern Germany and 494 in Bavaria, at 15-minute resolution, 2019–2023. Its finding is that "simple strategies can be robust" while many causal-discovery methods struggle. — [CausalRivers, arXiv 2503.17452](https://arxiv.org/abs/2503.17452)

### Inferences
- Every benchmark above that reports both detection and localization makes the task easier than the detective's. RCA sets give the anomaly time and ask only "where". TSB-AD and TCPD give one series and ask only "when". Even so, the best scores are about 0.4–0.7. The detective must find both "where" (one of about 300 series or pairs) and "when", under a strict false-alarm budget, so F1 ≈ 0.43 is not obviously below the state of the art.
- The TCPD result (no default method beats "report nothing") and the TSB-AD gap between point-adjusted and standard F1 both say that false positives drive the scores. That matches the detective's 3–5 false finds.
- Benchmark noise levels are not stated in units comparable to "d in a DiD z", except in the RiskLoc B-series. So the comparison is qualitative.

### Gaps
- I found no published benchmark of business, marketing or retail event detection with a causally simulated database and a planted answer key. M5 and similar retail sets have no planted causes.
- I did not retrieve:
  - CausalTime results;
  - NAB scores;
  - TSB-UAD numbers;
  - CausalRivers per-method numbers;
  - per-method RCAEval numbers on RE1 and RE3 (the fetched page showed only RE2).
- No benchmark reports F1 against an SNR in noise units the way the user's setup does. RiskLoc's B-series is the closest.

## Q2. How much effect is needed for blind detection at about 1 false alarm per year

### Takeaway
With a Gaussian null and Bonferroni correction over about 300 series × about 100 effective onset windows per series per year, the required threshold is only z* ≈ 4.0. That gives 50% power at d ≈ 4.0 and 80% at d ≈ 4.8. Under that assumption, d = 3.5 would be detected about 30% of the time and d = 5 about 85%.

The detective's threshold of 5.25 is far stricter than Gaussian Bonferroni needs: it would allow about 13 million independent tests per year. Since it still sees 3–5 false finds, its null must be heavy-tailed. Sources of heavy tails:
- standard deviations estimated from few placebo dates;
- autocorrelation;
- seasonality;
- pair-level multiplicity.

Against a true z of 5.25, d = 3.5 is detected only 4–15% of the time, and d = 5 about 40–48%. So finding 2–3 of 5 events at d = 3.5 is already above the naive ceiling. That suggests the detective's own z for true events is larger than the verifier's d. **It is near the ceiling for d = 3.5, and at or slightly above the ceiling for d = 5.**

### Cited Findings (theory sources)
- The scan statistic attains the minimax detection rate for anomalous clusters "to within a logarithmic factor". The price of unknown location and extent is a √(2 log(number of effectively distinct candidate sets)) term. — [Arias-Castro, Candès & Durand 2011, Ann. Statist. 39(1)](https://projecteuclid.org/journals/annals-of-statistics/volume-39/issue-1/Detection-of-an-anomalous-cluster-in-a-network/10.1214/10-AOS839.full); [arXiv 1001.3209](https://arxiv.org/abs/1001.3209)
- Higher criticism and the sparse detection boundary: with k = n^(1−β) signals of size μ = √(2r log n), detection is possible iff r > ρ*(β). Here ρ*(β) = β − 1/2 for 1/2 < β ≤ 3/4, and (1 − √(1−β))² for 3/4 < β < 1. — [Donoho & Jin 2004, Ann. Statist. 32(3)](https://projecteuclid.org/journals/annals-of-statistics/volume-32/issue-3/Higher-criticism-for-detecting-sparse-heterogeneous-mixtures/10.1214/009053604000000265.full). I wrote this from memory; the paper was not fetched in this session.
- Recovering the signals is harder than detecting that some exist:
  - Almost-full recovery, or FDR-controlled discovery with power → 1, needs r > β.
  - Exact support recovery needs √r > 1 + √(1−β).
  - These are the Hamming-loss and multiple-testing boundaries of [Butucea, Ndaoud, Stepanova & Tsybakov 2018, arXiv 1512.01832](https://arxiv.org/abs/1512.01832) and [Arias-Castro & Chen 2017, arXiv 1604.07520](https://arxiv.org/abs/1604.07520). These are also from memory, not fetched in this session.

### Computed numbers (from my scripts)

**1) Effective number of onset windows in one series.**
- Setup: simulated iid N(0,1) daily noise, T = 670, window 28 days after vs 28 before, scanned over every onset date, 2,000 simulations.
- Median of the maximum z is 2.65; the 95% quantile is 3.50.
- That corresponds to **M_eff ≈ 175–220 independent tests per series**, or about **95–120 per year**. Scanning every date is therefore worth roughly 4 independent windows per 28-day window length.

**2) Bonferroni threshold and power under a Gaussian null.**
- One-sided test; p per test = 1.84 / M, which allows 1 false alarm per year over 1.84 years. Power = Φ(d − z*).

  | Series | Windows/yr | M (1.84 yr) | z* | Power d=3.5 | Power d=5 | d for 50% | d for 80% |
  |---|---|---|---|---|---|---|---|
  | 150 | 90 | 24.8k | 3.79 | 0.38 | 0.89 | 3.79 | 4.64 |
  | 300 | 52 | 28.6k | 3.83 | 0.37 | 0.88 | 3.83 | 4.67 |
  | 300 | 90 | 49.6k | 3.96 | 0.32 | 0.85 | 3.96 | 4.80 |
  | 300 | 365 (every day independent, worst case) | 201k | 4.29 | 0.22 | 0.76 | 4.29 | 5.13 |
  | 600 (series + pairs) | 90 | 99k | 4.13 | 0.27 | 0.81 | 4.13 | 4.97 |
  | 600 | 365 | 402k | 4.44 | 0.17 | 0.71 | 4.44 | 5.28 |

- So under a Gaussian null the expected number found out of 5 is about 1.5–1.9 at d = 3.5 and about 4.0–4.4 at d = 5.

**3) What z* = 5.25 implies.**
- Gaussian one-sided p(5.25) = 7.6e-8, which means 1 false alarm per year at about **13 million independent tests per year**. That is about 100× more than 300 series × 365 days.
- So 5.25 only makes sense as compensation for heavy tails. Suppose each z is standardized by an SD estimated from n placebo windows, so the null is t with n−1 degrees of freedom. Then 5.25 is equivalent to a Gaussian threshold of:

  | Placebo windows n | Gaussian-equivalent threshold |
  |---|---|
  | 10 | 3.47 |
  | 20 | 4.08 |
  | 40 | 4.54 |
  | 80 | 4.85 |

- With n ≈ 20–40, the threshold 5.25 is roughly the Gaussian Bonferroni level from table 2. This is consistent with the observed false-alarm rate: 3–5 per 1.84 years, against a target of about 1.8.

**4) Power at the threshold 5.25 itself.**
- If the detective's z equals the verifier's d, with d fixed (noncentral t for n placebo windows):

  | n | d=3.5 | d=5 | d=6 | d=7 |
  |---|---|---|---|---|
  | 10 | 0.15 | 0.48 | 0.72 | 0.88 |
  | 20 | 0.10 | 0.45 | 0.74 | 0.92 |
  | 40 | 0.07 | 0.43 | 0.75 | 0.94 |
  | Gaussian | 0.04 | 0.40 | 0.77 | 0.96 |

- Expected number found out of 5 at z* = 5.25 with a Gaussian z, where each event's d varies with SD σ_d:

  | Mean d | σ_d = 0 | σ_d = 0.5 | σ_d = 1.0 |
  |---|---|---|---|
  | 3.5 | 0.20 | 0.29 | 0.54 |
  | 4 | 0.53 | 0.66 | 0.94 |
  | 5 | 2.01 | 2.06 | 2.15 |
  | 6 | 3.87 | 3.74 | 3.51 |

**5) Cost of a noisier blind statistic.**
- The blind detective must estimate target, onset and window, so its noise unit is k times the verifier's. Its z is then d / k.
- Power at 5.25 for d = 5 / 6 / 7:
  - k = 1.1: 0.24 / 0.58 / 0.87
  - k = 1.2: 0.14 / 0.40 / 0.72
  - k = 1.3: 0.08 / 0.26 / 0.55
- Each 10% of extra noise from a misplaced onset, wrong window or diluted target costs roughly 0.5 units of d.

**6) Sparse-signal boundaries.**
- Setup: k = 5 true events among n effective tests, so β = 1 − log 5 / log n. Values below are μ = √(2 r log n).

  | n | Detect "something" (higher criticism) | Almost-full recovery / FDR | Exact recovery | √(2 log n) |
  |---|---|---|---|---|
  | 2×10⁴ | 2.66 | 4.07 | 6.24 | 4.45 |
  | 5×10⁴ | 2.86 | 4.29 | 6.45 | 4.65 |
  | 10⁵ | 3.00 | 4.45 | 6.59 | 4.80 |
  | 10⁶ | 3.46 | 4.94 | 7.05 | 5.26 |

- These are asymptotic first-order rates; for finite n the real thresholds are higher.
- At n ≈ 5×10⁴, d = 3.5 lies between "you can tell something happened" (about 2.9) and "you can list most of the events with controlled errors" (about 4.3).
- d = 5 is above the almost-full-recovery boundary but below the exact-recovery boundary (about 6.5). Finding all 5 every time with almost no false alarms would need d ≈ 6.5–7.

### Inferences
- **Ceiling at d = 3.5.** In the best case (Gaussian null, about 300 series, about 100 windows per year), an ideal Bonferroni scanner finds about 1.5–1.9 of 5. Information-theoretically, d = 3.5 is below the almost-full-recovery boundary of about 4.3. Finding 2–3 of 5 at d = 3.5 is therefore at or above the theoretical ceiling for a blind scan with 1 false alarm per year.
  - If the detective really does find 2–3 at verifier d = 3.5 with z* = 5.25, its z at true events must on average be larger than d (about 5.25+). Possible reasons:
    - it tests the sub-series or pair where the effect is concentrated;
    - its noise unit is smaller than the verifier's.
  - Alternatively, some "finds" are matched generously (date tolerance, related KPIs).
  - Worth checking: compute the detective's z at the true series and date (an oracle-located blind z) and compare it with the verifier's d. That would split the loss into calibration (threshold) and localization (k > 1).
- **Ceiling at d = 5.** The ideal Gaussian-Bonferroni scanner finds about 4–4.4 of 5. The z = 5.25 rule finds about 2 of 5 if z = d. The gap between these is the price of heavy-tailed nulls.
  - Improving null calibration could recover much of it: more placebo windows; a robust or MAD scale; modelling seasonality and autocorrelation; empirical-null or extreme-value tail fitting per series family.
  - Recovering it this way is better than lowering the threshold.
- **False finds.** 3–5 false finds per 1.84 years is about 2× the target. Some may be real but unplanted effects of the simulator, such as spillovers from planted events, calendar effects or customer-count growth. They are then not statistical false alarms, and the answer key would need "tolerated side-effects".
- **Reasonable reference point.** Under 1 false alarm per year, expect:

  | Event d | Expected found of 5 |
  |---|---|
  | 3.5 | about 1–2 |
  | 5 | about 2–4 |
  | ≥ 6.5–7 | about 4.5+ |

  The result depends mostly on how heavy-tailed the null of the blind z is.

### Gaps
- Siegmund & Venkatraman (1995) and Siegmund–Yakir give closed-form tail approximations for scan statistics. I did not fetch them; I used simulation instead (point 1 above).
- The Donoho–Jin, Butucea et al. and Arias-Castro–Chen boundary formulas are quoted from memory (standard results), not re-read in this session. The report writer should treat the exact constants as standard but unverified here.
- The effective number of tests for correlated KPI series is unknown. Series built from the same orders are correlated, which lowers M_eff and helps; pair-level series raise it. The tables bracket it at 150–600 series.
- All power numbers assume the detective's z for a true event equals the verifier's d. That assumption should be measured in the system rather than assumed.
