# Story2Data: the plan for the hackathon

4FIS Hackathon, xPORT VŠE, Fri 27. 11. 13:00 → Sat 28. 11. 16:00.
Hacking runs Fri 15:00 → Sat 12:00 (submission). Presentations from 13:00, results at 15:30.

## What we are building, in plain words

You give the program **a company** ("a coffee roaster in Prague and Brno, e-shop and two cafés")
and **a story** ("we raised prices in March, students started leaving six weeks later").
It returns **a database** (customers, orders, deliveries, reviews, tickets, …) in which the story
really happened: nobody wrote "price increase" anywhere, you can only see it in the numbers.
Then it **proves** it: for every event in the story it runs a statistical test and gives you the
SQL query that shows it. The same world *without* the story must show nothing.

Why it matters: teachers at FIS can give every student their own dataset with a hidden story,
and they get the answer key and the SQL for free.

## What already works (before the event)

| Step | What it does | Where |
|---|---|---|
| 1. Story → spec | Gemma 4 (26b, on the homelab GPU) turns Czech text into a structured spec (events, dates, who, how strong) | `s2d/compiler.py` |
| 2. Simulation | builds 14 linked tables day by day; events *cause* the changes | `s2d/sim/` |
| 3. Calibration | makes each event strong enough to be findable (difficulty easy / medium / hard) | `s2d/calibrate.py` |
| 4. Twin | the same world with the same seed but no story, as a control | `s2d/sim` `--no-story` |
| 5. Verification | one test per event: ✅/❌, effect size, z, SQL; story vs twin | `s2d/verify.py` |
| 6. Czech narrative | Gemma writes what happened, only from confirmed events | `s2d/detective/narrate.py` |
| App | Streamlit tabs Story → Spec → Data → Detective → Score | `app/main.py` |

Measured on 11 different stories: 87 % of story events confirmed, 3 % false alarms on the twin,
no crashes. A run takes about 1–2 minutes. Known weak spots are in `DECISIONS.md` (87).

## What we build at the event: the API

Right now everything runs from the command line or the Streamlit app. We add an **HTTP API**
on the server, so anyone (a web page, a Discord bot, a script) can send a story and get the
dataset back. Michal builds the API core; B and C build things that *use* it.

### How it works

A run takes 1–2 minutes, and Cloudflare cuts off requests after ~100 s. So you don't wait for
the answer: you **submit a job**, get a ticket number (`job_id`), and **ask for the status**
until it is done.

| What you want | Request | What you get |
|---|---|---|
| Start a run | `POST /v1/jobs` with company + story (+ difficulty, seed) | `job_id` straight away |
| How far is it? | `GET /v1/jobs/{id}` | current step, progress 0–1, **estimated time left**, finished steps with their times |
| The result | `GET /v1/jobs/{id}/result` | spec, verification table (✅/❌, z, SQL), Czech narrative, **quality summary** ("story 4/4, twin 0/4") and warnings |
| What tables are there | `GET /v1/jobs/{id}/tables` | table names + row counts |
| Look at data | `GET /v1/jobs/{id}/tables/orders?limit=100` | rows as JSON |
| Ask your own question | `POST /v1/jobs/{id}/query` with SQL | the answer (read-only, the hidden answers are not reachable) |
| Take it home | `GET /v1/jobs/{id}/download` | ZIP: CSV per table, Postgres SQL dump, DuckDB file, Czech data dictionary + ERD |
| The answer key | `GET /v1/jobs/{id}/answer-key` | events, SQL and expected results; **teacher token only** |
| Is the server OK | `GET /v1/health` | AI reachable, which model, how many jobs waiting |

**Status example** (what the progress bar reads):

```json
{
  "status": "running", "step": "kalibrace a simulace", "step_index": 3, "steps_total": 5,
  "progress": 0.55, "elapsed_s": 48, "eta_s": 35,
  "steps": [
    {"name": "specifikace (AI)", "done": true, "s": 31, "note": "platná na 1. pokus"},
    {"name": "kalibrace a simulace", "done": false, "eta_s": 30},
    {"name": "dvojče bez příběhu", "done": false, "eta_s": 4},
    {"name": "ověření", "done": false, "eta_s": 2},
    {"name": "český příběh (AI)", "done": false, "eta_s": 15}
  ]
}
```

The time estimate is the median of earlier runs of each step, scaled by the number of customers.

**Access:** every request carries a token (`Authorization: Bearer …`). Each of us gets our own.
Roles: `student` (can generate and query), `teacher` (+ answer key), `admin` (everything).
Only one job runs at a time (the GPU can do one AI call at once); the others wait in a queue.
Docs you can click through: `/docs` on the API.

## Who does what

**Michal (A): the core.** API server (`s2d/api/`), job queue, status + ETA, auth, deploy,
fixing anything in `s2d/sim`, `verify.py`, `calibrate.py`. Merges everything into `main`.

**B: content and the pitch.**
- After the 14:15 brief: rewrite the official example company/story into our input and run it.
- 5 demo stories that work well (2–4 events, each for a specific city or segment).
- SQL exercises: for each demo story 5 questions + SQL answers (for the teaching pitch).
- Slides and the Czech pitch script (3 min core, 5 min full), rehearsal with a stopwatch.

**C: things built on the API** (pick in this order, stop when time runs out):
1. Web page (`clients/web/`): form → progress bar with time left → verification table → download button.
2. Discord or Slack bot: `/pribeh <text>` → replies with the result when the job is done.
3. Worksheet generator: company description + questions for students (PDF/Markdown), key separately.
4. Excel or Power BI file with a prepared pivot for the demo story.

**Together:** Czech check of the generated reviews and the narrative; testing from a phone.

## Rules so we don't break each other's work

- Everyone works on their own branch (`feat/b-…`, `feat/c-…`). Only Michal merges into `main`.
- Before a merge: `uv run pytest -q` must pass.
- Don't change `s2d/sim/engine.py`, `s2d/verify.py`, `s2d/calibrate.py`, `s2d/detective/scan.py`
  without asking Michal.
- To understand the code: read this file, then `DECISIONS.md`, then run one story yourself
  (commands in `README.md`).

## Timeline

| When | What |
|---|---|
| **Thu evening** | text pools (Czech reviews) generating; 3 demo stories pre-generated; laptop: clone, `uv sync`, offline replay tested with Wi-Fi off |
| Fri 13:00–15:00 | registration, opening; 14:15 the brief, **ask the challenge owner what they would do with the output** |
| Fri 15:00–18:30 | adapt to the brief (A, B); API skeleton + one endpoint working (A); web page against a fake API (C) |
| Fri 19:00–01:00 | API complete + deployed (A); clients on the real API (C); stories, exercises, slides (B) |
| Fri 01:00 | pre-generate the demo stories, copy to the laptop; sleep 02:00–06:00 |
| Sat 06:00–08:00 | fixes only |
| **Sat 08:00** | **code freeze**: auto-deploy off, tag `v-demo`; record a backup demo video |
| Sat 08:00–11:00 | rehearsal ×3, Q&A drill |
| Sat 11:45 | submit (deadline 12:00) |
| Sat 13:00 | presentations |

## If something fails at the presentation

1. Live run on the public URL.
2. Same, with `LLM_BACKEND=claude` (if the homelab AI is down).
3. Same, with `LLM_BACKEND=replay` (pre-generated runs, no AI needed).
4. The laptop runs everything locally in replay mode, no internet.
5. The recorded video.

## After the hackathon

Start the qwen bots on the homelab again: `pct start 124; pct start 125; pct start 126`.
