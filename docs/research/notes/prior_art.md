# Prior Art: Story-Driven / Causal / Relational Synthetic Data Generation (for Story2Data)

Research date: 2026-11-24. Scope: what exists, what it can and cannot do re "a story that is traceable in the data", and where the Story2Data pipeline (LLM story -> YAML spec -> deterministic agent-based sim -> Postgres -> LLM text fill -> blind detective -> recovery score) can differentiate.

## 1. Commercial / open-source synthetic data tools (SDV, Faker, Mimesis, Gretel, MOSTLY AI, Synthea, YData, Tonic, DataCebo)

### Takeaway
The mainstream tools fall into three groups: (a) "fit-and-sample" privacy synthesizers (SDV/DataCebo, MOSTLY AI, Gretel/NeMo Safe Synthesizer, YData) that copy the statistics of an existing real dataset; (b) from-scratch LLM/schema generators (NeMo Data Designer, YData text-to-dataset, Tonic Fabricate) that produce plausible rows from a prompt; (c) rule/value fakers (Faker, Mimesis). None of them take a dated causal narrative ("in March a competitor opened, churn in segment X rose 15% with a 2-week lag") as a first-class input and guarantee that it is recoverable from the output. The closest structural analogue is Synthea (state-machine simulation with modules), but it is healthcare-only and has no "story -> answer key -> recovery check" loop.

### Cited Findings
**SDV / DataCebo**
- SDV's multi-table HMASynthesizer uses a hierarchical ML algorithm that learns from real data; the community SDV version is described as handling "limited columns in up to 5 tables with a depth of 1" — [SDV docs: Synthesizers](https://docs.sdv.dev/sdv/multi-table-data/modeling/synthesizers)
- SDV is distributed under the Business Source License (non-production use free; production use needs commercial license); no longer MIT despite older roundups — [PyPI sdv](https://pypi.org/project/sdv/1.6.0/); [devtoollab 2026 comparison](https://devtoollab.com/blog/best-synthetic-data-generation-tools); [Hivebook SDV](https://hivebook.wiki/wiki/sdv-synthetic-data-vault-for-tabular-data)
- Implication: SDV requires real seed data to fit; it reproduces existing correlations but has no mechanism for injecting dated events with quantified causal effects (inference; see below).

**Gretel -> NVIDIA**
- NVIDIA acquired Gretel in March 2025 (nine-figure deal, above Gretel's last $320M valuation; ~80 staff) — [TechCrunch](https://techcrunch.com/2025/03/19/nvidia-reportedly-acquires-synthetic-data-startup-gretel); [Seedtable](https://seedtable.com/exits/gretel-labs-inc)
- Gretel tech now survives as two open-source NeMo components: NeMo Data Designer (generate synthetic datasets for training/evaluation) and NeMo Safe Synthesizer (privacy-safe copy of a sensitive table) — [druce.ai vendor wiki](https://druce.ai/governance/wiki/vendors/gretel)
- NeMo Data Designer: Apache 2.0, generates data via statistical samplers, LLMs, or seed datasets, with "dependency-aware generation" between fields and LLM-as-judge validators; paper arXiv 2609.17699 (Sep 2026) — [GitHub NVIDIA-NeMo/DataDesigner](https://github.com/NVIDIA-NeMo/DataDesigner/blob/main/README.md); [arXiv 2609.17699](https://arxiv.org/html/2609.17699v1)
- Note: Data Designer is column/record-oriented (sampler + LLM columns); I found no evidence of native multi-table relational FK generation or timeline/event injection — gap, not verified in full docs.

**MOSTLY AI**
- Released an open-source Synthetic Data SDK (`mostlyai`, Apache 2.0) in early 2025; LOCAL mode for on-prem training or CLIENT mode against hosted platform; powered by TabularARGN, built-in differential privacy, supports tabular + textual data — [MOSTLY AI blog](https://mostly.ai/blog/unlocking-ai-training-data-for-all-mostly-ai-releases-worlds-first-industry-grade-open-source-toolkit-for-synthetic-data); [arXiv 2508.00718](https://arxiv.org/html/2508.00718v1); [GitHub mostly-ai/mostlyai](https://github.com/mostly-ai/mostlyai)
- MOSTLY AI site now branded "MOSTLY AI powered by Syntho" (suggests a merger/acquisition by Syntho; details not verified) — [mostly.ai](https://mostly.ai/)
- Like SDV, it is a fit-on-real-data synthesizer (privacy use case), not a scenario injector.

**YData**
- KPMG acquired YData in October 2025; open-source `ydata-synthetic` still updated as of April 2026 — [aitoolalliance 2026](https://www.aitoolalliance.com/best-ai-synthetic-data-generation-tools-2026/)
- YData SDK has "text to dataset": creating tabular and multi-table databases from natural-language descriptions without an existing dataset via an LLM Synthesizer — [YData SDK docs](https://docs.sdk.ydata.ai/latest/synthetic_data/text_to_dataset/)

**Tonic**
- Tonic.ai acquired Fabricate in early 2025 to add from-scratch relational data generation; Fabricate has an agentic interface where users describe a schema conversationally and it drafts a generation plan; suite = Structural (production-based), Fabricate (from scratch), Textual (unstructured) — [aitoolalliance 2026](https://www.aitoolalliance.com/best-ai-synthetic-data-generation-tools-2026/); [Tonic comparison page](https://www.tonic.ai/synthetic-data/best-synthetic-data-tools)
- Tonic Fabricate is the closest commercial competitor on "describe a company DB in words -> get a relational DB", but marketing targets test data, not embedded verifiable narratives (inference; no evidence of story/answer-key features found).

**Synthea**
- Synthea (MITRE) is an open-source synthetic patient population simulator; each patient progresses birth-to-death through disease modules = state machines (Generic Module Framework) with delays, guards, encounters, conditional/probabilistic transitions; Monte Carlo — [JAMIA paper](https://academic.oup.com/jamia/article/25/3/230/4098271); [PySynthea arXiv 2606.28346](https://arxiv.org/html/2606.28346v1)
- Software license: Apache 2.0, 3.5k stars, active — [GitHub synthetichealth/synthea](https://github.com/synthetichealth/synthea). (One secondary source says CC BY 4.0 — [MITRE FHIR overview](https://mitre.github.io/fhir-for-research/modules/synthea-overview) via search snippet; the GitHub repo states Apache 2.0, trust the repo.)
- PySynthea (June 2026) is a Python-native re-implementation for scalable generation — [arXiv 2606.28346](https://arxiv.org/html/2606.28346v1)

**Faker / Mimesis** (not re-fetched this session; standard knowledge, repos cited)
- Value-level fake generators (names, addresses, IBANs, locales incl. cs_CZ in Faker); no relations, distributions, or time dynamics — [Faker](https://github.com/joke2k/faker); [Mimesis](https://github.com/lk-geimfari/mimesis)

### Inferences
- The whole commercial market optimizes for (1) privacy-preserving fidelity to real data or (2) realistic-looking test data. "Plantable, verifiable narrative" is not a product category; Story2Data occupies an empty slot.
- Fit-on-real synthesizers are structurally unable to do the challenge: there is no real data, and the story's effects are *counterfactual*; they would only reproduce whatever correlations exist.
- From-scratch LLM generators (Data Designer, YData text-to-dataset, Fabricate) are the most dangerous "they already do it" comparisons for judges. The rebuttal: LLM row generation does not guarantee quantified, lagged, cross-table effects; Story2Data's effects are produced by a deterministic simulation and then *measured* back.
- Faker/Mimesis are good building blocks for the sim's entity attributes (Czech locale) — use, don't compete.

### Gaps
- Could not verify whether Tonic Fabricate or NeMo Data Designer support time-indexed "event" injection; no public docs found in the budget.
- MOSTLY AI / Syntho relationship details not verified.
- DataCebo commercial SDV Enterprise feature set (e.g., more tables/constraints) not fetched.

## 2. LLM-based and causal synthetic tabular/relational generators; planted-insight benchmarks for data-analyst agents

### Takeaway
Academic work splits into (a) generative models of tables/databases (GReaT-style LLM, diffusion, SCM priors) aimed at fidelity or pretraining data, and (b) data-analyst agent benchmarks. InsightBench (ServiceNow, ICLR 2025) is the single closest prior art: it *plants* trends into synthetic business tables with formulas and uses LLM-generated text for free-text columns, then scores agents on recovering the planted insights. But it is single-table, 500 rows, hand-crafted per dataset, scored by LLM-judge text similarity, and has been criticized for flaws. A September 2026 position paper explicitly calls for "verifiable ground truth and explicitly planted insights within table corpora" — exactly what Story2Data produces.

### Cited Findings
**InsightBench (closest prior art)**
- 31 datasets (v1; later versions/abstract cite 100) across Incident, User, Finance, Asset, Goal Management, each 500 synthetic rows in CSV, modelled on ServiceNow tables — [arXiv 2407.06423v1](https://arxiv.org/html/2407.06423v1); 100 datasets per [ICLR 2025 version](https://proceedings.iclr.cc/paper_files/paper/2025/file/0dfe31d6e703e138d46a7d2fced38b7c-Paper-Conference.pdf) (conflict between versions noted)
- Planting method: trends injected into "controllable columns" with math models, e.g. `TTR = 1 + slope * (incident_open_date - data_start_date)`; non-controllable columns filled by random sampling from curated lists or GPT-4 for text like incident descriptions; ground truth = expert Jupyter notebooks with questions, code, plots, JSON — [arXiv 2407.06423v1](https://arxiv.org/html/2407.06423v1)
- Insight types: descriptive 45, diagnostic 40, predictive 15, prescriptive 10 — [arXiv 2407.06423v1](https://arxiv.org/html/2407.06423v1)
- Evaluation: LLaMA-3-Eval (G-Eval variant with LLaMA-3-70b) at summary and insight level; ROUGE-1 also reported — [arXiv 2407.06423v1](https://arxiv.org/html/2407.06423v1)
- Single-table, not multi-table joins — [arXiv 2407.06423v1](https://arxiv.org/html/2407.06423v1)
- License: code MIT ([GitHub ServiceNow/insight-bench](https://github.com/ServiceNow/insight-bench)), data CC BY-NC 4.0 ([HF](https://huggingface.co/datasets/ServiceNow/insight_bench))
- Criticisms: "format inconsistencies, poorly conceived objectives, and redundant insights"; sole reliance on LLaMA-3-Eval risks evaluator bias; does not reward novel insights — [InsightEval ACL Findings 2026](https://aclanthology.org/2026.findings-acl.1729.pdf); [arXiv 2511.22884](https://arxiv.org/pdf/2511.22884)
- DataSTORM (Stanford, Lam group; Apr-Aug 2026) evaluates a thesis-driven EDA + data-storytelling agent on InsightBench and ACLED; +19.4% relative insight-level recall — [arXiv 2604.06474](https://arxiv.org/abs/2604.06474)
- "Open Tabular Insight Extraction" (Gomm, de Rijke, Hulsebos; Sep/Oct 2026): existing benchmarks "largely unfit" for open settings because inputs presuppose knowledge of relevant tables; recommends verifiable ground truth and explicitly planted insights in table corpora — [arXiv 2609.07629](https://arxiv.org/abs/2609.07629)

**Other analyst-agent benchmarks (real data, no planted story)**
- DSBench 540 tasks; DA-Code 500 tasks from real-world sources in executable env; BLADE 188 decision questions over 12 datasets from scientific literature with expert ground truth — [FDABench related work](https://arxiv.org/html/2509.02473); [BLADE arXiv 2408.09667](https://arxiv.org/pdf/2408.09667)
- DiscoveryBench: find and verify hypotheses from datasets in 6 domains; gold hypotheses extracted from papers or human-annotated — [FDABench related work](https://arxiv.org/html/2509.02473)
- InfiAgent-DABench: closed-form data-analysis questions over CSVs — [arXiv 2401.05507](https://arxiv.org/pdf/2401.05507)
- Newer 2025-2026 data-agent benchmarks: FDABench (heterogeneous data), DAComp (full data-intelligence lifecycle), AgenticDataBench — [FDABench](https://arxiv.org/html/2509.02473); [DAComp](https://arxiv.org/pdf/2512.04324); [AgenticDataBench](https://arxiv.org/html/2607.01647)

**Relational/causal generators**
- "Generating Synthetic Relational Tabular Data via SCMs" (Hoppe et al., CONTACT Software, Jul 2025): extends TabPFN-style SCM priors to two linked tables via coupling node; purpose = pretraining tabular foundation models/benchmarks; no temporal or intervention modelling; only two-table experiments; no code repo found — [arXiv 2507.03528](https://arxiv.org/html/2507.03528)
- GRDM: graph-conditional diffusion jointly models all tables of a relational DB (fit on real data) — [arXiv 2505.16527](https://arxiv.org/html/2505.16527)
- Mixed-type relational DB synthesis with graph-prompted LM (Nov 2026) — [arXiv 2611.02373](https://arxiv.org/pdf/2611.02373)
- SQUiD: LLM synthesizes relational schema and populates tables from unstructured text (text is the source of facts, not a causal story) — [arXiv 2505.19025](https://arxiv.org/html/2505.19025)
- OmniSQL: prompts LLM to invent a business scenario and design a K-table DB, for text-to-SQL training data (scenario = flavor, not causal events) — [arXiv 2503.02240](https://arxiv.org/html/2503.02240v1)
- causalAssembly (Bosch, CLeaR 2024): semisynthetic production-line data with known causal graph from physics; supports hard/soft interventions; for benchmarking causal discovery — [arXiv 2306.10816](https://arxiv.org/html/2306.10816v2); [GitHub](https://github.com/boschresearch/causalAssembly)
- DoWhy-GCM supports sampling from fitted graphical causal models and `interventional_samples` — [DoWhy-GCM arXiv 2206.06821](https://arxiv.org/pdf/2206.06821); [DoWhy docs](https://www.pywhy.org/dowhy/v0.9.1/user_guide/gcm_based_inference/introduction.html)
- Text-guided time-series generation with dual LLM annotator/judge agents exists in power-systems scenario generation — [arXiv 2602.19522](https://arxiv.org/pdf/2602.19522); survey of LLM agents for time series references scenario-based synthesis systems (TESSA, MERIT, BRIDGE, ChatTS) — [arXiv 2608.26226](https://arxiv.org/pdf/2608.26226)

### Inferences
- InsightBench validates the Story2Data concept (planting + LLM text fill + recovery scoring is a publishable, ICLR-accepted idea), and its known weaknesses map directly onto Story2Data's improvements:
  - single table -> Story2Data: linked multi-table Postgres where effects propagate across FKs;
  - hand-written per-dataset formulas -> automatic from any company+story via YAML spec;
  - static "trend" columns -> dated events with lags, segments, and causal chains produced by an agent-based sim;
  - LLM-judge text similarity -> structured answer key (event date, segment, effect size, lag) scored numerically against detective output.
- SCM/causal generators (2507.03528, causalAssembly, DoWhy) give random or physics DAGs; none take a business narrative as input. Story2Data can cite DoWhy-style interventions as the conceptual basis ("story event = do()-intervention on the sim at time t").
- The 2026 "Open Tabular Insight Extraction" recommendation is a ready-made quote for the pitch: the field is asking for verifiable planted-insight corpora.

### Gaps
- GReaT, TabuLa, CLLM papers not fetched this session (known as LLM-based fit-on-real tabular generators; GReaT ICLR 2023). Did not verify current status.
- Did not find any paper that generates a *relational* database from a *causal storyline* with a recovery-based evaluation; absence after ~6 targeted searches, not proof of nonexistence.

## 3. Teaching / sample "fake company" databases and benchmark data generators

### Takeaway
Classic sample DBs (Northwind, AdventureWorks, TPC-H/TPC-DS) are static, schema-rich but story-poor; TPC-H in particular uses near-uniform distributions by design, the opposite of "a story you can find".

### Cited Findings
- TPC-D/TPC-H use uniform data distributions by design; widely recognized as unrepresentative because real warehouses are skewed; JCC-H and Zipf-skew forks of dbgen were created to add skew and join-crossing correlations — [JCC-H paper](https://www.researchgate.net/publication/322145758_JCC-H_Adding_Join_Crossing_Correlations_with_Skew_to_TPC-H); [Introducing Skew into TPC-H](https://www.researchgate.net/publication/216155461_Introducing_Skew_into_the_TPC-H_Benchmark); [tpch_dbgen_zipf_skew](https://github.com/SrikanthKandula/tpch_dbgen_zipf_skew)
- LLM-generated "fictional company" datasets exist for other purposes, e.g. a fictitious AI-companion company with ~1000 employees and ~10k enterprise data items for chatbot research (VizCopilot) — [arXiv 2510.11954](https://arxiv.org/pdf/2510.11954); LLM-generated 10k-row student-habits CSV — [PMC12925479](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12925479/)

### Inferences
- Northwind/AdventureWorks are what SQL/BI courses (likely incl. VŠE) use today; their "insights" are whatever the authors happened to type. Story2Data's educational pitch: instructor writes a 5-line story, gets a fresh DB per student/semester with an answer key, no answer leakage from the internet.
- TPC skew literature shows even the benchmark world recognized "uniform = no signal"; Story2Data is the extreme of controlled, semantic signal.

### Gaps
- No dedicated search budget for SQL-course dataset generators (e.g., tools that generate per-student DB variants); not found in the one search run. Northwind/AdventureWorks licensing not verified this session.

## 4. Agent-based business simulators producing transactional data (PaySim, BankSim, AMLSim, etc.)

### Takeaway
Fraud/AML simulators are the strongest methodological precedent for Story2Data's "deterministic agent-based sim with injected patterns + full ground truth": they inject known typologies into normal agent behaviour and label them. But they are domain-locked, patterns are hard-coded motifs (not free-text stories), and they don't model dated business events with effect sizes and lags across a company schema.

### Cited Findings
- PaySim and AMLSim generate routine customer activity from behavioral rules and inject canonical laundering motifs (fan-in/fan-out, smurfing) for labeled anomalies, enabling reproducible experiments with known ground truth — [TransXion arXiv 2604.17420](https://arxiv.org/html/2604.17420)
- PaySim: agent-based mobile-money simulator calibrated on an original real dataset — [PaySim EMSS 2016](https://www.msc-les.org/proceedings/emss/2016/EMSS2016_249.pdf)
- AMLSim (IBM): 6 normal and 8 AML typologies — [Bournemouth AML dataset paper](https://eprints.bournemouth.ac.uk/40982/1/Full_IEEE_Dataset_Conference_Paper%20(4).pdf)
- Synthetic data advantage: ground-truth labels are complete, whereas much real laundering is never detected — [IBM AML arXiv 2306.16424](https://arxiv.org/pdf/2306.16424)
- Newer: AMLgentex (2025), AMLNet multi-agent knowledge-based generator + detector (Sep 2025), TransXion high-fidelity graph benchmark (Apr 2026) — [AMLgentex](https://arxiv.org/pdf/2506.13989); [AMLNet](https://arxiv.org/pdf/2509.11595); [TransXion](https://arxiv.org/html/2604.17420)
- PaySim was criticized for narrow scope and insufficient regulatory alignment — [AMLNet arXiv 2509.11595](https://arxiv.org/pdf/2509.11595) (via search snippet)

### Inferences
- AMLNet's "generate and detect" pairing is structurally similar to Story2Data's generator + blind detective; worth acknowledging and differentiating: AMLNet detects labeled transactions (classification), Story2Data's detective must reconstruct a *narrative* (what, when, who/segment, how much, why) from an unlabeled DB.
- Story2Data generalizes the AMLSim idea: "typology library" becomes an LLM-parsed, domain-agnostic event spec.

### Gaps
- BankSim and retail simulators (e.g., supermarket/shopper ABMs) not researched within budget.

## 5. Differentiation: Story2Data edge vs. them

### Takeaway
The defensible edge is the closed loop: story -> machine-readable causal spec (answer key) -> simulation where events *cause* the patterns (not post-hoc painted) -> independent blind agent -> quantitative recovery score. No surveyed tool or paper combines all of: free-text story input, multi-table relational output, causal/temporal mechanics with lags and segments, and automated verification of recoverability.

### Cited Findings
- Closest academic analogue (InsightBench) is single-table, 500 rows, hand-planted formulas, LLM-judge scored — [arXiv 2407.06423v1](https://arxiv.org/html/2407.06423v1)
- Field explicitly calls for verifiable ground truth and planted insights across table corpora — [arXiv 2609.07629](https://arxiv.org/abs/2609.07629)
- Commercial from-scratch generators (Fabricate, YData text-to-dataset, NeMo Data Designer) focus on schema/plausibility from NL descriptions — [YData](https://docs.sdk.ydata.ai/latest/synthetic_data/text_to_dataset/); [aitoolalliance](https://www.aitoolalliance.com/best-ai-synthetic-data-generation-tools-2026/); [DataDesigner](https://github.com/NVIDIA-NeMo/DataDesigner/blob/main/README.md)
- Agent-based ground-truth sims exist but are domain-locked typology injectors — [TransXion](https://arxiv.org/html/2604.17420)

### Inferences (edge table for the pitch)
| Capability | SDV/MOSTLY/YData fit | Data Designer / Fabricate / YData text2data | InsightBench | AMLSim/PaySim | Synthea | Story2Data |
|---|---|---|---|---|---|---|
| Needs no real data | no | yes | yes | partly (calibration) | yes | yes |
| Multi-table relational FKs | yes (SDV limited) | yes (Fabricate/YData) | no | graph/txn | yes (EHR) | yes |
| Free-text story as input | no | prompt = schema, not events | no (hand-coded) | no | no | yes |
| Dated events with effect size, lag, segment | no | not found | linear trends only | fixed motifs | disease modules | yes (YAML spec) |
| Effects caused by mechanism, propagate across tables | no | no (LLM rows) | no (column formula) | yes, within domain | yes, within domain | yes |
| Machine-readable answer key | no | no | notebooks (manual) | labels | no | yes (spec = key) |
| Automated recoverability check | no | LLM-judge quality only | LLM-judge vs. text | detector accuracy | no | blind detective + numeric score |
| Domain-agnostic | yes | yes | business IT only | finance only | health only | yes |

Pitch lines and design implications:
- "Not a label, a mechanism": a story event is a `do()`-style intervention on the simulation at time t (cite DoWhy interventions) — the pattern is a consequence, so it shows up consistently in every derived table (orders, tickets, reviews, payments), unlike column-level painting.
- "The spec is the answer key": score detective output numerically per event (date within +/- k days, correct segment, effect size within tolerance, direction, lag) — avoids InsightBench's LLM-judge weakness.
- "Proof of recoverability before shipping": generator rejects/regenerates datasets where the detective fails or where events are statistically undetectable (signal-to-noise check) — no competitor validates recoverability.
- "Negative controls": include decoy noise / red herrings and require the detective to *not* report them (precision, not just recall) — InsightBench doesn't reward/penalize this.
- "Determinism": seeded sim -> reproducible dataset, unlike LLM row generators.
- Cite as related work honestly: InsightBench (planting), AMLSim/PaySim (ABM + ground truth), Synthea (state-machine modules), SCM generators (causal priors), NeMo Data Designer/Fabricate (NL->data). Positioning: "Story2Data = InsightBench's idea, made relational, causal, automatic, and self-verifying."
- Risk to pre-empt: judges may ask "isn't this just Fabricate/Data Designer with a prompt?" — demo a story whose effect is only visible via a JOIN + lagged time window, and show the detective's recovered timeline vs. the spec.

### Gaps
- Not verified whether any 2026 commercial release added "scenario/event injection" (searches did not surface one).
- No head-to-head trial of LLM-only generation to empirically show that it fails to embed quantified lagged effects; this could be a cheap ablation during the hackathon (generate with LLM-only vs. sim, run same detective).
