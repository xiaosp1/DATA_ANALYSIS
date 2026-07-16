"""W12 机尾「指数-s」机尾归因分析引擎。

纯函数,不依赖 Qt。输入是一张已经跨类合并好的宽表(列名带 [机头]/[机尾] 前缀),
输出可直接被 UI + AI prompt 消费的 dict。
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

# ===== C047 心跳日志基础设施(only logging; 不改业务行为) =====
_HB_T0 = time.time()  # 进程级 t0 锚点;每秒 5Hz 心跳可视化用
_HB_LAST: dict[tuple[int, str], float] = {}  # (pct, msg) -> last_print_monotonic
_HB_DEDUP_WINDOW = 0.2  # 200ms 限流,同样 (pct,msg) 只打一次


def _hb(msg: str, pct: int = -1) -> None:
    """5Hz 心跳:每次调用打一行到 stderr;模块级 _HB_T0 锚定相对秒数。

    仅日志,不抛异常、不影响返回值。
    """
    try:
        line = "[ATTR] t+%.3fs pct=%d %s" % (time.time() - _HB_T0, int(pct), str(msg))
        print(line, file=sys.stderr)
    except Exception:
        pass


class AttributionCancelledError(Exception):
    """用户取消机尾归因分析时抛出。"""
    pass

try:  # scipy 可选,缺失时 fallback 到 numpy 手工实现
    from scipy.stats import pearsonr as _scipy_pearsonr
    from scipy.stats import spearmanr as _scipy_spearmanr
    _HAS_SCIPY = True
except Exception:  # pragma: no cover
    _scipy_pearsonr = None
    _scipy_spearmanr = None
    _HAS_SCIPY = False


ProgressCb = Callable[[int, str], None] | None


_last_pct = 0  # 模块级单调性游标(跨调用保留;保证进度条永不倒退,C034)


def _call_progress(rp: ProgressCb, pct: int, msg: str) -> None:
    global _last_pct
    if rp is None:
        return
    pct = max(_last_pct, int(pct))  # ★ 强制单调递增
    pct_changed = (pct != _last_pct)
    _last_pct = pct
    # C047 5Hz 心跳:同样 (pct,msg) 200ms 内只打一次;pct 变化强制打
    try:
        now = time.monotonic()
        key = (int(pct), str(msg))
        last_ts = _HB_LAST.get(key)
        if pct_changed or last_ts is None or (now - last_ts) >= _HB_DEDUP_WINDOW:
            _HB_LAST[key] = now
            _hb(str(msg), pct)
    except Exception:
        pass
    try:
        rp(pct, str(msg))
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
    """简易平均秩,兼容 scipy.stats.rankdata(method='average')。"""
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


# ============================================================================
# S5 多变量归因(M1 偏相关 + M2 OLS 标准化系数 + VIF)
# 主路径用 numpy 实现;pingouin 可选,仅在偏相关精确化路径使用。
# ============================================================================

try:  # pingouin 可选;缺失时主路径降级到 numpy 残差法
    import pingouin as _pg  # type: ignore
    _HAS_PINGOOUIN = True
except Exception:  # pragma: no cover
    _pg = None
    _HAS_PINGOOUIN = False


def _zscore_array(arr: np.ndarray) -> np.ndarray:
    """逐列 z-score,常数列置 0。返回 float64 数组。"""
    a = np.asarray(arr, dtype=float)
    if a.ndim == 1:
        a = a.reshape(-1, 1)
    mu = a.mean(axis=0)
    sd = a.std(axis=0, ddof=1)
    # std=0 列(常数列)保持为 0,zscore 后仍是 nan;用 0 替代
    sd_safe = np.where(sd > 1e-12, sd, 1.0)
    z = (a - mu) / sd_safe
    z[:, sd <= 1e-12] = 0.0
    return z


def _ols_residual(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """OLS 取残差;X 至少 1 列;y/X 必须是已经 dropna 后的等长 float 数组。"""
    n = int(y.shape[0])
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    k = int(X.shape[1])
    if k == 0:
        return y - y.mean()
    XtX = X.T @ X
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        yhat = X @ beta
        return y - yhat
    except Exception:
        return y - y.mean()


def _partial_corr(
    df: pd.DataFrame,
    target: str,
    x: str,
    controls: list[str],
) -> tuple[float | None, float | None, int, list[str]]:
    """M1 偏相关:numpy 残差法。

    步骤:
      1) 收集 target / x / controls 的有效样本(dropna)
      2) 剔除 controls 中的常数列(std=0)→ warnings_local
      3) y 与 x 对 controls 做 OLS 残差 → corr(e_y, e_x)
      4) 若 controls 为空 → 退化为 Pearson(single_r)

    返回 (partial_r, p_value, n_used, warnings_local)。
    """
    local_warnings: list[str] = []
    cols = [target, x] + [c for c in controls if c not in (target, x)]
    sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    n_used = int(len(sub))
    if n_used < 5:
        return None, None, n_used, ["样本不足"]

    y = sub[target].to_numpy(dtype=float)
    xv = sub[x].to_numpy(dtype=float)

    # 过滤常数列
    ctrl_use: list[str] = []
    for c in controls:
        if c in (target, x):
            continue
        if c not in sub.columns:
            continue
        cstd = float(sub[c].std(ddof=1)) if n_used > 1 else 0.0
        if cstd <= 1e-12:
            local_warnings.append(f"已剔除常数列 {c}")
            continue
        ctrl_use.append(c)

    if not ctrl_use:
        # 控制集为空:退化为单 Pearson
        local_warnings.append("控制集为空,偏相关退化为单 Pearson")
        r_val = _pearson(xv, y)
        # p_value 用 scipy/pearsonr 的第二返回值
        p_val: float | None = None
        if _HAS_SCIPY:
            try:
                _, p_val = _scipy_pearsonr(xv, y)
                if not np.isfinite(p_val):
                    p_val = None
            except Exception:
                p_val = None
        return float(r_val), p_val, n_used, local_warnings

    Z = sub[ctrl_use].to_numpy(dtype=float)
    e_y = _ols_residual(y, Z)
    e_x = _ols_residual(xv, Z)
    r_partial = _pearson(e_x, e_y)
    # p 值:t 检验,df = n - k - 2(k = 控制集大小)
    df_t = n_used - len(ctrl_use) - 2
    p_val = None
    if df_t > 0 and abs(r_partial) < 1.0:
        try:
            t_stat = r_partial * np.sqrt(df_t / max(1e-12, 1.0 - r_partial * r_partial))
            # Student-t 双尾 p(不引入新依赖:numpy 不带 t 分布 CDF;用 scipy 可选)
            if _HAS_SCIPY:
                from scipy.stats import t as _student_t  # type: ignore
                tail = 1.0 - _student_t.cdf(abs(t_stat), df=df_t)
                if not np.isfinite(tail):
                    tail = 0.0
                p_val = float(2.0 * tail)
                if p_val <= 0.0:
                    # 下界截断为机器精度,避免下游 0.0 误判
                    p_val = float(np.finfo(float).tiny)
                if not np.isfinite(p_val):
                    p_val = None
        except Exception:
            p_val = None
    return float(r_partial), p_val, n_used, local_warnings


def _partial_corr_pg(
    df: pd.DataFrame,
    target: str,
    x: str,
    controls: list[str],
) -> tuple[float | None, float | None, int, list[str]]:
    """M1 pingouin 精化路径:缺失时返回 (None, None, 0, ['pingouin 不可用']) 让调用方回退 numpy。"""
    if not _HAS_PINGOOUIN:
        return None, None, 0, ["pingouin 不可用"]
    local_warnings: list[str] = []
    cols = [target, x] + [c for c in controls if c not in (target, x)]
    sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    n_used = int(len(sub))
    if n_used < 5:
        return None, None, n_used, ["样本不足"]
    ctrl_use = [c for c in controls if c not in (target, x) and c in sub.columns]
    try:
        if not ctrl_use:
            local_warnings.append("控制集为空,偏相关退化为单 Pearson")
            res = _pg.corr(sub[x], sub[target])
            r_val = float(res["r"].iloc[0])
            p_val = float(res["p-val"].iloc[0])
        else:
            res = _pg.partial_corr(sub, x=x, y=target, covar=ctrl_use, method="pearson")
            r_val = float(res["r"].iloc[0])
            p_val = float(res["p-val"].iloc[0])
    except Exception as e:
        local_warnings.append(f"pingouin 偏相关失败: {e}")
        return None, None, n_used, local_warnings
    if not np.isfinite(r_val):
        r_val = 0.0
    if not np.isfinite(p_val):
        p_val = None
    return float(r_val), float(p_val) if p_val is not None else None, n_used, local_warnings


def _compute_vif(X_std: np.ndarray, feature_names: list[str]) -> list[dict[str, Any]]:
    """VIF_j = 1 / (1 - R2_j),R2_j 由 x_j 对其余列做 OLS 得到。"""
    n, p = X_std.shape
    vifs: list[dict[str, Any]] = []
    if p < 2:
        for j in range(p):
            vifs.append({"feature": feature_names[j], "vif": 1.0})
        return vifs
    for j in range(p):
        y_j = X_std[:, j]
        mask = [k for k in range(p) if k != j]
        X_others = X_std[:, mask]
        try:
            beta, *_ = np.linalg.lstsq(X_others, y_j, rcond=None)
            yhat = X_others @ beta
            ss_res = float(((y_j - yhat) ** 2).sum())
            ss_tot = float(((y_j - y_j.mean()) ** 2).sum())
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
            r2 = min(max(r2, 0.0), 0.999999)
            vif = 1.0 / (1.0 - r2)
            if not np.isfinite(vif) or vif > 1e6:
                vif = float(vif) if np.isfinite(vif) else 1e6
        except Exception:
            vif = 1.0
        vifs.append({"feature": feature_names[j], "vif": float(vif)})
    return vifs


def _ols_standardized(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
) -> dict[str, Any]:
    """M2:标准化 OLS。

    输入是已经 dropna 后的等长 float 数组(n, p)和(n,)。
    返回:coef_std[], r2, r2_adj, n, k, vif[], condition_number, warnings
    """
    n = int(X.shape[0])
    p = int(X.shape[1])
    out_warnings: list[str] = []
    if y.std(ddof=1) <= 1e-12:
        out_warnings.append("目标列方差为 0")
        return {
            "r2": 0.0,
            "r2_adj": 0.0,
            "n": n,
            "k": 0,
            "coef_std": [],
            "vif": [],
            "condition_number": None,
            "warnings": out_warnings,
            "dropped": [],
        }
    # 剔除常数列
    keep_mask: list[int] = []
    keep_names: list[str] = []
    dropped_const: list[dict[str, str]] = []
    for j in range(p):
        col = X[:, j]
        if col.std(ddof=1) <= 1e-12:
            dropped_const.append({"feature": feature_names[j], "reason": "常数列"})
            out_warnings.append(f"已剔除常数列 {feature_names[j]}")
        else:
            keep_mask.append(j)
            keep_names.append(feature_names[j])
    if not keep_mask:
        out_warnings.append("全部特征为常数列,跳过 OLS")
        return {
            "r2": 0.0,
            "r2_adj": 0.0,
            "n": n,
            "k": 0,
            "coef_std": [],
            "vif": [],
            "condition_number": None,
            "warnings": out_warnings,
            "dropped": dropped_const,
        }
    X_keep = X[:, keep_mask]
    k = int(X_keep.shape[1])
    if p > n - 2:
        out_warnings.append("特征数 p > n-2,跳过 OLS")
        return {
            "r2": 0.0,
            "r2_adj": 0.0,
            "n": n,
            "k": k,
            "coef_std": [],
            "vif": [],
            "condition_number": None,
            "warnings": out_warnings,
            "dropped": dropped_const,
        }

    # z-score
    Xs = _zscore_array(X_keep)
    ys = (y - y.mean()) / max(y.std(ddof=1), 1e-12)

    # 条件数
    try:
        cond = float(np.linalg.cond(Xs))
        if not np.isfinite(cond):
            cond = float("inf")
    except Exception:
        cond = float("inf")

    used_ridge = False
    try:
        beta, *_ = np.linalg.lstsq(Xs, ys, rcond=None)
        yhat = Xs @ beta
        rank = int(np.linalg.matrix_rank(Xs))
        if rank < k:
            used_ridge = True
            out_warnings.append("X'X 奇异,启用岭化 λ=1e-4")
            lam = 1e-4
            XtX = Xs.T @ Xs + lam * np.eye(k)
            Xty = Xs.T @ ys
            beta = np.linalg.solve(XtX, Xty)
            yhat = Xs @ beta
    except Exception:
        beta = np.zeros(k)
        yhat = np.zeros(n)
        used_ridge = True
        out_warnings.append("OLS 求解失败,启用零系数兜底")

    resid = ys - yhat
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((ys - ys.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    if r2 < 0.0:
        r2 = 0.0
    # 调整 R2:df_resid = n - k(标准化 + 零截距)
    if n - k > 0:
        r2_adj = 1.0 - (1.0 - r2) * (n - 1) / (n - k)
    else:
        r2_adj = r2

    vif_list = _compute_vif(Xs, keep_names)

    coef_std: list[dict[str, Any]] = []
    for idx, name in enumerate(keep_names):
        b = float(beta[idx]) if np.isfinite(beta[idx]) else 0.0
        vif_val = next((v["vif"] for v in vif_list if v["feature"] == name), 1.0)
        coef_std.append({
            "feature": name,
            "beta_std": b,
            "abs_beta_std": float(abs(b)),
            "vif": float(vif_val),
            "kept": True,
        })
    return {
        "r2": float(r2),
        "r2_adj": float(r2_adj),
        "n": n,
        "k": k,
        "coef_std": coef_std,
        "vif": vif_list,
        "condition_number": cond,
        "warnings": out_warnings,
        "dropped": dropped_const,
        "used_ridge": used_ridge,
    }


def _format_multi_result(
    partial_rows: list[dict[str, Any]],
    ols_result: dict[str, Any] | None,
    ols_skipped_reason: str | None,
    vif_warn_threshold: float,
    warnings_list: list[str],
) -> dict[str, Any]:
    """把 M1/M2 内部结果序列化成 report['multi'] 节点。"""
    partial_corr_sorted = sorted(
        partial_rows,
        key=lambda d: d.get("abs_partial_r") or 0.0,
        reverse=True,
    )
    top_contributors: list[str] = []
    if ols_result and ols_result.get("coef_std"):
        sorted_coef = sorted(
            ols_result["coef_std"],
            key=lambda d: d.get("abs_beta_std") or 0.0,
            reverse=True,
        )
        top_contributors = [c["feature"] for c in sorted_coef[:5]]

    out: dict[str, Any] = {
        "partial_corr": partial_corr_sorted,
        "ols": ols_result if ols_result else None,
        "top_contributors": top_contributors,
        "ols_skipped_reason": ols_skipped_reason,
        "vif_warn_threshold": float(vif_warn_threshold),
        "warnings": list(warnings_list),
    }
    return out


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
    # ===== S5 多变量归因新增参数(向后兼容，默认关闭；UI 默认 multi=True) =====
    multi: bool = False,
    multi_top_n: int = 10,
    multi_min_samples: int = 30,
    multi_exclude_vif_gt: float = 10.0,
    multi_compute_partial: bool = True,
    multi_compute_ols: bool = True,
    use_pingouin: bool = True,
) -> dict[str, Any]:
    _hb("ENTER build_head_tail_report target=%s multi=%s" % (str(target_col), bool(multi)), 0)
    _call_progress(report_progress, 5, "准备数据...")

    if df is None or len(df) == 0:
        raise ValueError("数据集为空,无法进行机尾指数-s 归因分析。")
    if target_col not in df.columns:
        raise KeyError(f"目标列 {target_col} 不在数据集中,请确认已进行跨类合并。")

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
        warnings_list.append(f"未检测到 {head_prefix} 前缀的机头列,请确认已执行跨类合并。")
    if not has_tail:
        warnings_list.append(f"未检测到 {tail_prefix} 前缀的机尾列,请确认已执行跨类合并。")

    if feature_cols is None:
        feat_list: list[str] = []
        for c in df.columns:
            cname = str(c)
            if cname == target_col:
                continue
            if _looks_like_time(cname):
                continue
            # C037-B Owner #3: 归因模式纳入全部数值列(不再只限 [机头]* 前缀)
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
        raise ValueError("未检测到足够数值特征列(≥2 列)。请确认已执行跨类合并且数据集包含数值型参数。")

    _call_progress(report_progress, 10, "对齐目标列与特征...")

    target_raw = df[target_col]
    target_num = pd.to_numeric(target_raw, errors="coerce")
    near_ideal_mask = (target_num - float(ideal_value)).abs() <= float(ideal_tol)
    ideal_exact_mask = (target_num.round() == float(ideal_value))

    n_total = int(len(df))
    target_valid = target_num.dropna()
    n_target_valid = int(target_valid.shape[0])
    if n_target_valid == 0:
        raise ValueError(f"目标列 {target_col} 全为非数值/空值,无法分析。")

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
        _check_cancel("归因分析已被用户取消(相关系数阶段)")
        fv = pd.to_numeric(df[feat], errors="coerce")
        sub = pd.DataFrame({"y": target_num, "x": fv}).dropna()
        n = int(len(sub))
        if n < min_samples:
            warnings_list.append(f"特征 {feat} 有效配对样本 {n} < {min_samples},结论仅供参考。")
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
            _call_progress(report_progress, pct, f"相关系数:{idx+1}/{n_feats}")

    pairwise.sort(key=lambda d: d["abs_spearman"], reverse=True)
    top_feats = pairwise[: max(1, int(top_n))]

    _call_progress(report_progress, 55, "分组统计与分箱...")

    attribution: list[dict[str, Any]] = []
    for i, item in enumerate(top_feats):
        _check_cancel("归因分析已被用户取消(分组统计阶段)")
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
                warnings_list.append(f"特征 {feat} 样本数 {n} 不足,跳过五分位分箱。")

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
        _call_progress(report_progress, pct, f"分组统计:{i+1}/{len(top_feats)}")

    _call_progress(report_progress, 78, "规则挖掘...")

    rules: list[dict[str, Any]] = []
    rule_feats = attribution[: max(1, int(top_rules_n))]
    for ritem in rule_feats:
        _check_cancel("归因分析已被用户取消(规则挖掘阶段)")
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

    _call_progress(report_progress, 75, "W12 单变量阶段完成")

    feat_num = [pd.to_numeric(df[c], errors="coerce") for c in feat_list]
    any_feat = pd.concat(feat_num, axis=1).notna().any(axis=1) if feat_num else pd.Series(False, index=df.index)
    n_eff = int(((target_num.notna()) & any_feat).sum())

    # ============================================================================
    # S5 多变量归因(M1 偏相关 + M2 OLS 标准化系数 + VIF)
    # 旧 W12 调用(multi=False)下整个分支完全跳过,输出 dict 不含 'multi' 键
    # ============================================================================
    multi_node: dict[str, Any] | None = None
    if multi:
        _call_progress(report_progress, 78, "偏相关计算中...")
        multi_warnings: list[str] = []
        partial_rows: list[dict[str, Any]] = []
        ols_result: dict[str, Any] | None = None
        ols_skipped_reason: str | None = None

        # 取 M2 用列:默认按 |Spearman| TopN,N>multi_top_n 时截断
        m2_feats: list[str] = []
        if multi_compute_ols:
            for it in pairwise[: max(1, int(multi_top_n))]:
                m2_feats.append(it["feature"])
        # M1 列:默认用全部 feat_list(与单变量分析保持一致覆盖面)
        m1_feats = list(feat_list)

        n_multi_total = len(m1_feats) + len(m2_feats)
        multi_idx = 0

        # ---- M1 partial correlation ----
        if multi_compute_partial and len(m1_feats) >= 1:
            single_lookup: dict[str, float] = {it["feature"]: float(it["pearson_r"]) for it in pairwise}
            _hb("M1 start n_feats=%d" % len(m1_feats), 78)
            for i, feat in enumerate(m1_feats):
                _check_cancel("归因分析已被用户取消(偏相关阶段)")
                controls = [c for c in m1_feats if c != feat]
                if len(controls) == 0:
                    # 仅 1 列时 control 集为空 -> 让 _partial_corr 内部退回为单 Pearson
                    _hb("M1 call _partial_corr feat=%s i=%d/%d" % (feat, i + 1, len(m1_feats)), 78)
                    r_part, p_val, n_used, local_w = _partial_corr(df, target_col, feat, controls)
                else:
                    if use_pingouin and _HAS_PINGOOUIN:
                        _hb("M1 call _partial_corr_pg feat=%s i=%d/%d" % (feat, i + 1, len(m1_feats)), 78)
                        r_part, p_val, n_used, local_w = _partial_corr_pg(df, target_col, feat, controls)
                        if r_part is None and any("pingouin" in s for s in local_w):
                            # pingouin 不可用或失败 → 回退 numpy
                            _hb("M1 fallback _partial_corr feat=%s" % feat, 78)
                            r_part, p_val, n_used, local_w = _partial_corr(df, target_col, feat, controls)
                    else:
                        _hb("M1 call _partial_corr feat=%s i=%d/%d" % (feat, i + 1, len(m1_feats)), 78)
                        r_part, p_val, n_used, local_w = _partial_corr(df, target_col, feat, controls)
                single_r = single_lookup.get(feat)
                abs_part = float(abs(r_part)) if r_part is not None and np.isfinite(r_part) else 0.0
                partial_rows.append({
                    "feature": feat,
                    "n": n_used,
                    "single_r": float(single_r) if single_r is not None and np.isfinite(single_r) else 0.0,
                    "partial_r": float(r_part) if r_part is not None and np.isfinite(r_part) else 0.0,
                    "abs_partial_r": abs_part,
                    "p_value": float(p_val) if p_val is not None and np.isfinite(p_val) else None,
                    "controls_used": len(controls),
                    "warnings": list(local_w),
                })
                if n_used < int(multi_min_samples):
                    multi_warnings.append(f"{feat} N={n_used}<{multi_min_samples},M1 仅供参考")
                for lw in local_w:
                    if "已剔除常数列" in lw or "控制集为空" in lw:
                        multi_warnings.append(f"M1[{feat}] {lw}")
                multi_idx += 1
                if n_multi_total > 0:
                    pct = 78 + int(12 * (i + 1) / max(1, len(m1_feats)))  # C034 单调 78→90
                    _call_progress(report_progress, pct, f"偏相关计算中 {i+1}/{len(m1_feats)}")
        elif multi_compute_partial and len(m1_feats) == 1:
            multi_warnings.append("仅勾选 1 列,M1 退化为单 Pearson")

        # ---- M2 OLS standardized ----
        _check_cancel("归因分析已被用户取消(OLS 拟合阶段)")
        if multi_compute_ols and len(m2_feats) >= 2:
            _call_progress(report_progress, 92, "OLS 拟合中")
            cols_m2 = [target_col] + m2_feats
            sub = df[cols_m2].apply(pd.to_numeric, errors="coerce").dropna()
            n_used_m2 = int(len(sub))
            if n_used_m2 < int(multi_min_samples):
                ols_skipped_reason = f"N={n_used_m2}<{multi_min_samples},跳过 OLS"
                multi_warnings.append(ols_skipped_reason)
            else:
                X = sub[m2_feats].to_numpy(dtype=float)
                y = sub[target_col].to_numpy(dtype=float)
                _hb("M2 call _ols_standardized n=%d k=%d" % (n_used_m2, len(m2_feats)), 92)
                ols_result = _ols_standardized(X, y, m2_feats)
                _hb("M2 _ols_standardized done r2=%.4f" % (float(ols_result.get("r2") or 0.0) if ols_result else 0.0), 92)
                # VIF 警告文本(仅警告,不剔除)
                if ols_result and ols_result.get("coef_std"):
                    for c in ols_result["coef_std"]:
                        if c.get("vif", 1.0) > float(multi_exclude_vif_gt):
                            c["vif_warn"] = True
                            _feat = c["feature"]
                            _prefix = "[机头]"
                            _shown = _feat[len(_prefix):] if _feat.startswith(_prefix) else _feat
                            msg = f"[机头]{_shown} 与其它列 VIF={c['vif']:.2f},建议剔除"
                            multi_warnings.append(msg)
                            c["vif_warning_text"] = msg
                _call_progress(report_progress, 97, "OLS 完成")
        elif multi_compute_ols and len(m2_feats) == 1:
            ols_skipped_reason = "仅勾选 1 列,跳过 OLS(p<k)"
            multi_warnings.append(ols_skipped_reason)
        else:
            ols_skipped_reason = "OLS 未启用"
            multi_warnings.append(ols_skipped_reason)

        # 累计到外层 warnings_list(限 50 条避免刷屏)
        for mw in multi_warnings:
            warnings_list.append(mw)
            if len([w for w in warnings_list if w == mw]) <= 1:
                pass  # 保留全部用于诊断

        multi_node = _format_multi_result(
            partial_rows=partial_rows,
            ols_result=ols_result,
            ols_skipped_reason=ols_skipped_reason,
            vif_warn_threshold=multi_exclude_vif_gt,
            warnings_list=multi_warnings,
        )

    _call_progress(report_progress, 100, "完成")

    result: dict[str, Any] = {
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
            "has_pingouin": bool(_HAS_PINGOOUIN),
            "warnings": warnings_list,
        },
        "target_dist": target_dist,
        "attribution": attribution,
        "top_rules": top_rules,
        "overall_suggested_window": overall_window,
    }
    if multi_node is not None:
        result["multi"] = multi_node
    _hb("EXIT build_head_tail_report multi=%s" % (result.get("multi") is not None), 100)
    return result
