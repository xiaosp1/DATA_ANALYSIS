"""W6：Y 轴归一化显示（仅作用于绘图 chart_df 副本，不修改原始数据）。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def test_normalize_helper_two_scales_both_in_01() -> None:
    """两个量级差异巨大的序列归一化后都在 [0,1]，且每列 min=0、max=1。"""
    from app.ui.main_window import MainWindow

    df = pd.DataFrame(
        {
            "x": [1, 2, 3, 4, 5],
            "big": [1e6, 2e6, 3e6, 4e6, 5e6],
            "small": [0.1, 0.2, 0.3, 0.4, 0.5],
        }
    )
    out, mean_map = MainWindow._normalize_chart_df_01(df, ["big", "small"])

    # 不能修改原 df
    assert float(df["big"].iloc[0]) == 1e6
    assert float(df["small"].iloc[-1]) == 0.5

    for col in ("big", "small"):
        s = out[col].astype(float)
        assert float(s.min()) == 0.0
        assert abs(float(s.max()) - 1.0) < 1e-9
        assert ((s >= -1e-9) & (s <= 1.0 + 1e-9)).all()
        m = float(s.mean())
        assert abs(mean_map[col] - m) < 1e-9


def test_normalize_helper_constant_column_is_zero() -> None:
    """常数列（max-min==0）归一化后整列 0.0，不出 NaN/Inf。"""
    from app.ui.main_window import MainWindow

    df = pd.DataFrame(
        {
            "x": [1, 2, 3],
            "const": [7.0, 7.0, 7.0],
        }
    )
    out, mean_map = MainWindow._normalize_chart_df_01(df, ["const"])
    col = out["const"].astype(float)
    assert (col == 0.0).all()
    assert not col.isna().any()
    assert np.isfinite(col).all()
    assert mean_map["const"] == 0.0
