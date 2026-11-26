# Prove the story comes back out

**Keep your concept, but rebuild it around one moment the jury will remember.** A Czech story goes in. A seeded simulation turns it into a relational database. A blind detective that never sees the story then finds it again, with dates, segments, effect sizes and lags, and gets a number for how well it did. That round trip answers the challenge's key sentence, "Příběh … musí jít dohledat v samotných datech" ([hackathon.4fis.cz](https://hackathon.4fis.cz/)). No synthetic-data product or paper in the research does the whole loop ([InsightBench](https://arxiv.org/html/2407.06423v1); [YData text-to-dataset](https://docs.sdk.ydata.ai/latest/synthetic_data/text_to_dataset/); [NeMo Data Designer](https://github.com/NVIDIA-NeMo/DataDesigner/blob/main/README.md)). Change three things in your current plan. First, the detective is a **deterministic statistical scanner** (ruptures, STL with MAD, an Adtributor-style drill-down, and difference-in-differences across lags), and the LLM only writes its conclusion in Czech, because tool calling for Gemma 4 in Ollama has been unreliable all year ([ollama#18275](https://github.com/ollama/ollama/issues/18275), [#18649](https://github.com/ollama/ollama/issues/18649)). Second, the "agent-based" simulation is a **vectorized numpy day-loop** over arrays of customer state, not Mesa objects. Third, **DuckDB is the working store** and Postgres is a one-call export. **All LLM work runs on the always-on homelab Radeon (16 GB)**, on the same homelab as the app box. A Tuesday benchmark picks the model: gemma4:26b if it reaches ≥ about 20 tok/s mostly on the GPU, otherwise gemma4:12b for everything. Claude sits behind one env var. The desktop stays at home and is only an optional extra worker. The laptop (RTX 3060 6 GB) is the only machine at the venue: it is the dev client and runs an **offline replay demo** from cached LLM outputs. Serve the Streamlit demo from the team's auto-deploying box at **hack.dobsinsky.dev**, so judges can open it on their phones. **Do not fine-tune.** Build the whole engine Tuesday to Thursday. The 21 hours at the event go to adapting to the official brief, the detective-vs-story scoreboard, Czech polish and the pitch. The prize pool is shared with the Nova and Česká spořitelna challenges (10,000 Kč for 1st, 5,000 Kč for 2nd) ([hackathon.4fis.cz](https://hackathon.4fis.cz/)). So the demo has to make sense to a TV executive and a banker in 90 seconds, and hold up to a statistician's questions.

## Verdict: keep the loop, change the detective, cut the fine-tune

**Keep the concept.** Each part of it already has a cited precedent, and nobody has put them together. InsightBench (ICLR 2025) shows that planting insights, filling text columns with an LLM and scoring recovery is a publishable idea. Its weaknesses are your improvements: it uses a single table of **500 rows**, its formulas are written by hand for each dataset, and an LLM judge does the scoring ([arXiv 2407.06423](https://arxiv.org/html/2407.06423v1)). Critics point out that this scoring has no precision term and invites evaluator bias ([InsightEval](https://arxiv.org/html/2511.22884v2)). A September 2026 position paper asks the field for "verifiable ground truth and explicitly planted insights within table corpora", which is a good line for your pitch ([arXiv 2609.07629](https://arxiv.org/abs/2609.07629)). PaySim and AMLSim set the methodological pattern you are copying: a normal baseline plus injected typologies with full ground truth. They are locked to one domain and use hard-coded motifs ([TransXion](https://arxiv.org/html/2604.17420); [IBM/AMLSim](https://github.com/IBM/AMLSim)). The judges are FIS academics, plus partner representatives sitting on the jury ([hackathon.4fis.cz](https://hackathon.4fis.cz/)). For them, the teaching angle fits the courses directly: 4IZ450/460 knowledge discovery, 4IT218 databases and 4IT403 analytics and reporting ([fis.vse.cz 4DI](https://fis.vse.cz/magisterske-studium/vedlejsi-specializace/4di); [vsewiki 4IZ460](https://vsewiki.cz/predmet/4IZ460)). Note that this fit is inferred. No FIS course page mentions generated datasets.

**Change four things.**

1. **Detective.** A ReAct agent that calls tools natively through Ollama will break on stage. The issues are documented: dropped tool_calls with a system prompt plus `think:false` ([#15539](https://github.com/ollama/ollama/issues/15539)), reasoning loops that run to the token cap ([#18275](https://github.com/ollama/ollama/issues/18275)), and trailing garbage after the JSON ([#18649](https://github.com/ollama/ollama/issues/18649)). Instead, the detective runs a fixed, deterministic scan that produces a table of candidate events. Gemma receives that table plus summary statistics and returns one schema-constrained JSON with the events it accepts and a Czech narrative. The intelligence that matters is the statistics, and the statistics are reproducible.
2. **Simulation engine.** At 5k–50k customers over about 700 days, one Poisson draw per day across all customers runs in seconds. Mesa objects would mean tens of millions of Python method calls ([simulation notes, sizing inference](https://pypi.org/project/Mesa/)). Mesa 4 pre-releases also signal API churn ([mesa GitHub](https://github.com/mesa/mesa)). It is still agent-based in substance: every customer has its own rate, hazard, segment and history.
3. **Storage.** Use **DuckDB** as the working store: in-process, zero ops, and it can query pandas DataFrames directly. Export to Postgres through DuckDB's postgres extension, which uses binary COPY ([DuckDB postgres extension](https://duckdb.org/docs/2.0/core_extensions/postgres/overview)). Postgres stays in the deliverable because judges and teachers expect a database they can connect to.
4. **Fine-tune.** Cut it (reasons in the model plan section).

**The honest weak spots.**

- **"Isn't this Tonic Fabricate or YData with a prompt?"** Both turn natural language into relational data ([aitoolalliance](https://www.aitoolalliance.com/best-ai-synthetic-data-generation-tools-2026/)). Your defence is a story whose effect only appears after a JOIN and a lag (story 1 below), plus a no-story twin that shows the detective does not invent events.
- **LLM spec extraction can be confidently wrong.** A grammar enforces structure, not meaning ([ollama#15260](https://github.com/ollama/ollama/issues/15260)). Show the YAML on screen and let a human edit it. In the pitch, that becomes a feature.
- **The detective will miss subtle events.** Present this as a detection curve over effect size d, not as a failure. The detection thresholds are not measured yet ([TCPDBench](https://arxiv.org/pdf/2003.06222v3) only motivates the approach).
- **The official brief at 14:15 Friday may change the input format.** The engine has to treat company and story as plain text plus an optional table hint.
- **Only one person can debug the core.** Everything critical gets built before Friday.

## Architecture: LLM at the edges, determinism in the middle

The pipeline has seven stages. Stage 1 sends the company description and the story (Czech text) to the **spec compiler**. The homelab Gemma (26B or 12B per the benchmark rule), schema-constrained, produces a `story.yaml`, which Pydantic validates and a human can edit in the UI. In stage 2 the **simulator** (numpy day-loop with a seed) turns the spec into clean DataFrames plus an `_answer_key` events table. Stage 3 applies the **realism and dirt layer** (holidays, typos, duplicates, late arrivals) to an export copy only. Stage 4, the **text filler**, writes Czech reviews and tickets with the homelab Gemma. Text is generated ahead of time and cached, and the optional desktop worker helps when it is reachable. It uses pooled templates keyed by sentiment, topic and product, with the numbers passed in from the simulation. Stage 5, the **exporter**, writes DuckDB, Parquet and Postgres, with PK/FK DDL. Stage 6 is the **blind detective**. It reads only the analyst schema, never `_answer_key`, and produces candidate events, which the homelab Gemma turns into JSON events plus a Czech narrative. Stage 7 is the **scorer**. It compares those events against `_answer_key` with Hungarian matching and reports precision, recall and F1, a per-slot breakdown, a no-story twin and a seed sweep. The **Streamlit UI** wraps all of this as five tabs: Story → Spec → Data → Detective → Score. Every LLM call goes through one `llm.complete(step, prompt, schema)` interface with four backends: `ollama`, `claude`, `replay` and `ollama+desktop`. The replay backend serves cached outputs keyed by `hash(step, prompt, schema, model)`.

```
            HOME (homelab, always on)                                  VENUE
 ┌──────────────────────────────────────────────────┐         ┌──────────────────────────┐
 │ Shared app box (VM/LXC)            Radeon 16 GB    │         │ Laptop (RTX 3060 6 GB)    │
 │ ┌───────────┐  LAN  ┌──────────────────────────┐   │ Tailscale│ dev client (SSH, git)    │
 │ │ nginx:3000 │◄────►│ Ollama: gemma4:26b *or* 12b │◄──┼─────────┤ OFFLINE: same compose,   │
 │ │ Streamlit  │      │ MAX_LOADED_MODELS=1         │   │         │ LLM_BACKEND=replay,      │
 │ │ DuckDB/PG  │      └──────────────────────────┘   │         │ cached ./data + llm_cache│
 │ └─────┬─────┘                                       │         └──────────────────────────┘
 │       │ optional, health-checked ──► Desktop 4070S (gemma4:12b, bulk Czech text)      │
 │       │ fallback switch ──────────► Claude API (LLM_BACKEND=claude)                   │
 └───────┼──────────────────────────────────────────┘
         ▼ Cloudflare Tunnel → https://hack.dobsinsky.dev  (judges' phones, projector)
```

**Precompute and cache.** For the three demo stories, every LLM output is generated before the event and stored in `data/llm_cache/`: the spec, the text pools and the detective report. So is every dataset. On stage, the only fresh LLM calls are for a story a judge types in.

Two design choices are not negotiable. First, **the spec is the answer key**. Every event in the YAML becomes a row in `_answer_key` with `{type, metric, segment, start_date, lag_days, direction, magnitude_pct}`. The scorer matches on exactly those slots, following DiscoveryBench's context × variable × relation factorization ([arXiv 2407.01725](https://arxiv.org/pdf/2407.01725)). Second, **one root seed** goes through `np.random.SeedSequence(root).spawn()`, with a named child stream per subsystem (acquisition, purchases, payments, tickets, reviews, messiness, faker). That way, editing one rule does not reshuffle everything else ([NumPy parallel RNG](https://numpy.org/doc/stable/reference/random/parallel.html)). A test runs the sim twice and asserts that the Parquet hashes are equal.

**The daily step runs in this order:** events, then prices and inventory, then acquisitions, then churn, then purchases (with stock checks), then payments, tickets and reviews. **Behaviour is multiplicative:** `λ[i,t] = base_rate[i] · dow[t] · yearly[t] · holiday[t] · Π_e M_e(t) · alive[i]`. `base_rate` is Gamma-distributed, which gives realistic negative-binomial counts. Churn is a daily hazard with the same multiplier structure, and it also rises with recency and with unresolved tickets. That second link is what creates emergent chains such as stockout → tickets → churn. Each event compiles into a curve: zero before `start+lag`, a linear ramp over `ramp_days`, a plateau for `duration_days`, then a half-life decay. To hit a stated target ("15% of a segment churns within W days"), convert it to an extra daily hazard `h = 1-(1-p)^(1/W)`. The validation report then prints target vs realized. These are engineering patterns from the simulation research, not cited code. Holidays come from `holidays.CZ` with Czech names ([holidays](https://github.com/vacanza/holidays)). Product popularity follows Zipf weights. Czech names come from Faker `cs_CZ`, generating gender first so that "-ová" surnames stay consistent (verify this in a REPL). Cities are drawn from a weighted real list so that geography matches the stores ([Faker cs_CZ](https://faker.readthedocs.io/en/master/locales/cs_CZ.html)).

**Analyst-visible tables:** `customers`, `stores`, `products`, `product_prices` (SCD with `valid_from`), `suppliers`, `shipments_in`, `inventory_daily`, `orders`, `order_items`, `payments`, `deliveries`, `tickets`, `reviews`, `campaigns`, `employees`. The hidden schema `_truth` holds `answer_key`, `spec_yaml` and `sim_log`.

### Detective toolkit

1. **Breakpoints.** Build daily KPIs per segment. Remove weekly seasonality with STL (`period=7, robust=True`) and standardize the series with median/MAD. Run `ruptures.Pelt(model="l2", min_size=7).predict(pen=3·log n)`. Keep only breaks that `Binseg` confirms within ±3 days. Plain binseg/PELT were the best default univariate detectors in TCPDBench, Prophet was near the bottom, and a "no changepoints" baseline beat many methods, so false positives are the enemy ([arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)).
2. **Spikes and stockouts.** Use runs of residual |z| > 3.5. A stockout also shows up as a run of at least 3 days with zero units on an SKU that normally sells.
3. **Drill-down.** Adtributor-style: explanatory power plus JS-divergence surprise per dimension ([Microsoft Research](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/main-14.pdf)). Confirm with DiD and a 7-day block-bootstrap CI.
4. **Lag search.** Fit the DiD at lags {0, 7, 14, 28, 42} days and keep the maximum |t|.

### Scoring

- **Pair score:** `s = gate(metric, direction) × (0.4·timing + 0.4·segment_jaccard + 0.2·magnitude)`.
  - timing = `1-|Δdays|/τ`, with τ = 7 for shifts and 2 for spikes
  - magnitude = `1-|log(pred/true)|/log 2`
- **Matching:** Hungarian assignment with `scipy.optimize.linear_sum_assignment`, so each prediction matches at most one true event, the same no-double-count rule as TCPDBench. A match counts when s ≥ 0.5.
- **Metrics:** precision, recall and F1, as InsightEval recommends ([arXiv 2511.22884](https://arxiv.org/html/2511.22884v2)).
- **Controls:**
  - a **no-story twin** (same seed, no events), reported as false events per year
  - a **placebo histogram** from shuffled event dates
  - a **20-seed sweep**

The weights and τ are design choices, not values from the literature. Say so if asked.

### Stack and versions

Pin the Python packages with `uv` on Tuesday. Versions the research confirmed:

| Component | Library / version | Note |
|---|---|---|
| Changepoints | `ruptures==1.1.10` ([PyPI](https://pypi.org/project/ruptures/)) | PELT + Binseg |
| Holidays | `holidays` 0.101 line ([libraries.io](https://libraries.io/pypi/holidays)) | `holidays.CZ(language="cs")` |
| Postgres load | psycopg 3, `cursor.copy()` ([docs](https://www.psycopg.org/psycopg3/docs/basic/copy.html)) | or DuckDB `ATTACH … (TYPE postgres)` |
| Optional anomaly | `stumpy==1.14.1` ([PyPI](https://pypi.org/project/stumpy/)) | skip unless time; needs Numba warm-up |
| Not used | Mesa 3.5.x, SimPy 4.1.2, PyOD 3.6.9 ([Mesa](https://pypi.org/project/Mesa/), [PyOD](https://pypi.org/project/pyod/)) | overhead without benefit |
| LLM runtime | Ollama, GGUF tags only, ≥0.21.1 (format+think:false fix) ([#15260](https://github.com/ollama/ollama/issues/15260)) | pin the exact installed version |
| Core (versions not in notes; pin what installs Tuesday) | Python 3.12, numpy, pandas, duckdb, pydantic v2, PyYAML, Faker, statsmodels (STL), scipy, streamlit, plotly, `ollama` and `anthropic` SDKs | — |

### Deployment: the public URL is the demo

The repo already has the infrastructure. A shared Linux box, assumed to be a VM or LXC on the Proxmox homelab, sits behind a Cloudflare Tunnel. It serves **https://hack.dobsinsky.dev**, and SSH goes through `ssh.dobsinsky.dev` with a cloudflared ProxyCommand. Every 30 seconds it checks `main` on GitHub and runs `docker compose up -d --build`. Today `compose.yaml` runs a placeholder `nginx:alpine` on host port 3000 (repo `README.md`, `compose.yaml`, `nginx.conf`). Keep that nginx as the front door and add the app behind it:

```yaml
# compose.yaml
services:
  app:
    build: ./app                      # Dockerfile: python:3.12-slim, uv sync, streamlit run ui/main.py
    command: >
      streamlit run ui/main.py --server.port 8501 --server.address 0.0.0.0
      --server.headless true --server.enableCORS false --server.enableXsrfProtection false
    environment:
      OLLAMA_URL:         http://homelab-gpu.lan:11434   # primary: all LLM steps (Radeon 16 GB)
      OLLAMA_MODEL:       gemma4:26b                     # or gemma4:12b per Tuesday benchmark rule
      OLLAMA_DESKTOP_URL: http://desktop.tailnet:11434   # OPTIONAL bulk-text worker; health-checked, skipped if down
      LLM_BACKEND: ollama                                # or: claude | replay (cached outputs, no network LLM)
      LLM_CACHE_DIR: /data/llm_cache
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}            # from .env on the box, never in git
      DATA_DIR: /data
    volumes:
      - ./data:/data                  # DuckDB files, Parquet, pre-generated demo runs
    restart: unless-stopped
  postgres:
    image: postgres:17-alpine
    environment: {POSTGRES_PASSWORD: ${PG_PASSWORD}, POSTGRES_DB: story2data}
    volumes: [pgdata:/var/lib/postgresql/data]
    ports: ["127.0.0.1:5432:5432"]
    restart: unless-stopped
  web:
    image: nginx:alpine
    ports: ["3000:80"]
    volumes:
      - ./site:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on: [app]
    restart: unless-stopped
volumes: {pgdata: {}}
```

```nginx
# nginx.conf
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
server {
    listen 80;
    absolute_redirect off;
    location /static-site/ { root /usr/share/nginx/html; try_files $uri $uri/ =404; }
    location / {
        proxy_pass http://app:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

**Long LLM calls never block a request.** Cloudflare cuts off a non-streaming HTTP response after about 100 seconds. That limit comes from the team's infrastructure brief, not the research notes. So the UI submits each LLM step as a background job: a thread writes progress to a small table in the DuckDB file, and a `st.fragment(run_every=2)` panel polls it. The Streamlit websocket stays alive through Cloudflare and nginx thanks to those proxy headers and the regular UI updates.

Every Ollama host needs `OLLAMA_HOST=0.0.0.0` and a firewall rule that admits only the box and the tailnet.

**Topology:** only the laptops go to xPORT. The homelab holds the app box, the Radeon inference host and Postgres, and stays on at home. The team reaches it through the public URL and SSH, and the laptop also reaches it over Tailscale. The desktop is not on the critical path. If it is left on at home, the app's health check (`GET /api/tags`, 2 s timeout, re-checked every 60 s) adds it as a bulk-text worker; if it is down, the app skips it silently.

**Team git workflow.** B and C work on the shared box over SSH. Each has their own clone in `~/work`, pushes to `feat/<name>-<thing>` branches, and never touches `main`. **Only A merges to `main`**, because a merge is a deploy. Enable GitHub branch protection on `main`, requiring a PR with A's approval. At code freeze, run `sudo systemctl stop deploy` (plus `sudo systemctl disable --now` its timer if one exists, which you can check with `systemctl list-timers | grep deploy`). After that, a stray push cannot break the live demo.

## The story DSL: a closed vocabulary the LLM can fill and the sim can obey

The DSL's main job is to make LLM output checkable. **Every field is either an enum, a number with bounds, or free text that the sim ignores**: `narrative_cs`, `description`. Pydantic generates the JSON Schema passed to Ollama's `format`. Keep the schema flat. Avoid `oneOf` and recursive `$ref`, which the grammar converter may not support ([local LLM notes, inference](https://github.com/ollama/ollama/issues/15540)). Put long text fields last.

### Spec

```yaml
version: 1
meta:
  seed: int                        # root seed → SeedSequence
  start: date                      # sim start (YYYY-MM-DD)
  days: int [90..1095]
  currency: CZK|EUR
  locale: cs_CZ
  difficulty: easy|medium|hard     # scales event effect sizes ×1.5 / ×1.0 / ×0.5 and noise
company:
  name: str
  legal_form: s.r.o.|a.s.|other
  industry: retail|eshop|cafe_chain|subscription|services
  description: str                 # free text, not simulated
  channels: [eshop|store|app|phone]           # with weights
  cities: [{name: str, weight: float, has_store: bool}]
entities:
  customers: {n: int [500..100000], growth_per_year: float, 
              segments: [{id: str, share: float, base_orders_per_month: float,
                          price_sensitivity: float [0..3], base_churn_per_month: float}]}
  products:  {categories: [{id: str, n_skus: int, price_min: float, price_max: float,
                            supplier: str, zipf_s: float [0.8..1.4]}]}
  suppliers: [{id: str, name: str, lead_time_days: int, reliability: float [0..1]}]
  stores:    {per_city_with_store: int}
  employees: {support_agents: int, tickets_per_agent_day: float}
baseline:
  seasonality: {weekly: [7 floats], profile: retail_cz|flat|summer_peak|winter_peak,
                black_friday: bool, christmas: bool, cz_holidays_closed: bool}
  payment_failure_rate: float
  return_rate: float
  review_rate: float
  ticket_rate_per_order: float
events:                            # the answer key
  - id: str                        # E1, E2…
    type: price_change|competitor_entry|campaign|supplier_delay|stockout|
          courier_change|service_outage|quality_issue|staff_shortage|viral_spike
    start: date
    target: {city: [str]?, segment: [str]?, category: [str]?, channel: [str]?, supplier: [str]?}
    params: {price_change_pct?: float, lead_time_multiplier?: float,
             delivery_delay_days?: float, budget_czk?: float}
    effects:
      - metric: purchase_rate|churn_hazard|acquisition_rate|basket_size|
                ticket_rate|rating_mean|return_rate|payment_failure_rate|delivery_days
        size: float                # relative (+0.15 = +15 %), or absolute for rating/delivery_days
        lag_days: int [0..120]
        ramp_days: int [0..60]
        duration_days: int|null    # null = permanent
        decay_halflife_days: int|null
    caused_by: str|null            # event id → causal chain, scored as bonus
    narrative_cs: str              # human sentence; ignored by sim
decoys:                            # real-looking non-events; detective must NOT report them as story
  - {type: viral_spike|seasonal_peak|data_outage, date: date, target: {...}, size: float}
noise:
  messiness: none|light|medium|heavy   # nulls, typos (Plzen/Plzeň), duplicates, +420 formats, late ingest
```

Semantic validators run after the schema check:

- dates fall inside the sim window
- segment and city ids exist
- shares sum to 1 (±0.01)
- `caused_by` points to an earlier event
- every event's effect is at least **d ≥ 0.5 noise units** at segment level (the "recoverability gate")

Any failure goes back to the LLM verbatim for up to two retries.

### Example A: a Czech coffee roaster (headline demo)

Story input: *"Pražírna Zrnko s.r.o. prodává výběrovou kávu přes e-shop a má kavárny v Praze, Brně, Ostravě a Plzni. V březnu 2026 zdražila předplatné o 15 %. Studenti to nesli špatně a zhruba po šesti týdnech jich začalo odcházet víc. V květnu se zasekla dodávka z Etiopie, došla etiopská zrna, lidé si stěžovali na podporu a v Brně jsme kvůli tomu ztratili část věrných zákazníků. V září otevřela v Brně konkurence."*

```yaml
version: 1
meta: {seed: 20261127, start: 2025-01-01, days: 670, currency: CZK, locale: cs_CZ, difficulty: medium}
company:
  name: Pražírna Zrnko
  legal_form: s.r.o.
  industry: cafe_chain
  description: Výběrová káva, e-shop s předplatným a 4 kavárny.
  channels: [{eshop: 0.55}, {store: 0.45}]
  cities:
    - {name: Praha,   weight: 0.45, has_store: true}
    - {name: Brno,    weight: 0.25, has_store: true}
    - {name: Ostrava, weight: 0.15, has_store: true}
    - {name: Plzeň,   weight: 0.15, has_store: true}
entities:
  customers:
    n: 12000
    growth_per_year: 0.20
    segments:
      - {id: student,     share: 0.25, base_orders_per_month: 1.2, price_sensitivity: 2.0, base_churn_per_month: 0.04}
      - {id: predplatitel, share: 0.30, base_orders_per_month: 2.0, price_sensitivity: 0.8, base_churn_per_month: 0.02}
      - {id: bezny,       share: 0.45, base_orders_per_month: 0.8, price_sensitivity: 1.0, base_churn_per_month: 0.03}
  products:
    categories:
      - {id: etiopie,   n_skus: 6,  price_min: 290, price_max: 490, supplier: S_ETH, zipf_s: 1.1}
      - {id: kolumbie,  n_skus: 8,  price_min: 250, price_max: 420, supplier: S_COL, zipf_s: 1.1}
      - {id: espresso,  n_skus: 10, price_min: 220, price_max: 380, supplier: S_BRA, zipf_s: 1.2}
      - {id: prislusenstvi, n_skus: 25, price_min: 150, price_max: 4900, supplier: S_CZ, zipf_s: 1.3}
  suppliers:
    - {id: S_ETH, name: Addis Green Coffee, lead_time_days: 21, reliability: 0.95}
    - {id: S_COL, name: Huila Cooperative,  lead_time_days: 25, reliability: 0.95}
    - {id: S_BRA, name: Minas Trading,      lead_time_days: 18, reliability: 0.97}
    - {id: S_CZ,  name: Barista Potřeby s.r.o., lead_time_days: 3, reliability: 0.99}
  stores: {per_city_with_store: 1}
  employees: {support_agents: 4, tickets_per_agent_day: 25}
baseline:
  seasonality: {weekly: [0.95,0.95,1.0,1.0,1.1,1.2,0.8], profile: winter_peak, black_friday: true, christmas: true, cz_holidays_closed: true}
  payment_failure_rate: 0.02
  return_rate: 0.01
  review_rate: 0.12
  ticket_rate_per_order: 0.015
events:
  - id: E1
    type: price_change
    start: 2026-03-01
    target: {category: [etiopie, kolumbie, espresso]}
    params: {price_change_pct: 15}
    effects:
      - {metric: purchase_rate, size: -0.06, lag_days: 0,  ramp_days: 7,  duration_days: null, decay_halflife_days: null}
    caused_by: null
    narrative_cs: Zdražení kávy o 15 % od 1. 3. 2026.
  - id: E2
    type: price_change
    start: 2026-03-01
    target: {segment: [student]}
    params: {}
    effects:
      - {metric: churn_hazard, size: 0.60, lag_days: 42, ramp_days: 14, duration_days: 45, decay_halflife_days: 21}
    caused_by: E1
    narrative_cs: Studenti po zdražení odcházejí se zpožděním ~6 týdnů.
  - id: E3
    type: supplier_delay
    start: 2026-05-04
    target: {supplier: [S_ETH]}
    params: {lead_time_multiplier: 3.0}
    effects:
      - {metric: ticket_rate, size: 1.5, lag_days: 10, ramp_days: 3, duration_days: 35, decay_halflife_days: 7}
    caused_by: null
    narrative_cs: Zpoždění dodávky z Etiopie → vyprodaná etiopská zrna, stížnosti.
  - id: E4
    type: quality_issue
    start: 2026-05-14
    target: {city: [Brno], segment: [predplatitel]}
    params: {}
    effects:
      - {metric: churn_hazard, size: 0.80, lag_days: 21, ramp_days: 7, duration_days: 30, decay_halflife_days: 14}
    caused_by: E3
    narrative_cs: Brněnští předplatitelé po výpadku a stížnostech částečně odchází.
  - id: E5
    type: competitor_entry
    start: 2026-09-07
    target: {city: [Brno], channel: [store]}
    params: {}
    effects:
      - {metric: purchase_rate, size: -0.20, lag_days: 0, ramp_days: 30, duration_days: null, decay_halflife_days: null}
    caused_by: null
    narrative_cs: Otevření konkurenční kavárny v Brně.
decoys:
  - {type: viral_spike, date: 2025-10-14, target: {category: [prislusenstvi]}, size: 2.5}
  - {type: seasonal_peak, date: 2025-11-28, target: {}, size: 1.8}
noise: {messiness: light}
```

### Example B: an electronics e-shop with a courier switch (the "JOIN + lag" story)

```yaml
version: 1
meta: {seed: 4242, start: 2025-03-01, days: 600, currency: CZK, locale: cs_CZ, difficulty: hard}
company:
  name: ElektroDomov
  legal_form: a.s.
  industry: eshop
  description: Online prodejce domácí elektroniky s doručením po celé ČR.
  channels: [{eshop: 0.85}, {app: 0.15}]
  cities:
    - {name: Praha, weight: 0.30, has_store: false}
    - {name: Brno, weight: 0.18, has_store: false}
    - {name: Ostrava, weight: 0.12, has_store: false}
    - {name: Plzeň, weight: 0.10, has_store: false}
    - {name: Olomouc, weight: 0.10, has_store: false}
    - {name: Liberec, weight: 0.10, has_store: false}
    - {name: Hradec Králové, weight: 0.10, has_store: false}
entities:
  customers:
    n: 30000
    growth_per_year: 0.10
    segments:
      - {id: rodina, share: 0.5, base_orders_per_month: 0.35, price_sensitivity: 1.2, base_churn_per_month: 0.03}
      - {id: geek,   share: 0.2, base_orders_per_month: 0.70, price_sensitivity: 0.7, base_churn_per_month: 0.02}
      - {id: senior, share: 0.3, base_orders_per_month: 0.20, price_sensitivity: 1.5, base_churn_per_month: 0.025}
  products:
    categories:
      - {id: mala_spotrebice, n_skus: 120, price_min: 390, price_max: 4990, supplier: S1, zipf_s: 1.1}
      - {id: velka_spotrebice, n_skus: 60, price_min: 6990, price_max: 39990, supplier: S2, zipf_s: 1.0}
      - {id: mobily, n_skus: 80, price_min: 2990, price_max: 34990, supplier: S3, zipf_s: 1.3}
  suppliers:
    - {id: S1, name: Distri CZ, lead_time_days: 5, reliability: 0.98}
    - {id: S2, name: BigHome EU, lead_time_days: 12, reliability: 0.96}
    - {id: S3, name: MobilNet, lead_time_days: 4, reliability: 0.98}
  stores: {per_city_with_store: 0}
  employees: {support_agents: 10, tickets_per_agent_day: 30}
baseline:
  seasonality: {weekly: [1.05,1.0,1.0,1.0,0.95,0.85,1.15], profile: retail_cz, black_friday: true, christmas: true, cz_holidays_closed: false}
  payment_failure_rate: 0.03
  return_rate: 0.06
  review_rate: 0.08
  ticket_rate_per_order: 0.03
events:
  - id: E1
    type: courier_change
    start: 2026-02-02
    target: {city: [Ostrava, Olomouc]}
    params: {delivery_delay_days: 2.5}
    effects:
      - {metric: delivery_days, size: 2.5, lag_days: 0, ramp_days: 0, duration_days: 120, decay_halflife_days: null}
      - {metric: rating_mean, size: -0.9, lag_days: 3, ramp_days: 0, duration_days: 120, decay_halflife_days: null}
    caused_by: null
    narrative_cs: Přechod na levnějšího přepravce na Moravě → pozdní doručení.
  - id: E2
    type: courier_change
    start: 2026-02-02
    target: {city: [Ostrava, Olomouc]}
    params: {}
    effects:
      - {metric: churn_hazard, size: 0.9, lag_days: 35, ramp_days: 14, duration_days: 90, decay_halflife_days: 30}
    caused_by: E1
    narrative_cs: Zákazníci s opožděnou zásilkou odcházejí za ~5 týdnů.
  - id: E3
    type: campaign
    start: 2026-04-13
    target: {segment: [geek], category: [mobily]}
    params: {budget_czk: 400000}
    effects:
      - {metric: acquisition_rate, size: 0.8, lag_days: 0, ramp_days: 2, duration_days: 21, decay_halflife_days: 7}
      - {metric: purchase_rate, size: 0.3, lag_days: 0, ramp_days: 2, duration_days: 21, decay_halflife_days: 7}
    caused_by: null
    narrative_cs: Jarní kampaň na mobily pro technické nadšence.
decoys:
  - {type: data_outage, date: 2025-09-18, target: {channel: [app]}, size: -1.0}
noise: {messiness: medium}
```

In Example B the churn hazard is applied **only to customers who actually received a late order**, not to the whole city. The sim sets this up through each customer's `last_delivery_delay`. As a result, the churn rise is diluted at city level and invisible in aggregate. It is obvious once you join `customers → orders → deliveries` and compare churn 30–60 days after a late delivery against on-time orders. That is the "Fabricate can't do this" story.

## Model plan: one homelab Radeon serves everything, Claude behind a switch

**The homelab Radeon is the only inference host on the critical path.** It has 16 GB of VRAM and about 28 GB of RAM, and it sits on the same homelab as the app box, so the LAN connects them. **Assumption:** the card is an RDNA2-class RX 6800 / 6800 XT (gfx1030). It replaced the RX 6700 XT, so confirm the exact model with `rocminfo` or `lspci`. That chip is natively supported by ROCm, so `HSA_OVERRIDE_GFX_VERSION=10.3.0` is only a fallback if detection fails; the override is documented for the gfx1031 RX 6700 XT ([selfhost.directory](https://selfhost.directory/models/amd); [localaimaster](https://localaimaster.com/blog/rocm-unsupported-gpu-hsa-override)). llama.cpp with Vulkan needs no override. Proxmox needs one of two setups: GPU passthrough to a VM, or an LXC with `/dev/kfd` and `/dev/dri` mapped ([selfhost.directory](https://selfhost.directory/models/amd)).

**16 GB cannot hold the 26B and the 12B at the same time.** The default Q4 weights are 16–19 GB for the 26B and 7.7–8 GB for the 12B ([ollama.com/library/gemma4](https://ollama.com/library/gemma4)). Set `OLLAMA_MAX_LOADED_MODELS=1` and run **one model for every step**, because swapping models costs a reload on every switch.

**Optional second card: the old RX 6700 XT (12 GB).** Fitting it alongside the 16 GB card gives 28 GB of VRAM. Then the 26B runs on the 16 GB card and the 12B on the 6700 XT, both loaded at once with no swapping. Run two Ollama instances, each pinned to one card with `ROCR_VISIBLE_DEVICES` and its own port, and give the 6700 XT instance `HSA_OVERRIDE_GFX_VERSION=10.3.0`. Power is an estimate, not a measurement: about 250 W + 230 W for the two cards plus the CPU and system comes to roughly 600 W at full load, which is tight but plausible on a 700 W PSU. LLM decode rarely holds both cards at full power. **Only do this if** the PSU has enough separate PCIe 8-pin cables, never using daisy-chain splitters for both cards, and only if it's done and stable by **Wednesday evening**. Otherwise skip it; the single-card plan above already works.

**Decision rule, run on Tuesday.**

- **If** gemma4:26b reaches **≥ about 20 tok/s** with ≥ ~90 % of layers on the GPU, at `num_ctx` 16384 and q8_0 KV, **use the 26B for everything**: spec, detective and Czech text pools. The pools are generated overnight and cached, so their speed matters little.
- **Otherwise use gemma4:12b for everything.** It fits fully on 16 GB with plenty of room.

The 26B is the MoE with **3.8B active parameters**. It beats the 12B on every listed benchmark, including multilingual MMMLU, where it scores **86.3 against 83.4** ([model card](https://gemma.ai/models/gemma-4/model-card/)). It is worth having if it is fast enough.

**Speed estimates, not measurements:**

- A llama.cpp report for gfx1031 measured **35–41 tok/s decode**, model unspecified ([llama.cpp#26702](https://github.com/ggml-org/llama.cpp/issues/26702)).
- The 26B with partial offload on a 12 GB NVIDIA card ran at **32–38 tok/s** ([modelfit.io](https://modelfit.io/can-i-run/gemma4-26b-a4b-q4-on-rtx-4070/); [carteakey.dev](https://carteakey.dev/blog/local-inference/gemma-4-26b-qat-mtp/)).
- So expect **25–45 tok/s for the 26B** on the Radeon. At that rate a 1.5k–3k-token spec takes about 40–110 s, which is why custom stories run as background jobs.

**Optional desktop worker.** If the desktop RTX 4070 Super is left on at home (wake-on-LAN, Tailscale), it runs gemma4:12b fully on its GPU as a **second worker for bulk Czech text pools only**. The app health-checks it and skips it when it is down. Nothing demo-critical ever waits on it.

**Laptop.** The RTX 3060 6 GB is a client and the offline replay box. gemma4:e4b, or a partially offloaded 12B at an estimated ~10–20 tok/s, is a last resort only.

| Step | Model / host | Settings | Guardrails |
|---|---|---|---|
| Story → YAML spec | homelab Radeon: gemma4:26b (or 12b per rule), GGUF | `think:false`, `format=<Pydantic JSON schema>`, temperature 0.1, `num_ctx` 16384, `keep_alive:-1` | Pydantic + semantic validators; ≤2 retries with error text → Claude. Demo stories served from `llm_cache` |
| Czech reviews / tickets / product names | same homelab model, **pre-generated overnight**; desktop 12B as optional extra worker | temperature 1.0, top_p 0.95, top_k 64 (Google defaults), `format={text, rating, topic}`, `num_ctx` 4096 | Numbers come from the sim. Generate **pools** (e.g. 40 texts × rating 1–5 × topic {zpoždění, kvalita, cena, obsluha, vyprodáno}), sample with the seed; never one call per row. For custom stories, reuse the generic pool if generation would exceed 60 s |
| Detective narrative | same homelab model | `think:false`, `format={events[], narrative_cs}`, temperature 0.2, `num_ctx` 16384 | Input = candidate-event table from the deterministic scan; may only accept/reject/merge, never invent dates. Cached for demo stories |
| Fallback (any step) | Claude via Anthropic API | `LLM_BACKEND=claude`; same Pydantic schema via tool/structured output | Works on the box and on the laptop; tested Wednesday on all three steps; key in `.env`, never in git |
| Offline | none | `LLM_BACKEND=replay` | Serves cached outputs; unknown prompts show "offline – cached stories only" |

**Why these settings.** `format` with `think:false` was broken on gemma4 until Ollama **0.21.1** ([#15260](https://github.com/ollama/ollama/issues/15260)). In **0.35.1**, combining `think:true` with a schema can return unconstrained output ([#18774](https://github.com/ollama/ollama/issues/18774)). So never mix thinking and `format` in one call. MLX tags ignore `format` ([#17183](https://github.com/ollama/ollama/issues/17183)), so use GGUF only. Run `ollama show gemma4-26b-nodraft --modelfile`; if that model is the variant without the MTP drafter, use it on the homelab. Ollama support for MTP outside MLX is unconfirmed ([pooyagolchian](https://pooyagolchian.com/blog/gemma-4-ollama-multi-token-prediction-local-2026/)).

**Homelab Ollama settings:**

- `OLLAMA_HOST=0.0.0.0`, firewalled to the box and the tailnet
- `OLLAMA_MAX_LOADED_MODELS=1`
- `OLLAMA_NUM_PARALLEL=1`
- `OLLAMA_FLASH_ATTENTION=1`
- `OLLAMA_KV_CACHE_TYPE=q8_0`. Every gigabyte of KV cache saved keeps 26B weights on the GPU. Do not use it with MTP drafting, which loses acceptance on quantized KV ([carteakey.dev](https://carteakey.dev/blog/local-inference/gemma-4-26b-qat-mtp/)).
- `num_ctx` ≤ 16K
- Ollama runs as an enabled systemd unit, and a oneshot unit warms the model with `keep_alive:-1` after boot.

If Ollama/ROCm is slow, try `llama-server` with Vulkan and `--json-schema` / `--n-cpu-moe`. On NVIDIA, tuned llama.cpp more than doubled the 26B's throughput ([carteakey.dev](https://carteakey.dev/blog/local-inference/gemma-4-26b-qat-mtp/)).

**Fine-tune: no.** Unsloth cannot LoRA the 26B-A4B at home: it needs more than 40 GB, and 4-bit QLoRA on the MoE is discouraged ([Unsloth](https://unsloth.ai/docs/models/gemma-4/train)). A 12B QLoRA is feasible, but there are no gold description→spec pairs to train on. The grammar already guarantees syntax. Export and chat-template debugging alone would eat an evening. If a judge asks, say: "Schema-constrained decoding plus a validator closes the gap a fine-tune would close, and it is auditable."

## Calendar: build the engine before Friday, spend the event on proof

The prep evenings are Tuesday 24, Wednesday 25 and Thursday 26 November. The event runs from Friday 15:00 to the 12:00 Saturday submission, with presentations 13:00–15:00 and results at 15:30 ([hackathon.4fis.cz](https://hackathon.4fis.cz/)). **Person A** is you. **B** and **C** are the newcomers. Their tasks are fully specified and nothing on the critical path depends on them.

### Prep evenings

| Evening | A (core) | B | C |
|---|---|---|---|
| **Tue 24** (tonight) | Repo + `uv` lock; Pydantic spec models + JSON schema export; sim skeleton (customers, products, orders, order_items, payments) with SeedSequence streams and determinism test; Ollama pinned on the homelab; **Proxmox Radeon passthrough + 26B vs 12B benchmark → model decision**; Ollama as an enabled systemd service; BIOS "power on after AC loss"; GitHub branch protection on `main`; SSH accounts for B and C on the box | Write 6 Czech company+story texts (3–6 sentences each) in a shared doc, following Example A's style; include 1 story with a "trap" (seasonal peak that is *not* an event) | Set up cloudflared SSH per repo README; clone into `~/work`, make a test branch, push it, open a PR (practice the workflow); collect 10 Czech e-shop review styles (paraphrased) as tone references |
| **Wed 25** | Event-curve compiler, churn hazard, stockout/inventory, deliveries, tickets, reviews; DuckDB + Postgres export with FKs; spec compiler (homelab model + retries), provider abstraction with `ollama`/`claude`/`replay` backends and LLM cache; **compose.yaml + nginx websocket config deployed**, background-job pattern for LLM calls; overnight Czech text-pool batch | Hand-write the YAML for 2 of their stories using the spec as a form; draft Czech slide deck from the pitch outline below (8 slides) | Streamlit Data tab on a branch: table browser + 3 Plotly charts from templates A provides (daily orders by city, churn by segment, rating by courier); proofread 100 generated reviews, flag bad Czech in a spreadsheet |
| **Thu 26** | Detective scan (STL+MAD, PELT/Binseg, drill-down, DiD lag search) + 26B narrator; scorer with Hungarian matching, no-story twin, seed sweep; end-to-end on Examples A and B **through the public URL**; **pre-generate 3 demo datasets + all their LLM outputs** into `./data` and `./data/llm_cache`; copy both to the laptop and test replay with Wi-Fi off; screen recording v0 | Rehearse 3-minute core twice (record on phone); write SWOT slide and "Jak jsme použili AI" disclosure slide | Score tab: answer key vs detective table side-by-side with green/red per slot; test the full flow 5× on fresh seeds from a phone on mobile data, log anything that crashes |

**Gate on Thursday night:** an end-to-end run of Example A **through https://hack.dobsinsky.dev** finishes in under 5 minutes and scores F1 ≥ 0.7, with ≤ 1 false event per year on the no-story twin. If it misses, Friday's first two hours go to tuning effect sizes and penalties, not to features.

### Event hours

At the venue the team works on laptops only: SSH to the shared box, the public URL, and Tailscale from A's laptop. Everything critical runs on the homelab. The desktop is an optional bulk-text worker (see the topology note above).

| Time | A | B | C |
|---|---|---|---|
| Fri 13:00–15:00 | Opening, keynote; at 14:15 note the exact Story2Data brief; ask the mentor the organizer questions below | Same; write down any required input/output format | Same; check the venue Wi-Fi reaches hack.dobsinsky.dev and SSH; test the projector with the public URL |
| 15:00–16:00 | Adapt DSL/prompt to the official brief (their example company/story through the pipeline once) | Turn official example story into a demo story; Czech text check of compiled YAML narratives | Confirm the homelab Ollama answers from the box (`curl …/api/tags`), and the desktop worker if it is on; open the UI on a phone over mobile data |
| 16:00–18:30 | Fix whatever the official example broke; tune detective penalties on 3 stories | Slides v2 incorporating the official brief's wording | Run 10 seeds of each demo story via the public URL; fill a QA sheet (crash / F1 / runtime) |
| 18:30–19:00 | Dinner | Dinner | Dinner |
| 19:00–22:00 | Example B JOIN+lag detection polish; difficulty knob → detection curve (F1 vs effect size) | Pitch script in Czech, timing to 3:00 core / 5:00 full | Chart polish on branch `feat/c-overlay`: answer-key overlay on time series (vertical lines at true dates, dots at detected); A reviews + merges |
| 22:00–01:00 (quiet hours start, hacking continues) | Placebo histogram + seed sweep chart; Postgres export checked from a fresh client | Sleep by 23:30 | Proofread Czech UI strings + reviews pool; sleep by 00:30 |
| 01:00–02:00 | Kick off overnight batch on the box: 3 demo datasets × 3 difficulties → `./data` (DuckDB, Parquet, pg_dump, scored reports); rsync `./data` (incl. `llm_cache`) to laptop for offline replay | — | — |
| 02:00–06:00 | Sleep (4 h) | Sleep | Sleep |
| Sat 06:00–08:00 | Bugfixes from batch logs; nothing new | Rehearsal ×2 with stopwatch | Run the **laptop-local compose** with cached data, internet off; check every tab |
| **08:00** | **Code freeze.** `sudo systemctl stop deploy` (and its timer) on the box; tag `v-demo`; only crash fixes, deployed by hand | — | — |
| 08:00–09:30 (breakfast 09:00) | Record full demo video (2:30) from the frozen build; write README + AI-use disclosure | Final slides; insert screenshots from the frozen build | Package submission: repo link, public URL, video, datasets, slides PDF |
| 09:30–11:00 | Full dress rehearsal ×3 with live demo; Q&A drill (Fabricate? how do you know it's not overfit? why not fine-tune?) | Presents the opening and teaching use case | Presents the "Data" tab and charts |
| 11:00–11:45 | Submit; verify links open in incognito | Backup copy of slides on USB + cloud | Charge everything; phone hotspot ready |
| 12:00 | Submission deadline, then lunch | | |
| 12:00–13:00 | Laptop on the charger; open the public URL and the offline replay, one tab each; one last check that the homelab Ollama answers | Last pass through the script | Projector and HDMI test if possible |
| 13:00–15:00 | Presentations (order unknown; be ready at 13:00) | | |
| 15:30 | Results | | |

**Fallback demo, in tiers:**

1. **Live run** at https://hack.dobsinsky.dev on the homelab Radeon. Demo stories come from the cache, and only the judge's custom story calls the LLM.
2. **Same URL, `LLM_BACKEND=claude`.** Use it if the Radeon or Ollama is slow or down while the box and tunnel are up. Fresh custom stories still work.
3. **Same URL, `LLM_BACKEND=replay`.** Pre-generated runs only. This is legitimate, because the output is deterministic. Use it if neither Ollama nor Claude responds in time.
4. **Laptop-local.** Run the same compose with `./data` + `llm_cache` and `LLM_BACKEND=replay`. It needs no internet, no tunnel and no GPU. If the venue has internet but home does not (power or ISP outage), switch the laptop to `LLM_BACKEND=claude` so custom stories still work. A gemma4:e4b or a partially offloaded 12B on the 3060 is a last resort only.
5. **The recorded video** embedded in the slides.

Decide before going on stage: if the live spec compile takes more than 90 seconds, switch to tier 2 and say so openly.

## Checklist, risks, and questions to settle before Friday

| # | Check | Pass criterion |
|---|---|---|
| 1 | `ollama --version` recorded on the homelab (and desktop if used); auto-update disabled | ≥0.21.1, written in README |
| 2 | Model tags are GGUF, not MLX; `ollama show gemma4-26b-nodraft --modelfile` read | no MLX; know whether DRAFT is attached |
| 3 | `format`+`think:false` on the chosen homelab model (26b or 12b) with the real spec schema | 20/20 valid JSON, then ≥18/20 pass semantic validators after retries |
| 4 | Never `think:true` with `format` | grep codebase: zero occurrences |
| 5 | **Proxmox GPU passthrough** (VM) or LXC with `/dev/kfd` + `/dev/dri`; card identified | `rocminfo` (or `vulkaninfo`) shows the Radeon and its gfx target; Ollama log says GPU, not CPU |
| 6 | **26B benchmark on the Radeon**, 1.5k-token output, `num_ctx` 16384, q8_0 KV | tok/s in README; layers on GPU ≥ ~90 %; detective call < 90 s |
| 7 | 12B benchmark on the Radeon (for the decision rule), plus optional desktop worker health-check | 12B 100 % GPU; app runs normally with the desktop powered off (skip logged, no error) |
| 7a | **Tailscale + public URL from a non-home network** (phone hotspot) | laptop reaches homelab Ollama via Tailscale; hack.dobsinsky.dev loads; SSH via cloudflared works |
| 7b | **Homelab survives reboot**: Ollama is an enabled systemd unit, model warmed by a oneshot `curl` with `keep_alive:-1`; app containers `restart: unless-stopped`; BIOS power-on after AC loss; sleep/suspend disabled | after `reboot`, public URL + first LLM call work with no manual step |
| 8 | Box → homelab Ollama over LAN (and desktop over Tailscale if used); `OLLAMA_HOST=0.0.0.0` firewalled | `curl http://<host>:11434/api/tags` succeeds from inside the app container |
| 9 | Streamlit through nginx + Cloudflare | public URL loads from mobile data; a 3-minute job keeps progress updating without disconnect |
| 10 | Branch protection + deploy kill switch | push to `main` from B's account is rejected; `systemctl stop deploy` tested and restarted |
| 11 | Faker `cs_CZ` gendered names (female "-ová") + `holidays.CZ(language="cs")` names | 20 sample names correct; 17. listopadu present |
| 12 | Determinism | two runs → identical Parquet hashes |
| 13 | Claude fallback | all three LLM steps pass with `LLM_BACKEND=claude` |
| 14 | No-story twin | ≤1 false event/year on Examples A and B |
| 15 | Postgres export | `psql` sees tables, FKs, row counts match DuckDB |
| 16 | Offline laptop replay | compose runs on laptop with internet off, `LLM_BACKEND=replay`, all 3 demo stories end to end from `llm_cache` |
| 17 | Laptop + Claude without home | with the homelab unreachable, laptop compose with `LLM_BACKEND=claude` compiles a fresh custom story |

**Questions for the organizers** (email 4fis.hackathon@gmail.com today, then confirm with the mentor at 14:15) ([hackathon.4fis.cz](https://hackathon.4fis.cz/)):

1. Is code written before the event allowed, and must it be disclosed?
2. Are cloud LLM APIs allowed?
3. Is there a scoring rubric, and is there a separate prize for this challenge?
4. How long is each pitch, and is there Q&A?
5. Will you provide sample companies or stories, and in what format?
6. Is a specific output required: Postgres, CSV, or a defined schema?
7. Can we project from our own laptop over HDMI, and is the venue Wi-Fi open to outbound HTTPS?
8. Who on the faculty side owns the challenge?

No rubric is published. The closest Czech proxy scores innovation, quality and correctness, usability, sustainability and presentation, each on 0–10. It requires a solution schema, a demo, a SWOT analysis and **disclosure of how AI was used** ([UP Olomouc rules](https://hackathon.upol.cz/wp-content/uploads/2024/09/pravidla.pdf)). Prepare for that rubric.

| # | Risk | Mitigation |
|---|---|---|
| 1 | Official brief requires an input/output format the engine doesn't match | Generic text in, DSL in the middle; first Friday hour reserved for adaptation; ask format by email today |
| 2 | Gemma emits schema-valid but semantically wrong spec | Semantic validators + retries + 26B escalation + editable YAML in UI; Claude last |
| 3 | Ollama regression or format/think bug on stage | Pinned version on the homelab, no `think` with `format`, auto-update off, `LLM_BACKEND=claude` or replay tiers |
| 4 | ROCm/Vulkan on Proxmox fails (passthrough, gfx detection) or 26B too slow on the Radeon | Do it **Tuesday**, not Friday; decision rule falls back to 12B; Vulkan llama-server as plan B; plan C = `LLM_BACKEND=claude` |
| 5 | Venue Wi-Fi outage, or **home power/ISP outage** (app box, Radeon and Postgres all go down together, so a Claude switch on the box cannot help) | Laptop-local compose with cached `./data` + `llm_cache` in replay mode; if venue internet works, laptop `LLM_BACKEND=claude` for custom stories; homelab auto-recovers after power returns (checklist 7b); video |
| 6 | Long LLM calls hit the ~100 s Cloudflare limit or Streamlit websocket drops | All LLM work as background jobs with polled progress; nginx `proxy_read_timeout 3600s` + Upgrade headers; tested via checklist #9 |
| 7 | Bad push auto-deploys and breaks the live demo | Branch protection, only A merges, deploy service stopped at 08:00 freeze, `v-demo` tag to roll back |
| 8 | Detective misses lagged/JOIN effects or cries wolf on decoys | Explicit lag grid and delivery-join KPI; STL seasonality, Binseg confirmation; no-story twin on screen; detection curve shows *where* it fails |
| 9 | "It's just an LLM with a prompt / Fabricate" | Story 1 demo: aggregate chart flat, joined chart shows lagged churn; LLM never writes rows |
| 10 | A is the single point of failure (fatigue, illness) | Everything critical exists Thursday; 4 h sleep scheduled; B/C can run the cached demo, video and slides alone |

## Pitch in Czech and three stories that prove the mechanism

The pitch slot is probably **about 5–7 minutes including Q&A**. That is inferred from roughly 15–25 teams sharing 13:00–15:00 ([hackathon.4fis.cz](https://hackathon.4fis.cz/)). The 3-minute core (beats 2–5) has to stand on its own.

**Beat 1 (0:00–0:30), B.** "Každý semestr učitelé na FIS hledají data, ve kterých *něco je*: odliv zákazníků, výpadek dodavatele, efekt kampaně. Northwind nic nevypráví a odpovědi jsou na internetu. Postavili jsme Story2Data."

**Beat 2 (0:30–1:15), A. Core starts.** "Napíšu příběh česky: Pražírna Zrnko zdražila, studenti po šesti týdnech odcházejí, zasekla se dodávka z Etiopie. Lokální model Gemma ho přeloží do specifikace. Ta je čitelná, editovatelná a je to zároveň klíč správných odpovědí. Pak deterministická simulace s pevným seedem vytvoří 15 propojených tabulek: zákazníky, objednávky, dodávky, tikety, recenze. Model nevymýšlí řádky. Model jen píše texty recenzí."

**Beat 3 (1:15–2:15), A + C.** "Teď detektiv. Spec nevidí, vidí jen databázi. Hledá zlomy, rozpadá je po segmentech, testuje zpoždění. Tady našel zdražení 1. března, tady odchod studentů 42 dní poté a tady Brno." Show the Score tab: "Přesnost, úplnost, F1. A tady je stejný svět bez příběhu: detektiv nenašel nic. Neplete si Black Friday s příběhem."

**Beat 4 (2:15–2:45), A.** "Proč to není jen LLM s promptem? Kurýr na Moravě. V celkovém hodnocení nic nevidíte. Po JOINu zákazníků na doručení a posunu o pět týdnů je to jasné. Takový vztah textový generátor řádků nezaručí. Simulace ho způsobí."

**Beat 5 (2:45–3:00), B.** "Pro výuku: každý student dostane vlastní seed, vlastní data a stejný typ příběhu. Učitel má klíč a automatické hodnocení. Obtížnost se nastavuje jedním přepínačem."

**Beat 6 (3:00–4:00), C + A.** Show the detection curve (F1 against effect size), state the honest limits (the SWOT slide), then the AI-use disclosure slide. The disclosure says Gemma 4 runs locally for the spec, texts and narrative, and code assistants were used during prep.

**Beat 7 (4:00–4:30), A.** Related work in one sentence: "InsightBench zasazuje vzory do jedné tabulky a hodnotí je LLM soudcem. My máme relační databázi, kauzální simulaci a numerické skóre" ([arXiv 2407.06423](https://arxiv.org/html/2407.06423v1)). Then close: "Příběh není popisek. Dá se dohledat, změřit a ohodnotit."

Three demo stories, chosen for what each one proves:

| Story | What the judge sees | Why it convinces |
|---|---|---|
| **1. Kurýr na Moravě** (Example B) | Overall rating and churn charts look flat; the joined query `customers ⋈ orders ⋈ deliveries` with a 30–60-day window after late delivery shows churn nearly doubling in Ostrava/Olomouc | The effect exists **only via JOIN + lag**; a row-level LLM generator has no mechanism to produce it consistently across four tables |
| **2. Zdražení a studenti** (Example A, E1→E2) | Price step in `product_prices`, immediate small dip, then student churn rising after ~6 weeks; detective links E2 to E1 with lag | Causal chain with a stated lag recovered numerically, including the `caused_by` bonus |
| **3. Etiopie a konkurence v Brně** (Example A, E3–E5, plus decoys) | Stockout run on Ethiopian SKUs → ticket spike → Brno subscriber churn; competitor ramp in Brno stores; viral accessory spike and Black Friday *not* reported | Precision matters: the decoys and the no-story twin show the detective does not invent stories, the TCPDBench lesson that false positives are the main failure ([arXiv 2003.06222](https://arxiv.org/pdf/2003.06222v3)) |

For the Nova and ČS judges, keep one line ready: the same DSL can describe a viewership drop after a schedule change or a branch closure that pushes customers to mobile. Say it. Do not build it.

## Conclusion

The winning move is not a bigger generator. It is a **falsifiable** one. Most teams will show a dataset and claim the story is in it. You will show the jury a number for how well a blind detective recovered the story, and a twin dataset where it correctly found nothing. That changes the judging question from "does this look realistic?" to "did the story come back out?", which is exactly the challenge text.

The calendar matters as much as the design. By Thursday night, two of the three people should be unable to break anything critical, and the person who can should have nothing left to invent. Under the rubric this event is likely to use, that is the difference between a demo and a working system.
