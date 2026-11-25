"""Load the analyst tables, and nothing else.

The source database is attached read-only, every table of schema `main` is
copied into a fresh in-memory connection, and the source is detached again. The
detective only ever holds that in-memory connection, so the hidden schema, the
spec and the seed are out of reach. tests/test_detective.py checks that no file
in this package names the hidden schema.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def open_analyst(run_dir: str | Path) -> duckdb.DuckDBPyConnection:
    path = Path(run_dir)
    db = path / "story.duckdb" if path.is_dir() else path
    con = duckdb.connect(":memory:")
    con.execute("ATTACH ? AS src (READ_ONLY)", [str(db)])
    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_catalog = 'src' AND table_schema = 'main'").fetchall()]
    for t in tables:
        con.execute(f'CREATE TABLE main."{t}" AS SELECT * FROM src.main."{t}"')
    con.execute("DETACH src")
    return con


def tables(con: duckdb.DuckDBPyConnection) -> dict[str, set[str]]:
    """{table: {columns}} for what this run has."""
    out: dict[str, set[str]] = {}
    for t, c in con.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = 'main'").fetchall():
        out.setdefault(t, set()).add(c)
    return out
