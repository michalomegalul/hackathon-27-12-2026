# Prompts: content and the pitch (role B, Pepa)

Three prompts, one Claude Code session each, in this order (each needs the previous one's stories).
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

## Prompt 1: five demo stories that work (Fri 15:00–20:00)

```text
Story2Data hackathon, role B: the demo stories. Repo: git@github.com:michalomegalul/hackathon-27-12-2026.git,
git pull on main, create branch feat/b-content. Read docs/PLAN.md, README.md, docs/API.md, DECISIONS.md
(at least the entries about stated sizes, customer counts and the year-over-year control, and the
latest ones), examples/stories/*.yaml (format: title, company, story in Czech), examples/brief/sport.yaml
and s2d/spec.py (which event types and targets the simulator supports). Don't change any code under
s2d/, app/ or clients/. No Co-Authored-By lines, small commits, never merge to main.
The team API token is in .env.local as S2D_TOKEN; never print it or commit it.

Goal: 5 demo stories in examples/stories/demo-*.yaml that a TV executive and a banker get in 10 s,
and that the verifier confirms reliably. Each one:
- a different industry from the existing examples (or a better version of brief.yaml, SportMax),
  realistic Czech company text with cities, channels and segments;
- 2–4 events, each tied to a specific city, segment or channel, with a date and a stated size
  ("o 15 %"), at least one with a lag ("o šest týdnů později") and one that only shows after a JOIN;
- uses only event types the simulator supports (s2d/spec.py); if a story needs an unsupported
  one, rewrite the story rather than asking for code.
Process per story:
1. Send it ONCE to the live API (POST /v1/jobs, company + story, difficulty medium), poll
   GET /v1/jobs/{id} every 5 s, then GET /result. Save the returned spec_yaml as
   examples/demo/<name>.yaml.
2. Iterate locally without AI: scripts/try.sh examples/demo/<name>.yaml <n>, with 3 different
   seeds (edit meta.seed). Target: every event confirmed on all 3 seeds, twin 0 false alarms.
   If an event fails, change the story text (bigger stated size, narrower target, longer window)
   and the spec together; pick n_customers from DECISIONS (whole-population effects need far more).
3. Write docs/demo-stories.md: one section per story with the one-sentence pitch, the events,
   n_customers, seeds tried, story x/y and twin x/y per seed, run time, and which one we open the
   demo with.
Stop and report the table of results.
```

## Prompt 2: SQL exercises for teachers (Fri 20:00–23:30)

```text
Continue on branch feat/b-content (git pull main, rebase). Read docs/demo-stories.md and
docs/research/notes/hackathon_judging.md (the jury are FIS teachers: databases, analytics, data
mining). Use the local data from scripts/try.sh in data/try/<name>/story/story.duckdb, schema main
only (never _truth: students won't have it). Don't change code.

For each of the 5 demo stories write docs/teaching/<name>.md in Czech:
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
