"""The blind detective: analyst tables in, candidate events and a Czech story out.

It reads only schema `main` of a run (see data.py). Thresholds are global and
listed at the top of scan.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from . import kpis as kpis_mod
from . import scan as scan_mod
from .data import open_analyst


def run(run_dir: str | Path, *, narrate: bool = True, on_status=None) -> dict:
    say = on_status or (lambda _m: None)
    t0 = time.perf_counter()
    con = open_analyst(run_dir)
    say("KPI series")
    ks = kpis_mod.build(con)
    t1 = time.perf_counter()
    say(f"{len(ks.series)} series, scanning")
    cands = scan_mod.scan(ks)
    t2 = time.perf_counter()
    rows = [c.row() for c in cands]
    reported = [r for r in rows if r["status"] == "reported"]
    result = {
        "run_dir": str(run_dir),
        "data_start": str(ks.dates[0].date()), "data_end": str(ks.dates[-1].date()),
        "days": len(ks.dates),
        "kpis": sorted({k for k, _ in ks.series}),
        "n_series": len(ks.series),
        "notes": ks.notes,
        "candidates": rows,
        "events": reported,
        "status_counts": pd.Series([r["status"] for r in rows], dtype=object).value_counts().to_dict(),
        "timing": {"kpis_s": round(t1 - t0, 2), "scan_s": round(t2 - t1, 2)},
    }
    if narrate:
        from .narrate import narrate as narrate_fn
        say("narrative")
        result["narration"] = narrate_fn(result, on_status=say)
        accepted = {e["candidate_id"] for e in result["narration"]["events"] if e["accept"]}
        result["events"] = [r for r in reported if r["id"] in accepted]
    result["timing"]["total_s"] = round(time.perf_counter() - t0, 2)
    return result


def save(result: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def series_frame(run_dir: str | Path, series: list[str]) -> pd.DataFrame:
    """Daily values of the named series ("kpi|segment") for the UI charts."""
    ks = kpis_mod.build(open_analyst(run_dir))
    out = {}
    for name in series:
        kpi, seg = name.split("|", 1)
        s = scan_mod._union_series(ks, kpi, seg)
        if s is not None:
            out[name] = s
    return pd.DataFrame(out)
