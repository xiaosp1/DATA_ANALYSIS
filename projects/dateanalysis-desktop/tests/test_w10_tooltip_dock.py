"""W10: 右 Dock 宽度适配 + 图表悬停 tooltip 单测（offscreen）。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    # 测试隔离 organization/application，避免污染用户真实 QSettings
    QApplication.setOrganizationName("TestDateAnalysis_W10")
    QApplication.setApplicationName("TestDateAnalysis_W10")
    yield _app


@pytest.fixture()
def win(app, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    s = QSettings()
    s.clear()
    s.sync()
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    QApplication.processEvents()
    yield w
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    s = QSettings()
    s.clear()
    s.sync()


# ---------------------------------------------------------------------------
# Dock widths
# ---------------------------------------------------------------------------

def test_dock_minimum_widths(win):
    assert win.left_dock.minimumWidth() == 340
    assert win.right_dock.minimumWidth() == 400

    # 强制把 right_dock 缩到 400（最小宽度），所有 info tab widget 仍可见
    win.resizeDocks([win.left_dock, win.right_dock], [400, 400], win.width().__class__ and __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Orientation.Horizontal)
    from PySide6.QtCore import Qt
    win.resizeDocks([win.right_dock], [400], Qt.Orientation.Horizontal)
    QApplication.processEvents()
    assert win.right_dock.width() >= 400

    for i in range(win.info_tabs.count()):
        assert win.info_tabs.widget(i) is not None
        # 切到每个 tab，widget 都 show 出来 visible
        win.info_tabs.setCurrentIndex(i)
        QApplication.processEvents()

    win.info_tabs.setCurrentIndex(3)
    QApplication.processEvents()
    p = win.process_analysis_panel
    assert p.isVisible()
    assert p.analyze_btn.isVisible()
    assert p.analyze_btn.width() > 40, f"analyze_btn 宽度 {p.analyze_btn.width()} 应 >40"
    assert p.export_btn.isVisible()
    assert p.export_btn.width() > 40


def test_ai_toolbar_fits_in_dock(win):
    from PySide6.QtCore import Qt
    win.resizeDocks([win.right_dock], [400], Qt.Orientation.Horizontal)
    QApplication.processEvents()
    win.info_tabs.setCurrentIndex(3)
    QApplication.processEvents()
    p = win.process_analysis_panel
    # 切到 AI 解读 tab，AI 工具栏才可见
    ai_idx = p.result_tabs.indexOf(p.ai_tab)
    assert ai_idx >= 0
    p.result_tabs.setCurrentIndex(ai_idx)
    QApplication.processEvents()
    widgets = [
        p.ai_provider_combo,
        p.ai_model_edit,
        p.ai_base_url_edit,
        p.ai_set_key_btn,
        p.ai_generate_btn,
        p.ai_regenerate_btn,
    ]
    for w in widgets:
        w.show()
        assert w.isVisibleTo(p), f"{w.__class__.__name__} 必须在面板内可见"
    # 按钮不能被挤成 0 宽或极小宽度
    for btn in (p.ai_generate_btn, p.ai_regenerate_btn, p.ai_set_key_btn):
        w = btn.width() or btn.sizeHint().width()
        assert w >= 40, f"{btn.text()} 宽度 {w} 必须 >=40"
    # Base URL 输入框 sizeHint 宽度 > 0 且不硬撑破 Dock
    assert p.ai_base_url_edit.minimumWidth() == 0


# ---------------------------------------------------------------------------
# Chart tooltip
# ---------------------------------------------------------------------------

def _build_chart_panel(app):
    from app.ui.widgets.chart_panel import ChartPanel
    cp = ChartPanel()
    cp.resize(800, 500)
    cp.show()
    QApplication.processEvents()
    return cp


def test_single_plot_tooltip_format(app):
    from app.ui.widgets.chart_panel import GRAN_RAW
    cp = _build_chart_panel(app)
    xs = np.arange(100, dtype=float)
    s_sin = np.sin(xs / 5.0)
    s_cos = np.cos(xs / 5.0)
    s_tan = np.clip(np.tan(xs / 20.0), -10, 10)
    chart_df = pd.DataFrame({
        "t": pd.date_range("2025-01-01", periods=100, freq="min"),
        "sin": s_sin,
        "cos": s_cos,
        "tan": s_tan,
    })
    msgs = cp.plot_multi_line(
        chart_df,
        x_col="t",
        series_configs=[("sin", "#1f77b4", False), ("cos", "#ff7f0e", False), ("tan", "#2ca02c", False)],
        mean_map={},
        title="test",
        show_points=True,
        show_mean_lines=False,
        x_is_datetime=True,
        granularity=GRAN_RAW,
        y_axis_mode="shared",
    )
    assert isinstance(msgs, list)
    # 在第二条曲线（cos）的中点（idx=50）构造一个 scene 位置
    sd = cp._full_series["cos"]
    target_idx = 50
    vb = cp.plot_widget.plotItem.vb
    # 先让 viewBox 自动 range 生效
    vb.autoRange()
    QApplication.processEvents()
    px, py = float(sd["xs"][target_idx]), float(sd["ys"][target_idx])
    # 直接构造该点 scene 坐标
    sp = vb.mapViewToScene(QPointF(px, py))

    info, idx, dist = cp._nearest_for_vb(vb, sp)
    assert info is not None
    assert info["name"] == "cos"
    assert idx == target_idx
    assert dist < 5.0

    html = cp._format_tooltip(info, idx)
    assert "cos" in html
    # y 值以 4 位有效数字显示
    assert f"{py:.4g}" in html


def test_small_multiples_tooltip_nearest(app):
    from app.ui.widgets.chart_panel import GRAN_RAW
    cp = _build_chart_panel(app)
    n = 200
    chart_df = pd.DataFrame({
        "t": pd.date_range("2025-01-01", periods=n, freq="min"),
        "a": np.sin(np.arange(n) / 10.0),
        "b": np.cos(np.arange(n) / 10.0),
        "c": np.arange(n, dtype=float) * 0.01,
    })
    cp.plot_multi_line(
        chart_df,
        x_col="t",
        series_configs=[
            ("a", "#1f77b4", False),
            ("b", "#ff7f0e", False),
            ("c", "#2ca02c", False),
        ],
        mean_map={},
        title="sm",
        show_points=True,
        show_mean_lines=False,
        x_is_datetime=True,
        granularity=GRAN_RAW,
        y_axis_mode="small_multiples",
    )
    QApplication.processEvents()
    assert len(cp._sm_plots) == 3
    # 命中第二个子图（b 曲线，idx=1）中心数据点
    target_plot_idx = 1
    sd = cp._sm_full_series[target_plot_idx]
    target_data_idx = len(sd["xs"]) // 2
    vb = cp._sm_plots[target_plot_idx].vb
    vb.autoRange()
    QApplication.processEvents()
    px, py = float(sd["xs"][target_data_idx]), float(sd["ys"][target_data_idx])
    sp = vb.mapViewToScene(QPointF(px, py))

    hit = cp._sm_find_nearest(sp)
    assert hit is not None, "必须命中小多图子图上的点"
    plot_idx, data_idx, dist = hit
    assert plot_idx == target_plot_idx, f"应命中第 2 个子图，实际 {plot_idx}"
    assert data_idx == target_data_idx, f"应命中中点 idx={target_data_idx}，实际 {data_idx}"
    assert dist < 10.0

    # 子图 0 上的数据点必须能命中子图 0
    sd0 = cp._sm_full_series[0]
    idx0 = 10
    sp0 = cp._sm_plots[0].vb.mapViewToScene(QPointF(float(sd0["xs"][idx0]), float(sd0["ys"][idx0])))
    cp._sm_plots[0].vb.autoRange()
    QApplication.processEvents()
    # autoRange 后重算 scene 坐标
    sp0 = cp._sm_plots[0].vb.mapViewToScene(QPointF(float(sd0["xs"][idx0]), float(sd0["ys"][idx0])))
    hit0 = cp._sm_find_nearest(sp0)
    assert hit0 is not None
    assert hit0[0] == 0
    assert hit0[1] == idx0


def test_hover_tolerance_value(app):
    from app.ui.widgets import chart_panel as cp_mod
    assert cp_mod._HOVER_TOLERANCE_PX >= 15, \
        f"悬停容差应 >= 15px，实际 {cp_mod._HOVER_TOLERANCE_PX}"
