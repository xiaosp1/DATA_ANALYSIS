from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChartSeriesConfig:
    y_column: str
    color: str
    show_mean_line: bool = True


@dataclass
class ChartConfig:
    x_column: str
    series: list[ChartSeriesConfig]
    title: str
    sort_x_by_datetime: bool = True
    show_points: bool = True
    show_mean_lines: bool = True
