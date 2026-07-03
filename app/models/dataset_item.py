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
