from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

from app.models.dataset_item import DatasetItem
from app.models.processing_rule import ProcessingRule
from app.services.data_processor import infer_datetime_series, infer_numeric_series
from app.utils.type_utils import safe_float


SCALE_EXCLUDE_MODES = {"auto", "manual", "none"}


def _to_comparable(value: Any) -> Any:
    return value


def _is_numeric_column(series: pd.Series) -> bool:
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return False
    if pd.api.types.is_numeric_dtype(series):
        return True
    converted = pd.to_numeric(series, errors="coerce")
    non_null = series.dropna()
    if non_null.empty:
        return False
    valid_ratio = converted.notna().sum() / len(non_null)
    return valid_ratio >= 0.5


def _is_datetime_like_column(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_numeric_dtype(series):
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        converted = infer_datetime_series(series)
    non_null_original = series.dropna()
    if non_null_original.empty:
        return False
    non_null_converted = converted.notna().sum()
    return non_null_converted / len(non_null_original) >= 0.8


MM_SUFFIXES = ("(mm)", "（mm）", "(MM)", "（MM）")


def _strip_mm_suffix(col: str) -> str:
    """Remove trailing mm suffix (both half-width and full-width parentheses).

    Returns the base column name without mm suffix; if no mm suffix is present,
    returns the original text stripped.
    """
    text = str(col).strip()
    for suffix in MM_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    return text


def _scale_column_name(name: str) -> str:
    text = _strip_mm_suffix(name)
    return f"{text}(mm)"


def _revert_scaled_columns(df: pd.DataFrame, old_factor: float) -> tuple[pd.DataFrame, int]:
    """Revert a previously scaled DataFrame: strip (mm) suffix and divide by old_factor.

    Identifies columns ending with any mm suffix (full/half-width), divides the
    numeric values by ``old_factor`` (approximate inverse of a previous float32
    multiply), and renames them back to the base name. Returns (new_df, n_cols).
    """
    out = df.copy()
    rename_map: dict[str, str] = {}  # old (mm) name -> base name
    existing_names = [str(c) for c in out.columns]
    reverted = 0
    for col in list(out.columns):
        col_str = str(col)
        base = _strip_mm_suffix(col_str)
        if base == col_str:
            continue  # no mm suffix
        # Divide numeric values back by old factor to recover pixel-scale values
        series = pd.to_numeric(out[col_str], errors="coerce")
        if old_factor and np.isfinite(old_factor) and abs(old_factor) > 1e-30:
            series = series / float(old_factor)
        out[col_str] = series
        # Avoid name collisions when renaming back
        target = base
        if target in rename_map.values() or (target in existing_names and target != col_str):
            idx = 1
            while True:
                cand = f"{target}__rescale{idx}"
                if cand not in rename_map.values() and cand not in existing_names:
                    target = cand
                    break
                idx += 1
        rename_map[col_str] = target
        reverted += 1
    if rename_map:
        out = out.rename(columns=rename_map)
    return out, reverted


def _unique_column_name(existing: list[str], target: str) -> str:
    if target not in existing:
        return target
    index = 1
    while True:
        candidate = f"{target}_{index}"
        if candidate not in existing:
            return candidate
        index += 1


def _resolve_exclude_columns(result: pd.DataFrame, rule: ProcessingRule, index: int, logs: list[str]) -> list[str]:
    mode = getattr(rule, "exclude_mode", "auto")
    if mode not in SCALE_EXCLUDE_MODES:
        logs.append(f"规则 {index}：未知排除列模式“{mode}”，已按自动识别时间/日期列处理。")
        mode = "auto"

    if mode == "none":
        return []

    configured = [str(col) for col in getattr(rule, "exclude_columns", []) if str(col) in result.columns]
    missing = [str(col) for col in getattr(rule, "exclude_columns", []) if str(col) not in result.columns]
    if missing:
        logs.append(f"规则 {index}：排除列不存在，已忽略：{', '.join(missing)}")

    if mode == "manual":
        return configured

    auto_cols = [str(col) for col in result.columns if _is_datetime_like_column(result[col])]
    resolved: list[str] = []
    for col in dict.fromkeys(auto_cols + configured):
        resolved.append(col)
    return resolved


def _scale_numeric_series(series: pd.Series, factor: float) -> pd.Series:
    """使用 float32（单精度）完成乘法，再回到 float64 以便 pandas 后续处理。"""
    numeric = pd.to_numeric(series, errors="coerce").astype(np.float32)
    scaled = numeric * np.float32(factor)
    return pd.Series(scaled.to_numpy(dtype=np.float64), index=series.index, name=series.name)


def _apply_scale_all_columns(
    result: pd.DataFrame,
    rule: ProcessingRule,
    factor: float,
    index: int,
    logs: list[str],
    scaled_total: int,
) -> tuple[pd.DataFrame, int]:
    exclude_columns = _resolve_exclude_columns(result, rule, index, logs)
    excluded_numeric = [col for col in exclude_columns if _is_numeric_column(result[col])]
    excluded_non_numeric = [col for col in exclude_columns if col not in excluded_numeric]

    target_cols = [
        str(c)
        for c in result.columns
        if _is_numeric_column(result[c]) and str(c) not in exclude_columns
    ]
    if not target_cols:
        logs.append(f"规则 {index}：未找到可缩放的数值列，已跳过。")
        return result, scaled_total

    auto_skipped_non_numeric = [
        str(c)
        for c in result.columns
        if str(c) not in target_cols and str(c) not in exclude_columns
    ]

    renamed_map: dict[str, str] = {}
    existing_names = [str(c) for c in result.columns]
    scaled_count = 0
    failed_cols: list[str] = []
    for col in target_cols:
        try:
            result[col] = _scale_numeric_series(result[col], factor)
        except Exception as exc:
            logs.append(f"规则 {index}：列“{col}”缩放失败：{exc}")
            failed_cols.append(col)
            continue
        new_name = _unique_column_name([c for c in existing_names if c != col], _scale_column_name(col))
        renamed_map[col] = new_name
        scaled_count += 1

    if renamed_map:
        result = result.rename(columns=renamed_map)
    scaled_total += scaled_count

    # rename 后更新自动跳过列中的被重命名项（这里跳过列均为非数值，不会被 rename）
    exclude_desc_parts: list[str] = []
    if excluded_numeric:
        exclude_desc_parts.append(f"排除数值列 {len(excluded_numeric)} 列：{', '.join(excluded_numeric)}")
    skipped_all = []
    seen: set[str] = set()
    for col in excluded_non_numeric + auto_skipped_non_numeric:
        if col not in seen:
            skipped_all.append(col)
            seen.add(col)
    if skipped_all:
        exclude_desc_parts.append(f"自动跳过非数值列 {len(skipped_all)} 列：{', '.join(skipped_all)}")
    exclude_desc = "；".join(exclude_desc_parts) if exclude_desc_parts else "无排除列"
    if failed_cols:
        exclude_desc = f"{exclude_desc}；失败 {len(failed_cols)} 列：{', '.join(failed_cols)}"

    mode_label = getattr(rule, "exclude_mode", "auto")
    logs.append(
        f"规则 {index}：全部数值列按因子 {factor:g} 使用 float32 单精度语义缩放为 mm，"
        f"共缩放 {scaled_count} 列（排除模式：{mode_label}；{exclude_desc}）。"
    )
    return result, scaled_total


def _apply_scale_single_column(
    result: pd.DataFrame,
    rule: ProcessingRule,
    factor: float,
    index: int,
    logs: list[str],
    scaled_total: int,
) -> tuple[pd.DataFrame, int]:
    target_col = str(rule.column)
    if target_col not in result.columns:
        logs.append(f"规则 {index}：列“{target_col}”不存在，已跳过。")
        return result, scaled_total

    series = result[target_col]
    if not _is_numeric_column(series):
        logs.append(f"规则 {index}：列“{target_col}”非数值列，无法缩放，已跳过。")
        return result, scaled_total

    try:
        result[target_col] = _scale_numeric_series(series, factor)
    except Exception as exc:
        logs.append(f"规则 {index}：列“{target_col}”缩放失败：{exc}")
        return result, scaled_total

    existing_names = [str(c) for c in result.columns if str(c) != target_col]
    new_name = _unique_column_name(existing_names, _scale_column_name(target_col))
    if new_name != target_col:
        result = result.rename(columns={target_col: new_name})
    scaled_total += 1
    logs.append(
        f"规则 {index}：列“{target_col}”按因子 {factor:g} 使用 float32 单精度语义缩放为 mm，输出列“{new_name}”。"
    )
    return result, scaled_total


def apply_rules(df: pd.DataFrame, rules: list[ProcessingRule]) -> tuple[pd.DataFrame, list[str]]:
    result = df.copy()
    logs: list[str] = []
    deleted_total = 0
    replaced_total = 0
    scaled_total = 0

    for index, rule in enumerate(rules, start=1):
        if rule.action == "scale_by_factor":
            factor = safe_float(rule.threshold)
            if factor is None:
                logs.append(f"规则 {index}：缩放因子无效，已跳过。")
                continue
            if factor <= 0 or not np.isfinite(factor):
                logs.append(f"规则 {index}：缩放因子必须为大于 0 的有限数值（当前为 {factor}），已跳过。")
                continue
            if factor == 1.0:
                logs.append(f"规则 {index}：缩放因子为 1.0，数据无需缩放，已跳过。")
                continue

            if rule.column == "*":
                result, scaled_total = _apply_scale_all_columns(result, rule, factor, index, logs, scaled_total)
            else:
                result, scaled_total = _apply_scale_single_column(result, rule, factor, index, logs, scaled_total)
            continue

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

    logs.insert(0, f"数据处理完成：删除 {deleted_total} 行，替换 {replaced_total} 个值，缩放 {scaled_total} 列。")
    return result, logs


def scale_datasets_by_category(
    dataset_manager: Any,
    category: str | None,
    factor: float,
    exclude_mode: str = "auto",
    exclude_columns: list[str] | None = None,
    force_rescale: bool = False,
    rescale_targets: list[Any] | None = None,
) -> list[str]:
    """按类别批量缩放原始数据集（mm 语义）。

    - 仅作用于 ``kind == 'original'`` 且 ``category`` 匹配的数据集。
    - 默认已 ``scaled=True`` 的数据集会被跳过，避免重复乘。传入
      ``force_rescale=True`` 与 ``rescale_targets`` 列表时，会先把这些
      数据集的列名复原并按 old_factor 还原数值，再重新缩放。
    - 沿用现有 float32 单精度、自动跳时间/文本/布尔/日期、(mm) 后缀、排除列、非法因子校验语义。
    - 成功后把对应 :class:`DatasetItem` 的 ``scaled`` 置为 ``True``，并同步 ``pixel_factor``。
    - 返回本次处理的日志列表。
    """
    logs: list[str] = []
    if exclude_mode not in SCALE_EXCLUDE_MODES:
        logs.append(f"按类别缩放：未知排除列模式“{exclude_mode}”，已按自动识别时间/日期列处理。")
        exclude_mode = "auto"

    # 非法因子：保持与 apply_rules 一致的校验，并保证不修改任何数据
    try:
        factor_value = float(factor)
    except (TypeError, ValueError):
        logs.append(f"按类别缩放：缩放因子无效（{factor!r}），已跳过。")
        return logs
    if not np.isfinite(factor_value) or factor_value <= 0:
        logs.append(f"按类别缩放：缩放因子必须为大于 0 的有限数值（当前为 {factor_value}），已跳过。")
        return logs
    if factor_value == 1.0:
        logs.append("按类别缩放：缩放因子为 1.0，数据无需缩放，已跳过。")
        return logs

    # 先处理强制重缩放的数据集：先复原再走正常缩放流程
    if force_rescale and rescale_targets:
        by_id = {it.dataset_id: it for it in dataset_manager.items()}
        for item in rescale_targets:
            if item is None or not getattr(item, "dataset_id", None):
                continue
            live = by_id.get(item.dataset_id)
            if live is None:
                continue
            old_factor = float(getattr(live, "pixel_factor", None) or 1.0)
            try:
                reverted_df, n = _revert_scaled_columns(live.df, old_factor)
                live.df = reverted_df
                live.scaled = False
                live.pixel_factor = None
                logs.append(
                    f"按类别缩放：数据集“{live.name}”已复原 {n} 个 (mm) 列（旧 factor={old_factor:g}），准备重缩放。"
                )
            except Exception as exc:  # noqa: BLE001
                logs.append(f"按类别缩放：数据集“{live.name}”复原失败：{exc}，跳过该数据集。")
                continue

    targets: list[DatasetItem] = []
    for item in dataset_manager.items():
        if item.kind != "original":
            continue
        if item.category != category:
            continue
        targets.append(item)

    if not targets:
        label = "未分类" if category is None else category
        logs.append(f"按类别缩放：类别“{label}”下没有待缩放的原始数据集。")
        return logs

    rule = ProcessingRule(
        column="*",
        operator="none",
        threshold=factor_value,
        action="scale_by_factor",
        exclude_mode=exclude_mode,
        exclude_columns=list(exclude_columns or []),
    )

    label = "未分类" if category is None else ("机头" if category == "head" else ("机尾" if category == "tail" else str(category)))
    logs.append(f"按类别缩放：开始对类别“{label}”下 {len(targets)} 个原始数据集按因子 {factor_value:g} 批量缩放。")

    skipped_scaled = 0
    for item in targets:
        if item.scaled:
            skipped_scaled += 1
            logs.append(f"按类别缩放：数据集“{item.name}”已完成过缩放，跳过以避免重复乘。")
            continue
        sub_df, sub_logs = apply_rules(item.df, [rule])
        item.df = sub_df
        item.scaled = True
        item.pixel_factor = factor_value
        logs.append(f"按类别缩放：数据集“{item.name}”处理完成。")
        for sub in sub_logs:
            logs.append(f"  [{item.name}] {sub}")

    if skipped_scaled:
        logs.append(f"按类别缩放：已跳过 {skipped_scaled} 个已缩放数据集。")
    logs.append(f"按类别缩放：类别“{label}”批量缩放结束。")
    return logs


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
