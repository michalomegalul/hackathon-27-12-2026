"""Command line entry point.

    python -m s2d.sim run examples/a.yaml --seed 42 --out data/a/
    python -m s2d.sim run examples/a.yaml --out data/a/ --check   # + no-story twin and churn report
    python -m s2d.sim run examples/a.yaml --out data/a_nostory/ --no-story
    python -m s2d.sim run examples/b.yaml --out data/b/ --dirt medium --pg postgresql://u:pw@host/db
    python -m s2d.sim pg data/b/ --pg postgresql://u:pw@host/db     # export an existing run

Before simulating, s2d.calibrate scales up any effect that would be below its
difficulty's recoverability target (--no-calibrate to skip). The result is in
_truth.calibration.
"""

import argparse
import sys
import time
from pathlib import Path

from s2d.spec import load_spec

from . import simulate, without_story
from .output import write_world
from .report import churn_report, format_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m s2d.sim")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="simulate a story spec and write Parquet + DuckDB")
    run.add_argument("spec")
    run.add_argument("--seed", type=int, default=None, help="overrides meta.seed")
    run.add_argument("--out", required=True)
    run.add_argument("--n-customers", type=int, default=None, help="overrides entities.customers.n")
    run.add_argument("--no-story", action="store_true", help="drop all events (the no-story twin)")
    run.add_argument("--strict", action="store_true", help="fail on events that are not implemented yet")
    run.add_argument("--check", action="store_true", help="also run the no-story twin and print target vs realized")
    run.add_argument("--no-calibrate", action="store_true", help="skip the recoverability gate (s2d.calibrate)")
    run.add_argument("--dirt", choices=["none", "low", "medium", "high"], default=None,
                     help="messiness of the export copy (out/export*); default from the spec's noise.messiness")
    run.add_argument("--texts", metavar="POOL", help="text pool JSON for reviews.text "
                     "(default: data/text_pools/<company>.json or generic.json if present; 'none' to skip)")
    run.add_argument("--pg", metavar="URL", help="also export to Postgres (with PK/FK); the dirty copy if --dirt")
    run.add_argument("--pg-schema", default="public", help="Postgres schema for the analyst tables")
    pgp = sub.add_parser("pg", help="export an existing run to Postgres")
    pgp.add_argument("run_dir")
    pgp.add_argument("--pg", metavar="URL", required=True)
    pgp.add_argument("--pg-schema", default="public")
    pgp.add_argument("--clean", action="store_true", help="export story.duckdb even if a dirty export.duckdb exists")
    args = parser.parse_args(argv)

    if args.command == "pg":
        run_dir = Path(args.run_dir)
        db = run_dir / "story.duckdb" if args.clean or not (run_dir / "export.duckdb").exists() else run_dir / "export.duckdb"
        return _pg(db, args.pg, args.pg_schema)

    spec = load_spec(args.spec)
    if args.n_customers:
        spec.entities.customers.n = args.n_customers
    if args.no_story:
        spec = without_story(spec)

    t0 = time.perf_counter()
    table = None
    if spec.events and not args.no_calibrate:
        from s2d.calibrate import calibrate, format_table
        spec, table = calibrate(spec, seed=args.seed)
        print(format_table(table), file=sys.stderr)
    t_cal = time.perf_counter() - t0
    world = simulate(spec, seed=args.seed, strict=args.strict)
    if table is not None:
        world.truth["calibration"] = table
    if args.texts != "none":
        from s2d.texts import fill_reviews, find_pool, load_pool
        pool = Path(args.texts) if args.texts else find_pool(spec)
        if pool is not None:
            n = fill_reviews(world.tables, load_pool(pool), world.seed)
            print(f"reviews: {n:,} texts from {pool}", file=sys.stderr)
    t_sim = time.perf_counter() - t0 - t_cal
    from .dirt import FROM_SPEC
    dirt = args.dirt or FROM_SPEC[spec.noise.messiness.value]
    db = write_world(world, args.out, dirt=dirt)
    t_all = time.perf_counter() - t0

    for reason in world.story.skipped:
        print(f"WARNING skipped {reason}", file=sys.stderr)
    print(f"seed={world.seed}  days={spec.meta.days}  customers={world.population.n}")
    for name, df in world.tables.items():
        print(f"  {name:<15} {len(df):>9,} rows")
    print(f"calibrated in {t_cal:.1f}s, simulated in {t_sim:.1f}s, written in {t_all - t_sim - t_cal:.1f}s -> {db}"
          + (f" (+ export copy, dirt {dirt})" if dirt != "none" else ""))

    if args.pg:
        _pg(Path(args.out) / ("export.duckdb" if dirt != "none" else "story.duckdb"), args.pg, args.pg_schema)

    if args.check:
        twin = simulate(without_story(spec), seed=args.seed)
        print(format_report(churn_report(world, twin)))
    return 0


def _pg(db: Path, url: str, schema: str) -> int:
    from .pg import export
    t0 = time.perf_counter()
    rows = export(db, url, schema)
    print(f"postgres: {len(rows)} tables from {db.name} -> schema {schema} (+ _truth) "
          f"in {time.perf_counter() - t0:.1f}s, with primary and foreign keys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
