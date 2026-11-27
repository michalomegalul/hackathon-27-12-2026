# Prompts: the site redesign (`clients/web/` v2)

`04-web.md` built the plain flow, live at `/web/`.
This is the complete redesign the team agreed on. It replaces the earlier v2 draft of this file.

## The design

**Header:** `🌀 Story2Data` | **Story** | **Rev story** | **History** | **About**
- **Story** (`/`): a chat. One input, one send. Sending runs **everything automatically**:
  prompt → spec (AI) → simulation and twin → verification → detective → score → summary.
  No buttons in between, no forms with fields.
- **Rev story** (`/rev`): the reverse, data → story. Pick a database (or upload a YAML spec),
  the detective finds the story without seeing it, and the summary compares it with the original.
- **History** (`/history`): every earlier run; opening one shows it in the same view as Story.
- **About** (`/about`): the technical part: pipeline, model, statistics, tests, numbers, API.

**Left sidebar, only in Story, Rev story and History** (a drawer on the phone): the whole process as a vertical list:
**Prompt → Spec → Data → Detektiv → Skóre → Shrnutí**.
- Parts not reached yet are **grey**; the running one pulses; finished ones get a ✓ and become clickable (scroll to that section).
- **Status at the top of the sidebar, sticky** (it goes with you when you scroll): current step, progress bar, time left, queue position.
- In the chat the result sections stay grey placeholders until their step finishes, then fill in.

**Main column, top to bottom as the run progresses:**
1. **Prompt**: the user's message.
2. **Spec**: what the AI understood, as readable Czech parameters (company, segments, cities, channels, and the events as a table: what, from when, who, how much, lag). Never YAML on screen (only behind "pro vývojáře").
3. **Data**: the generated database as **Postgres tables**: `CREATE TABLE` with types, primary and foreign keys, and the first rows like `psql`; the ERD of the tables; a searchable grid and SQL box.
4. **Detektiv**: what the blind detective found without the story, and its Czech narrative.
5. **Skóre**: story x/y confirmed, twin 0/y false alarms, the detective's precision/recall/F1.
6. **Shrnutí** (the end, the money shot): the **original prompt** with the important words and phrases highlighted, and **arrows** from each one to
   (a) **the chart where it changed**: the KPI with the story against the twin without it, two lines together and then splitting at the event, and
   (b) **the Postgres table and column where it applied**, with the before/after numbers and the SQL that proves it.

Most building blocks already exist on `main`: the ERD and the word → column arrows (`src/story/`), `KpiChart` (uPlot), anime.js, the virtualized grid and SQL box, the API client.
Reuse them; restructure, don't rewrite from scratch.

**API needed** (Prompt 0 of the earlier draft, done on branch `feat/api-stats`, commit `fe0fc49`; merge it first):
`"world": "twin"` on `/query` and `/tables/{name}`, keys in `/tables`, `GET /ddl`, `GET /v1/jobs?scope=all`, `GET /v1/jobs/{id}/input`, `GET /v1/stats`.
Check `docs/API.md` on `main` for the exact shapes.

Order: prompt 1, then 2, then 3, one Claude Code session each, on one branch `feat/c-web-v2`.
Each stops and reports; Michal merges (`main` auto-deploys).

## Prompt 1: the new shell, the sidebar process, Story runs everything automatically

```text
Story2Data hackathon, web site redesign. Repo git@github.com:michalomegalul/hackathon-27-12-2026.git,
git pull main, branch feat/c-web-v2. Read docs/prompts/06-web-v2.md "The design" (follow it exactly),
docs/research/web-stack.md (versions, snippets, pitfalls), docs/API.md (on main, incl. world=twin,
/ddl, scope=all, /input, /stats), and ALL of clients/web/src first: reuse api.ts, components,
story/ (Erd, SpanArrow, KpiChart), DataGrid; restructure, don't rewrite. Only touch clients/web/.
No Co-Authored-By, small commits, never merge to main.

1. Header: 🌀 (spiral emoji, slow anime.js rotation, prefers-reduced-motion) Story2Data | Story |
   Rev story | History | About. Dark, rounded panels, thin borders, NOT AI-looking (no gradients,
   glow, emoji spam). Old links (/jobs/:id, /jobs/:id/data, /jobs/:id/story) redirect to the new
   views.
2. The run view (used by Story, Rev story and History): left sidebar with the process
   Prompt → Spec → Data → Detektiv → Skóre → Shrnutí, grey until reached, running one pulsing,
   finished ones ✓ and clickable (scroll to the section). Sticky status block at the top of the
   sidebar (step name, progress, "zbývá ~N s", queue position) that stays visible while scrolling.
   Main column = the sections in that order, each a grey placeholder until its step is done.
   Phone: the sidebar becomes a top drawer with the status always visible.
3. Story "/": a chat input at the bottom (one textarea, Enter sends, Shift+Enter new line).
   The API wants company and story separately: the first paragraph is the company, the rest the
   story (say so in the placeholder: "První odstavec: firma. Pak příběh."); with only one
   paragraph send it as both. Chips above the input: "Ukázka" (fills examples/stories/brief.yaml)
   and "Rychlý test bez AI" (sends examples/a.yaml as spec_yaml); a paperclip attaches a .yaml
   file as spec_yaml. URL becomes /run/:id so a reload or a shared link reopens it.
4. Automatic pipeline: POST /v1/jobs → poll GET /v1/jobs/{id} every 2 s (map the 5 API steps onto
   Spec and Data in the sidebar) → when done, fetch /result and POST /detect AUTOMATICALLY →
   poll GET /detect → Detektiv and Skóre fill in → Shrnutí. Never ask the user to click
   "next". Errors show in the section where they happened, with "Zkusit znovu".
5. Section content in this prompt (Prompt 2 makes them rich): Spec = the events table from the
   result's verification rows (claim_cs, KPI, target, start, stated size); Data = table list with
   row counts; Detektiv = found events + narrative; Skóre = story x/y, twin 0/y, P/R/F1;
   Shrnutí = placeholder.
Build + oxlint green. Stop and report with screenshots (desktop + phone) of a run in progress and
a finished run.
```

## Prompt 2: Spec, Postgres data and the Shrnutí with arrows

```text
Continue on feat/c-web-v2 (git pull main, rebase). Read docs/prompts/06-web-v2.md "The design" again.
1. Spec: readable Czech parameters from the spec (company, segments with shares, cities,
   channels) and the events table (what, from-to, who, stated size, lag). The YAML only behind a
   small "pro vývojáře" toggle. Nowhere else.
2. Data as Postgres: GET /ddl as highlighted SQL with a copy button; each table a psql-style card
   (columns, types, PK/FK badges, first 5 rows from /tables/{name}); the ERD (React Flow 13) with
   edges from primary_key/foreign_keys (not *_id guessing); a searchable grid + SQL box (reuse
   DataGrid / DataPage).
3. Shrnutí (the end of the page and the demo's money shot):
   - the original prompt (GET /v1/jobs/{id}/input) with the important words highlighted: each
     story event's phrase (match claim_cs / the event's words to the prompt text; if no match,
     put the event as a chip under the prompt);
   - for each highlight, an arrow (the SpanArrow overlay recipe from web-stack.md) to
     (a) its chart: KpiChart with the story line AND the twin line (the row's daily SQL with
     "world": "twin") and the control, together before the event and splitting after it, the gap
     shaded; and (b) its Postgres card: the table and column it changed, with before/after numbers
     for story vs twin and the SQL that proves it (copy button);
   - hovering a highlight lights its arrows, chart and column; arrows draw in one by one with
     anime.js svg.createDrawable when Shrnutí scrolls into view (onScroll); reduced motion = no
     animation;
   - a one-line verdict on top: "Příběh 4/4 potvrzeno, dvojče 0/4 falešných poplachů,
     detektiv našel 3/4".
Build + oxlint green. Stop and report with a screenshot of Shrnutí for the demo story.
```

## Prompt 3: Rev story, History, About

```text
Continue on feat/c-web-v2 (git pull main, rebase).
1. Rev story "/rev": same run view. Instead of a prompt the user picks a finished database (search
   by title/company from GET /v1/jobs?scope=all, demo ones pinned) or attaches a .yaml spec (runs
   the job first, automatically). Then POST /detect runs automatically; Detektiv fills in; Shrnutí
   shows the detective's narrative next to the original prompt, matched events linked by arrows
   (found ↔ planted), misses and false finds marked.
2. History "/history": all runs (GET /v1/jobs?scope=all: title, story_preview, date, status,
   summary), newest first, search + filter (moje / všechny / ukázky). Opening one = the run view
   rebuilt from /input, /result and /detect. "Znovu" sends the same prompt again (new seed),
   "Upravit" puts it into the Story input.
3. About "/about": the technical part. The pipeline as 6 steps with one sentence and a tiny real
   example each (lines drawn between them on scroll); the stack (Gemma 4 26b on the homelab GPU only
   for spec and narrative, numpy simulation, DuckDB, FastAPI, React); why the statistics are
   deterministic; the twin and calibration; tests (number of pytest tests and what they cover);
   the detection curves from docs/detection_curve_a.png and docs/verify_curve_a.png (copy into
   public/); our measured numbers with their source (DECISIONS.md / PLAN.md, e.g. 87 % of story
   events confirmed on 11 stories, 3 % false alarms on the twin; no invented numbers); live stats
   from GET /v1/stats as small Grafana-style panels; links to /docs (API) and the repo.
Build + oxlint green. Stop and report with screenshots.
```
