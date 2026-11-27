# Prompt: stated sizes + year-over-year control (DONE)

Already run on 27. 11. and merged into main (DECISIONS 90-93, commits a3729b7..0c20296).
Kept for the record.

```text
Continue Story2Data. Create branch feat/stated-sizes from main. First read DECISIONS.md
(9, 12, 54, 58, 62, 64, 86–89), s2d/calibrate.py, s2d/verify.py and s2d/compiler.py.

Problem (found 27.11): the hackathon brief is "generate data where company X's sales dropped by 5 %".
Story "Od dubna 2026 klesly tržby o 5 %." compiles to purchase_rate size -0.05 for everyone
(target {}), and then:
- Calibration inflated it to -30 % (Gemma picked difficulty easy). A number the story states must
  come out as that number.
- Uncalibrated, -5 % is not confirmed: the verifier measured about -10 %, z 2.6. An event for
  everyone has no control group, so the plain before/after picks up the March→April seasonal
  change (the twin alone shows -6 %). 80k customers barely helps (z 3.0), so it is seasonality,
  not noise.

Goal: "-5 %" in → about -5 % in the data and in the verifier's measurement, with the twin not
confirmed. Priorities:

1. Stated sizes are facts. Add a way for the spec to mark an effect's size as stated (e.g.
   effect.size_stated: bool, default false; the compiler sets it true when the story text gives
   the number). Calibration never scales a stated size: if it is below target, mark it
   below_target, write the expected z into _truth.calibration, and warn. Difficulty scaling
   (DIFFICULTY_SCALE) must not touch stated sizes either. Update the compiler prompt and
   few-shots, the JSON schema (python -m s2d.spec export-schema), and the 3 compiler tests.
   An LLM-written spec without the field must still work.

2. Year-over-year control for events with no control dimension (empty target, or a target whose
   keys the KPI cannot split by). Treated = the KPI around T; control = the same KPI over the same
   calendar dates 364 days earlier (weekday-aligned). DiD = (after/before at T) / (after/before a
   year earlier) - 1. Use it only when the data has a full window a year before T; otherwise keep
   the plain before/after and say so in the result (control: none, reason). The SQL must stay
   readable and give the same number as Python (sql_matches). Keep the placebo-in-time z and the
   bootstrap CI on the YoY series. Calibration measures with the same test.

3. Check: run the brief story (company: sportovní potřeby, e-shop + prodejny Praha a Brno, 20 000
   customers; story: data from Jan 2025 to end of 2026, sales down 5 % from April 2026) through
   compiler → sim → twin → verify at medium, seeds 1–5. Report the measured %, CI and z per seed,
   story vs twin. If -5 % is not confirmable at 20k, report at what customer count it is (d grows
   with √N) and say so plainly; do not inflate the size.

4. Rerun scripts/e2e.py (or at least examples A and B plus 3 of the stories) and confirm nothing
   regressed: report story/twin confirmed shares before vs after.

Tests: a stated size survives calibration unchanged; YoY control is chosen only when a year of
data exists and its SQL matches Python; the brief story at a customer count where it is findable
is confirmed and its twin is not. `uv run pytest -q -m "not integration"` passes.
Small commits, record everything in DECISIONS.md (new numbers from 90), don't merge to main.
When done, show: the verifier table for the brief story (story vs twin, 5 seeds), the YoY SQL,
and the e2e before/after summary.
```
