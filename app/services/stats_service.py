from __future__ import annotations

import pandas as pd

from app.models.stats_result import StatsResult
from app.services.data_processor import infer_numeric_series
from app.utils.type_utils import safe_float


def calculate_column_stats(df: pd.DataFrame, column_name: str) -> StatsResult:
    if column_name not in df.columns:
        raise KeyError(f"列不存在：{column_name}")

    numeric_series, invalid_count = infer_numeric_series(df[column_name])
    valid = numeric_series.dropna()

    count = int(valid.shape[0])
    missing_count = int(numeric_series.isna().sum())

    if count == 0:
        return StatsResult(
            column_name=column_name,
            count=0,
            missing_count=missing_count,
            max=None,
            min=None,
            mean=None,
            median=None,
            sum=None,
            variance=None,
            std_dev=None,
            range=None,
        )

    max_val = safe_float(valid.max())
    min_val = safe_float(valid.min())
    mean_val = safe_float(valid.mean())
    median_val = safe_float(valid.median())
    sum_val = safe_float(valid.sum())
    variance_val = safe_float(valid.var(ddof=1)) if count > 1 else None
    std_val = safe_float(valid.std(ddof=1)) if count > 1 else None
    range_val = safe_float(max_val - min_val) if max_val is not None and min_val is not None else None

    return StatsResult(
        column_name=column_name,
        count=count,
        missing_count=missing_count,
        max=max_val,
        min=min_val,
        mean=mean_val,
        median=median_val,
        sum=sum_val,
        variance=variance_val,
        std_dev=std_val,
        range=range_val,
    )


def calculate_batch_stats(df: pd.DataFrame, column_names: list[str]) -> list[StatsResult]:
    return [calculate_column_stats(df, name) for name in column_names]


def stats_to_dataframe(results: list[StatsResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append(
            {
                "列名": r.column_name,
                "有效计数": r.count,
                "缺失值": r.missing_count,
                "最大值": _fmt(r.max),
                "最小值": _fmt(r.min),
                "平均值": _fmt(r.mean),
                "中位数": _fmt(r.median),
                "求和": _fmt(r.sum),
                "方差": _fmt(r.variance),
                "标准差": _fmt(r.std_dev),
                "极差": _fmt(r.range),
            }
        )
    return pd.DataFrame(rows)


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"
