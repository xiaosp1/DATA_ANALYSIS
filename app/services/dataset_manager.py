from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from app.models.dataset_item import DatasetItem
from app.services.data_processor import infer_datetime_series


class DatasetManager:
    def __init__(self):
        self._items: dict[str, DatasetItem] = {}
        self._active_id: str | None = None
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()

    def import_file(self, name: str, file_path: str, df: pd.DataFrame) -> DatasetItem:
        item = DatasetItem(
            dataset_id=str(uuid.uuid4()),
            name=name,
            kind="original",
            df=df.copy(),
            source_files=[file_path],
            created_at=datetime.now(),
            can_delete=False,
        )
        self._items[item.dataset_id] = item
        if self._active_id is None:
            self._active_id = item.dataset_id
        self._notify()
        return item

    def add_temporary(self, name: str, df: pd.DataFrame, kind: str, source_files: list[str], metadata: dict | None = None) -> DatasetItem:
        item = DatasetItem(
            dataset_id=str(uuid.uuid4()),
            name=name,
            kind=kind,
            df=df.copy(),
            source_files=list(source_files),
            created_at=datetime.now(),
            can_delete=True,
            metadata=metadata or {},
        )
        self._items[item.dataset_id] = item
        self._notify()
        return item

    def remove(self, dataset_id: str) -> None:
        if dataset_id not in self._items:
            raise KeyError(f"数据集不存在：{dataset_id}")
        item = self._items[dataset_id]
        if not item.can_delete:
            raise ValueError("原始导入数据不可删除")
        del self._items[dataset_id]
        if self._active_id == dataset_id:
            self._active_id = next(iter(self._items), None)
        self._notify()

    def set_active(self, dataset_id: str) -> None:
        if dataset_id not in self._items:
            raise KeyError(f"数据集不存在：{dataset_id}")
        self._active_id = dataset_id
        self._notify()

    def items(self) -> list[DatasetItem]:
        return list(self._items.values())

    def get(self, dataset_id: str) -> DatasetItem:
        return self._items[dataset_id]

    def active_item(self) -> DatasetItem | None:
        if self._active_id is None:
            return None
        return self._items.get(self._active_id)

    def active_id(self) -> str | None:
        return self._active_id

    def clear(self) -> None:
        self._items.clear()
        self._active_id = None
        self._notify()

    def merge_by_time_column(self, dataset_ids: list[str], time_column: str, result_name: str | None = None) -> DatasetItem:
        if not dataset_ids:
            raise ValueError("请至少选择一个数据集进行合并")
        frames = []
        source_files: list[str] = []
        for dataset_id in dataset_ids:
            item = self._items[dataset_id]
            if time_column not in item.df.columns:
                raise ValueError(f"数据集“{item.name}”缺少时间列：{time_column}")
            work = item.df.copy()
            work[time_column] = infer_datetime_series(work[time_column])
            work = work.dropna(subset=[time_column])
            frames.append(work)
            source_files.extend(item.source_files)
        merged = pd.concat(frames, ignore_index=True, sort=False)
        merged = merged.sort_values(by=time_column, kind="mergesort").reset_index(drop=True)
        name = result_name or f"合并结果_{datetime.now().strftime('%H%M%S')}"
        return self.add_temporary(name, merged, kind="merged", source_files=source_files, metadata={"time_column": time_column})
