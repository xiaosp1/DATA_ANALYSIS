"""Spike: measure ACTUAL production LOESS fallback at n=1M and smaller."""
import time
import os
import sys
import numpy as np

print("=" * 80)
print("LOESS fallback (numpy.convolve) per-chart wall time")
print("kernel w = max(5, n//10), statsmodels NOT installed branch")
print("=" * 80)

for n in [10_000, 50_000, 100_000, 200_000, 500_000]:
    rng = np.random.default_rng(42)
    x = rng.normal(0, 1, n)
    resid = rng.normal(0, 1, n)
    order = np.argsort(x)
    xs_sorted = x[order]
    rs_sorted = resid[order]
    w = max(5, len(xs_sorted) // 10)
    kernel = np.ones(w) / w
    t0 = time.perf_counter()
    smooth = np.convolve(rs_sorted, kernel, mode="same")
    ms = (time.perf_counter() - t0) * 1000
    ops = n * w
    print(f"n={n:>7,}  w={w:>6,}  ops={ops:.2e}  → {ms:>9.1f} ms  ({ops/ms/1e6:.1f} Mops/s)")

print("\nExtrap to n=1M, single chart:")
print(f"  estimated per chart ≈ 100,000 × 100,000 / ops_rate")
print(f"  at p=10 multi_var → 10 charts in series on MAIN thread")
print(f"  → could be TENS OF MINUTES in worst case")
