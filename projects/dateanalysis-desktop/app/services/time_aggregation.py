from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


GRANULARITIES = ["原始", "分钟", "小时", "班次", "天", "周"]


def aggregate_by_time(df: pd.DataFrame, time_col: str, y_columns: Iterable[str], granularity: str) -> tuple[pd.DataFrame, list[str], bool, str]:
    """返回 (aggregated_df, logs, x_is_datetime, x_column_name)"""
    logs: list[str] = []
    if granularity == "原始":
        work = df.copy()
        work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
        is_dt = pd.api.types.is_datetime64_any_dtype(work[time_col])
        work.attrs["x_is_datetime"] = is_dt
        return work, logs, is_dt, time_col

    if time_col not in df.columns:
        raise KeyError(f"时间列不存在：{time_col}")
    work = df.copy()
    work[time_col] = pd.to_datetime(work[time_col], errors="coerce")
    work = work.dropna(subset=[time_col]).copy()
    if work.empty:
        empty = work.copy()
        empty.attrs["x_is_datetime"] = False
        return empty, ["时间列无有效时间数据，无法聚合。"], False, time_col

    y_cols = [c for c in y_columns if c in work.columns]
    if not y_cols:
        raise ValueError("没有可聚合的 Y 列")
    for col in y_cols:
        work[col] = pd.to_numeric(work[col], errors="coerce")

    if granularity == "分钟":
        labels = work[time_col].dt.floor("min")
        label_text = "分钟"
        x_is_datetime = True
    elif granularity == "小时":
        labels = work[time_col].dt.floor("h")
        label_text = "小时"
        x_is_datetime = True
    elif granularity == "天":
        labels = work[time_col].dt.floor("D")
        label_text = "天"
        x_is_datetime = True
    elif granularity == "周":
        labels = work[time_col].dt.to_period("W-MON").dt.start_time
        label_text = "周"
        x_is_datetime = True
    elif granularity == "班次":
        labels = work[time_col].apply(_shift_label)
        label_text = "班次"
        x_is_datetime = True
    else:
        raise ValueError(f"不支持的时间粒度：{granularity}")

    work["_聚合时间"] = labels
    # 先按标签和数值列聚合，避免非数值列造成问题
    grouped = (
        work.groupby("_聚合时间", as_index=False)[y_cols]
        .mean()
        .sort_values("_聚合时间")
        .reset_index(drop=True)
    )
    grouped.rename(columns={"_聚合时间": time_col}, inplace=True)
    logs.append(f"已按{label_text}聚合展示，Y 值取该时间窗口平均值。")
    grouped.attrs["x_is_datetime"] = x_is_datetime
    return grouped, logs, x_is_datetime, time_col


def _shift_label(ts: pd.Timestamp) -> pd.Timestamp:
    # 早班：08:00-20:00（含08，不含20）；晚班：20:00-次日08:00，归属开始日20点
    if ts.hour >= 8 and ts.hour < 20:
        return pd.Timestamp(year=ts.year, month=ts.month, day=ts.day, hour=8)
    if ts.hour >= 20:
        return pd.Timestamp(year=ts.year, month=ts.month, day=ts.day, hour=20)
    previous_day = ts - pd.Timedelta(days=1)
    return pd.Timestamp(year=previous_day.year, month=previous_day.month, day=previous_day.day, hour=20)
