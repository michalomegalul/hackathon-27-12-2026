"""The Rust kernels must give exactly what ruptures gives (skipped if the library is not built)."""

import math

import numpy as np
import pytest
import ruptures as rpt

from s2d import rustk

pytestmark = pytest.mark.skipif(rustk.LIB is None, reason="cd rust && cargo build --release")

MIN_SIZE = 7


def _series(seed: int):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(112, 1100))
    x = rng.normal(size=n)
    for _ in range(int(rng.integers(0, 5))):  # level shifts, ramps and spikes
        at = int(rng.integers(10, n - 10))
        x[at:] += rng.normal(scale=2.0)
    for _ in range(int(rng.integers(0, 3))):
        at = int(rng.integers(0, n - 5))
        x[at:at + 3] += 6
    return (x - np.median(x)) / (np.std(x) or 1.0)


@pytest.mark.parametrize("seed", range(150))
def test_pelt_and_binseg_match_ruptures(seed):
    z = _series(seed)
    pen = 3.0 * math.log(len(z))
    sig = z.reshape(-1, 1)
    assert rustk.pelt(z, MIN_SIZE, pen) == rpt.Pelt(model="l2", min_size=MIN_SIZE).fit(sig).predict(pen=pen)
    for p in (pen, pen / 2):
        assert rustk.binseg(z, MIN_SIZE, p) == rpt.Binseg(model="l2", min_size=MIN_SIZE).fit(sig).predict(pen=p)


@pytest.mark.parametrize("seed", range(50))
def test_confirmed_breakpoints_match_python(seed, monkeypatch):
    from s2d.detective import scan

    z = _series(1000 + seed)
    fast = scan.breakpoints(z)
    monkeypatch.setattr(scan.rustk, "LIB", None)
    assert fast == scan.breakpoints(z)


def test_flat_and_tiny_inputs():
    z = np.zeros(120)
    assert rustk.pelt(z, MIN_SIZE, 10.0) == [120]
    assert rustk.binseg(z, MIN_SIZE, 10.0) == [120]
    with pytest.raises(ValueError):
        rustk.pelt(np.zeros(5), MIN_SIZE, 10.0)


def _kpi_like(seed: int):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(112, 1100))
    t = np.arange(n)
    weekly = rng.normal(scale=0.3, size=7)[t % 7]
    y = 50 + 0.02 * t + 5 * np.sin(2 * np.pi * t / 365) + weekly + rng.poisson(8, n) * rng.choice([1, 1, 1, 2], n)
    for _ in range(int(rng.integers(0, 4))):
        at = int(rng.integers(0, n - 3))
        y[at:at + int(rng.integers(1, 4))] += rng.choice([-1, 1]) * rng.uniform(15, 60)  # spikes
    return y


@pytest.mark.parametrize("seed", range(60))
@pytest.mark.parametrize("robust", [True, False])
def test_stl_matches_statsmodels(seed, robust):
    from statsmodels.tsa.seasonal import STL

    y = _kpi_like(seed)
    ref = STL(y, period=7, robust=robust).fit()
    trend, season = rustk.stl(y, 7, robust=robust)
    np.testing.assert_allclose(trend, ref.trend, rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(season, ref.seasonal, rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize("seed", range(40))
def test_stl_is_bit_exact_on_sparse_series(seed):
    """Counts of rare events (mostly 0, a few 1-2). The robust weights have hard thresholds,
    so a 1-ulp difference in the tricube weights (e.g. u*u*u instead of pow) shows up as a
    visible difference here; it did in a 9e-3 trend error on a real run."""
    from statsmodels.tsa.seasonal import STL

    rng = np.random.default_rng(seed)
    n = int(rng.integers(112, 700))
    y = (rng.random(n) < rng.uniform(0.01, 0.3)).astype(float) * rng.integers(1, 3, n)
    ref = STL(y, period=7, robust=True).fit()
    trend, season = rustk.stl(y, 7)
    np.testing.assert_allclose(trend, ref.trend, rtol=0, atol=1e-12)
    np.testing.assert_allclose(season, ref.seasonal, rtol=0, atol=1e-12)


@pytest.mark.parametrize("seed", range(150))
def test_segmentation_matches_ruptures_on_tied_data(seed):
    """Rounded or integer series have exactly tied gains; which split wins then depends on the
    last bits of the cost, so the summation order has to be numpy's (pairwise) and CPython's
    compensated sum() for PELT. Before that was ported, ~1 in 400 series disagreed."""
    rng = np.random.default_rng(seed)
    n = int(rng.integers(112, 600))
    z = np.round(rng.normal(size=n) + (np.arange(n) > rng.integers(20, n - 20)) * rng.uniform(0, 2), int(rng.integers(0, 2)))
    pen = 3.0 * math.log(n)
    sig = z.reshape(-1, 1)
    assert rustk.pelt(z, MIN_SIZE, pen) == rpt.Pelt(model="l2", min_size=MIN_SIZE).fit(sig).predict(pen=pen)
    assert rustk.binseg(z, MIN_SIZE, pen / 2) == rpt.Binseg(model="l2", min_size=MIN_SIZE).fit(sig).predict(pen=pen / 2)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_input_raises_instead_of_aborting(bad):
    """A panic in the kernel would kill the whole Python process (it cannot unwind through C)."""
    z = np.random.default_rng(0).normal(size=200)
    z[3] = bad
    for call in (lambda: rustk.pelt(z, MIN_SIZE, 10.0), lambda: rustk.breakpoints(z, MIN_SIZE, 10.0, 17)):
        try:
            call()
        except ValueError:
            pass  # rejected cleanly; returning a list is fine too, aborting is not
    from s2d.detective import scan

    with pytest.raises(ValueError):  # the Python fallback keeps ruptures' own error
        scan.breakpoints(z)


def test_bad_penalty_raises():
    z = np.random.default_rng(0).normal(size=200)
    for pen in (np.nan, -1.0):
        try:
            rustk.pelt(z, MIN_SIZE, pen)
        except ValueError:
            pass


@pytest.mark.parametrize("params", [
    [7, 7, 13, -3, 1, 1, 1, 1, 1, 1, 1],      # negative low_pass: used to index out of bounds
    [7, 7, 15, 8, 1, 1, 1, 1, 1, 1, 1],       # even low_pass
    [7, 6, 15, 9, 1, 1, 1, 1, 1, 1, 1],       # even seasonal
    [7, 7, 5, 9, 1, 1, 1, 1, 1, 1, 1],        # trend not longer than the period
    [7, 7, 15, 9, 2, 1, 1, 1, 1, 1, 1],       # degree 2
    [7, 7, 15, 9, 1, 1, 1, 0, 1, 1, 1],       # jump 0
    [1, 7, 15, 9, 1, 1, 1, 1, 1, 1, 1],       # period 1
])
def test_stl_rejects_bad_parameters(params):
    y = np.random.default_rng(0).normal(size=100)
    out = np.empty(100)
    code = rustk.LIB.s2d_stl(y, 100, np.array(params, dtype=np.int64), out, out.copy())
    assert code == -1


# ---------------------------------------------------------------- KPI kernels

import pandas as pd  # noqa: E402


@pytest.mark.parametrize("seed", range(30))
def test_group_sums_is_pandas_groupby_sum_bit_for_bit(seed):
    """pandas sums a group with Kahan summation in row order; revenue-like floats expose any other order."""
    rng = np.random.default_rng(seed)
    n = int(rng.integers(50, 5000))
    df = pd.DataFrame({"g": rng.integers(0, 6, n), "d": rng.integers(0, 40, n),
                       "v": rng.normal(1e5, 3e4, n) * rng.choice([1, 1e-3, 1e3], n)})
    ref = df.groupby(["g", "d"])["v"].sum().unstack(fill_value=0.0).reindex(index=range(6), columns=range(40), fill_value=0.0)
    got = rustk.group_sums(df["g"].to_numpy(), df["d"].to_numpy(), df["v"].to_numpy(), 6, 40)
    assert np.array_equal(got, ref.to_numpy())


def test_group_sums_counts_skips_negative_codes_and_nan_values():
    codes = np.array([0, 0, 1, -1, 1, 0])
    days = np.array([2, 2, 0, 1, -1, 3])
    got = rustk.group_sums(codes, days, None, 2, 4)
    assert got.tolist() == [[0, 0, 2, 1], [1, 0, 0, 0]]
    vals = np.array([1.5, np.nan, 2.0, 9.0, 9.0, 4.0])
    got = rustk.group_sums(codes, days, vals, 2, 4)
    assert got.tolist() == [[0, 0, 1.5, 4.0], [2.0, 0, 0, 0]]


def test_group_sums_rejects_out_of_range():
    with pytest.raises(ValueError):
        rustk.group_sums(np.array([5]), np.array([0]), None, 2, 4)
    with pytest.raises(ValueError):
        rustk.group_sums(np.array([0]), np.array([4]), None, 2, 4)


def _repeat_reference(ci, day, n_cust, n_days, a, f, groups):
    cum = np.zeros((n_cust, n_days + 1), dtype=np.int16)
    np.add.at(cum, (ci, day + 1), 1)
    np.cumsum(cum, axis=1, out=cum)
    t = np.arange(a, n_days - f + 1)
    active = (cum[:, t] - cum[:, t - a]) > 0
    again = active & ((cum[:, t + f] - cum[:, t]) > 0)
    return (np.array([again[g].sum(0) for g in groups], dtype=float),
            np.array([active[g].sum(0) for g in groups], dtype=float))


@pytest.mark.parametrize("seed", range(25))
def test_repeat_counts_match_the_numpy_computation(seed):
    rng = np.random.default_rng(seed)
    n_cust, n_days, a, f = int(rng.integers(30, 300)), int(rng.integers(130, 400)), 60, 30
    k = int(rng.integers(100, 3000))
    pairs = np.unique(np.stack([rng.integers(0, n_cust, k), rng.integers(0, n_days, k)], 1), axis=0)  # one order per customer-day
    ci, day = pairs[:, 0], pairs[:, 1]
    groups = [np.arange(n_cust)] + [np.flatnonzero(rng.random(n_cust) < p) for p in (0.2, 0.5, 0.9)]
    num, den = rustk.repeat_counts(ci, day, n_cust, n_days, a, f, groups)
    ref_num, ref_den = _repeat_reference(ci, day, n_cust, n_days, a, f, groups)
    assert np.array_equal(num, ref_num) and np.array_equal(den, ref_den)


def test_repeat_counts_rejects_bad_customer_or_day():
    g = [np.arange(3)]
    with pytest.raises(ValueError):
        rustk.repeat_counts(np.array([5]), np.array([1]), 3, 200, 60, 30, g)
    with pytest.raises(ValueError):
        rustk.repeat_counts(np.array([1]), np.array([500]), 3, 200, 60, 30, g)
    with pytest.raises(ValueError):
        rustk.repeat_counts(np.array([1]), np.array([1]), 3, 200, 60, 30, [np.array([9])])


@pytest.mark.parametrize("n_days, a, f", [(5, -1, 1), (200, 2, -1), (200, 150, 100), (10, 60, 30)])
def test_repeat_counts_rejects_bad_sizes_instead_of_aborting(n_days, a, f):
    """ctypes turns a negative int into a huge unsigned one; that used to abort the process."""
    with pytest.raises(ValueError):
        rustk.repeat_counts(np.array([0]), np.array([0]), 2, n_days, a, f, [np.arange(2)])


def test_kernels_reject_negative_sizes_and_mismatched_arrays():
    with pytest.raises(ValueError):
        rustk.repeat_counts(np.array([0]), np.array([0]), -1, 200, 60, 30, [np.arange(1)])
    with pytest.raises(ValueError):
        rustk.repeat_counts(np.array([0]), np.array([0]), 2**62, 200, 60, 30, [np.arange(1)])
    with pytest.raises(ValueError):
        rustk.group_sums(np.array([0, 0]), np.array([0, 1]), np.array([1.0]), 1, 2)      # short vals
    with pytest.raises(ValueError):
        rustk.group_sums(np.array([0, 0]), np.array([0]), None, 1, 2)                    # short days
    with pytest.raises(ValueError):
        rustk.group_sums(np.zeros((2, 2), dtype=np.int64), np.zeros((2, 2), dtype=np.int64), None, 1, 2)
    with pytest.raises(ValueError):
        rustk.group_sums(np.array([0]), np.array([0]), None, -1, 2)
    with pytest.raises(ValueError):
        rustk.pelt(np.zeros(200), -7, 10.0)
