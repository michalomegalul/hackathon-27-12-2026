"""Scorer: detective events vs the answer key. This module may read _truth.

    python -m s2d.score data/a/ --twin data/a_twin/            # scorecard + controls
    python -m s2d.score sweep examples/a.yaml --seeds 5          # seed sweep, story and twin
    python -m s2d.score curve examples/a.yaml --out docs/detection_curve.png

Pair score  s = gate(metric, direction) x (0.4 timing + 0.4 segment Jaccard + 0.2 magnitude)
  timing    = max(0, 1 - |pred.start - (true.start + lag)| / tau), tau 7 (shift) or 2 (spike)
  segment   = Jaccard over key=value pairs ('category=a,b' is two pairs)
  magnitude = max(0, 1 - |log(pred/true)| / log 2)
Hungarian matching; a pair counts when s >= 0.5. Answer-key rows with
simulated = false are left out. Reported decoys are false positives.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml
from scipy.optimize import linear_sum_assignment

MATCH = 0.5
TAU = {"shift": 7, "spike": 2, "stockout": 2}
W_TIME, W_SEG, W_MAG = 0.4, 0.4, 0.2
LAG_TOLERANCE = 7


def load_truth(run_dir: str | Path) -> dict:
    db = Path(run_dir) / "story.duckdb"
    with duckdb.connect(str(db), read_only=True) as con:
        key = con.execute("SELECT * FROM _truth.answer_key").df()
        decoys = con.execute("SELECT * FROM _truth.decoys").df()
        lo, hi = con.execute("SELECT min(order_date), max(order_date) FROM main.orders").fetchone()
    key["start_date"] = pd.to_datetime(key["start_date"])
    decoys["date"] = pd.to_datetime(decoys["date"])
    return {"key": key, "scored": key[key["simulated"]].reset_index(drop=True), "decoys": decoys,
            "start": pd.Timestamp(lo), "end": pd.Timestamp(hi)}


def seg_pairs(seg) -> set[str]:
    if not isinstance(seg, str):
        return set()
    out = set()
    for part in filter(None, seg.split(";")):
        k, v = part.split("=", 1)
        out |= {f"{k}={x}" for x in v.split(",")}
    return out


def slots(pred: dict, true: pd.Series) -> dict:
    """Per-slot scores for one pair, before the gate."""
    t_true = true["start_date"] + pd.Timedelta(days=int(true["lag_days"] or 0))
    delta = (pd.Timestamp(pred["start_date"]) - t_true).days
    tau = TAU.get(pred.get("kind", "shift"), 7)
    a, b = seg_pairs(pred["segment"]), seg_pairs(true["segment"])
    jac = 1.0 if not a and not b else len(a & b) / len(a | b)
    p, t = abs(pred["magnitude_pct"] or 0), abs(true["magnitude_pct"] or 0)
    mag = max(0.0, 1 - abs(math.log(p / t)) / math.log(2)) if p > 0 and t > 0 else 0.0
    true_lag = int(true["lag_days"] or 0)
    pred_lag = pred.get("lag_days")
    lag_ok = (pred_lag is not None and not (isinstance(pred_lag, float) and math.isnan(pred_lag))
              and abs(int(pred_lag) - true_lag) <= LAG_TOLERANCE) if true_lag else not pred_lag
    return {
        "gate": float(pred["metric"] == true["metric"] and pred["direction"] == true["direction"]),
        "timing": max(0.0, 1 - abs(delta) / tau), "delta_days": delta,
        "segment": jac, "magnitude": mag, "lag": float(bool(lag_ok)),
    }


def pair_score(sl: dict) -> float:
    return sl["gate"] * (W_TIME * sl["timing"] + W_SEG * sl["segment"] + W_MAG * sl["magnitude"])


def score(events: list[dict], truth: dict) -> dict:
    key = truth["scored"]
    n_p, n_t = len(events), len(key)
    pairs = [[slots(e, key.iloc[j]) for j in range(n_t)] for e in events]
    s = np.array([[pair_score(x) for x in row] for row in pairs]) if n_p and n_t else np.zeros((n_p, n_t))
    matches = []
    if n_p and n_t:
        rows, cols = linear_sum_assignment(-s)
        matches = [(int(i), int(j)) for i, j in zip(rows, cols) if s[i, j] >= MATCH]
    tp = len(matches)
    precision = tp / n_p if n_p else 0.0
    recall = tp / n_t if n_t else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    pred_of = {key.iloc[j]["event_id"]: events[i]["id"] for i, j in matches}
    cb_possible = cb_hit = 0
    detail = []
    for i, j in matches:
        t = key.iloc[j]
        sl = pairs[i][j]
        cb = None
        if isinstance(t["caused_by"], str) and t["caused_by"] in pred_of:
            cb_possible += 1
            cb = events[i].get("caused_by") == pred_of[t["caused_by"]]
            cb_hit += int(cb)
        detail.append({"event_id": t["event_id"], "pred_id": events[i]["id"], "score": round(float(s[i, j]), 3),
                       **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in sl.items()},
                       "caused_by_ok": cb})
    matched_p = {i for i, _ in matches}
    fps = []
    for i, e in enumerate(events):
        if i in matched_p:
            continue
        day = pd.Timestamp(e["start_date"])
        near = truth["decoys"][(truth["decoys"]["date"] - day).abs() <= pd.Timedelta(days=3)]
        fps.append({"pred_id": e["id"], "metric": e["metric"], "segment": e["segment"],
                    "start_date": e["start_date"], "decoy": near.iloc[0]["type"] if len(near) else None})
    matched_t = {j for _, j in matches}
    misses = [key.iloc[j]["event_id"] for j in range(n_t) if j not in matched_t]
    slot_mean = {k: round(float(np.mean([d[k] for d in detail])), 3) if detail else None
                 for k in ("timing", "segment", "magnitude", "lag")}
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
            "tp": tp, "n_pred": n_p, "n_true": n_t, "matches": detail, "false_positives": fps,
            "missed": misses, "slots": slot_mean,
            "caused_by_bonus": {"hit": cb_hit, "possible": cb_possible},
            "excluded": truth["key"][~truth["key"]["simulated"]]["event_id"].tolist(),
            "score_matrix": s.round(3).tolist()}


def placebo(events: list[dict], truth: dict, n: int = 200, seed: int = 0) -> dict:
    """Shuffle the answer-key dates n times. How often does a random key score as
    well as the real one? p = (1 + #(F1_placebo >= F1_real)) / (1 + n)."""
    rng = np.random.default_rng(seed)
    real = score(events, truth)["f1"]
    days = (truth["end"] - truth["start"]).days
    f1s = []
    for _ in range(n):
        fake = dict(truth)
        k = truth["scored"].copy()
        lag = k["lag_days"].fillna(0).astype(int).to_numpy()
        offs = rng.integers(0, np.maximum(days - lag, 1))
        k["start_date"] = truth["start"] + pd.to_timedelta(offs, unit="D")
        fake["scored"] = k
        f1s.append(score(events, fake)["f1"])
    f1s = np.array(f1s)
    return {"f1": real, "placebo_f1": f1s.round(3).tolist(),
            "p_value": round(float((1 + np.sum(f1s >= real)) / (1 + n)), 4)}


def twin_rate(events: list[dict], days: int) -> float:
    return round(len(events) / (days / 365.25), 2)


def _detect(run_dir: Path, narrate: bool) -> dict:
    from s2d import detective
    path = run_dir / "detective.json"
    if path.exists():
        return detective.load(path)
    res = detective.run(run_dir, narrate=narrate)
    detective.save(res, path)
    return res


def scorecard(run_dir: str | Path, twin_dir: str | Path | None = None, *, narrate: bool = False,
              n_placebo: int = 200) -> dict:
    run_dir = Path(run_dir)
    det = _detect(run_dir, narrate)
    truth = load_truth(run_dir)
    card = {"run_dir": str(run_dir), "score": score(det["events"], truth),
            "answer_key": truth["key"].assign(start_date=truth["key"]["start_date"].dt.date.astype(str))
                                      .to_dict("records"),
            "events": det["events"], "timing": det["timing"]}
    card["placebo"] = placebo(det["events"], truth, n_placebo)
    if twin_dir:
        twin = _detect(Path(twin_dir), narrate)
        card["twin"] = {"n_events": len(twin["events"]), "days": twin["days"],
                        "false_events_per_year": twin_rate(twin["events"], twin["days"]),
                        "events": twin["events"]}
    return card


# ---------------------------------------------------------------- sweep and curve


def _sim(spec_path: Path, out: Path, seed: int, n: int | None, no_story: bool) -> None:
    cmd = [sys.executable, "-m", "s2d.sim", "run", str(spec_path), "--seed", str(seed), "--out", str(out)]
    if n:
        cmd += ["--n-customers", str(n)]
    if no_story:
        cmd.append("--no-story")
    subprocess.run(cmd, check=True, capture_output=True)


def sweep(spec_path: str | Path, seeds: list[int], n: int | None = 10000, difficulty: str | None = None,
          workdir: Path | None = None, twin: bool = True) -> dict:
    from s2d import detective
    spec_path = Path(spec_path)
    if difficulty:
        data = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        data["meta"]["difficulty"] = difficulty
        tmp = Path(tempfile.mkdtemp()) / spec_path.name
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        spec_path = tmp
    workdir = workdir or Path(tempfile.mkdtemp(prefix="s2d-sweep-"))
    rows = []
    for seed in seeds:
        row = {"seed": seed}
        for kind in (("story", "twin") if twin else ("story",)):
            out = workdir / f"{kind}_{seed}"
            _sim(spec_path, out, seed, n, kind == "twin")
            det = detective.run(out, narrate=False)
            if kind == "story":
                sc = score(det["events"], load_truth(out))
                row.update(f1=sc["f1"], precision=sc["precision"], recall=sc["recall"],
                           scan_s=det["timing"]["total_s"])
            else:
                row.update(twin_events=len(det["events"]),
                           twin_per_year=twin_rate(det["events"], det["days"]))
        rows.append(row)
        print(json.dumps(row), file=sys.stderr)
    df = pd.DataFrame(rows)
    summary = {c: {"mean": round(float(df[c].mean()), 3), "sd": round(float(df[c].std(ddof=1)), 3) if len(df) > 1 else 0.0}
               for c in df.columns if c != "seed"}
    return {"spec": str(spec_path), "difficulty": difficulty, "n_customers": n, "runs": rows, "summary": summary}


def curve(spec_path: str | Path, out_png: str | Path, seeds: list[int], n: int | None = 10000) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    levels = ["easy", "medium", "hard"]
    res = {lvl: sweep(spec_path, seeds, n, difficulty=lvl, twin=False) for lvl in levels}
    fig, ax = plt.subplots(figsize=(6, 4))
    for metric, style in (("f1", "o-"), ("recall", "s--"), ("precision", "^:")):
        m = [res[lvl]["summary"][metric]["mean"] for lvl in levels]
        sd = [res[lvl]["summary"][metric]["sd"] for lvl in levels]
        ax.errorbar(levels, m, yerr=sd, fmt=style, capsize=3, label=metric)
    ax.set_ylim(0, 1)
    ax.set_xlabel("difficulty (effect size x1.5 / x1.0 / x0.5)")
    ax.set_ylabel("score")
    ax.set_title(f"{Path(spec_path).stem}: detection vs difficulty ({len(seeds)} seeds, {n} customers)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120)
    return {lvl: res[lvl]["summary"] for lvl in levels}


# ---------------------------------------------------------------- CLI


def _print_card(card: dict) -> None:
    s = card["score"]
    print(f"precision {s['precision']}  recall {s['recall']}  F1 {s['f1']}  "
          f"({s['tp']} matched / {s['n_pred']} reported / {s['n_true']} in the key)")
    if s["excluded"]:
        print(f"excluded (simulated = false): {', '.join(s['excluded'])}")
    for m in s["matches"]:
        print(f"  {m['event_id']} <- {m['pred_id']}  s={m['score']}  timing {m['timing']} ({m['delta_days']:+d} d)  "
              f"segment {m['segment']}  magnitude {m['magnitude']}  lag {m['lag']}  caused_by {m['caused_by_ok']}")
    for e in s["missed"]:
        print(f"  {e}: missed")
    for fp in s["false_positives"]:
        print(f"  false positive {fp['pred_id']} {fp['metric']} {fp['segment'] or 'everyone'} {fp['start_date']}"
              + (f"  (decoy: {fp['decoy']})" if fp["decoy"] else ""))
    print(f"slots {s['slots']}  caused_by bonus {s['caused_by_bonus']['hit']}/{s['caused_by_bonus']['possible']}")
    print(f"placebo: p = {card['placebo']['p_value']} "
          f"(placebo F1 mean {np.mean(card['placebo']['placebo_f1']):.3f}, max {max(card['placebo']['placebo_f1']):.3f})")
    if "twin" in card:
        t = card["twin"]
        print(f"twin: {t['n_events']} events in {t['days']} days = {t['false_events_per_year']} per year")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("sweep", "curve"):
        p = argparse.ArgumentParser(prog=f"python -m s2d.score {argv[0]}")
        p.add_argument("spec")
        p.add_argument("--seeds", type=int, default=5)
        p.add_argument("--first-seed", type=int, default=1)
        p.add_argument("--n-customers", type=int, default=10000)
        p.add_argument("--difficulty")
        p.add_argument("--out", default="docs/detection_curve.png")
        a = p.parse_args(argv[1:])
        seeds = list(range(a.first_seed, a.first_seed + a.seeds))
        if argv[0] == "sweep":
            res = sweep(a.spec, seeds, a.n_customers, a.difficulty)
            print(json.dumps(res["summary"], indent=1))
        else:
            print(json.dumps(curve(a.spec, a.out, seeds, a.n_customers), indent=1))
            print(f"wrote {a.out}")
        return 0
    p = argparse.ArgumentParser(prog="python -m s2d.score")
    p.add_argument("run_dir")
    p.add_argument("--twin")
    p.add_argument("--placebo", type=int, default=200)
    p.add_argument("--llm", action="store_true", help="let the narrator accept/reject (default: scan output)")
    p.add_argument("--out", help="write the scorecard JSON here")
    a = p.parse_args(argv)
    card = scorecard(a.run_dir, a.twin, narrate=a.llm, n_placebo=a.placebo)
    _print_card(card)
    if a.out:
        Path(a.out).write_text(json.dumps(card, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
