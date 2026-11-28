"""Rev story's input is data: which finished job do uploaded tables come from?

The browser reads the download ZIP (or its CSVs) itself and sends only a fingerprint: the row
counts of customers and orders and a sample of customers (id and e-mail, spread over the table).
A job matches when its analyst tables have the same counts and every sampled customer. The same
spec and seed give the same data, so several jobs can match; all are returned, newest first.
The counts of each job are computed once from analyst.duckdb and kept in fingerprint.json.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from . import sandbox, store

SAMPLE_MAX = 64


def counts(job_dir: Path) -> dict | None:
    """{"customers": n, "orders": n} of a finished job's analyst tables (cached), None without them."""
    cached = store.read_json(job_dir / "fingerprint.json")
    if cached:
        return cached
    db = job_dir / "analyst.duckdb"
    if not db.exists():
        return None
    try:
        with sandbox.connect(db) as con:
            out = {"customers": con.execute("SELECT count(*) FROM customers").fetchone()[0],
                   "orders": con.execute("SELECT count(*) FROM orders").fetchone()[0]}
    except duckdb.Error:
        return None
    store.write_json(job_dir / "fingerprint.json", out)
    return out


def same_customers(db: Path, sample: list[tuple[int, str]]) -> bool:
    """Every sampled (customer_id, email) is a row of the job's customers."""
    values = ", ".join("(?, ?)" for _ in sample)
    args = [x for pair in sample for x in pair]
    with sandbox.connect(db) as con:
        n = con.execute(f"SELECT count(*) FROM customers WHERE (customer_id, email) IN (VALUES {values})",
                        args).fetchone()[0]
    return n == len(sample)


def find(jobs: list[dict], customers: int, orders: int, sample: list[tuple[int, str]]) -> list[dict]:
    """The finished jobs among `jobs` whose data are the uploaded data, newest first."""
    out = []
    for st in sorted(jobs, key=lambda s: s["created"], reverse=True):
        if st["status"] != "done":
            continue
        jd = store.job_dir(st["job_id"])
        c = counts(jd)
        if c != {"customers": customers, "orders": orders}:
            continue
        try:
            if same_customers(jd / "analyst.duckdb", sample):
                out.append(st)
        except duckdb.Error:
            continue
    return out
