//! Numeric kernels for the detective, behind a plain C ABI so Python can call them with
//! `ctypes` (no build tooling on the Python side). Every function returns a negative
//! number on bad input instead of panicking across the FFI boundary.

pub mod kpi;
pub mod segmentation;
pub mod stl;

use std::slice;

/// Copy `values` to `out` (capacity `cap`); returns the count, or -2 if it does not fit.
unsafe fn write_out(values: &[usize], out: *mut i64, cap: usize) -> i64 {
    if values.len() > cap {
        return -2;
    }
    for (i, v) in values.iter().enumerate() {
        *out.add(i) = *v as i64;
    }
    values.len() as i64
}

/// PELT (L2) segment ends including `n`. Returns the count, -1 for bad input, -2 if `cap` is too small.
///
/// # Safety
/// `x` must point to `n` readable f64 and `out` to `cap` writable i64.
#[no_mangle]
pub unsafe extern "C" fn s2d_pelt(
    x: *const f64, n: usize, min_size: usize, jump: usize, pen: f64, out: *mut i64, cap: usize,
) -> i64 {
    // A panic must not unwind through the C ABI (it would abort the Python process).
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if x.is_null() || out.is_null() || jump == 0 {
            return -1;
        }
        match segmentation::pelt(slice::from_raw_parts(x, n), min_size, jump, pen) {
            Some(v) => write_out(&v, out, cap),
            None => -1,
        }
    }))
    .unwrap_or(-2)
}

/// Binseg (L2, penalty stop) segment ends including `n`. Same return codes as [`s2d_pelt`].
///
/// # Safety
/// `x` must point to `n` readable f64 and `out` to `cap` writable i64.
#[no_mangle]
pub unsafe extern "C" fn s2d_binseg(
    x: *const f64, n: usize, min_size: usize, jump: usize, pen: f64, out: *mut i64, cap: usize,
) -> i64 {
    // A panic must not unwind through the C ABI (it would abort the Python process).
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if x.is_null() || out.is_null() || jump == 0 {
            return -1;
        }
        match segmentation::binseg(slice::from_raw_parts(x, n), min_size, jump, pen) {
            Some(v) => write_out(&v, out, cap),
            None => -1,
        }
    }))
    .unwrap_or(-2)
}

/// The detective's confirmed breaks (PELT at `pen`, confirmed by Binseg at `pen / 2` within
/// `confirm_days`), without the trailing `n`. Same return codes as [`s2d_pelt`].
///
/// # Safety
/// `x` must point to `n` readable f64 and `out` to `cap` writable i64.
#[no_mangle]
pub unsafe extern "C" fn s2d_breakpoints(
    x: *const f64, n: usize, min_size: usize, pen: f64, confirm_days: usize, out: *mut i64, cap: usize,
) -> i64 {
    // A panic must not unwind through the C ABI (it would abort the Python process).
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if x.is_null() || out.is_null() {
            return -1;
        }
        match segmentation::confirmed_breaks(slice::from_raw_parts(x, n), min_size, pen, confirm_days) {
            Some(v) => write_out(&v, out, cap),
            None => -1,
        }
    }))
    .unwrap_or(-2)
}

/// Robust or plain STL. Writes the trend to `trend_out` and the seasonal component to
/// `season_out` (both `n` long). `params` = [period, seasonal, trend, low_pass, seasonal_deg,
/// trend_deg, low_pass_deg, seasonal_jump, trend_jump, low_pass_jump, robust]. Returns 0, or -1 on bad input.
///
/// # Safety
/// `y` must point to `n` readable f64, `params` to 11 readable i64, and the outputs to `n` writable f64.
#[no_mangle]
pub unsafe extern "C" fn s2d_stl(
    y: *const f64, n: usize, params: *const i64, trend_out: *mut f64, season_out: *mut f64,
) -> i64 {
    // A panic must not unwind through the C ABI (it would abort the Python process).
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if y.is_null() || params.is_null() || trend_out.is_null() || season_out.is_null() {
            return -1;
        }
        let q = slice::from_raw_parts(params, 11);
        // Same rules as the statsmodels constructor: odd smoothers >= 3, trend and low_pass longer than
        // the period, degrees 0 or 1, jumps >= 1. Anything else could index out of bounds.
        let odd3 = |v: i64| v >= 3 && v % 2 == 1;
        let bad = q[0] < 2
            || !odd3(q[1])
            || !odd3(q[2])
            || !odd3(q[3])
            || q[2] <= q[0]
            || q[3] <= q[0]
            || q[4..7].iter().any(|&d| d != 0 && d != 1)
            || q[7..10].iter().any(|&j| j < 1)
            || n < 2 * q[0] as usize;
        if bad {
            return -1;
        }
        let p = stl::StlParams {
            period: q[0] as usize,
            seasonal: q[1] as usize,
            trend: q[2] as usize,
            low_pass: q[3] as usize,
            seasonal_deg: q[4] as i32,
            trend_deg: q[5] as i32,
            low_pass_deg: q[6] as i32,
            seasonal_jump: q[7] as usize,
            trend_jump: q[8] as usize,
            low_pass_jump: q[9] as usize,
            robust: q[10] != 0,
        };
        let r = stl::stl(slice::from_raw_parts(y, n), p);
        slice::from_raw_parts_mut(trend_out, n).copy_from_slice(&r.trend);
        slice::from_raw_parts_mut(season_out, n).copy_from_slice(&r.season);
        0
    }))
    .unwrap_or(-2)
}

/// Per-(group, day) Kahan sums (see `kpi::group_sums`). `vals` may be null (count rows).
/// `out` is `n_groups * n_days` and is zeroed here. Returns 0, or -1 on bad input.
///
/// # Safety
/// `codes` and `days` must point to `n` readable i64, `vals` to `n` readable f64 (or be null),
/// and `out` to `n_groups * n_days` writable f64.
#[no_mangle]
pub unsafe extern "C" fn s2d_group_sums(
    codes: *const i64, days: *const i64, vals: *const f64, n: usize, n_groups: usize, n_days: usize, out: *mut f64,
) -> i64 {
    // A panic must not unwind through the C ABI (it would abort the Python process).
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if codes.is_null() || days.is_null() || out.is_null() {
            return -1;
        }
        let Some(total) = n_groups.checked_mul(n_days) else { return -1 };
        let out = slice::from_raw_parts_mut(out, total);
        out.iter_mut().for_each(|v| *v = 0.0);
        let vals = if vals.is_null() { None } else { Some(slice::from_raw_parts(vals, n)) };
        if kpi::group_sums(slice::from_raw_parts(codes, n), slice::from_raw_parts(days, n), vals, n_groups, n_days, out) {
            0
        } else {
            -1
        }
    }))
    .unwrap_or(-2)
}

/// Repeat-purchase numerators and denominators (see `kpi::repeat_counts`). `num` and `den` are
/// `n_groups * (n_days - f - a + 1)` and are zeroed here. Returns 0, or -1 on bad input.
///
/// # Safety
/// All pointers must be valid for the lengths implied by the arguments: `ci`/`day` `n_rows`,
/// `group_ptr` `n_groups + 1`, `members` `n_members`, `num`/`den` `n_groups * (n_days - f - a + 1)`.
#[no_mangle]
pub unsafe extern "C" fn s2d_repeat(
    ci: *const i64, day: *const i64, n_rows: usize, n_cust: usize, n_days: usize, a: usize, f: usize,
    group_ptr: *const i64, n_groups: usize, members: *const i64, n_members: usize, num: *mut f64, den: *mut f64,
) -> i64 {
    // A panic must not unwind through the C ABI (it would abort the Python process).
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if ci.is_null() || day.is_null() || group_ptr.is_null() || members.is_null() || num.is_null() || den.is_null() {
            return -1;
        }
        let Some(nt) = a.checked_add(f).and_then(|af| n_days.checked_sub(af)).and_then(|d| d.checked_add(1)) else {
            return -1;
        };
        let Some(total) = n_groups.checked_mul(nt) else { return -1 };
        let (num, den) = (slice::from_raw_parts_mut(num, total), slice::from_raw_parts_mut(den, total));
        num.iter_mut().for_each(|v| *v = 0.0);
        den.iter_mut().for_each(|v| *v = 0.0);
        let ok = kpi::repeat_counts(
            slice::from_raw_parts(ci, n_rows), slice::from_raw_parts(day, n_rows), n_cust, n_days, a, f,
            slice::from_raw_parts(group_ptr, n_groups + 1), slice::from_raw_parts(members, n_members), num, den,
        );
        if ok { 0 } else { -1 }
    }))
    .unwrap_or(-2)
}
