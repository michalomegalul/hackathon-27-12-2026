"""Write a simulated world to Parquet files and one DuckDB database.

    out/customers.parquet ...           analyst tables
    out/_truth/answer_key.parquet ...   hidden truth
    out/story.duckdb                    main schema = analyst, _truth schema = truth
"""

from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DATE_COLUMNS = {"signup_date", "order_date", "valid_from", "valid_to", "start_date", "date", "churn_date",
                "shipped_date", "opened_date", "promised_date", "delivered_date", "review_date"}


def _to_arrow(df: pd.DataFrame) -> pa.Table:
    table = pa.Table.from_pandas(df, preserve_index=False)
    # Store calendar days as DATE, not as timestamps at midnight.
    for i, name in enumerate(table.column_names):
        if name in DATE_COLUMNS and not pa.types.is_date32(table.schema.field(i).type):
            table = table.set_column(i, name, table.column(name).cast(pa.date32()))
    # Drop pandas' metadata blob so files only depend on the data.
    return table.replace_schema_metadata(None)


def write_world(world, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    (out / "_truth").mkdir(parents=True, exist_ok=True)

    # (duckdb schema, table name, dataframe, parquet path)
    jobs = [("main", name, df, out / f"{name}.parquet") for name, df in world.tables.items()]
    jobs += [("_truth", name, df, out / "_truth" / f"{name}.parquet") for name, df in world.truth.items()]

    for _, _, df, path in jobs:
        pq.write_table(_to_arrow(df), path)

    db_path = out / "story.duckdb"
    db_path.unlink(missing_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE SCHEMA _truth")
        for schema, name, _, path in jobs:
            con.execute(f"CREATE TABLE {schema}.{name} AS SELECT * FROM read_parquet(?)", [str(path)])
    return db_path
