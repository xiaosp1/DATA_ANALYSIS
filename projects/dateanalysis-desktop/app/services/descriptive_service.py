from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from app.models.stats_result import StatsResult
from app.services.data_processor import infer_numeric_series
from app.utils.type_utils import safe_float


DEFAULT_QUANTILES = [0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0]


@dataclass
class DistributionData:
    column: str
    edges: np.ndarray
    counts: np.ndarray
    kde_x: np.ndarray | None
    kde_y: np.ndarray | None
    q1: float | None
    q3: float | None
    median: float | None
    mean: float | None
    iqr_lower: float | None
    iqr_upper: float | None
    outliers: np.ndarray
    n_total: int


def _safe_float(v) -> float | None:
    try:
        if v is None:
            return None
        fv = float(v)
        if np.isnan(fv) or np.isinf(fv):
            return None
        return fv
    except Exception:
        return None


def _valid_numeric(df: pd.DataFrame, column: str) -> tuple[pd.Series, int, int]:
    if column not in df.columns:
        raise KeyError(f"列不存在：{column}")
    numeric, invalid_count = infer_numeric_series(df[column])
    valid = numeric.dropna()
    total = int(df[column].shape[0])
    return valid, int(invalid_count), total


def _series_skew_kurt(s: pd.Series) -> tuple[float | None, float | None]:
    n = int(s.shape[0])
    if n < 3:
        return None, None
    try:
        skew = _safe_float(s.skew())
        kurt = _safe_float(s.kurt())
        return skew, kurt
    except Exception:
        return None, None


def calculate_descriptive_stats(df: pd.DataFrame, column_name: str) -> StatsResult:
    valid, invalid_count, total = _valid_numeric(df, column_name)
    count = int(valid.shape[0])
    missing_count = int(df[column_name].isna().sum() + invalid_count)
    if count == 0:
        return StatsResult(
            column_name=column_name, count=0, missing_count=missing_count,
            max=None, min=None, mean=None, median=None, sum=None,
            variance=None, std_dev=None, range=None,
            missing_rate=_safe_float(missing_count / total) if total > 0 else None,
            cv=None, skewness=None, kurtosis=None,
            q1=None, q3=None, iqr=None,
            p01=None, p05=None, p95=None, p99=None,
        )
    max_val = _safe_float(valid.max())
    min_val = _safe_float(valid.min())
    mean_val = _safe_float(valid.mean())
    median_val = _safe_float(valid.median())
    sum_val = _safe_float(valid.sum())
    var_val = _safe_float(valid.var(ddof=1)) if count > 1 else None
    std_val = _safe_float(valid.std(ddof=1)) if count > 1 else None
    range_val = _safe_float(max_val - min_val) if max_val is not None and min_val is not None else None
    cv_val = _safe_float(std_val / mean_val) if (std_val is not None and mean_val not in (None, 0.0)) else None
    skew_val, kurt_val = _series_skew_kurt(valid)
    q1 = _safe_float(valid.quantile(0.25))
    q3 = _safe_float(valid.quantile(0.75))
    iqr = _safe_float(q3 - q1) if q1 is not None and q3 is not None else None
    p01 = _safe_float(valid.quantile(0.01))
    p05 = _safe_float(valid.quantile(0.05))
    p95 = _safe_float(valid.quantile(0.95))
    p99 = _safe_float(valid.quantile(0.99))
    missing_rate = _safe_float(missing_count / total) if total > 0 else None
    return StatsResult(
        column_name=column_name, count=count, missing_count=missing_count,
        max=max_val, min=min_val, mean=mean_val, median=median_val, sum=sum_val,
        variance=var_val, std_dev=std_val, range=range_val,
        missing_rate=missing_rate, cv=cv_val, skewness=skew_val, kurtosis=kurt_val,
        q1=q1, q3=q3, iqr=iqr, p01=p01, p05=p05, p95=p95, p99=p99,
    )


def batch_descriptive_stats(df: pd.DataFrame, columns: Iterable[str]) -> list[StatsResult]:
    return [calculate_descriptive_stats(df, c) for c in columns]


def _fmt(v, digits=4):
    if v is None:
        return "-"
    return f"{float(v):.{digits}f}"


def descriptive_to_dataframe(results: list[StatsResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "列名": r.column_name,
            "有效计数": r.count,
            "缺失值": r.missing_count,
            "缺失率": _fmt(r.missing_rate),
            "最大值": _fmt(r.max),
            "最小值": _fmt(r.min),
            "均值": _fmt(r.mean),
            "中位数": _fmt(r.median),
            "求和": _fmt(r.sum),
            "方差": _fmt(r.variance),
            "标准差": _fmt(r.std_dev),
            "极差": _fmt(r.range),
            "变异系数CV": _fmt(r.cv),
            "偏度": _fmt(r.skewness),
            "峰度": _fmt(r.kurtosis),
            "Q1(25%)": _fmt(r.q1),
            "Q3(75%)": _fmt(r.q3),
            "IQR": _fmt(r.iqr),
            "P1": _fmt(r.p01),
            "P5": _fmt(r.p05),
            "P95": _fmt(r.p95),
            "P99": _fmt(r.p99),
        })
    return pd.DataFrame(rows)


def quantile_table(df: pd.DataFrame, columns: Iterable[str], probs: list[float] | None = None) -> pd.DataFrame:
    if probs is None:
        probs = [0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0]
    rows = []
    for col in columns:
        if col not in df.columns:
            continue
        valid, _, _ = _valid_numeric(df, col)
        if valid.empty:
            row = {"列名": col}
            for p in probs:
                row[f"P{int(p*100):02d}"] = "-"
            rows.append(row)
            continue
        qs = valid.quantile(probs)
        row = {"列名": col}
        for p in probs:
            key = f"P{int(round(p*100)):d}"
            if abs(p*100 - int(p*100)) > 1e-9:
                key = f"Q{p:.2f}"
            row[key] = _fmt(qs.loc[p])
        rows.append(row)
    return pd.DataFrame(rows)


def missing_summary(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    rows = []
    for col in columns:
        if col not in df.columns:
            continue
        s = df[col]
        total = int(s.shape[0])
        na = int(s.isna().sum())
        numeric, invalid = infer_numeric_series(s)
        if pd.api.types.is_numeric_dtype(s):
            invalid_num = 0
        else:
            invalid_num = int(invalid)
        valid_num = int(numeric.notna().sum())
        missing_total = na + invalid_num
        rows.append({
            "列名": col,
            "总行数": total,
            "缺失值(空)": na,
            "非数值无效数": invalid_num,
            "总无效数": missing_total,
            "有效数值数": valid_num,
            "缺失+无效占比": _fmt(missing_total / total if total else None),
        })
    return pd.DataFrame(rows)


def correlation_matrix(df: pd.DataFrame, columns: Iterable[str], method: str = "pearson") -> pd.DataFrame:
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return pd.DataFrame()
    num_df = df[cols].apply(lambda s: pd.to_numeric(s, errors="coerce"))
    corr = num_df.corr(method=method)
    return corr



def _kde_1d(x: np.ndarray, n_grid: int = 256, bw: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 2:
        return np.array([]), np.array([])
    std = float(np.std(x, ddof=1)) if n > 1 else 0.0
    if std <= 0:
        return np.array([]), np.array([])
    if bw is None:
        # Silverman's rule of thumb
        iqr = float(np.percentile(x, 75) - np.percentile(x, 25))
        s = min(std, iqr / 1.349) if iqr > 0 else std
        bw = 0.9 * s * (n ** (-0.2))
    if bw <= 0:
        bw = std * 0.2 if std > 0 else 1.0
    lo = float(x.min()) - 3 * bw
    hi = float(x.max()) + 3 * bw
    grid = np.linspace(lo, hi, n_grid)
    # Gaussian kernel, vectorized
    u = (grid[:, None] - x[None, :]) / bw
    kernel = np.exp(-0.5 * u * u) / np.sqrt(2 * np.pi)
    density = kernel.mean(axis=1) / bw
    return grid, density


def distribution_data(df: pd.DataFrame, column: str, bins: int = 30, iqr_k: float = 1.5) -> DistributionData:
    valid, _, total = _valid_numeric(df, column)
    arr = valid.to_numpy(dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return DistributionData(
            column=column, edges=np.array([]), counts=np.array([]),
            kde_x=None, kde_y=None,
            q1=None, q3=None, median=None, mean=None,
            iqr_lower=None, iqr_upper=None, outliers=np.array([]), n_total=total,
        )
    counts, edges = np.histogram(arr, bins=bins)
    kde_x, kde_y = _kde_1d(arr)
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    median = float(np.median(arr))
    mean = float(arr.mean())
    iqr = q3 - q1
    lower = q1 - iqr_k * iqr
    upper = q3 + iqr_k * iqr
    outlier_mask = (arr < lower) | (arr > upper)
    outliers = arr[outlier_mask]
    return DistributionData(
        column=column, edges=edges, counts=counts,
        kde_x=kde_x if kde_x.size else None,
        kde_y=kde_y if kde_y.size else None,
        q1=q1, q3=q3, median=median, mean=mean,
        iqr_lower=float(lower), iqr_upper=float(upper),
        outliers=outliers, n_total=total,
    )


def boxplot_stats(df: pd.DataFrame, columns: Iterable[str], iqr_k: float = 1.5) -> pd.DataFrame:
    rows = []
    for col in columns:
        if col not in df.columns:
            continue
        d = distribution_data(df, col, bins=2, iqr_k=iqr_k)
        rows.append({
            "列名": col,
            "N": d.n_total,
            "Min": _fmt(d.edges.min() if d.edges.size else None),
            "Q1": _fmt(d.q1),
            "Median": _fmt(d.median),
            "Q3": _fmt(d.q3),
            "Max": _fmt(d.edges.max() if d.edges.size else None),
            "IQR下界": _fmt(d.iqr_lower),
            "IQR上界": _fmt(d.iqr_upper),
            "离群点数": int(d.outliers.size),
        })
    return pd.DataFrame(rows)
