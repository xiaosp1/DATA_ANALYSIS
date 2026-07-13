"""W12 机尾「指数-s」机尾归因分析引擎。

纯函数，不依赖 Qt。输入是一张已经跨类合并好的宽表（列名带 [机头]/[机尾] 前缀），
输出可直接被 UI + AI prompt 消费的 dict。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd


class AttributionCancelledError(Exception):
    """用户取消机尾归因分析时抛出。"""
    pass

try:  # scipy 可选，缺失时 fallback 到 numpy 手工实现
    from scipy.stats import pearsonr as _scipy_pearsonr
    from scipy.stats import spearmanr as _scipy_spearmanr
    _HAS_SCIPY = True
except Exception:  # pragma: no cover
    _scipy_pearsonr = None
    _scipy_spearmanr = None
    _HAS_SCIPY = False


ProgressCb = Callable[[int, str], None] | None


def _call_progress(rp: ProgressCb, pct: int, msg: str) -> None:
    if rp is None:
        return
    try:
        rp(int(pct), str(msg))
    except Exception:
        pass


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if _HAS_SCIPY:
        try:
            r, _ = _scipy_pearsonr(x, y)
            return float(r) if np.isfinite(r) else 0.0
        except Exception:
            pass
    if x.size < 2:
        return 0.0
    xd = x - x.mean()
    yd = y - y.mean()
    denom = float(np.sqrt((xd * xd).sum() * (yd * yd).sum()))
    if denom <= 1e-12:
        return 0.0
    return float((xd * yd).sum() / denom)


def _rankdata(a: np.ndarray) -> np.ndarray:
    """简易平均秩，兼容 scipy.stats.rankdata(method='average')。"""
    a = np.asarray(a, dtype=float)
    n = a.size
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and a[order[j + 1]] == a[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based
        ranks[order[i : j + 1]] = avg_rank
        i = j + 1
    return ranks


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if _HAS_SCIPY:
        try:
            res = _scipy_spearmanr(x, y)
            r = res.correlation if hasattr(res, "correlation") else res[0]
            return float(r) if np.isfinite(r) else 0.0
        except Exception:
            pass
    if x.size < 2:
        return 0.0
    return _pearson(_rankdata(x), _rankdata(y))


def _direction(r: float) -> str:
    ar = abs(r)
    if ar < 0.1:
        return "弱相关"
    return "正相关" if r > 0 else "负相关"


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if not np.isfinite(f):
        return None
    return f


def _safe_std(series: pd.Series) -> float:
    n = int(series.notna().sum())
    if n <= 1:
        return 0.0
    s = float(series.std(ddof=1))
    return s if np.isfinite(s) else 0.0


def build_head_tail_report(
    df: pd.DataFrame,
    target_col: str,
    head_prefix: str = "[机头]",
    tail_prefix: str = "[机尾]",
    ideal_value: float = 4.0,
    min_samples: int = 30,
    feature_cols: Iterable[str] | None = None,
    time_col: str = "时间",
    ideal_tol: float = 0.5,
    n_buckets: int = 5,
    top_n: int = 20,
    top_rules_n: int = 5,
    report_progress: ProgressCb = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    _call_progress(report_progress, 5, "准备数据...")

    if df is None or len(df) == 0:
        raise ValueError("数据集为空，无法进行机尾指数-s 归因分析。")
    if target_col not in df.columns:
        raise KeyError(f"目标列 {target_col} 不在数据集中，请确认已进行跨类合并。")

    warnings_list: list[str] = []

    def _looks_like_time(col_name: str) -> bool:
        c = str(col_name)
        if c == time_col or c.endswith(time_col):
            return True
        if c.lower().endswith("时间") or c.lower().endswith("time") or c.lower().endswith("date"):
            return True
        return False

    has_head = any(str(c).startswith(head_prefix) for c in df.columns)
    has_tail = any(str(c).startswith(tail_prefix) for c in df.columns)
    if not has_head:
        warnings_list.append(f"未检测到 {head_prefix} 前缀的机头列，请确认已执行跨类合并。")
    if not has_tail:
        warnings_list.append(f"未检测到 {tail_prefix} 前缀的机尾列，请确认已执行跨类合并。")

    if feature_cols is None:
        feat_list: list[str] = []
        for c in df.columns:
            cname = str(c)
            if cname == target_col:
                continue
            if _looks_like_time(cname):
                continue
            if not cname.startswith(head_prefix):
                continue
            s = df[c]
            if pd.api.types.is_numeric_dtype(s):
                feat_list.append(cname)
            else:
                try:
                    conv = pd.to_numeric(s, errors="coerce")
                    if conv.notna().sum() >= max(1, int(len(s) * 0.8)):
                        feat_list.append(cname)
                except Exception:
                    pass
    else:
        feat_list = [str(c) for c in feature_cols if c in df.columns and str(c) != target_col]

    if not feat_list:
        raise ValueError(f"未找到 {head_prefix}* 前缀的机头数值特征列。请先执行跨类合并。")

    _call_progress(report_progress, 10, "对齐目标列与特征...")

    target_raw = df[target_col]
    target_num = pd.to_numeric(target_raw, errors="coerce")
    near_ideal_mask = (target_num - float(ideal_value)).abs() <= float(ideal_tol)
    ideal_exact_mask = (target_num.round() == float(ideal_value))

    n_total = int(len(df))
    target_valid = target_num.dropna()
    n_target_valid = int(target_valid.shape[0])
    if n_target_valid == 0:
        raise ValueError(f"目标列 {target_col} 全为非数值/空值，无法分析。")

    t_mean = _safe_float(target_valid.mean())
    t_std = _safe_std(target_valid)
    t_min = _safe_float(target_valid.min())
    t_max = _safe_float(target_valid.max())
    pct_ideal = float(ideal_exact_mask.sum() / n_target_valid) if n_target_valid else 0.0
    pct_near = float(near_ideal_mask.sum() / n_target_valid) if n_target_valid else 0.0

    vc = target_valid.round().value_counts().head(10)
    value_counts: dict[str, int] = {}
    for k, v in vc.items():
        kf = float(k)
        key = str(int(kf)) if kf.is_integer() else f"{kf:g}"
        value_counts[key] = int(v)

    target_dist = {
        "mean": t_mean,
        "std": t_std,
        "min": t_min,
        "max": t_max,
        "pct_ideal": pct_ideal,
        "pct_near_ideal": pct_near,
        "value_counts": value_counts,
    }

    _call_progress(report_progress, 20, "计算相关系数...")

    def _check_cancel(msg: str = "归因分析已被用户取消") -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise AttributionCancelledError(msg)

    pairwise: list[dict[str, Any]] = []
    n_feats = len(feat_list)
    for idx, feat in enumerate(feat_list):
        _check_cancel("归因分析已被用户取消（相关系数阶段）")
        fv = pd.to_numeric(df[feat], errors="coerce")
        sub = pd.DataFrame({"y": target_num, "x": fv}).dropna()
        n = int(len(sub))
        if n < min_samples:
            warnings_list.append(f"特征 {feat} 有效配对样本 {n} < {min_samples}，结论仅供参考。")
        if n < 5:
            pearson = 0.0
            spearman = 0.0
        else:
            x_arr = sub["x"].to_numpy(dtype=float)
            y_arr = sub["y"].to_numpy(dtype=float)
            pearson = _pearson(x_arr, y_arr)
            spearman = _spearman(x_arr, y_arr)
        pairwise.append({
            "feature": feat,
            "n": n,
            "pearson_r": pearson,
            "spearman_r": spearman,
            "abs_spearman": abs(spearman),
        })
        if n_feats > 0:
            pct = 20 + int(30 * (idx + 1) / n_feats)
            _call_progress(report_progress, pct, f"相关系数：{idx+1}/{n_feats}")

    pairwise.sort(key=lambda d: d["abs_spearman"], reverse=True)
    top_feats = pairwise[: max(1, int(top_n))]

    _call_progress(report_progress, 55, "分组统计与分箱...")

    attribution: list[dict[str, Any]] = []
    for i, item in enumerate(top_feats):
        _check_cancel("归因分析已被用户取消（分组统计阶段）")
        feat = item["feature"]
        fv = pd.to_numeric(df[feat], errors="coerce")
        work = pd.DataFrame({"y": target_num, "is_near": near_ideal_mask, "x": fv}).dropna(subset=["y", "x"])
        n = int(len(work))
        pearson = float(item["pearson_r"])
        spearman = float(item["spearman_r"])
        direction = _direction(spearman)

        ideal_group = work.loc[work["is_near"], "x"]
        off_group = work.loc[~work["is_near"], "x"]

        def _grp_stat(g: pd.Series) -> tuple[float | None, float | None, tuple[float | None, float | None]]:
            if len(g) < 2:
                return (None, None, (None, None))
            m = float(g.mean())
            s = float(g.std(ddof=1)) if len(g) > 1 else 0.0
            if not np.isfinite(s):
                s = 0.0
            return (m, s, (m - s, m + s))

        m_i, s_i, w_i = _grp_stat(ideal_group)
        m_o, s_o, w_o = _grp_stat(off_group)

        buckets: list[dict[str, Any]] = []
        if n >= n_buckets * 5:
            try:
                cat = pd.qcut(work["x"], q=n_buckets, duplicates="drop")
                for bval, bgrp in work.groupby(cat, observed=True):
                    bn = int(len(bgrp))
                    if bn == 0:
                        continue
                    bmean = float(bgrp["y"].mean())
                    bpct = float(bgrp["is_near"].mean())
                    lo = _safe_float(bval.left)
                    hi = _safe_float(bval.right)
                    buckets.append({
                        "range": (lo, hi),
                        "n": bn,
                        "target_mean": bmean,
                        "pct_near_ideal": bpct,
                    })
            except Exception:
                buckets = []
        else:
            if n < min_samples:
                warnings_list.append(f"特征 {feat} 样本数 {n} 不足，跳过五分位分箱。")

        attribution.append({
            "feature": feat,
            "n": n,
            "pearson_r": float(pearson),
            "spearman_r": float(spearman),
            "abs_spearman": float(abs(spearman)),
            "direction": direction,
            "mean_when_ideal": m_i,
            "std_when_ideal": s_i,
            "mean_when_off": m_o,
            "std_when_off": s_o,
            "window_ideal": w_i,
            "window_off": w_o,
            "bucket_analysis": buckets,
        })
        pct = 55 + int(20 * (i + 1) / len(top_feats))
        _call_progress(report_progress, pct, f"分组统计：{i+1}/{len(top_feats)}")

    _call_progress(report_progress, 78, "规则挖掘...")

    rules: list[dict[str, Any]] = []
    rule_feats = attribution[: max(1, int(top_rules_n))]
    for ritem in rule_feats:
        _check_cancel("归因分析已被用户取消（规则挖掘阶段）")
        feat = ritem["feature"]
        fv = pd.to_numeric(df[feat], errors="coerce")
        work = pd.DataFrame({"y": target_num, "is_near": near_ideal_mask, "x": fv}).dropna()
        if len(work) < min_samples:
            continue
        best: dict[str, Any] | None = None
        qs = work["x"].quantile([1 / 3, 0.5, 2 / 3]).tolist()
        for thr in qs:
            thr = float(thr)
            if not np.isfinite(thr):
                continue
            for op in ("<=", ">"):
                mask = work["x"] <= thr if op == "<=" else work["x"] > thr
                n_sel = int(mask.sum())
                if n_sel < max(10, min_samples // 3):
                    continue
                pct_sel = float(work.loc[mask, "is_near"].mean())
                tmean = float(work.loc[mask, "y"].mean())
                score = pct_sel * (n_sel ** 0.25)
                candidate = {
                    "feature": feat,
                    "op": op,
                    "threshold": thr,
                    "n": n_sel,
                    "pct_near_ideal": pct_sel,
                    "target_mean": tmean,
                    "_score": score,
                }
                if best is None or candidate["_score"] > best["_score"]:
                    best = candidate
        if best is not None:
            best.pop("_score", None)
            rules.append(best)

    rules.sort(key=lambda d: d["pct_near_ideal"], reverse=True)
    top_rules = rules[: max(1, int(top_rules_n))]

    _call_progress(report_progress, 92, "综合工艺窗口...")

    overall_window: dict[str, dict[str, float]] = {}
    for item in attribution[:3]:
        feat = item["feature"]
        lo, hi = item.get("window_ideal") or (None, None)
        mean = item.get("mean_when_ideal")
        if lo is None or hi is None or mean is None:
            continue
        overall_window[feat] = {"lo": float(lo), "hi": float(hi), "mean": float(mean)}

    _call_progress(report_progress, 100, "完成")

    feat_num = [pd.to_numeric(df[c], errors="coerce") for c in feat_list]
    any_feat = pd.concat(feat_num, axis=1).notna().any(axis=1) if feat_num else pd.Series(False, index=df.index)
    n_eff = int(((target_num.notna()) & any_feat).sum())

    return {
        "meta": {
            "mode": "head_tail_attribution",
            "n_rows": int(n_eff),
            "n_rows_total": n_total,
            "n_target_valid": n_target_valid,
            "n_head_features": len(feat_list),
            "target_col": str(target_col),
            "ideal_value": float(ideal_value),
            "ideal_tol": float(ideal_tol),
            "has_scipy": bool(_HAS_SCIPY),
            "warnings": warnings_list,
        },
        "target_dist": target_dist,
        "attribution": attribution,
        "top_rules": top_rules,
        "overall_suggested_window": overall_window,
    }
