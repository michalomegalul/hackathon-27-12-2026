# Prompts: the site as we want it (`clients/web/` v2)

`04-web.md` built the plain flow (form → progress → verification → data → story page), and it is live at `/web/`.
These prompts turn it into the site we actually want:

1. **Homepage**: the 🌀 spiral logo (animated), live Grafana-style stats of what the pipeline is doing now, in rounded boxes that don't look AI-made.
2. **Prompt Space**: a chat-like window with two ways: text → data (a story becomes a database), and data → story (reverse: the blind detective finds the story in the data).
3. **My DB**: a searchable list of databases; each opens as a DB scheme with arrows from the words of the prompt to the columns they changed. This works for the demo (test) prompt and for any new one.
4. **How it works** (the self-glaze): the whole pipeline with a cool example and our numbers.
5. **What changed**: the same database with the story and without it (the twin), side by side:
   what the story said, how it should look, what was measured, and what the twin shows (nothing).
6. **Postgres tables, not YAML**: everywhere a visitor sees "the data", show Postgres tables
   (`CREATE TABLE` with types, primary and foreign keys, sample rows like `psql`), never the spec YAML.
   The YAML stays only behind a small "pro vývojáře" toggle.

Most building blocks exist on `main`: the ERD with word → column arrows (`src/story/`), the uPlot charts, anime.js, the virtualized grid, the API client.
Reuse them; restructure, don't rewrite.

Order: prompt 0 (Michal, API, small) and prompt 1 can run at the same time; then 2, then 3, then 4.
Each stops and reports; Michal merges (`main` auto-deploys).

## Prompt 0 (Michal's session): API for the homepage, the twin and the Postgres view

```text
Story2Data, branch feat/api-stats from main. Read docs/API.md, s2d/api/ (main.py, store.py,
pipeline.py, sandbox.py) and s2d/sim/pg.py (PRIMARY_KEYS, FOREIGN_KEYS). Four additions:
A. The twin is queryable: when a job finishes, build analyst_twin.duckdb from run/twin/story.duckdb
   the same way as analyst.duckdb (sandbox.build_analyst, main schema only). POST /v1/jobs/{id}/query
   and GET /v1/jobs/{id}/tables/{name} take "world": "story" | "twin" (default story; body field
   for /query, query parameter for the table). Same sandbox, same limits. Jobs finished before this
   change: build it lazily on the first twin request.
B. Keys and Postgres DDL: GET /v1/jobs/{id}/tables adds per table "primary_key": [cols] and
   "foreign_keys": [{column, references: {table, column}}] from s2d/sim/pg.py (one source of truth).
   New GET /v1/jobs/{id}/ddl -> text/plain: the Postgres CREATE TABLE statements of the analyst
   tables with Postgres types (BIGINT, INTEGER, DOUBLE PRECISION, NUMERIC, TEXT, DATE, TIMESTAMP,
   BOOLEAN), PRIMARY KEY and REFERENCES, the same keys the Postgres export creates.
D. History: GET /v1/jobs?scope=all lists every job for teacher and admin (scope=mine, the default,
   keeps today's behaviour), so the public site (public mode = teacher) shows the whole history,
   including the demo jobs made with team tokens. New GET /v1/jobs/{id}/input -> the prompt as sent:
   {company, story, difficulty, seed, n_customers, dirt, spec_given: bool} (spec_yaml itself not
   repeated), same visibility as the job. Also add "story_preview" (first 120 chars of the story,
   null for spec jobs) to each item of GET /v1/jobs.
C. GET /v1/stats, no auth (like /v1/health), cheap (read the job files, cache 5 s):
{ "jobs_total", "jobs_done", "jobs_today", "running": {job_id, step, step_index, progress, eta_s} | null,
  "waiting", "median_run_s", "events_confirmed_pct" (story rows confirmed / tested, over done jobs),
  "twin_false_pct", "customers_simulated", "rows_generated",
  "recent": [last 20 finished jobs: {job_id, title, finished, elapsed_s, summary}],
  "timeline": [per hour of the last 24 h: {hour, jobs, median_run_s}] }
No owner names or story texts in it except job titles.
Document A, B, C and D in docs/API.md (exact JSON), test them in tests/test_api.py (the twin query
must not see _truth either), DECISIONS entry. uv run pytest -q -m "not integration" green.
No Co-Authored-By. Don't merge; stop and report.
```

## Prompt 1: new structure, the spiral homepage, How it works

```text
Story2Data hackathon, web site v2. Repo git@github.com:michalomegalul/hackathon-27-12-2026.git, git pull
main, branch feat/c-web-v2. Read docs/prompts/06-web-v2.md (the vision at the top), docs/research/web-stack.md
(versions, snippets, pitfalls: React Router 8, TanStack 9, React Flow 13, anime.js 4, uPlot), docs/API.md,
and ALL of clients/web/src first: reuse the existing api.ts, components, story/ (Erd, SpanArrow,
KpiChart), DataGrid; restructure, don't rewrite. Only touch clients/web/. No Co-Authored-By,
small commits, never merge to main.

1. Layout and nav: logo 🌀 (spiral emoji, slow rotation with anime.js, respects prefers-reduced-motion)
   + "Story2Data", nav: "Prompt Space" | "Moje DB" | "Jak to funguje". Keep all existing routes
   working (old links /jobs/:id, /jobs/:id/data, /jobs/:id/story must still open).
2. Homepage "/": a big animated 🌀 hero with one sentence ("Napiš příběh firmy, dostaneš databázi,
   ve které se opravdu stal, a důkaz.") and two buttons (Prompt Space, ukázka). Under it a
   Grafana-style dashboard: dark panels with rounded corners, thin borders, small caps titles,
   no gradients/glow/emoji spam (it must NOT look AI-generated):
   - live status tiles: pipeline now (running step with progress, queue length, ETA),
     jobs today, median run time, % events confirmed, % twin false alarms, rows generated;
   - uPlot panels: jobs per hour (24 h), run time per job; the running job's steps as a live bar.
   Data: GET /v1/stats (Michal adds it; if it 404s, fall back to /v1/health + /v1/jobs and hide the
   tiles you can't fill), refetch every 5 s. Numbers count up with anime.js on first load.
3. "Jak to funguje" "/how": the pipeline as 6 steps (příběh → spec → simulace → dvojče → ověření →
   vyprávění), each a panel with one sentence and a tiny real example from the demo story
   (the Czech story sentence, the events it found as plain Czech chips, a Postgres table as
   `CREATE TABLE` + 5 sample rows, the twin next to it, the z-score row, the narrative). No YAML. Line drawing (svg.createDrawable) connects the steps on scroll (onScroll).
   Then "Proč tomu věřit" with our measured numbers, each with its source (DECISIONS.md / PLAN.md:
   e.g. 87 % of story events confirmed on 11 stories, 3 % false alarms on the twin); no invented
   numbers.
4. Mobile first (judges use phones), Czech texts, npm run build + npx oxlint green.
Stop and report with screenshots of /, /how on desktop and phone width.
```

## Prompt 2: Prompt Space (text → data and data → story)

```text
Continue on feat/c-web-v2 (git pull main, rebase). Read docs/API.md (POST /v1/jobs, GET /v1/jobs/{id},
/result, POST+GET /v1/jobs/{id}/detect) and the existing Home.tsx/JobPage.tsx/Result.tsx.
"/prompt" Prompt Space, a chat-like window (messages top to bottom, input at the bottom):
- Mode switch at the input: "Text → data" | "Data → příběh".
- Text → data: the user writes the company + story (or picks "Ukázkový prompt" = the demo story,
  or "Rychlý test bez AI" = examples/a.yaml spec). Sending creates the job; the reply bubble shows
  the 5 steps live (reuse the progress component), then a result card: "příběh 4/4, dvojče 0/4",
  the confirmed events as chips, and buttons "Otevřít DB schéma" (→ the scheme with arrows),
  "Data" (→ grid/SQL), "Stáhnout ZIP".
- Data → příběh (the reverse): pick one of the done databases (searchable list), send; POST
  /detect, the bubble shows "detektiv hledá…" with status, then the events the detective found
  WITHOUT the story (metric, segment, start, magnitude, confidence) and its Czech narrative.
  If the score is there (teacher role / public mode), show precision/recall/F1 and a side-by-side
  "příběh říkal ↔ detektiv našel" table, matched rows highlighted. This is the proof the story
  can be found back in the data; make it look like it.
- History sidebar (left on desktop, a drawer on the phone), like a chat app: every earlier prompt
  from GET /v1/jobs?scope=all (title, story_preview, date, status, summary "4/4"), newest first,
  with a search box and a filter (moje / všechny / ukázky). Clicking one reopens it as a
  conversation: the user bubble rebuilt from GET /v1/jobs/{id}/input, then the result card and,
  if the detective ran, its reply. A "Znovu" button sends the same prompt again (new seed), and
  "Upravit" puts it into the input. The current conversation also stays in sessionStorage.
Build + oxlint green, stop and report with screenshots.
```

## Prompt 3: Moje DB and the scheme with arrows

```text
Continue on feat/c-web-v2 (git pull main, rebase). Reuse src/story/ (Erd, SpanArrow, KpiChart) and
the DataPage grid.
1. "/db" Moje DB: a searchable list (by title, company name, table or column name) of all databases
   (GET /v1/jobs), status + summary + date; pinned at the top: the demo databases (job ids from
   docs/demo-stories.md if it exists, else a hardcoded list in src/demo.ts that Michal fills in).
2. "/db/:id": the DB scheme as the main view: the prompt text on the left with every word or phrase
   that became an event highlighted, and arrows from each highlight to the table column it changed
   (the existing SpanArrow overlay); hovering a highlight lights its arrow, the column and the
   verification row (size, z, ✅); clicking it shows the daily KPI chart (KpiChart) and the SQL.
   Tables as modern ERD cards (React Flow 13), FK edges, the KPI columns marked. Tabs: Schéma |
   Data (grid + SQL) | Postgres (GET /ddl as highlighted SQL with a copy button, and each table as a
   psql-style card: columns, types, PK/FK, first rows) | Ověření | Co se změnilo | Detektiv (the
   reverse result if it was run). Use primary_key/foreign_keys from /tables for the ERD edges,
   not *_id guessing. The spec YAML only behind a "pro vývojáře" toggle. Old /jobs/:id/story
   redirects here.
3. Make the arrows draw in one by one with anime.js when the page opens (svg.createDrawable), and
   respect prefers-reduced-motion.
Build + oxlint green. Stop and report with screenshots of the demo database's scheme.
```

## Prompt 4: What changed (story vs twin, how it should look)

```text
Continue on feat/c-web-v2 (git pull main, rebase; needs prompt 0 merged: "world": "twin"). Read
docs/API.md (verification rows: story_size, expected_size, measured, ci, twin_measured, twin_z,
control_mode, control, sql) and src/story/KpiChart.tsx + model.ts (dailySql).
Tab "Co se změnilo" on /db/:id, and a short version in the Prompt Space result card:
1. One card per event, four numbers side by side with one Czech line each:
   "Příběh říká" (story_size + unit) | "Mělo by být" (expected_size, what the calibrated simulation
   aims for) | "Naměřeno" (measured with the CI as a range bar) | "Bez příběhu" (twin_measured,
   should be ~0). A small horizontal chart with the four on one axis, zero marked, and a verdict
   badge (✅ potvrzeno / ❌ / nelze ověřit + reason). The twin value close to zero is the point:
   say it ("ve světě bez příběhu se nic nestalo").
2. Under it the daily KPI chart with THREE lines: target with the story, the same target in the
   twin (run the row's daily SQL with "world": "twin"), and the control; the event start marked,
   the gap between story and twin shaded after it. Reuse KpiChart, add the twin series.
3. A "Před / po" mini table per event: the KPI before vs after the start, story vs twin, as the SQL
   computes it (show that SQL with a copy button: a judge can run it in the Data tab).
4. Summary bar at the top: "Příběh 4/4 potvrzeno, dvojče 0/4 falešných poplachů".
Build + oxlint green, stop and report with a screenshot of the demo database's "Co se změnilo".
```
