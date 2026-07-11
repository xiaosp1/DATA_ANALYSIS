# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
_OLD_ROOT = Path(r"E:\DEMO\DateAnalysis")
# test_descriptive_service 会往 sys.path 里插入旧目录，导致后续同进程 import 拿到旧包。
# 这里强制把新工作目录置顶，并把旧目录移到末尾，确保 app.* 解析到新源码。
if str(_OLD_ROOT) in sys.path:
    sys.path.remove(str(_OLD_ROOT))
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))
sys.path.append(str(_OLD_ROOT))

# 清掉可能已被旧目录加载的 app.* 模块，强制使用新目录源码
for _mod_name in list(sys.modules.keys()):
    if _mod_name == "app" or _mod_name.startswith("app."):
        del sys.modules[_mod_name]

from app.services.dataset_manager import DatasetManager
from app.services.data_processing import scale_datasets_by_category


def _make_df(times, **cols) -> pd.DataFrame:
    data = {"时间": pd.to_datetime(times)}
    data.update(cols)
    return pd.DataFrame(data)


def _import(manager: DatasetManager, name: str, df: pd.DataFrame, category: str | None, factor: float | None = None) -> None:
    item = manager.import_file(name, f"{name}.csv", df)
    item.category = category
    item.pixel_factor = factor


# ---------------------------------------------------------------------------
# a) 同类别多个文件 concat + 排序（回归旧行为）
# ---------------------------------------------------------------------------
def test_same_category_concat_and_sort() -> None:
    dm = DatasetManager()
    df1 = _make_df(["2026-01-01 00:02:00", "2026-01-01 00:01:00"], force=[2.0, 1.0])
    df2 = _make_df(["2026-01-01 00:03:00", "2026-01-01 00:00:30"], force=[3.0, 0.5])
    _import(dm, "h1", df1, "head")
    _import(dm, "h2", df2, "head")
    merged = dm.merge_by_category("head")
    assert merged.name == "机头_合并"
    assert list(merged.df["时间"]) == sorted(merged.df["时间"].tolist())
    assert merged.df["force"].tolist() == [0.5, 1.0, 2.0, 3.0]
    assert len(merged.df) == 4


# ---------------------------------------------------------------------------
# b) 跨类 outer join：时间重叠/先后/单侧缺失 NaN
# ---------------------------------------------------------------------------
def test_cross_category_outer_join_overlap_and_nan() -> None:
    dm = DatasetManager()
    head = _make_df(
        ["2026-01-01 00:00", "2026-01-01 00:01", "2026-01-01 00:02"],
        脱模力=[10.0, 11.0, 12.0],
    )
    tail = _make_df(
        ["2026-01-01 00:01", "2026-01-01 00:02", "2026-01-01 00:03"],
        顶出力=[20.0, 21.0, 22.0],
    )
    _import(dm, "h", head, "head")
    _import(dm, "t", tail, "tail")

    cross = dm.merge_cross_category()
    assert cross.name == "机头+机尾_跨类合并"
    assert len(cross.df) == 4  # outer: 00,01,02,03
    times = cross.df["时间"].tolist()
    assert times == sorted(times)

    # 00:00 只有机头
    row0 = cross.df.iloc[0]
    assert float(row0["[机头]脱模力"]) == 10.0
    assert pd.isna(row0["[机尾]顶出力"])
    # 00:03 只有机尾
    row3 = cross.df.iloc[3]
    assert pd.isna(row3["[机头]脱模力"])
    assert float(row3["[机尾]顶出力"]) == 22.0
    # 00:01 都有
    row1 = cross.df.iloc[1]
    assert float(row1["[机头]脱模力"]) == 11.0
    assert float(row1["[机尾]顶出力"]) == 20.0


# ---------------------------------------------------------------------------
# c) 列名前缀 '[机头]'/'[机尾]' 正确加在 (mm) 之前
# ---------------------------------------------------------------------------
def test_prefix_mm_suffix_position() -> None:
    dm = DatasetManager()
    head = _make_df(["2026-01-01 00:00"], **{"脱模力(mm)": [10.0], "速度": [5.0]})
    tail = _make_df(["2026-01-01 00:00"], **{"位移(mm)": [3.0]})
    _import(dm, "h", head, "head")
    _import(dm, "t", tail, "tail")
    cross = dm.merge_cross_category()
    cols = set(cross.df.columns)
    assert "[机头]脱模力(mm)" in cols
    assert "[机头]速度" in cols
    assert "[机尾]位移(mm)" in cols
    # 前缀不应出现在 (mm) 后面
    for c in cols:
        if c == "时间":
            continue
        assert "(mm)[机头]" not in c and "(mm)[机尾]" not in c


# ---------------------------------------------------------------------------
# d) 重名去重（两侧前缀后如果出现重名，追加 _1/_2）
# ---------------------------------------------------------------------------
def test_duplicate_column_after_prefix_gets_deduped() -> None:
    dm = DatasetManager()
    # 场景：机尾原始数据里同时存在 顶出力 和 [机尾]顶出力（异常列名），前缀化后会重名。
    head = _make_df(["2026-01-01 00:00"], 脱模力=[10.0])
    tail = _make_df(["2026-01-01 00:00"], **{"顶出力": [20.0], "[机尾]顶出力": [99.0]})
    _import(dm, "h", head, "head")
    _import(dm, "t", tail, "tail")
    cross = dm.merge_cross_category()
    cols = list(cross.df.columns)
    # 其中一个会保留 [机尾]顶出力，另一个需要 _1 去重
    assert "[机头]脱模力" in cols
    assert "[机尾]顶出力" in cols
    assert any(c.startswith("[机尾]顶出力_") for c in cols), f"重名应加 _1/_2 去重，实际列：{cols}"


# ---------------------------------------------------------------------------
# e) 时间列缺失抛出明确异常，并指出文件名
# ---------------------------------------------------------------------------
def test_missing_time_column_raises_clear_error() -> None:
    dm = DatasetManager()
    bad = pd.DataFrame({"force": [1.0, 2.0]})
    good = _make_df(["2026-01-01 00:00"], v=[1.0])
    _import(dm, "bad_file", bad, "head")
    _import(dm, "good_file", good, "tail")
    with pytest.raises(ValueError) as excinfo:
        dm.merge_cross_category()
    msg = str(excinfo.value)
    assert "时间" in msg
    assert "bad_file" in msg


# ---------------------------------------------------------------------------
# f) 未分类路径（category=None）与 V1.6.1 行为一致：concat + 时间排序
# ---------------------------------------------------------------------------
def test_uncategorized_path_equivalent_to_legacy_concat_sort() -> None:
    dm = DatasetManager()
    df1 = _make_df(["2026-01-01 00:02", "2026-01-01 00:01"], a=[2.0, 1.0])
    df2 = _make_df(["2026-01-01 00:03", "2026-01-01 00:00"], a=[3.0, 0.0])
    # 未分类导入：不设置 category（保持 None）
    i1 = dm.import_file("u1", "u1.csv", df1)
    i2 = dm.import_file("u2", "u2.csv", df2)
    assert i1.category is None
    assert i2.category is None

    # 旧逻辑（merge_by_time_column）
    legacy = dm.merge_by_time_column([i1.dataset_id, i2.dataset_id], "时间")
    legacy_vals = legacy.df["a"].tolist()
    legacy_times = legacy.df["时间"].tolist()

    # 新未分类入口
    uncat = dm.merge_uncategorized()
    assert uncat.df["a"].tolist() == legacy_vals
    assert list(uncat.df["时间"]) == list(legacy_times)
    assert legacy_times == sorted(legacy_times)


# ---------------------------------------------------------------------------
# 附加：merge_by_category 对已存在的同名临时数据集直接返回（不重复生成）
# ---------------------------------------------------------------------------
def test_merge_by_category_returns_existing_temporary() -> None:
    dm = DatasetManager()
    _import(dm, "h1", _make_df(["2026-01-01 00:00"], v=[1.0]), "head")
    first = dm.merge_by_category("head")
    second = dm.merge_by_category("head")
    assert first.dataset_id == second.dataset_id


# ---------------------------------------------------------------------------
# 按类别批量缩放（与 scale_feature 增补一起覆盖，这里做跨类协同）
# ---------------------------------------------------------------------------
def test_scale_by_category_skips_already_scaled_and_other_categories() -> None:
    dm = DatasetManager()
    _import(dm, "h1", _make_df(["2026-01-01 00:00"], f=[10.0], t=[1.0]), "head")
    _import(dm, "h2", _make_df(["2026-01-01 00:01"], f=[20.0]), "head")
    _import(dm, "t1", _make_df(["2026-01-01 00:00"], f=[30.0]), "tail")
    _import(dm, "u1", _make_df(["2026-01-01 00:00"], f=[40.0]), None)

    # head 用因子 0.1
    logs = scale_datasets_by_category(dm, "head", 0.1, exclude_mode="none")
    assert any("机头" in l for l in logs)
    head_items = [it for it in dm.items() if it.category == "head" and it.kind == "original"]
    for h in head_items:
        assert h.scaled is True
        assert h.pixel_factor == 0.1
        # 数值列 f 已加 (mm) 后缀
        assert "f(mm)" in h.df.columns
    tail_item = next(it for it in dm.items() if it.name == "t1")
    uncat_item = next(it for it in dm.items() if it.name == "u1")
    # 非 head 的没被缩放
    assert tail_item.scaled is False
    assert uncat_item.scaled is False
    assert "f" in tail_item.df.columns and "f(mm)" not in tail_item.df.columns
    assert "f" in uncat_item.df.columns and "f(mm)" not in uncat_item.df.columns

    # 再对 head 缩放一次应被跳过
    logs2 = scale_datasets_by_category(dm, "head", 0.1, exclude_mode="none")
    assert any("已完成过缩放" in l for l in logs2)
    # 数值没有再次乘 0.1（h1 f(mm) 原值是 1.0，再乘就会变成 0.1）
    h1 = next(it for it in dm.items() if it.name == "h1")
    assert abs(float(h1.df["f(mm)"].iloc[0]) - 1.0) < 1e-6

    # tail 用不同 factor 0.5
    scale_datasets_by_category(dm, "tail", 0.5, exclude_mode="none")
    assert tail_item.scaled is True
    assert abs(float(tail_item.df["f(mm)"].iloc[0]) - 15.0) < 1e-6


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception:
            failed += 1
            print(f"[FAIL] {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(0 if failed == 0 else 1)
