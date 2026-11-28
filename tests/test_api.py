"""The HTTP API (docs/API.md) through FastAPI's TestClient, without an LLM: the job is given
as spec_yaml, LLM_BACKEND=replay with an empty cache, so the narrator uses the template."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "examples" / "a.yaml").read_text("utf-8")
STEP_NAMES = ["specifikace (AI)", "kalibrace a simulace", "dvojče bez příběhu", "ověření", "český příběh (AI)"]


def _wait(c, url, h, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = c.get(url, headers=h).json()
        if s["status"] in ("done", "error"):
            return s
        time.sleep(0.5)
    raise AssertionError(f"{url} did not finish in {timeout} s")


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_DIR", str(tmp))
    mp.setenv("LLM_BACKEND", "replay")
    mp.setenv("LLM_CACHE_DIR", str(tmp / "llm_cache"))
    mp.setenv("TEXT_POOL_DIR", str(tmp / "text_pools"))
    from s2d.api.auth import add_token
    from s2d.api.main import app
    toks = {r: add_token(r, r) for r in ("student", "teacher", "admin")}
    toks["other"] = add_token("other", "student")
    hdr = {k: {"Authorization": f"Bearer {v}"} for k, v in toks.items()}
    with TestClient(app) as c:
        r = c.post("/v1/jobs", json={"spec_yaml": SPEC, "n_customers": 1500, "seed": 3}, headers=hdr["student"])
        assert r.status_code == 202, r.text
        first = r.json()
        seen = [c.get(f"/v1/jobs/{first['job_id']}", headers=hdr["student"]).json()]
        done = _wait(c, f"/v1/jobs/{first['job_id']}", hdr["student"])
        yield {"c": c, "h": hdr, "id": first["job_id"], "created": first, "first_status": seen[0],
               "status": done, "dir": tmp}
    mp.undo()


# ---------------------------------------------------------------- auth and input


def test_health_needs_no_token(api):
    r = api["c"].get("/v1/health")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["llm"]["backend"] == "replay" and j["llm"]["reachable"] is True
    assert set(j["queue"]) == {"running", "waiting"}


def test_401_without_or_with_unknown_token(api):
    c = api["c"]
    assert c.get("/v1/jobs").status_code == 401
    r = c.get("/v1/jobs", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json() == {"detail": "missing or unknown token"}
    assert c.post("/v1/jobs", json={"spec_yaml": SPEC}).status_code == 401
    assert c.get(f"/v1/jobs/{api['id']}/result").status_code == 401


def test_public_role_lets_requests_without_token_in(api, monkeypatch):
    c = api["c"]
    monkeypatch.setenv("API_PUBLIC_ROLE", "teacher")
    r = c.get("/v1/jobs")
    assert r.status_code == 200 and r.json() == {"jobs": []}  # "public" owns no job yet
    assert c.get(f"/v1/jobs/{api['id']}").json()["status"] == "done"  # teacher sees the student's job
    assert c.get(f"/v1/jobs/{api['id']}/answer-key").status_code == 200
    # a token still wins, and an unknown one is still 401
    assert c.get("/v1/jobs", headers=api["h"]["student"]).json()["jobs"][0]["owner"] == "student"
    assert c.get("/v1/jobs", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_public_role_student_sees_only_public_jobs(api, monkeypatch):
    monkeypatch.setenv("API_PUBLIC_ROLE", "student")
    assert api["c"].get(f"/v1/jobs/{api['id']}").status_code == 404


def test_public_role_must_be_a_role(api, monkeypatch):
    monkeypatch.setenv("API_PUBLIC_ROLE", "guest")
    with pytest.raises(RuntimeError, match="API_PUBLIC_ROLE"):
        api["c"].get("/v1/jobs")


def test_422_and_400_on_bad_input(api):
    c, h = api["c"], api["h"]["student"]
    r = c.post("/v1/jobs", json={"company": "x"}, headers=h)
    assert r.status_code == 422 and "company and story, or spec_yaml" in str(r.json()["detail"])
    assert c.post("/v1/jobs", json={"spec_yaml": SPEC, "n_customers": 100_001}, headers=h).status_code == 422
    assert c.post("/v1/jobs", json={"spec_yaml": SPEC, "difficulty": "brutal"}, headers=h).status_code == 422
    r = c.post("/v1/jobs", json={"spec_yaml": "meta: {seed: 1}"}, headers=h)
    assert r.status_code == 400 and r.json()["detail"].startswith("spec_yaml is not a valid spec")
    r = c.post("/v1/jobs", json={"spec_yaml": "a: [unclosed"}, headers=h)
    assert r.status_code == 400


# ---------------------------------------------------------------- lifecycle and status


def test_lifecycle_queued_to_done(api):
    assert api["created"]["status"] == "queued" and api["created"]["position"] == 0
    s = api["status"]
    assert s["status"] == "done", s.get("error")
    assert s["progress"] == 1.0 and s["eta_s"] == 0 and s["step_index"] == 5 and s["step"] is None
    assert [st["name"] for st in s["steps"]] == STEP_NAMES
    assert all(st["done"] and isinstance(st["s"], (int, float)) for st in s["steps"])
    assert s["steps"][0]["note"] == "spec zadán (bez AI)"
    assert s["steps"][3]["note"].startswith("story: ")


def test_status_fields_while_not_done(api):
    s = api["first_status"]
    assert s["status"] in ("queued", "running", "done")
    keys = {"job_id", "status", "position", "step", "step_index", "steps_total", "progress",
            "elapsed_s", "eta_s", "steps", "error"}
    assert keys <= set(s)
    assert s["steps_total"] == 5
    if s["status"] != "done":
        assert s["eta_s"] > 0 and 0 <= s["progress"] < 1
        assert any(not st["done"] and "eta_s" in st for st in s["steps"])


def test_eta_from_history_scales_with_customers(api):
    from s2d.api import store
    t = {"kalibrace a simulace": [{"s": 2 * store.prior("kalibrace a simulace", 10_000), "n": 10_000}]}
    assert store.estimate("kalibrace a simulace", 40_000, t) == pytest.approx(2 * store.prior("kalibrace a simulace", 40_000))
    assert store.estimate("český příběh (AI)", 40_000, {}) == store.PRIORS["český příběh (AI)"][0]
    state = store.new_job("x", "student", {"spec_yaml": None, "n_customers": 10_000}, "t")
    left, per = store.remaining(state, timings={})
    assert left == pytest.approx(sum(store.prior(n, 10_000) for n in STEP_NAMES))
    assert per[0] == store.PRIORS["specifikace (AI)"][0]
    store.job_dir(state["job_id"]).joinpath("job.json").unlink()
    timings = store.read_json(store.timings_path())
    assert "kalibrace a simulace" in timings and "český příběh (AI)" not in timings  # template: not a GPU time


def test_running_job_at_restart_becomes_error(api):
    from s2d.api import store
    from s2d.api.worker import Worker
    st = store.new_job("student", "student", {"spec_yaml": SPEC}, "dead")
    st.update(status="running", started=time.time())
    store.save_job(st)
    Worker().recover()
    assert store.load_job(st["job_id"])["status"] == "error"
    assert store.load_job(st["job_id"])["error"] == "server restarted"
    r = api["c"].get(f"/v1/jobs/{st['job_id']}", headers=api["h"]["student"]).json()
    assert r["status"] == "error" and r["error"] == "server restarted"


def test_job_visibility_and_listing(api):
    c, h, jid = api["c"], api["h"], api["id"]
    assert c.get(f"/v1/jobs/{jid}", headers=h["other"]).status_code == 404
    assert c.get(f"/v1/jobs/{jid}/result", headers=h["other"]).json() == {"detail": "job not found"}
    assert c.get(f"/v1/jobs/{jid}", headers=h["teacher"]).status_code == 200
    mine = c.get("/v1/jobs", headers=h["student"]).json()["jobs"]
    assert jid in {j["job_id"] for j in mine}
    assert all(j["owner"] == "student" for j in mine)
    assert c.get("/v1/jobs", headers=h["other"]).json()["jobs"] == []
    assert jid in {j["job_id"] for j in c.get("/v1/jobs", headers=h["admin"]).json()["jobs"]}
    row = next(j for j in mine if j["job_id"] == jid)
    assert row["summary"]["story"].count("/") == 1


def test_not_done_is_409(api):
    from s2d.api import store
    st = store.new_job("student", "student", {"spec_yaml": SPEC}, "waiting")  # never queued
    r = api["c"].get(f"/v1/jobs/{st['job_id']}/result", headers=api["h"]["student"])
    assert r.status_code == 409 and r.json()["detail"] == "job is queued, not done"
    st.update(status="error", error="x")
    store.save_job(st)


# ---------------------------------------------------------------- result and data


def test_result(api):
    r = api["c"].get(f"/v1/jobs/{api['id']}/result", headers=api["h"]["student"])
    assert r.status_code == 200
    j = r.json()
    assert set(j) >= {"spec_yaml", "verification", "narrative", "summary", "warnings", "rows", "untested"}
    assert "meta:" in j["spec_yaml"]
    n = len(j["verification"])
    assert n > 0 and j["summary"]["story"].endswith(f"/{n}") and j["summary"]["twin"].endswith(f"/{n}")
    assert j["narrative"]["text"] and j["narrative"]["source"].startswith("template")
    keys = {"event_id", "kpi", "target", "story_size", "measured", "ci", "z", "confirmed", "control_mode",
            "twin_z", "twin_confirmed", "sql", "sql_result"}
    for row in j["verification"]:
        assert keys <= set(row)
        if row["status"] != "not_testable":
            assert row["sql_matches"] is True
    assert j["rows"]["orders"] > 1000 and set(j["rows"]) >= {"customers", "orders", "reviews"}


def test_tables_and_pages(api):
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    tables = {t["name"]: t for t in c.get(f"/v1/jobs/{jid}/tables", headers=h).json()["tables"]}
    assert "orders" in tables and "answer_key" not in tables
    assert {"name": "order_date", "type": "DATE"} in tables["orders"]["columns"]
    p = c.get(f"/v1/jobs/{jid}/tables/orders?limit=5&offset=10", headers=h).json()
    assert p["total"] == tables["orders"]["rows"] and len(p["rows"]) == 5
    assert p["rows"][0][0] == 11  # order_id, in order
    names = [col["name"] for col in p["columns"]]
    assert isinstance(p["rows"][0][names.index("order_date")], str)
    assert c.get(f"/v1/jobs/{jid}/tables/orders?limit=1001", headers=h).status_code == 422
    assert c.get(f"/v1/jobs/{jid}/tables/nope", headers=h).json() == {"detail": "table not found"}


def test_query(api):
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    r = c.post(f"/v1/jobs/{jid}/query", json={"sql": "SELECT count(*) AS n FROM orders"}, headers=h).json()
    assert r["columns"] == [{"name": "n", "type": "BIGINT"}] and r["rows"][0][0] > 0 and not r["truncated"]
    r = c.post(f"/v1/jobs/{jid}/query", json={"sql": "SELECT * FROM order_items"}, headers=h).json()
    assert len(r["rows"]) == 1000 and r["truncated"] is True
    r = c.post(f"/v1/jobs/{jid}/query", json={"sql": "SELEC nonsense"}, headers=h)
    assert r.status_code == 400


def test_query_cannot_reach_the_answer_key_or_files(api):
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    story_db = Path(api["dir"]) / "api" / "jobs" / jid / "run" / "story.duckdb"
    parquet = story_db.parent / "_truth" / "answer_key.parquet"
    assert story_db.exists() and parquet.exists()
    attempts = [
        "SELECT * FROM _truth.answer_key",
        "SELECT * FROM information_schema.tables WHERE table_schema = '_truth'",
        f"SELECT * FROM read_parquet('{parquet}')",
        f"SELECT * FROM '{parquet}'",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_text('/etc/hostname')",
        "SELECT * FROM glob('*')",
        f"ATTACH '{story_db}' AS s (READ_ONLY)",
        "COPY orders TO 'out.csv'",
        "SET enable_external_access = true",
        "SET lock_configuration = false",
        "INSTALL httpfs",
        "LOAD httpfs",
        "CREATE TABLE x AS SELECT 1",
        "DROP TABLE orders",
    ]
    for q in attempts:
        r = c.post(f"/v1/jobs/{jid}/query", json={"sql": q}, headers=h)
        if r.status_code == 200:  # only the information_schema probe may answer, and it must be empty
            assert r.json()["rows"] == [], q
        else:
            assert r.status_code == 400, (q, r.text)
    assert not (Path.cwd() / "out.csv").exists()
    r = c.post(f"/v1/jobs/{jid}/query", json={"sql": "SELECT count(*) FROM orders"}, headers=h)
    assert r.status_code == 200  # the table survived the DROP


def test_query_timeout():
    from s2d.api import sandbox
    import duckdb
    db = Path(__file__).parent / "_timeout.duckdb"
    db.unlink(missing_ok=True)
    duckdb.connect(str(db)).execute("CREATE TABLE t AS SELECT 1 AS x").close()
    try:
        t0 = time.time()
        with pytest.raises(sandbox.QueryTimeout):
            sandbox.query(db, "SELECT count(*) FROM range(100000000000) a, range(10) b", timeout_s=0.5)
        assert time.time() - t0 < 5
    finally:
        db.unlink(missing_ok=True)


def test_answer_key_roles(api):
    c, h, jid = api["c"], api["h"], api["id"]
    r = c.get(f"/v1/jobs/{jid}/answer-key", headers=h["student"])
    assert r.status_code == 403 and r.json() == {"detail": "teacher or admin only"}
    for role in ("teacher", "admin"):
        r = c.get(f"/v1/jobs/{jid}/answer-key", headers=h[role])
        assert r.status_code == 200
        j = r.json()
        assert j["answer_key"] and {"event_id", "metric", "start_date", "magnitude_pct"} <= set(j["answer_key"][0])
        assert j["calibration"] and j["verification"] and j["spec_yaml"]


def test_download_zip(api):
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    r = c.get(f"/v1/jobs/{jid}/download", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert f"story2data-{jid}.zip" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"README.md", "analyst.duckdb", "customers.csv", "orders.csv", "reviews.csv"} <= names
    assert any(n.startswith("messy/") for n in names)  # examples/a.yaml is messiness light
    assert not any("truth" in n or "answer" in n for n in names)
    readme = z.read("README.md").decode()
    assert "| customer_id | BIGINT | identifikátor zákazníka" in readme and "### orders" in readme
    header = z.read("orders.csv").decode().splitlines()[0]
    assert header.startswith("order_id,customer_id")
    cached = Path(api["dir"]) / "api" / "jobs" / jid / "download.zip"
    mtime = cached.stat().st_mtime
    assert c.get(f"/v1/jobs/{jid}/download", headers=h).content == r.content
    assert cached.stat().st_mtime == mtime  # built once


def test_detective(api):
    c, h, jid = api["c"], api["h"], api["id"]
    assert c.get(f"/v1/jobs/{jid}/detect", headers=h["student"]).json() == {"detail": "detective not run"}
    r = c.post(f"/v1/jobs/{jid}/detect", headers=h["student"])
    assert r.status_code == 202 and r.json()["status"] in ("queued", "running", "done")
    s = _wait(c, f"/v1/jobs/{jid}/detect", h["student"])
    assert s["status"] == "done", s["error"]
    assert isinstance(s["events"], list) and s["narrative"]["text"] is not None
    assert s["score"] is None  # students never see the score
    t = c.get(f"/v1/jobs/{jid}/detect", headers=h["teacher"]).json()
    assert {"precision", "recall", "f1"} <= set(t["score"])
    assert c.post(f"/v1/jobs/{jid}/detect", headers=h["student"]).json()["status"] == "done"  # no second run


# ---------------------------------------------------------------- the twin ("world": "twin")


def _twin_db(api) -> Path:
    return Path(api["dir"]) / "api" / "jobs" / api["id"] / "run" / "twin" / "story.duckdb"


def test_twin_world_reads_the_twin(api):
    import duckdb
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    with duckdb.connect(str(_twin_db(api)), read_only=True) as con:
        n_twin = con.execute("SELECT count(*) FROM main.orders").fetchone()[0]
    p = c.get(f"/v1/jobs/{jid}/tables/orders?limit=3&world=twin", headers=h).json()
    assert p["total"] == n_twin and len(p["rows"]) == 3
    r = c.post(f"/v1/jobs/{jid}/query", json={"sql": "SELECT count(*) FROM orders", "world": "twin"}, headers=h)
    assert r.status_code == 200 and r.json()["rows"] == [[n_twin]]
    story = c.get(f"/v1/jobs/{jid}/tables/orders?limit=1", headers=h).json()  # default stays the story
    assert story["total"] == c.get(f"/v1/jobs/{jid}/tables/orders?limit=1&world=story", headers=h).json()["total"]
    assert c.get(f"/v1/jobs/{jid}/tables/orders?world=mars", headers=h).status_code == 422
    assert c.post(f"/v1/jobs/{jid}/query", json={"sql": "SELECT 1", "world": "mars"}, headers=h).status_code == 422
    assert c.get(f"/v1/jobs/{jid}/tables/orders?world=twin", headers=api["h"]["other"]).status_code == 404


def test_twin_is_built_lazily_for_older_jobs(api):
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    db = Path(api["dir"]) / "api" / "jobs" / jid / "analyst_twin.duckdb"
    assert db.exists()  # the pipeline builds it
    db.unlink()
    r = c.post(f"/v1/jobs/{jid}/query", json={"sql": "SELECT count(*) FROM customers", "world": "twin"}, headers=h)
    assert r.status_code == 200 and r.json()["rows"][0][0] > 0
    assert db.exists()


def test_twin_without_twin_files_is_404(api):
    from s2d.api import store
    st = store.new_job("student", "student", {"spec_yaml": SPEC}, "no twin")
    st.update(status="done", started=time.time(), finished=time.time())
    store.save_job(st)
    try:
        r = api["c"].get(f"/v1/jobs/{st['job_id']}/tables/orders?world=twin", headers=api["h"]["student"])
        assert r.status_code == 404 and r.json() == {"detail": "data not found"}
    finally:
        st.update(status="error", error="test")
        store.save_job(st)


def test_twin_query_cannot_reach_the_answer_key_or_files(api):
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    twin_db = _twin_db(api)
    parquets = sorted((twin_db.parent / "_truth").glob("*.parquet"))
    attempts = [
        "SELECT * FROM _truth.answer_key",
        "SELECT * FROM information_schema.tables WHERE table_schema = '_truth'",
        f"ATTACH '{twin_db}' AS s (READ_ONLY)",
        f"SELECT * FROM read_parquet('{twin_db.parent / '_truth' / '*.parquet'}')",
        "SELECT * FROM glob('*')",
        "SET enable_external_access = true",
        "COPY orders TO 'out_twin.csv'",
    ] + [f"SELECT * FROM '{p}'" for p in parquets]
    for q in attempts:
        r = c.post(f"/v1/jobs/{jid}/query", json={"sql": q, "world": "twin"}, headers=h)
        if r.status_code == 200:
            assert r.json()["rows"] == [], q
        else:
            assert r.status_code == 400, (q, r.text)
    assert not (Path.cwd() / "out_twin.csv").exists()
    tables = c.post(f"/v1/jobs/{jid}/query", headers=h, json={
        "sql": "SELECT DISTINCT table_schema FROM information_schema.tables", "world": "twin"}).json()["rows"]
    assert tables == [["main"]]


# ---------------------------------------------------------------- keys and Postgres DDL


def test_tables_have_keys(api):
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    tables = {t["name"]: t for t in c.get(f"/v1/jobs/{jid}/tables", headers=h).json()["tables"]}
    assert tables["orders"]["primary_key"] == ["order_id"]
    assert {"column": "customer_id", "references": {"table": "customers", "column": "customer_id"}} \
        in tables["orders"]["foreign_keys"]
    assert tables["inventory_daily"]["primary_key"] == ["product_id", "date"]
    assert tables["customers"]["foreign_keys"] == []
    from s2d.sim.pg import FOREIGN_KEYS
    n = sum(len(t["foreign_keys"]) for t in tables.values())
    assert n == sum(1 for ch, _, pa in FOREIGN_KEYS if ch in tables and pa in tables) and n > 0


def test_ddl_is_postgres_with_keys_and_runs(api):
    import duckdb
    c, h, jid = api["c"], api["h"]["student"], api["id"]
    r = c.get(f"/v1/jobs/{jid}/ddl", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    ddl = r.text
    assert 'CREATE TABLE "public"."orders" (' in ddl and '"order_date" DATE' in ddl
    assert 'PRIMARY KEY ("order_id")' in ddl and 'PRIMARY KEY ("product_id", "date")' in ddl
    assert ('CONSTRAINT "orders_customer_id_fkey" FOREIGN KEY ("customer_id") '
            'REFERENCES "public"."customers" ("customer_id")') in ddl
    assert "DOUBLE PRECISION" in ddl and "TEXT" in ddl and "VARCHAR" not in ddl and " DOUBLE," not in ddl
    # parents come before children: the script runs as is (DuckDB checks REFERENCES too)
    con = duckdb.connect()
    con.execute("CREATE SCHEMA public")
    con.execute(ddl)
    made = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    listed = {t["name"] for t in c.get(f"/v1/jobs/{jid}/tables", headers=h).json()["tables"]}
    assert made == listed
    assert c.get(f"/v1/jobs/{jid}/ddl", headers=api["h"]["other"]).status_code == 404


def test_pg_types():
    from s2d.sim.pg import pg_type
    assert [pg_type(t) for t in ("BIGINT", "INTEGER", "DOUBLE", "DECIMAL(10,2)", "VARCHAR", "DATE",
                                 "TIMESTAMP", "BOOLEAN", "BLOB")] == \
        ["BIGINT", "INTEGER", "DOUBLE PRECISION", "NUMERIC(10,2)", "TEXT", "DATE", "TIMESTAMP", "BOOLEAN", "TEXT"]


# ---------------------------------------------------------------- history


STORY = "V březnu 2026 jsme zdražili o 15 % a studenti začali odcházet. " * 5


def _story_job(owner="student"):
    from s2d.api import store
    params = {"company": "Pražírna Zrnko", "story": STORY, "spec_yaml": None, "difficulty": "hard",
              "seed": 7, "n_customers": 5000, "dirt": "low"}
    st = store.new_job(owner, "student", params, "Pražírna Zrnko")
    st.update(status="error", error="test")  # never runs
    store.save_job(st)
    return st["job_id"]


def test_jobs_scope_all(api):
    c, h, jid = api["c"], api["h"], api["id"]
    assert c.get("/v1/jobs?scope=all", headers=h["student"]).json() == {"detail": "teacher or admin only"}
    assert c.get("/v1/jobs?scope=all", headers=h["student"]).status_code == 403
    assert jid not in {j["job_id"] for j in c.get("/v1/jobs", headers=h["teacher"]).json()["jobs"]}
    assert jid not in {j["job_id"] for j in c.get("/v1/jobs?scope=mine", headers=h["teacher"]).json()["jobs"]}
    for role in ("teacher", "admin"):
        every = c.get("/v1/jobs?scope=all", headers=h[role]).json()["jobs"]
        assert jid in {j["job_id"] for j in every}
        assert [j["created"] for j in every] == sorted((j["created"] for j in every), reverse=True)
    assert jid in {j["job_id"] for j in c.get("/v1/jobs", headers=h["admin"]).json()["jobs"]}  # as before
    assert c.get("/v1/jobs?scope=everything", headers=h["teacher"]).status_code == 422


def test_jobs_scope_all_in_public_mode(api, monkeypatch):
    monkeypatch.setenv("API_PUBLIC_ROLE", "teacher")
    every = api["c"].get("/v1/jobs?scope=all").json()["jobs"]
    assert api["id"] in {j["job_id"] for j in every}  # a job made with a token


def test_story_preview_and_input(api):
    c, h = api["c"], api["h"]
    sid = _story_job()
    rows = {j["job_id"]: j for j in c.get("/v1/jobs", headers=h["student"]).json()["jobs"]}
    assert rows[sid]["story_preview"] == STORY.strip()[:120] and len(rows[sid]["story_preview"]) == 120
    assert rows[api["id"]]["story_preview"] is None  # a spec job
    assert c.get(f"/v1/jobs/{sid}/input", headers=h["student"]).json() == {
        "company": "Pražírna Zrnko", "story": STORY, "difficulty": "hard", "seed": 7, "n_customers": 5000,
        "dirt": "low", "spec_given": False}
    spec = c.get(f"/v1/jobs/{api['id']}/input", headers=h["student"]).json()
    assert spec == {"company": None, "story": None, "difficulty": None, "seed": 3, "n_customers": 1500,
                    "dirt": None, "spec_given": True}
    assert c.get(f"/v1/jobs/{sid}/input", headers=h["other"]).status_code == 404
    assert c.get(f"/v1/jobs/{sid}/input", headers=h["teacher"]).status_code == 200


# ---------------------------------------------------------------- stats


STATS_KEYS = {"jobs_total", "jobs_done", "jobs_today", "running", "waiting", "median_run_s",
              "events_confirmed_pct", "twin_false_pct", "customers_simulated", "rows_generated",
              "recent", "timeline"}


def test_stats_needs_no_token_and_has_no_owners_or_stories(api, monkeypatch):
    from s2d.api import main
    monkeypatch.setattr(main, "STATS_TTL_S", 0.0)
    _story_job()
    r = api["c"].get("/v1/stats")
    assert r.status_code == 200
    j = r.json()
    assert set(j) == STATS_KEYS
    assert j["jobs_total"] >= j["jobs_done"] >= 1 and j["jobs_today"] >= 1 and j["waiting"] >= 0
    assert j["median_run_s"] > 0
    assert 0 <= j["events_confirmed_pct"] <= 100 and 0 <= j["twin_false_pct"] <= 100
    assert j["customers_simulated"] >= 1500 and j["rows_generated"] > j["customers_simulated"]
    row = next(x for x in j["recent"] if x["job_id"] == api["id"])
    assert set(row) == {"job_id", "title", "finished", "elapsed_s", "summary"}
    assert row["summary"]["story"].count("/") == 1 and row["title"]
    assert len(j["recent"]) <= 20
    assert len(j["timeline"]) == 24 and set(j["timeline"][0]) == {"hour", "jobs", "median_run_s"}
    assert j["timeline"] == sorted(j["timeline"], key=lambda b: b["hour"])
    assert sum(b["jobs"] for b in j["timeline"]) >= 1
    assert all(b["median_run_s"] is None for b in j["timeline"] if b["jobs"] == 0)
    text = r.text
    assert "student" not in text and "owner" not in text and "studenti" not in text  # no owners, no stories


def test_stats_are_the_verification_rows(api, monkeypatch):
    from s2d.api import main
    monkeypatch.setattr(main, "STATS_TTL_S", 0.0)
    res = api["c"].get(f"/v1/jobs/{api['id']}/result", headers=api["h"]["student"]).json()
    f = main._facts(api["id"])
    tested = [r for r in res["verification"] if r["status"] != "not_testable"]
    assert f["tested"] == len(tested) and f["confirmed"] == sum(r["confirmed"] for r in tested)
    assert f["twin_false"] == sum(bool(r["twin_confirmed"]) for r in tested)
    assert f["customers"] == res["rows"]["customers"] and f["rows"] == sum(res["rows"].values())


def test_stats_are_cached(api, monkeypatch):
    from s2d.api import main
    monkeypatch.setattr(main, "STATS_TTL_S", 0.0)
    first = api["c"].get("/v1/stats").json()
    monkeypatch.setattr(main, "STATS_TTL_S", 60.0)
    _story_job()
    assert api["c"].get("/v1/stats").json()["jobs_total"] == first["jobs_total"]  # cached
    monkeypatch.setattr(main, "STATS_TTL_S", 0.0)
    assert api["c"].get("/v1/stats").json()["jobs_total"] == first["jobs_total"] + 1


def test_stats_running_job(api, monkeypatch):
    from s2d.api import main, store
    st = store.new_job("student", "student", {"spec_yaml": SPEC}, "running")
    st.update(status="running", started=time.time() - 10)
    st["steps"][1]["started"] = time.time() - 5
    store.save_job(st)
    monkeypatch.setattr(main.worker, "running", ("generate", st["job_id"]))
    try:
        r = main.compute_stats()["running"]
        assert r["job_id"] == st["job_id"] and r["step"] == "kalibrace a simulace" and r["step_index"] == 2
        assert 0 < r["progress"] < 1 and r["eta_s"] > 0
        monkeypatch.setattr(main.worker, "running", None)
        assert main.compute_stats()["running"] is None
    finally:
        st.update(status="error", error="test")
        store.save_job(st)


# ---------------------------------------------------------------- system load


def test_system_needs_no_token_and_the_buffer_is_bounded(api):
    from s2d.api import main, sysmon
    c = api["c"]
    main.monitor.sample()
    j = c.get("/v1/system").json()
    assert {"cores", "mem_total_gb", "period_s", "gpu", "step", "customers_now", "waiting", "samples"} <= set(j)
    assert set(j["samples"][-1]) == {"t", "cpu", "mem_gb", "load", "vram_gb", "progress", "customers"}
    for _ in range(sysmon.KEEP + 5):
        main.monitor.sample()
    assert len(c.get("/v1/system").json()["samples"]) == sysmon.KEEP


def test_sysmon_cpu_is_the_delta_between_samples(tmp_path):
    from s2d.api.sysmon import Monitor
    (tmp_path / "meminfo").write_text("MemTotal: 1000000 kB\nMemAvailable: 250000 kB\n")
    (tmp_path / "loadavg").write_text("1.50 1.00 0.50 1/100 123\n")
    (tmp_path / "stat").write_text("cpu 100 0 100 700 100 0 0 0\n")  # busy 200, total 1000
    m = Monitor(lambda: {"progress": 0.5, "customers": 7}, proc=tmp_path, gpu=lambda: {"loaded": True, "vram_gb": 9.5})
    (tmp_path / "stat").write_text("cpu 200 0 200 800 100 0 0 0\n")  # +200 busy of +300 total
    s = m.sample(now=100.0)
    assert (s["cpu"], s["mem_gb"], s["load"], s["vram_gb"], s["progress"], s["customers"]) == (66.7, 0.77, 1.5, 9.5, 0.5, 7)


def test_sysmon_without_proc_or_gpu_gives_none(tmp_path):
    from s2d.api.sysmon import Monitor
    s = Monitor(proc=tmp_path / "nope", gpu=lambda: None).sample(now=1.0)
    assert (s["cpu"], s["mem_gb"], s["load"], s["vram_gb"], s["progress"], s["customers"]) == (None, None, None, None, None, 0)
