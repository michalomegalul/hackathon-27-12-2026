//! KPI series kernels for `s2d/detective/kpis.py`.

/// Per-(group, day) sums with pandas' Kahan summation, in row order.
///
/// `codes[i]` is the group of row `i` and `days[i]` its column; a negative value skips the row.
/// `vals = None` means every row counts 1.0. NaN values are skipped like `groupby().sum()` does.
/// `out` is `n_groups * n_days`, row-major, and must be zeroed by the caller. Returns false on an
/// out-of-range code or day.
pub fn group_sums(
    codes: &[i64], days: &[i64], vals: Option<&[f64]>, n_groups: usize, n_days: usize, out: &mut [f64],
) -> bool {
    if codes.len() != days.len() || out.len() != n_groups * n_days || vals.is_some_and(|v| v.len() != codes.len()) {
        return false;
    }
    let mut comp = vec![0.0f64; out.len()];
    for i in 0..codes.len() {
        let (g, d) = (codes[i], days[i]);
        if g < 0 || d < 0 {
            continue;
        }
        let (g, d) = (g as usize, d as usize);
        if g >= n_groups || d >= n_days {
            return false;
        }
        let v = vals.map_or(1.0, |v| v[i]);
        if v.is_nan() {
            continue;
        }
        let cell = g * n_days + d;
        let y = v - comp[cell];
        let t = out[cell] + y;
        comp[cell] = (t - out[cell]) - y;
        out[cell] = t;
    }
    true
}

/// Repeat-purchase counts. For every anchor day `t` in `a..=n_days-f` and every group of customers:
/// `den` = customers with an order in `[t-a, t)`, `num` = those who order again in `[t, t+f)`.
///
/// `ci[k]`/`day[k]` are the customer index and day of order row `k`. Groups come as a CSR list:
/// `group_ptr` (`n_groups + 1` offsets) into `members` (customer indices). `num`/`den` are
/// `n_groups * (n_days - f - a + 1)`, row-major, zeroed by the caller. Returns false on bad input.
#[allow(clippy::too_many_arguments)]
pub fn repeat_counts(
    ci: &[i64], day: &[i64], n_cust: usize, n_days: usize, a: usize, f: usize,
    group_ptr: &[i64], members: &[i64], num: &mut [f64], den: &mut [f64],
) -> bool {
    let Some(nt) = a.checked_add(f).and_then(|af| n_days.checked_sub(af)).and_then(|d| d.checked_add(1)) else {
        return false;
    };
    if ci.len() != day.len() || group_ptr.is_empty() || n_cust > ci.len().saturating_mul(1 << 20).max(1 << 26) {
        return false;
    }
    let n_groups = group_ptr.len() - 1;
    if n_groups.checked_mul(nt) != Some(num.len()) || num.len() != den.len() {
        return false;
    }
    // order days per customer, as cumulative counts built one customer at a time
    let mut order_start = vec![0usize; n_cust + 1];
    for &c in ci {
        if c < 0 || c as usize >= n_cust {
            return false;
        }
        order_start[c as usize + 1] += 1;
    }
    for c in 0..n_cust {
        order_start[c + 1] += order_start[c];
    }
    let mut days_of = vec![0usize; ci.len()];
    let mut fill = order_start.clone();
    for k in 0..ci.len() {
        if day[k] < 0 || day[k] as usize >= n_days {
            return false;
        }
        let c = ci[k] as usize;
        days_of[fill[c]] = day[k] as usize;
        fill[c] += 1;
    }
    // customer -> groups
    let mut gstart = vec![0usize; n_cust + 1];
    for g in 0..n_groups {
        let (lo, hi) = (group_ptr[g], group_ptr[g + 1]);
        if lo < 0 || hi < lo || hi as usize > members.len() {
            return false;
        }
        for &m in &members[lo as usize..hi as usize] {
            if m < 0 || m as usize >= n_cust {
                return false;
            }
            gstart[m as usize + 1] += 1;
        }
    }
    for c in 0..n_cust {
        gstart[c + 1] += gstart[c];
    }
    let mut groups_of = vec![0usize; gstart[n_cust]];
    let mut gfill = gstart.clone();
    for g in 0..n_groups {
        for &m in &members[group_ptr[g] as usize..group_ptr[g + 1] as usize] {
            groups_of[gfill[m as usize]] = g;
            gfill[m as usize] += 1;
        }
    }

    let mut cum = vec![0i32; n_days + 1];
    for c in 0..n_cust {
        let gs = &groups_of[gstart[c]..gstart[c + 1]];
        if gs.is_empty() {
            continue;
        }
        cum.iter_mut().for_each(|v| *v = 0);
        for &d in &days_of[order_start[c]..order_start[c + 1]] {
            cum[d + 1] += 1;
        }
        for d in 0..n_days {
            cum[d + 1] += cum[d];
        }
        for j in 0..nt {
            let t = a + j;
            if cum[t] - cum[t - a] > 0 {
                let again = cum[t + f] - cum[t] > 0;
                for &g in gs {
                    den[g * nt + j] += 1.0;
                    if again {
                        num[g * nt + j] += 1.0;
                    }
                }
            }
        }
    }
    true
}
