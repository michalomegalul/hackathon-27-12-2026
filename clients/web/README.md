# Story2Data web (`clients/web/`)

The web page for the Story2Data API (`docs/API.md`). It has a story form, a progress bar while the job runs, the verification table and a ZIP download.
It is built with Vite 8, React 19, React Router 8 (data mode), TanStack Query 5 and Tailwind v4, with the pins from `docs/research/web-stack.md`.
It uses no MSW.

## Setup

Node **≥ 22.22** is required (Vite 8 and React Router 8 do not run on Node 18).

1. **Get a token.** Ask Michal, or on the server run:
   ```sh
   uv run python -m s2d.api token <name> student
   ```
2. **Put it in `clients/web/.env.local`.** The file is git-ignored by `*.local`; never commit it.
   Use the exact name `.env.local`, not `.env.local.txt`.
   ```sh
   VITE_API_TOKEN=<token>
   ```
3. Install and run:
   ```sh
   cd clients/web
   npm ci
   npm run dev            # http://localhost:5173, /v1 is proxied to https://hack.dobsinsky.dev
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
| `/` | Form with company, story, difficulty, customers, dirt and seed. **Načíst příklad** fills in `examples/stories/brief.yaml`. **Rychlý test (bez AI)** posts `examples/a.yaml` as `spec_yaml`. The side panel lists finished jobs to reuse. |
| `/jobs/:id` | Polls every 2 s and stops on done or error. Shows the 5 steps, the running one highlighted, `zbývá ~N s`, and the queue position. When the job is done it shows the summary, the verification table (each row expands to its SQL), untested events, warnings, the narrative and the ZIP download. |
| `/jobs` | My jobs (`GET /v1/jobs`) with status and summary. |

Use **Rychlý test** for testing.
Real stories run on one GPU in one shared queue.

The ZIP download needs the Bearer header.
It is fetched as a blob and saved through a temporary `<a download>`.
