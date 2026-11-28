//! L2 change-point search: PELT and binary segmentation.
//!
//! Faithful ports of `ruptures.Pelt(model="l2")` and `ruptures.Binseg(model="l2")`
//! (jump=5 by default there), including their tie-breaking, so the results can be
//! compared one for one with the Python library.

/// numpy's `pairwise_sum` (`np.add.reduce` on a contiguous float64 array): plain loop below 8
/// items, eight interleaved accumulators up to 128, recursive halves above. Reproducing the
/// summation order keeps the last bits of the cost equal to numpy's, which decides ties.
fn pairwise_sum(a: &[f64]) -> f64 {
    let n = a.len();
    if n < 8 {
        let mut res = 0.0;
        for v in a {
            res += v;
        }
        res
    } else if n <= 128 {
        let mut r = [a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]];
        let mut i = 8;
        while i < n - (n % 8) {
            for k in 0..8 {
                r[k] += a[i + k];
            }
            i += 8;
        }
        let mut res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        while i < n {
            res += a[i];
            i += 1;
        }
        res
    } else {
        let mut n2 = n / 2;
        n2 -= n2 % 8;
        pairwise_sum(&a[..n2]) + pairwise_sum(&a[n2..])
    }
}

/// Cost of `x[start..end]`: `numpy.var(x[start:end]) * len`, with numpy's own summation order
/// (mean first, then the mean of squared deviations).
fn error(x: &[f64], start: usize, end: usize) -> f64 {
    let len = (end - start) as f64;
    let seg = &x[start..end];
    let mean = pairwise_sum(seg) / len;
    let dev: Vec<f64> = seg.iter().map(|v| (v - mean) * (v - mean)).collect();
    pairwise_sum(&dev) / len * len
}

/// Running total of a list of floats, summed the way CPython 3.12's `sum()` does
/// (compensated), so PELT's partition costs compare like `sum(partition.values())`.
#[derive(Clone, Copy, Default)]
struct PySum {
    f: f64,
    c: f64,
}

impl PySum {
    fn with(self, x: f64) -> Self {
        let t = self.f + x;
        let c = if self.f.abs() >= x.abs() { self.c + ((self.f - t) + x) } else { self.c + ((x - t) + self.f) };
        Self { f: t, c }
    }

    fn value(self) -> f64 {
        if self.c.is_finite() { self.f + self.c } else { self.f }
    }
}

/// `ruptures.utils.sanity_check` with `n_bkps = 0`: only the minimum length can fail.
fn feasible(n: usize, min_size: usize) -> bool {
    min_size <= n
}

/// PELT breakpoints (segment ends, the last one is `x.len()`), or `None` when the
/// segmentation is impossible.
pub fn pelt(x: &[f64], min_size: usize, jump: usize, pen: f64) -> Option<Vec<usize>> {
    let n = x.len();
    let min_size = min_size.max(1);
    if !feasible(n, min_size) {
        return None;
    }
    // total[t]: cost of the optimal partition of x[0..t]; prev[t]: start of its last segment.
    let mut total = vec![PySum::default(); n + 1];
    let mut prev = vec![0usize; n + 1];
    let mut known = vec![false; n + 1];
    known[0] = true;

    let mut ind: Vec<usize> = (0..n).step_by(jump).filter(|&k| k >= min_size).collect();
    ind.push(n);

    let mut admissible: Vec<usize> = Vec::new();
    for &bkp in &ind {
        let new_adm = (bkp.saturating_sub(min_size) / jump) * jump;
        admissible.push(new_adm);

        // One subproblem per admissible start that has a partition (ruptures `continue`s on a miss).
        let mut subs: Vec<PySum> = Vec::with_capacity(admissible.len());
        let mut sub_start: Vec<usize> = Vec::with_capacity(admissible.len());
        for &t in &admissible {
            if !known[t] {
                continue;
            }
            subs.push(total[t].with(error(x, t, bkp) + pen));
            sub_start.push(t);
        }
        // `min(..., key=sum)` returns the first minimum. No subproblem at all (NaN costs pruned
        // everything) is ruptures' "min() of an empty sequence": report it, do not panic.
        if subs.is_empty() {
            return None;
        }
        let mut best = 0;
        for (i, c) in subs.iter().enumerate() {
            if c.value() < subs[best].value() {
                best = i;
            }
        }
        total[bkp] = subs[best];
        prev[bkp] = sub_start[best];
        known[bkp] = true;
        // `zip(admissible, subproblems)`: pairs by position and stops at the shorter list.
        let limit = total[bkp].value() + pen;
        admissible = admissible
            .iter()
            .zip(subs.iter())
            .filter(|(_, c)| c.value() <= limit)
            .map(|(&t, _)| t)
            .collect();
    }

    let mut ends = Vec::new();
    let mut t = n;
    while t != 0 {
        ends.push(t);
        t = prev[t];
    }
    ends.reverse();
    Some(ends)
}

/// Best split of `x[start..end]` as `(breakpoint, gain)`, or `None` if no split fits.
fn single_bkp(x: &[f64], start: usize, end: usize, min_size: usize, jump: usize) -> Option<(usize, f64)> {
    let whole = error(x, start, end);
    let mut best: Option<(f64, usize)> = None;
    let mut bkp = start;
    while bkp < end {
        if bkp - start >= min_size && end - bkp >= min_size {
            let gain = whole - error(x, start, bkp) - error(x, bkp, end);
            // Python `max` over (gain, bkp) tuples: larger gain wins, ties go to the larger bkp.
            let better = match best {
                None => true,
                Some((g, b)) => gain > g || (gain == g && bkp > b),
            };
            if better {
                best = Some((gain, bkp));
            }
        }
        bkp += jump;
    }
    best.map(|(g, b)| (b, g))
}

/// Binary segmentation stopped by a penalty: keep splitting while the best gain exceeds `pen`.
pub fn binseg(x: &[f64], min_size: usize, jump: usize, pen: f64) -> Option<Vec<usize>> {
    let n = x.len();
    let min_size = min_size.max(1);
    if !feasible(n, min_size) {
        return None;
    }
    let mut bkps = vec![n];
    loop {
        let mut starts = vec![0usize];
        starts.extend(&bkps[..bkps.len() - 1]);
        // `max(new_bkps, key=gain)`: first of equal gains wins; "no split" counts as gain 0.
        let mut chosen: Option<(usize, f64)> = None;
        let mut chosen_gain = f64::NEG_INFINITY;
        let mut chosen_none = false;
        let mut first = true;
        for (&s, &e) in starts.iter().zip(bkps.iter()) {
            let (cand, gain) = match single_bkp(x, s, e, min_size, jump) {
                Some((b, g)) => (Some((b, g)), g),
                None => (None, 0.0),
            };
            if first || gain > chosen_gain {
                chosen = cand;
                chosen_gain = gain;
                chosen_none = cand.is_none();
                first = false;
            }
        }
        if chosen_none {
            break;
        }
        let (bkp, gain) = chosen.expect("a split was chosen");
        if !(gain > pen) {
            break;
        }
        bkps.push(bkp);
        bkps.sort_unstable();
    }
    Some(bkps)
}

/// The detective's `breakpoints()`: PELT breaks (penalty `pen`) that Binseg (penalty `pen / 2`)
/// confirms within `confirm_days`. Returns break positions without the final `x.len()`.
pub fn confirmed_breaks(x: &[f64], min_size: usize, pen: f64, confirm_days: usize) -> Option<Vec<usize>> {
    const JUMP: usize = 5;
    let mut pelt_b = pelt(x, min_size, JUMP, pen)?;
    pelt_b.pop();
    if pelt_b.is_empty() {
        return Some(vec![]);
    }
    let mut bin_b = binseg(x, min_size, JUMP, pen / 2.0)?;
    bin_b.pop();
    Some(
        pelt_b
            .into_iter()
            .filter(|&b| bin_b.iter().any(|&c| b.abs_diff(c) <= confirm_days))
            .collect(),
    )
}
