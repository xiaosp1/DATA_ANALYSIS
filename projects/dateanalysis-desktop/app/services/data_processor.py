from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from PySide6.QtGui import QColor

from app.utils.type_utils import safe_float


def infer_datetime_series(series: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(series, errors="coerce")


def infer_numeric_series(series: pd.Series) -> tuple[pd.Series, int]:
    numeric = pd.to_numeric(series, errors="coerce")
    invalid_count = int(numeric.isna().sum() - series.isna().sum())
    if invalid_count < 0:
        invalid_count = 0
    return numeric, invalid_count


def _infer_x_axis(work: pd.DataFrame, x_col: str) -> tuple[pd.Series, bool, list[str]]:
    messages: list[str] = []
    x_series = work[x_col]
    if pd.api.types.is_datetime64_any_dtype(x_series):
        return x_series, True, messages

    converted = infer_datetime_series(x_series)
    non_null_original = x_series.dropna().shape[0]
    non_null_converted = converted.dropna().shape[0]
    if non_null_original > 0 and non_null_converted / non_null_original >= 0.8:
        messages.append(f"X 轴列“{x_col}”已自动识别为日期时间。")
        return converted, True, messages
    return x_series, False, messages


def prepare_multi_y_chart_data(df: pd.DataFrame, x_col: str, y_columns: list[str]) -> tuple[pd.DataFrame, dict[str, float], bool, list[str]]:
    messages: list[str] = []
    if x_col not in df.columns:
        raise KeyError(f"X 轴列不存在：{x_col}")
    if not y_columns:
        raise ValueError("请至少选择一个 Y 轴列。")
    for y_col in y_columns:
        if y_col not in df.columns:
            raise KeyError(f"Y 轴列不存在：{y_col}")

    keep = [x_col] + y_columns
    work = df[keep].copy()

    x_series, x_is_datetime, x_messages = _infer_x_axis(work, x_col)
    work[x_col] = x_series
    messages.extend(x_messages)

    mean_map: dict[str, float] = {}
    for y_col in y_columns:
        y_numeric, invalid_count = infer_numeric_series(work[y_col])
        work[y_col] = y_numeric
        if invalid_count > 0:
            messages.append(f"Y 轴列“{y_col}”有 {invalid_count} 个值无法转换为数值，已按空值处理。")
        valid = y_numeric.dropna()
        if not valid.empty:
            mean_val = safe_float(valid.mean())
            if mean_val is not None:
                mean_map[y_col] = mean_val

    before_drop = work.shape[0]
    work = work.dropna(subset=[x_col]).copy()
    after_drop = work.shape[0]
    dropped = before_drop - after_drop
    if dropped > 0:
        messages.append(f"绘图时自动忽略 {dropped} 行 X 轴空值数据。")

    if x_is_datetime:
        work = work.sort_values(by=x_col, kind="mergesort")
        messages.append(f"X 轴列“{x_col}”已按日期时间排序。")

    work.attrs["x_is_datetime"] = x_is_datetime
    return work, mean_map, x_is_datetime, messages
