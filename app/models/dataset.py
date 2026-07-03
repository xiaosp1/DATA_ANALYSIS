from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ColumnMeta:
    name: str
    dtype: str
    is_numeric: bool
    is_datetime: bool
    missing_count: int
    sample_values: list[Any] = field(default_factory=list)


@dataclass
class DataSet:
    file_name: str
    file_path: str
    df: pd.DataFrame
    column_metas: dict[str, ColumnMeta]

    @property
    def columns(self) -> list[str]:
        return [str(c) for c in self.df.columns.tolist()]

    @property
    def row_count(self) -> int:
        return int(self.df.shape[0])

    @property
    def column_count(self) -> int:
        return int(self.df.shape[1])

    def get_numeric_columns(self) -> list[str]:
        return [name for name, meta in self.column_metas.items() if meta.is_numeric]

    def get_datetime_columns(self) -> list[str]:
        return [name for name, meta in self.column_metas.items() if meta.is_datetime]

    def get_column_series(self, column_name: str) -> pd.Series:
        if column_name not in self.df.columns:
            raise KeyError(f"Column not found: {column_name}")
        return self.df[column_name]

    def clear(self) -> None:
        self.df = self.df.iloc[0:0]
        self.column_metas = {}
