"""W6：按类别默认排除列（机尾的 未脱模-s / 指数-s 不应被 factor 乘）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.data_processing import scale_datasets_by_category
from app.services.dataset_manager import DatasetManager

EPS = 1e-6


def _make_tail_manager() -> DatasetManager:
    dm = DatasetManager()
    # 模拟机尾数据：像素列 a（数值），以及数值但非像素的 未脱模-s / 指数-s
    df = pd.DataFrame(
        {
            "时间": [1.0, 2.0, 3.0],   # 数值时间，auto 模式下会被识别为非日期（仅3点），这里用 explicit exclude 测试
            "a": [10.0, 20.0, 30.0],
            "未脱模-s": [100.0, 200.0, 300.0],
            "指数-s": [1.5, 2.5, 3.5],
        }
    )
    item = dm.import_file("tail1.csv", "tail1.csv", df)
    item.category = "tail"
    return dm


def test_tail_default_exclude_columns_not_scaled() -> None:
    """机尾默认排除列 "未脱模-s"、"指数-s" 传入 exclude_columns 后不应被乘 factor。"""
    dm = _make_tail_manager()
    factor = 0.1
    logs = scale_datasets_by_category(
        dm,
        "tail",
        factor,
        exclude_mode="auto",
        exclude_columns=["未脱模-s", "指数-s"],
    )
    item = next(it for it in dm.items() if it.name == "tail1.csv")
    assert item.scaled is True

    # 普通数值列 a 应被缩放并改名 (mm)
    assert "a(mm)" in item.df.columns, "普通数值列 a 应被缩放并加 (mm) 后缀"
    assert abs(float(item.df["a(mm)"].iloc[0]) - 1.0) < EPS, "a 应被 factor 乘"

    # 默认排除列：未脱模-s / 指数-s 不应被乘，也不加 (mm)
    assert "未脱模-s" in item.df.columns, "未脱模-s 不应被重命名"
    assert "未脱模-s(mm)" not in item.df.columns
    assert abs(float(item.df["未脱模-s"].iloc[0]) - 100.0) < EPS, "未脱模-s 不应被乘 factor"

    assert "指数-s" in item.df.columns, "指数-s 不应被重命名"
    assert "指数-s(mm)" not in item.df.columns
    assert abs(float(item.df["指数-s"].iloc[0]) - 1.5) < EPS, "指数-s 不应被乘 factor"

    assert any("排除数值列" in log for log in logs), "日志应提示排除数值列"


def test_parse_exclude_columns_helper_preserves_order_and_dedup() -> None:
    """MainWindow._parse_exclude_columns：split+strip+去空+保序去重。"""
    from app.ui.main_window import MainWindow  # noqa: WPS433
    raw = " 时间 , 未脱模-s , , 指数-s , 未脱模-s "
    parsed = MainWindow._parse_exclude_columns(raw)
    assert parsed == ["时间", "未脱模-s", "指数-s"]
    assert MainWindow._parse_exclude_columns("") == []
    assert MainWindow._parse_exclude_columns(None) == []
