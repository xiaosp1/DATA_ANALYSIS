"""C034 归因分析进度反馈回归测试。

目标:验证 V1.13.1 进度单调性 + UI 异常捕获修复,防止 V1.13.0 的"卡死感"回归。

受修复文件:
- app/services/head_tail_attribution.py(_call_progress 单调性 + M1/M2 阶段 pct 调整)
- app/ui/main_window.py(setMinimumDuration(0) + _progress_cb 异常捕获 + 推到 panel)
- app/ui/widgets/process_analysis_panel.py(内嵌 QProgressBar + set_progress 方法)

测试要点(T1/T2/T3 来自 C034 DoD 4):
- T1:build_head_tail_report(multi=True) 进度回调序列单调递增
- T2:_call_progress 收到 pct=30 在 pct=50 之后,传出仍是 50
- T3:_progress_cb(None) 不抛 AttributeError
- T4(额外):验证 panel 内嵌进度条 widget 已创建 + set_progress 可用
"""
from __future__ import annotations

import os
import sys

import pytest

# 允许在无 Qt 时跳过 UI 测试
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.head_tail_attribution import (
    _call_progress,
    _last_pct,
    build_head_tail_report,
)


# --------------------------------------------------------------------------
# Fixture:合成数据(借用 test_s5_multi_attribution.py 的工厂风格)
# --------------------------------------------------------------------------

def _make_synthetic_df(n: int = 200, seed: int = 0) -> "pd.DataFrame":
    """最小合成数据:f1 强正相关,target 由 f1 决定。"""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=n, freq="1min")
    f1 = rng.normal(50, 5, n)
    f2 = rng.normal(100, 10, n)
    noise = rng.normal(0, 0.4, n)
    raw = 4.0 + 0.15 * (f1 - 50) + noise
    target = np.clip(np.round(raw), 1, 8).astype(int)
    return pd.DataFrame({
        "时间": t,
        "[机头]f1": f1,
        "[机头]f2": f2,
        "[机尾]指数-s": target,
    })


@pytest.fixture(autouse=True)
def _reset_module_progress():
    """每个测试前重置模块级 _last_pct,避免跨测试污染。"""
    import app.services.head_tail_attribution as mod
    mod._last_pct = 0
    yield
    mod._last_pct = 0


# --------------------------------------------------------------------------
# T1:进度回调序列单调递增(build_head_tail_report multi=True 端到端)
# --------------------------------------------------------------------------

def test_progress_sequence_is_monotonic_multi():
    """T1:multi=True 全程跑下来,所有 _call_progress 回调的 pct 必须是单调非递减的。"""
    events: list[tuple[int, str]] = []

    def cb(pct: int, msg: str) -> None:
        events.append((int(pct), str(msg)))

    df = _make_synthetic_df(150, seed=7)
    build_head_tail_report(
        df,
        target_col="[机尾]指数-s",
        min_samples=10,
        feature_cols=["[机头]f1", "[机头]f2"],
        multi=True,
        report_progress=cb,
    )

    assert len(events) >= 5, f"应有 ≥5 个进度事件,实际 {len(events)}"
    pcts = [e[0] for e in events]
    # 断言严格单调(允许相等;但任何回调的 pct 都不能比之前的回调小)
    for i in range(1, len(pcts)):
        assert pcts[i] >= pcts[i - 1], (
            f"进度回退! events[{i-1}]={events[i-1]} > events[{i}]={events[i]}\n"
            f"完整序列:{pcts}"
        )
    # 首尾应在合理区间(W12 起 5%,结尾 100%)
    assert pcts[0] >= 0 and pcts[0] <= 10, f"起始 pct 应在 0~10,实际 {pcts[0]}"
    assert pcts[-1] == 100, f"最终 pct 应为 100,实际 {pcts[-1]}"


def test_progress_sequence_no_100_then_25_regression():
    """T1b(回归):专门防止 V1.13.0 的'W12 100% → M1 25%'倒退 bug 复现。"""
    events: list[tuple[int, str]] = []

    def cb(pct: int, msg: str) -> None:
        events.append((int(pct), str(msg)))

    df = _make_synthetic_df(120, seed=11)
    build_head_tail_report(
        df,
        target_col="[机尾]指数-s",
        min_samples=10,
        feature_cols=["[机头]f1", "[机头]f2"],
        multi=True,
        report_progress=cb,
    )

    pcts = [e[0] for e in events]
    # 核心断言:不应出现"先 100 再降"的 pattern
    seen_100 = False
    for i, p in enumerate(pcts):
        if p >= 100:
            seen_100 = True
            continue
        if seen_100 and p < 100:
            pytest.fail(
                f"V1.13.0 回归! events[{i}]={events[i]} 在 100% 之后回退,"
                f"完整序列:{list(zip(pcts, [e[1] for e in events]))}"
            )


# --------------------------------------------------------------------------
# T2:_call_progress 单调保护(直接调用)
# --------------------------------------------------------------------------

def test_call_progress_monotonic_protection():
    """T2:先发 pct=50,再发 pct=30,传出仍是 50(单调保护)。"""
    out: list[tuple[int, str]] = []
    rp = lambda pct, msg: out.append((int(pct), str(msg)))

    _call_progress(rp, 50, "half")
    _call_progress(rp, 30, "regression attempt")
    _call_progress(rp, 70, "advance")

    assert out == [(50, "half"), (50, "regression attempt"), (70, "advance")], (
        f"进度值不符合单调保护: {out}"
    )


def test_call_progress_none_safe():
    """T2b:_call_progress(rp=None, ...) 必须静默 no-op,不能抛。"""
    # 必须不抛任何异常
    _call_progress(None, 50, "no callback")
    _call_progress(None, 0, "")
    _call_progress(None, 100, "完成")


# --------------------------------------------------------------------------
# T3:_progress_cb 在 _progress=None 时不抛 AttributeError
# --------------------------------------------------------------------------

def test_main_window_progress_cb_none_safe():
    """T3:模拟 _progress=None 的竞态场景,_progress_cb 不应抛 AttributeError。"""
    from PySide6.QtWidgets import QApplication
    # 确保有 QApplication(若 _probe2 已创建会复用)
    _ = QApplication.instance() or QApplication(sys.argv)

    from app.ui.main_window import MainWindow
    w = MainWindow()
    # 默认 _progress 是 None
    assert w._progress is None

    # 必须不抛任何异常
    try:
        w._progress_cb(0, "")
        w._progress_cb(50, "阶段 1")
        w._progress_cb(100, "完成")
    except AttributeError as e:
        pytest.fail(f"V1.13.0 回归! _progress_cb(None) 抛 AttributeError: {e}")
    except Exception as e:
        # 其它异常(例如 RuntimeError)也属于修复范围外,不 fail 测试但记录
        pytest.fail(f"_progress_cb 抛非预期异常 {type(e).__name__}: {e}")


# --------------------------------------------------------------------------
# T4(额外):panel 内嵌进度条 widget 已实例化 + set_progress 可调用
# --------------------------------------------------------------------------

def test_panel_has_embedded_progress_bar_and_set_progress():
    """T4:panel 应在 _build_multi_attr_tab 中创建 attrib_progress_bar + attrib_status_label
    并暴露 set_progress(pct, msg) 方法。"""
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication(sys.argv)

    from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel
    p = ProcessAnalysisPanel()

    assert hasattr(p, "attrib_progress_bar"), "panel 缺 attrib_progress_bar"
    assert hasattr(p, "attrib_status_label"), "panel 缺 attrib_status_label"
    assert hasattr(p, "set_progress"), "panel 缺 set_progress 方法"

    # 验证进度条初值与范围
    bar = p.attrib_progress_bar
    assert bar.minimum() == 0
    assert bar.maximum() == 100
    assert bar.value() == 0
    # 默认隐藏(等 set_running 时再显)
    assert bar.isVisible() is False

    # 验证 set_progress(pct, msg) 真正写入
    p.set_progress(42, "M1 偏相关 2/4")
    assert bar.value() == 42
    assert p.attrib_status_label.text() == "M1 偏相关 2/4"

    # 边界:clamp 到 [0,100]
    p.set_progress(-5, "")
    assert bar.value() == 0
    p.set_progress(250, "")
    assert bar.value() == 100
