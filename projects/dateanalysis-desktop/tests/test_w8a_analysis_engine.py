"""W8a 工艺分析引擎单测。

只使用代码构造的合成 DataFrame，严禁读取 E:\\项目\\ 下的真实数据。\n"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.process_analysis import (
    align_by_time,
    build_analysis_report,
    compute_feature_importance,
    compute_univariate_windows,
    fit_greedy_tree,
    infer_columns,
)


# ---------- 构造测试数据 ----------

def _make_synthetic_df(n: int = 600, seed: int = 42) -> pd.DataFrame:
    """构造一个已知分布的合成宽表：state=4 虎口距~N(380,15), state=5 ~N(430,20)。"""
    rng = np.random.default_rng(seed)
    states = rng.choice([3, 4, 5], size=n, p=[0.1, 0.55, 0.35])
    hk = np.where(
        states == 4, rng.normal(380, 15, n),
        np.where(states == 5, rng.normal(430, 20, n), rng.normal(400, 30, n)),
    )
    zz = np.where(
        states == 4, rng.normal(1020, 12, n),
        np.where(states == 5, rng.normal(1080, 14, n), rng.normal(1050, 25, n)),
    )
    t = pd.date_range("2025-01-01 09:00:00", periods=n, freq="500ms")
    wtm = rng.normal(50, 5, n)  # 未脱模-s 的列（应被默认排除）
    df = pd.DataFrame({
        "时间": t,
        "虎口距": hk,
        "中指距": zz,
        "指数-s": states.astype(np.int64),
        "未脱模-s": wtm,
        "拇指距": rng.normal(200, 10, n),
    })
    return df


# ---------- infer_columns ----------

def test_infer_columns_finds_time_state_features():
    df = _make_synthetic_df()
    info = infer_columns(df)
    assert info["time_col"] == "时间"
    assert info["state_col"] == "指数-s"
    assert "虎口距" in info["feature_cols"]
    assert "中指距" in info["feature_cols"]
    # 未脱模默认排除
    assert "未脱模-s" not in info["feature_cols"]
    # 状态列/时间列不进特征
    assert "时间" not in info["feature_cols"]
    assert "指数-s" not in info["feature_cols"]


def test_infer_columns_no_datetime_returns_none_time():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [0, 1, 1]})
    info = infer_columns(df)
    assert info["time_col"] is None
    # 两列都是低基数整数，关键词相同时按 nunique 少者优先；只要存在一个 state_col 即可
    assert info["state_col"] in {"a", "b"} or info["state_col"] is None


def test_infer_columns_keyword_priority():
    """含 '指数' 关键词的低基数列优先被选为状态列。"""
    df = pd.DataFrame({
        "t": pd.date_range("2025-01-01", periods=100, freq="s"),
        "虎口距": np.random.normal(380, 15, 100),
        "label": np.random.randint(0, 2, 100),
        "指数-s": np.random.randint(3, 6, 100),
    })
    info = infer_columns(df)
    assert info["state_col"] == "指数-s"


# ---------- align_by_time ----------

def test_align_by_time_nearest_basic():
    left = pd.DataFrame({
        "t": pd.date_range("2025-01-01", periods=5, freq="s"),
        "lv": [10, 20, 30, 40, 50],
    })
    right = pd.DataFrame({
        "rt": pd.to_datetime([
            "2025-01-01 00:00:00.500",
            "2025-01-01 00:00:02.600",
            "2025-01-01 00:00:04.400",
        ]),
        "rv": [1, 2, 3],
    })
    out = align_by_time(left, right, "t", "rt", tolerance_sec=1.0)
    # left 行全部保留，rv 就近匹配（tolerance ±1s）
    assert len(out) == 5
    # 第1行 (00:00:00) 最近 0.5s → rv=1
    assert out.loc[0, "rv"] == 1
    # 第2行 (00:00:01) 最近 0.5s 差 0.5s，但方向 nearest；0.5→1；2.6→2 差 1.6>1 → 无匹配 NaN
    assert np.isnan(out.loc[1, "rv"]) or out.loc[1, "rv"] == 1
    # 第3行 (00:00:02) 最近 2.6 差 0.6 → rv=2
    assert out.loc[2, "rv"] == 2


def test_align_by_time_raises_on_missing_column():
    left = pd.DataFrame({"t": [1], "lv": [1]})
    right = pd.DataFrame({"rt": [1], "rv": [1]})
    with pytest.raises(KeyError):
        align_by_time(left, right, "missing", "rt")


def test_align_by_time_suffix_avoids_conflict():
    left = pd.DataFrame({
        "t": pd.date_range("2025-01-01", periods=3, freq="s"),
        "v": [10, 20, 30],
    })
    right = pd.DataFrame({
        "rt": pd.date_range("2025-01-01", periods=3, freq="s"),
        "v": [1, 2, 3],
    })
    out = align_by_time(left, right, "t", "rt", tolerance_sec=1.0)
    assert "v" in out.columns
    assert "v_y" in out.columns


# ---------- compute_univariate_windows ----------

def test_univariate_windows_keys_and_ranges():
    df = _make_synthetic_df(n=800)
    res = compute_univariate_windows(df, ["虎口距", "中指距"], "指数-s", target_states=[4, 5])
    assert set(res.keys()) == {4, 5}
    for st in (4, 5):
        assert "features" in res[st]
        assert "虎口距" in res[st]["features"]
        feat = res[st]["features"]["虎口距"]
        assert feat["count"] > 0
        assert feat["p5"] <= feat["p50"] <= feat["p95"]
        lo1, hi1 = feat["window_1sigma"]
        lo2, hi2 = feat["window_2sigma"]
        assert lo2 <= lo1 <= feat["mean"] <= hi1 <= hi2
    # state=4 虎口距均值应接近 380，state=5 接近 430
    assert abs(res[4]["features"]["虎口距"]["mean"] - 380) < 8
    assert abs(res[5]["features"]["虎口距"]["mean"] - 430) < 10


def test_univariate_windows_marks_unreliable_small_samples():
    df = _make_synthetic_df(n=200)
    # 人为把 state=3 样本减少
    df.loc[df["指数-s"] == 3, "指数-s"] = 4
    df.loc[0:2, "指数-s"] = 99  # 仅 3 个样本
    res = compute_univariate_windows(df, ["虎口距"], "指数-s", target_states=[4, 99], min_samples=30)
    assert res[99]["unreliable"] is True
    assert res[4]["unreliable"] is False


def test_univariate_windows_ignores_nan():
    df = _make_synthetic_df(n=300)
    df.loc[0:20, "虎口距"] = np.nan
    res = compute_univariate_windows(df, ["虎口距"], "指数-s", target_states=[4, 5])
    # state 4 应仍有足够样本
    assert res[4]["features"]["虎口距"]["count"] > 0


# ---------- fit_greedy_tree ----------

def test_fit_tree_finds_high_precision_rule_on_separable_data():
    rng = np.random.default_rng(0)
    n = 600
    hk = np.concatenate([rng.normal(380, 8, n // 2), rng.normal(430, 8, n // 2)])
    st = np.array([4] * (n // 2) + [5] * (n // 2))
    df = pd.DataFrame({"虎口距": hk, "中指距": rng.normal(1000, 30, n), "指数-s": st})
    rules4 = fit_greedy_tree(df, ["虎口距", "中指距"], "指数-s", target_state=4, max_depth=2, min_samples_leaf=30)
    assert rules4, "应产出至少一条规则"
    # 最高 precision 的规则应该 > 0.9
    top = max(rules4, key=lambda r: r["precision"])
    assert top["precision"] > 0.9
    assert top["support"] >= 30


def test_fit_tree_returns_empty_when_no_positive():
    df = pd.DataFrame({"a": np.random.normal(0, 1, 100), "s": [0] * 100})
    rules = fit_greedy_tree(df, ["a"], "s", target_state=1)
    assert rules == []


def test_fit_tree_conditions_have_expected_keys():
    df = _make_synthetic_df(n=500)
    rules = fit_greedy_tree(df, ["虎口距", "中指距"], "指数-s", target_state=4, max_depth=2, min_samples_leaf=20)
    for r in rules:
        assert set(r.keys()) >= {"conditions", "support", "precision", "recall", "state"}
        for c in r["conditions"]:
            assert c["op"] in ("<=", ">")
            assert isinstance(c["threshold"], float)


# ---------- feature importance ----------

def test_feature_importance_separable_feature_has_higher_f():
    rng = np.random.default_rng(1)
    n = 400
    hk = np.concatenate([rng.normal(380, 5, n // 2), rng.normal(430, 5, n // 2)])
    noise = rng.normal(0, 100, n)  # 与 state 无关
    st = np.array([4] * (n // 2) + [5] * (n // 2))
    df = pd.DataFrame({"虎口距": hk, "noise": noise, "指数-s": st})
    imp = compute_feature_importance(df, ["虎口距", "noise"], "指数-s")
    assert imp[0][0] == "虎口距"
    assert imp[0][1] > imp[1][1] * 2  # 可分特征 F 值显著更高


def test_feature_importance_ignores_nan():
    df = _make_synthetic_df(n=300)
    df.loc[0:20, "虎口距"] = np.nan
    imp = compute_feature_importance(df, ["虎口距", "中指距"], "指数-s")
    assert len(imp) == 2
    assert all(f >= 0 for _, f in imp)


# ---------- build_analysis_report ----------

def test_build_report_end_to_end_structure():
    df = _make_synthetic_df(n=500)
    rpt = build_analysis_report(df)
    assert "error" not in rpt, rpt.get("error")
    assert "summary" in rpt
    assert "univariate" in rpt
    assert "rules" in rpt
    assert "feature_importance" in rpt
    meta = rpt["meta"]
    assert meta["n_rows"] == 500
    assert meta["state_col"] == "指数-s"
    assert "虎口距" in meta["feature_cols"]


def test_build_report_warns_on_small_samples():
    df = _make_synthetic_df(n=200)
    # 增加一个稀有状态
    df.loc[0:3, "指数-s"] = 99
    rpt = build_analysis_report(df, min_samples=30)
    assert "error" not in rpt
    joined = " ".join(rpt["meta"]["warnings"])
    assert "99" in joined
    assert "不可靠" in joined


def test_build_report_min_samples_filter_flags_state():
    df = _make_synthetic_df(n=300)
    df.loc[0:2, "指数-s"] = 77
    rpt = build_analysis_report(df, min_samples=30)
    summary = rpt["summary"]
    assert "77" in summary
    assert summary["77"]["unreliable"] is True


def test_build_report_returns_error_when_no_state_col():
    df = pd.DataFrame({"a": np.random.normal(0, 1, 50), "b": np.random.normal(0, 1, 50)})
    rpt = build_analysis_report(df)
    # 没有低基数整数列，应该报 error
    assert "error" in rpt


def test_build_report_empty_df_returns_error():
    rpt = build_analysis_report(pd.DataFrame())
    assert "error" in rpt


def test_build_report_target_states_subset():
    df = _make_synthetic_df(n=400)
    rpt = build_analysis_report(df, target_states=[4])
    # 摘要含所有 state，但 univariate/rules 只含 4
    assert "4" in rpt["univariate"]
    assert "5" not in rpt["univariate"]
    assert "4" in rpt["rules"]
