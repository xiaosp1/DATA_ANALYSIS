# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.processing_rule import ProcessingRule
from app.services.data_processing import apply_rules, scale_datasets_by_category
from app.services.dataset_manager import DatasetManager


EPS = 1e-6


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_single_column_scale() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "name": ["a", "b", "c"]})
    rule = ProcessingRule(column="x", operator="none", threshold=0.1, action="scale_by_factor")
    result, logs = apply_rules(df, [rule])
    assert_true("x(mm)" in result.columns, "单列缩放后应自动重命名为 x(mm)")
    assert_true("x" not in result.columns, "原列名 x 不应保留")
    assert_true(abs(float(result["x(mm)"].iloc[0]) - 0.1) < EPS, "x 第一行未按 0.1 缩放")
    assert_true(any("0.1" in log and "mm" in log for log in logs), "日志应包含缩放为 mm 提示")
    assert_true(result["name"].tolist() == ["a", "b", "c"], "文本列不应被缩放影响")


def test_factor_point_five() -> None:
    df = pd.DataFrame({"y": [10.0, 20.0]})
    rule = ProcessingRule(column="y", operator="none", threshold=0.5, action="scale_by_factor")
    result, _ = apply_rules(df, [rule])
    assert_true(abs(float(result["y(mm)"].iloc[0]) - 5.0) < EPS, "因子 0.5 缩放结果错误")
    assert_true(abs(float(result["y(mm)"].iloc[1]) - 10.0) < EPS, "因子 0.5 缩放结果错误")


def test_factor_one_skip() -> None:
    df = pd.DataFrame({"z": [1.0, 2.0]})
    rule = ProcessingRule(column="z", operator="none", threshold=1.0, action="scale_by_factor")
    result, logs = apply_rules(df, [rule])
    assert_true("z" in result.columns, "因子为 1 时不应重命名列")
    assert_true("z(mm)" not in result.columns, "因子为 1 时不应生成 (mm) 列")
    assert_true(any("1.0" in log and "跳过" in log for log in logs), "因子 1 应记录跳过日志")


def test_factor_negative_invalid() -> None:
    df = pd.DataFrame({"z": [1.0, 2.0]})
    rule = ProcessingRule(column="z", operator="none", threshold=-1, action="scale_by_factor")
    result, logs = apply_rules(df, [rule])
    assert_true("z" in result.columns, "非法因子不应修改列")
    assert_true(result["z"].tolist() == [1.0, 2.0], "非法因子不应修改数据")
    assert_true(any("大于 0" in log and "跳过" in log for log in logs), "非法因子应给出错误日志")


def test_factor_non_finite_invalid() -> None:
    df = pd.DataFrame({"z": [1.0, 2.0]})
    rule = ProcessingRule(column="z", operator="none", threshold=float("inf"), action="scale_by_factor")
    result, logs = apply_rules(df, [rule])
    assert_true("z" in result.columns, "非法因子不应修改列")
    assert_true(result["z"].tolist() == [1.0, 2.0], "非法因子不应修改数据")
    assert_true(any("大于 0" in log and "跳过" in log for log in logs), "非有限因子应视为非法")


def test_all_numeric_columns_auto_skip_datetime_text_bool() -> None:
    df = pd.DataFrame(
        {
            "a": [10.0, 20.0],
            "b": [30.0, 40.0],
            "dt": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "time_text": ["2026-01-01 10:00:00", "2026-01-02 11:00:00"],
            "flag": [True, False],
            "name": ["p", "q"],
        }
    )
    rule = ProcessingRule(column="*", operator="none", threshold=10.0, action="scale_by_factor")
    result, logs = apply_rules(df, [rule])
    expected = {"a(mm)", "b(mm)", "dt", "time_text", "flag", "name"}
    assert_true(set(result.columns) == expected, f"全部数值列缩放后列名异常：{list(result.columns)}")
    assert_true(abs(float(result["a(mm)"].iloc[0]) - 100.0) < EPS, "数值列 a 未按因子缩放")
    assert_true(abs(float(result["b(mm)"].iloc[1]) - 400.0) < EPS, "数值列 b 未按因子缩放")
    assert_true(str(result["dt"].dtype).startswith("datetime64"), "日期列不应被缩放")
    assert_true(result["flag"].tolist() == [True, False], "布尔列不应被缩放")
    assert_true(result["name"].tolist() == ["p", "q"], "文本列不应被缩放")
    assert_true(any("共缩放 2 列" in log for log in logs), "全部数值列日志应显示缩放量")
    assert_true(any("自动跳过非数值列" in log for log in logs), "应记录自动跳过非数值列")


def test_existing_mm_suffix_not_duplicated() -> None:
    df = pd.DataFrame({"len(mm)": [1.0, 2.0]})
    rule = ProcessingRule(column="len(mm)", operator="none", threshold=10.0, action="scale_by_factor")
    result, _ = apply_rules(df, [rule])
    assert_true("len(mm)" in result.columns, "已有 (mm) 后缀时不应重复拼接")
    assert_true("len(mm)(mm)" not in result.columns, "不应重复添加 (mm)")
    assert_true(abs(float(result["len(mm)"].iloc[0]) - 10.0) < EPS, "已有 mm 后缀列缩放失败")


def test_existing_mm_suffix_not_duplicated_all_columns() -> None:
    df = pd.DataFrame({"len(mm)": [1.0, 2.0], "width": [3.0, 4.0]})
    rule = ProcessingRule(column="*", operator="none", threshold=10.0, action="scale_by_factor", exclude_mode="none")
    result, _ = apply_rules(df, [rule])
    assert_true("len(mm)" in result.columns, "批量缩放时已有 (mm) 后缀不应重复拼接")
    assert_true("width(mm)" in result.columns, "批量缩放时普通列应补充 mm 后缀")
    assert_true("len(mm)(mm)" not in result.columns, "不应重复添加 (mm)")


def test_exclude_one_manual_column() -> None:
    df = pd.DataFrame(
        {
            "time": [100.0, 200.0, 300.0],
            "len": [1.0, 2.0, 3.0],
            "width": [4.0, 5.0, 6.0],
        }
    )
    rule = ProcessingRule(
        column="*",
        operator="none",
        threshold=10.0,
        action="scale_by_factor",
        exclude_mode="manual",
        exclude_columns=["time"],
    )
    result, logs = apply_rules(df, [rule])
    assert_true("time" in result.columns, "手动排除列 time 不应重命名")
    assert_true("len(mm)" in result.columns and "width(mm)" in result.columns, "其余数值列应缩放并加 mm 后缀")
    assert_true(result["time"].tolist() == [100.0, 200.0, 300.0], "手动排除列不应缩放数据")
    assert_true(abs(float(result["len(mm)"].iloc[0]) - 10.0) < EPS, "未排除列 len 未按因子缩放")
    assert_true(any("排除数值列 1 列：time" in log for log in logs), "日志应明确写出排除列")


def test_auto_exclude_datetime_column() -> None:
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "value": [1.0, 2.0, 3.0],
            "label": ["a", "b", "c"],
        }
    )
    rule = ProcessingRule(column="*", operator="none", threshold=10.0, action="scale_by_factor", exclude_mode="auto")
    result, logs = apply_rules(df, [rule])
    assert_true("ts" in result.columns, "自动识别的时间列应保留不缩放")
    assert_true("value(mm)" in result.columns, "数值列应缩放")
    assert_true(str(result["ts"].dtype).startswith("datetime64"), "时间列类型应保持 datetime")
    assert_true(any("自动跳过非数值列" in log and "ts" in log for log in logs), "日志应显示自动跳过时间列")


def test_auto_exclude_text_datetime_column() -> None:
    df = pd.DataFrame(
        {
            "record_time": ["2026-01-01 08:00:00", "2026-01-01 09:00:00", "2026-01-01 10:00:00"],
            "value": [1.0, 2.0, 3.0],
        }
    )
    rule = ProcessingRule(column="*", operator="none", threshold=10.0, action="scale_by_factor")
    result, logs = apply_rules(df, [rule])
    assert_true("record_time" in result.columns, "文本日期列应自动识别并不缩放")
    assert_true("value(mm)" in result.columns, "数值列应缩放为 mm")
    assert_true(any("record_time" in log for log in logs), "日志应体现自动识别的文本日期列")


def test_scale_uses_float32_multiplication_semantics() -> None:
    # 16777217 在 float32 中无法精确表示，乘接近 1 的因子时会和 float64 结果出现差异，
    # 以此验证缩放路径确实走了 float32 单精度乘法。
    large = 16777217.0
    df = pd.DataFrame({"x": [large]})
    rule1 = ProcessingRule(column="x", operator="none", threshold=1.0, action="scale_by_factor")
    result1, _ = apply_rules(df, [rule1])
    assert_true(abs(float(result1["x"].iloc[0]) - large) < EPS, "因子 1 不应触发缩放")

    rule2 = ProcessingRule(column="x", operator="none", threshold=1.0000002, action="scale_by_factor")
    result2, logs = apply_rules(df, [rule2])
    actual = float(result2["x(mm)"].iloc[0])
    expected_double = large * 1.0000002
    assert_true(abs(actual - expected_double) > 1e-9, "缩放应走 float32 单精度路径，不应直接保留 float64 结果")
    assert_true(any("float32 单精度语义" in log for log in logs), "日志应明确 float32 语义")


def test_skip_text_and_bool_columns() -> None:
    df = pd.DataFrame(
        {
            "name": ["a", "b", "c"],
            "ok": [True, False, True],
            "value": [1.0, 2.0, 3.0],
        }
    )
    rule = ProcessingRule(column="*", operator="none", threshold=10.0, action="scale_by_factor", exclude_mode="none")
    result, logs = apply_rules(df, [rule])
    assert_true(set(result.columns) == {"name", "ok", "value(mm)"}, "文本/布尔列应跳过，数值列应缩放")
    assert_true(result["name"].tolist() == ["a", "b", "c"], "文本列不应改动")
    assert_true(result["ok"].tolist() == [True, False, True], "布尔列不应改动")
    assert_true(
        any("自动跳过非数值列" in log and "name" in log and "ok" in log for log in logs),
        "日志应写出跳过的文本/布尔列",
    )


def test_manual_exclude_missing_column_is_ignored() -> None:
    df = pd.DataFrame({"value": [1.0, 2.0]})
    rule = ProcessingRule(
        column="*",
        operator="none",
        threshold=10.0,
        action="scale_by_factor",
        exclude_mode="manual",
        exclude_columns=["missing"],
    )
    result, logs = apply_rules(df, [rule])
    assert_true("value(mm)" in result.columns, "排除不存在列时仍应缩放实际数值列")
    assert_true(any("排除列不存在" in log for log in logs), "不存在排除列应记录日志")


# ---------------------------------------------------------------------------
# V1.7 按类别批量缩放（在不改动以上 14 个断言的前提下追加）
# ---------------------------------------------------------------------------

def _build_categorized_manager() -> DatasetManager:
    dm = DatasetManager()
    h1 = dm.import_file("h1", "h1.csv", pd.DataFrame({"时间": pd.to_datetime(["2026-01-01 00:00"]), "f": [10.0]}))
    h2 = dm.import_file("h2", "h2.csv", pd.DataFrame({"时间": pd.to_datetime(["2026-01-01 00:01"]), "f": [20.0], "tag": ["a"]}))
    t1 = dm.import_file("t1", "t1.csv", pd.DataFrame({"时间": pd.to_datetime(["2026-01-01 00:00"]), "f": [30.0]}))
    u1 = dm.import_file("u1", "u1.csv", pd.DataFrame({"时间": pd.to_datetime(["2026-01-01 00:00"]), "f": [40.0]}))
    h1.category = "head"
    h2.category = "head"
    t1.category = "tail"
    # u1 保持 category=None（未分类）
    return dm


def test_scale_by_category_head_only() -> None:
    dm = _build_categorized_manager()
    logs = scale_datasets_by_category(dm, "head", 0.1, exclude_mode="none")
    h1 = next(it for it in dm.items() if it.name == "h1")
    h2 = next(it for it in dm.items() if it.name == "h2")
    t1 = next(it for it in dm.items() if it.name == "t1")
    u1 = next(it for it in dm.items() if it.name == "u1")
    assert_true(h1.scaled is True, "head 数据集 h1 应被标记已缩放")
    assert_true(h2.scaled is True, "head 数据集 h2 应被标记已缩放")
    assert_true(abs(float(h1.df["f(mm)"].iloc[0]) - 1.0) < EPS, "head h1 应按 0.1 缩放")
    assert_true(abs(float(h2.df["f(mm)"].iloc[0]) - 2.0) < EPS, "head h2 应按 0.1 缩放")
    assert_true("tag" in h2.df.columns and "tag(mm)" not in h2.df.columns, "文本列不应被缩放")
    assert_true(t1.scaled is False, "tail 不应被误缩放")
    assert_true(u1.scaled is False, "未分类不应被误缩放")
    assert_true("f" in t1.df.columns and "f(mm)" not in t1.df.columns, "tail 数值列不应被改名")
    assert_true(any("机头" in log for log in logs), "日志应标明类别为机头")


def test_scale_by_category_tail_with_different_factor() -> None:
    dm = _build_categorized_manager()
    scale_datasets_by_category(dm, "head", 0.1, exclude_mode="none")
    scale_datasets_by_category(dm, "tail", 0.5, exclude_mode="none")
    t1 = next(it for it in dm.items() if it.name == "t1")
    u1 = next(it for it in dm.items() if it.name == "u1")
    assert_true(t1.scaled is True, "tail 应被标记已缩放")
    assert_true(abs(float(t1.df["f(mm)"].iloc[0]) - 15.0) < EPS, "tail 应按 0.5 缩放")
    assert_true(u1.scaled is False, "未分类仍然不应被误缩放")
    assert_true("f" in u1.df.columns, "未分类 f 不应被改名")
    assert_true(abs(float(u1.df["f"].iloc[0]) - 40.0) < EPS, "未分类 f 数值不应变化")


def test_scale_by_category_skips_already_scaled() -> None:
    dm = _build_categorized_manager()
    scale_datasets_by_category(dm, "head", 0.1, exclude_mode="none")
    h1 = next(it for it in dm.items() if it.name == "h1")
    assert_true(abs(float(h1.df["f(mm)"].iloc[0]) - 1.0) < EPS, "首次缩放后 h1 值应为 1.0")
    logs2 = scale_datasets_by_category(dm, "head", 0.1, exclude_mode="none")
    assert_true(any("已完成过缩放" in log for log in logs2), "二次缩放应输出跳过日志")
    assert_true(abs(float(h1.df["f(mm)"].iloc[0]) - 1.0) < EPS, "已 scaled=True 的数据集不重复乘")


def test_scale_by_category_invalid_factor_does_not_modify() -> None:
    dm = _build_categorized_manager()
    for bad in (-1.0, 0.0, float("inf"), float("nan"), "abc"):
        logs = scale_datasets_by_category(dm, "head", bad, exclude_mode="none")  # type: ignore[arg-type]
        assert_true(any("缩放因子" in log and "跳过" in log for log in logs), f"非法因子 {bad!r} 应给出跳过日志")
    for name in ("h1", "h2"):
        it = next(it_ for it_ in dm.items() if it_.name == name)
        assert_true(it.scaled is False, f"非法因子不应修改 {name} 的 scaled 标志")
        assert_true("f" in it.df.columns and "f(mm)" not in it.df.columns, f"非法因子不应修改 {name} 列名")
        assert_true(abs(float(it.df["f"].iloc[0]) - (10.0 if name == "h1" else 20.0)) < EPS, f"非法因子不应修改 {name} 数据")


def test_scale_by_category_existing_mm_suffix_not_duplicated_and_scaled_flag_set() -> None:
    dm = DatasetManager()
    item = dm.import_file("mm", "mm.csv", pd.DataFrame({"len(mm)": [1.0, 2.0], "w": [3.0, 4.0]}))
    item.category = "head"
    scale_datasets_by_category(dm, "head", 10.0, exclude_mode="none")
    assert_true("len(mm)" in item.df.columns, "批量按类别缩放时已有 (mm) 后缀列不应重复拼接")
    assert_true("w(mm)" in item.df.columns, "普通数值列应加 (mm) 后缀")
    assert_true(item.scaled is True, "缩放完成后应标记 scaled")
    assert_true(abs(float(item.df["len(mm)"].iloc[0]) - 10.0) < EPS, "(mm) 列仍应按因子缩放")


def main() -> int:
    tests = [
        test_single_column_scale,
        test_factor_point_five,
        test_factor_one_skip,
        test_factor_negative_invalid,
        test_factor_non_finite_invalid,
        test_all_numeric_columns_auto_skip_datetime_text_bool,
        test_existing_mm_suffix_not_duplicated,
        test_existing_mm_suffix_not_duplicated_all_columns,
        test_exclude_one_manual_column,
        test_auto_exclude_datetime_column,
        test_auto_exclude_text_datetime_column,
        test_scale_uses_float32_multiplication_semantics,
        test_skip_text_and_bool_columns,
        test_manual_exclude_missing_column_is_ignored,
        test_scale_by_category_head_only,
        test_scale_by_category_tail_with_different_factor,
        test_scale_by_category_skips_already_scaled,
        test_scale_by_category_invalid_factor_does_not_modify,
        test_scale_by_category_existing_mm_suffix_not_duplicated_and_scaled_flag_set,
    ]
    for fn in tests:
        fn()
        print(f"[PASS] {fn.__name__}")
    print("VERIFY_SCALE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
