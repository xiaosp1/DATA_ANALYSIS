"""W7：小多图（Small Multiples）模式。

覆盖：
1. ChartOptionsPanel 能切到 "small_multiples"，current_y_mode()=="small_multiples"。
2. ChartPanel.plot_multi_line(y_axis_mode="small_multiples")：
   - _sm_widget 可见，plot_widget 隐藏；
   - 子图数量 == 选了几条 Y 列；
   - 每个子图上至少有 1 条 PlotDataItem。
3. 单条 Y 列 small_multiples 不崩溃（1 个子图）。
4. shared 模式下 _sm_widget 不可见、plot_widget 可见（回归）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pytest

from app.ui.widgets.chart_options_panel import ChartOptionsPanel
from app.ui.widgets.chart_panel import (
    ChartPanel,
    LABEL_SM_MODE_LOG,
)


def _make_panel(qtbot) -> ChartPanel:
    panel = ChartPanel()
    qtbot.addWidget(panel)
    panel.resize(800, 600)
    panel.show()
    return panel


# ---------------------------------------------------------------------------
# 1. Options panel
# ---------------------------------------------------------------------------
def test_chart_options_small_multiples_selectable(qtbot):
    panel = ChartOptionsPanel()
    qtbot.addWidget(panel)
    idx = panel.y_mode_combo.findData("small_multiples")
    assert idx >= 0, "combo 里必须包含 small_multiples 项"
    panel.y_mode_combo.setCurrentIndex(idx)
    assert panel.current_y_mode() == "small_multiples"
    text = panel.y_mode_combo.itemText(idx)
    assert "小多图" in text or "独立子图" in text
    panel.reset()
    assert panel.current_y_mode() == "shared"


def test_chart_options_small_multiples_signal(qtbot):
    panel = ChartOptionsPanel()
    qtbot.addWidget(panel)
    received = []
    panel.y_mode_changed.connect(received.append)
    idx = panel.y_mode_combo.findData("small_multiples")
    panel.y_mode_combo.setCurrentIndex(idx)
    assert "small_multiples" in received


# ---------------------------------------------------------------------------
# 2. Two series -> two subplots
# ---------------------------------------------------------------------------
def test_small_multiples_two_series_two_subplots(qtbot):
    panel = _make_panel(qtbot)
    n = 50
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    df = pd.DataFrame(
        {
            "t": dates,
            "small": np.sin(np.linspace(0, 6.28, n)),
            "big": np.linspace(1000, 5000, n) + np.random.default_rng(0).normal(0, 50, n),
        }
    )
    series = [("small", "#1f77b4", False), ("big", "#d62728", False)]
    msgs = panel.plot_multi_line(
        df, "t", series, mean_map={}, title="sm test",
        x_is_datetime=True, granularity="原始", y_axis_mode="small_multiples",
    )
    # _sm_widget 可见，plot_widget 被隐藏
    assert panel._sm_widget.isVisible(), "small_multiples 下 _sm_widget 应可见"
    assert not panel.plot_widget.isVisible(), "small_multiples 下 plot_widget 应隐藏"
    assert len(panel._sm_plots) == 2, f"应有 2 个子图，实际 {len(panel._sm_plots)}"
    for p in panel._sm_plots:
        assert isinstance(p, pg.PlotItem)
        dis = p.listDataItems()
        assert len(dis) >= 1, "每个子图至少 1 条 PlotDataItem"


# ---------------------------------------------------------------------------
# 3. Single Y -> 1 subplot, no crash
# ---------------------------------------------------------------------------
def test_small_multiples_single_y_one_subplot(qtbot):
    panel = _make_panel(qtbot)
    df = pd.DataFrame(
        {"t": pd.date_range("2024-01-01", periods=10, freq="h"),
         "a": np.arange(10, dtype=float)}
    )
    msgs = panel.plot_multi_line(
        df, "t", [("a", "#1f77b4", True)], mean_map={"a": 4.5}, title="single sm",
        x_is_datetime=True, granularity="原始", y_axis_mode="small_multiples",
        show_mean_lines=True,
    )
    assert panel._sm_widget.isVisible()
    assert len(panel._sm_plots) == 1
    assert len(panel._sm_plots[0].listDataItems()) == 1
    # 均值虚线存在
    mean_lines = [it for it in panel._sm_plots[0].items if isinstance(it, pg.InfiniteLine)
                  and it.angle == 0]
    assert len(mean_lines) >= 1, "单图应至少有一条水平均值虚线"


# ---------------------------------------------------------------------------
# 4. Shared mode regression: sm_widget hidden, plot_widget visible
# ---------------------------------------------------------------------------
def test_small_multiples_does_not_leak_into_shared_mode(qtbot):
    panel = _make_panel(qtbot)
    # 先切到 small_multiples
    df = pd.DataFrame(
        {"t": pd.date_range("2024-01-01", periods=5, freq="h"),
         "a": [1.0, 2.0, 3.0, 4.0, 5.0],
         "b": [10.0, 20.0, 30.0, 40.0, 50.0]}
    )
    panel.plot_multi_line(
        df, "t", [("a", "#1f77b4"), ("b", "#d62728")], mean_map={},
        title="sm", x_is_datetime=True, granularity="原始", y_axis_mode="small_multiples",
    )
    assert panel._sm_widget.isVisible()
    assert not panel.plot_widget.isVisible()
    # 再切回 shared（clear 会复位）
    panel.plot_multi_line(
        df, "t", [("a", "#1f77b4"), ("b", "#d62728")], mean_map={},
        title="shared", x_is_datetime=True, granularity="原始", y_axis_mode="shared",
    )
    assert not panel._sm_widget.isVisible(), "shared 模式下 _sm_widget 应隐藏"
    assert panel.plot_widget.isVisible(), "shared 模式下 plot_widget 应可见"
    assert len(panel._sm_plots) == 0, "shared 模式下不应残留小多图子图"


# ---------------------------------------------------------------------------
# 5. Non-datetime (category) X axis in small_multiples
# ---------------------------------------------------------------------------
def test_small_multiples_category_x_axis(qtbot):
    panel = _make_panel(qtbot)
    df = pd.DataFrame({
        "cat": ["A", "B", "C", "D"],
        "x1": [1.0, 2.0, 3.0, 4.0],
        "x2": [100.0, 200.0, 300.0, 400.0],
        "x3": [0.1, 0.2, 0.3, 0.4],
    })
    panel.plot_multi_line(
        df, "cat",
        [("x1", "#1f77b4"), ("x2", "#d62728"), ("x3", "#2ca02c")],
        mean_map={}, title="cat sm",
        x_is_datetime=False, y_axis_mode="small_multiples",
    )
    assert panel._sm_widget.isVisible()
    assert len(panel._sm_plots) == 3
    for p in panel._sm_plots:
        assert len(p.listDataItems()) == 1


# ---------------------------------------------------------------------------
# 6. W7B：current_export_widget / has_plotted_data 随模式切换正确
# ---------------------------------------------------------------------------
def test_current_export_widget_switches_for_small_multiples(qtbot):
    panel = _make_panel(qtbot)
    n = 20
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    df = pd.DataFrame(
        {
            "t": dates,
            "a": np.sin(np.linspace(0, 6.28, n)),
            "b": np.linspace(0, 10, n),
        }
    )
    # 初始态：无数据
    assert not panel.has_plotted_data(), "clear 状态下不应有数据"

    # small_multiples：两条序列 -> 导出 _sm_widget，has_plotted_data=True
    panel.plot_multi_line(
        df, "t", [("a", "#1f77b4"), ("b", "#d62728")], mean_map={},
        title="sm", x_is_datetime=True, granularity="原始", y_axis_mode="small_multiples",
    )
    assert panel.current_export_widget() is panel._sm_widget
    assert panel.has_plotted_data()

    # clear 后恢复无数据
    panel.clear()
    assert not panel.has_plotted_data(), "clear 后 has_plotted_data 应为 False"
    # 清空调制模式时应回落到 plot_widget
    assert panel.current_export_widget() is panel.plot_widget

    # shared 模式：导出 plot_widget，has_plotted_data=True
    panel.plot_multi_line(
        df, "t", [("a", "#1f77b4"), ("b", "#d62728")], mean_map={},
        title="shared", x_is_datetime=True, granularity="原始", y_axis_mode="shared",
    )
    assert panel.current_export_widget() is panel.plot_widget
    assert panel.has_plotted_data()
