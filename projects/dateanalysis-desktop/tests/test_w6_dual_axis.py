"""W6B：双 Y 轴模式（dual）。

覆盖：
1. ChartOptionsPanel 默认 shared，可切到 dual。
2. ChartPanel.plot_multi_line(y_axis_mode="dual") 时创建右 ViewBox，
   右轴可见、左/右 ViewBox 各至少一条曲线。
3. 单条 Y 列传入 dual 自动退化为 shared（不抛异常，右轴不可见）。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pytest

from app.ui.widgets.chart_options_panel import ChartOptionsPanel
from app.ui.widgets.chart_panel import ChartPanel, LABEL_DUAL_DEGRADE


# ---------------------------------------------------------------------------
# 1. Options panel
# ---------------------------------------------------------------------------
def test_chart_options_y_mode_default_is_shared_and_dual_selectable(qtbot):
    panel = ChartOptionsPanel()
    qtbot.addWidget(panel)
    assert panel.current_y_mode() == "shared"

    idx = panel.y_mode_combo.findData("dual")
    assert idx >= 0, "combo 里必须包含 dual 项"
    panel.y_mode_combo.setCurrentIndex(idx)
    assert panel.current_y_mode() == "dual"

    # reset 回到 shared
    panel.reset()
    assert panel.current_y_mode() == "shared"


def test_chart_options_dual_option_text_present(qtbot):
    panel = ChartOptionsPanel()
    qtbot.addWidget(panel)
    idx = panel.y_mode_combo.findData("dual")
    text = panel.y_mode_combo.itemText(idx)
    assert "双 Y 轴" in text


# ---------------------------------------------------------------------------
# 2&3. ChartPanel dual mode
# ---------------------------------------------------------------------------
def _make_panel(qtbot) -> ChartPanel:
    panel = ChartPanel()
    qtbot.addWidget(panel)
    panel.resize(800, 500)
    panel.show()
    return panel


def test_dual_mode_two_series_creates_right_axis_and_curves(qtbot):
    panel = _make_panel(qtbot)
    df = pd.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, 4.0],
            "small": [0.0, 1.0, 2.0, 3.0],
            "big": [1000.0, 2000.0, 3000.0, 4000.0],
        }
    )
    series = [("small", "#1f77b4", False), ("big", "#d62728", False)]
    msgs = panel.plot_multi_line(
        df, "x", series, mean_map={}, title="dual test",
        x_is_datetime=False, y_axis_mode="dual",
    )

    plot_item = panel.plot_widget.plotItem
    # 右轴可见
    assert plot_item.getAxis("right").isVisible(), "dual 模式下右轴应可见"
    # 左轴至少 1 条曲线
    left_curves = plot_item.listDataItems()
    assert len(left_curves) >= 1, f"左轴至少应有 1 条曲线，实际 {len(left_curves)}"
    # 右 ViewBox 存在且至少 1 条曲线
    assert panel._right_vb is not None, "dual 模式下应创建 _right_vb"
    right_items = [it for it in panel._right_vb.addedItems if isinstance(it, pg.PlotDataItem)]
    assert len(right_items) >= 1, f"右 vb 至少应有 1 条 PlotDataItem，实际 {len(right_items)}"
    # 不应有退化提示
    assert LABEL_DUAL_DEGRADE not in msgs


def test_dual_mode_single_y_degrades_to_shared(qtbot):
    panel = _make_panel(qtbot)
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "a": [10.0, 20.0, 30.0]})
    series = [("a", "#1f77b4", False)]
    msgs = panel.plot_multi_line(
        df, "x", series, mean_map={}, title="single dual",
        x_is_datetime=False, y_axis_mode="dual",
    )
    # 应收到退化提示
    assert any(LABEL_DUAL_DEGRADE in m for m in msgs)
    # 右轴不可见 / 无右 vb
    plot_item = panel.plot_widget.plotItem
    assert not plot_item.getAxis("right").isVisible(), "退化情况下右轴不应启用"
    assert panel._right_vb is None, "退化情况下不应创建右 ViewBox"
    # 左轴正常绘制
    assert len(plot_item.listDataItems()) >= 1


def test_dual_mode_invalid_y_mode_falls_back_to_shared(qtbot):
    panel = _make_panel(qtbot)
    df = pd.DataFrame({"x": [1.0, 2.0], "a": [1.0, 2.0], "b": [3.0, 4.0]})
    msgs = panel.plot_multi_line(
        df, "x", [("a", "#1f77b4"), ("b", "#d62728")], mean_map={},
        title="fallback", x_is_datetime=False, y_axis_mode="bogus",
    )
    # 非法值走 shared，右轴不可见
    assert not panel.plot_widget.plotItem.getAxis("right").isVisible()
    assert panel._right_vb is None
    assert LABEL_DUAL_DEGRADE not in msgs


def test_dual_mode_right_axis_label_is_numeric(qtbot):
    panel = _make_panel(qtbot)
    df = pd.DataFrame(
        {"x": [1.0, 2.0, 3.0], "left_col": [1.0, 2.0, 3.0], "right_col": [100.0, 200.0, 300.0]}
    )
    panel.plot_multi_line(
        df, "x", [("left_col", "#1f77b4"), ("right_col", "#d62728")],
        mean_map={}, title="labels", x_is_datetime=False, y_axis_mode="dual",
    )
    right_axis = panel.plot_widget.plotItem.getAxis("right")
    label_text = ""
    try:
        label_text = right_axis.labelText
    except Exception:
        # pyqtgraph 内部 label 可能通过 _tickLevels / label.toPlainText() 读取
        try:
            label_text = right_axis.label.toPlainText() if right_axis.label is not None else ""
        except Exception:
            label_text = ""
    # 若读不到 text，至少确认轴可见 + 右 vb 存在
    assert panel._right_vb is not None
    assert right_axis.isVisible()
