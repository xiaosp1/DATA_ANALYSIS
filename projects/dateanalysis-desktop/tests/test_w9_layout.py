"""W9 layout / AI base_url 单测（offscreen）。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDockWidget, QTabWidget  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    yield _app


from app.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture()
def win(monkeypatch, tmp_path, app):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # 每个测试清空/隔离 QSettings，避免污染用户真实配置
    s = QSettings("DateAnalysis", "DateAnalysis")
    s.clear()
    s.sync()
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    QApplication.processEvents()
    yield w
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    s = QSettings("DateAnalysis", "DateAnalysis")
    s.clear()
    s.sync()


def _find_dock(w: MainWindow, title: str) -> QDockWidget | None:
    for c in w.children():
        if isinstance(c, QDockWidget) and c.windowTitle() == title:
            return c
    return None


def test_left_dock_exists_and_toggle(win):
    dock = _find_dock(win, "数据与配置")
    assert dock is not None, "必须存在左 Dock「数据与配置」"
    assert dock.isVisible() is True
    assert win.toggle_left_dock_btn.isChecked() is True
    # 点击按钮隐藏
    win.toggle_left_dock_btn.setChecked(False)
    QApplication.processEvents()
    assert dock.isVisible() is False
    assert win.toggle_left_dock_btn.isChecked() is False
    # 再点恢复
    win.toggle_left_dock_btn.setChecked(True)
    QApplication.processEvents()
    assert dock.isVisible() is True
    assert win.toggle_left_dock_btn.isChecked() is True


def test_right_info_dock_exists_with_4_tabs(win):
    dock = _find_dock(win, "信息面板")
    assert dock is not None, "必须存在右 Dock「信息面板」"
    assert dock.isVisible() is True
    inner = dock.widget()
    # inner 可能直接是 QTabWidget，或者是包含 QTabWidget 的容器
    tabs = inner if isinstance(inner, QTabWidget) else inner.findChild(QTabWidget)
    assert tabs is not None
    assert tabs.count() == 4
    expected = ["当前数据", "统计结果", "日志提示", "工艺分析"]
    for i, title in enumerate(expected):
        assert tabs.tabText(i) == title
    assert tabs.widget(0) is win.data_panel
    assert tabs.widget(1) is win.stats_panel
    assert tabs.widget(2) is win.log_panel
    assert tabs.widget(3) is win.process_analysis_panel


def test_central_widget_is_chart_tabs_only(win):
    central = win.centralWidget()
    assert central is not None
    # chart_tabs 必须在 central 下
    assert win.chart_tabs.parent() is central or central.isAncestorOf(win.chart_tabs)
    # 旧 self.tabs 不得直接挂在 central 下（应在右 Dock 中）
    assert win.tabs is win.info_tabs, "self.tabs 应别名为 info_tabs"
    assert win.chart_tabs.parent() is not win.tabs
    # 隐藏左右 dock 后，chart_tabs 宽度接近窗口宽度
    win.left_dock.setVisible(False)
    win.right_dock.setVisible(False)
    QApplication.processEvents()
    win.resize(1400, 900)
    QApplication.processEvents()
    w_chart = win.chart_tabs.width()
    w_win = win.width()
    assert w_chart > w_win - 50, f"chart_tabs 宽度 {w_chart} 应接近窗口宽度 {w_win}"


def test_ai_base_url_editable_on_all_providers(win):
    p = win.process_analysis_panel
    for provider_key in ("openai", "deepseek"):
        idx = p.ai_provider_combo.findData(provider_key)
        assert idx >= 0
        p.ai_provider_combo.setCurrentIndex(idx)
        QApplication.processEvents()
        assert p.ai_base_url_edit.isReadOnly() is False, f"{provider_key} 下 base_url 必须可编辑"
        assert p.ai_model_edit.isReadOnly() is False
    # 切到 openai，改 base_url，确认 get_ai_config 读回的就是输入值
    idx = p.ai_provider_combo.findData("openai")
    p.ai_provider_combo.setCurrentIndex(idx)
    QApplication.processEvents()
    p.ai_base_url_edit.setText("https://my-proxy.example.com/v1")
    p.ai_base_url_edit.textEdited.emit("https://my-proxy.example.com/v1")
    cfg = p.get_ai_config()
    assert cfg["provider"] == "openai"
    assert cfg["base_url"] == "https://my-proxy.example.com/v1"


def test_ai_base_url_validation(win):
    p = win.process_analysis_panel
    p.set_dataset(
        pd.DataFrame({
            "t": pd.date_range("2025-01-01", periods=50, freq="min"),
            "x": np.random.default_rng(0).normal(size=50),
            "s": np.random.default_rng(1).choice([0, 1], size=50),
        }),
        time_col_options=["t"],
        state_col_options=["s"],
        numeric_cols=["x"],
        datetime_cols=["t"],
    )
    # 制造一个假 report，绕开「先完成工艺分析」校验
    p._report = {"summary": {"1": {"count": 30, "pct": 1.0, "unreliable": False}},
                 "univariate": {"1": {"features": {"x": {"count": 30, "mean": 0, "std": 1,
                                                        "window_1sigma": (-1, 1),
                                                        "p5": -2, "p95": 2}}}},
                 "rules": {}, "feature_importance": [],
                 "meta": {"n_rows": 50, "feature_cols": ["x"], "target_states": ["1"]}}
    p._refresh_ai_button_state()
    p.set_api_key("sk-fake")

    idx = p.ai_provider_combo.findData("openai")
    p.ai_provider_combo.setCurrentIndex(idx)
    QApplication.processEvents()
    p.ai_base_url_edit.setText("ftp://bad")

    emitted = {"count": 0}

    def _slot(*a, **k):
        emitted["count"] += 1

    p.ai_insight_requested.connect(_slot)
    try:
        p._emit_ai_insight()
        QApplication.processEvents()
        assert emitted["count"] == 0, "URL 非法时不应 emit ai_insight_requested"
        assert "http" in p.ai_status_label.text()
    finally:
        try:
            p.ai_insight_requested.disconnect(_slot)
        except Exception:
            pass


def test_ai_client_preset_url_override(app):
    from app.services.ai_client import AIClient
    c = AIClient("openai", api_key="k", base_url="https://my-proxy.example.com/v1",
                 model="gpt-4.1")
    assert c.base_url == "https://my-proxy.example.com/v1"
    assert c.model == "gpt-4.1"


def test_dock_toggle_buttons_sync_with_close_button(win):
    # 用 dock 自身的 close -> visibilityChanged 同步按钮
    win.left_dock.close()
    QApplication.processEvents()
    assert win.toggle_left_dock_btn.isChecked() is False
    win.left_dock.show()
    QApplication.processEvents()
    assert win.toggle_left_dock_btn.isChecked() is True
