"""Command line entry point.

    python -m s2d.sim run examples/a.yaml --seed 42 --out data/a/
    python -m s2d.sim run examples/a.yaml --out data/a/ --check   # + no-story twin and churn report
    python -m s2d.sim run examples/a.yaml --out data/a_nostory/ --no-story
"""

import argparse
import sys
import time

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
    args = parser.parse_args(argv)

    spec = load_spec(args.spec)
    if args.n_customers:
        spec.entities.customers.n = args.n_customers
    if args.no_story:
        spec = without_story(spec)

    t0 = time.perf_counter()
    world = simulate(spec, seed=args.seed, strict=args.strict)
    t_sim = time.perf_counter() - t0
    db = write_world(world, args.out)
    t_all = time.perf_counter() - t0

    for reason in world.story.skipped:
        print(f"WARNING skipped {reason}", file=sys.stderr)
    print(f"seed={world.seed}  days={spec.meta.days}  customers={world.population.n}")
    for name, df in world.tables.items():
        print(f"  {name:<15} {len(df):>9,} rows")
    print(f"simulated in {t_sim:.1f}s, written in {t_all - t_sim:.1f}s -> {db}")

    if args.check:
        twin = simulate(without_story(spec), seed=args.seed)
        print(format_report(churn_report(world, twin)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
