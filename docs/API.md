# Story2Data HTTP API (v1)

Base URL: `https://hack.dobsinsky.dev` (locally `http://localhost:8000`). Swagger: `/docs`,
schema: `/openapi.json`. All bodies are JSON (UTF-8), except the ZIP download.

A run takes 1–2 minutes and Cloudflare cuts a request after ~100 s, so nothing waits:
`POST /v1/jobs` returns a `job_id` at once, then poll `GET /v1/jobs/{id}` (every 2 s is fine)
until `status` is `done` or `error`, then read `/result`.

## Auth

Every endpoint except `GET /v1/health`, `GET /v1/stats`, `GET /v1/system`, `/docs` and `/openapi.json` needs

```
Authorization: Bearer <token>
```

| role | can |
|---|---|
| `student` | create jobs, see **own** jobs, input, result, tables, query, DDL, download, run the detective |
| `teacher` | the same on **every** job, + `answer-key`, + the detective's score, + `GET /v1/jobs?scope=all` |
| `admin` | everything; `GET /v1/jobs` lists every job (with or without `scope=all`) |

A job you may not see answers `404 job not found` (not 403), so ids do not leak.

**Public mode** (`API_PUBLIC_ROLE`, on for the hackathon demo with `teacher`): a request **without**
`Authorization` is user `public` with that role, so the web page works without a login.
A token still wins, and an unknown token is still `401`.

## Errors

Every error is `{"detail": "<message>"}` with these codes:

| code | when | example `detail` |
|---|---|---|
| 400 | the request is well-formed but cannot run | `"spec_yaml is not a valid spec: meta.days: Input should be less than or equal to 1095"` |
| 400 | SQL error in `/query` | `"Catalog Error: Table with name foo does not exist!"` |
| 401 | no / unknown token | `"missing or unknown token"` |
| 403 | wrong role (`answer-key`, `GET /v1/jobs?scope=all`) | `"teacher or admin only"` |
| 404 | no such job (or not yours), table, data files, or detective run | `"job not found"`, `"table not found"`, `"data not found"`, `"detective not run"` |
| 408 | `/query` ran over 20 s | `"query timed out after 20 s"` |
| 409 | the job is not `done` yet (result, tables, ddl, query, download, answer-key, detect) | `"job is running, not done"` |
| 422 | body or query parameters do not match the schema (FastAPI) | see below |

422 is FastAPI's own format, `detail` is a list:

```json
{"detail": [{"type": "less_than_equal", "loc": ["body", "n_customers"],
             "msg": "Input should be less than or equal to 100000", "input": 500000,
             "ctx": {"le": 100000}}]}
```

## Endpoints

### `GET /v1/health` (no auth)

```json
{
  "ok": true,
  "llm": {"backend": "ollama", "model": "gemma4:26b", "reachable": true},
  "queue": {"running": "20261127-191502-3fa9c1", "waiting": 2}
}
```

`running` is the id of the running job or `null`. `reachable`: Ollama answers (`ollama`), an
API key is set (`claude`), always `true` for `replay` (cache only, no network). `ok` is
`false` only when the worker thread is dead.

### `GET /v1/system` (no auth): server load for the live Spec page

One sample a second of the last 15 minutes (oldest first), so a chart is full when it opens.
CPU, memory and load are the server's (`/proc`); `vram_gb` is the Ollama model's, `null` when
the backend is not Ollama or does not answer.

```json
{"cores": 14, "mem_total_gb": 33.4, "period_s": 1.0, "gpu": {"loaded": true, "vram_gb": 17.8},
 "step": "kalibrace a simulace", "customers_now": 20000, "waiting": 0,
 "samples": [{"t": 1796000000.0, "cpu": 63.5, "mem_gb": 5.2, "load": 4.1, "vram_gb": 17.8,
              "progress": 0.55, "customers": 20000}]}
```

### `GET /v1/stats` (no auth): the homepage dashboard

```json
{
  "jobs_total": 23,
  "jobs_done": 19,
  "jobs_today": 7,
  "running": {"job_id": "20261127-191502-3fa9c1", "step": "kalibrace a simulace", "step_index": 2,
              "progress": 0.55, "eta_s": 35},
  "waiting": 1,
  "median_run_s": 81,
  "events_confirmed_pct": 87.5,
  "twin_false_pct": 3.1,
  "customers_simulated": 412000,
  "rows_generated": 9731554,
  "recent": [
    {"job_id": "20261127-191502-3fa9c1", "title": "Pražírna Zrnko",
     "finished": "2026-11-27T19:16:16+01:00", "elapsed_s": 74, "summary": {"story": "4/4", "twin": "0/4"}}
  ],
  "timeline": [
    {"hour": "2026-11-26T20:00:00+01:00", "jobs": 0, "median_run_s": null},
    {"hour": "2026-11-26T21:00:00+01:00", "jobs": 3, "median_run_s": 77},
    "... 24 entries, oldest first, the last one is the current hour ..."
  ]
}
```

Computed from the job files at most every 5 s (cached in between), so polling it every 5 s is
fine. Over every user's jobs; it has no owner names and no story texts, only job titles.

- `jobs_total`: every job, any status. `jobs_done`: status `done`. `jobs_today`: created
  today (server time).
- `running`: the job the worker runs now, with these five fields as in `GET /v1/jobs/{id}`; `null` when idle.
  While the detective runs it is `{"job_id": ..., "step": "detektiv", "step_index": 0, ...}`.
- `waiting`: items in the queue behind it (generate and detective), as in `/v1/health`.
- `median_run_s`: median of `finished − started` of the done jobs (queue wait not included);
  `null` before the first one.
- `events_confirmed_pct`: confirmed story rows / tested story rows (`status` not
  `not_testable`) of `/result` `verification`, over all done jobs, in % (0–100, one decimal).
- `twin_false_pct`: tested rows with `twin_confirmed: true` / tested rows with a twin value,
  in %: how often the twin without the story "finds" the event (a false alarm).
  Both are `null` while nothing was tested.
- `customers_simulated`, `rows_generated`: sums of `/result` `rows` (`customers`, and all
  tables) over done jobs; the story world only (the twin is not counted).
- `recent`: the last 20 done jobs, newest `finished` first.
- `timeline`: always 24 hours, oldest first, the last entry is the current (unfinished)
  hour; `hour` is its start. `jobs`: done jobs that finished in that hour, `median_run_s` their
  median run time (`null` when `jobs` is 0).

### `POST /v1/jobs` → 202

Either a story (the AI writes the spec):

```json
{
  "company": "Pražírna Zrnko, kavárny v Praze a Brně a e-shop ...",
  "story": "V březnu 2026 jsme zdražili o 15 %, studenti začali odcházet ...",
  "difficulty": "medium",
  "seed": 42,
  "n_customers": 20000,
  "dirt": "low"
}
```

or a ready spec (skips the AI; tests, replays, hand-edited specs):

```json
{"spec_yaml": "meta:\n  seed: 42\n  ...", "n_customers": 5000}
```

| field | type | default | meaning |
|---|---|---|---|
| `company` | string | – | company description (Czech). Required with `story` unless `spec_yaml` |
| `story` | string | – | the story (Czech) |
| `spec_yaml` | string | – | a StorySpec as YAML; when given, `company`/`story` are ignored |
| `difficulty` | `easy` \| `medium` \| `hard` | from the spec | how findable the events are (stated sizes stay) |
| `seed` | int | from the spec | same seed → same data |
| `n_customers` | int 500 – 100000 | from the spec | number of customers |
| `dirt` | `none` \| `low` \| `medium` \| `high` | from the spec (`noise.messiness`) | the messy export (`messy/` in the ZIP) |

Response **202**:

```json
{"job_id": "20261127-191502-3fa9c1", "status": "queued", "position": 1}
```

`position`: jobs ahead of this one (0 = it is next, or already running).
Errors: 400 (invalid `spec_yaml`), 401, 422 (no `company`+`story` and no `spec_yaml`:
`"detail": [{"type": "value_error", "loc": ["body"], "msg": "Value error, give company and story, or spec_yaml", ...}]`).

### `GET /v1/jobs?scope=mine`

Own jobs, newest first (admin: everyone's). `scope=all` lists **every** job for teacher and
admin (403 `"teacher or admin only"` for a student), so in public mode (`teacher`) the web page
shows the whole history, including the demo jobs made with team tokens. `scope=mine` is the
default.

```json
{"jobs": [
  {"job_id": "20261127-191502-3fa9c1", "status": "done", "title": "Pražírna Zrnko",
   "owner": "michal", "created": "2026-11-27T19:15:02+01:00", "elapsed_s": 74,
   "summary": {"story": "4/4", "twin": "0/4"},
   "story_preview": "V březnu 2026 jsme zdražili o 15 %, studenti začali odcházet ..."}
]}
```

`summary` is `null` until the job is done. `story_preview`: the first 120 characters of the
story (trimmed), `null` for a `spec_yaml` job.

### `GET /v1/jobs/{id}/input`: the prompt as sent

Any status, same visibility as the job.

```json
{"company": "Pražírna Zrnko, kavárny v Praze a Brně a e-shop ...",
 "story": "V březnu 2026 jsme zdražili o 15 %, studenti začali odcházet ...",
 "difficulty": "medium", "seed": 42, "n_customers": 20000, "dirt": "low", "spec_given": false}
```

The fields of `POST /v1/jobs` as given (`null` when left out). For a `spec_yaml` job
`company` and `story` are `null`, `spec_given` is `true` and `n_customers` is the spec's count
unless one was given; the spec itself is in `/result` `spec_yaml`, not repeated here.

### `GET /v1/jobs/{id}`: status (the progress bar reads this)

```json
{
  "job_id": "20261127-191502-3fa9c1",
  "status": "running",
  "position": 0,
  "step": "kalibrace a simulace",
  "step_index": 2,
  "steps_total": 5,
  "progress": 0.55,
  "elapsed_s": 48,
  "eta_s": 35,
  "steps": [
    {"name": "specifikace (AI)", "done": true, "s": 31, "note": "platná na 1. pokus"},
    {"name": "kalibrace a simulace", "done": false, "eta_s": 18},
    {"name": "dvojče bez příběhu", "done": false, "eta_s": 4},
    {"name": "ověření", "done": false, "eta_s": 2},
    {"name": "český příběh (AI)", "done": false, "eta_s": 11}
  ],
  "error": null
}
```

- `status`: `queued` → `running` → `done` | `error`.
- `step`: name of the running step (`null` when queued, done or error). `step_index` is
  1-based (1..5), `0` while queued, `5` when done.
- The five steps are always these, in this order. With `spec_yaml` the first one is
  `{"name": "specifikace (AI)", "done": true, "s": 0, "note": "spec zadán (bez AI)"}`.
- A finished step: `{name, done: true, s, note}` (`note` may be `""`). A step not finished:
  `{name, done: false, eta_s}`; for the running step `eta_s` is what is left of it.
- `eta_s`: seconds left for the whole job (while queued it includes the jobs ahead).
  The estimate is the median of earlier runs of each step; the simulation steps are scaled
  by `n_customers`. `0` when done.
- `progress`: 0–1, `elapsed / (elapsed + eta)`; `1.0` when done.
- `position`: jobs ahead while queued, else `0`.
- `error`: `null`, or a message. After a server restart a job that was running ends with
  `"error": "server restarted"` (queued jobs stay queued).

### `GET /v1/jobs/{id}/result` (409 until done)

```json
{
  "job_id": "20261127-191502-3fa9c1",
  "spec_yaml": "meta:\n  seed: 42\n  ...",
  "summary": {"story": "4/4", "twin": "0/4"},
  "narrative": {"text": "Od 1. března 2026 klesly objednávky studentů ...",
                "source": "ollama gemma4:26b"},
  "verification": [
    {
      "event_id": "E1",
      "claim_cs": "Zdražení o 15 % od března.",
      "kpi": "orders",
      "metric": "purchase_rate",
      "target": "segment=student",
      "start": "2026-03-01",
      "direction": "down",
      "story_size": -15.0,
      "story_unit": "%",
      "expected_size": -12.4,
      "measured": -13.1,
      "measured_unit": "%",
      "ci": [-16.2, -9.8],
      "z": 5.4,
      "p_placebo": 0.0,
      "confirmed": true,
      "status": "confirmed",
      "reason": "",
      "control_mode": "vary",
      "control": "segment ∉ {student}",
      "twin_measured": 0.4,
      "twin_z": 0.3,
      "twin_confirmed": false,
      "sql": "WITH ... SELECT ... AS did_pct",
      "sql_result": {"did_pct": -13.1},
      "sql_matches": true
    }
  ],
  "untested": [{"event_id": "E3", "type": "staff_shortage", "claim_cs": "...",
                "reason": "simulátor tuto událost nepodporuje (...)"}],
  "warnings": ["E2 (objednávky, from 2026-10-20) needs data until 2026-12-14, ..."],
  "rows": {"customers": 20000, "orders": 151234, "order_items": 301822, "...": 0}
}
```

- `status` of a row: `confirmed` | `not_confirmed` | `not_testable` (then `measured`, `ci`,
  `z`, `sql` are `null` and `reason` says why).
- `control_mode`: `vary` (other values of the target's dimension), `rest` (everything outside
  the target), `yoy` (same days 364 days earlier), `none` (plain before/after).
- Units: `%`, `pp` (percentage points), `b.` (rating points), `/den`, `‰/den`; `story_unit`
  can also be `d` (days, a delivery delay the story states).
- `sql` runs on the job's data (`/query` or the `analyst.duckdb` from the ZIP) and gives
  `did_pct` = `measured`.

### `GET /v1/jobs/{id}/tables`

```json
{"tables": [
  {"name": "customers", "rows": 20000,
   "columns": [{"name": "customer_id", "type": "BIGINT"}, {"name": "city", "type": "VARCHAR"}],
   "primary_key": ["customer_id"], "foreign_keys": []},
  {"name": "orders", "rows": 151234, "columns": [...],
   "primary_key": ["order_id"],
   "foreign_keys": [{"column": "customer_id", "references": {"table": "customers", "column": "customer_id"}},
                    {"column": "store_id", "references": {"table": "stores", "column": "store_id"}},
                    {"column": "subscription_id", "references": {"table": "subscriptions", "column": "subscription_id"}}]},
  {"name": "inventory_daily", "...": "...", "primary_key": ["product_id", "date"], "foreign_keys": [...]}
]}
```

`type` is DuckDB's. `primary_key` and `foreign_keys` are the keys the Postgres export
creates (`s2d/sim/pg.py`), the same as `/ddl`; a foreign key is listed only when both tables
exist. Use them for ERD edges instead of guessing from `*_id`.

### `GET /v1/jobs/{id}/ddl` → `text/plain`

The analyst tables as Postgres `CREATE TABLE` statements, with the keys of `/tables`, parents
before children, so the script runs as is in an empty `public` schema (excerpt, every column
is in the real one):

```sql
CREATE TABLE "public"."customers" (
    "customer_id" BIGINT,
    "first_name" TEXT,
    "signup_date" DATE,
    PRIMARY KEY ("customer_id")
);

CREATE TABLE "public"."orders" (
    "order_id" BIGINT,
    "customer_id" BIGINT,
    "order_ts" TIMESTAMP,
    "order_date" DATE,
    "total_czk" DOUBLE PRECISION,
    PRIMARY KEY ("order_id"),
    CONSTRAINT "orders_customer_id_fkey" FOREIGN KEY ("customer_id") REFERENCES "public"."customers" ("customer_id")
);
```

Types: `BIGINT`, `INTEGER`, `DOUBLE PRECISION`, `NUMERIC`, `TEXT`, `DATE`, `TIMESTAMP`,
`BOOLEAN` (DuckDB `DOUBLE` → `DOUBLE PRECISION`, `VARCHAR` → `TEXT`, `DECIMAL(p,s)` →
`NUMERIC(p,s)`, anything else → `TEXT`). The constraint names are the export's
(`<table>_<column>_fkey`).

### `GET /v1/jobs/{id}/tables/{name}?limit=100&offset=0&world=story`

`limit` 1–1000 (default 100), `offset` ≥ 0. `world`: `story` (default) or `twin`, see
`/query`. Rows are arrays in column order; dates are
`"YYYY-MM-DD"`, timestamps ISO 8601, missing values `null`.

```json
{
  "name": "orders", "total": 151234, "limit": 2, "offset": 0,
  "columns": [{"name": "order_id", "type": "BIGINT"}, {"name": "order_date", "type": "DATE"}],
  "rows": [[1, "2025-01-01"], [2, "2025-01-01"]]
}
```

Errors: 404 `"table not found"`, 404 `"data not found"` (no twin files), 422 (limit > 1000,
`world` not `story`/`twin`).

### `POST /v1/jobs/{id}/query`

```json
{"sql": "SELECT city, count(*) AS n FROM customers GROUP BY 1 ORDER BY 2 DESC", "world": "story"}
```

`world`: `story` (default), the data the story happened in, or `twin`, the same company
simulated with the same seed **without** the story (the control the verification compares
with): the same tables and columns, so the same SQL runs on both.

```json
{"columns": [{"name": "city", "type": "VARCHAR"}, {"name": "n", "type": "BIGINT"}],
 "rows": [["Praha", 12000], ["Brno", 8000]],
 "truncated": false, "seconds": 0.01}
```

Sandboxed: DuckDB SQL on a separate `analyst.duckdb` (`analyst_twin.duckdb` for the twin)
holding only the analyst tables (no answer key, no `_truth`), opened read-only with external access off (no `read_parquet`,
`read_csv`, `ATTACH`, `COPY`, no files) and the configuration locked. At most 1000 rows
(`truncated: true` if there were more), 20 s timeout (408). SQL errors are 400.
The twin file is built when the job finishes; for a job finished before the twin was
queryable it is built on the first twin request (that one takes a second longer). 404
`"data not found"` if the job has no twin files.

### `GET /v1/jobs/{id}/download` → `application/zip`

`story2data-<job_id>.zip`, built once and cached:

```
README.md          data dictionary (Czech): every table, column, type, one line each
analyst.duckdb     the analyst tables in DuckDB (the same as /query)
customers.csv      one CSV per table (clean), UTF-8, header row
orders.csv
...
messy/orders.csv   the messy export (only when dirt is not "none")
...
```

### `GET /v1/jobs/{id}/answer-key` (teacher, admin; 403 otherwise)

```json
{
  "job_id": "20261127-191502-3fa9c1",
  "answer_key": [{"event_id": "E1", "type": "price_change", "metric": "purchase_rate",
                  "segment": "segment=student", "start_date": "2026-03-01", "lag_days": 0,
                  "magnitude_pct": -15.0, "direction": "down", "caused_by": null, "simulated": true,
                  "mechanism": "...", "narrative_cs": "Zdražení o 15 % od března."}],
  "decoys": [{"...": "..."}],
  "calibration": [{"event_id": "E1", "metric": "purchase_rate", "kpi": "orders", "story_size": -0.15,
                   "simulated_size": -0.15, "d": 5.1, "target_d": 4.0, "status": "ok", "stated": false, "...": "..."}],
  "verification": ["... the same rows as /result, with sql and sql_result ..."],
  "spec_yaml": "..."
}
```

`answer_key`, `decoys` and `calibration` are the rows of the hidden tables as they are
(`calibration` is `[]` for a story without events).

### `POST /v1/jobs/{id}/detect` → 202

The blind detective: searches the data for events without the answer key (data → story).
Runs in the same queue. No body.

```json
{"job_id": "20261127-191502-3fa9c1", "status": "queued", "position": 0}
```

409 if the job is not done. If a detective run is already queued, running or done, it is
returned as is (no second run).

### `GET /v1/jobs/{id}/detect`

```json
{
  "job_id": "20261127-191502-3fa9c1",
  "status": "done",
  "position": 0,
  "elapsed_s": 21,
  "error": null,
  "events": [{"id": "C3", "metric": "orders", "segment": "segment=student",
              "start_date": "2026-03-02", "end_date": null, "direction": "down",
              "magnitude_pct": -12.8, "lag_days": null, "caused_by": null,
              "kind": "shift", "confidence": 0.9, "evidence": "...",
              "label_cs": "Pokles objednávek studentů",
              "observation_cs": "Od 2026-03-02 objednávky (segment student) klesají o 13 %.",
              "hypothesis_cs": "Studenti po zdražení nakupují méně."}],
  "narrative": {"text": "V březnu 2026 začali ubývat studenti ...", "source": "ollama gemma4:26b"},
  "score": {"precision": 1.0, "recall": 0.75, "f1": 0.86,
            "twin_false_events_per_year": 0.5, "placebo_p": 0.01},
  "matching": {"pairs": [{"found_id": "C3", "event_id": "E2", "score": 0.83, "...": "..."}],
               "missed": [], "false_finds": [], "consequences": [], "background": []},
  "charts": [{"event_id": "C3", "claim_cs": "Studenti po zdražení nakupují méně.", "kpi": "orders",
              "...": "as a verification row of the result"}]
}
```

`status`/`position` as for a job (the detective waits in the same queue and takes about
40 s). `events`, `narrative`, `score` and `charts` are `null` until `done`. `score` and
`matching` are `null` for a student (always). 404 `"detective not run"` before a `POST`.

Each find carries the narrator's words: `label_cs` (a few words), `observation_cs` (what is odd
in the data) and `hypothesis_cs` (what most likely happened, one Czech sentence shaped like a
spec event's `narrative_cs`). They are `""` in results saved before they existed. `charts` is the
verifier's test of each find, in the shape of the result's `verification` rows with
`event_id` = the find's `id` and `claim_cs` = its hypothesis: the story against the twin with
the SQL, so a client can chart a find the prompt never told like a planted event (a find with
no testable KPI is left out; `null` in older results).

## curl

```sh
T=<token>; H="Authorization: Bearer $T"; U=https://hack.dobsinsky.dev
curl -s $U/v1/health
curl -s $U/v1/stats
curl -s -H "$H" -H 'Content-Type: application/json' -X POST $U/v1/jobs \
     -d '{"company":"Pekárna v Brně ...","story":"V dubnu jsme zdražili ...","seed":7}'
curl -s -H "$H" $U/v1/jobs
curl -s -H "$H" "$U/v1/jobs?scope=all"
curl -s -H "$H" $U/v1/jobs/$ID/input
curl -s -H "$H" $U/v1/jobs/$ID
curl -s -H "$H" $U/v1/jobs/$ID/result
curl -s -H "$H" $U/v1/jobs/$ID/tables
curl -s -H "$H" "$U/v1/jobs/$ID/tables/orders?limit=5&offset=0"
curl -s -H "$H" "$U/v1/jobs/$ID/tables/orders?limit=5&world=twin"
curl -s -H "$H" $U/v1/jobs/$ID/ddl
curl -s -H "$H" -H 'Content-Type: application/json' -X POST $U/v1/jobs/$ID/query \
     -d '{"sql":"SELECT count(*) FROM orders"}'
curl -s -H "$H" -H 'Content-Type: application/json' -X POST $U/v1/jobs/$ID/query \
     -d '{"sql":"SELECT count(*) FROM orders","world":"twin"}'
curl -s -H "$H" -o data.zip $U/v1/jobs/$ID/download
curl -s -H "$H" $U/v1/jobs/$ID/answer-key
curl -s -H "$H" -X POST $U/v1/jobs/$ID/detect
curl -s -H "$H" $U/v1/jobs/$ID/detect
```

Tokens (on the server): `uv run python -m s2d.api token <name> <student|teacher|admin>`
prints a new token and stores it in `$DATA_DIR/api/tokens.json`.
