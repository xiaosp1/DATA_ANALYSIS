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
