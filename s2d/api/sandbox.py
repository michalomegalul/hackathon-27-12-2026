"""The analyst database and the sandboxed query.

`build_analyst` copies only schema `main` of a run's story.duckdb into a new file, so the
answer key (`_truth`) is not in it at all. Every user query opens that file read-only with
external access off (no read_parquet / read_csv / glob / ATTACH / COPY, no extensions) and
the configuration locked, so SQL cannot turn it back on. At most MAX_ROWS rows; a timer
interrupts a query after TIMEOUT_S.
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import math
import threading
import time
import uuid
from pathlib import Path

import duckdb

MAX_ROWS = 1000
TIMEOUT_S = 20.0
CONFIG = {
    "enable_external_access": False,
    "autoload_known_extensions": False,
    "autoinstall_known_extensions": False,
    "memory_limit": "2GB",
    "threads": 2,
    "lock_configuration": True,  # last: nothing after it may change the configuration
}


class QueryTimeout(Exception):
    pass


class QueryError(Exception):
    pass


def build_analyst(story_db: Path, out: Path) -> Path:
    tmp = out.with_name(out.name + ".tmp")
    tmp.unlink(missing_ok=True)
    with duckdb.connect(str(tmp)) as con:
        con.execute("ATTACH ? AS src (READ_ONLY)", [str(story_db)])
        names = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog = 'src' AND table_schema = 'main' ORDER BY table_name").fetchall()]
        for t in names:
            con.execute(f'CREATE TABLE main."{t}" AS SELECT * FROM src.main."{t}"')
        con.execute("DETACH src")
    tmp.replace(out)
    return out


def connect(db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db), read_only=True, config=dict(CONFIG))


def jsonable(v):
    if v is None:
        return None
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    return v


def _columns(desc) -> list[dict]:
    return [{"name": d[0], "type": str(d[1])} for d in desc or []]


def tables(db: Path) -> list[dict]:
    with connect(db) as con:
        cols = con.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                           "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position").fetchall()
        out: dict[str, dict] = {}
        for t, c, typ in cols:
            out.setdefault(t, {"name": t, "rows": 0, "columns": []})["columns"].append({"name": c, "type": typ})
        for t in out.values():
            t["rows"] = con.execute(f'SELECT count(*) FROM main."{t["name"]}"').fetchone()[0]
    return list(out.values())


def page(db: Path, name: str, limit: int, offset: int) -> dict | None:
    with connect(db) as con:
        known = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}
        if name not in known:
            return None
        total = con.execute(f'SELECT count(*) FROM main."{name}"').fetchone()[0]
        cur = con.execute(f'SELECT * FROM main."{name}" LIMIT ? OFFSET ?', [limit, offset])
        rows = [[jsonable(v) for v in r] for r in cur.fetchall()]
        return {"name": name, "total": total, "limit": limit, "offset": offset,
                "columns": _columns(cur.description), "rows": rows}


def query(db: Path, sql: str, max_rows: int = MAX_ROWS, timeout_s: float = TIMEOUT_S) -> dict:
    t0 = time.perf_counter()
    con = connect(db)
    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    try:
        cur = con.execute(sql)
        if cur.description is None:
            rows, cols = [], []
        else:
            cols = _columns(cur.description)
            rows = cur.fetchmany(max_rows + 1)
    except duckdb.InterruptException as e:
        raise QueryTimeout(f"query timed out after {timeout_s:g} s") from e
    except duckdb.Error as e:
        if time.perf_counter() - t0 >= timeout_s:
            raise QueryTimeout(f"query timed out after {timeout_s:g} s") from e
        raise QueryError(str(e)) from e
    finally:
        timer.cancel()
        con.close()
    return {"columns": cols, "rows": [[jsonable(v) for v in r] for r in rows[:max_rows]],
            "truncated": len(rows) > max_rows, "seconds": round(time.perf_counter() - t0, 3)}
