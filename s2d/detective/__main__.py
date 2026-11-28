"""python -m s2d.detective run data/a/ --out data/a/detective.json [--no-llm]"""

import argparse
import sys

import pandas as pd

from . import run, save


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m s2d.detective")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="scan a run directory (analyst tables only)")
    r.add_argument("run_dir")
    r.add_argument("--out")
    r.add_argument("--no-llm", action="store_true", help="template narrative, no LLM call")
    args = p.parse_args(argv)

    res = run(args.run_dir, narrate=not args.no_llm, on_status=lambda m: print(f"  {m}", file=sys.stderr))
    t = res["timing"]
    st = res["scan_stats"]
    print(f"{res['n_series']} series ({st['scanned_total']} scanned, {st['tests_total']} DiD tests), "
          f"{len(res['candidates'])} candidates {res['status_counts']}")
    print(f"kpis {t['kpis_s']}s, scan {t['scan_s']}s, total {t['total_s']}s")
    if res["events"]:
        cols = ["id", "metric", "segment", "start_date", "end_date", "direction", "magnitude_pct",
                "lag_days", "caused_by", "kind", "confidence"]
        print(pd.DataFrame(res["events"])[cols].to_string(index=False))
    if "narration" in res:
        words = {n["candidate_id"]: n for n in res["narration"]["events"]}
        print(f"\n[{res['narration']['source']}]")
        for e in res["events"]:
            w = words.get(e["id"], {})
            print(f"{e['id']}  {w.get('observation_cs', '')}\n      hypotéza: {w.get('hypothesis_cs', '')}")
        print(f"\n{res['narration']['narrative_cs']}")
    if args.out:
        save(res, args.out)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
