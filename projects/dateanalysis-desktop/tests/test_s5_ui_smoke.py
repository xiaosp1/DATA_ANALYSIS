"""S5-#3 UI smoke 测试（纯函数 + 简单 widget 调用，无 GUI 渲染）。

覆盖：
  T1  build_multi_params(multi_enabled=False)  → multi=False 且 M1/M2 全 False
  T2  build_multi_params(multi_enabled=True, multi_top_n=1) → top_n 规范化为 10
  T3  _make_synthetic_df + build_head_tail_report(multi=True)
      → report["multi"]["ols"]["coef_std"][0]["beta_std"] 是浮点数（非 NaN/None）
  T4  （额外）build_multi_params(multi_enabled=True, multi_top_n=3, True/True/True)
      → top_n 透传，partial/ols/use_pingouin 全 True
  T5  （额外）ProcessAnalysisPanel._render_chart3_grid 在 5 特征场景下
      产出 5 个 PlotItem（grid 2 × ⌈5/2⌉ = 2 × 3，4 cell 占用 5）

注：T5 需要 PySide6 + QApplication offscreen（pytest-qt 或 QT_QPA_PLATFORM=offscreen）。
    为不强制依赖 GUI 环境，conftest-like guard 用 sys.platform + import 跳过。
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd
import pytest


# --------------------------------------------------------------------------
# T1/T2/T4 纯函数
# --------------------------------------------------------------------------

def test_build_multi_params_disabled_returns_all_false():
    """T1：multi_enabled=False 时返回 dict 含 multi=False 且 M1/M2/use_pingouin 全 False。"""
    from app.ui.widgets.process_analysis_panel import build_multi_params
    p = build_multi_params(multi_enabled=False)
    assert isinstance(p, dict)
    assert p["multi"] is False
    assert p["multi_compute_partial"] is False
    assert p["multi_compute_ols"] is False
    assert p["multi_compute_partial"] is False
    assert p["use_pingouin"] is False
    # top_n 在 disabled 路径也要规范化（避免脏值污染 cfg）
    assert p["multi_top_n"] == 10


def test_build_multi_params_top_n_normalized_to_10_when_le_1():
    """T2：multi_enabled=True, multi_top_n=1 规范化为 10（避免 OLS 退化）。"""
    from app.ui.widgets.process_analysis_panel import build_multi_params
    p = build_multi_params(multi_enabled=True, multi_top_n=1)
    assert p["multi"] is True
    assert p["multi_top_n"] == 10, f"multi_top_n=1 应规范化为 10, got {p['multi_top_n']}"

    # 同样：0、负数、None 都应规范化为 10
    for bad in (0, -1, -100, None):
        p2 = build_multi_params(multi_enabled=True, multi_top_n=bad)
        assert p2["multi_top_n"] == 10, f"bad={bad} → {p2['multi_top_n']}"


def test_build_multi_params_enabled_passes_through():
    """T4（额外）：multi_enabled=True + multi_top_n=3 + 三子开关 True → 透传。"""
    from app.ui.widgets.process_analysis_panel import build_multi_params
    p = build_multi_params(
        multi_enabled=True,
        multi_top_n=3,
        multi_compute_partial=True,
        multi_compute_ols=True,
        use_pingouin=True,
    )
    assert p["multi"] is True
    assert p["multi_top_n"] == 3
    assert p["multi_compute_partial"] is True
    assert p["multi_compute_ols"] is True
    assert p["use_pingouin"] is True


# --------------------------------------------------------------------------
# T3 引擎层 smoke
# --------------------------------------------------------------------------

def _make_synthetic_df(n: int = 500, seed: int = 0) -> pd.DataFrame:
    """复用 test_s5_multi_attribution._make_synthetic_df 的口径（独立 copy 避免 import 耦合）。"""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=n, freq="1min")
    f1 = rng.normal(50, 5, n)
    f2 = rng.normal(100, 10, n)
    f3 = rng.normal(0, 1, n)
    f4 = f1 + rng.normal(0, 0.05, n)  # 与 f1 高度共线 → VIF>10
    noise = rng.normal(0, 0.4, n)
    raw = 4.0 + 0.15 * (f1 - 50) + 0.2 * f3 + noise
    target = np.clip(np.round(raw), 1, 8).astype(int)
    return pd.DataFrame({
        "时间": t,
        "[机头]f1": f1,
        "[机头]f2": f2,
        "[机头]f3": f3,
        "[机头]f4": f4,
        "[机尾]指数-s": target,
    })


def test_multi_report_coef_std_beta_is_real_float():
    """T3：用 _make_synthetic_df(500) 调 build_head_tail_report(multi=True)，
    断言 report["multi"]["ols"]["coef_std"] 非空且每条 beta_std 是有限浮点数。"""
    from app.services.head_tail_attribution import build_head_tail_report
    df = _make_synthetic_df(n=500, seed=0)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10, multi=True)
    assert "multi" in rpt
    ols = rpt["multi"].get("ols") or {}
    coef_std = ols.get("coef_std") or []
    assert isinstance(coef_std, list)
    assert len(coef_std) > 0, "multi=True 场景 coef_std 应非空"

    # 每条都必须是 dict，beta_std 是有限 float
    for row in coef_std:
        assert isinstance(row, dict)
        assert "feature" in row
        b = row.get("beta_std")
        assert b is not None, f"feature={row.get('feature')} beta_std=None"
        assert isinstance(b, float), f"feature={row.get('feature')} type={type(b)}"
        assert math.isfinite(b), f"feature={row.get('feature')} beta_std={b} 非有限"

    # 至少第一条也满足——这是 DoD 显式要求的
    first = coef_std[0]
    assert first["beta_std"] is not None
    assert isinstance(first["beta_std"], float)
    assert math.isfinite(first["beta_std"])


# --------------------------------------------------------------------------
# T5 渲染层 smoke（仅在 PySide6 + offscreen 可用时跑）
# --------------------------------------------------------------------------

@pytest.mark.skipif(
    sys.platform.startswith("linux") and not os.environ.get("DISPLAY"),
    reason="无 DISPLAY 时跳过 Qt 渲染 smoke",
)
def test_render_chart3_grid_emits_n_plotitems():
    """T5（额外）：5 特征场景下 _render_chart3_grid 应产出 5 个 PlotItem，
    验证 grid 2 × ⌈p/2⌉ 不会丢子图。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from app.services.head_tail_attribution import build_head_tail_report
    from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel

    rng = np.random.default_rng(7)
    n = 300
    df = pd.DataFrame({
        f"[机头]f{i}": rng.normal(0, 1, n) for i in range(1, 6)
    })
    df["[机尾]指数-s"] = rng.integers(1, 9, n).astype(float)

    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10, multi=True)
    ols = rpt["multi"]["ols"]
    coef_sorted = sorted(ols["coef_std"], key=lambda c: abs(c.get("beta_std", 0.0)), reverse=True)

    panel = ProcessAnalysisPanel()
    panel._df = df
    panel._multi_enabled = True
    panel._render_chart3_grid(coef_sorted=coef_sorted, ols_dict=ols)

    plots = [c for c in panel.multi_chart3.ci.childItems()
             if "PlotItem" in type(c).__name__]
    assert len(plots) == len(coef_sorted), (
        f"chart3 应产出 {len(coef_sorted)} 个子图, got {len(plots)}"
    )
    # 每个标题必须含 "mean=" 与 "std="（ASCII-only 避免 Unicode 规范化陷阱）
    for p in plots:
        raw_title = p.titleLabel.text if hasattr(p, "titleLabel") else ""
        title = str(raw_title)
        assert "mean=" in title and "std=" in title, f"标题缺统计量: {title!r}"
