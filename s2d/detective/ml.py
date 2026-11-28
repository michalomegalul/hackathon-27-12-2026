"""ML detective: score every (series, day) of the KPI series, then pick peaks as events.

The features only use the analyst series (no hidden schema). The label for training comes from the
answer key and is built in scripts/ml/ (never here). One model for every dataset and story.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .kpis import INVERSE_KPIS, METRIC, KPISet

WINDOWS = (7, 14, 28, 56)
MIN_T, MIN_AFTER = 28, 14
KPI_NAMES = sorted(METRIC)
DIMS = ("city", "channel", "segment", "category", "store", "product")
FEATURES = (
    [f"z{w}" for w in WINDOWS] + [f"rel{w}" for w in (14, 28, 56)]
    + ["zs28", "zs14", "peak28", "rank28", "sib28", "sib14", "par28", "par14", "mean", "cv", "total", "nkeys", "tfrac"]
    + [f"kpi_{k}" for k in KPI_NAMES] + [f"dim_{d}" for d in DIMS]
)


def _dow_adjust(s: pd.Series) -> np.ndarray:
    v = s.to_numpy(dtype=float)
    dow = s.index.dayofweek.to_numpy()
    out = v.copy()
    for d in range(7):
        m = dow == d
        if m.any():
            out[m] -= np.nanmedian(v[m]) - np.nanmedian(v)
    return out


def _diff(x: np.ndarray, w: int) -> np.ndarray:
    """after-mean minus before-mean for every t; NaN where the window does not fit."""
    n = len(x)
    c = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x))])
    d = np.full(n, np.nan)
    for t in range(MIN_T, n - MIN_AFTER + 1):
        lo = max(0, t - w)
        hi = min(n, t + w)
        before = (c[t] - c[lo]) / (t - lo)
        after = (c[hi] - c[t]) / (hi - t)
        d[t] = after - before
    return d


def _z(d: np.ndarray) -> np.ndarray:
    ok = d[~np.isnan(d)]
    if len(ok) < 30:
        return np.zeros_like(d)
    sd = 1.4826 * np.median(np.abs(ok - np.median(ok))) + 1e-9
    return d / sd


def _local_max(a: np.ndarray, r: int = 14) -> np.ndarray:
    m = np.nan_to_num(np.abs(a))
    pad = np.pad(m, r, constant_values=0)
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * r + 1)
    return m / (win.max(axis=1) + 1e-9)


def _parts(seg: str) -> list[tuple[str, str]]:
    return [tuple(p.split("=", 1)) for p in seg.split(";") if p]  # type: ignore[misc]


def series_features(ks: KPISet) -> pd.DataFrame:
    """One row per (kpi, segment, day index) with the model features and the orienting sign."""
    n = len(ks.dates)
    base: dict[tuple[str, str], dict] = {}
    for (kpi, seg), s in ks.series.items():
        s = s.reindex(ks.dates)
        if s.isna().all() or np.nanstd(s.to_numpy(dtype=float)) == 0:
            continue
        x = _dow_adjust(s)
        zs, ds = {}, {}
        for w in WINDOWS:
            ds[w] = _diff(x, w)
            zs[w] = _z(ds[w])
        # share of the segment in the parent total: catches shifts that the total hides
        zsh = {14: zs[14], 28: zs[28]}
        tot = ks.series.get((kpi, ""))
        if tot is not None and seg and kpi not in {"late_rate", "rating_mean", "repeat_rate"}:
            tt = tot.reindex(ks.dates).to_numpy(dtype=float)
            sh = np.where(tt > 0, s.to_numpy(dtype=float) / np.where(tt > 0, tt, 1), np.nan)
            xs = _dow_adjust(pd.Series(sh, index=ks.dates).ffill().bfill())
            zsh = {w: _z(_diff(xs, w)) for w in (14, 28)}
        base[(kpi, seg)] = {"x": x, "d": ds, "z": zs, "zsh": zsh, "s": s.to_numpy(dtype=float)}

    # siblings: same kpi, same single key (e.g. every city): an event hits one value, the others stay
    sib: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for kpi, seg in base:
        p = _parts(seg)
        if len(p) == 1:
            sib.setdefault((kpi, p[0][0]), []).append((kpi, seg))
    rows = []
    for (kpi, seg), b in base.items():
        p = _parts(seg)
        z28, z14 = b["z"][28], b["z"][14]
        peak = _local_max(z28)
        valid = ~np.isnan(z28)
        absz = np.abs(np.nan_to_num(z28))
        rank = np.zeros(n)
        if valid.sum():
            order = absz[valid].argsort().argsort() / max(valid.sum() - 1, 1)
            rank[valid] = order
        if len(p) == 1 and len(sib[(kpi, p[0][0])]) > 2:
            others = [c for c in sib[(kpi, p[0][0])] if c != (kpi, seg)]
            m28 = np.median([base[c]["z"][28] for c in others], axis=0)
            m14 = np.median([base[c]["z"][14] for c in others], axis=0)
            sib28, sib14 = z28 - m28, z14 - m14
        else:
            sib28 = sib14 = np.zeros(n)
        par = base.get((kpi, ""))
        par28, par14 = (par["z"][28], par["z"][14]) if par is not None and seg else (np.zeros(n), np.zeros(n))
        d28 = b["d"][28]
        rel = {}
        for w in (14, 28, 56):
            lo = pd.Series(b["x"]).rolling(w, min_periods=7).mean().shift(1).to_numpy()
            rel[w] = np.clip(b["d"][w] / (np.abs(lo) + 1e-6), -5, 5)
        mean = float(np.nanmean(b["s"]))
        cv = float(np.nanstd(b["s"]) / (abs(mean) + 1e-9))
        f = pd.DataFrame({
            **{f"z{w}": b["z"][w] for w in WINDOWS},
            **{f"rel{w}": rel[w] for w in (14, 28, 56)},
            "zs28": b["zsh"][28], "zs14": b["zsh"][14], "peak28": peak, "rank28": rank,
            "sib28": sib28, "sib14": sib14, "par28": par28, "par14": par14,
            "mean": mean, "cv": cv, "total": float(np.nansum(b["s"])), "nkeys": len(p),
            "tfrac": np.arange(n) / n,
        })
        for k in KPI_NAMES:
            f[f"kpi_{k}"] = float(k == kpi)
        for d in DIMS:
            f[f"dim_{d}"] = float(any(k == d for k, _ in p))
        sign = np.sign(np.nan_to_num(d28))
        if kpi in INVERSE_KPIS:
            sign = -sign
        f["kpi"], f["segment"], f["t"], f["sign"] = kpi, seg, np.arange(n), sign
        f["rel28_signed"] = np.nan_to_num(rel[28]) * 100
        rows.append(f[valid])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=[*FEATURES, "kpi", "segment", "t", "sign"])


def pick_events(df: pd.DataFrame, prob: np.ndarray, dates: pd.DatetimeIndex, threshold: float,
                nms_days: int = 21, max_events: int = 12) -> list[dict]:
    """Peaks of the model probability, one event per metric and time window, as score.py event dicts."""
    d = df.assign(p=prob)
    d = d[(d["p"] >= threshold) & (d["sign"] != 0)].sort_values("p", ascending=False)
    kept: list[dict] = []
    for r in d.itertuples():
        metric = METRIC[r.kpi]
        direction = "up" if r.sign > 0 else "down"
        if any(k["metric"] == metric and abs(k["_t"] - r.t) <= nms_days for k in kept):
            continue
        kept.append({
            "id": f"M{len(kept) + 1:03d}", "metric": metric, "segment": r.segment, "kind": "shift",
            "start_date": str(dates[int(r.t)].date()), "end_date": None, "direction": direction,
            "magnitude_pct": abs(float(r.rel28_signed)), "lag_days": None, "caused_by": None,
            "confidence": float(r.p), "_t": int(r.t),
        })
        if len(kept) >= max_events:
            break
    for k in kept:
        k.pop("_t")
    return kept
