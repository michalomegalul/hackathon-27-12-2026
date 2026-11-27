# Prompts: the web page (`clients/web/`, role C)

Three prompts, one Claude Code session each, in this order.
Each one stops and reports; paste the next one only after the previous is merged.
They need `docs/research/web-stack.md` on `main` (versions, checked snippets, pitfalls).

The page is developed against the **real API** at `https://hack.dobsinsky.dev`, through the Vite dev proxy.
No fake API (MSW) and no Python on the teammates' machines.

## Before the first prompt

Michal makes one token per teammate on the server (the API reloads the token file, no restart):

```bash
ssh <you>@ssh.dobsinsky.dev
cd /opt/app && docker compose exec api python -m s2d.api token <name> student
```

Each teammate, once:

```bash
node -v        # must be >= 22.22 (React Router 8, Vite 8). Arch: sudo pacman -S nodejs-lts-jod npm
git clone git@github.com:michalomegalul/hackathon-27-12-2026.git && cd hackathon-27-12-2026
```

Running it while you work (after prompt 1 created `clients/web/`):

```bash
cd clients/web
echo "VITE_API_TOKEN=<your token>" > .env.local   # git-ignored, never commit it
npm run dev                                       # http://localhost:5173, /v1 proxied to hack.dobsinsky.dev
```

Rules for test jobs (one GPU, one job at a time, a story run takes 1–2 min):
- While building the UI, create jobs with `{"spec_yaml": ...}` (the content of `examples/a.yaml` or `examples/b.yaml`).
  It skips the AI step, so it is fast and barely uses the GPU.
- Send a real story (`company` + `story`) only to test that path, a few times in total.
- Reuse finished jobs: `GET /v1/jobs` lists yours, and a done job's page can be reloaded forever.
- **No test jobs after midnight on Friday**: the queue is for the demo stories then.

## Prompt 1: skeleton + job flow on the real API (Fri 15:00–18:30)

```text
Story2Data hackathon, role C: the web page. Repo: git@github.com:michalomegalul/hackathon-27-12-2026.git,
git pull on main, then create branch feat/c-web. Read docs/research/web-stack.md FIRST and use exactly
its versions and snippets (typechecked against those pins; don't use older APIs from memory: no
react-router-dom, no useReactTable, no applyNodeChanges). We do NOT use MSW: skip every MSW part of
web-stack.md (no msw dependency, no msw() plugin, no virtual:msw / enableMocking in main.tsx).
Read docs/API.md (the contract, every request/response/error) and docs/PLAN.md "Who does what".
Only touch clients/web/. No Co-Authored-By lines, small commits, never merge to main (Michal merges;
main auto-deploys).

The API is live at https://hack.dobsinsky.dev. My token is in clients/web/.env.local as VITE_API_TOKEN
(make sure .env.local is git-ignored; never print or commit the token).

Build clients/web/:
1. Scaffold: npm create vite@9.4.0 clients/web -- --template react-ts --no-interactive, the starter
   package.json pins from web-stack.md minus msw, the Tailwind v4 plugin, and a dev proxy:
   server.proxy { '/v1': { target: process.env.API_URL ?? 'https://hack.dobsinsky.dev',
   changeOrigin: true } } so the code only ever calls relative /v1/... URLs (same as production).
   Check it with: curl the proxied http://localhost:5173/v1/health.
2. src/api.ts: typed client for docs/API.md (Bearer token from VITE_API_TOKEN, ApiError with status
   and detail; 422 detail is a list). Types for job status, result, verification row, tables.
3. Pages (React Router 8 data mode, TanStack Query):
   - "/" form: company + story textareas (Czech placeholders), difficulty, n_customers, dirt, seed;
     buttons "Načíst příklad" (fills examples/stories/brief.yaml company+story) and
     "Rychlý test (bez AI)" (sends {spec_yaml: <examples/a.yaml>}; import the file with Vite's ?raw).
     Use the fast test button for your own testing; real stories only a few times (one GPU, one queue).
   - "/jobs/:id": progress bar with the 5 steps, the running one highlighted, "zbývá ~N s" from eta_s,
     queue position while queued, polling every 2 s that stops on done/error; error message on error.
   - when done (fetch /result only then, it is 409 before): summary "příběh 4/4, dvojče 0/4", the
     verification table (claim_cs, KPI, target, story size vs measured with unit, CI, z, status badge
     confirmed/not_confirmed/not_testable with reason, twin column), each row expandable to its SQL;
     untested events and warnings; the narrative text below.
   - Download button: /download needs the Bearer header, so fetch it as a blob and save it
     (URL.createObjectURL + a temporary <a download>), not a plain <a href>.
   - "/jobs": my jobs (GET /v1/jobs) with status and summary, linking to each job; reuse done jobs
     instead of creating new ones.
4. Dark, clean, Czech UI texts, works on a phone (judges open it on phones).
5. npm run build (tsc -b + vite build) and npx oxlint must pass. clients/web/README.md: how to get a
   token, .env.local, npm run dev, API_URL=http://localhost:8000 npm run dev for a local API.
   Stop and report: what works, screenshots if you can, anything in the API that differs from
   docs/API.md (report it, don't work around it silently).
```

## Prompt 2: data browser + SQL (Fri 19:00–23:00)

```text
Continue on branch feat/c-web (git pull main and rebase first). Read docs/research/web-stack.md again
for TanStack Table 9 + Virtual and the 409/422 pitfalls. Real API only (no MSW); test on done jobs
from GET /v1/jobs or on fast {spec_yaml} jobs, not on new real stories.
1. "/jobs/:id/data": table list from /tables (name, rows, columns), and a virtualized sortable grid
   (TanStack Table 9 + Virtual, snippet in web-stack.md) for /tables/:name, loading more with
   offset paging as you scroll (limit 1000, total from the response). Dates as dates, nulls greyed.
2. SQL box: textarea + run -> POST /query, results in the same grid, "truncated" notice,
   400 (SQL error) and 408 (timeout) shown inline. Pre-fill it from a verification row
   ("Spustit SQL" button on each row of the result table), so a judge can check a number live.
3. Error handling everywhere: 401 -> "neplatný token", 404 -> "úloha nenalezena", network down ->
   retry banner.
4. Build + oxlint green, then stop and report.
```

## Prompt 3: deploy + the wow page (Fri 23:00–01:00, only if 1 and 2 are merged)

```text
Continue on feat/c-web (git pull main, rebase). Two parts; ask Michal before touching anything
outside clients/web/. Don't create new jobs after midnight; use existing done jobs.
A. Deploy: nginx serves / to Streamlit today. Propose (don't merge) serving the built site at
   /web/: Vite base '/web/', React Router basename '/web', a node:22 build stage producing
   clients/web/dist, nginx `location /web/ { try_files $uri /web/index.html; }`. Write the exact
   compose.yaml + nginx.conf diff in the report for Michal to apply. Production shares the origin
   with /v1, so relative /v1 URLs keep working; the token comes from a small login field (stored in
   localStorage), not from the build (VITE_API_TOKEN stays dev-only).
B. "/jobs/:id/story" demo page for the pitch (web-stack.md snippets):
   - ERD of the generated tables from /tables (React Flow 13 table nodes, one handle per column,
     FK edges by *_id column names), the narrative in a side panel with each event's claim as a
     span and an SVG arrow from the span to the KPI column it moved (overlay recipe in web-stack.md).
   - uPlot dark time series per confirmed event: daily KPI for the target vs the control, a
     vertical marker at `start` (data via POST /query with a daily GROUP BY written from the row).
   - anime.js: steps reveal, arrow draws in, respect prefers-reduced-motion.
   Lazy-load this route so the main page stays small. Build + oxlint green, stop and report.
```
