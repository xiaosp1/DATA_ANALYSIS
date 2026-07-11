from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class DatasetItem:
    dataset_id: str
    name: str
    kind: str  # original / processed / merged
    df: pd.DataFrame
    source_files: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    can_delete: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    # V1.7 跨类别字段（默认值保证向后兼容：旧构造/旧 pickle 不报错）
    category: str | None = None  # None=未分类；'head'=机头；'tail'=机尾
    pixel_factor: float | None = None
    scaled: bool = False
