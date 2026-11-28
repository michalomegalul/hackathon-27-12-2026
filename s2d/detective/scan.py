"""Statistical scan: KPI series -> candidate events.

Every threshold here is global (see DECISIONS.md, "Detective"). Nothing reads the
story; the same numbers run on every dataset and on the no-story twin.

Pipeline per series:
  STL(period 7, robust) -> trend + residual, scaled by the residual's MAD
  PELT(l2, min_size 7, pen 3 log n), kept only if Binseg agrees within +-3 days
  up/down pairs in one series become one temporary event
  onset = start of the ramp (piecewise ramp fit), not the PELT midpoint
  drill-down (Adtributor) for everyone-level breaks
  DiD vs the rest of the population, 7-day moving-block bootstrap, 95 % CI
Hierarchy: everyone and single-dimension series are always scanned; a pair of
dimensions only under a parent with a confirmed change in the same metric
(CI excludes 0, z >= Z_DRILL, within DRILL_DAYS), except city x channel order cells,
which are always scanned (DECISIONS 141). Reported shifts need z >= the level's max-T
bar, MAXT_K x the median largest |z| on placebo dates (DECISIONS 140). Ratio KPIs with
counts are tested on pooled window sums with overdispersion (DECISIONS 138).
Anchored family (DECISIONS 137): dates from treatment tables (price list, courier
assignment) get pre-registered outcome families with their own alpha, calibrated on
placebo dates. Then: merge duplicates across series, lag search for churn, calendar filter,
spikes and stockouts, substitution and contaminated controls (DECISIONS 139).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import holidays
import numpy as np
import pandas as pd
import ruptures as rpt
from scipy.stats import norm
from statsmodels.tsa.seasonal import STL

from .kpis import CLOGLOG_KPIS, FLIP_KPIS, INVERSE_KPIS, METRIC, POOLED_KPIS, RATIO_KPIS, SMEAR_DAYS, KPISet

# ---------------------------------------------------------------- global parameters

PEN_FACTOR = 3.0          # PELT penalty = PEN_FACTOR * log(n)
MIN_SIZE = 7              # shortest segment between breaks
RAMP_MAX = 35             # longest ramp the onset fit considers
CONFIRM_DAYS = RAMP_MAX // 2  # Binseg must find a break within +-17 days (both inside one ramp)
WINDOW = 28               # days before / after for size and DiD
MIN_AFTER = 14            # an after-window shorter than this (data end) is not enough
MIN_MEAN = 2.0            # shifts are only scanned on count series with >= 2 events a day
PAIR_MAX_DAYS = 150       # an up break and a later down break within this are one event
BOOT = 200                # bootstrap resamples
BLOCK = 7                 # bootstrap block length (days)
Z_REPORT = 5.25           # reported shifts need placebo z >= this (hierarchical scan, set on no-story twins, DECISIONS 57)
MIN_CONFIDENCE = 0.5      # = confidence at Z_REPORT (spikes; shifts compare z itself)
EP_MIN, EP_CUM = 0.3, 0.8  # Adtributor: per-value and cumulative explanatory power
MIN_SURPRISE = 0.002      # below this JS divergence a change counts as uniform
SPECIFIC_GAIN = 1.5       # prefer a narrower segment if its effect is 1.5x larger
MERGE_DAYS = 14           # candidates for one metric this close in time are one event
SPIKE_Z, SPIKE_MIN_RUN = 3.5, 3
SPIKE_MERGE_DAYS = 2      # spikes in several series starting this close are one spike
STOCKOUT_RUN, STOCKOUT_MIN_RATE = 3, 5.0
STOCKOUT_MIN_SKUS = 2     # a stock-out is reported when this many SKUs of a category are out together
STOCKOUT_SHARE = 0.10     # a routine (one-SKU) stock-out explains its category's moves if the SKU sold >= 10 % of it
STOCKOUT_TOPICS = ("vyprodáno",)  # ticket topics an empty shelf writes ("sold out")
LAGS = (0, 7, 14, 28, 42)
LAG_MIN_T = 3.0           # floor of the lag search's bar ...
LAG_ALPHA = 0.05          # ... which is Bonferroni over the (anchor, lag) pairs it tried (DECISIONS 137)
LAG_MATCH_DAYS = 14
YOY_DAYS = 364            # last year's same days (52 weeks), as the verifier's yoy control
YOY_SHARE = 0.5           # a change last year at least half as big = the segment's season
PRICE_Z = 3.0             # a dated price change is one pre-specified test (the verifier's Z_CONFIRM)
Z_DRILL = 4.0             # a parent change this strong (and CI excluding 0) opens its pairs
DRILL_DAYS = 21           # a pair is tested only within this of a confirmed parent change
CALENDAR_MAX_DAYS = 10    # only spikes and temporary changes shorter than this can be "just the calendar"
PAIRS_GATED = False       # True: every pair only under a confirmed parent (DECISIONS 57); False: city x channel
                          # order cells are always scanned (DECISIONS 141)
MAXT_K = 1.85             # reported shifts need z >= MAXT_K x median max-T of their level (DECISIONS 140)
MAXT_STEP = 7             # placebo dates for max-T: every 7th day
MAXT_FLOOR = 4.5          # a level with few series never gets a bar below this
POOLED_MIN = 10           # pooled ratio test: >= 10 events and >= 10 non-events in each of its 4 windows
# Anchored family (DECISIONS 137): pre-registered tests at dates from treatment tables
ANCHOR_ALPHA = 0.18       # expected false anchored finds per run: 0.1 of 1 a year over a ~1.8-year run
ANCHOR_LAGS = tuple(range(0, 57))  # churn after an anchor: any day 0..56 (the family's max dates it)
SERVICE_LAGS = (0,)       # late deliveries and ratings answer a courier switch at once
ANCHOR_NULL_STEP = 1      # placebo dates for the family's null: every day ...
ANCHOR_NULL_GAP = WINDOW + max(ANCHOR_LAGS)  # ... whose windows miss every anchor's windows
ANCHOR_DATE_SMOOTH = 21   # churn after an anchor is dated at the peak of the family's z, averaged over 3 weeks
COURIER_SHIFT = 0.2       # a courier's share of a city's deliveries moving by 20 pp is a switch
COURIER_DAYS = 14         # share in the 14 days from t against the 28 days before


@dataclass
class Candidate:
    id: str
    metric: str
    segment: str
    start_date: str
    end_date: str | None
    direction: str
    magnitude_pct: float
    lag_days: int | None
    caused_by: str | None
    kind: str                    # shift / spike / stockout
    confidence: float
    evidence: str
    series: str                  # "kpi|segment", for the chart
    status: str = "reported"     # reported / explained_by_calendar / uniform_change / not_confirmed / merged / transient
    kpi: str = ""
    ci: tuple[float, float] | None = None
    raw_change_pct: float | None = None
    extra: dict = field(default_factory=dict)

    def row(self) -> dict:
        d = asdict(self)
        d.pop("extra")
        d["z"] = self.extra.get("z")
        return d


# ---------------------------------------------------------------- series prep


@dataclass
class Prepared:
    s: pd.Series            # original values
    x: np.ndarray           # weekly-adjusted (trend + residual)
    z: np.ndarray           # standardized x
    resid_z: np.ndarray     # standardized residual (for spikes)
    scale: float
    clean: np.ndarray | None = None  # s with spike days replaced by trend + seasonal


def prepare(s: pd.Series, smear: int = 0) -> Prepared | None:
    v = s.to_numpy(dtype=float)
    if len(v) < 4 * WINDOW or np.nanstd(v) == 0:
        return None
    res = STL(v, period=7, robust=True).fit()
    x = res.trend + res.resid
    r = res.resid
    # Noise scale of x itself. The STL residual is too small for this: the trend
    # soaks up the slow part of the noise. First differences see all of it and are
    # robust to level shifts: sd = 1.4826 * MAD(diff) / sqrt(2). A rolling KPI
    # (repeat rate: `smear` = 30 days) is smooth from day to day, so its
    # differences are taken `smear` days apart, where the windows do not overlap.
    d = x[max(smear, 1):] - x[:-max(smear, 1)]
    scale = 1.4826 * np.median(np.abs(d - np.median(d))) / math.sqrt(2)
    if scale <= 1e-9:
        scale = float(np.std(d)) / math.sqrt(2)
    if scale <= 1e-9:
        return None
    rscale = 1.4826 * np.median(np.abs(r - np.median(r))) or scale
    rz = (r - np.median(r)) / rscale
    spike = np.abs(rz) > SPIKE_Z
    # break search and levels ignore spike days: a store closure on a holiday is
    # one zero day, not the location of a level shift
    x = np.where(spike, res.trend, x)
    z = (x - np.median(x)) / scale
    clean = np.where(spike, res.trend + res.seasonal, v)
    return Prepared(s, x, z, rz, scale, clean)


def despike(s: pd.Series, pr: Prepared | None = None) -> np.ndarray:
    """The series with spike days (|STL residual z| > SPIKE_Z) replaced by trend +
    seasonal. Shift statistics run on this: a few days of a viral spike inside a
    28-day window are not a level shift, and the spike has its own detector."""
    pr = pr or prepare(s)
    return s.to_numpy(float) if pr is None else pr.clean


def breakpoints(z: np.ndarray) -> list[int]:
    """PELT breaks that Binseg confirms within +-CONFIRM_DAYS."""
    n = len(z)
    pen = PEN_FACTOR * math.log(n)
    sig = z.reshape(-1, 1)
    pelt = rpt.Pelt(model="l2", min_size=MIN_SIZE).fit(sig).predict(pen=pen)[:-1]
    if not pelt:
        return []
    # Binseg is greedy: with the same penalty it misses breaks that a larger break
    # shadows, and on a gradual rise it puts the break elsewhere. Give it half the
    # penalty so "both algorithms agree on the location" is the test, not "both
    # rank it first".
    binseg = rpt.Binseg(model="l2", min_size=MIN_SIZE).fit(sig).predict(pen=pen / 2)[:-1]
    return [b for b in pelt if any(abs(b - c) <= CONFIRM_DAYS for c in binseg)]


def ramp_onset(x: np.ndarray, b: int, lo: int, hi: int) -> tuple[int, int]:
    """Fit level a -> linear ramp -> level c around break b, on x[lo:hi].
    Returns (t0, t1): first day of the ramp and first day at the new level.
    All (t0, t1) pairs are solved at once with the closed-form 2-parameter fit."""
    t = np.arange(lo, hi, dtype=float)
    y = x[lo:hi]
    pairs = [(t0, t1) for t0 in range(max(lo + 7, b - RAMP_MAX), min(b, hi - 7) + 1)
             for t1 in range(t0, min(t0 + RAMP_MAX, hi - 7) + 1)]
    if not pairs or len(y) < 14:
        return b, b
    p = np.array(pairs, dtype=float)
    width = np.maximum(p[:, 1] - p[:, 0], 1)[:, None]
    r = np.clip((t[None, :] - p[:, :1]) / width, 0, 1)
    r = np.where(p[:, 1:2] == p[:, :1], (t[None, :] >= p[:, :1]).astype(float), r)
    q = 1 - r
    s11, s12, s22 = (q * q).sum(1), (q * r).sum(1), (r * r).sum(1)
    b1, b2 = (q * y).sum(1), (r * y).sum(1)
    det = s11 * s22 - s12 ** 2
    ok = det > 1e-9
    explained = np.where(ok, (s22 * b1 ** 2 - 2 * s12 * b1 * b2 + s11 * b2 ** 2) / np.where(ok, det, 1), -np.inf)
    best = int(np.argmax(explained))  # max explained = min SSE
    return int(p[best, 0]), int(p[best, 1])


# ---------------------------------------------------------------- DiD with block bootstrap


def _block_idx(n: int, rng: np.random.Generator, reps: int) -> np.ndarray:
    k = max(1, math.ceil(n / BLOCK))
    starts = rng.integers(0, max(1, n - BLOCK + 1), size=(reps, k))
    idx = (starts[:, :, None] + np.arange(BLOCK)).reshape(reps, -1)[:, :n]
    return np.minimum(idx, n - 1)


def did(seg: np.ndarray, rest: np.ndarray | None, before: slice, after: slice,
        rng: np.random.Generator, ratio: bool = False) -> tuple[float, tuple[float, float], float]:
    """Relative difference-in-differences: (A_s/B_s) / (A_r/B_r) - 1, with a 95 % CI
    from a 7-day moving-block bootstrap. For ratio KPIs, differences of means.
    Without a control (rest is None) it is a plain before/after change."""
    def eff(bs, as_, br, ar):
        m = lambda a: np.nanmean(a, -1)  # holiday days are NaN  # noqa: E731
        if ratio:
            d = m(as_) - m(bs)
            return d - (m(ar) - m(br)) if br is not None else d
        e = m(as_) / np.maximum(m(bs), 1e-9)
        if br is not None:
            e = e / np.maximum(m(ar) / np.maximum(m(br), 1e-9), 1e-9)
        return e - 1

    sb, sa = seg[before], seg[after]
    rb, ra = (rest[before], rest[after]) if rest is not None else (None, None)
    point = float(eff(sb, sa, rb, ra))
    ib, ia = _block_idx(len(sb), rng, BOOT), _block_idx(len(sa), rng, BOOT)
    boot = eff(sb[ib], sa[ia], rb[ib] if rb is not None else None, ra[ia] if ra is not None else None)
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    sd = float(np.nanstd(boot)) or 1e-9
    return point, (float(lo), float(hi)), abs(point) / sd


def _window_means(v: np.ndarray, length: int) -> np.ndarray:
    """m[t] = mean(v[t:t+length]) for every t where the window fits, NaN days left out."""
    ok = ~np.isnan(v)
    c = np.concatenate([[0.0], np.cumsum(np.where(ok, v, 0.0))])
    k = np.concatenate([[0], np.cumsum(ok)])
    return (c[length:] - c[:-length]) / np.maximum(k[length:] - k[:-length], 1)


def did_effects(seg: np.ndarray, rest: np.ndarray | None, gap: int, nb: int = WINDOW, na: int = WINDOW,
                ratio: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """The DiD statistic at every anchor t: before = [t-nb, t), after = [t+gap, t+gap+na).
    Relative change vs the control for counts, difference for ratios. The placebo
    test and the generator's recoverability gate (s2d/calibrate.py) both use it."""
    def effects(v):
        mb, ma = _window_means(v, nb), _window_means(v, na)
        t = np.arange(nb, len(v) - gap - na + 1)
        b, a = mb[t - nb], ma[t + gap]
        return t, (a - b) if ratio else a / np.maximum(b, 1e-9)

    t, es = effects(seg)
    if rest is not None:
        _, er = effects(rest)
        e = es - er if ratio else es / np.maximum(er, 1e-9) - 1
    else:
        e = es if ratio else es - 1
    return t, e


def robust_sd(v: np.ndarray) -> float:
    v = v[~np.isnan(v)]
    sd = 1.4826 * float(np.median(np.abs(v - np.median(v)))) if len(v) else 0.0
    return sd if sd > 1e-9 else (float(np.std(v)) if len(v) else 0.0) or 1e-9


def placebo_z(seg: np.ndarray, rest: np.ndarray | None, t0: int, t1: int, nb: int, na: int,
              ratio: bool = False) -> float:
    """How unusual is the DiD effect at (t0, t1) compared with the same statistic
    at every other date of this series? Robust z against that placebo-in-time
    distribution. This carries the series' own autocorrelation and sparsity,
    which a 7-day bootstrap on 28 days does not see."""
    t, e = did_effects(seg, rest, t1 - t0, nb, na, ratio)
    here = e[t == t0]
    if len(here) == 0:
        return 0.0
    far = np.abs(t - t0) > 2 * WINDOW
    null = e[far]
    if len(null) < 20:
        return 0.0
    med = np.median(null)
    sd = robust_sd(null)
    _last_placebo["max_ratio"] = float(abs(here[0] - med) / (np.max(np.abs(null - med)) or 1e-9))
    return float(abs(here[0] - med) / sd)


_last_placebo: dict = {}


def confidence_from_z(z: float, bar: float = Z_REPORT) -> float:
    """0.5 at the reporting threshold (Z_REPORT, or the level's max-T bar), 0 two units below
    it, 1 two units above."""
    return float(np.clip(0.5 + (z - bar) / 4.0, 0.0, 1.0))


def maxt_bars(ks: KPISet, preps: dict, cache: dict) -> dict[int, float]:
    """The reporting bar per tree level, from this dataset alone (DECISIONS 140). For every
    series of the level that the shift scan can test, the DiD z at every date (_z_by_date);
    at every MAXT_STEP-th date the largest |z| over the level's series is what chance gives
    when nothing happens there (max-T). The bar is MAXT_K times the median of those maxima:
    the median, not an upper quantile, because the dataset's own events sit in the upper
    tail of a story run (a story's 90th percentile is 19 where its twin's is 4.6), and the
    median is the same in a story and its twin. Levels 0 and 1 share a bar; pairs have
    their own (many more, thinner series). A level with only a few series has a small
    maximum, so the bar never drops below MAXT_FLOOR."""
    out = {}
    for name, levels in (("1", (0, 1)), ("2", (2,))):
        cols = []
        for (kpi, seg), s in ks.series.items():
            if _level(seg) not in levels or (kpi, seg) not in preps:
                continue
            if kpi not in RATIO_KPIS and s.mean() < MIN_MEAN:
                continue
            if (kpi, seg) in ks.parts and not seg:
                continue
            z = _z_by_date(ks, kpi, seg, cache)
            if z is not None:
                cols.append(z.reindex(ks.dates).abs().to_numpy()[::MAXT_STEP])
        if len(cols) < 5:
            out[int(name)] = Z_REPORT
            continue
        with np.errstate(all="ignore"):
            m = np.nanmax(np.clip(np.vstack(cols), 0, 50), axis=0)
        m = m[np.isfinite(m)]
        out[int(name)] = round(max(MAXT_FLOOR, float(MAXT_K * np.median(m))), 2) if len(m) >= 20 else Z_REPORT
    return out


# ---------------------------------------------------------------- calendar


def calendar_reason(day: pd.Timestamp, span_end: pd.Timestamp | None = None) -> str | None:
    """Known seasonality: CZ holidays (+-3 d), Black Friday week through Cyber
    Monday, and 1 Dec - 7 Jan (the December season)."""
    cz = holidays.CZ(years=[day.year - 1, day.year, day.year + 1])
    for h in cz:
        if abs((pd.Timestamp(h) - day).days) <= 3:
            return f"státní svátek {cz[h]}"
    nov = pd.Timestamp(day.year, 11, 1)
    bf = nov + pd.Timedelta(days=(4 - nov.weekday()) % 7 + 21)
    if bf - pd.Timedelta(days=7) <= day <= bf + pd.Timedelta(days=4):
        return "Black Friday"
    if day.month == 12 or (day.month == 1 and day.day <= 7):
        return "Vánoce a konec roku"
    return None


def calendar_applies(kind: str, start: str, end: str | None, has_control: bool, smear: int = 0) -> bool:
    """Can a calendar date explain this candidate away? Only a spike or a change
    that is over within CALENDAR_MAX_DAYS. A lasting shift measured against a
    control group cannot be the calendar: the control has the same holidays, so
    the DiD has already removed them. `smear` is the window of a KPI that is a
    rolling measure (repeat rate: 30 days): one holiday moves it for that long."""
    if kind != "shift":
        return True
    if end is not None and (pd.Timestamp(end) - pd.Timestamp(start)).days - smear < CALENDAR_MAX_DAYS:
        return True
    return not has_control


def onset_series(x: np.ndarray, seg: np.ndarray, rest: np.ndarray | None, ratio: bool) -> np.ndarray:
    """The series the ramp is fitted on. With a control group it is the segment
    relative to the control (share of seg + rest for counts, difference for
    ratios), so days that hit both (a holiday when every store is closed) cancel
    instead of pulling the fit. 0/0 days are interpolated."""
    if rest is None:
        return x
    if ratio:
        return pd.Series(seg - rest).interpolate(limit_direction="both").to_numpy()
    tot = seg + rest
    share = np.divide(seg, tot, out=np.full(len(seg), np.nan), where=tot > 0)
    return pd.Series(share).interpolate(limit_direction="both").to_numpy()


def cloglog(v: np.ndarray) -> np.ndarray:
    v = np.clip(v, 1e-6, 1 - 1e-6)
    return np.log(-np.log(1 - v))


def holiday_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """True on CZ public holidays. Shift statistics on counts leave these days out:
    stores close and the e-shop does not, so a channel's control has a different
    holiday response and the DiD alone does not cancel it."""
    cz = holidays.CZ(years=sorted(set(index.year)))
    return np.isin(index.normalize(), pd.DatetimeIndex(list(cz.keys())))


# ---------------------------------------------------------------- pooled ratio KPIs


def pooled_parts(ks: KPISet, kpi: str, seg: str) -> tuple[np.ndarray, ...] | None:
    """(num, den) of the segment and of its control, daily: the complement for one
    dimension, the siblings (same second key, other first key) for a pair."""
    def get(sg):
        if (kpi, sg) in ks.parts:
            return ks.parts[(kpi, sg)]
        if "," in sg and ";" not in sg:  # a union like city=Ostrava,Olomouc
            dim, vals = sg.split("=", 1)
            ps = [ks.parts.get((kpi, f"{dim}={v}")) for v in vals.split(",")]
            if all(p is not None for p in ps):
                return sum(p[0] for p in ps), sum(p[1] for p in ps)
        return None
    me = get(seg)
    if me is None or not seg:
        return None
    parts = seg.split(";")
    if len(parts) == 2:
        first_dim, second = parts[0].split("=")[0], parts[1]
        sib = [v for (k, sg), v in ks.parts.items()
               if k == kpi and sg.endswith(";" + second) and sg.startswith(first_dim + "=") and sg != seg]
        if not sib:
            return None
        rn, rd = sum(p[0] for p in sib), sum(p[1] for p in sib)
    else:
        tot = ks.parts.get((kpi, ""))
        if tot is None:
            return None
        rn, rd = tot[0] - me[0], tot[1] - me[1]
    return tuple(np.asarray(x, float) for x in (me[0], me[1], rn, rd))


def overdispersion(num: np.ndarray, den: np.ndarray) -> float:
    """phi = Pearson chi2 / df of a quasi-binomial GLM of the daily shares on day-of-week
    and 4-week blocks (the level may drift; the days scatter around it). 1 = binomial noise;
    a courier whose bad days come in batches has phi > 1. Never below 1."""
    key = (float(num.sum()), float(den.sum()), len(num), float((num * np.arange(len(num))).sum()))
    if key in _phi_cache:
        return _phi_cache[key]
    ok = den > 0
    if ok.sum() < 30:
        return 1.0
    p = np.clip(num[ok] / den[ok], 0, 1)
    n = len(num)
    t = np.arange(n)[ok]
    # 4-week blocks carry the level, day of week (Monday the base) the weekly pattern; a full
    # set of both would be collinear
    X = np.column_stack([np.eye(n // 28 + 1)[t // 28], np.eye(7)[t % 7][:, 1:]])
    X = X[:, X.sum(0) > 0]
    import warnings

    import statsmodels.api as sm
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            fit = sm.GLM(p, X, family=sm.families.Binomial(), var_weights=den[ok]).fit()
        phi = float(fit.pearson_chi2 / max(fit.df_resid, 1))
    except Exception:  # noqa: BLE001  (perfect separation on a tiny series)
        phi = 1.0
    phi = max(1.0, phi) if np.isfinite(phi) else 1.0
    _phi_cache[key] = phi
    return phi


_phi_cache: dict = {}


def _win(v: np.ndarray, length: int) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(v)])
    return c[length:] - c[:-length]


def pooled_effects(ns, ds, nr, dr, gap: int, nb: int, na: int, kind: str, phi_s: float = 1.0,
                   phi_r: float = 1.0) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """At every anchor t (before [t-nb, t), after [t+gap, t+gap+na)) the DiD of the pooled
    ratio: log-odds of the window sums for a share ("share"), sum / count for a mean ("mean").
    Returns t, effect, analytic se (share only: binomial variance x phi; NaN for a mean) and
    whether every window has >= POOLED_MIN events and non-events (share) or values (mean)."""
    t = np.arange(nb, len(ns) - gap - na + 1)
    out = []
    for n_, d_ in ((ns, ds), (nr, dr)):
        b_n, b_d = _win(n_, nb)[t - nb], _win(d_, nb)[t - nb]
        a_n, a_d = _win(n_, na)[t + gap], _win(d_, na)[t + gap]
        out.append((b_n, b_d, a_n, a_d))
    (sbn, sbd, san, sad), (rbn, rbd, ran, rad) = out
    if kind == "share":
        lo = lambda n_, d_: np.log((n_ + 0.5) / (d_ - n_ + 0.5))  # noqa: E731
        eff = (lo(san, sad) - lo(sbn, sbd)) - (lo(ran, rad) - lo(rbn, rbd))
        var_s = sum(1 / (n_ + 0.5) + 1 / (d_ - n_ + 0.5) for n_, d_ in ((sbn, sbd), (san, sad)))
        var_r = sum(1 / (n_ + 0.5) + 1 / (d_ - n_ + 0.5) for n_, d_ in ((rbn, rbd), (ran, rad)))
        se = np.sqrt(phi_s * var_s + phi_r * var_r)
        cells = [(sbn, sbd), (san, sad), (rbn, rbd), (ran, rad)]
        valid = np.all([(n_ >= POOLED_MIN) & (d_ - n_ >= POOLED_MIN) for n_, d_ in cells], axis=0)
    else:
        m = lambda n_, d_: n_ / np.maximum(d_, 1e-9)  # noqa: E731
        eff = (m(san, sad) - m(sbn, sbd)) - (m(ran, rad) - m(rbn, rbd))
        se = np.full(len(t), np.nan)
        valid = np.all([d_ >= POOLED_MIN for d_ in (sbd, sad, rbd, rad)], axis=0)
    return t, eff, se, valid


def pooled_test(ks: KPISet, kpi: str, seg: str, t0: int, t1: int) -> dict | None:
    """The DiD of a ratio KPI from pooled counts (DECISIONS 138), at (t0, t1) with the usual
    28-day windows. Noise = the larger of the placebo spread (the same statistic at every date
    more than 2 windows away, valid windows only) and the phi-scaled binomial se. z = |effect -
    placebo median| / noise, CI = effect +- 1.96 noise. The size is reported as the DiD of the
    pooled shares (percentage points) or means. None if the windows lack events."""
    parts = pooled_parts(ks, kpi, seg)
    if parts is None:
        return None
    ns, ds, nr, dr = parts
    kind = POOLED_KPIS[kpi]
    phi_s = overdispersion(ns, ds) if kind == "share" else 1.0
    phi_r = overdispersion(nr, dr) if kind == "share" else 1.0
    gap = t1 - t0
    t, eff, se, valid = pooled_effects(ns, ds, nr, dr, gap, WINDOW, WINDOW, kind, phi_s, phi_r)
    here = np.flatnonzero(t == t0)
    if not len(here):
        return None
    i = here[0]
    res = {"phi": round(max(phi_s, phi_r), 2), "valid": bool(valid[i])}
    if not valid[i]:
        return res
    null = eff[valid & (np.abs(t - t0) > 2 * WINDOW)]
    if len(null) < 20:
        res["valid"] = False
        return res
    med, sd = float(np.median(null)), robust_sd(null)
    noise = max(sd, float(se[i]) if np.isfinite(se[i]) else 0.0)
    point = float(eff[i])
    # the size in the KPI's own units: DiD of the pooled shares or means
    w = lambda v, a, b: v[a:b].sum()  # noqa: E731
    b0, a0, a1 = t0 - WINDOW, t1, t1 + WINDOW
    ms = lambda n_, d_, a, b: w(n_, a, b) / max(w(d_, a, b), 1e-9)  # noqa: E731
    size = (ms(ns, ds, a0, a1) - ms(ns, ds, b0, t0)) - (ms(nr, dr, a0, a1) - ms(nr, dr, b0, t0))
    scale = size / point if abs(point) > 1e-12 else 0.0
    lo, hi = point - 1.96 * noise, point + 1.96 * noise
    res.update(point=point, size=float(size), ci_size=tuple(sorted((lo * scale, hi * scale))),
               excludes=bool(lo > 0 or hi < 0), z=abs(point - med) / noise,
               max_ratio=float(abs(point - med) / (np.max(np.abs(null - med)) or 1e-9)))
    return res


# ---------------------------------------------------------------- the scan


def _rest(ks: KPISet, kpi: str, seg: str, s: pd.Series) -> pd.Series | None:
    """Control group for the DiD. For a single-key segment it is everyone else.
    For a pair like city=Brno;channel=store it is the same second key in the
    other values of the first (stores in other cities): like is compared with
    like, so channel- or segment-specific seasonality cancels too."""
    if not seg:
        return None
    if (kpi, seg) in ks.parts:
        return _rest_ratio(ks, kpi, seg, s)
    if kpi in RATIO_KPIS:
        return ks.get(kpi, "")
    parts = seg.split(";")
    if len(parts) == 2 and "," not in seg:
        first_dim, second = parts[0].split("=")[0], parts[1]
        sib = [v for (k, sg), v in ks.series.items()
               if k == kpi and sg.endswith(";" + second) and sg.startswith(first_dim + "=") and sg != seg]
        if sib:
            return sum(sib).reindex(s.index)
    if len(parts) == 1 and seg.startswith("category="):
        # an order counts once per category it contains, so "everyone minus these
        # categories" is not a count of anything: compare with the other categories
        cats = set(seg.split("=", 1)[1].split(","))
        others = [v for (k, sg), v in ks.series.items()
                  if k == kpi and sg.startswith("category=") and ";" not in sg and sg.split("=", 1)[1] not in cats]
        return sum(others).reindex(s.index) if others else None
    total = ks.get(kpi, "")
    if total is None:
        return None
    return (total.reindex(s.index) - s).clip(lower=0)


@dataclass
class TestArrays:
    seg: np.ndarray            # what the DiD and the placebo run on
    rest: np.ndarray | None    # its control (None: no control group)
    raw_seg: np.ndarray        # before the cloglog transform and the holiday mask
    raw_rest: np.ndarray | None
    ratio: bool
    index: pd.DatetimeIndex


def test_arrays(ks: KPISet, kpi: str, seg: str, s: pd.Series | None = None, pr: Prepared | None = None,
                cache: dict | None = None) -> TestArrays | None:
    """Segment and control arrays exactly as the shift test sees them: spike days
    replaced (counts), cloglog (shares), holidays masked (counts)."""
    s = s if s is not None else _union_series(ks, kpi, seg)
    if s is None:
        return None
    ratio = kpi in RATIO_KPIS
    rest = _rest(ks, kpi, seg, s)
    sv = s.to_numpy(float) if ratio else despike(s, pr or prepare(s))
    if rest is None:
        rv = None
    else:
        rest = rest.reindex(s.index)
        if ratio:
            rv = rest.to_numpy(float)
        else:
            ck = (kpi, seg, "rest")
            if cache is not None and ck in cache:
                rv = cache[ck]
            else:
                rv = despike(rest)
                if cache is not None:
                    cache[ck] = rv
    raw_sv, raw_rv = sv, rv
    if kpi in CLOGLOG_KPIS:
        # P(buy in 30 d) = 1 - exp(-30 * rate) for a Poisson buyer, so cloglog(r) =
        # log(30 * rate): a seasonal multiplier common to every segment becomes
        # an additive constant and cancels in the DiD, whatever the base rate
        sv, rv = cloglog(sv), (None if rv is None else cloglog(rv))
    if not ratio:
        hol = holiday_mask(s.index)
        sv = np.where(hol, np.nan, sv)
        rv = None if rv is None else np.where(hol, np.nan, rv)
    return TestArrays(sv, rv, raw_sv, raw_rv, ratio, s.index)


def _rest_ratio(ks: KPISet, kpi: str, seg: str, s: pd.Series) -> pd.Series | None:
    """Control for a ratio KPI with numerator and denominator: the same ratio
    over the complement (pair segment: the siblings, as in _rest)."""
    parts = seg.split(";")
    if len(parts) == 2:
        first_dim, second = parts[0].split("=")[0], parts[1]
        sib = [v for (k, sg), v in ks.parts.items()
               if k == kpi and sg.endswith(";" + second) and sg.startswith(first_dim + "=") and sg != seg]
        if sib:
            num, den = sum(p[0] for p in sib), sum(p[1] for p in sib)
            return (num / den.where(den > 0)).reindex(s.index).interpolate(limit_direction="both")
    if (kpi, "") not in ks.parts:
        return ks.get(kpi, "")
    num = ks.parts[(kpi, "")][0] - ks.parts[(kpi, seg)][0]
    den = ks.parts[(kpi, "")][1] - ks.parts[(kpi, seg)][1]
    return (num / den.where(den > 0)).reindex(s.index).interpolate(limit_direction="both")


def _windows(n: int, t0: int, t1: int, end: int | None = None) -> tuple[slice, slice] | None:
    end = n if end is None else min(end, n)
    before = slice(max(0, t0 - WINDOW), t0)
    after = slice(t1, min(end, t1 + WINDOW))
    if before.stop - before.start < MIN_AFTER or after.stop - after.start < MIN_AFTER:
        return None
    return before, after


def _seg_keys(seg: str) -> set[str]:
    out = set()
    for part in filter(None, seg.split(";")):
        k, v = part.split("=", 1)
        out |= {f"{k}={x}" for x in v.split(",")}
    return out


def adtributor(ks: KPISet, kpi: str, before: slice, after: slice) -> tuple[str, float]:
    """Which single dimension explains the change? Returns (segment text, surprise).
    Values with explanatory power >= EP_MIN are kept until EP_CUM is reached;
    the dimension with the highest total JS surprise wins."""
    total = ks.get(kpi, "")
    if total is None:
        return "", 0.0
    d_total = total.iloc[after].mean() - total.iloc[before].mean()
    if abs(d_total) < 1e-9:
        return "", 0.0
    best = ("", 0.0)
    dims = ks.dims.get(kpi, []) + (["category"] if kpi == "orders" else [])
    for dim in dims:
        vals = [(seg, s) for (k, seg), s in ks.series.items()
                if k == kpi and seg.startswith(f"{dim}=") and ";" not in seg]
        if len(vals) < 2:
            continue
        b = np.array([s.iloc[before].mean() for _, s in vals])
        a = np.array([s.iloc[after].mean() for _, s in vals])
        p, q = b / max(b.sum(), 1e-9), a / max(a.sum(), 1e-9)
        m = (p + q) / 2
        with np.errstate(divide="ignore", invalid="ignore"):
            js_terms = 0.5 * (np.where(p > 0, p * np.log(p / m), 0) + np.where(q > 0, q * np.log(q / m), 0))
        ep = (a - b) / d_total
        order = np.argsort(-ep)
        chosen, cum = [], 0.0
        for i in order:
            if ep[i] < EP_MIN or cum >= EP_CUM:
                break
            chosen.append(i)
            cum += ep[i]
        if not chosen:
            continue
        surprise = float(np.sum(js_terms[chosen]))
        if surprise > best[1]:
            values = ",".join(vals[i][0].split("=", 1)[1] for i in chosen)
            best = (f"{dim}={values}", surprise)
    return best


def _union_series(ks: KPISet, kpi: str, seg: str) -> pd.Series | None:
    """Series for a multi-value segment like 'category=a,b' (sum of the parts)."""
    s = ks.get(kpi, seg)
    if s is not None or "," not in seg:
        return s
    dim, vals = seg.split("=", 1)
    parts = [ks.get(kpi, f"{dim}={v}") for v in vals.split(",")]
    return None if any(p is None for p in parts) else sum(parts)


def _shift(kpi: str, seg: str, s: pd.Series, b: int, level: float, lo: int, right: int,
           end: int | None) -> Candidate | None:
    """A shift candidate at break b, before the onset fit and the DiD."""
    w = _windows(len(s), b, b, right)
    if w is None:
        return None
    return Candidate(
        id="", metric=METRIC[kpi], segment=seg, kpi=kpi, start_date=str(s.index[b].date()),
        end_date=str(s.index[end].date()) if end is not None else None,
        direction="up" if level > 0 else "down", magnitude_pct=0.0,
        lag_days=None, caused_by=None, kind="shift", confidence=0.0, evidence="",
        series=f"{kpi}|{seg}",
        extra={"t0": b, "t1": b, "lo": lo, "right": right, "before": w[0], "after": w[1]})


def _level(seg: str) -> int:
    """0 = everyone, 1 = one dimension (city=Brno, category=a,b), 2 = a pair."""
    return 0 if not seg else seg.count(";") + 1


def _series_breaks(kpi: str, seg: str, s: pd.Series, pr: Prepared) -> list[Candidate]:
    """Shift candidates of one series: confirmed breaks, ramps joined, up/down pairs
    as temporary events (the end break kept as a fallback onset of its own)."""
    n = len(s)
    bks = breakpoints(pr.z)
    levels = []
    for b in bks:
        lo, hi = max(0, b - WINDOW), min(n, b + WINDOW)
        levels.append(pr.x[b:hi].mean() - pr.x[lo:b].mean())
    # PELT cuts a long ramp into steps: same-direction breaks closer than
    # RAMP_MAX are one ramp, starting at the first of them
    keep = [i for i in range(len(bks)) if i == 0 or not (
        bks[i] - bks[i - 1] <= RAMP_MAX and np.sign(levels[i]) == np.sign(levels[i - 1]))]
    bks, levels = [bks[i] for i in keep], [levels[i] for i in keep]
    # pair an up break with a later opposite break: a temporary event
    out, used = [], set()
    for i, b in enumerate(bks):
        if i in used:
            continue
        end = None
        for j in range(i + 1, len(bks)):
            if j not in used and np.sign(levels[j]) == -np.sign(levels[i]) and bks[j] - b <= PAIR_MAX_DAYS:
                end = j
                break
        if end is not None:
            used.add(end)
        right = bks[end] if end is not None else n
        lo = bks[i - 1] if i > 0 else 0
        c = _shift(kpi, seg, s, b, levels[i], lo, right, bks[end] if end is not None else None)
        if end is not None:
            # if the pair is not confirmed as one temporary event, its end
            # break is still a candidate onset of its own
            nxt = bks[end + 1] if end + 1 < len(bks) else n
            fb = _shift(kpi, seg, s, bks[end], levels[end], b, nxt, None)
            if c is None:
                c = fb
            elif fb is not None:
                c.extra["fallback"] = fb
        if c is not None:
            out.append(c)
    return out


def _parent_of(parent: Candidate, kpi: str, seg: str) -> bool:
    """Is `parent` (a confirmed level-0/1 change) above the pair `seg` of `kpi`?
    Same metric, and the pair contains one of the parent's key=value items
    (everyone is above every pair)."""
    return parent.metric == METRIC[kpi] and (not parent.segment or bool(_seg_keys(parent.segment) & _seg_keys(seg)))


def scan(ks: KPISet, seed: int = 0, stats: dict | None = None) -> list[Candidate]:
    """Hierarchical scan. Level 0 (everyone) and level 1 (one dimension) series are
    always scanned. A pair (city=Brno;channel=store) is scanned only under a parent
    with a confirmed change in the same metric (CI excludes 0, z >= Z_DRILL: the
    parent need not be reportable, it is diluted by its other half), and only its
    shifts whose ramp lies within DRILL_DAYS of that change are tested. `stats` receives how many series
    and DiD tests that took."""
    rng = np.random.default_rng(seed)  # bootstrap only; fixed so a run is repeatable
    preps: dict[tuple[str, str], Prepared] = {}
    clean_rest: dict[tuple, np.ndarray] = {}
    st = {"series": len(ks.series), "scanned": {0: 0, 1: 0, 2: 0}, "tests": {0: 0, 1: 0, 2: 0}, "price_tests": 0}
    n_id = 0

    def new_id() -> str:
        nonlocal n_id
        n_id += 1
        return f"C{n_id:03d}"

    for (kpi, seg), s in ks.series.items():
        pr = prepare(s, SMEAR_DAYS.get(kpi, 0))
        if pr is not None:
            preps[(kpi, seg)] = pr  # spikes use every series

    def breaks(keys) -> list[Candidate]:
        raw = []
        for kpi, seg in keys:
            pr, s = preps.get((kpi, seg)), ks.series[(kpi, seg)]
            if pr is None or (kpi not in RATIO_KPIS and s.mean() < MIN_MEAN):
                continue  # too sparse for shifts
            if (kpi, seg) in ks.parts and not seg:
                continue  # a share of everyone has no control; its segments are scanned directly
            st["scanned"][_level(seg)] += 1
            raw += _series_breaks(kpi, seg, s, pr)
        return raw

    def evaluate(raw: list[Candidate], gate=None) -> list[Candidate]:
        """Onset fit, DiD, placebo z and status for each raw candidate. `gate(c)`
        (after the onset fit) decides whether a drilled candidate is tested at all."""
        out: list[Candidate] = []
        while raw:
            c = raw.pop(0)
            fb = c.extra.pop("fallback", None)
            s = ks.get(c.kpi, c.segment)
            before, after = c.extra["before"], c.extra["after"]
            raw_change = s.iloc[after].mean() / max(s.iloc[before].mean(), 1e-9) - 1
            c.raw_change_pct = round(100 * raw_change, 1)
            if not c.segment:
                seg, surprise = adtributor(ks, c.kpi, before, after)
                if surprise < MIN_SURPRISE or not seg:
                    c.status = "uniform_change"
                    c.evidence = "změna stejná ve všech segmentech, od sezónnosti ji nejde odlišit"
                    out.append(c)
                    if fb is not None:
                        raw.insert(0, fb)
                    continue
                c.segment = seg
                c.extra["surprise"] = surprise
                s = _union_series(ks, c.kpi, seg)
                if s is None:
                    c.status = "uniform_change"
                    out.append(c)
                    if fb is not None:
                        raw.insert(0, fb)
                    continue
            ratio = c.kpi in RATIO_KPIS
            pr = preps.get((c.kpi, c.segment)) or prepare(s)
            ta = test_arrays(ks, c.kpi, c.segment, s, pr, clean_rest)
            sv, rv, raw_sv, raw_rv = ta.seg, ta.rest, ta.raw_seg, ta.raw_rest
            b = c.extra["t0"]
            t0, t1 = ramp_onset(onset_series(pr.x, sv, rv, ratio), b,
                                max(c.extra["lo"], b - 60), min(c.extra["right"], b + 60))
            w = _windows(len(s), t0, t1, c.extra["right"])
            if w is None or (gate is not None and not gate(c, s.index[t0], s.index[t1])):
                if fb is not None:
                    raw.insert(0, fb)
                continue
            before, after = w
            nb, na = before.stop - before.start, after.stop - after.start
            c.start_date = str(s.index[t0].date())
            c.extra.update(t0=t0, t1=t1, before=before, after=after)
            st["tests"][_level(c.series.split("|", 1)[1])] += 1
            pooled = pooled_test(ks, c.kpi, c.segment, t0, t1) if c.kpi in POOLED_KPIS else None
            if pooled is not None and not pooled["valid"]:
                # too few late parcels (or reviews) in a window to say anything: not tested
                c.status, c.extra["z"] = "not_confirmed", 0.0
                c.evidence = f"{c.kpi} {c.segment}: v některém okně méně než {POOLED_MIN} událostí, netestováno"
                out.append(c)
                if fb is not None:
                    raw.insert(0, fb)
                continue
            if pooled is not None:
                point, ci, z = pooled["size"], pooled["ci_size"], pooled["z"]
                c.extra["phi"] = pooled["phi"]
                _last_placebo["max_ratio"] = pooled["max_ratio"]
            else:
                point, ci, _ = did(sv, rv, before, after, rng, ratio=ratio)
                z = placebo_z(sv, rv, t0, t1, nb, na, ratio)
            c.extra["z"] = round(z, 2)
            c.extra["max_ratio"] = round(_last_placebo.get("max_ratio", 0), 2)
            c.ci = (round(100 * ci[0], 1), round(100 * ci[1], 1))
            c.magnitude_pct = round(100 * point, 1)
            c.direction = "up" if point > 0 else "down"
            bar = bars[min(_level(c.series.split("|", 1)[1]), 2) or 1]
            c.extra["bar"] = bar
            c.confidence = round(confidence_from_z(z, bar), 2)
            c.evidence = (f"{c.kpi} {c.segment or 'vše'}: {c.raw_change_pct:+.1f} % (28 d po vs před), "
                          f"proti zbytku {c.magnitude_pct:+.1f} %, 95% CI {c.ci[0]:+.1f}..{c.ci[1]:+.1f} %")
            if pooled is not None:
                c.evidence += f" (sečtené počty v oknech, nadrozptyl φ = {pooled['phi']})"
            if c.kpi in INVERSE_KPIS:
                _invert(c, raw_sv, raw_rv, before, after)
            if c.kpi in FLIP_KPIS:  # more 1-2 star reviews = the rating falls
                c.direction = "down" if c.direction == "up" else "up"
            if ci[0] <= 0 <= ci[1]:
                c.status = "not_confirmed"
            elif z < bar:  # not the rounded confidence: z 4.99 is below 5
                c.status = "not_confirmed"
            elif (calendar_applies(c.kind, c.start_date, c.end_date, rv is not None, SMEAR_DAYS.get(c.kpi, 0))
                  and (reason := calendar_reason(pd.Timestamp(c.start_date)))):
                c.status = "explained_by_calendar"
                c.evidence += f"; {reason}"
            elif (ly := last_year(sv, rv, before, after, rng, ratio, point)) is not None:
                c.status = "seasonal"
                c.evidence += f"; loni ve stejných dnech {100 * ly:+.1f} % proti zbytku: sezóna"
            out.append(c)
            if fb is not None and c.status != "reported":
                raw.insert(0, fb)
        return out

    bars = maxt_bars(ks, preps, clean_rest) if MAXT_K else {1: Z_REPORT, 2: Z_REPORT}
    st["bars"] = bars
    out = evaluate(breaks([k for k in ks.series if _level(k[1]) <= 1]))
    prices = price_candidates(ks, rng)
    st["price_tests"] = len(prices)
    # drill-down: pairs under a confirmed level-0/1 change of the same metric
    parents = [c for c in out + prices if c.kind == "shift" and c.status in ("reported", "not_confirmed")
               and c.ci is not None and not c.ci[0] <= 0 <= c.ci[1] and c.extra.get("z", 0) >= Z_DRILL]
    def open_cell(kpi: str, seg: str) -> bool:
        # orders of one city x channel cell are scanned without a parent: a store-only change
        # is diluted to ~1/3 in its city and ~1/10 in its channel, so the parent never confirms
        # (DECISIONS 141). The pairs' own max-T bar pays for the larger family
        return not PAIRS_GATED and kpi == "orders" and seg.startswith("city=") and ";channel=" in seg
    pair_keys = [(kpi, seg) for kpi, seg in ks.series
                 if _level(seg) == 2 and (open_cell(kpi, seg) or any(_parent_of(p, kpi, seg) for p in parents))]

    def near_parent(c: Candidate, t0: pd.Timestamp, t1: pd.Timestamp) -> bool:
        # distance from the parent's onset to the pair's ramp [t0, t1]: a long ramp
        # whose fitted start is early still contains the parent's change
        def dist(p):
            d = pd.Timestamp(p.start_date)
            return 0 if t0 <= d <= t1 else min(abs((d - t0).days), abs((d - t1).days))
        return any(_parent_of(p, c.kpi, c.segment) and dist(p) <= DRILL_DAYS for p in parents)

    out += evaluate(breaks(pair_keys), gate=lambda c, t0, t1: open_cell(c.kpi, c.segment) or near_parent(c, t0, t1))
    out += prices
    # the anchor catalogue is fixed from treatment tables before its tests run (pre-registration)
    anchors = anchor_catalogue(ks)
    st["anchors"] = [{k: (str(v.date()) if isinstance(v, pd.Timestamp) else v) for k, v in a.items()} for a in anchors]
    anchored = anchored_candidates(ks, anchors, prices, rng, clean_rest)
    st["anchor_tests"] = len(anchored)
    out += anchored
    # a significant price response below the z threshold can still be corroborated
    # by a confirmed shift at the same time (see merge)
    pool = [c for c in out if c.status == "reported" and c.extra.get("source") != "price"] + [
        c for c in prices if c.status == "reported" or (c.status == "not_confirmed" and c.extra.get("significant"))]
    reported = merge(pool)
    absorb_into_anchored(reported)
    mirrors(reported)
    control_moved(reported)
    churn_consequences(reported)
    out = [c for c in out if not any(c is p for p in pool)] + pool
    out += spikes(ks, preps)
    out += stockouts(ks)
    explained_by_stockout(out)
    substitution(out, ks)
    contaminated_control(out, ks, rng)
    for c in sorted(out, key=lambda c: (c.status != "reported", c.start_date, c.metric)):
        c.id = new_id()
    lag_search([c for c in out if c.status == "reported"], ks, preps)
    st["tests_total"] = sum(st["tests"].values()) + st["price_tests"]
    st["scanned_total"] = sum(st["scanned"].values())
    if stats is not None:
        stats.update(st)
    return sorted(out, key=lambda c: c.id)


def last_year(sv: np.ndarray, rv: np.ndarray | None, before: slice, after: slice, rng, ratio: bool,
              point: float) -> float | None:
    """The same DiD on the same days YOY_DAYS earlier (52 weeks: same weekdays). If last year
    the segment moved the same way against the rest, at least YOY_SHARE as much and with a CI
    excluding 0, the change is the segment's own season, not an event: its DiD, else None.
    Needs the full windows a year back in the data (DECISIONS 136)."""
    if rv is None or before.start - YOY_DAYS < 0:
        return None
    b = slice(before.start - YOY_DAYS, before.stop - YOY_DAYS)
    a = slice(after.start - YOY_DAYS, after.stop - YOY_DAYS)
    if np.isnan(sv[b]).all() or np.isnan(sv[a]).all():
        return None
    ly, ci, _ = did(sv, rv, b, a, rng, ratio=ratio)
    if ci[0] <= 0 <= ci[1] or np.sign(ly) != np.sign(point) or abs(ly) < YOY_SHARE * abs(point):
        return None
    return float(ly)


def _invert(c: Candidate, sv: np.ndarray, rv: np.ndarray | None, before: slice, after: slice) -> None:
    """Repeat rate -> churn: fewer repeat buyers is more churn. The magnitude is
    the relative DiD change of the lapse share (1 - repeat rate), the part of the
    active customers who did not come back; the CI and z stay those of the
    repeat-rate DiD (in percentage points)."""
    def lapse(v, w):
        return 1 - float(np.nanmean(v[w]))
    rel = lapse(sv, after) / max(lapse(sv, before), 1e-9)
    if rv is not None:
        rel /= max(lapse(rv, after) / max(lapse(rv, before), 1e-9), 1e-9)
    c.direction = "down" if c.direction == "up" else "up"
    c.extra["repeat_rate_pp"] = c.magnitude_pct
    c.magnitude_pct = round(100 * (rel - 1), 1)
    c.evidence = (f"opakované nákupy {c.segment}: {c.extra['repeat_rate_pp']:+.1f} p.b. proti zbytku "
                  f"(95% CI {c.ci[0]:+.1f}..{c.ci[1]:+.1f} p.b.), podíl neopakujících {c.magnitude_pct:+.1f} %")


# ---------------------------------------------------------------- price changes


def price_candidates(ks: KPISet, rng) -> list[Candidate]:
    """A price change in product_prices is visible data. For each change date, test
    the orders of the repriced categories against the other categories."""
    pc = ks.events.get("price_changes")
    by_cat = ks.events.get("orders_by_category")
    if pc is None or by_cat is None or pc.empty:
        return []
    out = []
    for day, g in pc.groupby("valid_from"):
        cats = sorted(g["category"].unique())
        day = pd.Timestamp(day)
        seg_s = _union_series(ks, "orders", "category=" + ",".join(cats))
        ta = None if seg_s is None else test_arrays(ks, "orders", "category=" + ",".join(cats), seg_s)
        if ta is None or ta.rest is None:
            continue  # control = the other categories (see _rest)
        t0 = int(seg_s.index.get_indexer([day])[0])
        if t0 < 0:
            continue
        # The verifier's test (s2d/verify.py): raw daily counts (no despiking, no holiday
        # mask: a price response is not a spike), windows [T, T+28) vs [T-28, T)
        sv = seg_s.to_numpy(float)
        rv = _rest(ks, "orders", "category=" + ",".join(cats), seg_s)
        rv = None if rv is None else rv.reindex(seg_s.index).to_numpy(float)
        w = _windows(len(seg_s), t0, t0)
        if w is None or rv is None:
            continue
        point, ci, _ = did(sv, rv, *w, rng)
        z = placebo_z(sv, rv, t0, t0, w[0].stop - w[0].start, w[1].stop - w[1].start)
        mr = _last_placebo.get("max_ratio", 0)
        pct = float(g["pct"].median())
        c = Candidate(
            id="", metric="purchase_rate", segment="category=" + ",".join(cats), kpi="orders",
            start_date=str(day.date()), end_date=None, direction="up" if point > 0 else "down",
            magnitude_pct=round(100 * point, 1), lag_days=None, caused_by=None, kind="shift",
            confidence=round(confidence_from_z(z), 2),
            evidence=(f"ceník: {pct:+.0f} % u {', '.join(cats)} od {day.date()}; objednávky těchto "
                      f"kategorií proti ostatním {100 * point:+.1f} %, 95% CI {100 * ci[0]:+.1f}..{100 * ci[1]:+.1f} %"),
            series="orders|category=" + ",".join(cats), ci=(round(100 * ci[0], 1), round(100 * ci[1], 1)),
            extra={"source": "price", "price_pct": pct, "z": round(z, 2), "max_ratio": round(mr, 2)})
        c.extra["significant"] = not ci[0] <= 0 <= ci[1]
        # One test per dated price change the data shows, not a search over series, so it
        # needs the verifier's bar, not the scan's: a significant response against the
        # price (dearer -> fewer orders) with z >= PRICE_Z (DECISIONS 135)
        against = (point < 0) == (pct > 0)
        if not c.extra["significant"] or not against or z < PRICE_Z:
            c.status = "not_confirmed"
        out.append(c)
    return out


# ---------------------------------------------------------------- anchored family


def anchor_catalogue(ks: KPISet) -> list[dict]:
    """Dates the data itself names as interventions, read from treatment tables only, before
    any outcome is tested: price changes (product_prices.valid_from) and courier switches
    (a courier's share of a city's deliveries moving by COURIER_SHIFT, from the delivery
    assignment). Never an outcome KPI (DECISIONS 137)."""
    out = []
    pc = ks.events.get("price_changes")
    if pc is not None and not pc.empty:
        for day, g in pc.groupby("valid_from"):
            out.append({"kind": "price", "date": pd.Timestamp(day),
                        "segment": "category=" + ",".join(sorted(g["category"].unique())),
                        "pct": round(float(g["pct"].median()), 1)})
    ca = ks.events.get("courier_assign")
    if ca is not None and not ca.empty:
        ca = ca.assign(date=pd.to_datetime(ca["date"]))
        found = []
        for city, g in ca.groupby("city"):
            tab = g.pivot_table(index="date", columns="courier", values="n", aggfunc="sum").reindex(ks.dates).fillna(0)
            tot = tab.sum(1).to_numpy()
            if tot.sum() == 0:
                continue
            for courier in tab.columns:
                n = tab[courier].to_numpy()
                c = np.concatenate([[0.0], np.cumsum(n)])
                ct = np.concatenate([[0.0], np.cumsum(tot)])
                t = np.arange(WINDOW, len(n) - COURIER_DAYS + 1)
                after = (c[t + COURIER_DAYS] - c[t]) / np.maximum(ct[t + COURIER_DAYS] - ct[t], 1)
                before = (c[t] - c[t - WINDOW]) / np.maximum(ct[t] - ct[t - WINDOW], 1)
                d = after - before
                i = 0
                while i < len(t):  # each run of |d| >= COURIER_SHIFT is one switch, at its peak
                    if abs(d[i]) < COURIER_SHIFT:
                        i += 1
                        continue
                    j = i
                    while j < len(t) and abs(d[j]) >= COURIER_SHIFT and np.sign(d[j]) == np.sign(d[i]):
                        j += 1
                    k = i + int(np.argmax(np.abs(d[i:j])))
                    found.append((ks.dates[t[k]], city, courier, float(d[k])))
                    i = j
        # one switch moves two couriers (one in, one out), often in several cities on the same
        # days: everything within 3 days is one anchor, named after the courier that gained most
        found.sort()
        groups: list[list] = []
        for f in found:
            if groups and (f[0] - groups[-1][0][0]).days <= 3:
                groups[-1].append(f)
            else:
                groups.append([f])
        for g in groups:
            cities = sorted({f[1] for f in g})
            gain = max(g, key=lambda f: f[3])
            out.append({"kind": "courier", "date": min(f[0] for f in g), "segment": "city=" + ",".join(cities),
                        "cities": cities, "courier": gain[2], "share_pp": round(100 * gain[3], 1)})
    return sorted(out, key=lambda a: a["date"])


def _z_by_date(ks: KPISet, kpi: str, seg: str, cache: dict) -> pd.Series | None:
    """The DiD statistic of (kpi, seg) at every possible date T (before [T-28, T), after
    [T, T+28), no gap), as a robust z against all dates of the series. Indexed by T."""
    key = ("zdate", kpi, seg)
    if key in cache:
        return cache[key]
    s = _union_series(ks, kpi, seg)
    ta = None if s is None else test_arrays(ks, kpi, seg, s, None, cache)
    out = None
    if ta is not None and ta.rest is not None and (kpi in RATIO_KPIS or s.mean() >= 0.5):
        t, e = did_effects(ta.seg, ta.rest, 0, WINDOW, WINDOW, ta.ratio)
        ok = np.isfinite(e)
        if ok.sum() >= 60:
            z = (e - np.median(e[ok])) / robust_sd(e[ok])
            out = pd.Series(z, index=s.index[t])
    cache[key] = out
    return out


def _family_table(ks: KPISet, outcomes: list[tuple[str, str]], lags: tuple, cache: dict) -> pd.DataFrame:
    """Columns (kpi, seg, lag): the z of that outcome lag days after the anchor date (row)."""
    cols = {}
    for kpi, seg in outcomes:
        z = _z_by_date(ks, kpi, seg, cache)
        if z is None:
            continue
        for lag in lags:
            cols[(kpi, seg, lag)] = z.shift(-lag, freq="D").reindex(ks.dates)
    return pd.DataFrame(cols, index=ks.dates)


def family_test(ks: KPISet, anchor_dates: list[pd.Timestamp], day: pd.Timestamp, outcomes: list[tuple[str, str]],
                lags: tuple, sign: int, cache: dict) -> dict | None:
    """One anchor, one pre-registered family: the largest z over outcomes x lags (one-sided in
    `sign`, two-sided if 0), and its p from the same maximum at placebo dates: every
    ANCHOR_NULL_STEP-th day more than ANCHOR_NULL_GAP before or 2 x ANCHOR_NULL_GAP after every
    anchor (the placebo machinery
    of placebo_z, here for a maximum). p = (1 + #placebo >= observed) / (1 + #placebo)."""
    tab = _family_table(ks, outcomes, lags, cache)
    if tab.empty or day not in tab.index:
        return None
    stat = tab.abs() if sign == 0 else sign * tab
    row = stat.loc[day]
    if row.isna().all():
        return None
    m = stat.max(axis=1, skipna=True)
    far = np.ones(len(tab), bool)
    for a in anchor_dates:
        # before an anchor its windows must not reach it; after it, an effect that started there
        # may also end there (and its mirror shows in the other segments): twice the span
        d = (tab.index - a).days
        far &= (d < -ANCHOR_NULL_GAP) | (d > 2 * ANCHOR_NULL_GAP)
    grid = np.zeros(len(tab), bool)
    grid[::ANCHOR_NULL_STEP] = True
    null = m[far & grid & stat.notna().all(axis=1).to_numpy()].to_numpy()
    if len(null) < 20:
        return None
    best = row.idxmax()
    obs = float(row.max())
    return {"kpi": best[0], "segment": best[1], "lag": int(best[2]), "stat": obs, "n_null": len(null),
            "n_tests": int(row.notna().sum()), "p": float((1 + np.sum(null >= obs)) / (1 + len(null)))}


def anchored_candidates(ks: KPISet, anchors: list[dict], prices: list[Candidate], rng, cache: dict) -> list[Candidate]:
    """The anchored family (DECISIONS 137). Each anchor gets ANCHOR_ALPHA / #anchors, split in
    two fixed families tested one after the other: price -> (orders of the repriced categories
    at lag 0: price_candidates, its own bar) then churn of every customer segment at
    ANCHOR_LAGS, one-sided (dearer -> more churn); courier -> (late share and rating of its
    cities at SERVICE_LAGS) then churn of its cities at ANCHOR_LAGS, two-sided. The second
    family gets half the anchor's alpha, or all of it if the first family is confirmed
    (Bonferroni with the alpha passed on)."""
    if not anchors:
        return []
    alpha = ANCHOR_ALPHA / len(anchors)
    dates = [a["date"] for a in anchors]
    seg_values = [sg for (k, sg) in ks.series if k == "churn_onsets" and sg.startswith("segment=") and ";" not in sg]
    out = []
    for a in anchors:
        day = a["date"]
        fams = []
        if a["kind"] == "price":
            first = next((c for c in prices if c.start_date == str(day.date())), None)
            first_ok = first is not None and first.status == "reported"
            sign = 1 if a["pct"] > 0 else -1
            fams.append(("churn", [("churn_onsets", sg) for sg in seg_values], ANCHOR_LAGS, sign,
                         alpha if first_ok else alpha / 2))
            what = f"ceník {a['pct']:+.0f} % u {a['segment'].split('=', 1)[1]} od {day.date()}"
        else:
            cities = a["cities"]
            service = [(k, f"city={c}") for k in ("late_rate", "rating_mean") for c in cities]
            res = family_test(ks, dates, day, service, SERVICE_LAGS, 0, cache)
            first_ok = False
            if res is not None:
                c = _anchored(ks, a, res, alpha / 2, rng, f"kurýr {a['courier']} v {', '.join(cities)} od {day.date()}")
                if c is not None:
                    first_ok = c.status == "reported"
                    out.append(c)
            churn = [("churn_onsets", a["segment"])] + ([("churn_onsets", f"city={c}") for c in cities] if len(cities) > 1 else [])
            fams.append(("churn", churn, ANCHOR_LAGS, 0, alpha if first_ok else alpha / 2))
            what = f"kurýr {a['courier']} v {', '.join(cities)} od {day.date()}"
        for _, outcomes, lags, sign, a_f in fams:
            res = family_test(ks, dates, day, outcomes, lags, sign, cache)
            if res is not None:
                c = _anchored(ks, a, res, a_f, rng, what, lags, sign)
                if c is not None:
                    out.append(c)
    return out


def _anchored(ks: KPISet, a: dict, res: dict, alpha: float, rng, what: str, lags: tuple = SERVICE_LAGS,
              sign: int = 0) -> Candidate | None:
    """The candidate for a family's best outcome and lag: DiD with CI at T = anchor + lag."""
    kpi, seg, lag = res["kpi"], res["segment"], res["lag"]
    s = _union_series(ks, kpi, seg)
    pr = prepare(s, SMEAR_DAYS.get(kpi, 0)) if s is not None else None
    ta = test_arrays(ks, kpi, seg, s, pr) if pr is not None else None
    if ta is None:
        return None
    n = len(s)
    # dated at the family's best lag: the day whose 28 days after differ most from the 28
    # before. Churn dates are estimated (last order + mean gap), which smears a step evenly on
    # both sides, so its centre, not the start of a fitted ramp, is the onset
    if len(lags) > 2:
        # one day's z is noisy by a week or more: take the centre of the best 3 weeks
        z = _z_by_date(ks, kpi, seg, {})
        days = pd.date_range(a["date"], a["date"] + pd.Timedelta(days=max(lags)))
        sm = z.reindex(pd.date_range(days[0] - pd.Timedelta(days=ANCHOR_DATE_SMOOTH), days[-1]
                                     + pd.Timedelta(days=ANCHOR_DATE_SMOOTH)))
        sm = (sm.abs() if sign == 0 else sign * sm).rolling(ANCHOR_DATE_SMOOTH, center=True, min_periods=7).mean()
        sm = sm.reindex(days)
        if sm.notna().any():
            lag = int((sm.idxmax() - a["date"]).days)
    t0 = t1 = int(s.index.searchsorted(a["date"] + pd.Timedelta(days=lag)))
    w = _windows(n, t0, t1)
    if w is None:
        return None
    T = s.index[t0]
    point, ci, _ = did(ta.seg, ta.rest, *w, rng, ratio=ta.ratio)
    z = placebo_z(ta.seg, ta.rest, t0, t1, w[0].stop - w[0].start, w[1].stop - w[1].start, ta.ratio)
    unit = " p.b." if ta.ratio else " %"
    k = 1 if ta.ratio and kpi != "late_rate" else 100
    c = Candidate(
        id="", metric=METRIC[kpi], segment=seg, kpi=kpi, start_date=str(T.date()), end_date=None,
        direction="up" if point > 0 else "down", magnitude_pct=round(100 * point, 1), lag_days=lag,
        caused_by=None, kind="shift", confidence=round(float(np.clip(1 - res["p"] / alpha / 2, 0, 1)), 2),
        evidence=(f"kotva: {what}; {kpi} {seg} {lag} d po ní: {k * point:+.1f}{unit} proti zbytku, "
                  f"95% CI {k * ci[0]:+.1f}..{k * ci[1]:+.1f}{unit}; největší z {res['n_tests']} předem daných testů, "
                  f"p = {res['p']:.3f} z {res['n_null']} placebo dat (hladina {alpha:.3f})"),
        series=f"{kpi}|{seg}", ci=(round(100 * ci[0], 1), round(100 * ci[1], 1)),
        raw_change_pct=round(100 * (s.iloc[w[1]].mean() / max(s.iloc[w[0]].mean(), 1e-9) - 1), 1),
        extra={"source": "anchor", "anchor": a["kind"], "anchor_date": str(a["date"].date()), "p_anchor": round(res["p"], 4),
               "alpha": round(alpha, 4), "z": round(z, 2), "t0": t0, "t1": t1, "before": w[0], "after": w[1]})
    if res["p"] > alpha or ci[0] <= 0 <= ci[1]:
        c.status = "not_confirmed"
    return c


def absorb_into_anchored(cands: list[Candidate]) -> None:
    """A reported churn rise that the scan dated between an anchor and the anchored test's lag
    (its ramp fit started at the price change, where the slower buying first looks like churn)
    is the anchored event, dated by the anchored test: `merged` into it (DECISIONS 137)."""
    anch = [c for c in cands if c.status == "reported" and c.extra.get("source") == "anchor"]
    for c in cands:
        if c.status != "reported" or c.kind != "shift" or c.extra.get("source") in ("anchor", "price"):
            continue
        for a in anch:
            lo = pd.Timestamp(a.extra["anchor_date"]) - pd.Timedelta(days=RAMP_MAX)
            hi = pd.Timestamp(a.start_date) + pd.Timedelta(days=MERGE_DAYS)
            if (c.metric == a.metric and c.direction == a.direction and _overlap(c.segment, a.segment)
                    and lo <= pd.Timestamp(c.start_date) <= hi):
                c.status = "merged"
                c.extra["merged_into"] = a
                c.evidence += f"; tutéž změnu datuje ukotvený test ({a.series} od {a.start_date})"
                break


# ---------------------------------------------------------------- merging


def merge(cands: list[Candidate]) -> list[Candidate]:
    """One event per (metric, direction, time, overlapping segment). Inside a group, start from the
    broadest segment and move to a narrower one only if its effect is at least
    SPECIFIC_GAIN times larger. A price-response candidate wins its group, and a
    significant one below the z threshold is reported if a confirmed shift in the
    same group corroborates it (two independent tests agree)."""
    cands = sorted(cands, key=lambda c: c.start_date)
    groups: list[list[Candidate]] = []
    for c in cands:
        for g in groups:
            g0 = g[0]
            if (g0.metric == c.metric and g0.direction == c.direction
                    # a rolling KPI (repeat rate: 30 days) is dated at the end of its window
                    and abs((pd.Timestamp(g0.start_date) - pd.Timestamp(c.start_date)).days)
                    <= MERGE_DAYS + max(SMEAR_DAYS.get(g0.kpi, 0), SMEAR_DAYS.get(c.kpi, 0))
                    # two segments with nothing in common are two events (Brno subscribers'
                    # churn and regular customers' churn in the same week), not one
                    and any(_overlap(x.segment, c.segment) for x in g)):
                g.append(c)
                break
        else:
            groups.append([c])
    out = []
    for g in groups:
        price = [c for c in g if c.extra.get("source") in ("price", "anchor")]
        confirmed = [c for c in g if c.status == "reported"]
        if price and not confirmed:
            continue  # a weak price response alone stays not_confirmed
        if price:
            best = price[0]
            if best.status != "reported":
                best.status = "reported"
                best.confidence = max(best.confidence, max(c.confidence for c in confirmed))
                best.evidence += "; potvrzeno posunem ve stejném čase: " + ", ".join(c.series for c in confirmed)
        else:
            g.sort(key=lambda c: (len(_seg_keys(c.segment)), c.kpi != "orders", -c.extra.get("z", 0)))
            best = g[0]
            changed = True
            while changed:
                changed = False
                bk = {k.split("=")[0] for k in _seg_keys(best.segment)}
                narrower = [c for c in g if c is not best
                            and {k.split("=")[0] for k in _seg_keys(c.segment)} > bk
                            and _seg_keys(c.segment) >= _seg_keys(best.segment) | set()
                            and abs(c.magnitude_pct) >= SPECIFIC_GAIN * abs(best.magnitude_pct)]
                # a narrower segment must contain the broader one's values
                narrower = [c for c in narrower if _seg_keys(best.segment) <= _seg_keys(c.segment)]
                if narrower:
                    best = max(narrower, key=lambda c: c.confidence * abs(c.magnitude_pct))
                    changed = True
        for c in g:
            if c is not best:
                c.status = "merged"
                c.extra["merged_into"] = best
        best.extra["also_seen_in"] = [c.series for c in g if c is not best]
        out.extend(g)
    return out


def _in_control(a: str, b: str) -> bool:
    """Is segment b part of segment a's DiD control (see _rest)? Same dimension,
    other value (city=Praha vs city=Brno), or for a pair the same second key and
    another value of the first (Praha stores vs Brno stores)."""
    pa, pb = a.split(";"), b.split(";")
    if len(pa) != len(pb) or a == b or "," in a + b:
        return False
    if len(pa) == 1:
        return pa[0].split("=")[0] == pb[0].split("=")[0]
    return pa[1] == pb[1] and pa[0].split("=")[0] == pb[0].split("=")[0]


def mirrors(cands: list[Candidate]) -> None:
    """A big drop in one segment makes its siblings look up against a control that
    contains it (and the other way round). Of two reported shifts on the same KPI,
    in opposite directions, within MERGE_DAYS, where each is in the other's
    control, only the one with the larger placebo z is real."""
    rep = [c for c in cands if c.status == "reported" and c.kind == "shift"]
    for a in rep:
        for b in rep:
            if (a is not b and a.kpi == b.kpi and a.direction != b.direction and a.status == "reported"
                    and b.status == "reported" and _in_control(a.segment, b.segment)
                    and abs((pd.Timestamp(a.start_date) - pd.Timestamp(b.start_date)).days) <= MERGE_DAYS
                    and a.extra.get("z", 0) < b.extra.get("z", 0)):
                a.status = "mirror"
                a.evidence += f"; zrcadlo změny v {b.series} (je v kontrolní skupině)"


def explained_by_stockout(cands: list[Candidate]) -> None:
    """Orders of a category moving while its shelves are empty are the stock-out, not a
    change in demand: the drop into it (whose fitted ramp can start up to RAMP_MAX days
    earlier), blips during it and the rebound after the restock (up to MERGE_DAYS after its
    end). Such a shift or spike is kept as `explained_by_stockout` (DECISIONS 135). Since
    DECISIONS 139 a routine one-SKU stock-out explains them too when that SKU sold at least
    STOCKOUT_SHARE of its category, and "sold out" tickets during any such stock-out are the
    empty shelf as well."""
    # an empty shelf in December is still an empty shelf: stock-outs the calendar explains (the
    # Christmas rush empties them) explain their category's moves too
    outs = [c for c in cands if c.kind == "stockout" and (
        c.status == "reported" or (c.status in ("routine", "explained_by_calendar")
                                   and c.extra.get("share", 0) >= STOCKOUT_SHARE))]
    for c in cands:
        if (c.status != "reported" or c.kind == "stockout"
                or c.extra.get("source") in ("price", "anchor")):  # a price change is its own dated cause
            continue
        tickets = c.metric == "ticket_rate" and any(f"topic={t}" in _seg_keys(c.segment) for t in STOCKOUT_TOPICS)
        if c.metric != "purchase_rate" and not tickets:
            continue
        cats = {p.split("=", 1)[1] for p in _seg_keys(c.segment) if p.startswith("category=")}
        day = pd.Timestamp(c.start_date)
        for o in outs:
            cat = o.segment.split(";")[0].split("=", 1)[1]
            lo = pd.Timestamp(o.start_date) - pd.Timedelta(days=RAMP_MAX)
            hi = pd.Timestamp(o.end_date) + pd.Timedelta(days=MERGE_DAYS)
            if (cat in cats or tickets) and lo <= day <= hi:
                c.status = "explained_by_stockout"
                c.evidence += f"; v té době vyprodáno: {o.series} ({o.start_date} .. {o.end_date})"
                break


def substitution(cands: list[Candidate], ks: KPISet) -> None:
    """Customers who cannot buy one category buy a neighbouring one: a rise in category X that
    starts from RAMP_MAX days before to MERGE_DAYS after a reported stock-out or a reported drop
    in another category Y, and that gains no more orders a day than Y loses over the same
    windows, is that substitution, not an event of its own (`substitution`, DECISIONS 139)."""
    def daily(seg: str, w: slice) -> float | None:
        s = _union_series(ks, "orders", seg)
        return None if s is None else float(s.iloc[w].mean())

    shocks = [c for c in cands if c.status in ("reported", "explained_by_stockout") and c.metric == "purchase_rate"
              and c.direction == "down" and c.kind in ("stockout", "shift")
              and any(k.startswith("category=") for k in _seg_keys(c.segment))]
    for c in cands:
        if (c.status != "reported" or c.kind != "shift" or c.direction != "up" or c.metric != "purchase_rate"
                or c.extra.get("source") in ("price", "anchor") or "before" not in c.extra):
            continue
        mine = {k for k in _seg_keys(c.segment) if k.startswith("category=")}
        if not mine:
            continue
        gain_b, gain_a = daily(c.segment, c.extra["before"]), daily(c.segment, c.extra["after"])
        if gain_b is None:
            continue
        for o in shocks:
            theirs = {k for k in _seg_keys(o.segment) if k.startswith("category=")}
            dt = (pd.Timestamp(c.start_date) - pd.Timestamp(o.start_date)).days
            if theirs & mine or not -RAMP_MAX <= dt <= MERGE_DAYS:
                continue
            seg = "category=" + ",".join(sorted(k.split("=", 1)[1] for k in theirs))
            loss_b, loss_a = daily(seg, c.extra["before"]), daily(seg, c.extra["after"])
            if loss_b is None:
                continue
            gain, loss = gain_a - gain_b, loss_b - loss_a
            if 0 < gain <= loss:
                c.status = "substitution"
                c.evidence += (f"; zákazníci přešli z {seg} ({o.series} od {o.start_date}): "
                               f"+{gain:.1f} objednávek denně zde, -{loss:.1f} tam")
                break


def contaminated_control(cands: list[Candidate], ks: KPISet, rng) -> None:
    """A control group is clean only if none of its members has an event of its own around the
    test. For each reported shift, the donors (the other values of its dimension, or the sibling
    pairs) with a reported or merged shift of the same metric whose onset lies from PAIR_MAX_DAYS
    before the before-window to the end of the after-window are taken out of the control and the
    DiD is run again. If it no longer passes (CI excludes 0, z >= Z_REPORT), or no clean control
    is left, the shift is `contaminated_control`: the mirror of the donor's event (a student churn
    wave ending makes regular customers' churn look up). Both estimates are in the evidence
    (DECISIONS 139). Count KPIs and pooled ratio KPIs; anchored and price tests have their own."""
    flagged = [c for c in cands if c.status in ("reported", "merged") and c.kind == "shift"]
    for c in cands:
        if (c.status != "reported" or c.kind != "shift" or c.extra.get("source") in ("price", "anchor")
                or "before" not in c.extra or not c.segment or "," in c.segment):
            continue
        if c.kpi in RATIO_KPIS and c.kpi not in POOLED_KPIS:
            continue
        parts = c.segment.split(";")
        first_dim = parts[0].split("=")[0]
        before, after = c.extra["before"], c.extra["after"]
        lo = ks.dates[before.start] - pd.Timedelta(days=PAIR_MAX_DAYS) if before.start < len(ks.dates) else None
        hi = ks.dates[min(after.stop, len(ks.dates)) - 1]

        def donor_of(seg: str) -> bool:
            q = seg.split(";")
            if len(q) != len(parts) or seg == c.segment or q[0].split("=")[0] != first_dim:
                return False
            return len(q) == 1 or q[1] == parts[1]

        bad = sorted({f.segment for f in flagged if f is not c and f.metric == c.metric and "," not in f.segment
                      and donor_of(f.segment) and lo is not None and lo <= pd.Timestamp(f.start_date) <= hi})
        if not bad:
            continue
        s = ks.get(c.kpi, c.segment)
        if s is None:
            continue
        idx = s.index
        t0 = int(idx.searchsorted(ks.dates[before.stop])) if before.stop < len(ks.dates) else None
        if t0 is None:
            continue
        if c.kpi in POOLED_KPIS:
            pp = pooled_parts(ks, c.kpi, c.segment)
            if pp is None:
                continue
            nr, dr = pp[2].copy(), pp[3].copy()
            for b in bad:
                q = ks.parts.get((c.kpi, b))
                if q is not None:
                    nr, dr = nr - q[0].to_numpy(float), dr - q[1].to_numpy(float)
            kind = POOLED_KPIS[c.kpi]
            t, eff, se, valid = pooled_effects(pp[0], pp[1], nr, dr, after.start - before.stop, WINDOW, WINDOW, kind)
            i = np.flatnonzero(t == before.stop)
            if not len(i) or not valid[i[0]]:
                ok, text = False, "bez nich nezbývá dost kontroly"
            else:
                null = eff[valid & (np.abs(t - before.stop) > 2 * WINDOW)]
                noise = max(robust_sd(null), float(se[i[0]]) if np.isfinite(se[i[0]]) else 0)
                z = abs(eff[i[0]] - np.median(null)) / noise
                ok = z >= Z_REPORT and abs(eff[i[0]]) > 1.96 * noise
                text = f"bez nich z = {z:.1f}"
        else:
            rest = _rest(ks, c.kpi, c.segment, s)
            if rest is None:
                continue
            rest = rest.reindex(idx).copy()
            for b in bad:
                d = ks.get(c.kpi, b)
                if d is not None:
                    rest = rest - d.reindex(idx).fillna(0)
            rest = rest.clip(lower=0)
            if rest.mean() < MIN_MEAN:
                ok, text = False, "bez nich nezbývá dost kontroly"
            else:
                sv = np.where(holiday_mask(idx), np.nan, despike(s))
                rv = np.where(holiday_mask(idx), np.nan, despike(rest))
                tb, ta_ = int(idx.searchsorted(ks.dates[before.start])), int(idx.searchsorted(ks.dates[after.start]))
                nb, na = before.stop - before.start, after.stop - after.start
                w = (slice(tb, tb + nb), slice(ta_, ta_ + na))
                point, ci, _ = did(sv, rv, *w, rng)
                z = placebo_z(sv, rv, tb + nb, ta_, nb, na)
                ok = z >= Z_REPORT and not ci[0] <= 0 <= ci[1] and (point > 0) == (c.direction == "up")
                text = f"bez nich {100 * point:+.1f} %, z = {z:.1f}"
        c.extra["clean_control"] = text
        if not ok:
            c.status = "contaminated_control"
            c.evidence += f"; v kontrole jsou segmenty s vlastní událostí ({', '.join(bad)}): {text}"
        else:
            c.evidence += f"; bez segmentů s vlastní událostí ({', '.join(bad)}) v kontrole: {text}"


def control_moved(cands: list[Candidate]) -> None:
    """A reported shift whose own series moved the other way (orders "up" against the rest
    while they fell, 28 days after vs before) is all control: the rest moved more, which is
    a change somewhere else (its mirror) or a seasonal swing the segment shares less of. It is
    kept as `control_moved`, not reported. Count KPIs only; price tests are their own test
    (DECISIONS 135)."""
    for c in cands:
        if (c.status == "reported" and c.kind == "shift" and c.kpi not in RATIO_KPIS
                and c.extra.get("source") != "price" and c.raw_change_pct is not None
                and c.raw_change_pct * (1 if c.direction == "up" else -1) < 0):
            c.status = "control_moved"
            c.evidence += f"; sama řada se pohnula opačně ({c.raw_change_pct:+.1f} %), změnu dělá kontrola"


def _overlap(a: str, b: str) -> bool:
    ka, kb = _seg_keys(a), _seg_keys(b)
    return bool(ka & kb) or not ka or not kb


def churn_consequences(cands: list[Candidate]) -> None:
    """Customers who leave stop buying: a purchase drop in a segment that starts
    from 21 days before to 60 days after a confirmed churn rise in an overlapping
    segment is that churn's consequence, not an event of its own."""
    churn = [c for c in cands if c.status == "reported" and c.metric == "churn_hazard" and c.direction == "up"]
    for c in cands:
        if c.status != "reported" or c.metric != "purchase_rate" or c.direction != "down" or c.kind != "shift":
            continue
        for r in churn:
            dt = (pd.Timestamp(c.start_date) - pd.Timestamp(r.start_date)).days
            if -21 <= dt <= 60 and _overlap(c.segment, r.segment):
                c.status = "explained_by_churn"
                c.evidence += f"; důsledek odchodu zákazníků ({r.series} od {r.start_date})"
                break


# ---------------------------------------------------------------- lag search


def lag_search(cands: list[Candidate], ks: KPISet, preps: dict) -> None:
    """For churn and rating events: does the change follow an earlier event by one
    of LAGS days? Keep the anchor and lag with the largest |t|."""
    anchors = [c for c in cands if c.metric not in ("churn_hazard", "rating_mean")]
    for c in cands:
        if c.metric not in ("churn_hazard", "rating_mean") or c.kind != "shift" or c.extra.get("source") == "anchor":
            continue
        pr = preps.get((c.kpi, c.segment))
        if pr is None:
            s = _union_series(ks, c.kpi, c.segment)
            pr = prepare(s) if s is not None else None
        if pr is None:
            continue
        idx = pr.s.index
        onset = pd.Timestamp(c.start_date)
        best = None
        tried = 0
        for a in anchors:
            a_day = pd.Timestamp(a.start_date)
            if not (pd.Timedelta(0) <= onset - a_day <= pd.Timedelta(days=max(LAGS) + LAG_MATCH_DAYS)):
                continue
            for lag in LAGS:
                t = int(idx.get_indexer([a_day + pd.Timedelta(days=lag)])[0])
                if t < WINDOW or t + WINDOW > len(idx):
                    continue
                tstat = (pr.z[t:t + WINDOW].mean() - pr.z[t - WINDOW:t].mean()) / math.sqrt(2 / WINDOW)
                want = (1 if c.direction == "up" else -1) * (-1 if c.kpi in INVERSE_KPIS else 1)
                if np.sign(tstat) != want:
                    continue
                if abs((a_day + pd.Timedelta(days=lag) - onset).days) > LAG_MATCH_DAYS:
                    continue
                tried += 1
                if best is None or abs(tstat) > abs(best[2]):
                    best = (a, lag, tstat)
        # the best of m tried (anchor, lag) pairs is a maximum: its bar grows with m
        bar = max(LAG_MIN_T, float(norm.isf(LAG_ALPHA / (2 * max(tried, 1)))))
        if best and abs(best[2]) >= bar:
            c.caused_by, c.lag_days = best[0].id, best[1]
            c.evidence += f"; navazuje na {best[0].id} se zpožděním {best[1]} d (t = {best[2]:.1f})"


# ---------------------------------------------------------------- spikes and stockouts


def spikes(ks: KPISet, preps: dict) -> list[Candidate]:
    """Runs of residual |z| > SPIKE_Z. One- and two-day blips are listed as
    transient, not reported: story events are lasting changes."""
    out = []
    for (kpi, seg), pr in preps.items():
        # churn onsets are estimated (last order + gap), so a 1-3 day churn spike is
        # an artefact of that estimate, not something the data can show
        if kpi in ("revenue", "churn_onsets", "cancellations", "repeat_rate") or ";" in seg:
            continue
        # a share (late deliveries, mean rating) of a few hundred trials a day swings by
        # several points on its own, and its MAD z ignores how many trials a day had:
        # three noisy days read as "+150 %". No story event is a ratio spike (a courier
        # switch is a lasting shift, scanned as one), so ratio KPIs get no spikes (DECISIONS 135)
        if kpi in RATIO_KPIS:
            continue
        if kpi not in RATIO_KPIS and pr.s.mean() < MIN_MEAN:
            continue  # 1 -> 5 new customers in a day is no spike; same rule as for shifts
        hot = np.abs(pr.resid_z) > SPIKE_Z
        i, n = 0, len(hot)
        while i < n:
            if not hot[i]:
                i += 1
                continue
            j = i
            while j < n and hot[j] and np.sign(pr.resid_z[j]) == np.sign(pr.resid_z[i]):
                j += 1
            day = pr.s.index[i]
            base = float(np.median(pr.s.iloc[max(0, i - WINDOW):i])) if i > 0 else float(pr.s.iloc[i])
            peak = float(pr.s.iloc[i:j].max() if pr.resid_z[i] > 0 else pr.s.iloc[i:j].min())
            mag = 100 * (peak / base - 1) if base > 0 else 0.0
            c = Candidate(
                id="", metric=METRIC[kpi], segment=seg, kpi=kpi, start_date=str(day.date()),
                end_date=str(pr.s.index[j - 1].date()), direction="up" if pr.resid_z[i] > 0 else "down",
                magnitude_pct=round(mag, 1), lag_days=None, caused_by=None, kind="spike",
                confidence=round(float(np.clip((np.abs(pr.resid_z[i:j]).max() - SPIKE_Z) / 4, 0, 1)), 2),
                evidence=f"{kpi} {seg or 'vše'}: {j - i} d mimo normál, max |z| = {np.abs(pr.resid_z[i:j]).max():.1f}",
                series=f"{kpi}|{seg}")
            if j - i < SPIKE_MIN_RUN:
                c.status = "transient"
            elif c.confidence < MIN_CONFIDENCE:
                c.status = "not_confirmed"
            elif reason := calendar_reason(day):
                c.status = "explained_by_calendar"
                c.evidence += f"; {reason}"
            out.append(c)
            i = j
    # the same spike in several series (start within SPIKE_MERGE_DAYS) is one
    # spike: keep the broadest reported one
    kept: list[Candidate] = []
    for c in sorted((c for c in out if c.status == "reported"), key=lambda c: c.start_date):
        same = [k for k in kept if k.metric == c.metric and abs(
            (pd.Timestamp(k.start_date) - pd.Timestamp(c.start_date)).days) <= SPIKE_MERGE_DAYS]
        if not same:
            kept.append(c)
        elif len(_seg_keys(same[0].segment)) <= len(_seg_keys(c.segment)):
            c.status = "merged"
        else:
            same[0].status = "merged"
            kept[kept.index(same[0])] = c
    return out


def stockouts(ks: KPISet) -> list[Candidate]:
    """>= STOCKOUT_RUN days without a sale of a SKU that sold >= STOCKOUT_MIN_RATE
    units a day over the previous 28 days."""
    units = ks.events.get("sku_units")
    if units is None or units.empty:
        return []
    out = []
    cat_rate = {cat: pd.Series(g.groupby("date")["units"].sum().reindex(ks.dates, fill_value=0).to_numpy(float))
                .rolling(WINDOW, min_periods=WINDOW).mean().shift(1).to_numpy()
                for cat, g in units.groupby("category")}
    for (sku, cat, sup), g in units.groupby(["sku", "category", "supplier_id"]):
        s = g.set_index("date")["units"].reindex(ks.dates, fill_value=0).to_numpy(float)
        rate = pd.Series(s).rolling(WINDOW, min_periods=WINDOW).mean().shift(1).to_numpy()
        i = 0
        while i < len(s):
            if s[i] == 0 and rate[i] >= STOCKOUT_MIN_RATE:
                j = i
                while j < len(s) and s[j] == 0:
                    j += 1
                if j - i >= STOCKOUT_RUN:
                    out.append(c := Candidate(
                        id="", metric="purchase_rate", segment=f"category={cat};supplier={sup}", kpi="sku_units",
                        start_date=str(ks.dates[i].date()), end_date=str(ks.dates[j - 1].date()),
                        direction="down", magnitude_pct=-100.0, lag_days=None, caused_by=None, kind="stockout",
                        confidence=1.0, evidence=f"{sku}: {j - i} d bez prodeje, předtím {rate[i]:.1f} ks/d",
                        series=f"sku_units|{sku}", extra={"share": float(rate[i] / max(cat_rate[cat][i], 1e-9))}))
                    if reason := calendar_reason(ks.dates[i]):
                        c.status = "explained_by_calendar"
                        c.evidence += f"; {reason}"
                i = j
            else:
                i += 1
    # Several SKUs of one category whose empty runs overlap are one stock-out, dated at the
    # first. One SKU of a category with others still selling is routine restocking (the
    # simulator's inventory, like a real one, runs dry now and then): listed, not reported.
    # A supply problem empties several shelves of a supplier at once (DECISIONS 135).
    sold = units[units["units"] > 0].groupby("category")["sku"].nunique().to_dict()
    groups: list[list[Candidate]] = []
    for c in sorted((c for c in out if c.status == "reported"), key=lambda c: c.start_date):
        g = next((g for g in groups if g[0].segment == c.segment
                  and c.start_date <= max(x.end_date for x in g)), None)
        if g is None:
            groups.append([c])
        else:
            g.append(c)
    for g in groups:
        head = g[0]
        skus = sorted({x.series.split("|", 1)[1] for x in g})
        for x in g[1:]:
            x.status = "merged"
        head.end_date = max(x.end_date for x in g)
        head.extra["share"] = round(min(1.0, sum(x.extra.get("share", 0) for x in g)), 3)
        cat = head.segment.split(";")[0].split("=", 1)[1]
        n_cat = sold.get(cat, 1)
        head.evidence = (f"{len(skus)} z {n_cat} SKU kategorie {cat} bez prodeje "
                         f"({', '.join(skus)}), {head.start_date} .. {head.end_date}")
        if len(skus) < STOCKOUT_MIN_SKUS and len(skus) < n_cat:
            head.status = "routine"
    return out
