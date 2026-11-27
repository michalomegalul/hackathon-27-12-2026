# Story2Data web (`clients/web/`)

The web page for the Story2Data API (`docs/API.md`). Story is a chat: one message runs the whole pipeline (spec, data, detective, score) by itself, shown as a process in a sidebar. Design: `docs/prompts/06-web-v2.md`.
It is built with Vite 8, React 19, React Router 8 (data mode), TanStack Query 5 and Tailwind v4, with the pins from `docs/research/web-stack.md`.
It uses no MSW.

**Live:** https://hack.dobsinsky.dev/ (old `/web/...` links redirect there). `clients/web/Dockerfile` builds it into the `web` nginx image (see `nginx.conf`, `compose.yaml`) on every auto-deploy of main.

**Token.** The site is public, so no token is built in. The page asks for one and keeps it in the browser's localStorage (**Odhlásit** forgets it).
A link `https://hack.dobsinsky.dev/#token=<token>` logs in directly, e.g. as a QR code for judges.
The part after `#` is not sent to the server, and the page removes it from the address bar.

## Setup

Node **≥ 22.22** is required (Vite 8 and React Router 8 do not run on Node 18).

1. **Get a token.** Ask Michal, or on the server run:
   ```sh
   uv run python -m s2d.api token <name> student
   ```
2. **For `npm run dev` only, put it in `clients/web/.env.local`.** The file is git-ignored by `*.local`, and `.dockerignore` keeps it out of images. Never commit it.
   A production build never includes it.
   Use the exact name `.env.local`, not `.env.local.txt`.
   ```sh
   VITE_API_TOKEN=<token>
   ```
3. Install and run:
   ```sh
   cd clients/web
   npm ci
   npm run dev            # http://localhost:5173/, /v1 is proxied to https://hack.dobsinsky.dev
   ```

The code only ever calls relative `/v1/...` URLs.
In dev, Vite's `server.proxy` forwards them.
In production, nginx serves the site and the API on one origin.

**Local API:** start `uv run uvicorn s2d.api.main:app --port 8000`, then:

```sh
API_URL=http://localhost:8000 npm run dev
```

Check the proxy: `curl http://localhost:5173/v1/health`.

## Checks

```sh
npm run build    # tsc -b && vite build
npx oxlint
```

## Pages

| route | what |
|---|---|
| `/` | **Story.** A chat input (Enter sends, Shift+Enter is a new line). The first paragraph is the company, the rest the story; one paragraph is sent as both. **Ukázka** fills in `examples/stories/brief.yaml`, **Rychlý test bez AI** posts `examples/a.yaml` as `spec_yaml`, the paperclip attaches a `.yaml` spec. Sending goes to `/run/:id`. |
| `/run/:id` | **The run view** (also used by History and Rev story). Left sidebar: **Prompt → Spec → Data → Detektiv → Skóre → Shrnutí** (grey until reached, the running one pulses, finished ones get ✓ and scroll to their section) under a sticky status block (step, progress bar, `zbývá ~N s`, queue position). On the phone it is a top bar with the status and a **Průběh** drawer. Pipeline (`src/run/useRun.ts`): poll the job every 2 s (API step 1 = Spec, steps 2–5 = Data) → `/result` → `POST /detect` automatically → poll `/detect` → Skóre → Shrnutí. Errors show in the section they happened in, with **Zkusit znovu** (a failed job is sent again as a new run; a failed detective is restarted). `#s-<stage>` in the URL scrolls to that section. **Spec**: the company, segments, cities and channels with their shares and the events table (what, from–to, who, stated size, lag), read from the result's `spec_yaml` (`src/spec.ts`, a reader of PyYAML's block output); the YAML only behind *pro vývojáře*. **Data** (lazy): tabs *Tabulky* (psql-style cards: Postgres types, PK/FK badges, the first 5 rows), *ERD* (React Flow, edges from `primary_key`/`foreign_keys`), *CREATE TABLE* (`GET /ddl`, highlighted, copy) and *Hledat a SQL* (the data browser below, embedded). **Shrnutí** (lazy): the verdict line, the prompt from `/input` with each event's phrase highlighted (`src/run/highlight.ts`; unmatched events become chips), and per verification row a chart (the row's daily SQL in the story and with `world: twin`, the gap after the event shaded, the control on its own axis) and a Postgres card (the changed table and column, before/after for story vs twin, the proving SQL with copy). Arrows from each highlight to its chart and card are a fixed SVG overlay, drawn in one by one by anime.js when the section scrolls into view (none with reduced motion, none on the phone); hovering a highlight or a block lights its arrows, block and column. |
| `/run/:id/data` | The job's tables and a virtualized, sortable, searchable (loaded rows, or the whole table via SQL `ILIKE`) grid (TanStack Table 9 + Virtual) that loads 1000 rows at a time by offset as you scroll (`?t=<table>` picks one). The SQL box (`POST /query`, Ctrl+Enter) shows results in the same grid, a "truncated" notice past 1000 rows, and SQL errors (400) and timeouts (408) inline. **▶ Spustit SQL** on each verification row opens this page with that row's SQL, runs it, and marks each value ✓/≠ against `sql_result`. |
| `/history`, `/history/:id` | Every run (`GET /v1/jobs?scope=all`); opening one shows it in the run view. |
| `/rev` | Rev story (data → story): the run view, picker still to come (Prompt 3). |
| `/about` | The technical part (Prompt 3 fills it in). |
| `/jobs/...` | The v1 links redirect: `/jobs/:id` → `/run/:id`, `/jobs/:id/data` → `/run/:id/data`, `/jobs/:id/story` → `/run/:id#s-summary`, `/jobs` → `/history`. |

Errors on every page: 401 → the token form says **Neplatný token**; 404 → **Úloha nenalezena**; network down (or nginx 502/503/504) → a banner with **Zkusit znovu** that also retries when the browser comes back online. 4xx are not retried.

Use **Rychlý test** for testing.
Real stories run on one GPU in one shared queue.

The ZIP download needs the Bearer header.
It is fetched as a blob and saved through a temporary `<a download>`.
