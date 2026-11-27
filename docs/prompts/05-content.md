# Prompts: content and the pitch (role B, Pepa)

Three prompts, one Claude Code session each, in this order (each needs the previous one's stories).
The demo has three stories: a short one (run live), a big one (a chain takes over a rival, pre-generated) and an optional random one for Q&A.
Each one stops and reports; Michal merges.
They don't touch any code, so they run in parallel with the web page (`04-web.md`).

## Before the first prompt

```bash
git clone git@github.com:michalomegalul/hackathon-27-12-2026.git && cd hackathon-27-12-2026
curl -LsSf https://astral.sh/uv/install.sh | sh     # if `uv` is missing
uv sync
echo "S2D_TOKEN=<the team token>" > .env.local       # git-ignored; never commit it
```

Two ways to run a story, both used below:
- **Through the live API** (the AI turns the Czech story into a spec; 1–2 min, one GPU queue shared with the team):
  `POST https://hack.dobsinsky.dev/v1/jobs` with `Authorization: Bearer $S2D_TOKEN` (`docs/API.md`).
- **Locally without AI** from a spec YAML (seconds): `scripts/try.sh <spec.yaml> [n_customers]`.

Rule: send each new story to the API **once** to get its spec, then iterate on the spec locally with `try.sh`.
No API jobs after midnight on Friday: the queue is for the final demo runs.

## Prompt 1: three demo stories (Fri 15:00–20:00)

```text
Story2Data hackathon, role B: the demo stories. Repo: git@github.com:michalomegalul/hackathon-27-12-2026.git,
git pull on main, create branch feat/b-content. Read docs/PLAN.md, README.md, docs/API.md, DECISIONS.md
(at least the entries about stated sizes, customer counts and the year-over-year control, and the
latest ones), examples/stories/*.yaml (format: title, company, story in Czech), examples/brief/sport.yaml
and s2d/spec.py (EventType and Metric: the only event types and metrics the simulator supports).
Don't change any code under s2d/, app/ or clients/. No Co-Authored-By lines, small commits, never
merge to main. The team API token is in .env.local as S2D_TOKEN; never print it or commit it.

Goal: three demo stories, each understood by a TV executive and a banker in 10 s, each confirmed
reliably by the verifier. Use invented company names only (no real chains or brands).

1. SHORT (examples/stories/demo-short.yaml): the opening demo, as small as
   examples/stories/kavarny.yaml. One small company, ~10–20k customers, 2 events, each tied to one
   city or segment, with a date and a stated size ("o 20 %"), one with a lag. Must finish on the
   live API in about a minute, so it can run live on stage.
2. BIG (examples/stories/demo-big.yaml): "a supermarket chain buys a rival chain", e.g. Kupka a.s.
   takes over the 40 stores of Trhovna. 80–100k customers (API max 100000), several cities and
   segments, 3–4 events over two years. There is no "acquisition" event type, so tell the takeover
   through the supported ones, e.g.: the taken-over stores' customers churn after the rebranding
   (churn_shock), new customers arrive in the cities where the new stores open (campaign or
   competitor_entry with acquisition_rate), prices of the old brand go up (price_change), the IT
   migration breaks the e-shop for two weeks (service_outage), a new courier (courier_change).
   At least one effect only shows after a JOIN (a segment or a city), and one with a lag.
   Pre-generate it before midnight; on stage we open the finished job, we don't wait for it.
3. RANDOM (optional, only if 1 and 2 are done): a wild card in a different industry, 2–3 events,
   for Q&A ("give us any story": it shows nothing is hand-tuned).

Process per story:
1. Send it ONCE to the live API (POST /v1/jobs, company + story, difficulty medium), poll
   GET /v1/jobs/{id} every 5 s, then GET /result. Save the returned spec_yaml as
   examples/demo/<name>.yaml.
2. Iterate locally without AI: scripts/try.sh examples/demo/<name>.yaml <n>, with 3 different
   seeds (edit meta.seed). Target: every event confirmed on all 3 seeds, twin 0 false alarms.
   If an event fails, change the story text (bigger stated size, narrower target, longer window)
   and the spec together; pick n_customers from DECISIONS (whole-population effects need far more).
   When the story is final, send it to the API once more: that job is the one we open on stage.
3. Write docs/demo-stories.md: one section per story with the one-sentence pitch, the events,
   n_customers, seeds tried, story x/y and twin x/y per seed, run time, the stage job_id, and
   what we say while it is on screen.
Stop and report the table of results.
```

## Prompt 2: SQL exercises for teachers (Fri 20:00–23:30)

```text
Continue on branch feat/b-content (git pull main, rebase). Read docs/demo-stories.md and
docs/research/notes/hackathon_judging.md (the jury are FIS teachers: databases, analytics, data
mining). Use the local data from scripts/try.sh in data/try/<name>/story/story.duckdb, schema main
only (never _truth: students won't have it). Don't change code.

For each demo story (short, big, and random if it exists) write docs/teaching/<name>.md in Czech:
- "Zadání pro studenty": the company text, the table list with one line per table, and 5 questions
  from easy to hard: 1 a plain SELECT/GROUP BY, 2 a JOIN of 2–3 tables, 3 a time series by week,
  4 a comparison segment vs the rest (before/after the event date), 5 an open question
  ("Co se stalo a kdy? Dokažte to dotazem.") whose answer is a story event.
- "Řešení" (separately, for the teacher): the SQL for each question (DuckDB dialect), the actual
  result rows from running it (paste the output), and 1–2 sentences of interpretation. Question 5's
  answer must match the verifier's SQL and measured size from verify.json.
Run every query and paste real output; no made-up numbers. Also make docs/teaching/README.md:
how a teacher generates a fresh dataset per student (different seed, same story) and grades it.
Stop and report.
```

## Prompt 3: pitch script and slides outline (Fri 23:30–01:00)

```text
Continue on branch feat/b-content (git pull main, rebase). Read docs/PLAN.md, docs/demo-stories.md,
docs/teaching/, docs/research/notes/hackathon_judging.md and docs/research/winning-plan.md
(the jury, the "one moment they remember" idea, the weak spots and our answers). Don't change code.

Write in Czech:
1. docs/pitch/script.md: a 3-minute core and a 5-minute full version, as spoken text with timings
   per block: problem (teachers need datasets with a hidden story) → live demo (the opening demo
   story: text in, database out, every event proven with SQL, the twin shows nothing) → why it is
   hard and why it is right (calibration, twin, stated sizes) → teaching use (exercises, a fresh
   dataset per student) → numbers (from DECISIONS/PLAN: confirmed %, false alarms %) → ask.
   Mark exactly where the demo clicks happen and what we say if the live run is slow
   (fallback order from docs/PLAN.md "If something fails at the presentation").
2. docs/pitch/qa.md: the 12 hardest jury questions (statistician, teacher, TV/bank partner)
   with a 2–3 sentence answer each, every number taken from DECISIONS.md or the docs.
3. docs/pitch/slides.md: 6–8 slides, title + 3 bullets max + what is on screen; no walls of text.
Read every number from the repo; mark anything unverified with (OVĚŘIT). Stop and report.
```
