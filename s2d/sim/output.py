"""Write a simulated world to Parquet files and one DuckDB database.

    out/customers.parquet ...           analyst tables (clean)
    out/_truth/answer_key.parquet ...   hidden truth
    out/story.duckdb                    main schema = analyst, _truth schema = truth
    out/export/*.parquet                the dirty copy (--dirt low|medium|high, s2d/sim/dirt.py)
    out/export.duckdb                   the same, main = dirty tables, _truth.dirt_log
"""

from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DATE_COLUMNS = {"signup_date", "order_date", "valid_from", "valid_to", "start_date", "date", "churn_date",
                "shipped_date", "opened_date", "started_at", "cancelled_at", "promised_date", "delivered_date", "review_date"}


def _to_arrow(df: pd.DataFrame) -> pa.Table:
    table = pa.Table.from_pandas(df, preserve_index=False)
    # Store calendar days as DATE, not as timestamps at midnight.
    for i, name in enumerate(table.column_names):
        if name in DATE_COLUMNS and not pa.types.is_date32(table.schema.field(i).type):
            table = table.set_column(i, name, table.column(name).cast(pa.date32()))
    # Drop pandas' metadata blob so files only depend on the data.
    return table.replace_schema_metadata(None)


def _write_db(path: Path, jobs) -> None:
    path.unlink(missing_ok=True)
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA _truth")
        for schema, name, _, p in jobs:
            con.execute(f"CREATE TABLE {schema}.{name} AS SELECT * FROM read_parquet(?)", [str(p)])


def export_tables(world, level: str) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """The tables to export: the dirty copy for a level other than 'none' (seeded from the
    world's `dirt` stream, so the same seed gives the same dirt)."""
    from .dirt import dirty_copy
    from .rng import make_streams
    return dirty_copy(world.tables, level, make_streams(world.seed)["dirt"])


def write_world(world, out_dir: str | Path, dirt: str = "none") -> Path:
    out = Path(out_dir)
    (out / "_truth").mkdir(parents=True, exist_ok=True)

    # (duckdb schema, table name, dataframe, parquet path)
    jobs = [("main", name, df, out / f"{name}.parquet") for name, df in world.tables.items()]
    jobs += [("_truth", name, df, out / "_truth" / f"{name}.parquet") for name, df in world.truth.items()]

    for _, _, df, path in jobs:
        pq.write_table(_to_arrow(df), path)

    db_path = out / "story.duckdb"
    _write_db(db_path, jobs)

    if dirt != "none":
        tables, log = export_tables(world, dirt)
        (out / "export").mkdir(exist_ok=True)
        ex = [("main", name, df, out / "export" / f"{name}.parquet") for name, df in tables.items()]
        ex.append(("_truth", "dirt_log", log, out / "export" / "_dirt_log.parquet"))
        for _, _, df, path in ex:
            pq.write_table(_to_arrow(df), path)
        _write_db(out / "export.duckdb", ex + [j for j in jobs if j[0] == "_truth"])
    return db_path
