"""Postgres export: the tables of a run, with primary and foreign keys.

    python -m s2d.sim run examples/b.yaml --out data/b --pg postgresql://user:pw@host:5432/story2data
    python -m s2d.sim pg data/b --pg postgresql://...           # an existing run

Uses DuckDB's postgres extension (ATTACH ... TYPE postgres, binary COPY), so there is no
extra Python dependency. The analyst tables go to `--pg-schema` (default public), the
hidden ones to `_truth`. Existing tables of the same names are dropped first. With a
dirt level, the dirty export copy is what goes to Postgres (its keys are still valid,
DECISIONS 75).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# table -> primary key
PRIMARY_KEYS = {
    "customers": "customer_id", "stores": "store_id", "suppliers": "supplier_id", "products": "product_id",
    "product_prices": "price_id", "orders": "order_id", "order_items": "order_item_id",
    "payments": "payment_id", "deliveries": "delivery_id", "reviews": "review_id", "tickets": "ticket_id",
    "subscriptions": "subscription_id", "shipments_in": "shipment_line_id",
    "inventory_daily": ("product_id", "date"),
}
# (child table, column, parent table)
FOREIGN_KEYS = [
    ("products", "supplier_id", "suppliers"),
    ("product_prices", "product_id", "products"),
    ("orders", "customer_id", "customers"),
    ("orders", "store_id", "stores"),
    ("orders", "subscription_id", "subscriptions"),
    ("order_items", "order_id", "orders"),
    ("order_items", "product_id", "products"),
    ("payments", "order_id", "orders"),
    ("deliveries", "order_id", "orders"),
    ("reviews", "order_id", "orders"),
    ("reviews", "customer_id", "customers"),
    ("reviews", "product_id", "products"),
    ("tickets", "order_id", "orders"),
    ("tickets", "customer_id", "customers"),
    ("tickets", "product_id", "products"),
    ("subscriptions", "customer_id", "customers"),
    ("shipments_in", "supplier_id", "suppliers"),
    ("shipments_in", "product_id", "products"),
    ("inventory_daily", "product_id", "products"),
]


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def export(db_path: str | Path, url: str, schema: str = "public", truth: bool = True) -> dict[str, int]:
    """Copy every table of a run's DuckDB file to Postgres and add the keys. Returns rows per table."""
    con = duckdb.connect()
    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")
    con.execute(f"ATTACH '{Path(db_path)}' AS src (READ_ONLY)")
    con.execute(f"ATTACH '{url.replace(chr(39), chr(39) * 2)}' AS pg (TYPE postgres)")

    def pg(sql: str) -> None:
        con.execute("CALL postgres_execute('pg', ?)", [sql])

    groups = {schema: "main"} | ({"_truth": "_truth"} if truth else {})
    rows = {}
    for dst, src in groups.items():
        names = [r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'src' AND schema_name = ? "
            "ORDER BY table_name", [src]).fetchall()]
        pg(f"CREATE SCHEMA IF NOT EXISTS {_q(dst)}")
        for name in names:
            pg(f"DROP TABLE IF EXISTS {_q(dst)}.{_q(name)} CASCADE")
        con.execute("CALL postgres_clear_cache()")
        for name in names:
            con.execute(f"CREATE TABLE pg.{_q(dst)}.{_q(name)} AS SELECT * FROM src.{_q(src)}.{_q(name)}")
            rows[f"{dst}.{name}"] = con.execute(f"SELECT count(*) FROM src.{_q(src)}.{_q(name)}").fetchone()[0]
        if src != "main":
            continue
        for name in names:
            pk = PRIMARY_KEYS.get(name)
            if pk:
                cols = ", ".join(_q(c) for c in ((pk,) if isinstance(pk, str) else pk))
                pg(f"ALTER TABLE {_q(dst)}.{_q(name)} ADD PRIMARY KEY ({cols})")
        for child, col, parent in FOREIGN_KEYS:
            if child in names and parent in names:
                pg(f"ALTER TABLE {_q(dst)}.{_q(child)} ADD CONSTRAINT {_q(f'{child}_{col}_fkey')} "
                   f"FOREIGN KEY ({_q(col)}) REFERENCES {_q(dst)}.{_q(parent)} ({_q(PRIMARY_KEYS[parent])})")
    con.close()
    return rows
