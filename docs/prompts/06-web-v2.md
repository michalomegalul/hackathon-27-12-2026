# Prompts: the site as we want it (`clients/web/` v2)

`04-web.md` built the plain flow (form → progress → verification → data → story page), and it is live at `/web/`.
These prompts turn it into the site we actually want:

1. **Homepage**: the 🌀 spiral logo (animated), live Grafana-style stats of what the pipeline is doing now, in rounded boxes that don't look AI-made.
2. **Prompt Space**: a chat-like window with two ways: text → data (a story becomes a database), and data → story (reverse: the blind detective finds the story in the data).
3. **My DB**: a searchable list of databases; each opens as a DB scheme with arrows from the words of the prompt to the columns they changed. This works for the demo (test) prompt and for any new one.
4. **How it works** (the self-glaze): the whole pipeline with a cool example and our numbers.

Most building blocks exist on `main`: the ERD with word → column arrows (`src/story/`), the uPlot charts, anime.js, the virtualized grid, the API client.
Reuse them; restructure, don't rewrite.

Order: prompt 0 (Michal, API, small) and prompt 1 can run at the same time; then 2, then 3.
Each stops and reports; Michal merges (`main` auto-deploys).

## Prompt 0 (Michal's session): `GET /v1/stats` for the homepage

```text
Story2Data, branch feat/api-stats from main. Read docs/API.md and s2d/api/ (main.py, store.py).
Add GET /v1/stats, no auth (like /v1/health), cheap (read the job files, cache 5 s):
{ "jobs_total", "jobs_done", "jobs_today", "running": {job_id, step, step_index, progress, eta_s} | null,
  "waiting", "median_run_s", "events_confirmed_pct" (story rows confirmed / tested, over done jobs),
  "twin_false_pct", "customers_simulated", "rows_generated",
  "recent": [last 20 finished jobs: {job_id, title, finished, elapsed_s, summary}],
  "timeline": [per hour of the last 24 h: {hour, jobs, median_run_s}] }
No owner names or story texts in it except job titles. Document it in docs/API.md (exact JSON),
test it in tests/test_api.py, DECISIONS entry. uv run pytest -q -m "not integration" green.
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
   (the Czech story sentence, the spec YAML snippet, a table sample, the twin, the z-score row,
   the narrative). Line drawing (svg.createDrawable) connects the steps on scroll (onScroll).
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
- Keep the conversation in sessionStorage so a reload keeps it.
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
   Data (grid + SQL) | Ověření | Detektiv (the reverse result if it was run). Old /jobs/:id/story
   redirects here.
3. Make the arrows draw in one by one with anime.js when the page opens (svg.createDrawable), and
   respect prefers-reduced-motion.
Build + oxlint green. Stop and report with screenshots of the demo database's scheme.
```
