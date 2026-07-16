"""Spike: confirm M1 _partial_corr scaling with n and p.

Per-call cost: 2 OLS residuals (each np.linalg.lstsq on (n, p-1) matrix) + Pearson.
OLS on (n, k): O(n*k²) flops. With k = p-1 controls, p-1 calls per feat, p feats:
  M1_total = O(p * n * p²) = O(n * p³)
For n=1M, p=15: 1e6 * 15³ = 3.4e9 flops per M1 (15 features).
On 1 GFlop/s Python (numpy.linalg.lstsq is BLAS, faster) → ~3s ideal, but observed 11s.
"""
import time
import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.head_tail_attribution import _partial_corr

TARGET = "[机尾]指数-s"


def make_synthetic(n: int, p: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cols = {}
    for j in range(p - 1):
        cols[f"[机头]f{j+1}"] = rng.normal(50, 5, n)
    target = np.clip(
        np.round(4.0 + 0.3 * (cols["[机头]f1"] - 50) + rng.normal(0, 0.4, n)),
        1, 8,
    ).astype(int)
    cols[TARGET] = target
    return pd.DataFrame(cols)


print("=" * 70)
print("M1 _partial_corr per-feat cost (numpy path; pingouin NOT installed)")
print("=" * 70)
print(f"{'n':>10} {'p':>4} {'feats':>6} {'per_feat_ms':>12} {'M1_total_ms':>14}")
print("-" * 60)
for n, p in [(10_000, 5), (100_000, 5), (1_000_000, 5),
             (10_000, 15), (100_000, 15), (1_000_000, 15),
             (1_000_000, 20)]:
    df = make_synthetic(n, p)
    feat_list = [f"[机头]f{j+1}" for j in range(p - 1)]
    # warmup
    _ = _partial_corr(df, TARGET, feat_list[0], feat_list[1:3])
    t0 = time.perf_counter()
    for feat in feat_list:
        controls = [c for c in feat_list if c != feat]
        _ = _partial_corr(df, TARGET, feat, controls)
    total_ms = (time.perf_counter() - t0) * 1000
    per_feat = total_ms / len(feat_list)
    print(f"{n:>10,} {p:>4} {len(feat_list):>6} {per_feat:>12.1f} {total_ms:>14.1f}")
