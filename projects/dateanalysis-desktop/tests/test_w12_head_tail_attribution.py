"""W12 机尾指数-s 归因引擎单元测试（纯函数，不依赖 Qt，offscreen 可跑）。"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd
import pytest

from app.services.head_tail_attribution import (
    AttributionCancelledError,
    build_head_tail_report,
)
from app.services.ai_prompt import build_head_tail_prompt


def _make_synthetic_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """构造合成长表：[机头]f1 强负相关指数-s，[机头]f2 噪声，[机头]f3 弱正相关。"""
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=n, freq="1min")
    f1 = rng.normal(50, 5, n)
    f2 = rng.normal(100, 10, n)
    f3 = rng.normal(0, 1, n)
    noise = rng.normal(0, 0.4, n)
    raw = 4.0 + 0.15 * (f1 - 50) + 0.2 * f3 + noise
    target = np.clip(np.round(raw), 1, 8).astype(int)
    df = pd.DataFrame({
        "时间": t,
        "[机头]f1": f1,
        "[机头]f2": f2,
        "[机头]f3": f3,
        "[机尾]指数-s": target,
    })
    return df


def test_build_head_tail_report_basic_structure():
    df = _make_synthetic_df(500)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10)
    assert "error" not in rpt, rpt.get("error")
    assert "meta" in rpt
    assert "target_dist" in rpt
    assert "attribution" in rpt
    assert "top_rules" in rpt
    assert "overall_suggested_window" in rpt
    meta = rpt["meta"]
    assert meta["n_rows"] == 500
    assert meta["n_head_features"] >= 3
    assert meta["target_col"] == "[机尾]指数-s"


def test_build_head_tail_report_correlation_ranking():
    """f1 应排前两位（强相关），f2 应在尾部（噪声）。"""
    df = _make_synthetic_df(1000, seed=42)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10)
    assert "error" not in rpt
    attrs = rpt["attribution"]
    names = [a["feature"] for a in attrs]
    assert names.index("[机头]f1") <= 1
    assert names.index("[机头]f2") >= len(names) - 2


def test_build_head_tail_report_rules_not_empty():
    df = _make_synthetic_df(800, seed=7)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10)
    assert "error" not in rpt
    rules = rpt["top_rules"]
    assert isinstance(rules, list)
    assert len(rules) > 0
    for r in rules[:3]:
        for k in ("feature", "threshold", "pct_near_ideal"):
            assert k in r, f"rule missing {k}: {r}"


def test_build_head_tail_report_min_samples_filter():
    """min_samples 很大时可能 rules 空，但不报错。"""
    df = _make_synthetic_df(200, seed=1)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=500)
    assert "error" not in rpt
    assert "top_rules" in rpt


def test_build_head_tail_report_no_head_cols():
    """C037-B: 原语义“没有 [机头] 列时拋 ValueError”已被 Owner #3 覆盖。
    新语义:没有任何数值特征列时拖 ValueError(GUI 层捕获后提示)。
    本例 df 仅有字符串列 + 目标列,无可用 feature,应拖 ValueError。
    """
    df = pd.DataFrame({
        "时间": pd.date_range("2024-01-01", periods=100, freq="1min"),
        "name": ["x"] * 100,
        "[机尾]指数-s": [4] * 100,
    })
    with pytest.raises(ValueError):
        build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=5)


def test_build_head_tail_report_no_target_col():
    df = pd.DataFrame({"a": [1,2,3], "[机头]x": [1,2,3]})
    with pytest.raises((KeyError, ValueError)):
        build_head_tail_report(df, target_col="不存在", min_samples=1)


def test_build_head_tail_report_cancelled():
    """cancel_event.set() 后应抛出 AttributionCancelledError。"""
    df = _make_synthetic_df(500, seed=99)
    ev = threading.Event()
    ev.set()
    with pytest.raises(AttributionCancelledError):
        build_head_tail_report(
            df, target_col="[机尾]指数-s", min_samples=10,
            cancel_event=ev,
        )
    try:
        build_head_tail_report(
            df, target_col="[机尾]指数-s", min_samples=10,
            cancel_event=ev,
        )
    except AttributionCancelledError as e:
        assert "已被用户取消" in str(e)


def test_build_head_tail_prompt_contains_keywords():
    df = _make_synthetic_df(500)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10)
    assert "error" not in rpt
    prompt = build_head_tail_prompt(rpt)
    assert "指数-s" in str(prompt)
    assert "机头" in str(prompt)
