from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StatsResult:
    column_name: str
    count: int
    missing_count: int
    max: float | None
    min: float | None
    mean: float | None
    median: float | None
    sum: float | None
    variance: float | None
    std_dev: float | None
    range: float | None
    # --- 描述性统计扩展（基础层） ---
    missing_rate: float | None = None
    cv: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    p01: float | None = None
    p05: float | None = None
    p95: float | None = None
    p99: float | None = None
