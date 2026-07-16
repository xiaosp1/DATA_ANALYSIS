# -*- coding: utf-8 -*-
"""C050 P0A 修复单测：折线图多小图模式 (chart_panel._plot_small_multiples) 入口降采样。

C049 根因报告指出, 折线图多小图模式 (show_points=True) 在 n=百万级时, 主线程串行
渲染 10 个子图 × 30,000 点 ≈ 30 万个 curve segment 卡死 UI (与 C046 chart3 LOESS
卡死同源主线程串行问题)。C050 P0A 修复: 在 _plot_small_multiples 每个 y_col 子图
入口加 MAX_RENDER_POINTS=5000 阈值, n>5000 时降采样到 5000 点, xs/ys/x_labels
三者同步降采样 (复用 C048 _downsample_for_render helper, 同一组采样点 + np.sort
回原顺序), 折线图路径 (曲线 + 散点) 共用同一组采样点 (避免"对不上")。

与 C048 的区别:
  - C048 修 chart3 单子图 (pyqtgraph PlotItem + LOESS trend)
  - C050 修折线图多小图模式 (chart_panel._plot_small_multiples, 多个子图串行渲染)
  - 两者**复用同一份** _downsample_for_render helper (从 process_analysis_panel import),
    阈值都是 MAX_RENDER_POINTS=5000, 避免代码冗余 + 阈值漂移。

本测试覆盖 (≥3 用例):
  T1  n<=5000 时**不**降采样 (输入/输出严格相等, n_orig 透传) —— 同时验证
      chart_panel.MAX_RENDER_POINTS 与 process_analysis_panel.MAX_RENDER_POINTS 是
      同一个对象 (避免阈值漂移)
  T2  n=10000 时降采样, x / y / x_labels 三者保持索引对应 (散点 + 折线 + x 轴 label
      视觉一致, DoD "折线图路径共用同一组采样点")
  T3  n=100000 降采样到 5000 后, matplotlib 单子图 plot 应 < 100ms (vs 原 n=100000)
      —— 用 matplotlib 模拟 pyqtgraph 折线图渲染入口开销 (pyqtgraph 在 offscreen
      Qt 环境下 render 实际耗时不易测, matplotlib 单图 plot 是更稳定的代理指标)

测试策略:
  - 仅 import chart_panel.py 模块级 helper (_downsample_with_labels, MAX_RENDER_POINTS)
  - 不依赖 Qt (matplotlib backend 用 'Agg', CI 友好)
  - 不修改 chart_panel.py / process_analysis_panel.py 行为 (仅验证 helper)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pytest


# --------------------------------------------------------------------------
# helper imports
# --------------------------------------------------------------------------

def _import_helper():
    """延迟 import: 走 chart_panel.py 的模块级 helper (它本身已 import 复用
    process_analysis_panel 的 helper)。"""
    from app.ui.widgets.chart_panel import (
        MAX_RENDER_POINTS,
        _downsample_with_labels,
    )
    # 顺便比对 process_analysis_panel 的常量是否是同一对象 (避免阈值漂移)
    from app.ui.widgets.process_analysis_panel import MAX_RENDER_POINTS as MAX_RENDER_POINTS_PAP
    return MAX_RENDER_POINTS, _downsample_with_labels, MAX_RENDER_POINTS_PAP


# --------------------------------------------------------------------------
# T1: n <= MAX_RENDER_POINTS 时不降采样 + 跨模块阈值一致
# --------------------------------------------------------------------------

def test_downsampling_disabled_when_n_below_threshold():
    """T1: n=100 时**不**触发降采样——输入 x/y/x_labels 与输出严格相等, 原 n 透传。

    设计意图: 小样本场景 (n<=5000) 跳过降采样避免无谓丢失, 也保证 DoD 说的
    "n<=5000 时**不**降采样" 显式约束。同时验证 chart_panel.MAX_RENDER_POINTS
    与 process_analysis_panel.MAX_RENDER_POINTS 是同一对象 (避免阈值漂移)。
    """
    MAX_RENDER_POINTS, _downsample_with_labels, MAX_RENDER_POINTS_PAP = _import_helper()
    # 跨模块常量必须一致 (防止后续一边改了忘了另一边)
    assert MAX_RENDER_POINTS is MAX_RENDER_POINTS_PAP, (
        f"chart_panel.MAX_RENDER_POINTS={MAX_RENDER_POINTS} 应是 process_analysis_panel"
        f".MAX_RENDER_POINTS={MAX_RENDER_POINTS_PAP} 的同一对象 (避免阈值漂移)"
    )
    # 边界: n=MAX_RENDER_POINTS 也应**不**降采样 (<= 不 <)
    rng = np.random.default_rng(0)
    for n in (10, 100, 1000, MAX_RENDER_POINTS):
        x = rng.normal(0, 1, n).astype(float)
        y = rng.normal(0, 1, n).astype(float)
        labels = np.array([f"L{i}" for i in range(n)], dtype=object)
        x_ds, y_ds, labels_ds, n_orig = _downsample_with_labels(x, y, labels)
        # 输入严格不变
        assert len(x_ds) == n, f"n={n} 应原样返回 xs, got len={len(x_ds)}"
        assert len(y_ds) == n, f"n={n} 应原样返回 ys, got len={len(y_ds)}"
        assert len(labels_ds) == n, f"n={n} 应原样返回 labels, got len={len(labels_ds)}"
        np.testing.assert_array_equal(x_ds, x, err_msg=f"n={n} x 内容被改")
        np.testing.assert_array_equal(y_ds, y, err_msg=f"n={n} y 内容被改")
        np.testing.assert_array_equal(labels_ds, labels, err_msg=f"n={n} labels 内容被改")
        # 原 n 透传
        assert n_orig == n, f"n_orig 应透传 {n}, got {n_orig}"


# --------------------------------------------------------------------------
# T2: n > MAX_RENDER_POINTS 时降采样, x / y / x_labels 三者索引对应
# --------------------------------------------------------------------------

def test_downsampling_keeps_correspondence():
    """T2: n=10000 时降采样到 5000, x / y / x_labels 三者必须保留一一对应
    (DoD "折线图路径共用同一组采样点, 避免均值线和散点对不上")。

    关键不变量:
      1. 输出长度 = MAX_RENDER_POINTS (=5000)
      2. 每个采样点的 (x[i], y[i], label[i]) 都来自原始输入同一索引
         (不能散点取 idx_a, label 取 idx_b, 否则 x 轴 tick 会对不上散点)
      3. 索引按原始顺序排序 (np.sort) —— 既利于散点视觉顺序与原始数据点序列一致,
         也与 C048 helper 行为一致 (LOESS / np.argsort 内部会再排)
      4. 同一 seed=42 下输出可复现
    """
    MAX_RENDER_POINTS, _downsample_with_labels, _ = _import_helper()
    rng = np.random.default_rng(123)
    n_orig = 10_000
    x = rng.normal(0, 1, n_orig).astype(float)
    y = (0.7 * x + rng.normal(0, 0.3, n_orig)).astype(float)
    labels = np.array([f"L{i}" for i in range(n_orig)], dtype=object)

    x_ds, y_ds, labels_ds, n_back = _downsample_with_labels(x, y, labels)

    # (1) 长度正确
    assert len(x_ds) == MAX_RENDER_POINTS, (
        f"降采样后 x_ds 长度应={MAX_RENDER_POINTS}, got {len(x_ds)}"
    )
    assert len(y_ds) == MAX_RENDER_POINTS
    assert len(labels_ds) == MAX_RENDER_POINTS
    assert n_back == n_orig, f"n_orig 应透传 {n_orig}, got {n_back}"

    # (2) 对应关系: 构造映射 (x[i], y[i]) 对照 + label 索引
    orig_pairs = set(zip(x.tolist(), y.tolist()))
    ds_pairs = list(zip(x_ds.tolist(), y_ds.tolist()))
    assert len(ds_pairs) == MAX_RENDER_POINTS
    assert all(p in orig_pairs for p in ds_pairs), (
        "降采样点 (x, y) 应一一对应原数据, 出现不在原集合的 (x, y) 对"
    )

    # (3) label 必须按原始索引取样 (用 label 内容判断: L0..L9999 中选 5000 个)
    # 因为 label 唯一 (L0..L9999), 降采样后的 label 集合应等于原始 label 集合的子集
    orig_label_set = set(labels.tolist())
    ds_label_set = set(labels_ds.tolist())
    assert ds_label_set.issubset(orig_label_set), (
        f"降采样 label 集合 ({len(ds_label_set)} 个) 应是原始 ({len(orig_label_set)} 个) 的子集"
    )
    assert len(ds_label_set) == MAX_RENDER_POINTS, (
        f"label 唯一时降采样后应保留 {MAX_RENDER_POINTS} 个不同 label, got {len(ds_label_set)}"
    )

    # (4) 可复现: 同样输入+seed 两次应一致
    x_ds2, y_ds2, labels_ds2, _ = _downsample_with_labels(x, y, labels)
    np.testing.assert_array_equal(x_ds, x_ds2, err_msg="同 seed 第二次跑 x 应一致")
    np.testing.assert_array_equal(y_ds, y_ds2, err_msg="同 seed 第二次跑 y 应一致")
    np.testing.assert_array_equal(labels_ds, labels_ds2, err_msg="同 seed 第二次跑 labels 应一致")

    # (5) DoD "折线图路径共用同一组采样点": 验证降采样点索引在 xs/ys/labels 三者
    # 之间完全一致 (同一组 np.sort(idx) 切片出来的)。由于 labels 唯一, 我们可以
    # 反向求索引: label "Lk" 对应原始下标 k, 比较 x_ds[i] == x[k] + labels_ds[i] == Lk
    # 的"隐含 k"是否与 y_ds[i] == y[k] 一致
    label_to_idx = {f"L{i}": i for i in range(n_orig)}
    for i in range(MAX_RENDER_POINTS):
        orig_idx = label_to_idx[labels_ds[i]]
        assert x_ds[i] == x[orig_idx], (
            f"i={i}: label=L{orig_idx} 但 x_ds[i]={x_ds[i]} != x[orig_idx]={x[orig_idx]}"
        )
        assert y_ds[i] == y[orig_idx], (
            f"i={i}: label=L{orig_idx} 但 y_ds[i]={y_ds[i]} != y[orig_idx]={y[orig_idx]}"
        )


# --------------------------------------------------------------------------
# T3: 降采样后 matplotlib 单子图渲染 < 100ms (n=100000 → 5000)
# --------------------------------------------------------------------------

def test_downsampling_speedup():
    """T3: n=100000 降采样到 5000 后, matplotlib 单子图 plot 应 < 100ms
    (vs 原 n=100000, 加速 ≥3x)。

    设计说明:
      - pyqtgraph offscreen Qt 在测试环境里 render 实际耗时受 GPU/驱动影响很大,
        不稳定; matplotlib 'Agg' backend 单图 plot 是更稳定的代理指标。
      - DoD 硬阈值: 降采样后 < 100ms (n=1M → 5k 估算约 200x 加速, 与 C048 同级)
      - 基线: n=100000 直接 plot (matplotlib Agg) 实测约 30-80ms (单图),
        10 子图 × 100k 点 ≈ 300-800ms, 正是 C049 "开始分析卡死"的体感来源。
        本测试单子图对比即可体现量级。
    """
    MAX_RENDER_POINTS, _downsample_with_labels, _ = _import_helper()
    import matplotlib
    matplotlib.use("Agg")  # CI / 无显示环境
    import matplotlib.pyplot as plt

    rng = np.random.default_rng(42)
    n_orig = 100_000
    x = rng.normal(0, 1, n_orig).astype(float)
    y = rng.normal(0, 1, n_orig).astype(float)
    labels = np.array([f"L{i}" for i in range(n_orig)], dtype=object)

    # (a) 基线: 不降采样, n=100000 直接 plot
    fig_a, ax_a = plt.subplots(figsize=(4, 3))
    t0 = time.perf_counter()
    ax_a.plot(x, y, linewidth=0.5)
    fig_a.canvas.draw()  # 强制后端真正画一遍 (matplotlib plot 本身只是 record, draw 才是 render)
    ms_full = (time.perf_counter() - t0) * 1000.0
    plt.close(fig_a)

    # 基线 sanity: n=100000 matplotlib Agg draw 应 ≥ 10ms (实测 30-80ms)
    assert ms_full > 10.0, (
        f"基线 n=100000 matplotlib draw 应至少 10ms (实测 30-80ms), got {ms_full:.1f}ms — "
        f"环境异常或 matplotlib 版本变了, 请检查"
    )

    # (b) 降采样后: n_ds=5000
    x_ds, y_ds, labels_ds, _ = _downsample_with_labels(x, y, labels)
    n_ds = len(x_ds)
    assert n_ds == MAX_RENDER_POINTS
    assert len(y_ds) == MAX_RENDER_POINTS
    assert len(labels_ds) == MAX_RENDER_POINTS

    fig_b, ax_b = plt.subplots(figsize=(4, 3))
    t0 = time.perf_counter()
    ax_b.plot(x_ds, y_ds, linewidth=0.5)
    fig_b.canvas.draw()
    ms_ds = (time.perf_counter() - t0) * 1000.0
    plt.close(fig_b)

    # DoD 硬阈值: 降采样后单图 plot 应 < 100ms (留余量给慢 CI, 但仍比基线快 3x+)
    assert ms_ds < 100.0, (
        f"n={n_orig:,} 降采样到 {MAX_RENDER_POINTS} 后单图 plot 应 < 100ms, "
        f"got {ms_ds:.1f}ms (matplotlib Agg)"
    )
    # 加速比 sanity: 应 ≥3x (更激进 10x 也常见)
    speedup = ms_full / max(ms_ds, 0.1)
    assert speedup > 3.0, (
        f"降采样后加速比应 > 3x (full={ms_full:.1f}ms, ds={ms_ds:.1f}ms, "
        f"speedup={speedup:.1f}x), 异常请检查"
    )

    # 输出一行诊断信息 (pytest -s 可看)
    print(
        f"\n[C050 T3] n={n_orig:,} → n_ds={n_ds:,}: "
        f"full={ms_full:.1f}ms → ds={ms_ds:.1f}ms speedup={speedup:.1f}x "
        f"(matplotlib Agg 单图 plot 代理, pyqtgraph 多子图实际加速更显著)"
    )


# --------------------------------------------------------------------------
# T4 (bonus): _downsample_with_labels 与 _downsample_for_render 同种子索引一致
# --------------------------------------------------------------------------

def test_helper_shares_indices_with_c048():
    """T4 (bonus): _downsample_with_labels 返回的 x_ds 与直接调 C048 helper 的
    x_ds 应**逐元素相等** (证明 wrapper 没有引入额外的随机性 / 排序差异)。

    这是 C050 "复用 C048 helper, 不要重写" 的关键保证——wrapper 只在 x_labels
    上**复用相同的 rng 选择逻辑**, 但不应改变 xs/ys 的索引。
    """
    MAX_RENDER_POINTS, _downsample_with_labels, _ = _import_helper()
    from app.ui.widgets.process_analysis_panel import _downsample_for_render
    rng = np.random.default_rng(7)
    n_orig = 8_000
    x = rng.normal(0, 1, n_orig).astype(float)
    y = (0.5 * x + rng.normal(0, 0.2, n_orig)).astype(float)
    labels = np.array([f"row_{i}" for i in range(n_orig)], dtype=object)

    # 走 wrapper
    x_w, y_w, labels_w, n_w = _downsample_with_labels(x, y, labels)
    # 走 C048 helper 直接
    x_c, y_c, n_c = _downsample_for_render(x, y)

    # xs/ys 必须**完全一致** (证明 wrapper 共用同一组采样点)
    np.testing.assert_array_equal(x_w, x_c, err_msg="wrapper 与 C048 helper 的 x_ds 应一致")
    np.testing.assert_array_equal(y_w, y_c, err_msg="wrapper 与 C048 helper 的 y_ds 应一致")
    assert n_w == n_c, f"n_orig 透传应一致, wrapper={n_w} vs C048={n_c}"
    # labels 长度与 xs/ys 一致 (保证三组数组同长度)
    assert len(labels_w) == len(x_w), (
        f"labels_ds 长度({len(labels_w)})应与 xs_ds 长度({len(x_w)})一致"
    )


# --------------------------------------------------------------------------
# T5 (bonus): MAX_RENDER_POINTS 常量值正确
# --------------------------------------------------------------------------

def test_max_render_points_constant_is_5000():
    """T5 (bonus): 模块级常量 MAX_RENDER_POINTS 必须 = 5000, 不是 magic number。"""
    MAX_RENDER_POINTS, _, _ = _import_helper()
    assert isinstance(MAX_RENDER_POINTS, int), (
        f"MAX_RENDER_POINTS 应为 int, got {type(MAX_RENDER_POINTS).__name__}"
    )
    assert MAX_RENDER_POINTS == 5000, (
        f"MAX_RENDER_POINTS 应 = 5000 (C046 / C049 P0A 推荐值), got {MAX_RENDER_POINTS}"
    )


if __name__ == "__main__":
    # 直接跑模式 (pytest 没装也能跑)
    import sys as _sys
    _sys.exit(pytest.main([__file__, "-v"]))
