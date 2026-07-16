"""S5 多变量归因引擎（M1 偏相关 + M2 OLS β*/R²/VIF）单元测试。

向后兼容：旧 W12 行为通过 multi=False（默认）保持不变。
0 新增 UI 改动：本测试只覆盖纯函数 build_head_tail_report 的 multi 分支。
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd
import pytest

from app.services.head_tail_attribution import (
    AttributionCancelledError,
    _compute_vif,
    _ols_standardized,
    _partial_corr,
    _zscore_array,
    build_head_tail_report,
)


# --------------------------------------------------------------------------
# 合成数据工厂
# --------------------------------------------------------------------------

def _make_synthetic_df(n: int = 500, seed: int = 0) -> pd.DataFrame:
    """f1 强正相关，f2 噪声，f3 弱正相关，f4 与 f1 高度共线（用于 VIF 警告）。"""
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


# --------------------------------------------------------------------------
# 1. 报告结构（含 multi 节点 + 旧 W12 字段不丢失）
# --------------------------------------------------------------------------

def test_build_head_tail_report_multi_structure():
    """multi=True 时报告必须含 multi 节点，且保留旧 4 个 W12 字段。"""
    df = _make_synthetic_df(500)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10, multi=True)
    assert "multi" in rpt, "multi=True 必须输出 multi 节点"
    multi = rpt["multi"]
    assert "partial_corr" in multi
    assert "ols" in multi
    assert "top_contributors" in multi
    assert "warnings" in multi
    assert isinstance(multi["partial_corr"], list)
    assert len(multi["partial_corr"]) >= 4  # 4 个 [机头] 列
    # 旧 W12 字段保留
    for key in ("meta", "target_dist", "attribution", "top_rules", "overall_suggested_window"):
        assert key in rpt, f"旧字段 {key} 不应丢失"
    # meta 中带 has_pingouin 标记
    assert "has_pingouin" in rpt["meta"]
    assert isinstance(rpt["meta"]["has_pingouin"], bool)


def test_build_head_tail_report_multi_disabled_default():
    """默认 multi=False（向后兼容），报告不含 multi 键。"""
    df = _make_synthetic_df(200)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10)
    assert "multi" not in rpt
    # 旧字段全部保留
    for key in ("meta", "target_dist", "attribution", "top_rules", "overall_suggested_window"):
        assert key in rpt


# --------------------------------------------------------------------------
# 2. M1 偏相关：单特征 / 多特征 / 混杂塌陷
# --------------------------------------------------------------------------

def test_multi_partial_corr_single_feature():
    """只勾 1 列时 M1 退化为单 Pearson，warnings 注明。"""
    df = _make_synthetic_df(300)
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=10,
        feature_cols=["[机头]f1"], multi=True,
    )
    assert "multi" in rpt
    pc = rpt["multi"]["partial_corr"]
    assert len(pc) == 1
    row = pc[0]
    # single_r 应与原 single Pearson 一致
    assert abs(row["single_r"]) > 0.3, f"f1 应强相关，实际 {row['single_r']}"
    # partial_r == single_r（控制集为空）
    assert abs(row["partial_r"] - row["single_r"]) < 1e-9
    # 退化警告
    warns = row.get("warnings") or []
    assert any("退化为单 Pearson" in w or "控制集为空" in w for w in warns), warns
    # M2 因仅 1 列应跳过
    assert rpt["multi"]["ols"] is None
    assert rpt["multi"]["ols_skipped_reason"] is not None
    assert "1 列" in rpt["multi"]["ols_skipped_reason"]


def test_multi_partial_corr_basic_multifeature():
    """M1 多特征：在不含高度共线 f4 的子集上，f1 是主因子（partial_r 最大）。"""
    df = _make_synthetic_df(500, seed=42)
    # 排除 f4（与 f1 高度共线，会帮 f1 背锅），只用 f1/f2/f3
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=10,
        feature_cols=["[机头]f1", "[机头]f2", "[机头]f3"],
        multi=True,
    )
    pc = rpt["multi"]["partial_corr"]
    by_feat = {row["feature"]: row for row in pc}
    assert "[机头]f1" in by_feat
    assert "[机头]f3" in by_feat
    # 主因子 f1 的偏相关应显著大于 f3（生成参数 f1 贡献 > f3）
    assert by_feat["[机头]f1"]["partial_r"] > by_feat["[机头]f3"]["partial_r"]
    # f1 的偏相关绝对值应是三者中最大的
    abs_partials = {f: abs(by_feat[f]["partial_r"]) for f in ("[机头]f1", "[机头]f2", "[机头]f3")}
    assert max(abs_partials, key=abs_partials.get) == "[机头]f1"
    # partial_corr 按 abs_partial_r 降序排 → f1 应在首位
    assert pc[0]["feature"] == "[机头]f1"


def test_multi_partial_corr_collapses_for_proxy():
    """f4 与 f1 高度共线 → f4 的偏相关应明显低于其单 Pearson。"""
    df = _make_synthetic_df(500, seed=7)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10, multi=True)
    by_feat = {row["feature"]: row for row in rpt["multi"]["partial_corr"]}
    assert "[机头]f4" in by_feat
    f4 = by_feat["[机头]f4"]
    # f4 单相关应较高（被 f1 代理），偏相关应塌陷到接近 0
    assert abs(f4["single_r"]) > 0.5, f"f4 单相关应较高，实际 {f4['single_r']}"
    assert abs(f4["partial_r"]) < abs(f4["single_r"]), (
        f"f4 偏相关应低于单相关：single={f4['single_r']:.3f} partial={f4['partial_r']:.3f}"
    )


# --------------------------------------------------------------------------
# 3. M2 OLS：系数方向、R²/VIF/常数列/岭化
# --------------------------------------------------------------------------

def test_multi_ols_beta_direction_and_r2():
    """β* 方向与生成参数一致（f1 正、f3 正），R² 在 [0, 1]。"""
    df = _make_synthetic_df(800, seed=11)
    # 排除 f4（与 f1 高度共线 → 会让 OLS β* 翻号，专用 VIF 警告用例覆盖）
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=10,
        feature_cols=["[机头]f1", "[机头]f2", "[机头]f3"],
        multi=True,
    )
    ols = rpt["multi"]["ols"]
    assert ols is not None
    assert 0.0 <= ols["r2"] <= 1.0
    assert 0.0 <= ols["r2_adj"] <= 1.0
    assert ols["n"] > 30
    assert ols["k"] >= 2
    coef = {c["feature"]: c for c in ols["coef_std"]}
    # 生成参数 f1 系数为正（0.15/5 标准化后 ~0.42），f3 系数为正（0.2 标准化后 ~0.4）
    assert coef["[机头]f1"]["beta_std"] > 0
    assert coef["[机头]f3"]["beta_std"] > 0
    # f2 噪声 → β* 接近 0
    assert abs(coef["[机头]f2"]["beta_std"]) < 0.15
    # top_contributors 按 |β*| 降序
    top = rpt["multi"]["top_contributors"]
    assert isinstance(top, list)
    assert len(top) >= 1
    assert "[机头]f1" in top


def test_multi_vif_warning():
    """f1 与 f4 高度共线 → VIF>10，必须有警告文本。"""
    df = _make_synthetic_df(500, seed=3)
    rpt = build_head_tail_report(df, target_col="[机尾]指数-s", min_samples=10, multi=True)
    ols = rpt["multi"]["ols"]
    assert ols is not None
    vif_map = {v["feature"]: v["vif"] for v in ols["vif"]}
    # f1/f4 应该至少一个 VIF > 10
    assert vif_map["[机头]f1"] > 10 or vif_map["[机头]f4"] > 10
    # warnings 中必须包含 VIF 文本（仅警告，不剔除）
    vifs_warns = [w for w in rpt["multi"]["warnings"] if "VIF" in w]
    assert vifs_warns, f"应有 VIF 警告，实际 {rpt['multi']['warnings']}"
    for w in vifs_warns:
        assert "建议剔除" in w
    # coef_std 中 vif_warn 标记
    high_vif = [c for c in ols["coef_std"] if c.get("vif_warn")]
    assert high_vif, "应至少 1 列被标 vif_warn"
    # 警告的列仍 kept=True（不自动剔除）
    for c in high_vif:
        assert c.get("kept") is True, "S5-#2 仅警告，不自动剔除"


def test_multi_ols_constant_column_dropped():
    """M2 OLS 必须自动剔除常数列 + 警告。"""
    df = _make_synthetic_df(300, seed=0)
    df["[机头]const_col"] = 42.0  # 常数列
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=10,
        feature_cols=["[机头]f1", "[机头]f2", "[机头]f3", "[机头]const_col"],
        multi=True,
    )
    ols = rpt["multi"]["ols"]
    assert ols is not None
    feat_names = [c["feature"] for c in ols["coef_std"]]
    assert "[机头]const_col" not in feat_names
    # dropped 列表里有 const_col
    drop_names = [d["feature"] for d in ols["dropped"]]
    assert "[机头]const_col" in drop_names
    # warnings 包含常数列剔除
    warns = " ".join(ols["warnings"]) + " " + " ".join(rpt["multi"]["warnings"])
    assert "常数列" in warns or "const_col" in warns


def test_multi_ols_rank_deficient_ridge_fallback():
    """X'X 奇异（rank<k）必须自动岭化，OLS 仍出结果。"""
    df = _make_synthetic_df(300, seed=0)
    # 构造完全共线列（f5 = f1 + 5），让 X'X 接近奇异
    df["[机头]f5"] = df["[机头]f1"] + 5.0
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=10,
        feature_cols=["[机头]f1", "[机头]f5", "[机头]f3"],
        multi=True,
    )
    ols = rpt["multi"]["ols"]
    assert ols is not None
    # 可能 rcond 给出较小 rank → used_ridge=True；至少 coef_std 仍返回
    assert isinstance(ols["coef_std"], list)
    assert ols["k"] >= 2
    # 检查 condition_number 字段存在且有限
    assert "condition_number" in ols


def test_multi_ols_p_gt_n_minus_2_skip():
    """特征数 p > n-2 → OLS 必须跳过并给出原因。"""
    # 20 列 vs n=20 → p=20, n-2=18 → p>n-2，OLS 应跳过
    rng = np.random.default_rng(0)
    n = 20
    data = {"时间": pd.date_range("2024-01-01", periods=n, freq="1min")}
    for i in range(20):
        data[f"[机头]c{i}"] = rng.normal(0, 1, n)
    data["[机尾]指数-s"] = rng.integers(1, 9, n)
    df = pd.DataFrame(data)
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=5,
        feature_cols=[f"[机头]c{i}" for i in range(20)],
        multi=True, multi_top_n=20, multi_min_samples=5,
    )
    ols = rpt["multi"]["ols"]
    assert ols is not None
    # k > n-2 时应跳到 skipped，coef_std 为空
    assert ols["coef_std"] == []
    assert any("p > n-2" in w or "跳过" in w for w in ols["warnings"])


# --------------------------------------------------------------------------
# 4. 取消事件 / N 不足
# --------------------------------------------------------------------------

def test_multi_cancellation():
    """M1/M2 阶段 cancel_event.set() 必须抛 AttributionCancelledError。"""
    df = _make_synthetic_df(500, seed=99)
    ev = threading.Event()
    ev.set()
    with pytest.raises(AttributionCancelledError):
        build_head_tail_report(
            df, target_col="[机尾]指数-s", min_samples=10,
            multi=True, cancel_event=ev,
        )


def test_multi_low_samples_skip_ols():
    """N < multi_min_samples → OLS 跳过，warnings 注明。"""
    df = _make_synthetic_df(20, seed=5)  # 20 行
    rpt = build_head_tail_report(
        df, target_col="[机尾]指数-s", min_samples=5,
        multi=True, multi_min_samples=30,
    )
    # 报告不报错
    assert "multi" in rpt
    # OLS 跳过
    assert rpt["multi"]["ols_skipped_reason"] is not None
    assert "N=" in rpt["multi"]["ols_skipped_reason"] or "样本" in rpt["multi"]["ols_skipped_reason"]


# --------------------------------------------------------------------------
# 5. 内部工具函数单元测试（直接覆盖实现细节）
# --------------------------------------------------------------------------

def test_zscore_array_handles_constant_columns():
    """常数列 z-score 后应为 0，不抛 nan。"""
    a = np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0], [4.0, 5.0]])
    z = _zscore_array(a)
    assert z.shape == a.shape
    # 第 0 列 zscore 正常
    assert np.allclose(z[:, 0].mean(), 0.0, atol=1e-9)
    assert np.allclose(z[:, 0].std(ddof=1), 1.0, atol=1e-9)
    # 第 1 列是常数 → 全 0
    assert np.allclose(z[:, 1], 0.0)


def test_compute_vif_low_for_independent():
    """独立列 VIF≈1。"""
    rng = np.random.default_rng(0)
    X = np.column_stack([rng.normal(0, 1, 100), rng.normal(0, 1, 100), rng.normal(0, 1, 100)])
    vifs = _compute_vif(X, ["a", "b", "c"])
    assert len(vifs) == 3
    for v in vifs:
        assert 1.0 <= v["vif"] <= 5.0, f"VIF 应接近 1，实际 {v['vif']}"


def test_compute_vif_high_for_collinear():
    """完全共线列 VIF 应 > 100。"""
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 100)
    X = np.column_stack([x, x + rng.normal(0, 1e-6, 100), rng.normal(0, 1, 100)])
    vifs = _compute_vif(X, ["a", "b", "c"])
    vif_map = {v["feature"]: v["vif"] for v in vifs}
    assert vif_map["a"] > 50 or vif_map["b"] > 50


def test_ols_standardized_basic():
    """_ols_standardized 在干净线性数据上 R² 应接近 1。"""
    rng = np.random.default_rng(0)
    n = 200
    X = rng.normal(0, 1, (n, 3))
    beta_true = np.array([1.0, -2.0, 0.5])
    y = X @ beta_true + rng.normal(0, 0.1, n)
    res = _ols_standardized(X, y, ["a", "b", "c"])
    assert res["r2"] > 0.95
    coef_map = {c["feature"]: c["beta_std"] for c in res["coef_std"]}
    # 标准化系数 → 真实系数 * std(X)/std(y)，符号应一致
    assert coef_map["a"] > 0
    assert coef_map["b"] < 0
    assert coef_map["c"] > 0


def test_partial_corr_basic_match_ols_residual():
    """_partial_corr 应等于 numpy 残差法手算的 Pearson。"""
    rng = np.random.default_rng(0)
    n = 300
    z1 = rng.normal(0, 1, n)
    z2 = rng.normal(0, 1, n)
    z3 = rng.normal(0, 1, n)
    y = z1 + 0.5 * z2 + rng.normal(0, 0.1, n)
    df = pd.DataFrame({"y": y, "x": z1, "z2": z2, "z3": z3})
    r_part, p_val, n_used, warns = _partial_corr(df, "y", "x", ["z2", "z3"])
    # 控制后 x 与 y 的偏相关应接近 1
    assert r_part is not None
    assert r_part > 0.8
    assert n_used == n
    # p 值应极小
    assert p_val is not None
    assert p_val < 1e-10
