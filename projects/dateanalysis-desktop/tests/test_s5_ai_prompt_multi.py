"""S5 AI 解读覆盖多变量归因（C037-A）。

覆盖 build_head_tail_prompt 在 multi 节点存在/缺失/VIF 警告时的渲染行为。

T1: 有 multi 节点 → prompt 含 "偏相关" / "OLS" / "VIF" 三个关键词
T2: 无 multi 节点 → prompt 不含 "偏相关" / "OLS"（向后兼容 W12 单变量模板）
T3: multi["warnings"] 含 VIF 警告 → prompt 含 "⚠ VIF"
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.ai_prompt import build_head_tail_prompt
from app.services.head_tail_attribution import build_head_tail_report


# --------------------------------------------------------------------------
# 合成数据工厂（与 test_s5_multi_attribution.py 一致）
# --------------------------------------------------------------------------

def _make_synthetic_df(n: int = 500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = pd.date_range("2024-01-01", periods=n, freq="1min")
    f1 = rng.normal(50, 5, n)
    f2 = rng.normal(100, 10, n)
    f3 = rng.normal(0, 1, n)
    f4 = f1 + rng.normal(0, 0.05, n)
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


def _user_text(messages: list[dict]) -> str:
    """仅取 user message 的 content（系统提示会预设 6 段式结构指引）。"""
    return "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")


def _sys_text(messages: list[dict]) -> str:
    """仅取 system message 的 content。"""
    return "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")


# --------------------------------------------------------------------------
# T1: multi 节点存在时，prompt 必须含三个核心关键词
# --------------------------------------------------------------------------

def test_prompt_with_multi_contains_keywords():
    """multi=True → build_head_tail_prompt user prompt 必须渲染 M1/M2/VIF 三个段。"""
    df = _make_synthetic_df(500, seed=1)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10, multi=True)
    assert "multi" in rpt, "前置：multi=True 必须产出 multi 节点"

    msgs = build_head_tail_prompt(rpt)
    user = _user_text(msgs)
    sys_msg = _sys_text(msgs)

    # user prompt 中必须渲染三个段位
    assert "M1 偏相关" in user, "M1 偏相关段位应出现"
    assert "M2 OLS" in user, "M2 OLS β* 段位应出现"
    assert "VIF" in user, "VIF 警告 / 表头应出现"

    # system prompt 必须升级到 6 段式
    assert "共线性风险" in sys_msg, "系统提示应扩展为 6 段式（共线性风险）"
    assert "下一步可执行建议" in sys_msg


# --------------------------------------------------------------------------
# T2: 无 multi 节点时，prompt 不含 M1/M2 段（向后兼容 W12 测试）
# --------------------------------------------------------------------------

def test_prompt_without_multi_backward_compat():
    """multi=False（默认） → user prompt 不应渲染多变量段，保留 W12 单变量行为。"""
    df = _make_synthetic_df(300, seed=2)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10)
    assert "multi" not in rpt, "前置：默认 multi=False 不应产出 multi 节点"

    msgs = build_head_tail_prompt(rpt)
    user = _user_text(msgs)
    sys_msg = _sys_text(msgs)

    # user prompt 不渲染多变量段
    assert "偏相关" not in user, "无 multi 时 user prompt 不应出现「偏相关」段"
    assert "OLS" not in user, "无 multi 时 user prompt 不应出现「OLS β*」段"
    assert "VIF" not in user, "无 multi 时 user prompt 不应出现「VIF」"

    # 老 W12 单变量段必须保留（防回归）
    assert "Top 10 机头特征相关系数表" in user
    assert "综合建议工艺窗口" in user

    # system prompt 仍然升级为 6 段式（指南描述，不依赖是否有 multi 数据）
    assert "共线性风险" in sys_msg


# --------------------------------------------------------------------------
# T3: multi 含 VIF 警告时，prompt 必须含显眼标记 "⚠ VIF"
# --------------------------------------------------------------------------

def test_prompt_multi_vif_warning_visible():
    """f1/f4 高度共线 → multi.warnings 含 VIF → user prompt 必须含「⚠ VIF」显眼提示。"""
    df = _make_synthetic_df(500, seed=3)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10, multi=True)
    assert "multi" in rpt

    # 前置：引擎应已生成 VIF 警告
    assert any("VIF" in w for w in rpt["multi"].get("warnings", [])), \
        "前置：f1/f4 共线应触发 VIF 警告"

    msgs = build_head_tail_prompt(rpt)
    user = _user_text(msgs)
    assert "⚠ VIF" in user, "VIF 警告必须在 user prompt 显眼位置出现"


# --------------------------------------------------------------------------
# T4（额外兜底）：缺字段时静默跳过，不抛异常
# --------------------------------------------------------------------------

def test_prompt_multi_with_minimal_schema_no_crash():
    """仅构造 partial_corr（无 ols） → 应渲染 M1 段，跳过 M2，不抛异常。"""
    rpt = {
        "meta": {"n_rows": 100, "target_col": "[机尾]指数-s", "ideal_value": 4.0, "warnings": []},
        "target_dist": {},
        "attribution": [],
        "top_rules": [],
        "overall_suggested_window": {},
        "multi": {
            "partial_corr": [
                {"feature": "[机头]f1", "n": 100, "single_r": 0.5, "partial_r": 0.4},
            ],
            "ols": None,
            "top_contributors": ["[机头]f1"],
            "ols_skipped_reason": "仅勾选 1 列，跳过 OLS（p<k）",
            "vif_warn_threshold": 10.0,
            "warnings": ["仅勾选 1 列，跳过 OLS（p<k）"],
        },
    }
    msgs = build_head_tail_prompt(rpt)
    user = _user_text(msgs)
    assert "M1 偏相关" in user
    assert "跳过" in user  # OLS 跳过原因
    assert "⚠ VIF" not in user  # 无 VIF 警告


def test_prompt_multi_with_ols_only_no_partial():
    """仅 ols 无 partial_corr → user prompt 跳过 M1，仅渲染 M2。"""
    rpt = {
        "meta": {"n_rows": 200, "target_col": "[机尾]指数-s", "ideal_value": 4.0, "warnings": []},
        "target_dist": {},
        "attribution": [],
        "top_rules": [],
        "overall_suggested_window": {},
        "multi": {
            "partial_corr": [],
            "ols": {
                "r2": 0.42, "r2_adj": 0.39, "n": 200, "k": 3,
                "coef_std": [
                    {"feature": "[机头]f1", "beta_std": 0.42, "abs_beta_std": 0.42,
                     "vif": 3.1, "vif_warn": False, "kept": True},
                ],
                "vif": [{"feature": "[机头]f1", "vif": 3.1}],
                "warnings": [],
                "dropped": [],
                "used_ridge": False,
            },
            "top_contributors": ["[机头]f1"],
            "ols_skipped_reason": None,
            "vif_warn_threshold": 10.0,
            "warnings": [],
        },
    }
    msgs = build_head_tail_prompt(rpt)
    user = _user_text(msgs)
    assert "OLS" in user
    # M1 段无数据 → user prompt 中不应渲染偏相关表
    # 注意：system prompt 仍含"偏相关"指引，所以只看 user
    assert "M1 偏相关（控制其它头部列后的净相关）：" not in user, \
        "partial_corr 为空时 user prompt 不应渲染 M1 段表头"
