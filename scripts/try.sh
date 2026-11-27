#!/usr/bin/env bash
# Try the whole pipeline on your machine: story or spec -> data -> twin -> verification.
#
#   scripts/try.sh                                  # hand-written brief spec, no AI needed
#   scripts/try.sh examples/stories/sport.yaml      # Czech story -> spec with Gemma (needs the LLM)
#   scripts/try.sh examples/b.yaml 40000            # any spec, with a customer count
#
# Output goes to data/try/<name>/ : story.duckdb (open it in DuckDB / DBeaver), the twin,
# verify.json, and the SQL of every test printed at the end.
set -euo pipefail
cd "$(dirname "$0")/.."

INPUT="${1:-examples/brief/sport.yaml}"
N="${2:-80000}"                       # a -5 % drop needs ~80k customers to confirm reliably
NAME="$(basename "${INPUT%.*}")"
OUT="data/try/$NAME"
mkdir -p "$OUT"

if grep -q '^story:' "$INPUT"; then
  echo "== 1/4 story -> spec (AI: $(uv run python -c 'from s2d import llm; print(llm.describe())'))"
  uv run python -m s2d.compiler "$INPUT" --out "$OUT/spec.yaml"
  SPEC="$OUT/spec.yaml"
else
  echo "== 1/4 spec given, no AI needed: $INPUT"
  SPEC="$INPUT"
fi

echo "== 2/4 simulate with the story ($N customers, calibrated)"
uv run python -m s2d.sim run "$SPEC" --n-customers "$N" --out "$OUT/story" --texts none

echo "== 3/4 simulate the twin (same seed, no story)"
uv run python -m s2d.sim run "$SPEC" --n-customers "$N" --no-story --out "$OUT/twin" --texts none

echo "== 4/4 verify: one test per event, story vs twin"
uv run python -m s2d.verify "$OUT/story" --twin "$OUT/twin" --sql --out "$OUT/verify.json"

echo
echo "Data: $OUT/story/story.duckdb  (tables in schema main, the answers in _truth)"
echo "Try:  uv run python -c \"import duckdb; print(duckdb.connect('$OUT/story/story.duckdb').sql('select city, count(*) from orders group by 1'))\""
