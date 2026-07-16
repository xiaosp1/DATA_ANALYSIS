"""C037-B: target_col 解耦 + 归因模式语义验证。

约束(与现有 S5 UI 测试一致):
- PySide6 offscreen 模式启动 QApplication;
- 不启动主窗口、不读真实文件;
- 覆盖 process_analysis_panel 上的 target_col 解耦集成点:
  T1  归因模式下 target_combo 出现且可选;状态分类模式下 target_combo 禁用
  T2  归因模式下 cfg["target_col"] 默认 "[机尾]指数-s",切换后变 "[机头]机头温度"
  T3  feature_cols 默认返回的是"全部数值列 - target - 时间列"(不是只有 [机头]*)
  T4(额外) 引擎默认 feature_cols 现在接受非 [机头]* 的数值列(Owner #3)
"""
from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    yield _app


from app.ui.widgets.process_analysis_panel import (  # noqa: E402
    ProcessAnalysisPanel,
)


def _make_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    """构造含 [机头]* + [机尾]指数-s + 一个非 [机头] 数值列(用于验证 Owner #3)。"""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=n, freq="1min")
    f1 = rng.normal(50, 5, n)
    f2 = rng.normal(100, 10, n)
    f3 = rng.normal(0, 1, n)
    extra = rng.normal(7, 2, n)  # 非 [机头]* 数值列,验证 Owner #3
    raw = 4.0 + 0.15 * (f1 - 50) + 0.2 * f3 + rng.normal(0, 0.4, n)
    target = np.clip(np.round(raw), 1, 8).astype(int)
    return pd.DataFrame({
        "时间": t,
        "[机头]机头温度": f1,
        "[机头]机头压力": f2,
        "[机头]机头速度": f3,
        "[机尾]指数-s": target,
        "外部数值": extra,  # 不带 [机头] 前缀
    })


def _switch_to_head_tail_mode(p: ProcessAnalysisPanel) -> None:
    idx = p.mode_combo.findData("head_tail_attr")
    assert idx >= 0
    p.mode_combo.setCurrentIndex(idx)


def _switch_to_state_classify_mode(p: ProcessAnalysisPanel) -> None:
    idx = p.mode_combo.findData("state_classify")
    assert idx >= 0
    p.mode_combo.setCurrentIndex(idx)


# --------------------------------------------------------------------------
# T1: 归因模式下 target_combo 出现且可选;状态分类模式下 target_combo 禁用
# --------------------------------------------------------------------------
def test_target_combo_enable_disable_by_mode(app):
    """归因模式: target_combo enabled;状态分类模式: target_combo disabled。"""
    p = ProcessAnalysisPanel()
    df = _make_df()
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机头]机头压力", "[机头]机头速度", "[机尾]指数-s", "外部数值"],
        datetime_cols=["时间"],
    )

    # 初始默认 state_classify 模式
    assert p.target_combo.isEnabled() is False, "state_classify 模式下 target_combo 应禁用"
    assert p.state_combo.isEnabled() is True, "state_classify 模式下 state_combo 应启用"
    # target_combo 应至少包含所有数值列(包括默认 [机尾]指数-s)
    items = [p.target_combo.itemText(i) for i in range(p.target_combo.count())]
    assert "[机尾]指数-s" in items
    assert "[机头]机头温度" in items
    assert "外部数值" in items

    # 切到归因模式
    _switch_to_head_tail_mode(p)
    assert p.target_combo.isEnabled() is True, "归因模式下 target_combo 应启用"
    assert p.state_combo.isEnabled() is False, "归因模式下 state_combo 应禁用"

    # 切回状态分类
    _switch_to_state_classify_mode(p)
    assert p.target_combo.isEnabled() is False, "回到 state_classify 后 target_combo 应禁用"
    assert p.state_combo.isEnabled() is True


# --------------------------------------------------------------------------
# T2: 归因模式下 cfg["target_col"] 默认 "[机尾]指数-s",切换后变 "[机头]机头温度"
# --------------------------------------------------------------------------
def test_get_config_target_col_decoupled(app):
    """默认 target = [机尾]指数-s;手动切换后 cfg 跟随。"""
    p = ProcessAnalysisPanel()
    df = _make_df()
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机头]机头压力", "[机头]机头速度", "[机尾]指数-s", "外部数值"],
        datetime_cols=["时间"],
    )
    _switch_to_head_tail_mode(p)

    cfg = p.get_config()
    assert cfg["mode"] == "head_tail_attr"
    assert cfg["target_col"] == "[机尾]指数-s", f"默认应为 [机尾]指数-s, got {cfg['target_col']}"
    assert cfg["ideal_value"] == 4.0

    # 切到 [机头]机头温度
    idx = p.target_combo.findData("[机头]机头温度")
    assert idx >= 0
    p.target_combo.setCurrentIndex(idx)
    cfg2 = p.get_config()
    assert cfg2["target_col"] == "[机头]机头温度", (
        f"切换后 cfg['target_col'] 应为 [机头]机头温度, got {cfg2['target_col']}"
    )
    # target 不应在 feature_cols 里
    assert "[机头]机头温度" not in cfg2["feature_cols"], (
        f"target 不能进入 feature_cols, got {cfg2['feature_cols']}"
    )


# --------------------------------------------------------------------------
# T3: feature_cols 默认返回"全部数值列 - target - 时间列"(不是只有 [机头]*)
# --------------------------------------------------------------------------
def test_feature_cols_includes_all_numeric_except_target(app):
    """Owner #3: feature = 全部数值列(排除 target、时间列、ID 列)"""
    p = ProcessAnalysisPanel()
    df = _make_df()
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["[机尾]指数-s"],
        numeric_cols=["[机头]机头温度", "[机头]机头压力", "[机头]机头速度", "[机尾]指数-s", "外部数值"],
        datetime_cols=["时间"],
    )
    _switch_to_head_tail_mode(p)

    cfg = p.get_config()
    feats = cfg["feature_cols"]
    # 至少包含 [机头]* 和非 [机头]* 数值列
    assert "[机头]机头温度" in feats
    assert "[机头]机头压力" in feats
    assert "[机头]机头速度" in feats
    assert "外部数值" in feats, f"Owner #3 要求纳入全部数值列, got feats={feats}"
    # 不包含 target 和时间列
    assert "[机尾]指数-s" not in feats, f"target 不应在 feats 里, got {feats}"
    assert "时间" not in feats


# --------------------------------------------------------------------------
# T4(额外): 引擎默认 feature_cols 现在接受非 [机头]* 的数值列
# --------------------------------------------------------------------------
def test_engine_default_feature_cols_includes_non_head_numeric():
    """Owner #3: 引擎默认 feature_cols 不再过滤 [机头]* 前缀,纳入全部数值列。"""
    from app.services.head_tail_attribution import build_head_tail_report

    df = _make_df(n=200, seed=42)
    rpt = build_head_tail_report(
        df,
        target_col="[机尾]指数-s",
        min_samples=10,
        # feature_cols=None 走默认路径
    )
    assert "error" not in rpt, rpt.get("error")
    # n_head_features 现在表示"全部数值特征数"(变量名保留向后兼容)
    n_feats = int(rpt["meta"]["n_head_features"])
    # 4 个非 target/时间的数值列:[机头]机头温度/压力/速度 + 外部数值
    assert n_feats >= 4, f"默认 feature_cols 应纳入全部数值列(≥4), got {n_feats}"
    # 至少一个非 [机头]* 数值列进入 attribution
    attr_names = [a["feature"] for a in rpt.get("attribution", [])]
    # 外部数值可能被相关性低而过滤掉,所以不强求它在 attribution;
    # 但 n_head_features 计数应包含它(确认默认 feature_cols 纳入非 [机头]* 列)
    assert n_feats == 4, f"默认 feature_cols 应包含 [机头]*(3) + 外部数值(1) = 4, got {n_feats}"


# --------------------------------------------------------------------------
# T5(额外): _has_head_tail_columns 软化后,无 [机头]* 时仅需 ≥2 数值列即可通过
# --------------------------------------------------------------------------
def test_has_head_tail_columns_softened(app):
    """C037-B: _has_head_tail_columns 不再要求 [机头]* + [机尾]指数-s,只要求 ≥2 数值列。"""
    p = ProcessAnalysisPanel()
    # 构造无 [机头]* 前缀的数据集,但有 3 个数值列(含 target)
    rng = np.random.default_rng(0)
    n = 100
    df = pd.DataFrame({
        "时间": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "x1": rng.normal(0, 1, n),
        "x2": rng.normal(0, 1, n),
        "y": rng.integers(1, 9, n).astype(float),
    })
    p.set_dataset(
        df,
        time_col_options=["时间"],
        state_col_options=["y"],
        numeric_cols=["x1", "x2", "y"],
        datetime_cols=["时间"],
    )
    # 软化后应通过(因为 x1+x2+y = 3 个数值列,≥2)
    assert p._has_head_tail_columns() is True, "≥2 数值列应通过(软化后)"

    # 只有 1 个数值列时应不通过
    df2 = pd.DataFrame({
        "时间": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "y": rng.integers(1, 9, n).astype(float),
        "name": ["x"] * n,
    })
    p.set_dataset(
        df2,
        time_col_options=["时间"],
        state_col_options=["y"],
        numeric_cols=["y"],
        datetime_cols=["时间"],
    )
    assert p._has_head_tail_columns() is False, "仅 1 个数值列应不通过"
