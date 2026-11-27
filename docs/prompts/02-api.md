# Prompt: the HTTP API (on its own)

Superseded by `03-next-steps.md`, whose priority 1 is this same API. Kept for a session that
should build only the API.

```text
Story2Data: build the HTTP API. Repo: git@github.com:michalomegalul/hackathon-27-12-2026.git,
branch main (git pull first). Create branch feat/api. Read docs/PLAN.md (section "What we build at
the event: the API" is the contract), README.md, app/main.py (run_sim / run_compile: the pipeline
the API must run), app/jobs.py, s2d/compiler.py (compile_story), s2d/verify.py (verify, narrate,
summary_line), s2d/sim/output.py (write_world), s2d/texts.py (fill_reviews, find_pool),
s2d/detective (run, save). Don't change s2d/sim/engine.py, verify.py, calibrate.py, detective/scan.py.

Step 0, before any code (teammates build the web page and a bot against this today): write
docs/API.md with the exact JSON of every request and response below, including errors, and commit
it first.

Build s2d/api/ with FastAPI + uvicorn (add fastapi==0.165.0, uvicorn==0.54.0 to pyproject, uv lock):

Endpoints (all under /v1, Authorization: Bearer <token> except health and docs):
- POST /v1/jobs {company, story, difficulty?, seed?, n_customers?, dirt?} OR {spec_yaml, ...}
  -> 202 {job_id, status:"queued", position}. spec_yaml skips the LLM (for tests and replays).
- GET /v1/jobs -> the caller's jobs (admin: all).
- GET /v1/jobs/{id} -> {status: queued|running|done|error, step, step_index, steps_total, progress
  0-1, elapsed_s, eta_s, steps:[{name, done, s, note} | {name, done:false, eta_s}], error?}
  Steps: "specifikace (AI)", "kalibrace a simulace", "dvojče bez příběhu", "ověření",
  "český příběh (AI)". ETA = median of earlier runs of each step (data/api/timings.json),
  sim-type steps scaled by n_customers; sensible priors when there is no history.
- GET /v1/jobs/{id}/result -> spec_yaml, verification rows (event, KPI, target, story size,
  measured, CI, z, confirmed, twin z, twin confirmed, sql, sql_result), narrative,
  summary {story:"4/4", twin:"0/4"}, warnings, rows per table.
- GET /v1/jobs/{id}/tables -> [{name, rows, columns:[{name,type}]}]
- GET /v1/jobs/{id}/tables/{name}?limit=100&offset=0 -> rows as JSON (limit <= 1000)
- POST /v1/jobs/{id}/query {sql} -> {columns, rows, truncated}. Read-only and SANDBOXED: run it
  on a separate analyst.duckdb that holds ONLY the main schema (copy it when the job finishes),
  opened read_only with enable_external_access=false and lock_configuration=true, max 1000 rows,
  20 s timeout (con.interrupt from a timer). A test must prove _truth, read_parquet and file
  access are unreachable.
- GET /v1/jobs/{id}/download -> ZIP: CSV per table (clean) + messy/ CSVs if the dirty export
  exists + analyst.duckdb + README.md data dictionary (table, column, type, one Czech line each).
  Built once, cached.
- GET /v1/jobs/{id}/answer-key -> answer key + verify rows with SQL; role teacher or admin only (403).
- POST /v1/jobs/{id}/detect -> starts the blind detective on that job's data (reverse search:
  data -> story), its own job; GET /v1/jobs/{id}/detect -> events + Czech narrative + score vs
  the answer key (score only for teacher/admin).
- GET /v1/health -> {ok, llm:{backend, model, reachable}, queue:{running, waiting}} (no auth).
- /docs (Swagger) stays on.

Behaviour:
- One worker thread, FIFO queue: only one job runs at a time (one GPU). Jobs survive a restart as
  files under $DATA_DIR/api/jobs/<id>/ (job.json + the run dir); running jobs at startup -> error
  "server restarted".
- Pipeline = what app/main.py run_sim does: compile (if no spec_yaml) -> calibrate -> simulate
  -> fill_reviews if a text pool exists -> write_world (dirt from spec unless given) -> twin
  (same seed, without_story) -> verify -> narrate (LLM, template fallback). Cap n_customers at
  100000. Log every step's duration into timings.json.
- Tokens: $DATA_DIR/api/tokens.json {token: {name, role}}; roles student | teacher | admin.
  CLI: uv run python -m s2d.api token <name> <role> prints a new random token.
  401 without/unknown token, 403 for the wrong role.
- CORS on (the web page runs on another origin).

Deploy: add service `api` to compose.yaml (same image as app, command
"uvicorn s2d.api.main:app --host 0.0.0.0 --port 8000", same env and ./data volume); in
nginx.conf route /v1/, /docs and /openapi.json to api:8000 (proxy_read_timeout 120s), everything
else stays on Streamlit. The server auto-deploys main every 30 s, so only merge when tests pass.

Tests (tests/test_api.py, FastAPI TestClient, no LLM: spec_yaml input, small n_customers,
LLM_BACKEND=replay so narrate falls back to the template): job lifecycle queued -> done; status
fields and eta present; result has verification rows; tables and a page of rows; query works
and cannot reach _truth / files; answer-key 403 for student, 200 for teacher; 401 without token;
download ZIP contains the CSVs and README. uv run pytest -q -m "not integration" must pass.

Small commits, no Co-Authored-By lines, record decisions in DECISIONS.md (continue the numbering),
don't merge to main. When done: curl examples for every endpoint, the test count, and what is
not done.
```
