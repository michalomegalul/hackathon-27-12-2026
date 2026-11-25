"""Postgres export. Needs a database: S2D_TEST_PG=<libpq URL or 'host=... dbname=...'>
(skipped otherwise). The tables in that database's public and _truth schemas are replaced."""

import os

import duckdb
import pytest

from s2d.sim import simulate
from s2d.sim.output import write_world
from s2d.sim.pg import FOREIGN_KEYS, PRIMARY_KEYS, export
from s2d.spec import load_spec

URL = os.environ.get("S2D_TEST_PG")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not URL, reason="set S2D_TEST_PG to a Postgres URL")]


def test_export_with_keys(tmp_path):
    spec = load_spec("examples/a.yaml")
    spec.entities.customers.n = 2000
    write_world(simulate(spec, seed=2), tmp_path, dirt="high")
    rows = export(tmp_path / "export.duckdb", URL)
    export(tmp_path / "export.duckdb", URL)  # again: replaces, does not fail on existing tables
    con = duckdb.connect()
    con.execute("LOAD postgres")
    con.execute(f"ATTACH '{URL}' AS pg (TYPE postgres, READ_ONLY)")
    for name, n in rows.items():
        schema, table = name.split(".")
        assert con.execute(f'SELECT count(*) FROM pg."{schema}"."{table}"').fetchone()[0] == n, name
    fks = con.execute("SELECT * FROM postgres_query('pg', $$SELECT count(*) FROM pg_constraint "
                      "WHERE contype = 'f' AND connamespace = 'public'::regnamespace$$)").fetchone()[0]
    pks = con.execute("SELECT * FROM postgres_query('pg', $$SELECT count(*) FROM pg_constraint "
                      "WHERE contype = 'p' AND connamespace = 'public'::regnamespace$$)").fetchone()[0]
    assert fks == len(FOREIGN_KEYS) and pks == len(PRIMARY_KEYS)
    assert "_truth.answer_key" in rows and "_truth.dirt_log" in rows
