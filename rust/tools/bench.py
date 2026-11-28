"""Python vs Rust kernels: micro-benchmarks and the detective end to end.

    cd rust && cargo build --release && cd ..
    PYTHONPATH=. uv run python rust/tools/bench.py [RUN_DIR ...]

Each RUN_DIR is a simulated world (python -m s2d.sim run ... --out DIR). The detective runs
twice per directory, with S2D_KERNELS=0 and =1, and the findings are compared (timing fields
excluded); a difference is reported as MISMATCH.
"""

import json
import math
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import ruptures as rpt
from statsmodels.tsa.seasonal import STL

from s2d import rustk


def best(fn, repeat=5):
    out = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t)
    return min(out)


def micro():
    rng = np.random.default_rng(0)
    n = 600
    t = np.arange(n)
    y = 50 + 5 * np.sin(2 * np.pi * t / 365) + rng.normal(size=n) * 3
    z = (y - np.median(y)) / y.std()
    pen = 3 * math.log(n)
    sig = z.reshape(-1, 1)
    rows = [
        ("STL robust, n=600", lambda: STL(y, period=7, robust=True).fit(), lambda: rustk.stl(y, 7)),
        ("PELT l2, n=600", lambda: rpt.Pelt(model="l2", min_size=7).fit(sig).predict(pen=pen),
         lambda: rustk.pelt(z, 7, pen)),
        ("Binseg l2, n=600", lambda: rpt.Binseg(model="l2", min_size=7).fit(sig).predict(pen=pen / 2),
         lambda: rustk.binseg(z, 7, pen / 2)),
    ]
    print(f"{'kernel':<22}{'python':>12}{'rust':>12}{'speedup':>10}")
    for name, py, rs in rows:
        a, b = best(py), best(rs, 20)
        print(f"{name:<22}{a * 1000:>10.2f}ms{b * 1000:>10.3f}ms{a / b:>9.0f}x")


def detective(run_dir):
    res = {}
    for flag in ("0", "1"):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "d.json")
            env = {**os.environ, "S2D_KERNELS": flag, "LLM_CACHE_DIR": tmp, "PYTHONPATH": "."}
            t = time.perf_counter()
            subprocess.run([sys.executable, "-m", "s2d.detective", "run", run_dir, "--out", out, "--no-llm"],
                           env=env, check=True, capture_output=True)
            wall = time.perf_counter() - t
            data = json.load(open(out))
            data.pop("timing", None)
            res[flag] = (wall, json.dumps(data, sort_keys=True))
    (w0, j0), (w1, j1) = res["0"], res["1"]
    same = "identical findings" if j0 == j1 else "MISMATCH"
    print(f"{os.path.basename(run_dir.rstrip('/')):<14}{w0:>9.1f}s{w1:>9.1f}s{w0 / w1:>8.1f}x   {same}")


if __name__ == "__main__":
    assert rustk.LIB is not None, "build the kernels first: cd rust && cargo build --release"
    micro()
    if sys.argv[1:]:
        print(f"\n{'detective':<14}{'python':>10}{'rust':>10}{'speedup':>9}")
        for d in sys.argv[1:]:
            detective(d)
