# Simulation Engine for Story-Driven Synthetic Business Data (Python, 24h build)

> Scope: deterministic agent-based / discrete-event business sim producing a relational dataset (customers, products, orders, order_items, payments, tickets, reviews, employees, stores, campaigns) where scripted "story events" causally drive patterns. Research date 2026-11-24. Tool budget was limited (~17 calls); items marked "Inference" are engineering judgement, not cited facts.

## Which engine: SimPy vs Mesa 3.x vs Salabim vs numpy/pandas day-loop vs polars

### Takeaway
**Recommendation: plain numpy (Generator) + pandas/polars "vectorized day-by-day" loop over customer arrays, with a small declarative Event/Effect layer — no DES/ABM framework.** At 5k-50k customers x 365-730 days, a per-day vectorized step (one Poisson/Bernoulli draw over all customers per day) is ~0.5-37M draws total and runs in seconds; SimPy/Salabim/Mesa add per-agent Python overhead and a learning/API surface without giving you anything the story layer needs (no queues/resources are central to the story). Use SimPy only if you want a genuine queueing sub-model (e.g., support-ticket backlog with limited agents), and even that can be a simple daily capacity calculation.

### Cited Findings
- SimPy latest is 4.1.2 (released 2026-05-24); the 4.x API has been stable since 4.0.0 — [PyPI simpy](https://pypi.org/project/simpy/4.1.1/), [Repology simpy versions](https://repology.org/project/python:simpy/versions)
- Mesa 3 is the current major line: v3.4.2 (2026-01-23) fixed "a critical memory leak affecting all Mesa models"; v3.5.0 (2026-02-15) added explicit Scenario support and creating agents directly from a pandas DataFrame; v3.5.2 (2026-10-28) fixed AgentSet.do()/shuffle_do()/map() skipping removed agents; Mesa 4 pre-releases have started (API churn risk) — [Mesa on Zenodo](https://zenodo.org/records/18349187), [Mesa PyPI](https://pypi.org/project/Mesa/), [mesa/mesa GitHub](https://github.com/mesa/mesa), [Mesa 3 JOSS paper](https://www.theoj.org/joss-papers/joss.07668/10.21105.joss.07668.pdf)
- Salabim latest 26.0.8 (2026-06-24), frequent 2026 releases (26.0.4 Mar, 26.0.5 Apr, 26.0.6 May); it is object-oriented DES with queues, resources, stores, statistical sampling, monitoring and 2D/3D animation, aimed at logistics — [libraries.io salabim](https://libraries.io/pypi/salabim), [salabim manual](https://salabim.org/manual/Overview.html), [salabim JOSS paper](https://www.theoj.org/joss-papers/joss.00767/10.21105.joss.00767.pdf)
- PaySim (the canonical synthetic-transaction ABM) uses aggregated statistics from a real dataset to calibrate agent behaviour, generates "normal" transactions and then injects malicious behaviour — i.e., a baseline+injection design — [PaySim EMSS 2016 paper](https://www.msc-les.org/proceedings/emss/2016/EMSS2016_249.pdf), [Semantic Scholar](https://www.semanticscholar.org/paper/Paysim:-a-financial-mobile-money-simulator-for-Lopez-Rojas-Elmir/3a1d2057543cdf2a771f7421c8deab280a04779d)
- AMLSim uses Java MASON for the agent engine plus Python scripts for graph generation; config is a `conf.json` (seed, total steps, base date, input/output paths) and suspicious typologies are injected from an `alertPatterns.csv` parameter file — [IBM/AMLSim](https://github.com/IBM/AMLSim)
- Synthea models behaviour as JSON "Generic Modules": a progression of states and transitions between them (state machine), with states/transitions/logic documented separately — [Synthea Generic Module Framework](https://github.com/synthetichealth/synthea/wiki/Generic-Module-Framework)

### Inferences
- Rough sizing (inference): 50k customers x 730 days = 36.5M customer-days. One vectorized `rng.poisson(lam_array)` per day over a 50k float array is microseconds-to-low-ms; total sim loop for purchases < ~5-10 s on a Ryzen 7 5800X. Generating order_items/payments from the resulting ~100k-1M orders is also vectorizable (`np.repeat`, `rng.choice` with Zipf weights). A Mesa model with 50k Python agent objects stepping 730 times = 36.5M Python method calls ≈ minutes and more code.
- Polars vs pandas: the bottleneck is the per-day numpy draw, not dataframe ops. Keep state in numpy arrays during the loop, append per-day order arrays to Python lists, concatenate once at the end, then build DataFrames. Polars is optional (nice for fast post-processing and Parquet writes); pick whichever the team knows. Don't mix both.
- Mesa's DataFrame-to-agents and Scenario features are attractive, but Mesa 4 pre-releases signal impending API changes, and the recent memory-leak/AgentSet bug fixes show the 3.x line still moves — unnecessary risk for a 24h build.
- SimPy is stable and tiny; it's justifiable only for one sub-model where queuing matters (support center: tickets arrive, N employees resolve, wait time → satisfaction → churn). Even this can be approximated with daily `backlog = max(0, backlog + arrivals - capacity)`, which is deterministic and simpler.
- Architecture borrowed from PaySim/AMLSim/Synthea: (1) baseline behaviour model calibrated by parameters, (2) a separate declarative file of injected "typologies"/story events, (3) a fixed seed + base date + step count in config. That separation is the main pattern to copy — it makes the story auditable ("ground truth" table of events) which is a strong demo point.

### Gaps
- No published benchmark found comparing SimPy/Mesa/Salabim/numpy throughput for this specific workload; the sizing above is an estimate.
- Polars current version/API stability as of late 2026 was not verified in this session.

## Event-driven modifiers: hazards, churn, lags/ramps/decay, segment targeting

### Takeaway
Model every customer behaviour as a **daily rate (intensity) = baseline x seasonality x product of active event multipliers**, and churn as a **daily hazard** with the same multiplicative structure. Each story event is a record `{start_date, target (segment/city/product/store), metric (purchase_rate | churn_hazard | price | stock | ticket_rate | rating), effect_size, lag_days, ramp_days, duration, decay_halflife}`, compiled into a per-day multiplier curve and applied via boolean masks over the customer arrays.

### Cited Findings
- PaySim/AMLSim pattern: baseline generator + injected behaviours/typologies defined in parameter files — [PaySim paper](https://www.msc-les.org/proceedings/emss/2016/EMSS2016_249.pdf), [IBM/AMLSim](https://github.com/IBM/AMLSim)
- Synthea: state-machine modules with delays and conditional transitions on patient attributes — [Synthea GMF](https://github.com/synthetichealth/synthea/wiki/Generic-Module-Framework)
- An existing open-source e-commerce generator exposes `seasonal_factors` and `retention_shocks` in YAML plus long-tail churn & reactivation with dormancy periods and spend-based loyalty tiers — [G-Schumacher44/ecom_sales_data_generator](https://github.com/G-Schumacher44/ecom_sales_data_generator)

### Inferences (implementation patterns)
- **Purchase process**: per customer i, day t: `lam[i,t] = base_rate[i] * dow[t] * yearly[t] * holiday[t] * prod_e M_e(t) * active[i]`; `n_orders = rng.poisson(lam)` (mostly 0/1). `base_rate` ~ Gamma (heterogeneity → negative-binomial counts, i.e., realistic "few heavy buyers").
- **Effect curve** for event e with lag L, ramp R, duration D, half-life H, size s (e.g., s=+0.15 for hazard or -0.2 for rate):
  `w(t) = 0 if t<start+L; ramp = min(1,(t-start-L)/R); after start+L+R+D: decay = 0.5**((t-end)/H)`; multiplier `M = 1 + s*w(t)` (or `exp(log(1+s)*w)` to keep positive).
- **Hit an exact story target** ("15% of segment X churns over the 2 weeks after a 2-week lag"): convert a target cumulative probability p over window W to a constant daily extra hazard `h = 1-(1-p)**(1/W)` and add it to baseline hazard for the masked segment. Deterministically checkable afterwards — print "target vs realized" in a validation report.
- **Churn as survival**: `alive &= rng.random(n) >= hazard[i,t]`; store `churn_date`. Baseline hazard can rise with days-since-last-order (recency) and with unresolved tickets → creates emergent causal chains (stockout → tickets → churn).
- **Stockouts (supplier delay)**: keep per-product (or per-store-product) inventory array; replenishment shipments scheduled by lead time; the event multiplies lead time for supplier S. When stock=0, demand for that product converts to: lost sale (no order), substitution (choose another product in category), or backorder (late ship date) — each leaves a different fingerprint in data.
- **Competitor opens in Brno**: mask `city=='Brno'`, rate multiplier e.g. 0.8 with ramp 30 days; also shift share from store-pickup to e-shop, and raise price sensitivity.
- **Price increase**: modify `products.price` history (SCD-type `product_prices` table with valid_from) so analysts can join; demand elasticity multiplier `(p_new/p_old)**elasticity` per segment.
- **Marketing campaigns**: campaign rows with channel/target segment/budget; effect = rate multiplier during flight + acquisition spike (new customers created with `acquisition_campaign_id`) → gives attributable FK.
- Keep an `events` ground-truth table in the output DB (not shown to the "analyst" persona) to demo "the agent found the planted story".
- Ordering of per-day loop: apply events → update prices/inventory → acquisitions → churn → purchases (allocate products, check stock) → payments (failure/refund probabilities) → tickets (rate depends on late shipments/stockouts) → reviews (rating depends on delay/ticket) → append.

### Gaps
- Did not retrieve PaySim/AMLSim source code details on how they parameterise time-varying intensities; patterns above are standard point-process/survival modelling, not copied from those codebases.

## Realism layer: seasonality, Czech holidays, distributions, dirty data, Czech fake data

### Takeaway
Use the `holidays` library (`holidays.CZ`, supports Czech language names) for holiday/closure effects, multiplicative weekly + yearly profiles (Christmas peak, Black Friday, summer dip), Gamma-Poisson customer heterogeneity, Zipf product popularity, log-normal/geometric basket sizes, and a final "messiness" pass (MCAR/MAR nulls, typos, duplicates, late arrivals) applied *after* the clean ground truth is saved. Faker `cs_CZ` is the safe default for names/addresses; Mimesis (`Locale.CS`) is a faster alternative.

### Cited Findings
- `holidays` supports Czechia with code `CZ`, languages cs, en_US, sk, uk, and no subdivisions — [holidays PyPI](https://pypi.org/project/holidays/0.34/), [vacanza/holidays GitHub](https://github.com/vacanza/holidays). Version 0.101 released 2026-07-20 and 0.103 dev builds through Aug 2026 — [libraries.io holidays](https://libraries.io/pypi/holidays). (Note: one search snippet claimed v0.34 was released Nov 2026; that is inconsistent with the 0.10x line and should be disregarded.)
- Python Faker cs_CZ address provider offers `address, city, postcode, street_name, street_suffix, building_number, administrative_unit, city_with_postcode` — [Faker cs_CZ docs](https://faker.readthedocs.io/en/master/locales/cs_CZ.html) (page returned 404 when fetched directly in this session; listing from search snippet), [Snowfakery cs_CZ fake data reference](https://snowfakery.readthedocs.io/en/v2.2/fakedata/cs_CZ.html)
- Mimesis supports Czech as `Locale.CS` with Person and Address providers — [Mimesis locales](https://mimesis.name/master/locales.html)
- Existing generator implements a "messiness engine" with levels baseline/light/medium/heavy injecting typos, duplicates, nulls and formatting inconsistencies — [ecom_sales_data_generator](https://github.com/G-Schumacher44/ecom_sales_data_generator)

### Inferences (techniques)
- **Seasonality**: `dow = [1.0,0.95,0.95,1.0,1.15,1.25,0.8]` style vector; yearly via smooth sum of Fourier terms + spikes (Black Friday last Fri of Nov, 1-20 Dec Christmas ramp, drop 24-26 Dec, January slump, summer dip). Czech-specific: stores closed on some public holidays (Czech law restricts large-store opening on certain holidays — verify list before claiming), Easter Monday, 28 Oct, 17 Nov. Use `holidays.CZ(years=[2025,2026], language='cs')` for names in Czech.
- **Product popularity**: weights `1/rank**s` (s≈1.0-1.2) shuffled per category; `rng.choice(n_products, size=k, p=w)`. Rotate a few "trending" products over time for realism.
- **Basket size**: `1 + rng.geometric(0.45)` or `1 + poisson(lognormal)`; quantities mostly 1 with occasional bulk; order value heavy-tailed (lognormal).
- **Customers**: Gamma-distributed base purchase rates by segment; acquisition dates spread with growth curve; signup channel; segment by age/city/loyalty.
- **Czech names**: generate gender first and use `first_name_male/female` + `last_name_male/female` so female surnames take "-ová" forms consistently (inference: Faker cs_CZ has separate gendered surname lists — verify quickly in REPL). Pick cities from a weighted real list (Praha, Brno, Ostrava, Plzeň, Liberec, Olomouc…) rather than Faker's random city so geography matches stores; use Faker only for street/house number. Czech PSČ format "XXX XX".
- **Dirty data** (apply to an export copy, keep clean ground truth): MCAR nulls in optional fields (phone 5%); MAR nulls (e.g., `review_text` missing more often for 4-5 star ratings, `email` missing more for store-channel customers); typos (char swap/drop, diacritics stripped "Plzen" vs "Plzeň", case variants "BRNO"); duplicate customers (same person, slightly different email/case, new id) ~1-2%; duplicate order rows from "retries"; inconsistent phone formats (+420 / 00420 / none); late-arriving data (`ingested_at = event_time + lognormal delay`, some payments posted days later; a few orders with `updated_at` after period end); timezone mix; negative quantities for returns.

### Gaps
- No independent quality comparison of Faker cs_CZ vs Mimesis cs names/addresses found; Faker docs page could not be fetched (404). Recommend a 5-minute REPL check of both.
- Specific Czech retail-closure holidays (Act No. 223/2016) not verified in this session.

## Writing to Postgres vs DuckDB/SQLite; FK integrity

### Takeaway
Generate everything into DataFrames, write Parquet + a **DuckDB file** as primary artifact (zero-ops, fast, great for demo/LLM-SQL), and load Postgres only if the hackathon requires it — via **psycopg3 `cursor.copy()`** or **DuckDB's postgres extension (`ATTACH ... (TYPE postgres)` + `COPY`/`INSERT ... SELECT`, binary COPY by default)**. Avoid default `pandas.to_sql` (row INSERTs). Create tables with PKs, load in dependency order, then add FK constraints (or create them up front and load parent→child).

### Cited Findings
- psycopg3: `cursor.copy("COPY ... FROM STDIN")` returns a `Copy` context manager; `copy.write_row(record)` adapts Python values; `copy.write()` streams pre-formatted blocks; `FORMAT BINARY` is faster but requires exact types (use `set_types()`); CSV/DELIMITER options are incompatible with `write_row` — [psycopg3 COPY docs](https://www.psycopg.org/psycopg3/docs/basic/copy.html)
- DuckDB postgres extension can read and write a running Postgres; attach via `ATTACH 'dbname=... host=...' AS db (TYPE postgres)`; `COPY db.tbl FROM 'data.parquet'` works; binary COPY protocol used by default (`pg_use_binary_copy`) — [DuckDB Postgres extension docs](https://duckdb.org/docs/2.0/core_extensions/postgres/overview), [DuckDB postgres scanner blog](https://duckdb.org/2022/09/30/postgres-scanner)
- pandas `to_sql` accepts `method=None|'multi'|callable`; the pandas IO docs include an example callable that uses Postgres COPY for speed — [pandas IO docs, insertion method](https://pandas.pydata.org/docs/user_guide/io.html#insertion-method) (the fetch summary of this page was partly garbled; the string `'psql_insert_copy'` is NOT a built-in method name — it is a user-defined function in the docs example)

### Inferences
- At ≤1M rows, any COPY-based path loads in seconds; INSERT-based `to_sql` could take minutes.
- Simplest robust path: `duckdb.sql("CREATE TABLE orders AS SELECT * FROM orders_df")` (DuckDB scans pandas/polars DataFrames directly), then optionally `ATTACH` Postgres and `CREATE TABLE pg.orders AS SELECT * FROM orders` — one code path for both targets. Add PK/FK DDL in Postgres afterwards via SQL file.
- FK integrity is guaranteed by construction (IDs are array indices allocated by the sim). Deliberately "dirty" variants (orphan rows) must live in a separate schema/export without FK constraints, or FKs will reject them.
- Is Postgres necessary? For a demo, no — unless judges/tools (e.g., an existing BI or text-to-SQL stack) expect a Postgres connection. A Docker Postgres in the existing compose file is cheap insurance.

### Gaps
- DuckDB version and whether docs path "2.0" reflects a released DuckDB 2.0 not verified.

## Reproducibility: seeding and substreams

### Takeaway
One root seed in config → `np.random.SeedSequence(root)` → spawn **named child streams per subsystem** (acquisition, purchases, products, payments, tickets, reviews, messiness, faker). This keeps outputs stable when you change one subsystem (e.g., adding a ticket rule won't reshuffle orders). Seed Faker separately (`Faker.seed_instance(n)`) from a derived integer. Avoid per-customer Generators (slow); use vectorized draws from subsystem streams; if per-entity stability is needed, use `default_rng([entity_id, root_seed])`.

### Cited Findings
- `SeedSequence(12345).spawn(n)` → independent child streams via tree-hashing; collision probability ~n²·2⁻¹²⁸ (≈2⁻⁸⁸ for 1M streams); `Generator.spawn(n)` is a convenience shortcut — [NumPy parallel random generation](https://numpy.org/doc/stable/reference/random/parallel.html)
- Per-entity ad hoc seeding: `default_rng([worker_id, root_seed])` — put the varying ID *before* the fixed root seed; human-chosen seeds are biased, prefer a 128-bit root from `secrets` (fix it once in config) — [NumPy parallel](https://numpy.org/doc/stable/reference/random/parallel.html)
- Philox counter-based streams with `Philox(key=root_seed + stream_id)` as an alternative — [NumPy parallel](https://numpy.org/doc/stable/reference/random/parallel.html)

### Inferences
- Determinism hazards: iterating Python `set`s/dict of unordered origin, `pandas.sample` without `random_state`, Faker global seeding, multiprocessing order, and `datetime.now()` for "ingested_at" — all must be derived from sim time/seeded streams. Add a test: run twice, hash Parquet outputs, assert equal.
- Use `default_rng([SUBSYSTEM_ID, day_index, root_seed])` per day per subsystem if you want "change one day's event without perturbing earlier days" (cheap: 730 x ~8 generators).

### Gaps
- None material.

## Open-source examples/templates to borrow from

### Takeaway
The closest template is **G-Schumacher44/ecom_sales_data_generator** (MIT; YAML-configured relational e-commerce generator with churn/reactivation, `seasonal_factors`, `retention_shocks`, messiness levels, Postgres/SQLite output, QA tests). Conceptual references: PaySim (baseline + injected behaviour), AMLSim (conf.json + typology CSV injection), Synthea (state-machine modules). No found project implements a dated "story event → lagged causal effect" DSL, which is the differentiator to build.

### Cited Findings
- ecom_sales_data_generator: tables orders, order_items, returns, return_items, shopping_carts, cart_items, product_catalog, customers; CLI `ecomgen`; messiness engine; Faker + PyYAML; Pytest + SQL audit; MIT — [GitHub](https://github.com/G-Schumacher44/ecom_sales_data_generator)
- markoxtomic/ecomgen: catalog, customers, orders, returns and daily marketing performance with market-aware currencies, tax, demand, locale data — [GitHub](https://github.com/markoxtomic/ecomgen)
- Smaller Faker+NumPy generators (e.g., shopsense, dyllansegura/ecommerce-data-generator) exist but are simple random generators — [shopsense](https://github.com/shubhamtyagi1306/shopsense-ecommerce-analytics), [ecommerce-data-generator](https://github.com/dyllansegura/ecommerce-data-generator)
- AMLSim (Java MASON + Python, conf.json, alertPatterns.csv) — [IBM/AMLSim](https://github.com/IBM/AMLSim); PaySim — [paper](https://www.msc-les.org/proceedings/emss/2016/EMSS2016_249.pdf); Synthea GMF — [wiki](https://github.com/synthetichealth/synthea/wiki/Generic-Module-Framework)

### Inferences
- Borrow: config schema ideas and messiness taxonomy from ecom_sales_data_generator; ground-truth "alerts/events" table idea from AMLSim; keep own core loop (numpy vectorized) since none of these implement lagged multiplicative event effects.
- Suggested repo layout (inference): `config/story.yaml` (events), `sim/entities.py` (init customers/products/stores/employees), `sim/effects.py` (curve compiler), `sim/loop.py` (daily step), `sim/realism.py` (seasonality, holidays), `sim/dirty.py`, `sim/export.py` (DuckDB/Parquet/Postgres), `tests/test_story_recovery.py` (assert each planted effect is detectable: e.g., churn in segment X in window ≈15% ± tolerance).

### Gaps
- Did not inspect ecom_sales_data_generator source quality or last-commit date; verify activity before forking.
