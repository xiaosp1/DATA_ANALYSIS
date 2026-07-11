from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProcessingRule:
    column: str
    operator: str  # lt, lte, gt, gte, eq, neq, is_null, not_null, none
    threshold: Any | None
    action: str  # delete_row, replace_mean, scale_by_factor
    exclude_mode: str = "auto"  # auto / manual / none
    exclude_columns: list[str] = field(default_factory=list)
