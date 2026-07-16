"""Spike: chart3 ScatterPlotItem data prep + actual rendering time on main thread."""
import time
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.head_tail_attribution import _zscore_array


def make_synthetic(n, p, seed=42):
    rng = np.random.default_rng(seed)
    cols = {}
    for j in range(p - 1):
        cols[f"[机头]f{j+1}"] = rng.normal(50, 5, n)
    target = np.clip(np.round(4.0 + 0.3 * (cols["[机头]f1"] - 50) + rng.normal(0, 0.4, n)), 1, 8).astype(int)
    cols["[机尾]指数-s"] = target
    return pd.DataFrame(cols)


print("=" * 70)
print("Chart3 data prep + per-chart render (10 charts in series)")
print("=" * 70)
for n, p in [(100_000, 5), (1_000_000, 5), (1_000_000, 10), (1_000_000, 15)]:
    df = make_synthetic(n, p)
    target_col = "[机尾]指数-s"
    m2_feats = [f"[机头]f{j+1}" for j in range(min(p - 1, 10))]

    # F1+F2: dropna + zscore + lstsq + resid
    t0 = time.perf_counter()
    sub = df[[target_col] + m2_feats].apply(pd.to_numeric, errors="coerce").dropna()
    y = sub[target_col].to_numpy(dtype=float)
    X = sub[m2_feats].to_numpy(dtype=float)
    Xs = _zscore_array(X)
    ys = (y - y.mean()) / max(y.std(ddof=1), 1e-12)
    beta, *_ = np.linalg.lstsq(Xs, ys, rcond=None)
    resid = ys - Xs @ beta
    f12_ms = (time.perf_counter() - t0) * 1000

    # F3 per-chart cost (LOESS fallback argsort + convolve) — just measure argsort part
    t0 = time.perf_counter()
    for fi in range(len(m2_feats)):
        x = Xs[:, fi]
        order = np.argsort(x)
        # simulate scatter data (no actual pyqtgraph render)
        _scatter = (x, resid)
    f_argsort_ms = (time.perf_counter() - t0) * 1000

    print(f"n={n:>9,} p={p:>3}  F1+F2(sub+zscore+lstsq)={f12_ms:>8.1f} ms  F3_argsort×{len(m2_feats)}={f_argsort_ms:>8.1f} ms")
    print(f"  scatter pts per chart = {n:,}  total pts across {len(m2_feats)} charts = {n*len(m2_feats):,}")
