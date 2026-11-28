"""Optional Rust kernels (rust/s2d-kernels) for the detective's hot loops.

`LIB` is None when the shared library is not built; callers then use the Python code.
S2D_KERNELS=0 turns the kernels off, S2D_KERNELS_LIB=<path> points at a library.

    cd rust && cargo build --release
"""

import ctypes
import math
import os
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent


def _load() -> ctypes.CDLL | None:
    if os.environ.get("S2D_KERNELS", "1") == "0":
        return None
    candidates = [os.environ.get("S2D_KERNELS_LIB"),
                  _ROOT / "rust" / "target" / "release" / "libs2d_kernels.so",
                  _ROOT / "libs2d_kernels.so"]
    for path in candidates:
        if path and Path(path).exists():
            lib = ctypes.CDLL(str(path))
            f64p = np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS")
            i64p = np.ctypeslib.ndpointer(np.int64, flags="C_CONTIGUOUS,WRITEABLE")
            sz = ctypes.c_size_t
            lib.s2d_breakpoints.argtypes = [f64p, sz, sz, ctypes.c_double, sz, i64p, sz]
            lib.s2d_breakpoints.restype = ctypes.c_int64
            for name in ("s2d_pelt", "s2d_binseg"):
                fn = getattr(lib, name)
                fn.argtypes = [f64p, sz, sz, sz, ctypes.c_double, i64p, sz]
                fn.restype = ctypes.c_int64
            lib.s2d_stl.argtypes = [f64p, sz, np.ctypeslib.ndpointer(np.int64, flags="C_CONTIGUOUS"), f64p, f64p]
            lib.s2d_stl.restype = ctypes.c_int64
            i64r = np.ctypeslib.ndpointer(np.int64, flags="C_CONTIGUOUS")
            lib.s2d_group_sums.argtypes = [i64r, i64r, ctypes.c_void_p, sz, sz, sz,
                                           np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS,WRITEABLE")]
            lib.s2d_group_sums.restype = ctypes.c_int64
            f64w = np.ctypeslib.ndpointer(np.float64, flags="C_CONTIGUOUS,WRITEABLE")
            lib.s2d_repeat.argtypes = [i64r, i64r, sz, sz, sz, sz, sz, i64r, sz, i64r, sz, f64w, f64w]
            lib.s2d_repeat.restype = ctypes.c_int64
            return lib
    return None


LIB = _load()


def _call(fn, *args, n: int) -> list[int]:
    out = np.empty(n + 1, dtype=np.int64)
    count = fn(*args, out, len(out))
    if count < 0:
        raise ValueError(f"kernel failed with code {count}")
    return out[:count].tolist()


def pelt(z: np.ndarray, min_size: int, pen: float, jump: int = 5) -> list[int]:
    """Same as ruptures.Pelt(model="l2", min_size, jump).fit(z).predict(pen=pen) (ends incl. len(z))."""
    z = np.ascontiguousarray(z, dtype=np.float64)
    _check(z, sizes=(min_size, jump))
    return _call(LIB.s2d_pelt, z, len(z), min_size, jump, pen, n=len(z))


def binseg(z: np.ndarray, min_size: int, pen: float, jump: int = 5) -> list[int]:
    """Same as ruptures.Binseg(model="l2", min_size, jump).fit(z).predict(pen=pen)."""
    z = np.ascontiguousarray(z, dtype=np.float64)
    _check(z, sizes=(min_size, jump))
    return _call(LIB.s2d_binseg, z, len(z), min_size, jump, pen, n=len(z))


def breakpoints(z: np.ndarray, min_size: int, pen: float, confirm_days: int) -> list[int]:
    """PELT breaks (penalty pen) confirmed by Binseg (pen / 2) within confirm_days."""
    z = np.ascontiguousarray(z, dtype=np.float64)
    _check(z, sizes=(min_size, confirm_days))
    return _call(LIB.s2d_breakpoints, z, len(z), min_size, pen, confirm_days, n=len(z))


def stl(y: np.ndarray, period: int, seasonal: int = 7, robust: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """(trend, seasonal) of statsmodels.tsa.seasonal.STL(y, period, seasonal, robust=robust).fit().

    The smoother lengths follow statsmodels' defaults: trend = smallest odd integer >=
    1.5 * period / (1 - 1.5 / seasonal), low_pass = smallest odd integer > period, all
    degrees 1 and all jumps 1. The residual is y - season - trend.
    """
    y = np.ascontiguousarray(y, dtype=np.float64)
    trend = int(math.ceil(1.5 * period / (1 - 1.5 / seasonal)))
    trend += int(trend % 2 == 0)
    low_pass = period + 1
    low_pass += int(low_pass % 2 == 0)
    params = np.array([period, seasonal, trend, low_pass, 1, 1, 1, 1, 1, 1, int(robust)], dtype=np.int64)
    trend_out, season_out = np.empty(len(y)), np.empty(len(y))
    code = LIB.s2d_stl(y, len(y), params, trend_out, season_out)
    if code != 0:
        raise ValueError(f"stl kernel failed with code {code}")
    return trend_out, season_out


def _check(*arrays: np.ndarray, sizes: tuple[int, ...] = ()) -> None:
    """Reject what would make the kernels read out of bounds: wrong dimensions, unequal lengths,
    negative sizes (ctypes turns them into huge unsigned numbers)."""
    if any(a.ndim != 1 for a in arrays) or len({len(a) for a in arrays}) > 1:
        raise ValueError("kernel arrays must be 1-D and of equal length")
    if any(int(v) < 0 for v in sizes):
        raise ValueError("kernel sizes must not be negative")


def group_sums(codes: np.ndarray, days: np.ndarray, vals: np.ndarray | None, n_groups: int, n_days: int) -> np.ndarray:
    """(n_groups, n_days) sums of vals (1.0 per row when None) by group code and day column.

    Rows with a negative code or day are skipped. The sum is pandas' Kahan summation in row
    order, so it equals `df.groupby([group, day])[val].sum()` bit for bit. vals must be finite.
    """
    codes = np.ascontiguousarray(codes, dtype=np.int64)
    days = np.ascontiguousarray(days, dtype=np.int64)
    out = np.zeros((n_groups, n_days))
    if vals is None:
        _check(codes, days, sizes=(n_groups, n_days))
        ptr = None
    else:
        vals = np.ascontiguousarray(vals, dtype=np.float64)
        _check(codes, days, vals, sizes=(n_groups, n_days))
        ptr = vals.ctypes.data_as(ctypes.c_void_p)
    if LIB.s2d_group_sums(codes, days, ptr, len(codes), n_groups, n_days, out) != 0:
        raise ValueError("group_sums kernel rejected its input")
    return out


def repeat_counts(ci: np.ndarray, day: np.ndarray, n_cust: int, n_days: int, a: int, f: int,
                  groups: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Repeat-purchase (numerator, denominator), each (len(groups), n_days - f - a + 1).

    Per anchor day t (a .. n_days - f): the denominator counts the customers of a group with an
    order in [t-a, t), the numerator those that order again in [t, t+f).
    """
    ci = np.ascontiguousarray(ci, dtype=np.int64)
    day = np.ascontiguousarray(day, dtype=np.int64)
    _check(ci, day, sizes=(n_cust, n_days, a, f))
    ptr = np.zeros(len(groups) + 1, dtype=np.int64)
    ptr[1:] = np.cumsum([len(g) for g in groups])
    members = np.ascontiguousarray(np.concatenate(groups) if groups else [], dtype=np.int64)
    nt = n_days - f - a + 1
    if nt < 1:
        raise ValueError("repeat kernel needs n_days >= a + f")
    num, den = np.zeros((len(groups), nt)), np.zeros((len(groups), nt))
    code = LIB.s2d_repeat(ci, day, len(ci), n_cust, n_days, a, f, ptr, len(groups), members, len(members), num, den)
    if code != 0:
        raise ValueError("repeat kernel rejected its input")
    return num, den
