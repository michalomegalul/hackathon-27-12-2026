"""Scorer: detective events vs the answer key. This module may read _truth.

    python -m s2d.score data/a/ --twin data/a_twin/            # scorecard + controls
    python -m s2d.score sweep examples/a.yaml --seeds 5          # seed sweep, story and twin
    python -m s2d.score curve examples/a.yaml --out docs/detection_curve.png

Pair score  s = gate(metric, direction) x (0.4 timing + 0.4 segment Jaccard + 0.2 magnitude)
  timing    = max(0, 1 - |pred.start - (true.start + lag)| / tau), tau 7 (shift) or 2 (spike)
  segment   = Jaccard over key=value pairs ('category=a,b' is two pairs)
  magnitude = max(0, 1 - |log(pred/true)| / log 2)
The gate is metric and direction match and, unlike the original formula, timing > 0
(TIME_GATE, see DECISIONS.md). Hungarian matching; a pair counts when s >= 0.5. Answer-key rows with
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
CONSEQUENCE_DAYS = 60
# Which way is bad: purchases and new customers falling, churn rising, ...
ADVERSE_UP = {"purchase_rate": False, "acquisition_rate": False, "rating_mean": False,
              "churn_hazard": True, "delivery_days": True, "ticket_rate": True}
# The formula as specified lets segment + magnitude alone reach 0.6 >= 0.5, so a
# detection on the wrong date still matched and the date-shuffle placebo could
# never reject. With TIME_GATE the gate also needs timing > 0 (|delta| < tau).
TIME_GATE = True


SUPPLY_TYPES = ("supplier_delay", "stockout")
# the ticket topic each emergent mechanism writes (the same table as s2d/verify.py TICKET_TOPIC)
TICKET_TOPIC = {"supplier_delay": "vyprodáno", "stockout": "vyprodáno", "courier_change": "zpoždění"}
STOCKOUT_MIN_SKUS = 2   # several shelves empty together (as s2d/detective/scan.py)
BACKGROUND_DAYS = 7     # a find within this many days of the same find on the twin is background


def seg_pairs(seg) -> set[str]:
    if not isinstance(seg, str):
        return set()
    out = set()
    for part in filter(None, seg.split(";")):
        k, v = part.split("=", 1)
        out |= {f"{k}={x}" for x in v.split(",")}
    return out


def _seg_dict(seg) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in sorted(seg_pairs(seg)):
        k, v = p.split("=", 1)
        out.setdefault(k, []).append(v)
    return out


def _supply_truth(con, key: pd.DataFrame) -> None:
    """Supply events (supplier_delay, stockout) show in the data as stock running out, not as a
    curve with a known lag: the lag in the key is the story's guess. For each such row add
    `observed_start`, the first day in [start, start + lag + CONSEQUENCE_DAYS] on which a product
    of its target has no stock, and `supply_pairs`, the target with a supplier expanded into its
    categories ('supplier=S_ETH' -> also 'category=etiopie'), which is how the detective names it."""
    key["observed_start"] = pd.NaT
    key["supply_pairs"] = [seg_pairs(s) for s in key["segment"]]
    if key.empty:
        return
    try:
        prod = con.execute("SELECT product_id, category, supplier_id FROM main.products").df()
        inv = con.execute("SELECT date, product_id FROM main.inventory_daily WHERE stock_units <= 0").df()
    except duckdb.Error:
        return
    inv["date"] = pd.to_datetime(inv["date"])
    for i, t in key.iterrows():
        if t["type"] not in SUPPLY_TYPES:
            continue
        seg = _seg_dict(t["segment"])
        p = prod
        if "supplier" in seg:
            p = p[p["supplier_id"].isin(seg["supplier"])]
        if "category" in seg:
            p = p[p["category"].isin(seg["category"])]
        if p.empty or not ({"supplier", "category"} & seg.keys()):
            continue
        key.at[i, "supply_pairs"] = seg_pairs(t["segment"]) | {f"category={c}" for c in p["category"].unique()} \
            | {f"supplier={s}" for s in p["supplier_id"].unique()}
        lo = t["start_date"]
        hi = lo + pd.Timedelta(days=int(t["lag_days"] or 0) + CONSEQUENCE_DAYS)
        out = inv[inv["product_id"].isin(p["product_id"]) & (inv["date"] >= lo) & (inv["date"] <= hi)]
        # the first day several shelves are empty together: one SKU out is routine restocking,
        # which the detective does not report either (scan.STOCKOUT_MIN_SKUS)
        need = min(STOCKOUT_MIN_SKUS, len(p))
        per_day = out.groupby("date")["product_id"].nunique()
        days = per_day[per_day >= need].index
        if len(days):
            key.at[i, "observed_start"] = days.min()


def _courier_truth(con, key: pd.DataFrame) -> None:
    """A courier_change targets cities, but the data names the courier: add `alias_pairs`
    {courier=X}, X the courier whose share of the target cities' deliveries grew most in the 28
    days from start against the 28 before (the courier the company switched to)."""
    key["alias_pairs"] = [set() for _ in range(len(key))]
    rows = [i for i, t in key.iterrows() if t["type"] == "courier_change" and "city" in _seg_dict(t["segment"])]
    if not rows:
        return
    try:
        d = con.execute("""SELECT o.order_date AS date, o.city, d.courier
                           FROM main.deliveries d JOIN main.orders o USING (order_id)""").df()
    except duckdb.Error:
        return
    d["date"] = pd.to_datetime(d["date"])
    for i in rows:
        t = key.loc[i]
        g = d[d["city"].isin(_seg_dict(t["segment"])["city"])]
        s0 = t["start_date"]
        before = g[(g["date"] >= s0 - pd.Timedelta(days=28)) & (g["date"] < s0)]["courier"].value_counts(normalize=True)
        after = g[(g["date"] >= s0) & (g["date"] < s0 + pd.Timedelta(days=28))]["courier"].value_counts(normalize=True)
        if after.empty:
            continue
        gain = after.sub(before, fill_value=0)
        if gain.max() > 0.2:
            key.at[i, "alias_pairs"] = {f"courier={gain.idxmax()}"}


def load_truth(run_dir: str | Path) -> dict:
    db = Path(run_dir) / "story.duckdb"
    with duckdb.connect(str(db), read_only=True) as con:
        key = con.execute("SELECT * FROM _truth.answer_key").df()
        decoys = con.execute("SELECT * FROM _truth.decoys").df()
        lo, hi = con.execute("SELECT min(order_date), max(order_date) FROM main.orders").fetchone()
        key["start_date"] = pd.to_datetime(key["start_date"])
        _supply_truth(con, key)
        _courier_truth(con, key)
    # an empty key reads `simulated` as object, and key[~col] is then a column selection
    key["simulated"] = key["simulated"].astype(bool)
    decoys["date"] = pd.to_datetime(decoys["date"])
    return {"key": key, "scored": key[key["simulated"]].reset_index(drop=True), "decoys": decoys,
            "start": pd.Timestamp(lo), "end": pd.Timestamp(hi)}


def _true_pairs(true: pd.Series) -> set[str]:
    """The event's target as key=value pairs (a supply event's supplier with its categories)."""
    sp = true.get("supply_pairs") if hasattr(true, "get") else None
    return set(sp) if isinstance(sp, set) else seg_pairs(true["segment"])


def _alias(true: pd.Series) -> set[str]:
    al = true.get("alias_pairs") if hasattr(true, "get") else None
    return set(al) if isinstance(al, set) else set()


def _family_pairs(true: pd.Series) -> set[str]:
    """For consequences: the target plus the ticket topic its mechanism writes (an empty
    shelf -> 'vyprodáno', a late courier -> 'zpoždění'), as s2d/verify.py tests them."""
    out = _true_pairs(true) | _alias(true)
    topic = TICKET_TOPIC.get(true.get("type") if hasattr(true, "get") else None)
    if topic and true.get("mechanism") == "emergent":
        out.add(f"topic={topic}")
    return out


def _observed(true: pd.Series):
    o = true.get("observed_start") if hasattr(true, "get") else None
    return None if o is None or pd.isna(o) else pd.Timestamp(o)


def slots(pred: dict, true: pd.Series) -> dict:
    """Per-slot scores for one pair, before the gate.

    A supply event (supplier_delay, stockout) also matches the detective's stock-out of its
    products: dated at the observed first stock-out, segment against the target with its
    categories, no magnitude (the key's size is for another metric)."""
    obs = _observed(true)
    as_stockout = obs is not None and pred.get("kind") == "stockout"
    t_true = obs if as_stockout else true["start_date"] + pd.Timedelta(days=int(true["lag_days"] or 0))
    delta = (pd.Timestamp(pred["start_date"]) - t_true).days
    tau = TAU.get(pred.get("kind", "shift"), 7)
    a, b = seg_pairs(pred["segment"]), _true_pairs(true)
    jac = 1.0 if not a and not b else len(a & b) / len(a | b)
    alias = _alias(true)
    if alias and a:  # the same target under another name (the new courier for its cities)
        jac = max(jac, len(a & alias) / len(a | alias))
    p, t = abs(pred["magnitude_pct"] or 0), abs(true["magnitude_pct"] or 0)
    mag = max(0.0, 1 - abs(math.log(p / t)) / math.log(2)) if p > 0 and t > 0 and not as_stockout else 0.0
    true_lag = int(true["lag_days"] or 0)
    pred_lag = pred.get("lag_days")
    lag_ok = (pred_lag is not None and not (isinstance(pred_lag, float) and math.isnan(pred_lag))
              and abs(int(pred_lag) - true_lag) <= LAG_TOLERANCE) if true_lag else not pred_lag
    gate = as_stockout or (pred["metric"] == true["metric"] and pred["direction"] == true["direction"])
    return {
        "gate": float(gate),
        "timing": max(0.0, 1 - abs(delta) / tau), "delta_days": delta,
        "segment": jac, "magnitude": mag, "lag": float(bool(lag_ok)),
    }


def pair_score(sl: dict) -> float:
    gate = sl["gate"] * (sl["timing"] > 0 if TIME_GATE else 1)
    return gate * (W_TIME * sl["timing"] + W_SEG * sl["segment"] + W_MAG * sl["magnitude"])


def _dims(pairs: set[str]) -> set[str]:
    return {p.split("=", 1)[0] for p in pairs}


def consequence_of(e: dict, true: pd.Series) -> bool:
    """Is unmatched detection e a consequence of matched answer-key event `true`?
    In its segment family, within [start, start + lag + CONSEQUENCE_DAYS], in the
    expected direction:
      - shares a key=value with it (or one side is everyone): moves the bad way,
        whatever the metric (a price rise -> fewer orders -> more churn);
      - or is its mirror control (same dimension, another value: Praha stores while
        Brno stores fall): same metric, opposite direction."""
    start = true["start_date"]
    day = pd.Timestamp(e["start_date"])
    lag = int(true["lag_days"] or 0)
    if not start <= day <= start + pd.Timedelta(days=lag + CONSEQUENCE_DAYS):
        return False
    a, b = seg_pairs(e["segment"]), _family_pairs(true)
    bad = lambda metric, direction: (direction == "up") == ADVERSE_UP.get(metric, False)  # noqa: E731
    if (not a or not b or a & b) and bad(e["metric"], e["direction"]) == bad(true["metric"], true["direction"]):
        return True
    if true.get("type") in SUPPLY_TYPES and e["metric"] in ("purchase_rate", "ticket_rate"):
        # an outage has a whole cycle: the shelf empties, tickets come, then the restock brings
        # orders back up and tickets down; and customers switch to other categories meanwhile,
        # and back once the shelf is full again
        if a & b or "category" in _dims(a) & _dims(b):
            return True
    return bool(_dims(a) & _dims(b)) and not a & b and e["metric"] == true["metric"] and e["direction"] != true["direction"]


def background_of(e: dict, twin_events: list[dict]) -> dict | None:
    """The twin's find that `e` repeats, if any: same metric and direction, within
    BACKGROUND_DAYS, segments equal or overlapping (or both everyone). The twin has no story,
    so such a find is how the company runs anyway (a routine stock-out, a courier's bad week),
    not a hallucination and not the story."""
    a = seg_pairs(e["segment"])
    day = pd.Timestamp(e["start_date"])
    for w in twin_events:
        if w["metric"] != e["metric"] or w["direction"] != e["direction"]:
            continue
        if abs((pd.Timestamp(w["start_date"]) - day).days) > BACKGROUND_DAYS:
            continue
        b = seg_pairs(w["segment"])
        if a == b or a & b:
            return w
    return None


def score(events: list[dict], truth: dict, twin_events: list[dict] | None = None) -> dict:
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
    fps, cons, background = [], [], []
    for i, e in enumerate(events):
        if i in matched_p:
            continue
        of = next((key.iloc[j]["event_id"] for _, j in matches if consequence_of(e, key.iloc[j])), None)
        if of is not None:
            cons.append({"pred_id": e["id"], "metric": e["metric"], "segment": e["segment"],
                         "start_date": e["start_date"], "direction": e["direction"], "of": of})
            continue
        day = pd.Timestamp(e["start_date"])
        near = truth["decoys"][(truth["decoys"]["date"] - day).abs() <= pd.Timedelta(days=3)]
        decoy = near.iloc[0]["type"] if len(near) else None
        tw = background_of(e, twin_events) if twin_events and decoy is None else None
        if tw is not None:  # a decoy stays a false find: it is planted in both worlds on purpose
            background.append({"pred_id": e["id"], "metric": e["metric"], "segment": e["segment"],
                               "start_date": e["start_date"], "direction": e["direction"],
                               "twin_id": tw["id"], "twin_start_date": tw["start_date"]})
            continue
        fps.append({"pred_id": e["id"], "metric": e["metric"], "segment": e["segment"],
                    "start_date": e["start_date"], "decoy": decoy})
    matched_t = {j for _, j in matches}
    misses = [key.iloc[j]["event_id"] for j in range(n_t) if j not in matched_t]
    # with consequences: a consequence (or a find the twin has too) is neither a TP nor an FP,
    # precision = TP / (TP + FP)
    p_c = tp / (tp + len(fps)) if tp + len(fps) else 0.0
    f1_c = 2 * p_c * recall / (p_c + recall) if p_c + recall else 0.0
    slot_mean = {k: round(float(np.mean([d[k] for d in detail])), 3) if detail else None
                 for k in ("timing", "segment", "magnitude", "lag")}
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
            "precision_cons": round(p_c, 3), "f1_cons": round(f1_c, 3), "n_fp": len(fps),
            "tp": tp, "n_pred": n_p, "n_true": n_t, "matches": detail, "false_positives": fps,
            "consequences": cons, "background": background,
            "missed": misses, "slots": slot_mean,
            "caused_by_bonus": {"hit": cb_hit, "possible": cb_possible},
            "excluded": truth["key"][~truth["key"]["simulated"]]["event_id"].tolist(),
            "score_matrix": s.round(3).tolist()}


def placebo(events: list[dict], truth: dict, n: int = 200, seed: int = 0,
            twin_events: list[dict] | None = None) -> dict:
    """Shuffle the answer-key dates n times. How often does a random key score as
    well as the real one? p = (1 + #(F1_placebo >= F1_real)) / (1 + n)."""
    rng = np.random.default_rng(seed)
    sc = score(events, truth, twin_events)
    real, real_c = sc["f1"], sc["f1_cons"]
    days = (truth["end"] - truth["start"]).days
    f1s, f1s_c = [], []
    for _ in range(n):
        fake = dict(truth)
        k = truth["scored"].copy()
        lag = k["lag_days"].fillna(0).astype(int).to_numpy()
        offs = rng.integers(0, np.maximum(days - lag, 1))
        new = truth["start"] + pd.to_timedelta(offs, unit="D")
        if "observed_start" in k:  # the observed stock-out moves with its event
            k["observed_start"] = new + (pd.to_datetime(k["observed_start"]) - k["start_date"]).to_numpy()
        k["start_date"] = new
        fake["scored"] = k
        ps = score(events, fake, twin_events)
        f1s.append(ps["f1"])
        f1s_c.append(ps["f1_cons"])
    f1s, f1s_c = np.array(f1s), np.array(f1s_c)
    return {"f1": real, "placebo_f1": f1s.round(3).tolist(),
            "p_value": round(float((1 + np.sum(f1s >= real)) / (1 + n)), 4),
            "f1_cons": real_c, "p_value_cons": round(float((1 + np.sum(f1s_c >= real_c)) / (1 + n)), 4)}


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
    twin = _detect(Path(twin_dir), narrate) if twin_dir else None
    tw_events = twin["events"] if twin else None
    key = truth["key"].drop(columns=["supply_pairs", "alias_pairs"]).assign(
        start_date=truth["key"]["start_date"].dt.date.astype(str),
        observed_start=truth["key"]["observed_start"].map(lambda d: None if pd.isna(d) else str(d.date())))
    card = {"run_dir": str(run_dir), "score": score(det["events"], truth, tw_events),
            "answer_key": key.to_dict("records"),
            "events": det["events"], "timing": det["timing"]}
    card["placebo"] = placebo(det["events"], truth, n_placebo, twin_events=tw_events)
    if twin:
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


def sweep(spec_path: str | Path, seeds: list[int], n: int | None = 40000, difficulty: str | None = None,
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
                           f1_cons=sc["f1_cons"], precision_cons=sc["precision_cons"],
                           n_fp=sc["n_fp"], n_cons=len(sc["consequences"]),
                           matched=",".join(m["event_id"] for m in sc["matches"]),
                           scan_s=det["timing"]["total_s"])
            else:
                row.update(twin_events=len(det["events"]),
                           twin_per_year=twin_rate(det["events"], det["days"]))
        rows.append(row)
        print(json.dumps(row), file=sys.stderr)
    df = pd.DataFrame(rows)
    num = df.select_dtypes("number")
    summary = {c: {"mean": round(float(df[c].mean()), 3), "sd": round(float(df[c].std(ddof=1)), 3) if len(df) > 1 else 0.0}
               for c in num.columns if c != "seed"}
    return {"spec": str(spec_path), "difficulty": difficulty, "n_customers": n, "runs": rows, "summary": summary}


def curve(spec_path: str | Path, out_png: str | Path, seeds: list[int], n: int | None = 40000) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    levels = ["easy", "medium", "hard"]
    res = {lvl: sweep(spec_path, seeds, n, difficulty=lvl, twin=False) for lvl in levels}
    fig, ax = plt.subplots(figsize=(6, 4))
    for metric, style in (("f1", "o-"), ("f1_cons", "o-."), ("recall", "s--"), ("precision", "^:")):
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
    print(f"strict:            precision {s['precision']}  recall {s['recall']}  F1 {s['f1']}  "
          f"({s['tp']} matched / {s['n_pred']} reported / {s['n_true']} in the key)")
    print(f"with consequences: precision {s['precision_cons']}  recall {s['recall']}  F1 {s['f1_cons']}  "
          f"({s['tp']} TP, {s['n_fp']} FP, {len(s['consequences'])} důsledky)")
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
    for b in s.get("background", []):
        print(f"  background {b['pred_id']} {b['metric']} {b['direction']} {b['segment'] or 'everyone'} "
              f"{b['start_date']}  (twin {b['twin_id']} {b['twin_start_date']})")
    for c in s["consequences"]:
        print(f"  důsledek {c['pred_id']} {c['metric']} {c['direction']} {c['segment'] or 'everyone'} "
              f"{c['start_date']}  (of {c['of']})")
    print(f"slots {s['slots']}  caused_by bonus {s['caused_by_bonus']['hit']}/{s['caused_by_bonus']['possible']}")
    print(f"placebo: p = {card['placebo']['p_value']} (with consequences {card['placebo']['p_value_cons']}) "
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
        p.add_argument("--n-customers", type=int, default=40000)
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
