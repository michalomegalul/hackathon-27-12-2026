//! STL seasonal-trend decomposition (Cleveland et al. 1990).
//!
//! A line-for-line port of `statsmodels.tsa.stl._stl.STL` (itself the NETLIB Fortran with
//! the fixed median), so results can be compared with statsmodels to float precision.
//! Indices in `est`/`ess` are 1-based like the original; arrays are 0-based.

/// Parameters, named like the statsmodels constructor.
#[derive(Debug, Clone, Copy)]
pub struct StlParams {
    pub period: usize,
    pub seasonal: usize,
    pub trend: usize,
    pub low_pass: usize,
    pub seasonal_deg: i32,
    pub trend_deg: i32,
    pub low_pass_deg: i32,
    pub seasonal_jump: usize,
    pub trend_jump: usize,
    pub low_pass_jump: usize,
    pub robust: bool,
}

/// Components of the decomposition.
#[derive(Debug, Clone)]
pub struct StlResult {
    pub trend: Vec<f64>,
    pub season: Vec<f64>,
}

/// Memo of the tricube weight `(1 - (r/h)^3)^3` for integer distances `r` at one half-width `h`.
///
/// The weight depends only on `(r, h)` and `h` is the same for every interior point, so the
/// expensive `pow` calls are done once per distance. The cached value is the very same
/// `pow` result, so the output stays bit-identical to statsmodels (a plain `u*u*u` is not:
/// 1 ulp is enough to flip a robustness weight on sparse series).
#[derive(Default)]
struct Tricube {
    h: f64,
    table: Vec<f64>,
}

impl Tricube {
    fn weight(&mut self, r: f64, h: f64) -> f64 {
        if self.h != h || self.table.is_empty() {
            self.h = h;
            self.table.clear();
        }
        let idx = r as usize;
        if r.fract() != 0.0 {
            return (1.0 - (r / h).powf(3.0)).powf(3.0);
        }
        if idx >= self.table.len() {
            self.table.resize(idx + 1, f64::NAN);
        }
        if self.table[idx].is_nan() {
            self.table[idx] = (1.0 - (r / h).powf(3.0)).powf(3.0);
        }
        self.table[idx]
    }
}

/// Local fit at `xs` over `w[nleft-1..nright]`; NaN when every weight is zero.
#[allow(clippy::too_many_arguments)]
fn est(tc: &mut Tricube, y: &[f64], n: i64, len: i64, ideg: i32, xs: i64, nleft: i64, nright: i64,
       w: &mut [f64], userw: bool, rw: &[f64]) -> f64 {
    let rng = n as f64 - 1.0;
    let mut h = (xs - nleft).max(nright - xs) as f64;
    if len > n {
        h += ((len - n) as f64 / 2.0).floor();
    }
    let h9 = 0.999 * h;
    let h1 = 0.001 * h;
    let (lo, hi) = ((nleft - 1) as usize, nright as usize);
    let mut a = 0.0;
    for j in lo..hi {
        w[j] = 0.0;
        let r = ((j as i64 + 1) - xs).abs() as f64;
        if r <= h9 {
            if r <= h1 {
                w[j] = 1.0;
            } else {
                w[j] = tc.weight(r, h);
            }
            if userw {
                w[j] *= rw[j];
            }
            a += w[j];
        }
    }
    if a <= 0.0 {
        return f64::NAN;
    }
    for j in lo..hi {
        w[j] /= a;
    }
    if h > 0.0 && ideg > 0 {
        let mut a = 0.0;
        for j in lo..hi {
            a += w[j] * (j as f64 + 1.0);
        }
        let mut b = xs as f64 - a;
        let mut c = 0.0;
        for j in lo..hi {
            let d = j as f64 + 1.0 - a;
            c += w[j] * (d * d);
        }
        if c.sqrt() > 0.001 * rng {
            b /= c;
            for j in lo..hi {
                w[j] *= b * (j as f64 + 1.0 - a) + 1.0;
            }
        }
    }
    let mut ys = 0.0;
    for j in lo..hi {
        ys += w[j] * y[j];
    }
    ys
}

/// Loess smoothing of `y[..n]` into `ys`, evaluating every `njump` points and interpolating.
#[allow(clippy::too_many_arguments)]
fn ess(tc: &mut Tricube, y: &[f64], n: i64, len: i64, ideg: i32, njump: i64, userw: bool, rw: &[f64],
       ys: &mut [f64], res: &mut [f64]) {
    if n < 2 {
        ys[0] = y[0];
        return;
    }
    let newnj = njump.min(n - 1);
    let (mut nleft, mut nright) = (0i64, 0i64);
    let fill = |ys: &mut [f64], i: usize, v: f64| ys[i] = if v.is_nan() { y[i] } else { v };
    if len >= n {
        nleft = 1;
        nright = n;
        let mut i = 0i64;
        while i < n {
            let v = est(tc, y, n, len, ideg, i + 1, nleft, nright, res, userw, rw);
            fill(ys, i as usize, v);
            i += newnj;
        }
    } else if newnj == 1 {
        let nsh = (len + 2) / 2;
        nleft = 1;
        nright = len;
        for i in 0..n {
            if (i + 1) > nsh && nright != n {
                nleft += 1;
                nright += 1;
            }
            let v = est(tc, y, n, len, ideg, i + 1, nleft, nright, res, userw, rw);
            fill(ys, i as usize, v);
        }
    } else {
        let nsh = (len + 1) / 2;
        let mut i = 0i64;
        while i < n {
            if (i + 1) < nsh {
                nleft = 1;
                nright = len;
            } else if (i + 1) >= (n - nsh + 1) {
                nleft = n - len + 1;
                nright = n;
            } else {
                nleft = i + 1 - nsh + 1;
                nright = len + i + 1 - nsh;
            }
            let v = est(tc, y, n, len, ideg, i + 1, nleft, nright, res, userw, rw);
            fill(ys, i as usize, v);
            i += newnj;
        }
    }
    if newnj == 1 {
        return;
    }
    let mut i = 0i64;
    while i < n - newnj {
        let delta = (ys[(i + newnj) as usize] - ys[i as usize]) / newnj as f64;
        for j in i..i + newnj {
            ys[j as usize] = ys[i as usize] + delta * ((j + 1) - (i + 1)) as f64;
        }
        i += newnj;
    }
    let k = ((n - 1) / newnj) * newnj + 1;
    if k != n {
        let v = est(tc, y, n, len, ideg, n, nleft, nright, res, userw, rw);
        fill(ys, (n - 1) as usize, v);
        if k != n - 1 {
            let delta = (ys[(n - 1) as usize] - ys[(k - 1) as usize]) / (n - k) as f64;
            for j in k..n {
                ys[j as usize] = ys[(k - 1) as usize] + delta * ((j + 1) - k) as f64;
            }
        }
    }
}

/// Moving average of length `len` over `x[..n]` into `ave` (`n - len + 1` values).
fn ma(x: &[f64], n: usize, len: usize, ave: &mut [f64]) {
    let newn = n - len + 1;
    let flen = len as f64;
    let mut v = 0.0;
    for xi in &x[..len] {
        v += xi;
    }
    ave[0] = v / flen;
    let (mut k, mut m) = (len, 0usize);
    for j in 1..newn {
        v += x[k] - x[m];
        ave[j] = v / flen;
        k += 1;
        m += 1;
    }
}

struct Stl<'a> {
    y: &'a [f64],
    n: usize,
    p: StlParams,
    use_rw: bool,
    trend: Vec<f64>,
    season: Vec<f64>,
    rw: Vec<f64>,
    work: [Vec<f64>; 5],
    tc: Tricube,
}

impl Stl<'_> {
    /// Seasonal smoothing of every cycle-subseries (work[0] in, work[1] out).
    fn ss(&mut self) {
        let (n, np, ns) = (self.n as i64, self.p.period as i64, self.p.seasonal as i64);
        let [w0, w1, w2, w3, w4] = &mut self.work;
        for j in 0..np {
            let k = (n - (j + 1)) / np + 1;
            for i in 0..k {
                w2[i as usize] = w0[(i * np + j) as usize];
            }
            if self.use_rw {
                for i in 0..k {
                    w4[i as usize] = self.rw[(i * np + j) as usize];
                }
            }
            // ess(work1 -> work2[1..], weights scratch = season)
            ess(&mut self.tc, w2, k, ns, self.p.seasonal_deg, self.p.seasonal_jump as i64, self.use_rw, w4,
                &mut w3[1..], &mut self.season);
            let mut v = est(&mut self.tc, w2, k, ns, self.p.seasonal_deg, 0, 1, ns.min(k), &mut self.season,
                            self.use_rw, w4);
            if v.is_nan() {
                v = w3[1];
            }
            w3[0] = v;
            let mut v = est(&mut self.tc, w2, k, ns, self.p.seasonal_deg, k + 1, (k - ns + 1).max(1), k,
                            &mut self.season, self.use_rw, w4);
            if v.is_nan() {
                v = w3[k as usize];
            }
            w3[(k + 1) as usize] = v;
            for m in 0..(k + 2) {
                w1[(m * np + j) as usize] = w3[m as usize];
            }
        }
    }

    /// Low-pass filter of the cycle-subseries (work[1] in, work[2] out).
    fn fts(&mut self) {
        let n = self.n + 2 * self.p.period;
        let np = self.p.period;
        let [w0, w1, w2, _, _] = &mut self.work;
        ma(w1, n, np, w2);
        ma(w2, n - np + 1, np, w0);
        ma(w0, n - 2 * np + 2, 3, w2);
    }

    /// Robustness weights from the current fit in work[0].
    fn rwts(&mut self) {
        let n = self.n;
        for i in 0..n {
            self.rw[i] = (self.y[i] - self.work[0][i]).abs();
        }
        let mut sorted = self.rw.clone();
        sorted.sort_by(|a, b| a.total_cmp(b));
        let (m0, m1) = (n / 2, n - n / 2 - 1);
        let cmad = 3.0 * (sorted[m0] + sorted[m1]);
        if cmad == 0.0 {
            self.rw.iter_mut().for_each(|r| *r = 1.0);
            return;
        }
        let (c9, c1) = (0.999 * cmad, 0.001 * cmad);
        for r in self.rw.iter_mut() {
            *r = if *r <= c1 {
                1.0
            } else if *r <= c9 {
                {
                let v = 1.0 - (*r / cmad) * (*r / cmad);
                v * v
            }
            } else {
                0.0
            };
        }
    }

    fn onestp(&mut self, inner_iter: usize) {
        let n = self.n;
        let np = self.p.period;
        for _ in 0..inner_iter {
            for i in 0..n {
                self.work[0][i] = self.y[i] - self.trend[i];
            }
            self.ss();
            self.fts();
            // low-pass of work[2] -> work[0], scratch work[4]
            {
                let [w0, _, w2, w3, w4] = &mut self.work;
                ess(&mut self.tc, w2, n as i64, self.p.low_pass as i64, self.p.low_pass_deg,
                    self.p.low_pass_jump as i64, false, w3, w0, w4);
            }
            for i in 0..n {
                self.season[i] = self.work[1][np + i] - self.work[0][i];
                self.work[0][i] = self.y[i] - self.season[i];
            }
            let [w0, _, w2, _, _] = &mut self.work;
            ess(&mut self.tc, w0, n as i64, self.p.trend as i64, self.p.trend_deg, self.p.trend_jump as i64,
                self.use_rw, &self.rw, &mut self.trend, w2);
        }
    }
}

/// Decompose `y`. `inner_iter`/`outer_iter` default (as in statsmodels) to 2/15 when robust, else 5/0.
pub fn stl(y: &[f64], p: StlParams) -> StlResult {
    let n = y.len();
    let rows = n + 2 * p.period;
    let mut s = Stl {
        y,
        n,
        p,
        use_rw: false,
        trend: vec![0.0; n],
        season: vec![0.0; n],
        rw: vec![1.0; n],
        work: std::array::from_fn(|_| vec![0.0; rows]),
        tc: Tricube::default(),
    };
    let (inner, outer) = if p.robust { (2, 15) } else { (5, 0) };
    let mut k = 0;
    loop {
        s.onestp(inner);
        k += 1;
        if k > outer {
            break;
        }
        for i in 0..n {
            s.work[0][i] = s.trend[i] + s.season[i];
        }
        s.rwts();
        s.use_rw = true;
    }
    StlResult { trend: s.trend, season: s.season }
}
