"""W8a 本地工艺窗口分析引擎。

纯函数 / 纯类，不依赖 Qt，可单测。
输入是一张已对齐的宽表 DataFrame，输出是可直接被 UI 消费的 dict 报告。
"""
from __future__ import annotations

import warnings
from typing import Any, Iterable

import numpy as np
import pandas as pd


# ---------- 工具 ----------

def _is_datetime_like(series: pd.Series) -> bool:
    """判断列是否像时间列：datetime dtype 或 object/string 列中大部分值可解析为 datetime。"""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
        return False
    non_null = series.dropna()
    if non_null.empty:
        return False
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return False
    sample_n = min(200, len(non_null))
    sample = non_null.head(sample_n)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        converted = pd.to_datetime(sample, errors="coerce")
    ratio = converted.notna().sum() / max(1, len(sample))
    name = str(series.name).lower()
    name_hint = any(k in name for k in ["date", "time", "日期", "时间"])
    return bool(ratio >= 0.8 or (name_hint and ratio >= 0.6))


def _is_numeric_feature(series: pd.Series) -> bool:
    if pd.api.types.is_bool_dtype(series):
        return False
    if pd.api.types.is_datetime64_any_dtype(series):
        return False
    if pd.api.types.is_numeric_dtype(series):
        return True
    # object/string 列若 80% 可转数字，也视为数值列（兼容"1.23"字符串）
    non_null = series.dropna()
    if non_null.empty:
        return False
    converted = pd.to_numeric(non_null, errors="coerce")
    ratio = converted.notna().sum() / max(1, len(non_null))
    return bool(ratio >= 0.8)


def _state_keyword_score(name: str) -> int:
    """关键词匹配得分：越大越像状态列。"""
    low = name.lower()
    score = 0
    for kw in ["指数", "index", "state", "状态", "label", "target", "等级"]:
        if kw in low:
            score += 10
    return score


# ---------- 1. 列自动识别 ----------

def infer_columns(
    df: pd.DataFrame,
    state_keywords: Iterable[str] = ("指数", "state", "状态", "label", "index"),
    exclude_keywords: Iterable[str] = ("未脱模",),
    max_state_nunique: int = 12,
) -> dict[str, Any]:
    """自动识别时间列 / 状态列候选 / 特征列。

    返回：
        {
            "time_col": str | None,
            "state_col_candidates": [str, ...],  # 按关键词优先排序
            "feature_cols": [str, ...],          # 数值列，排除时间/状态/排除关键词
        }
    """
    time_col: str | None = None
    for col in df.columns:
        if _is_datetime_like(df[col]):
            time_col = str(col)
            break

    state_candidates: list[tuple[int, int, str]] = []  # (score, -nunique, col)
    for col in df.columns:
        s = df[col]
        if str(col) == time_col:
            continue
        if pd.api.types.is_datetime64_any_dtype(s):
            continue
        # 要求 nunique 少 + 可作类别/整数
        try:
            nu = int(s.nunique(dropna=True))
        except Exception:
            continue
        if nu == 0 or nu > max_state_nunique:
            continue
        if pd.api.types.is_bool_dtype(s):
            continue
        is_int_like = False
        if pd.api.types.is_integer_dtype(s):
            is_int_like = True
        elif pd.api.types.is_categorical_dtype(s):
            is_int_like = True
        else:
            # 尝试转数字后若全部为整数也接受
            num = pd.to_numeric(s, errors="coerce")
            if num.notna().sum() >= max(1, int(len(s) * 0.8)):
                diff = (num.dropna() - np.floor(num.dropna()))
                is_int_like = bool((diff.abs() < 1e-9).all())
        if not is_int_like:
            continue
        score = _state_keyword_score(str(col))
        state_candidates.append((score, -nu, str(col)))
    state_candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    state_sorted = [c for _, _, c in state_candidates]
    state_col = state_sorted[0] if state_sorted else None

    feature_cols: list[str] = []
    exclude_kw = tuple(exclude_keywords)
    for col in df.columns:
        cname = str(col)
        if cname == time_col:
            continue
        if state_col is not None and cname == state_col:
            continue
        if any(kw in cname for kw in exclude_kw):
            continue
        if _is_numeric_feature(df[col]):
            feature_cols.append(cname)

    return {
        "time_col": time_col,
        "state_col": state_col,
        "state_col_candidates": state_sorted,
        "feature_cols": feature_cols,
    }


# ---------- 2. 按时间就近对齐 ----------

def align_by_time(
    df_left: pd.DataFrame,
    df_right: pd.DataFrame,
    time_col_left: str,
    time_col_right: str,
    tolerance_sec: float = 1.0,
    suffixes: tuple[str, str] = ("", "_y"),
) -> pd.DataFrame:
    """把右表按时间就近匹配到左表（pd.merge_asof, nearest）。

    - 两表各自把时间列转 datetime、按时间排序
    - tolerance = ±tolerance_sec 秒
    - 右表同名列加 ``_y`` 后缀，避免冲突
    """
    if time_col_left not in df_left.columns:
        raise KeyError(f"左表缺少时间列：{time_col_left}")
    if time_col_right not in df_right.columns:
        raise KeyError(f"右表缺少时间列：{time_col_right}")

    left = df_left.copy()
    right = df_right.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        left[time_col_left] = pd.to_datetime(left[time_col_left], errors="coerce")
        right[time_col_right] = pd.to_datetime(right[time_col_right], errors="coerce")
    left = left.dropna(subset=[time_col_left]).sort_values(time_col_left).reset_index(drop=True)
    right = right.dropna(subset=[time_col_right]).sort_values(time_col_right).reset_index(drop=True)

    merged = pd.merge_asof(
        left,
        right,
        left_on=time_col_left,
        right_on=time_col_right,
        direction="nearest",
        tolerance=pd.Timedelta(seconds=float(tolerance_sec)),
        suffixes=suffixes,
    )
    return merged


# ---------- 3. 单变量工艺窗口 ----------

def compute_univariate_windows(
    df: pd.DataFrame,
    feature_cols: Iterable[str],
    state_col: str,
    target_states: Iterable[Any] | None = None,
    min_samples: int = 30,
) -> dict[Any, dict[str, dict[str, Any]]]:
    """对每个 state × feature 计算统计量 + μ±σ / μ±2σ 窗口。"""
    feature_cols = [str(c) for c in feature_cols if c in df.columns]
    if state_col not in df.columns:
        raise KeyError(f"状态列不存在：{state_col}")

    if target_states is None:
        states = [v for v in df[state_col].dropna().unique().tolist()]
    else:
        states = list(target_states)

    out: dict[Any, dict[str, dict[str, Any]]] = {}
    for state in states:
        sub = df[df[state_col] == state]
        n_total = int(len(sub))
        per_feat: dict[str, dict[str, Any]] = {}
        unreliable = n_total < min_samples
        for feat in feature_cols:
            series = pd.to_numeric(sub[feat], errors="coerce").dropna()
            n = int(len(series))
            if n == 0:
                per_feat[feat] = {
                    "count": 0, "mean": None, "std": None,
                    "min": None, "p1": None, "p5": None, "p25": None, "p50": None,
                    "p75": None, "p95": None, "p99": None, "max": None,
                    "window_1sigma": (None, None),
                    "window_2sigma": (None, None),
                }
                continue
            mean = float(series.mean())
            std = float(series.std(ddof=1)) if n > 1 else 0.0
            if not np.isfinite(std):
                std = 0.0
            qs = series.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
            per_feat[feat] = {
                "count": n,
                "mean": mean,
                "std": std,
                "min": float(series.min()),
                "p1": float(qs.loc[0.01]),
                "p5": float(qs.loc[0.05]),
                "p25": float(qs.loc[0.25]),
                "p50": float(qs.loc[0.5]),
                "p75": float(qs.loc[0.75]),
                "p95": float(qs.loc[0.95]),
                "p99": float(qs.loc[0.99]),
                "max": float(series.max()),
                "window_1sigma": (mean - std, mean + std),
                "window_2sigma": (mean - 2 * std, mean + 2 * std),
            }
        out[state] = {
            "count": n_total,
            "unreliable": bool(unreliable),
            "features": per_feat,
        }
    return out


# ---------- 4. 贪心分类树（规则挖掘） ----------

def _gini(p: float) -> float:
    if p <= 0 or p >= 1:
        return 0.0
    return float(1.0 - p * p - (1 - p) * (1 - p))


def _best_split(
    X: np.ndarray, y: np.ndarray, feature_idx: list[int], min_samples_leaf: int
) -> tuple[int, float, float] | None:
    """返回 (feat_idx, threshold, gain)，无增益返回 None。"""
    n = len(y)
    if n == 0:
        return None
    pos_total = int(y.sum())
    g_parent = _gini(pos_total / n)
    best: tuple[int, float, float] | None = None
    for fi in feature_idx:
        col = X[:, fi]
        # 9 个分位切分点
        qs = np.nanquantile(col, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        thresholds = np.unique([float(v) for v in qs if np.isfinite(v)])
        for thr in thresholds:
            left_mask = col <= thr
            right_mask = ~left_mask
            n_l = int(left_mask.sum())
            n_r = int(right_mask.sum())
            if n_l < min_samples_leaf or n_r < min_samples_leaf:
                continue
            p_l = int(y[left_mask].sum()) / max(1, n_l)
            p_r = int(y[right_mask].sum()) / max(1, n_r)
            g_l = _gini(p_l)
            g_r = _gini(p_r)
            gain = g_parent - (n_l / n) * g_l - (n_r / n) * g_r
            if gain <= 1e-12:
                continue
            if best is None or gain > best[2] + 1e-12:
                best = (fi, float(thr), float(gain))
    return best


def fit_greedy_tree(
    df: pd.DataFrame,
    feature_cols: Iterable[str],
    state_col: str,
    target_state: Any,
    max_depth: int = 3,
    min_samples_leaf: int = 30,
    max_rules: int = 8,
) -> list[dict[str, Any]]:
    """对二分类（target_state vs 其他）递归贪心分裂，返回叶节点规则列表。"""
    feature_cols = [str(c) for c in feature_cols if c in df.columns]
    if state_col not in df.columns or not feature_cols:
        return []
    sub = df[feature_cols + [state_col]].copy()
    for c in feature_cols:
        sub[c] = pd.to_numeric(sub[c], errors="coerce")
    sub = sub.dropna(subset=feature_cols + [state_col])
    if sub.empty:
        return []

    X = sub[feature_cols].to_numpy(dtype=float)
    y = (sub[state_col].to_numpy() == target_state).astype(np.int8)
    n_total_pos = int(y.sum())
    if n_total_pos == 0:
        return []

    rules: list[dict[str, Any]] = []

    def recurse(
        idx: np.ndarray, depth: int, conditions: list[dict[str, Any]]
    ) -> None:
        n = len(idx)
        if n == 0:
            return
        pos = int(y[idx].sum())
        p = pos / n
        # 停止条件
        if (
            depth >= max_depth
            or n < min_samples_leaf * 2
            or p >= 0.95
            or p <= 0.05
        ):
            rules.append({
                "conditions": [dict(c) for c in conditions],
                "support": int(n),
                "precision": float(p),
                "recall": float(pos / n_total_pos),
                "state": target_state,
            })
            return
        split = _best_split(X[idx], y[idx], list(range(len(feature_cols))), min_samples_leaf)
        if split is None:
            rules.append({
                "conditions": [dict(c) for c in conditions],
                "support": int(n),
                "precision": float(p),
                "recall": float(pos / n_total_pos),
                "state": target_state,
            })
            return
        fi, thr, _gain = split
        col = X[idx, fi]
        left_mask_local = col <= thr
        right_mask_local = ~left_mask_local
        left_idx = idx[left_mask_local]
        right_idx = idx[right_mask_local]
        left_cond = conditions + [{"feature": feature_cols[fi], "op": "<=", "threshold": thr}]
        right_cond = conditions + [{"feature": feature_cols[fi], "op": ">", "threshold": thr}]
        recurse(left_idx, depth + 1, left_cond)
        recurse(right_idx, depth + 1, right_cond)

    recurse(np.arange(len(y)), 0, [])

    # 排序：F0.5 = (1.25 * P * R) / (0.25 * P + R)，precision 权重高
    def score(rule: dict[str, Any]) -> float:
        p, rec = rule["precision"], rule["recall"]
        sup = rule["support"]
        if p + rec <= 0:
            return 0.0
        f05 = (1.25 * p * rec) / (0.25 * p + rec)
        return float(f05 * (sup ** 0.3))

    rules.sort(key=score, reverse=True)
    return rules[:max_rules]


# ---------- 5. 特征重要性（简化 ANOVA F） ----------

def compute_feature_importance(
    df: pd.DataFrame,
    feature_cols: Iterable[str],
    state_col: str,
    min_group_samples: int = 2,
) -> list[tuple[str, float]]:
    """one-way ANOVA F 值简化实现：F = (SSB/(k-1)) / (SSW/(n-k))。

    忽略 NaN；样本数不足的组会被跳过；若某特征无法计算（常数列/组数<2等）返回 F=0。
    """
    feature_cols = [str(c) for c in feature_cols if c in df.columns]
    if state_col not in df.columns or not feature_cols:
        return []
    groups_raw = df[state_col]
    out: list[tuple[str, float]] = []
    for feat in feature_cols:
        s = pd.to_numeric(df[feat], errors="coerce")
        data = pd.DataFrame({"g": groups_raw, "v": s}).dropna()
        if data.empty:
            out.append((feat, 0.0))
            continue
        group_list = [g["v"].to_numpy(dtype=float) for _, g in data.groupby("g") if len(g) >= min_group_samples]
        if len(group_list) < 2:
            out.append((feat, 0.0))
            continue
        all_v = np.concatenate(group_list)
        n = int(all_v.size)
        if n <= len(group_list):
            out.append((feat, 0.0))
            continue
        grand_mean = float(all_v.mean())
        ssb = 0.0
        ssw = 0.0
        for g in group_list:
            ng = int(g.size)
            gm = float(g.mean())
            ssb += ng * (gm - grand_mean) ** 2
            ssw += float(((g - gm) ** 2).sum())
        k = len(group_list)
        dfb = k - 1
        dfw = n - k
        if dfw <= 0 or ssw <= 1e-12:
            f_val = float("inf") if ssb > 1e-12 else 0.0
        else:
            f_val = float((ssb / dfb) / (ssw / dfw))
        if not np.isfinite(f_val):
            f_val = 1e18
        out.append((feat, float(f_val)))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


# ---------- 6. 报告总入口 ----------

def build_analysis_report(
    df: pd.DataFrame,
    time_col: str | None = None,
    state_col: str | None = None,
    feature_cols: Iterable[str] | None = None,
    target_states: Iterable[Any] | None = None,
    min_samples: int = 30,
    max_tree_depth: int = 3,
    min_samples_leaf: int = 30,
) -> dict[str, Any]:
    """分析总入口。任何识别失败时返回带 ``error`` 字段的 dict 而不是抛异常。"""
    warnings_list: list[str] = []
    try:
        if df is None or len(df) == 0:
            return {"error": "数据集为空，无法分析。", "meta": {"warnings": ["数据集为空。"]}}

        # 自动识别列（若未指定）
        inferred = infer_columns(df)
        if time_col is None:
            time_col = inferred.get("time_col")
        if state_col is None:
            state_col = inferred.get("state_col")
        if feature_cols is None:
            feature_cols = list(inferred.get("feature_cols", []))
        else:
            feature_cols = [str(c) for c in feature_cols if c in df.columns]

        if state_col is None:
            return {
                "error": "未能自动识别状态列（如 指数-s），请手动选择。",
                "meta": {"warnings": warnings_list + ["未能识别状态列。"]},
            }
        if not feature_cols:
            return {
                "error": "未找到可分析的数值特征列。",
                "meta": {"warnings": warnings_list + ["未找到数值特征列。"]},
            }

        # 解析目标状态
        state_series = df[state_col]
        state_values_present: list[Any] = []
        for v in state_series.dropna().unique().tolist():
            try:
                state_values_present.append(v.item() if hasattr(v, "item") else v)
            except Exception:
                state_values_present.append(v)
        if target_states is None:
            # 默认全选非 0 值
            target_states_list = [v for v in state_values_present if not _is_zero(v)]
            if not target_states_list:
                target_states_list = list(state_values_present)
        else:
            target_states_list = [v for v in target_states if v in state_values_present or _in_state_series(state_series, v)]
        target_states_list = _unique_preserve(target_states_list)

        n_total = int(len(df))
        summary: dict[Any, dict[str, Any]] = {}
        for sv in state_values_present:
            cnt = int((state_series == sv).sum())
            summary[sv] = {
                "count": cnt,
                "pct": float(cnt / n_total) if n_total else 0.0,
                "unreliable": bool(cnt < min_samples),
            }
            if cnt < min_samples:
                warnings_list.append(
                    f"状态 {sv} 仅 {cnt} 条样本（<{min_samples}），结论不可靠。"
                )

        # univariate
        univariate = compute_univariate_windows(
            df, feature_cols, state_col,
            target_states=target_states_list, min_samples=min_samples,
        )

        # rules：每个目标状态分别拟合
        rules: dict[Any, list[dict[str, Any]]] = {}
        for sv in target_states_list:
            cnt = summary.get(sv, {}).get("count", 0)
            if cnt < min_samples_leaf:
                rules[sv] = []
                warnings_list.append(f"状态 {sv} 样本数 {cnt} 不足 min_samples_leaf={min_samples_leaf}，未生成规则。")
                continue
            rules[sv] = fit_greedy_tree(
                df, feature_cols, state_col, target_state=sv,
                max_depth=max_tree_depth, min_samples_leaf=min_samples_leaf,
            )

        # feature importance
        importance = compute_feature_importance(df, feature_cols, state_col)

        # 把所有 state key 转成字符串，便于 JSON 序列化（UI 里再转也可）
        summary_s = {_key_to_str(k): v for k, v in summary.items()}
        univariate_s = {_key_to_str(k): v for k, v in univariate.items()}
        rules_s = {_key_to_str(k): v for k, v in rules.items()}

        return {
            "summary": summary_s,
            "univariate": univariate_s,
            "rules": rules_s,
            "feature_importance": importance,
            "meta": {
                "n_rows": n_total,
                "n_cols": int(df.shape[1]),
                "time_col": time_col,
                "state_col": state_col,
                "feature_cols": list(feature_cols),
                "target_states": [_key_to_str(v) for v in target_states_list],
                "warnings": warnings_list,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"分析失败：{exc}",
            "meta": {"warnings": warnings_list + [f"异常：{exc}"]},
        }


# ---------- 辅助 ----------

def _is_zero(v: Any) -> bool:
    try:
        return float(v) == 0.0
    except Exception:
        return False


def _in_state_series(s: pd.Series, v: Any) -> bool:
    try:
        return bool((s == v).any())
    except Exception:
        return False


def _unique_preserve(seq: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for v in seq:
        key = v
        try:
            if isinstance(v, (np.generic,)):
                key = v.item()
        except Exception:
            pass
        if key in seen:
            continue
        seen.add(key)
        out.append(v if not isinstance(v, (np.generic,)) else key)
    return out


def _key_to_str(k: Any) -> str:
    try:
        return str(k.item() if hasattr(k, "item") else k)
    except Exception:
        return str(k)
