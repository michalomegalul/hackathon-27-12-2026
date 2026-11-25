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
Then: merge duplicates across series, lag search for churn, calendar filter,
spikes and stockouts.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import holidays
import numpy as np
import pandas as pd
import ruptures as rpt
from statsmodels.tsa.seasonal import STL

from .kpis import CLOGLOG_KPIS, INVERSE_KPIS, METRIC, RATIO_KPIS, SMEAR_DAYS, KPISet

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
Z_REPORT = 6.5            # reported shifts need placebo z >= this (set on no-story twins, DECISIONS 55)
MIN_CONFIDENCE = 0.5      # = confidence at Z_REPORT
EP_MIN, EP_CUM = 0.3, 0.8  # Adtributor: per-value and cumulative explanatory power
MIN_SURPRISE = 0.002      # below this JS divergence a change counts as uniform
SPECIFIC_GAIN = 1.5       # prefer a narrower segment if its effect is 1.5x larger
MERGE_DAYS = 14           # candidates for one metric this close in time are one event
SPIKE_Z, SPIKE_MIN_RUN = 3.5, 3
SPIKE_MERGE_DAYS = 2      # spikes in several series starting this close are one spike
STOCKOUT_RUN, STOCKOUT_MIN_RATE = 3, 5.0
LAGS = (0, 7, 14, 28, 42)
LAG_MIN_T = 3.0
LAG_MATCH_DAYS = 14
CALENDAR_MAX_DAYS = 10    # only spikes and temporary changes shorter than this can be "just the calendar"


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


def confidence_from_z(z: float) -> float:
    """0.5 at the reporting threshold Z_REPORT, 0 two units below it, 1 two units above."""
    return float(np.clip(0.5 + (z - Z_REPORT) / 4.0, 0.0, 1.0))


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


def scan(ks: KPISet, seed: int = 0) -> list[Candidate]:
    rng = np.random.default_rng(seed)  # bootstrap only; fixed so a run is repeatable
    raw: list[Candidate] = []
    preps: dict[tuple[str, str], Prepared] = {}
    clean_rest: dict[tuple, np.ndarray] = {}
    n_id = 0

    def new_id() -> str:
        nonlocal n_id
        n_id += 1
        return f"C{n_id:03d}"

    for (kpi, seg), s in ks.series.items():
        pr = prepare(s, SMEAR_DAYS.get(kpi, 0))
        if pr is None:
            continue
        preps[(kpi, seg)] = pr
        if kpi not in RATIO_KPIS and s.mean() < MIN_MEAN:
            continue  # kept in preps for spikes; too sparse for shifts
        if (kpi, seg) in ks.parts and not seg:
            continue  # a share of everyone has no control; its segments are scanned directly
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
        used = set()
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
                raw.append(c)

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
        if w is None:
            if fb is not None:
                raw.insert(0, fb)
            continue
        before, after = w
        nb, na = before.stop - before.start, after.stop - after.start
        c.start_date = str(s.index[t0].date())
        c.extra.update(t0=t0, t1=t1, before=before, after=after)
        point, ci, _ = did(sv, rv, before, after, rng, ratio=ratio)
        z = placebo_z(sv, rv, t0, t1, nb, na, ratio)
        c.extra["z"] = round(z, 2)
        c.extra["max_ratio"] = round(_last_placebo.get("max_ratio", 0), 2)
        c.ci = (round(100 * ci[0], 1), round(100 * ci[1], 1))
        c.magnitude_pct = round(100 * point, 1)
        c.direction = "up" if point > 0 else "down"
        c.confidence = round(confidence_from_z(z), 2)
        c.evidence = (f"{c.kpi} {c.segment or 'vše'}: {c.raw_change_pct:+.1f} % (28 d po vs před), "
                      f"proti zbytku {c.magnitude_pct:+.1f} %, 95% CI {c.ci[0]:+.1f}..{c.ci[1]:+.1f} %")
        if c.kpi in INVERSE_KPIS:
            _invert(c, raw_sv, raw_rv, before, after)
        if ci[0] <= 0 <= ci[1]:
            c.status = "not_confirmed"
        elif c.confidence < MIN_CONFIDENCE:
            c.status = "not_confirmed"
        elif (calendar_applies(c.kind, c.start_date, c.end_date, rv is not None, SMEAR_DAYS.get(c.kpi, 0))
              and (reason := calendar_reason(pd.Timestamp(c.start_date)))):
            c.status = "explained_by_calendar"
            c.evidence += f"; {reason}"
        out.append(c)
        if fb is not None and c.status != "reported":
            raw.insert(0, fb)

    prices = price_candidates(ks, rng)
    out += prices
    # a significant price response below the z threshold can still be corroborated
    # by a confirmed shift at the same time (see merge)
    pool = [c for c in out if c.status == "reported"] + [
        c for c in prices if c.status == "not_confirmed" and c.extra.get("significant")]
    reported = merge(pool)
    mirrors(reported)
    churn_consequences(reported)
    out = [c for c in out if not any(c is p for p in pool)] + pool
    out += spikes(ks, preps)
    out += stockouts(ks)
    for c in sorted(out, key=lambda c: (c.status != "reported", c.start_date, c.metric)):
        c.id = new_id()
    lag_search([c for c in out if c.status == "reported"], ks, preps)
    return sorted(out, key=lambda c: c.id)


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
        w = _windows(len(seg_s), t0, t0 + 7)  # allow one week for the response to settle
        if w is None:
            continue
        point, ci, _ = did(ta.seg, ta.rest, *w, rng)
        z = placebo_z(ta.seg, ta.rest, t0, t0 + 7, w[0].stop - w[0].start, w[1].stop - w[1].start)
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
        if not c.extra["significant"] or c.confidence < MIN_CONFIDENCE:
            c.status = "not_confirmed"
        out.append(c)
    return out


# ---------------------------------------------------------------- merging


def merge(cands: list[Candidate]) -> list[Candidate]:
    """One event per (metric, direction, time). Inside a group, start from the
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
                    and abs((pd.Timestamp(g0.start_date) - pd.Timestamp(c.start_date)).days) <= MERGE_DAYS):
                g.append(c)
                break
        else:
            groups.append([c])
    out = []
    for g in groups:
        price = [c for c in g if c.extra.get("source") == "price"]
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
        if c.metric not in ("churn_hazard", "rating_mean") or c.kind != "shift":
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
                if best is None or abs(tstat) > abs(best[2]):
                    best = (a, lag, tstat)
        if best and abs(best[2]) >= LAG_MIN_T:
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
        if kpi in ("revenue", "churn_onsets", "repeat_rate") or ";" in seg:
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
                        series=f"sku_units|{sku}"))
                    if reason := calendar_reason(ks.dates[i]):
                        c.status = "explained_by_calendar"
                        c.evidence += f"; {reason}"
                i = j
            else:
                i += 1
    seen = set()
    for c in out:  # several SKUs of one category out at once = one stockout
        k = (c.segment, c.start_date)
        if c.status == "reported" and k in seen:
            c.status = "merged"
        seen.add(k)
    return out
