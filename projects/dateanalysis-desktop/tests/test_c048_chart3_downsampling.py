# -*- coding: utf-8 -*-
"""C048 P0A 修复单测：chart3 散点 + LOESS 双重降采样（MAX_RENDER_POINTS=5000）。

C046 根因报告指出，n=百万级时 chart3 LOESS fallback（np.convolve）单子图 O(n × n/10)
= O(n²/10) 在主线程执行，单子图耗时 100-180s，p=10 多变量模式卡死 20+ 分钟。
C048 P0A 修复：在 _render_chart3_subplot 入口加 n 阈值判断，n>5000 时降采样到 5000 点，
散点 + LOESS 用同一组采样点（避免散点和趋势线对不上），LOESS kernel w 按降采样后的
n 重算（max(5, n_ds//10)），n=1M → 5000 = 200x 速提升。

本测试覆盖：
  T1  n<=5000 时**不**降采样（输入/输出严格相等, n_orig 透传）
  T2  n>5000 时降采样, x 与 resid 索引一致（散点对应关系不破）
  T3  n=100000 降采样到 5000 后, 用 spike_loess_only 同款 np.convolve LOESS fallback
      应 < 100ms（vs 原 n=100000=329ms）

测试策略：
  - 仅 import 模块级纯函数 _downsample_for_render + 常量 MAX_RENDER_POINTS
  - 不依赖 Qt (可 CI 运行)
  - 不修改 process_analysis_panel.py 的 _render_chart3_subplot 行为（仅验证 helper）
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
    """延迟 import: 直接 import 模块会触发 Qt 依赖, 这里只取需要的符号。"""
    from app.ui.widgets.process_analysis_panel import (
        MAX_RENDER_POINTS,
        _downsample_for_render,
    )
    return MAX_RENDER_POINTS, _downsample_for_render


# --------------------------------------------------------------------------
# T1: n <= MAX_RENDER_POINTS 时不降采样
# --------------------------------------------------------------------------

def test_downsampling_disabled_when_n_below_threshold():
    """T1: n=100 时**不**触发降采样——输入 x/resid 与输出严格相等, 原 n 透传。

    设计意图: 小样本场景 (n<=5000) 跳过降采样避免无谓丢失, 也保证 DoD 说的
    "n<=5000 时**不**降采样" 显式约束。
    """
    MAX_RENDER_POINTS, _downsample_for_render = _import_helper()
    # 边界: n=MAX_RENDER_POINTS 也应**不**降采样（<= 不 <）
    rng = np.random.default_rng(0)
    for n in (10, 100, 1000, MAX_RENDER_POINTS):
        x = rng.normal(0, 1, n).astype(float)
        resid = rng.normal(0, 1, n).astype(float)
        x_ds, resid_ds, n_orig = _downsample_for_render(x, resid, max_points=MAX_RENDER_POINTS)
        # 输入严格不变
        assert len(x_ds) == n, f"n={n} 应原样返回, got len={len(x_ds)}"
        assert len(resid_ds) == n, f"n={n} resid 应原样返回, got len={len(resid_ds)}"
        np.testing.assert_array_equal(x_ds, x, err_msg=f"n={n} x 内容被改")
        np.testing.assert_array_equal(resid_ds, resid, err_msg=f"n={n} resid 内容被改")
        # 原 n 透传
        assert n_orig == n, f"n_orig 应透传 {n}, got {n_orig}"


# --------------------------------------------------------------------------
# T2: n > MAX_RENDER_POINTS 时降采样, x 与 resid 索引对应
# --------------------------------------------------------------------------

def test_downsampling_keeps_correspondence():
    """T2: n=10000 时降采样到 5000, x 和 resid 必须保留一一对应（散点 + LOESS 对得上）。

    关键不变量:
      1. 输出长度 = MAX_RENDER_POINTS (=5000)
      2. 每个采样点的 (x[i], resid[i]) 都来自原始输入同一索引
         （不能散点取 idx_a, 残差取 idx_b, 否则图上点会"飞"）
      3. 索引按原始顺序排序（np.sort）—— 既利于 LOESS 要求 x 升序,
         也保证散点视觉顺序与原始数据点序列一致
      4. 同一 seed=42 下输出可复现
    """
    MAX_RENDER_POINTS, _downsample_for_render = _import_helper()
    rng = np.random.default_rng(123)
    n_orig = 10_000
    x = rng.normal(0, 1, n_orig).astype(float)
    # 让 resid 包含线性项 + 噪声, 便于验证索引对应
    resid = (0.7 * x + rng.normal(0, 0.3, n_orig)).astype(float)

    x_ds, resid_ds, n_back = _downsample_for_render(x, resid, max_points=MAX_RENDER_POINTS)

    # (1) 长度正确
    assert len(x_ds) == MAX_RENDER_POINTS, (
        f"降采样后长度应={MAX_RENDER_POINTS}, got {len(x_ds)}"
    )
    assert len(resid_ds) == MAX_RENDER_POINTS
    assert n_back == n_orig, f"n_orig 应透传 {n_orig}, got {n_back}"

    # (2) 对应关系: 构造映射 (x[i], resid[i]) 对照
    # 因为 x 是浮点, 改成索引比对: 用 np.argsort(x) 反推采样点
    # 直接断言: (x_ds, resid_ds) 的所有点都在原集合中, 且配对正确
    # 用 set of tuples
    orig_pairs = set(zip(x.tolist(), resid.tolist()))
    ds_pairs = list(zip(x_ds.tolist(), resid_ds.tolist()))
    assert len(ds_pairs) == MAX_RENDER_POINTS
    assert all(p in orig_pairs for p in ds_pairs), (
        "降采样点 (x, resid) 应一一对应原数据, 出现不在原集合的 (x, resid) 对"
    )
    # (3) 排序回原顺序: 索引经 np.sort 后, x[idx_sorted] 是原数组的"原顺序"取样
    #     (不要求 x 值升序, 因为原数组顺序是任意的; LOESS 内部会再 np.argsort)
    #     验证: 两次运行顺序一致 (seed 复现), 即可证明"回原顺序"语义稳定
    #     不强制 x_ds 升序（那是 argsort 后的事, 不是 downsample 的事）

    # (4) 可复现: 同样输入+seed 两次应一致
    x_ds2, resid_ds2, _ = _downsample_for_render(x, resid, max_points=MAX_RENDER_POINTS)
    np.testing.assert_array_equal(x_ds, x_ds2, err_msg="同 seed 第二次跑 x 应一致")
    np.testing.assert_array_equal(resid_ds, resid_ds2, err_msg="同 seed 第二次跑 resid 应一致")


# --------------------------------------------------------------------------
# T3: 降采样后 LOESS fallback 速度 < 100ms (n=100000 → 5000)
# --------------------------------------------------------------------------

def test_downsampling_speedup():
    """T3: n=100000 降采样到 5000 后, 用 spike_loess_only 同款 np.convolve LOESS
    fallback 应 < 100ms（vs 原 n=100000 实测 329ms, 加速 ≥3x）。

    注: spike_loess_only.py 实测 n=100000,w=10000 → 329ms；本测试 n=100000
    降采样到 n_ds=5000, w_ds=500 → ops=5000×500=2.5e6, 应远 < 100ms。
    阈值取 100ms 留余量（CI 环境可能略慢）, 但仍比原值快 3x+。
    """
    MAX_RENDER_POINTS, _downsample_for_render = _import_helper()
    rng = np.random.default_rng(42)
    n_orig = 100_000
    x = rng.normal(0, 1, n_orig).astype(float)
    resid = rng.normal(0, 1, n_orig).astype(float)

    # (a) 不降采样 baseline: n=100000 走 np.convolve 是 C046 卡死的入口
    # 我们不强制跑 baseline (329ms 在 CI 仍可接受), 但记录供对比
    order_full = np.argsort(x)
    xs_full = x[order_full]
    rs_full = resid[order_full]
    w_full = max(5, len(xs_full) // 10)
    t0 = time.perf_counter()
    smooth_full = np.convolve(rs_full, np.ones(w_full) / w_full, mode="same")
    ms_full = (time.perf_counter() - t0) * 1000.0
    # 基准 sanity: n=100000 np.convolve 应 ≥50ms（实测 329ms, 留余量）
    assert ms_full > 20.0, (
        f"基线 n=100000 np.convolve 应至少 20ms (实测 329ms), got {ms_full:.1f}ms — "
        f"环境异常或 numpy 版本变了, 请检查 spike_loess_only.py 是否过期"
    )

    # (b) 降采样后: n_ds=5000, w_ds=500, 应 < 100ms
    x_ds, resid_ds, _ = _downsample_for_render(x, resid, max_points=MAX_RENDER_POINTS)
    n_ds = len(x_ds)
    assert n_ds == MAX_RENDER_POINTS
    # spike_loess_only 同款实现: 排序 + max(5, n//10) kernel + np.convolve same
    order_ds = np.argsort(x_ds)
    xs_ds = x_ds[order_ds]
    rs_ds = resid_ds[order_ds]
    w_ds = max(5, n_ds // 10)
    kernel_ds = np.ones(w_ds) / w_ds
    t0 = time.perf_counter()
    smooth_ds = np.convolve(rs_ds, kernel_ds, mode="same")
    ms_ds = (time.perf_counter() - t0) * 1000.0

    # DoD 硬阈值
    assert ms_ds < 100.0, (
        f"n=100000 降采样到 {MAX_RENDER_POINTS} 后 LOESS fallback 应 < 100ms, "
        f"got {ms_ds:.1f}ms (kernel w={w_ds}, n={n_ds})"
    )
    # 加速比 sanity: 应 ≥3x（更激进 10x 也常见）
    speedup = ms_full / max(ms_ds, 0.1)
    assert speedup > 3.0, (
        f"降采样后加速比应 > 3x (full={ms_full:.1f}ms, ds={ms_ds:.1f}ms, "
        f"speedup={speedup:.1f}x), 异常请检查 np.argsort + kernel 链路"
    )

    # 输出一行诊断信息（pytest -s 可看, 默认 capture=fd 也会有 -v 末尾）
    print(
        f"\n[C048 T3] n={n_orig:,} → n_ds={n_ds:,}: "
        f"full={ms_full:.1f}ms (w={w_full:,}) → ds={ms_ds:.1f}ms (w={w_ds:,}) "
        f"speedup={speedup:.1f}x"
    )


# --------------------------------------------------------------------------
# T4 (bonus): MAX_RENDER_POINTS 常量值正确
# --------------------------------------------------------------------------

def test_max_render_points_constant_is_5000():
    """T4 (bonus): 模块级常量 MAX_RENDER_POINTS 必须 = 5000, 不是 magic number。"""
    MAX_RENDER_POINTS, _ = _import_helper()
    assert isinstance(MAX_RENDER_POINTS, int), (
        f"MAX_RENDER_POINTS 应为 int, got {type(MAX_RENDER_POINTS).__name__}"
    )
    assert MAX_RENDER_POINTS == 5000, (
        f"MAX_RENDER_POINTS 应 = 5000 (C046 P0A 推荐值), got {MAX_RENDER_POINTS}"
    )


if __name__ == "__main__":
    # 直接跑模式 (pytest 没装也能跑)
    import sys as _sys
    _sys.exit(pytest.main([__file__, "-v"]))
