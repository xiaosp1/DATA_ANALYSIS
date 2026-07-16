"""S5-#3 多变量归因 UI 集成 smoke 测试。

约束（与现有 W8a/W11/W12 测试一致）：
- PySide6 offscreen 模式启动 QApplication；
- 不启动主窗口、不读真实文件；
- 覆盖 process_analysis_panel 上的多变量归因 UI 集成点：
  1) 多变量使能 checkbox / pingouin 精化 checkbox 存在 + 默认状态；
  2) get_config() 透传 multi* 参数；
  3) Top10 预勾选函数 + 子工具条切换；
  4) 多变量关闭时 Tab 隐藏 / 报告不含 multi 节点；
  5) 取消按钮回调接入 cancel_event。

≥3 UI smoke 测试（任务硬性要求）；实际本文件给到 6 个。
"""
from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QListWidgetItem  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    yield _app


from app.ui.widgets.process_analysis_panel import (  # noqa: E402
    ProcessAnalysisPanel,
    build_multi_params,
    compute_top_n_pearson,
    preselect_top_n_indices,
)


def _make_head_tail_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=n, freq="1min")
    f1 = rng.normal(50, 5, n)
    f2 = rng.normal(100, 10, n)
    f3 = rng.normal(0, 1, n)
    noise = rng.normal(0, 0.4, n)
    raw = 4.0 + 0.15 * (f1 - 50) + 0.2 * f3 + noise
    target = np.clip(np.round(raw), 1, 8).astype(int)
    return pd.DataFrame({
        "时间": t,
        "[机头]机头温度": f1,
        "[机头]机头压力": f2,
        "[机头]机头速度": f3,
        "[机尾]指数-s": target,
    })


def _switch_to_head_tail_mode(p: ProcessAnalysisPanel) -> None:
    """强制把 panel 切到 head_tail_attr 模式（模拟用户在 mode_combo 选中机尾归因）。"""
    idx = p.mode_combo.findData("head_tail_attr")
    assert idx >= 0
    p.mode_combo.setCurrentIndex(idx)


def _find_tab(p: ProcessAnalysisPanel, widget) -> int:
    return p.result_tabs.indexOf(widget)


# --------------------------------------------------------------------------
# 1. 构建 multi 参数 dict（纯函数）
# --------------------------------------------------------------------------

def test_build_multi_params_basic():
    """build_multi_params 默认开启 multi=True / multi_top_n=10 / partial+ols=True。"""
    d = build_multi_params(multi_enabled=True, multi_top_n=10)
    assert d["multi"] is True
    assert d["multi_top_n"] == 10
    assert d["multi_compute_partial"] is True
    assert d["multi_compute_ols"] is True
    assert d["use_pingouin"] is False  # 默认关


def test_build_multi_params_disabled():
    """关闭 multi 时所有 multi* 字段应传 False。"""
    d = build_multi_params(
        multi_enabled=False,
        multi_top_n=10,
        multi_compute_partial=True,
        multi_compute_ols=True,
        use_pingouin=True,
    )
    assert d["multi"] is False
    assert d["multi_compute_partial"] is False
    assert d["multi_compute_ols"] is False
    assert d["use_pingouin"] is False


def test_build_multi_params_top_n_clamped():
    """multi_top_n<=1 时被规范化为 10。"""
    d = build_multi_params(True, multi_top_n=0)
    assert d["multi_top_n"] == 10
    d2 = build_multi_params(True, multi_top_n=-3)
    assert d2["multi_top_n"] == 10
    d3 = build_multi_params(True, multi_top_n=15)
    assert d3["multi_top_n"] == 15


# --------------------------------------------------------------------------
# 2. Top10 预勾选 / 子工具条切换
# --------------------------------------------------------------------------

def test_compute_top_n_pearson_orders_by_abs():
    """compute_top_n_pearson 应按 |Pearson| 降序返回前 n 个。"""
    df = _make_head_tail_df(500, seed=42)
    cands = ["[机头]机头温度", "[机头]机头压力", "[机头]机头速度"]
    out = compute_top_n_pearson(df, "[机尾]指数-s", cands, n=3)
    assert len(out) == 3
    # 排序：|r| 单调不增
    for a, b in zip(out, out[1:]):
        assert abs(a[1]) >= abs(b[1])
    # 在该数据生成参数下，机头温度应排第 1（强正相关）
    assert out[0][0] == "[机头]机头温度"
    # r 数值应与符号匹配
    assert out[0][1] > 0.3


def test_preselect_top_n_indices_helper():
    """preselect_top_n_indices 返回的索引集合应只含 top10 列的位置。"""
    names = ["a", "b", "c", "d", "e"]
    top = ["c", "a"]
    idx_set = preselect_top_n_indices(names, top)
    assert idx_set == {0, 2}


def test_panel_top10_preselect_on_head_tail_mode(app):
    """切到 head_tail_attr 模式后，feature_list 默认应按 |Pearson| Top10 预勾。"""
    p = ProcessAnalysisPanel()
    df = _make_head_tail_df(500, seed=42)
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机头]机头压力", "[机头]机头速度", "[机尾]指数-s"],
        datetime_cols=["时间"],
    )
    _switch_to_head_tail_mode(p)
    # 默认全勾（只 3 列都在 Top10 → 应全部勾选；子工具条 = top10）
    sel = [p.feature_list.item(i).text() for i in range(p.feature_list.count())
           if p.feature_list.item(i).isSelected()]
    assert set(sel) == {"[机头]机头温度", "[机头]机头压力", "[机头]机头速度"}
    assert p._feat_select_mode == "top10"

    # 测「反选」：全部不勾
    p._apply_feat_select_mode("invert")
    sel2 = [p.feature_list.item(i).text() for i in range(p.feature_list.count())
            if p.feature_list.item(i).isSelected()]
    assert sel2 == []
    assert p._feat_select_mode == "invert"

    # 测「全选」
    p._apply_feat_select_mode("all")
    sel3 = [p.feature_list.item(i).text() for i in range(p.feature_list.count())
            if p.feature_list.item(i).isSelected()]
    assert len(sel3) == 3
    assert p._feat_select_mode == "all"


# --------------------------------------------------------------------------
# 3. get_config 透传 multi* 参数
# --------------------------------------------------------------------------

def test_get_config_head_tail_default_multi_on(app):
    """head_tail_attr 模式下 get_config 默认 multi=True, multi_top_n=10。"""
    p = ProcessAnalysisPanel()
    df = _make_head_tail_df(200, seed=0)
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机头]机头压力", "[机头]机头速度", "[机尾]指数-s"],
        datetime_cols=["时间"],
    )
    _switch_to_head_tail_mode(p)
    cfg = p.get_config()
    assert cfg["mode"] == "head_tail_attr"
    assert cfg["multi"] is True
    assert cfg["multi_top_n"] == 10
    assert cfg["multi_compute_partial"] is True
    assert cfg["multi_compute_ols"] is True
    # use_pingouin 依赖环境；当前 venv 未装 → 必然 False
    assert cfg["use_pingouin"] is False


def test_get_config_state_classify_multi_off(app):
    """state_classify 模式下 get_config 必须 multi=False。"""
    p = ProcessAnalysisPanel()
    df = pd.DataFrame({
        "时间": pd.date_range("2024-01-01", periods=50, freq="s"),
        "x": np.arange(50, dtype=float),
        "y": np.arange(50, dtype=float),
        "state": [1, 2] * 25,
    })
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["state"],
        numeric_cols=["x", "y", "state"],
        datetime_cols=["时间"],
    )
    cfg = p.get_config()
    assert cfg["mode"] == "state_classify"
    assert cfg["multi"] is False
    assert cfg["multi_compute_partial"] is False
    assert cfg["multi_compute_ols"] is False


def test_get_config_toggles_with_multi_checkbox(app):
    """取消勾选 multi_checkbox 后 get_config 应返回 multi=False。"""
    p = ProcessAnalysisPanel()
    df = _make_head_tail_df(200, seed=0)
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机头]机头压力", "[机尾]指数-s"],
        datetime_cols=["时间"],
    )
    _switch_to_head_tail_mode(p)
    # 初始 multi=True
    assert p.get_config()["multi"] is True
    # 关闭 checkbox
    p.multi_checkbox.setChecked(False)
    cfg = p.get_config()
    assert cfg["multi"] is False
    assert cfg["multi_compute_partial"] is False
    assert cfg["multi_compute_ols"] is False
    # 重新打开
    p.multi_checkbox.setChecked(True)
    assert p.get_config()["multi"] is True


# --------------------------------------------------------------------------
# 4. UI 状态：Tab 隐藏 / pingouin 提示 / 取消按钮
# --------------------------------------------------------------------------

def test_multi_tab_visibility_toggles_with_checkbox(app):
    """multi_checkbox 关掉时，「多变量归因 (S5)」Tab 必须隐藏。"""
    p = ProcessAnalysisPanel()
    df = _make_head_tail_df(100, seed=0)
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机尾]指数-s"],
        datetime_cols=["时间"],
    )
    _switch_to_head_tail_mode(p)
    idx = _find_tab(p, p.multi_attr_widget)
    assert idx >= 0
    # 默认 multi=True → Tab 可见
    assert p.result_tabs.isTabVisible(idx) is True
    p.multi_checkbox.setChecked(False)
    assert p.result_tabs.isTabVisible(idx) is False
    p.multi_checkbox.setChecked(True)
    assert p.result_tabs.isTabVisible(idx) is True


def test_use_pingouin_checkbox_disabled_when_unavailable(app):
    """当前 venv 未装 pingouin 时 use_pingouin_checkbox 必须禁用并提示。"""
    from app.ui.widgets import process_analysis_panel as pap
    p = ProcessAnalysisPanel()
    if pap._HAS_PINGOOUIN:  # 若环境已装则跳过断言
        pytest.skip("环境已装 pingouin，本断言仅在缺失时验证")
    assert p.use_pingouin_checkbox.isEnabled() is False
    assert "pingouin" in p.use_pingouin_checkbox.toolTip()
    # 同时默认勾选应为 False
    assert p.use_pingouin_checkbox.isChecked() is False


def test_cancel_button_enabled_only_in_head_tail_running(app):
    """取消按钮仅在 head_tail_attr 模式 + 运行中可用。"""
    p = ProcessAnalysisPanel()
    df = _make_head_tail_df(100, seed=0)
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机尾]指数-s"],
        datetime_cols=["时间"],
    )
    # state_classify 模式 + 运行 → 取消按钮应保持禁用
    assert p.cancel_btn.isEnabled() is False
    p.set_running(True)
    assert p.cancel_btn.isEnabled() is False  # state_classify 不支持取消
    p.set_running(False)
    # 切到 head_tail_attr + 运行 → 取消按钮可用
    _switch_to_head_tail_mode(p)
    p.set_running(True)
    assert p.cancel_btn.isEnabled() is True
    p.set_running(False)
    assert p.cancel_btn.isEnabled() is False


def test_cancel_button_triggers_callback(app):
    """点击取消按钮必须触发 set_analysis_cancel_callback 设置的回调。"""
    p = ProcessAnalysisPanel()
    flag = {"called": False}
    p.set_analysis_cancel_callback(lambda: flag.__setitem__("called", True))
    df = _make_head_tail_df(100, seed=0)
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机尾]指数-s"],
        datetime_cols=["时间"],
    )
    _switch_to_head_tail_mode(p)
    p.set_running(True)
    assert p.cancel_btn.isEnabled() is True
    p.cancel_btn.click()
    assert flag["called"] is True


# --------------------------------------------------------------------------
# 5. 端到端：set_result 含 multi 节点时新 Tab 应填上数据
# --------------------------------------------------------------------------

def test_set_result_fills_multi_tab_when_present(app):
    """set_result 传入含 multi 节点的报告时，新 Tab 必须有内容（M1/M2 表行数 > 0）。"""
    from app.services.head_tail_attribution import build_head_tail_report
    p = ProcessAnalysisPanel()
    df = _make_head_tail_df(500, seed=42)
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=10,
        feature_cols=["[机头]机头温度", "[机头]机头压力", "[机头]机头速度"],
        multi=True,
    )
    p.set_result(rpt, mode="head_tail_attr")
    assert p.multi_m1_table.rowCount() >= 3
    assert p.multi_m2_table.rowCount() >= 2
    # 顶部摘要文字包含 "M2 OLS" 或 "跳过"
    assert "M2 OLS" in p.multi_summary_label.text()
    # 归因结果表也填了
    assert p.attrib_table.rowCount() > 0


def test_set_result_no_multi_keeps_tab_empty(app):
    """set_result 传入 multi=False 的报告时，新 Tab 必须保持占位文字。"""
    from app.services.head_tail_attribution import build_head_tail_report
    p = ProcessAnalysisPanel()
    df = _make_head_tail_df(200, seed=0)
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=10, multi=False,
    )
    p.set_result(rpt, mode="head_tail_attr")
    assert "multi" not in rpt
    assert p.multi_m1_table.rowCount() == 0
    assert p.multi_m2_table.rowCount() == 0
    # 占位文字
    assert "未执行" in p.multi_summary_label.text()
