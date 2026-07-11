"""W8a ProcessAnalysisPanel UI 单测（offscreen）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    yield _app


from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel  # noqa: E402


def _make_df(n=200, seed=0):
    rng = np.random.default_rng(seed)
    states = rng.choice([3, 4, 5], size=n, p=[0.1, 0.6, 0.3])
    hk = np.where(states == 4, rng.normal(380, 10, n), rng.normal(430, 12, n))
    return pd.DataFrame({
        "时间": pd.date_range("2025-01-01", periods=n, freq="s"),
        "虎口距": hk,
        "中指距": rng.normal(1020, 15, n),
        "指数-s": states.astype(np.int64),
        "未脱模-s": rng.normal(50, 5, n),
    })


def test_panel_instantiates(app):
    p = ProcessAnalysisPanel()
    assert p is not None


def test_set_dataset_populates_lists(app):
    p = ProcessAnalysisPanel()
    df = _make_df()
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["指数-s"],
        numeric_cols=["虎口距", "中指距", "指数-s", "未脱模-s"],
        datetime_cols=["时间"],
    )
    assert p.state_combo.count() == 1
    assert p.state_combo.currentData() == "指数-s"
    assert p.state_list.count() == 3  # 3/4/5
    # 特征列：排除 时间/未脱模-s/状态列 后应剩 虎口距+中指距
    feats = [p.feature_list.item(i).text() for i in range(p.feature_list.count())]
    assert "虎口距" in feats
    assert "中指距" in feats
    assert "未脱模-s" not in feats
    assert "指数-s" not in feats


def test_get_config_returns_selections(app):
    p = ProcessAnalysisPanel()
    df = _make_df()
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["指数-s"],
        numeric_cols=["虎口距", "中指距", "指数-s", "未脱模-s"],
        datetime_cols=["时间"],
    )
    cfg = p.get_config()
    assert cfg["state_col"] == "指数-s"
    assert set(cfg["feature_cols"]) == {"虎口距", "中指距"}
    # 默认非0全选 → 3/4/5 都被选中
    assert set(cfg["target_states"]) == {3, 4, 5}


def test_set_result_fills_summary_table(app):
    p = ProcessAnalysisPanel()
    df = _make_df(n=300)
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["指数-s"],
        numeric_cols=["虎口距", "中指距", "指数-s", "未脱模-s"],
        datetime_cols=["时间"],
    )
    from app.services.process_analysis import build_analysis_report
    rpt = build_analysis_report(df)
    p.set_result(rpt)
    n_states = len(rpt["summary"])
    assert p.summary_table.rowCount() == n_states
    assert p.window_table.rowCount() > 0
    assert p.imp_table.rowCount() >= 2
    assert "WHEN" in p.rules_text.toPlainText() or "全体样本" in p.rules_text.toPlainText() or "目标状态" in p.rules_text.toPlainText()


def test_set_result_error_shows_message(app):
    p = ProcessAnalysisPanel()
    p.set_result({"error": "测试错误", "meta": {"warnings": []}})
    assert "测试错误" in p.status_label.text()


def test_set_running_toggles_buttons(app):
    p = ProcessAnalysisPanel()
    p.set_running(True)
    assert p.analyze_btn.isEnabled() is False
    assert "分析中" in p.analyze_btn.text()
    p.set_running(False)
    assert p.analyze_btn.isEnabled() is True
    assert "开始分析" in p.analyze_btn.text()


def test_set_dataset_none_clears(app):
    p = ProcessAnalysisPanel()
    df = _make_df()
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["指数-s"],
        numeric_cols=["虎口距", "中指距", "指数-s", "未脱模-s"],
        datetime_cols=["时间"],
    )
    p.set_dataset(None, [], [], [], [])
    assert p.state_combo.count() == 0
    assert p.feature_list.count() == 0
    assert p.state_list.count() == 0
