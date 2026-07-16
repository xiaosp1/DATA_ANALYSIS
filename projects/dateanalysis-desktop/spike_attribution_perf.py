"""C033 spike: measure actual time for M1/M2/data-prep at various p x n scales.

Run with: .venv/Scripts/python.exe spike_attribution_perf.py
"""
from __future__ import annotations
import time
import sys
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, ".")

from app.services.head_tail_attribution import (
    _partial_corr,
    _ols_standardized,
    _HAS_PINGOOUIN,
)


TARGET = "[机尾]指数-s"


def make_synthetic(n: int, p: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=n, freq="1min")
    cols = {"时间": t}
    for j in range(p - 1):
        cols[f"[机头]f{j+1}"] = rng.normal(50, 5, n)
    target = np.clip(
        np.round(4.0 + 0.3 * (cols["[机头]f1"] - 50) + rng.normal(0, 0.4, n)),
        1, 8,
    ).astype(int)
    cols[TARGET] = target
    return pd.DataFrame(cols)


def test_data_prep(n: int, p: int):
    df = make_synthetic(n, p)
    feat_list = [f"[机头]f{j+1}" for j in range(p - 1)]

    t0 = time.perf_counter()
    target_num = pd.to_numeric(df[TARGET], errors="coerce")
    near_ideal = (target_num - 4.0).abs() <= 0.5
    for f in feat_list:
        df[f + "_n"] = pd.to_numeric(df[f], errors="coerce")
    dt_to_numeric = time.perf_counter() - t0

    t0 = time.perf_counter()
    work = pd.DataFrame({"y": target_num, "x": df[feat_list[0] + "_n"]}).dropna()
    dt_dropna = time.perf_counter() - t0

    t0 = time.perf_counter()
    try:
        _ = pd.qcut(df[feat_list[0] + "_n"], q=5, duplicates="drop")
    except Exception:
        pass
    dt_qcut = time.perf_counter() - t0

    return dt_to_numeric, dt_dropna, dt_qcut


def test_partial_corr(n: int, p: int) -> float:
    df = make_synthetic(n, p)
    feat_list = [f"[机头]f{j+1}" for j in range(p - 1)]
    t0 = time.perf_counter()
    for feat in feat_list:
        controls = [c for c in feat_list if c != feat]
        _ = _partial_corr(df, TARGET, feat, controls)
    return time.perf_counter() - t0


def test_ols(n: int, p: int) -> float:
    df = make_synthetic(n, p)
    feat_list = [f"[机头]f{j+1}" for j in range(p - 1)]
    sub = df[[TARGET] + feat_list].apply(pd.to_numeric, errors="coerce").dropna()
    X = sub[feat_list].to_numpy(dtype=float)
    y = sub[TARGET].to_numpy(dtype=float)
    t0 = time.perf_counter()
    _ = _ols_standardized(X, y, feat_list)
    return time.perf_counter() - t0


def test_full_report(n: int, p: int, multi: bool = True) -> float:
    from app.services.head_tail_attribution import build_head_tail_report
    df = make_synthetic(n, p)
    feat_list = [f"[机头]f{j+1}" for j in range(p - 1)]
    t0 = time.perf_counter()
    _ = build_head_tail_report(
        df,
        target_col=TARGET,
        feature_cols=feat_list,
        min_samples=10,
        multi=multi,
        use_pingouin=False,
    )
    return time.perf_counter() - t0


def main():
    print("=" * 80)
    print(f"Python: {sys.version.split()[0]}")
    print(f"numpy={np.__version__}, pandas={pd.__version__}")
    print(f"_HAS_PINGOOUIN={_HAS_PINGOOUIN}")
    print("=" * 80)

    cases = [
        ("sample",   40,    10),
        ("owner-p2", 640000, 2),
        ("owner-p4", 640000, 4),
        ("med-p10",  1000,  10),
        ("med-p20",  1000,  20),
        ("med-p50",  1000,  50),
    ]

    print("\n## Direction 2/3: M1 partial_corr / M2 OLS timing")
    print(f"{'label':<12} {'n':>8} {'p':>4} {'M1(ms)':>10} {'M2(ms)':>10}")
    print("-" * 50)
    for label, n, p in cases:
        try:
            t1 = test_partial_corr(n, p)
        except Exception as e:
            t1 = -1
            print(f"  M1 err: {e}")
        try:
            t2 = test_ols(n, p)
        except Exception as e:
            t2 = -1
            print(f"  M2 err: {e}")
        print(f"{label:<12} {n:>8} {p:>4} {t1*1000:>9.1f} {t2*1000:>9.1f}")

    print("\n## Direction 5: Data prep timing")
    print(f"{'label':<12} {'n':>8} {'p':>4} {'to_num':>10} {'dropna':>10} {'qcut':>10}")
    print("-" * 60)
    for label, n, p in cases:
        try:
            t1, t2, t3 = test_data_prep(n, p)
            print(f"{label:<12} {n:>8} {p:>4} {t1*1000:>9.1f} {t2*1000:>9.1f} {t3*1000:>9.1f}")
        except Exception as e:
            print(f"{label} err: {e}")

    print("\n## Direction 4: build_head_tail_report(multi=True) end-to-end")
    print(f"{'label':<12} {'n':>8} {'p':>4} {'total(ms)':>12}")
    print("-" * 50)
    for label, n, p in cases:
        try:
            t = test_full_report(n, p, multi=True)
            print(f"{label:<12} {n:>8} {p:>4} {t*1000:>11.1f}")
        except Exception as e:
            print(f"{label} err: {e}")

    print("\n## Control: build_head_tail_report(multi=False) W12 only")
    print(f"{'label':<12} {'n':>8} {'p':>4} {'total(ms)':>12}")
    print("-" * 50)
    for label, n, p in cases:
        try:
            t = test_full_report(n, p, multi=False)
            print(f"{label:<12} {n:>8} {p:>4} {t*1000:>11.1f}")
        except Exception as e:
            print(f"{label} err: {e}")


if __name__ == "__main__":
    main()
