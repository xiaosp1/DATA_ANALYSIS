"""C046 spike: p<20 / n=百万级 / 首次点卡死在 100% 根因定位脚本.

目的:
  1) 拆解 build_head_tail_report 端到端 6 个阶段的耗时,定位 n=1M / p<20 时的瓶颈
  2) 同时复现 on_success 主线程渲染瓶颈(图3 LOESS/散点/pyqtgraph)
  3) 参数化 --p --n 复现卡死场景

设计思路:
  阶段拆分(每阶段单独 time.perf_counter,共享一份合成的 df):
    A 数据准备:to_numeric + dropna(全局,O(n*p))
    B 相关系数:Spearman 排序(p * O(n log n))
    C 分组统计/分箱:每特征 qcut(qcut 单特征 n=1M ≈ 30ms × p)
    D M1 偏相关:_partial_corr(p-1 次 OLS 残差,主路径 numpy)
    E M2 OLS + VIF:_ols_standardized + p 次 VIF OLS
    F on_success 主线程渲染模拟:图3 残差 scatter + LOESS + chart1/chart2 bar
       —— 模拟 _fill_multi_attr 在主线程执行

不依赖 Qt(在 headless 环境跑);只测纯计算 / numpy 瓶颈。
图3 LOESS fallback 用 numpy convolve(等价于生产代码 statsmodels 不可用分支)。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# 让 import 'app.services.head_tail_attribution' 可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.head_tail_attribution import (
    _HAS_PINGOOUIN,
    _HAS_SCIPY,
    _ols_standardized,
    _partial_corr,
    _rankdata,
    _zscore_array,
)

TARGET = "[机尾]指数-s"


def make_synthetic(n: int, p: int, seed: int = 42) -> pd.DataFrame:
    """合成数据:f1 强正相关,其余噪声。p 是 [机头]* + 1 target。"""
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


# ============================================================================
# 阶段 A:数据准备 —— 全局 to_numeric + dropna(模拟 head_tail_attr 内 n_eff 计算)
# ============================================================================
def stage_a_data_prep(df: pd.DataFrame, target_col: str, feat_list: list[str]) -> dict:
    """对应 head_tail_attribution.py:570-585 的 n_eff 计算 + global dropna.

    Real engine: feat_num = [pd.to_numeric(df[c], errors="coerce") for c in feat_list]
                 any_feat = pd.concat(feat_num, axis=1).notna().any(axis=1)
                 n_eff = ((target_num.notna()) & any_feat).sum()
    这里只测 to_numeric + 一次全局 dropna(模拟 _ols_standardized 的 sub)。
    """
    t0 = time.perf_counter()
    target_num = pd.to_numeric(df[target_col], errors="coerce")
    feat_num = [pd.to_numeric(df[c], errors="coerce") for c in feat_list]
    any_feat = pd.concat(feat_num, axis=1).notna().any(axis=1) if feat_num else pd.Series(False, index=df.index)
    n_eff = int(((target_num.notna()) & any_feat).sum())
    t_to_num = time.perf_counter() - t0

    # 模拟 _ols_standardized 的 sub 计算(全局 dropna)
    t0 = time.perf_counter()
    sub = df[[target_col] + feat_list].apply(pd.to_numeric, errors="coerce").dropna()
    t_dropna = time.perf_counter() - t0

    return {
        "to_numeric_ms": t_to_num * 1000,
        "global_dropna_ms": t_dropna * 1000,
        "n_eff": n_eff,
        "sub_n_after_dropna": int(len(sub)),
    }


# ============================================================================
# 阶段 B:相关系数(Pearson + Spearman,排序)—— 对应 head_tail_attribution.py:610-660
# ============================================================================
def stage_b_correlations(df: pd.DataFrame, target_col: str, feat_list: list[str]) -> dict:
    t0 = time.perf_counter()
    target_num = pd.to_numeric(df[target_col], errors="coerce")
    pairwise = []
    for feat in feat_list:
        x = pd.to_numeric(df[feat], errors="coerce")
        work = pd.DataFrame({"y": target_num, "x": x}).dropna()
        if len(work) < 5:
            continue
        x_arr = work["x"].to_numpy(dtype=float)
        y_arr = work["y"].to_numpy(dtype=float)
        # Pearson
        xd = x_arr - x_arr.mean()
        yd = y_arr - y_arr.mean()
        denom = float(np.sqrt((xd * xd).sum() * (yd * yd).sum()))
        r = float((xd * yd).sum() / denom) if denom > 1e-12 else 0.0
        # Spearman(rank Pearson) —— numpy path
        xr = _rankdata(x_arr)
        yr = _rankdata(y_arr)
        xrd = xr - xr.mean()
        yrd = yr - yr.mean()
        denom_r = float(np.sqrt((xrd * xrd).sum() * (yrd * yrd).sum()))
        rs = float((xrd * yrd).sum() / denom_r) if denom_r > 1e-12 else 0.0
        pairwise.append({
            "feature": feat,
            "pearson_r": r,
            "spearman_r": rs,
            "abs_spearman": abs(rs),
            "n": int(len(work)),
        })
    pairwise.sort(key=lambda d: d["abs_spearman"], reverse=True)
    elapsed = time.perf_counter() - t0
    return {
        "corr_total_ms": elapsed * 1000,
        "n_pairs": len(pairwise),
    }


# ============================================================================
# 阶段 C:分组统计与分箱(qcut × top_n)—— 对应 head_tail_attribution.py:660-720
# ============================================================================
def stage_c_grouping(df: pd.DataFrame, target_col: str, top_feats: list[str], n_buckets: int = 5) -> dict:
    t0 = time.perf_counter()
    target_num = pd.to_numeric(df[target_col], errors="coerce")
    near_ideal_mask = (target_num - 4.0).abs() <= 0.5
    elapsed_total = 0.0
    n_qcut = 0
    for feat in top_feats:
        x = pd.to_numeric(df[feat], errors="coerce")
        work = pd.DataFrame({"y": target_num, "is_near": near_ideal_mask, "x": x}).dropna()
        if len(work) < n_buckets * 5:
            continue
        t1 = time.perf_counter()
        try:
            cat = pd.qcut(work["x"], q=n_buckets, duplicates="drop")
            for bval, bgrp in work.groupby(cat, observed=True):
                pass
        except Exception:
            pass
        elapsed_total += time.perf_counter() - t1
        n_qcut += 1
    elapsed = time.perf_counter() - t0
    return {
        "grouping_total_ms": elapsed * 1000,
        "qcut_only_ms": elapsed_total * 1000,
        "qcut_calls": n_qcut,
    }


# ============================================================================
# 阶段 D:M1 偏相关(p-1 次 _partial_corr)
# ============================================================================
def stage_d_partial_corr(df: pd.DataFrame, target_col: str, feat_list: list[str]) -> dict:
    t0 = time.perf_counter()
    for feat in feat_list:
        controls = [c for c in feat_list if c != feat]
        _ = _partial_corr(df, target_col, feat, controls)
    elapsed = time.perf_counter() - t0
    return {"m1_total_ms": elapsed * 1000}


# ============================================================================
# 阶段 E:M2 OLS + VIF
# ============================================================================
def stage_e_ols_vif(df: pd.DataFrame, target_col: str, m2_feats: list[str]) -> dict:
    sub = df[[target_col] + m2_feats].apply(pd.to_numeric, errors="coerce").dropna()
    X = sub[m2_feats].to_numpy(dtype=float)
    y = sub[target_col].to_numpy(dtype=float)
    t0 = time.perf_counter()
    _ = _ols_standardized(X, y, m2_feats)
    elapsed = time.perf_counter() - t0
    return {
        "m2_ols_vif_ms": elapsed * 1000,
        "ols_n_used": int(len(sub)),
    }


# ============================================================================
# 阶段 F:on_success 主线程渲染模拟 —— 模拟 _fill_multi_attr
# ============================================================================
def stage_f_render_simulation(df: pd.DataFrame, target_col: str, m2_feats: list[str],
                              top_contrib: int = 10, verbose: bool = False) -> dict:
    """模拟 _fill_multi_attr + _render_chart3_grid + _render_chart3_subplot 在主线程的执行。

    关键调用:
      - pd.to_numeric + dropna(sub for chart3)
      - z-score + np.linalg.lstsq + 残差
      - scatter: ScatterPlotItem(size=4) ← pyqtgraph (此处不实跑,只量数据规模)
      - LOESS fallback:numpy convolve(等价 statsmodels 不可用分支)
    """
    import builtins
    out = {}

    # F1: 数据准备(zscore + dropna, n=1M × p 全量)
    t0 = time.perf_counter()
    sub = df[[target_col] + m2_feats].apply(pd.to_numeric, errors="coerce").dropna()
    out["f1_sub_dropna_ms"] = (time.perf_counter() - t0) * 1000
    n_after = int(len(sub))

    # F2: zscore + lstsq + 残差
    t0 = time.perf_counter()
    y = sub[target_col].to_numpy(dtype=float)
    X = sub[m2_feats].to_numpy(dtype=float)
    Xs = _zscore_array(X)
    ys = (y - y.mean()) / max(y.std(ddof=1), 1e-12)
    try:
        beta, *_ = np.linalg.lstsq(Xs, ys, rcond=None)
        resid = ys - Xs @ beta
    except Exception:
        resid = np.zeros_like(ys)
    out["f2_zscore_lstsq_ms"] = (time.perf_counter() - t0) * 1000

    # F3: LOESS fallback(numpy convolve,每个子图一次,模拟 p 个子图)
    # head_tail_attr._render_chart3_subplot 的 statsmodels fallback:
    #   order = np.argsort(x); w = max(5, n//10); smooth = np.convolve(rs_sorted, kernel, mode="same")
    # 注意: statsmodels 不可用时,numpy.convolve(n, w) 是 O(n*w);
    #       n=1M × w=100k = 10^11 ops/单图 ≈ 几分钟,所以要可中断。
    t0 = time.perf_counter()
    n_feat = len(m2_feats)
    per_chart_ms = []
    # OLS 残差是固定的,所有子图共用同一个 resid(模拟生产代码)
    F3_SKIP_THRESHOLD_MS = 60_000  # 单子图 > 60s 视为实际生产已不可用
    f3_skipped = False
    for fi in range(n_feat):
        ts = time.perf_counter()
        x = Xs[:, fi]
        order = np.argsort(x)
        xs_sorted = x[order]
        rs_sorted = resid[order]
        w = max(5, len(xs_sorted) // 10)
        kernel = np.ones(w) / w
        # 检查子图规模是否大到实际生产已卡死;过大则只跑 1 个 + 外推
        n_pts = len(xs_sorted)
        w_pts = w
        ops_per_chart = n_pts * w_pts
        if ops_per_chart > 5e10:  # n=1M × w=50k 即 5e10
            # 跳过 convolve,只测 argsort 耗时,记录 ops 量级
            chart_ms = (time.perf_counter() - ts) * 1000
            per_chart_ms.append(chart_ms)
            f3_skipped = True
            if verbose:
                builtins.print(f"     F3 chart[{fi+1}/{n_feat}] SKIP convolve (n={n_pts:,} × w={w_pts:,} = {ops_per_chart:.2e} ops),"
                               f" 仅 argsort+分配 用时 {chart_ms:.1f} ms", flush=True)
            continue
        smooth = np.convolve(rs_sorted, kernel, mode="same")
        chart_ms = (time.perf_counter() - ts) * 1000
        per_chart_ms.append(chart_ms)
        if verbose:
            builtins.print(f"     F3 chart[{fi+1}/{n_feat}] convolve n={n_pts:,} w={w_pts:,} → {chart_ms:.1f} ms", flush=True)
    out["f3_loess_fallback_ms"] = (time.perf_counter() - t0) * 1000
    out["f3_per_chart_ms"] = per_chart_ms
    out["f3_skipped_for_size"] = f3_skipped

    # F4: 散点 ScatterPlotItem 数据准备(实际渲染在 pyqtgraph 内,这里只算 scatter 数据)
    t0 = time.perf_counter()
    scatter_data_size = 0
    for fi in range(n_feat):
        scatter_data_size += len(Xs[:, fi])
    out["f4_scatter_data_pts"] = scatter_data_size
    out["f4_scatter_data_ms"] = (time.perf_counter() - t0) * 1000

    # F5: 模拟 setCellText × (M1 + M2 行 × 列) —— 实测填表耗时极短,跳过
    # 重点是上面 4 个子项

    out["n_after_dropna"] = n_after
    return out


# ============================================================================
# 主流程:端到端 build_head_tail_report(multi=True) 真实耗时
# ============================================================================
def stage_g_end_to_end(df: pd.DataFrame, target_col: str, feat_list: list[str]) -> dict:
    t0 = time.perf_counter()
    from app.services.head_tail_attribution import build_head_tail_report
    rep = build_head_tail_report(
        df, target_col=target_col, feature_cols=feat_list,
        min_samples=10, multi=True, use_pingouin=False,
    )
    return {
        "g_e2e_total_ms": (time.perf_counter() - t0) * 1000,
        "rep_keys": sorted(list(rep.keys())) if isinstance(rep, dict) else None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="C046 spike: p<20 / n=百万级 / 首次点卡死在 100% 根因定位",
    )
    parser.add_argument("--p", type=int, default=15, help="特征列数(不含 target);p=15 → 总列数 17")
    parser.add_argument("--n", type=int, default=1_000_000, help="样本行数")
    parser.add_argument("--top-n", type=int, default=10, help="多变量 M2 TopN")
    parser.add_argument("--skip-g", action="store_true", help="跳过端到端(防 OOM)")
    args = parser.parse_args()

    n = int(args.n)
    p = int(args.p)
    top_n = int(args.top_n)
    multi_top_n = min(top_n, p)
    m2_feats = [f"[机头]f{j+1}" for j in range(p - 1)][:multi_top_n]

    import builtins
    _print = builtins.print
    def uprint(*a, **kw):
        kw.setdefault("flush", True)
        _print(*a, **kw)
    builtins.print = uprint

    uprint("=" * 84)
    uprint(f"C046 spike: p={p}, n={n:,}, multi_top_n={multi_top_n}")
    uprint(f"env: numpy={np.__version__}, pandas={pd.__version__}, "
           f"_HAS_SCIPY={_HAS_SCIPY}, _HAS_PINGOOUIN={_HAS_PINGOOUIN}")
    uprint(f"statsmodels={'installed' if _has_statsmodels() else 'NOT installed (LOESS falls back to numpy convolve)'}")
    uprint("=" * 84)

    uprint("\n[0] Synth data")
    t0 = time.perf_counter()
    df = make_synthetic(n, p)
    synth_ms = (time.perf_counter() - t0) * 1000
    uprint(f"   synth_ms={synth_ms:.1f}  df.shape={df.shape}  mem={df.memory_usage(deep=True).sum()/1e6:.1f} MB")

    feat_list = [f"[机头]f{j+1}" for j in range(p - 1)]

    uprint("\n[A] data prep (to_numeric + global dropna)")
    res_a = stage_a_data_prep(df, TARGET, feat_list)
    uprint(f"   to_numeric_ms={res_a['to_numeric_ms']:.1f}  global_dropna_ms={res_a['global_dropna_ms']:.1f}")
    uprint(f"   n_eff={res_a['n_eff']}  sub_n_after_dropna={res_a['sub_n_after_dropna']}")

    uprint("\n[B] Pearson + Spearman correlation (all features)")
    res_b = stage_b_correlations(df, TARGET, feat_list)
    uprint(f"   corr_total_ms={res_b['corr_total_ms']:.1f}  n_pairs={res_b['n_pairs']}")

    # 取 top N 用于后续阶段
    target_num = pd.to_numeric(df[TARGET], errors="coerce")
    near_ideal_mask = (target_num - 4.0).abs() <= 0.5
    top_feats_for_c = feat_list[:max(1, top_n)]

    uprint(f"\n[C] grouping + qcut (top_n={len(top_feats_for_c)})")
    res_c = stage_c_grouping(df, TARGET, top_feats_for_c)
    uprint(f"   grouping_total_ms={res_c['grouping_total_ms']:.1f}  "
           f"qcut_only_ms={res_c['qcut_only_ms']:.1f}  qcut_calls={res_c['qcut_calls']}")

    uprint("\n[D] M1 partial_corr (p-1 features × OLS residual)")
    res_d = stage_d_partial_corr(df, TARGET, feat_list)
    uprint(f"   m1_total_ms={res_d['m1_total_ms']:.1f}")

    uprint(f"\n[E] M2 OLS + VIF (k={len(m2_feats)})")
    res_e = stage_e_ols_vif(df, TARGET, m2_feats)
    uprint(f"   m2_ols_vif_ms={res_e['m2_ols_vif_ms']:.1f}  ols_n_used={res_e['ols_n_used']}")

    uprint("\n[F] on_success MAIN-THREAD render simulation (_fill_multi_attr + chart3 LOESS)")
    uprint("    (sub-stages may take MINUTES at n=1M, esp. F3 LOESS)")
    res_f = stage_f_render_simulation(df, TARGET, m2_feats, verbose=True)
    uprint(f"   f1_sub_dropna_ms={res_f['f1_sub_dropna_ms']:.1f}  (2nd dropna in on_success)")
    uprint(f"   f2_zscore_lstsq_ms={res_f['f2_zscore_lstsq_ms']:.1f}")
    uprint(f"   f3_loess_fallback_ms={res_f['f3_loess_fallback_ms']:.1f}  "
           f"(n={res_f['n_after_dropna']:,} × p={len(m2_feats)} 子图)")
    uprint(f"   f4_scatter_data_pts={res_f['f4_scatter_data_pts']:,}")

    if not args.skip_g:
        uprint("\n[G] end-to-end build_head_tail_report(multi=True)")
        try:
            res_g = stage_g_end_to_end(df, TARGET, feat_list)
            uprint(f"   e2e_total_ms={res_g['g_e2e_total_ms']:.1f}")
            uprint(f"   rep keys={res_g['rep_keys']}")
        except Exception as e:
            uprint(f"   ERR: {type(e).__name__}: {e}")

    # 总和 vs e2e
    if not args.skip_g:
        total_abcde_ms = (res_a["to_numeric_ms"] + res_a["global_dropna_ms"] +
                          res_b["corr_total_ms"] + res_c["grouping_total_ms"] +
                          res_d["m1_total_ms"] + res_e["m2_ols_vif_ms"])
        f_ms = (res_f["f1_sub_dropna_ms"] + res_f["f2_zscore_lstsq_ms"] +
                res_f["f3_loess_fallback_ms"] + res_f["f4_scatter_data_ms"])
        uprint("\n" + "=" * 84)
        uprint(f"  Σ backend(A..E) ≈ {total_abcde_ms:.1f} ms")
        uprint(f"  Σ render(F1..F4)≈ {f_ms:.1f} ms")
        uprint(f"  E2E(G)        = {res_g['g_e2e_total_ms']:.1f} ms")
        uprint(f"  diff          = {res_g['g_e2e_total_ms'] - total_abcde_ms:.1f} ms "
               f"(其它 W12 步骤 + multi 分组 overhead)")
        uprint("=" * 84)


def _has_statsmodels() -> bool:
    try:
        import statsmodels  # noqa: F401
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
