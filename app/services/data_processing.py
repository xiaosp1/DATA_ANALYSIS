from __future__ import annotations

from typing import Any

import pandas as pd

from app.models.processing_rule import ProcessingRule
from app.services.data_processor import infer_numeric_series
from app.utils.type_utils import safe_float


def _to_comparable(value: Any) -> Any:
    return value


def apply_rules(df: pd.DataFrame, rules: list[ProcessingRule]) -> tuple[pd.DataFrame, list[str]]:
    result = df.copy()
    logs: list[str] = []
    deleted_total = 0
    replaced_total = 0

    for index, rule in enumerate(rules, start=1):
        if rule.column not in result.columns:
            logs.append(f"规则 {index}：列“{rule.column}”不存在，已跳过。")
            continue

        series = result[rule.column]
        numeric_series, _ = infer_numeric_series(series)
        threshold = _parse_threshold(rule.threshold)

        if rule.operator in {"lt", "lte", "gt", "gte", "eq", "neq"} and threshold is None:
            logs.append(f"规则 {index}：缺少阈值，已跳过。")
            continue

        if rule.operator == "is_null":
            mask = result[rule.column].isna()
        elif rule.operator == "not_null":
            mask = result[rule.column].notna()
        else:
            compare_series = numeric_series if rule.action == "replace_mean" else series
            try:
                if rule.operator == "lt":
                    mask = compare_series < threshold
                elif rule.operator == "lte":
                    mask = compare_series <= threshold
                elif rule.operator == "gt":
                    mask = compare_series > threshold
                elif rule.operator == "gte":
                    mask = compare_series >= threshold
                elif rule.operator == "eq":
                    mask = compare_series == threshold
                elif rule.operator == "neq":
                    mask = compare_series != threshold
                else:
                    logs.append(f"规则 {index}：未知运算符 {rule.operator}，已跳过。")
                    continue
            except Exception as exc:
                logs.append(f"规则 {index}：条件执行失败：{exc}")
                continue
            mask = mask.fillna(False)

        if rule.action == "delete_row":
            before = len(result)
            result = result.loc[~mask].copy()
            deleted = before - len(result)
            deleted_total += deleted
            logs.append(f"规则 {index}：根据列“{rule.column}”执行删除，删除 {deleted} 行。")
        elif rule.action == "replace_mean":
            col = rule.column
            valid_numeric = pd.to_numeric(result[col], errors="coerce")
            mean_value = safe_float(valid_numeric.mean())
            if mean_value is None:
                logs.append(f"规则 {index}：列“{col}”无有效数值，无法替换为均值。")
                continue
            replace_count = int(mask.sum())
            result.loc[mask, col] = mean_value
            replaced_total += replace_count
            logs.append(f"规则 {index}：根据列“{col}”替换 {replace_count} 个值为均值 {mean_value:.4f}。")
        else:
            logs.append(f"规则 {index}：未知动作 {rule.action}，已跳过。")

    logs.insert(0, f"数据处理完成：删除 {deleted_total} 行，替换 {replaced_total} 个值。")
    return result, logs


def _parse_threshold(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    text = str(raw).strip()
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text
