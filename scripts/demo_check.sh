#!/usr/bin/env bash
# Pre-demo checklist: one PASS / FAIL / SKIP line per check, exit 1 if anything FAILs.
#
#   S2D_TOKEN=<admin|teacher token> scripts/demo_check.sh                      # local
#   BASE_URL=https://hack.dobsinsky.dev S2D_TOKEN=... S2D_STUDENT_TOKEN=... scripts/demo_check.sh
#
# Environment:
#   BASE_URL           the API            (default http://localhost:8000)
#   APP_URL            the Streamlit app  (default http://localhost:8501 when BASE_URL is the
#                      default, else BASE_URL: on the server nginx serves both)
#   S2D_TOKEN          a token (required). Locally: DATA_DIR=... uv run python -m s2d.api token check admin
#   S2D_STUDENT_TOKEN  a student token for the 403 check on /answer-key (SKIP without it)
#   S2D_TEST_PG        a Postgres URL: export the job's data there (SKIP without it). Uses the
#                      job's story.duckdb when $DATA_DIR/api/jobs/<id>/run/ is on this machine,
#                      else analyst.duckdb from the ZIP (no _truth schema).
#   DATA_DIR           where the local API keeps its jobs (default data)
#   SPEC               the spec to run (default examples/a.yaml), N_CUSTOMERS (default 2000)
#   JOB_TIMEOUT        seconds to wait for the job (default 300)
set -uo pipefail
cd "$(dirname "$0")/.."

BASE_URL="${BASE_URL:-http://localhost:8000}"; BASE_URL="${BASE_URL%/}"
if [[ -z "${APP_URL:-}" ]]; then
  [[ "$BASE_URL" == "http://localhost:8000" ]] && APP_URL="http://localhost:8501" || APP_URL="$BASE_URL"
fi
APP_URL="${APP_URL%/}"
SPEC="${SPEC:-examples/a.yaml}"
N_CUSTOMERS="${N_CUSTOMERS:-2000}"
JOB_TIMEOUT="${JOB_TIMEOUT:-300}"
DATA_DIR="${DATA_DIR:-data}"

FAILS=0
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if [[ -t 1 ]]; then G=$'\e[32m' R=$'\e[31m' Y=$'\e[33m' O=$'\e[0m'; else G= R= Y= O=; fi
pass() { echo "${G}PASS${O}  $*"; }
fail() { echo "${R}FAIL${O}  $*"; FAILS=$((FAILS + 1)); }
skip() { echo "${Y}SKIP${O}  $*"; }
err1() { head -n 1 "$TMP/err" | head -c 200; }

for tool in curl jq unzip; do
  command -v "$tool" >/dev/null || { echo "needs $tool"; exit 2; }
done
[[ -n "${S2D_TOKEN:-}" ]] || { echo "set S2D_TOKEN (see the header of $0)"; exit 2; }

# req METHOD PATH [curl args...]: body to $TMP/body, prints the HTTP code (000 = no connection)
req() {
  local m="$1" p="$2"; shift 2
  curl -sS -o "$TMP/body" -w '%{http_code}' --max-time 120 -X "$m" "$@" "$BASE_URL$p" 2>"$TMP/err" || true
}
auth=(-H "Authorization: Bearer $S2D_TOKEN")
json=(-H 'Content-Type: application/json')
detail() { jq -r '.detail // empty | tostring' "$TMP/body" 2>/dev/null | head -c 200; err1; }

echo "API $BASE_URL · app $APP_URL"

# ---------------------------------------------------------------- 1. health
code=$(req GET /v1/health)
if [[ "$code" == 200 ]] && jq -e '.ok == true' "$TMP/body" >/dev/null 2>&1; then
  llm=$(jq -r '.llm | "\(.backend) \(.model // "")"' "$TMP/body")
  if jq -e '.llm.reachable == true' "$TMP/body" >/dev/null; then
    pass "health: ok, LLM $llm reachable"
  else
    fail "health: ok, but LLM $llm NOT reachable"
  fi
else
  fail "health: HTTP $code $(detail)"
fi

# ---------------------------------------------------------------- 2. one job end to end
JOB=""
body=$(jq -n --rawfile s "$SPEC" --argjson n "$N_CUSTOMERS" '{spec_yaml: $s, n_customers: $n}')
code=$(req POST /v1/jobs "${auth[@]}" "${json[@]}" -d "$body")
if [[ "$code" == 202 ]]; then
  JOB=$(jq -r .job_id "$TMP/body")
  pass "job: created $JOB ($SPEC, $N_CUSTOMERS customers)"
else
  fail "job: POST /v1/jobs HTTP $code $(detail)"
fi

if [[ -n "$JOB" ]]; then
  t0=$SECONDS; status=queued; last=""
  while (( SECONDS - t0 < JOB_TIMEOUT )); do
    code=$(req GET "/v1/jobs/$JOB" "${auth[@]}")
    [[ "$code" == 200 ]] || { status="HTTP $code"; break; }
    status=$(jq -r .status "$TMP/body")
    step=$(jq -r '.step // empty' "$TMP/body")
    [[ -n "$step" && "$step" != "$last" ]] && { echo "      … $step"; last="$step"; }
    [[ "$status" == done || "$status" == error ]] && break
    sleep 2
  done
  if [[ "$status" == done ]]; then
    pass "job: done in $((SECONDS - t0)) s"
  else
    fail "job: $status after $((SECONDS - t0)) s $(jq -r '.error // empty' "$TMP/body" 2>/dev/null)"
    JOB_FAILED=1
  fi
fi

if [[ -n "$JOB" && -z "${JOB_FAILED:-}" ]]; then
  code=$(req GET "/v1/jobs/$JOB/result" "${auth[@]}")
  n=$(jq '.verification | length' "$TMP/body" 2>/dev/null || echo 0)
  if [[ "$code" == 200 && "$n" -gt 0 ]]; then
    pass "result: $n verification rows, story $(jq -r .summary.story "$TMP/body"), twin $(jq -r .summary.twin "$TMP/body"), narrative from $(jq -r '.narrative.source' "$TMP/body")"
  else
    fail "result: HTTP $code, ${n:-0} verification rows $(detail)"
  fi

  code=$(req GET "/v1/jobs/$JOB/tables" "${auth[@]}")
  if [[ "$code" == 200 ]] && jq -e '[.tables[].name] | index("orders") and index("customers")' "$TMP/body" >/dev/null; then
    pass "tables: $(jq -r '[.tables[] | "\(.name) \(.rows)"] | join(", ")' "$TMP/body" | head -c 160)"
  else
    fail "tables: HTTP $code $(detail)"
  fi

  code=$(req POST "/v1/jobs/$JOB/query" "${auth[@]}" "${json[@]}" -d '{"sql":"SELECT count(*) AS n FROM orders"}')
  if [[ "$code" == 200 ]] && jq -e '.rows[0][0] > 0' "$TMP/body" >/dev/null 2>&1; then
    pass "query: SELECT count(*) FROM orders = $(jq '.rows[0][0]' "$TMP/body")"
  else
    fail "query: HTTP $code $(detail)"
  fi

  zcode=$(curl -sS -o "$TMP/data.zip" -w '%{http_code}' --max-time 120 "${auth[@]}" "$BASE_URL/v1/jobs/$JOB/download" 2>"$TMP/err" || true)
  if [[ "$zcode" == 200 ]] && unzip -l "$TMP/data.zip" >"$TMP/zl" 2>/dev/null && grep -qE ' README\.md$' "$TMP/zl"; then
    pass "download: ZIP $(du -h "$TMP/data.zip" | cut -f1), $(($(wc -l <"$TMP/zl") - 5)) files incl. README.md"
  else
    fail "download: HTTP $zcode, not a ZIP with README.md $(err1)"
  fi

  if [[ -n "${S2D_STUDENT_TOKEN:-}" ]]; then
    code=$(req GET "/v1/jobs/$JOB/answer-key" -H "Authorization: Bearer $S2D_STUDENT_TOKEN")
    [[ "$code" == 403 ]] && pass "answer-key: student gets 403" || fail "answer-key: student got HTTP $code, expected 403 $(detail)"
  else
    skip "answer-key: set S2D_STUDENT_TOKEN to check that a student gets 403"
  fi
else
  fail "result / tables / query / download / answer-key: not checked, no finished job"
fi

# ---------------------------------------------------------------- 3. Streamlit app
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 "$APP_URL/" 2>"$TMP/err" || true)
hc=$(curl -sS --max-time 30 "$APP_URL/_stcore/health" 2>>"$TMP/err" || true)
if [[ "$code" == 200 && "$hc" == ok ]]; then
  pass "app: / is 200, /_stcore/health says ok"
else
  fail "app: / HTTP $code, /_stcore/health '${hc:0:60}' $(err1)"
fi

# ---------------------------------------------------------------- 4. Postgres export
if [[ -z "${S2D_TEST_PG:-}" ]]; then
  skip "postgres: set S2D_TEST_PG to a Postgres URL to check the export"
elif [[ -z "$JOB" || -n "${JOB_FAILED:-}" ]]; then
  fail "postgres: no finished job to export"
else
  db="$DATA_DIR/api/jobs/$JOB/run/story.duckdb"; truth=True
  if [[ ! -f "$db" ]]; then                           # remote API: use the ZIP's analyst tables
    unzip -o -q "$TMP/data.zip" analyst.duckdb -d "$TMP" 2>/dev/null && db="$TMP/analyst.duckdb" && truth=False
  fi
  if [[ -f "$db" ]]; then
    if out=$(uv run --quiet python -c '
import sys
from s2d.sim.pg import export
rows = export(sys.argv[1], sys.argv[2], truth=sys.argv[3] == "True")
print(f"{len(rows)} tables, {sum(rows.values())} rows" + ("" if sys.argv[3] == "True" else " (analyst.duckdb from the ZIP, no _truth)"))
' "$db" "$S2D_TEST_PG" "$truth" 2>"$TMP/err"); then
      pass "postgres: exported $(basename "$db"): $out"
    else
      fail "postgres: $(tail -n 3 "$TMP/err" | head -c 300)"
    fi
  else
    fail "postgres: no story.duckdb at $db and no analyst.duckdb in the ZIP"
  fi
fi

echo
if (( FAILS )); then echo "$FAILS check(s) FAILED"; exit 1; fi
echo "all checks passed"
