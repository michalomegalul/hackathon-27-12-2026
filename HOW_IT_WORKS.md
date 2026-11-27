# How it works

You write a company and a story in Czech ("we raised prices in March, students left six weeks later").
You get a database where that really happened, plus a check that the story is in the numbers.

One job runs these steps (`s2d/api/pipeline.py`):

1. **compile** (`s2d/compiler.py`) – the LLM turns the text into a spec: events, dates, who is hit, how much.
   The spec is validated; if it is wrong the error goes back to the model, and after two failed tries Claude gets one go.
2. **calibrate** (`s2d/calibrate.py`) – scales weak events up until the test can see them.
   A size the story states ("-5 %") is kept as it is.
3. **simulate** (`s2d/sim/`) – builds the linked tables day by day from the spec and a seed.
   Events change behaviour (purchase rate, churn, delivery delay), they are not written in anywhere.
   Texts for reviews and tickets are sampled from pools made earlier (`s2d/texts.py`).
4. **twin** – the same world and seed, without the story. Nothing should be found in it.
5. **verify** (`s2d/verify.py`) – one statistical test per event, story against twin, with the SQL that shows it.
6. **narrate** (`s2d/detective/narrate.py`) – a short Czech summary of the events that were confirmed.

The answer key stays in a hidden `_truth` schema.
The detective (`s2d/detective/`) is a separate job: it only sees the analyst tables and looks for events by itself,
and `s2d/score.py` compares what it found with the answer key.

Every LLM answer is cached on disk, so a demo story does not wait for the model twice.
Backend (`ollama`, `claude`, `replay`) is set by `LLM_BACKEND`, see `README.md`.

Parts:

- `s2d/api/` – FastAPI, job queue, one worker. Contract in `docs/API.md`.
- `clients/web/` – the React site, served by nginx next to the API (`compose.yaml`).
- `examples/` – stories and hand-written specs. `schema/story.schema.json` is the spec schema.
- `DECISIONS.md` – why things are the way they are.
