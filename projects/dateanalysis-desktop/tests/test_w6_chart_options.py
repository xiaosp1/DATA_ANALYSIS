"""W6：ChartOptionsPanel Y 轴模式默认 shared，可切换到 normalized。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.ui.widgets.chart_options_panel import ChartOptionsPanel  # noqa: E402


def test_chart_options_y_mode_default_and_switch(qtbot):
    panel = ChartOptionsPanel()
    qtbot.addWidget(panel)
    assert panel.current_y_mode() == "shared", "默认应为 shared（共用 Y 轴原始值）"

    # 切换到归一化
    idx = panel.y_mode_combo.findData("normalized")
    assert idx >= 0
    panel.y_mode_combo.setCurrentIndex(idx)
    assert panel.current_y_mode() == "normalized"

    # reset 回到 shared
    panel.reset()
    assert panel.current_y_mode() == "shared"


def test_chart_options_y_mode_changed_signal_emits(qtbot):
    panel = ChartOptionsPanel()
    qtbot.addWidget(panel)
    received = []
    panel.y_mode_changed.connect(received.append)
    idx = panel.y_mode_combo.findData("normalized")
    panel.y_mode_combo.setCurrentIndex(idx)
    assert received == ["normalized"]
