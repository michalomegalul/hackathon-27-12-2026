# Prompt: what is left (Fri 27. 11. evening)

Paste the block below into a new Claude Code session on the notebook. It replaces
`02-api.md` (priority 1 below is the same API).

```text
Story2Data, hackathon (4FIS, code freeze Sat 08:00, submission Sat 12:00). Repo:
git@github.com:michalomegalul/hackathon-27-12-2026.git, branch main (git pull first; it has
the full sim, verifier, stated sizes and the year-over-year control). Read docs/PLAN.md,
README.md and DECISIONS.md 87-93 before anything else. Don't change s2d/sim/engine.py,
s2d/verify.py, s2d/calibrate.py, s2d/detective/scan.py without asking me. Each priority on its
own branch, small commits, no Co-Authored-By lines, decisions into DECISIONS.md (continue the
numbering), `uv run pytest -q -m "not integration"` green before asking me to merge. Never merge
to main yourself: main auto-deploys to hack.dobsinsky.dev every 30 s. Stop and report after each
priority.

PRIORITY 1 (branch feat/api, until ~19:00): the HTTP API from docs/PLAN.md.
1a. First commit docs/API.md: the exact JSON of every request and response, including errors.
    Teammates build a web page and a Discord bot against it today.
1b. s2d/api/ with FastAPI + uvicorn (fastapi==0.165.0, uvicorn==0.54.0):
  - POST /v1/jobs {company, story, difficulty?, seed?, n_customers?, dirt?} or {spec_yaml, ...}
    -> 202 {job_id, status, position}. spec_yaml skips the LLM.
  - GET /v1/jobs (own; admin all). GET /v1/jobs/{id} -> status, step, step_index, steps_total,
    progress, elapsed_s, eta_s, steps [{name, done, s, note} | {name, done:false, eta_s}], error.
    Steps: "specifikace (AI)", "kalibrace a simulace", "dvojče bez příběhu", "ověření",
    "český příběh (AI)". ETA = median of earlier runs per step ($DATA_DIR/api/timings.json),
    sim steps scaled by n_customers, priors when there is no history.
  - GET /v1/jobs/{id}/result -> spec_yaml, verification rows (event, KPI, target, story size,
    measured, CI, z, confirmed, control mode, twin z, twin confirmed, sql, sql_result),
    narrative, summary {story:"4/4", twin:"0/4"}, warnings, rows per table.
  - GET /v1/jobs/{id}/tables and /tables/{name}?limit&offset (limit <= 1000).
  - POST /v1/jobs/{id}/query {sql}: SANDBOXED on a separate analyst.duckdb holding only the main
    schema, read_only, enable_external_access=false, lock_configuration=true, max 1000 rows, 20 s
    timeout (con.interrupt). A test proves _truth, read_parquet and files are unreachable.
  - GET /v1/jobs/{id}/download -> ZIP: CSV per table + messy/ CSVs if the dirty export exists +
    analyst.duckdb + README.md data dictionary (table, column, type, one Czech line). Cached.
  - GET /v1/jobs/{id}/answer-key: teacher/admin only (403 otherwise).
  - POST/GET /v1/jobs/{id}/detect: the blind detective on that job's data (reverse search, data ->
    story) as its own queued job; events + Czech narrative; score vs the answer key only for
    teacher/admin.
  - GET /v1/health (no auth): llm backend/model/reachable, queue running/waiting. /docs stays on.
  - One worker thread, FIFO (one GPU). Jobs are files under $DATA_DIR/api/jobs/<id>/ and survive a
    restart (running at startup -> error "server restarted"). Pipeline = app/main.py run_sim:
    compile -> calibrate -> simulate -> fill_reviews if a pool exists -> write_world -> twin ->
    verify -> narrate (template fallback). n_customers cap 100000.
  - Tokens in $DATA_DIR/api/tokens.json {token: {name, role}}, roles student|teacher|admin,
    CLI `uv run python -m s2d.api token <name> <role>`. 401/403. CORS on.
1c. Deploy: compose service `api` (same image, `uvicorn s2d.api.main:app --host 0.0.0.0
    --port 8000`, same env + ./data volume); nginx routes /v1/, /docs, /openapi.json to api:8000
    (proxy_read_timeout 120s); the rest stays Streamlit.
1d. Tests with TestClient, no LLM (spec_yaml, small n_customers, LLM_BACKEND=replay): lifecycle,
    status/eta, result, tables, sandboxed query, 401/403, answer-key roles, ZIP contents.
    Report curl examples for every endpoint.

PRIORITY 2 (branch feat/brief): the official brief.
- Write the brief's company + story as examples/stories/brief.yaml and run it end to end (compile
  with the real Gemma -> sim -> twin -> verify). A small stated drop (like "-5 % sales") needs
  ~80k customers to confirm reliably (DECISIONS 92): if the brief's numbers are that small, raise
  the spec's n_customers limit (spec.py, max 100_000) to 200_000 only if sim time at 160k stays
  under 30 s, and report the time.
- Close the open item from DECISIONS 93: fit_windows should extend the data a year back when an
  event for everyone starts less than a year into the data, so the year-over-year control applies.

PRIORITY 3 (branch feat/demo): demo readiness.
- Pre-generate the 3-5 demo stories (B picks them) at their final settings, save the runs and the
  LLM cache under data/, so LLM_BACKEND=replay reproduces them with no network.
- Generate Czech text pools for those companies (uv run python -m s2d.texts generate <story>) so
  reviews.text is filled; report how long one pool takes on the homelab GPU.
- A checklist script scripts/demo_check.sh: health, one replay job through the API end to end,
  the app loads, Postgres export works if S2D_TEST_PG is set. Report what fails.

Final report per priority: what works, test count, what is not done, timings.
```
