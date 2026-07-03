from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ProcessingRule:
    column: str
    operator: str  # lt, lte, gt, gte, eq, neq, is_null, not_null
    threshold: Any | None
    action: str  # delete_row, replace_mean
