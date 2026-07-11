from __future__ import annotations

from typing import Any

import pandas as pd


def to_builtin(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def safe_float(value: Any) -> float | None:
    val = to_builtin(value)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
