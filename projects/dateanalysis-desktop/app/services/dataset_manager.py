from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from app.models.dataset_item import DatasetItem
from app.services.data_processor import infer_datetime_series


CATEGORY_LABELS: dict[str, str] = {
    "head": "机头",
    "tail": "机尾",
}

CATEGORY_PREFIXES: dict[str, str] = {
    "head": "[机头]",
    "tail": "[机尾]",
}

TIME_COLUMN = "时间"
MM_SUFFIXES = ("(mm)", "（mm）", "(MM)", "（MM）")


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

    # ------------------------------------------------------------------
    # V1.7 跨类别合并
    # ------------------------------------------------------------------
    def _original_items_of_category(self, category: str | None) -> list[DatasetItem]:
        return [
            item for item in self._items.values()
            if item.kind == "original" and getattr(item, "category", None) == category
        ]

    def _find_temporary_by_name(self, name: str) -> DatasetItem | None:
        for item in self._items.values():
            if item.kind in {"processed", "merged"} and item.name == name:
                return item
        return None

    def _concat_and_sort(self, items: list[DatasetItem], time_column: str, label: str) -> pd.DataFrame:
        frames = []
        source_files: list[str] = []
        missing_names: list[str] = []
        for item in items:
            if time_column not in item.df.columns:
                missing_names.append(item.name)
                continue
            work = item.df.copy()
            work[time_column] = infer_datetime_series(work[time_column])
            work = work.dropna(subset=[time_column])
            frames.append(work)
            source_files.extend(item.source_files)
        if missing_names:
            raise ValueError(
                f"{label}合并失败：以下数据集缺少时间列“{time_column}”：{', '.join(missing_names)}"
            )
        if not frames:
            raise ValueError(f"{label}合并失败：没有可用数据。")
        merged = pd.concat(frames, ignore_index=True, sort=False)
        merged = merged.sort_values(by=time_column, kind="mergesort").reset_index(drop=True)
        return merged

    def merge_by_category(self, category: str) -> DatasetItem:
        """同类别多文件 concat + 时间排序，结果存入临时储存区。"""
        if category not in CATEGORY_LABELS:
            raise ValueError(f"不支持的类别：{category}，仅支持 {sorted(CATEGORY_LABELS)}")
        label = CATEGORY_LABELS[category]
        result_name = f"{label}_合并"
        existing = self._find_temporary_by_name(result_name)
        if existing is not None:
            return existing

        originals = self._original_items_of_category(category)
        if not originals:
            raise ValueError(f"{label}合并失败：类别“{label}”下还没有导入原始数据集。")

        merged = self._concat_and_sort(originals, TIME_COLUMN, label)
        source_files: list[str] = []
        for it in originals:
            source_files.extend(it.source_files)
        return self.add_temporary(
            result_name,
            merged,
            kind="merged",
            source_files=source_files,
            metadata={"time_column": TIME_COLUMN, "category": category, "merge_type": "category"},
        )

    @staticmethod
    def _strip_mm_suffix(text: str) -> tuple[str, str]:
        """返回 (不含 mm 后缀的主体, 原始 mm 后缀或空串)。"""
        for suffix in MM_SUFFIXES:
            if text.endswith(suffix):
                return text[: -len(suffix)].strip(), suffix
        return text, ""

    @classmethod
    def _prefix_non_time_columns(
        cls,
        df: pd.DataFrame,
        prefix: str,
        used_names: list[str],
    ) -> pd.DataFrame:
        rename_map: dict[str, str] = {}
        existing = list(used_names)
        for col in df.columns:
            col_str = str(col)
            if col_str == TIME_COLUMN:
                continue
            base, suffix = cls._strip_mm_suffix(col_str)
            # 如果列名本身已经以该类前缀开头，则保留主体不再重复加前缀
            if base.startswith(prefix):
                target = f"{base}{suffix}"
            else:
                target = f"{prefix}{base}{suffix}"
            if target in existing or target in rename_map.values():
                index = 1
                while True:
                    candidate = f"{target}_{index}"
                    if candidate not in existing and candidate not in rename_map.values():
                        target = candidate
                        break
                    index += 1
            rename_map[col_str] = target
            existing.append(target)
        return df.rename(columns=rename_map)

    def merge_cross_category(
        self,
        head_label: str = "机头",
        tail_label: str = "机尾",
    ) -> DatasetItem:
        """跨类别 outer join：先确保 机头_合并 / 机尾_合并 存在，再按时间外连接。"""
        result_name = f"{head_label}+{tail_label}_跨类合并"
        existing = self._find_temporary_by_name(result_name)
        if existing is not None:
            return existing

        # 标签→内部类别码
        label_to_code = {lab: code for code, lab in CATEGORY_LABELS.items()}
        head_code = label_to_code.get(head_label)
        tail_code = label_to_code.get(tail_label)
        if head_code is None or tail_code is None:
            raise ValueError(f"不支持的跨类标签：head_label={head_label}, tail_label={tail_label}")

        head_merged = self.merge_by_category(head_code)
        tail_merged = self.merge_by_category(tail_code)

        for item in (head_merged, tail_merged):
            if TIME_COLUMN not in item.df.columns:
                raise ValueError(
                    f"跨类合并失败：数据集“{item.name}”缺少时间列“{TIME_COLUMN}”。"
                )

        head_df = head_merged.df.copy()
        tail_df = tail_merged.df.copy()
        head_df[TIME_COLUMN] = infer_datetime_series(head_df[TIME_COLUMN])
        tail_df[TIME_COLUMN] = infer_datetime_series(tail_df[TIME_COLUMN])
        head_df = head_df.dropna(subset=[TIME_COLUMN])
        tail_df = tail_df.dropna(subset=[TIME_COLUMN])

        # 给非时间列加前缀，两侧先用 TIME_COLUMN 保留；前缀重名去重保证全局唯一
        used_names: list[str] = [TIME_COLUMN]
        head_prefixed = self._prefix_non_time_columns(head_df, CATEGORY_PREFIXES[head_code], used_names)
        used_names = [c for c in head_prefixed.columns]
        tail_prefixed = self._prefix_non_time_columns(tail_df, CATEGORY_PREFIXES[tail_code], used_names)

        joined = pd.merge(
            head_prefixed,
            tail_prefixed,
            on=TIME_COLUMN,
            how="outer",
            sort=True,
        )
        joined = joined.reset_index(drop=True)

        source_files = list(head_merged.source_files) + list(tail_merged.source_files)
        return self.add_temporary(
            result_name,
            joined,
            kind="merged",
            source_files=source_files,
            metadata={
                "time_column": TIME_COLUMN,
                "merge_type": "cross_category",
                "head": head_label,
                "tail": tail_label,
            },
        )

    def merge_uncategorized(self, result_name: str | None = None) -> DatasetItem:
        """未分类路径：把所有 category=None 的原始数据集按旧逻辑 concat+时间排序。

        返回临时数据集。未分类是 V1.6.1 的 0 回归入口，这里单独提供方法方便测试/UI 复用。
        """
        originals = self._original_items_of_category(None)
        if not originals:
            raise ValueError("未分类合并失败：当前没有未分类原始数据集。")
        label = "未分类"
        merged = self._concat_and_sort(originals, TIME_COLUMN, label)
        source_files: list[str] = []
        for it in originals:
            source_files.extend(it.source_files)
        name = result_name or f"未分类合并_{datetime.now().strftime('%H%M%S')}"
        return self.add_temporary(
            name,
            merged,
            kind="merged",
            source_files=source_files,
            metadata={"time_column": TIME_COLUMN, "category": None, "merge_type": "category"},
        )
