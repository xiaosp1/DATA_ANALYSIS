# CHANGELOG

> 项目变更日志。新增条目放最上面，按 日期 / 阶段 / 改动 三段式记录。
> 详细交付说明见 `docs/changes/`（W12 / W12.1 / W12.2 等）。

---

## 2026-07-15 — S5-#2 多变量归因引擎

### 阶段
S5-#2（引擎层），S5-#3（UI 层）尚未启动。

### 改动
1. **`app/services/head_tail_attribution.py`**
   - 新增 `multi / multi_top_n / multi_min_samples / multi_exclude_vif_gt / multi_compute_partial / multi_compute_ols / use_pingouin` 7 个向后兼容参数（默认 `multi=False`）。
   - 新增内部函数：`_zscore_array`、`_ols_residual`、`_partial_corr`（numpy 残差法主路径）、`_partial_corr_pg`（pingouin 精化路径，缺失时降级）、`_ols_standardized`（标准化 OLS + 岭化 fallback）、`_compute_vif`（1/(1-R²)）、`_format_multi_result`。
   - `build_head_tail_report` 在 `multi=True` 时新增 `report["multi"]` 节点，含 `partial_corr[] / ols{} / top_contributors[] / ols_skipped_reason / warnings[]`。
   - 进度回调沿用 25→50 段（「偏相关计算中 i/n」+「OLS 拟合中」），取消事件在 M1 每特征后、M2 拟合前后插入 `_check_cancel()`。
   - VIF>10 仅警告不剔除（`vif_warn=True`、`vif_warning_text`），告警文案：`"[机头]X 与其它列 VIF=12.34，建议剔除"`。
   - 常数列自动从 OLS 剔除并写 warnings；p>n-2 → OLS 跳过并写 ols_skipped_reason；`X'X` 奇异 → 岭化 λ=1e-4。
   - 仅勾 1 列时：M1 退化为单 Pearson（warnings 注明），M2 跳过（ols_skipped_reason="仅勾选 1 列…"）。
   - `meta` 节点新增 `has_pingouin: bool` 字段。

2. **`tests/test_s5_multi_attribution.py`**（新文件）
   - 17 个 pytest 用例：报告结构、向后兼容、M1 单/多特征偏相关、共线代理塌陷、M2 β* 方向 + R²、VIF>10 警告 + 仅警告不剔除、常数列剔除、岭化 fallback、p>n-2 跳过、cancel、N<min_samples、zscore/VIF/OLS/partial_corr 内部函数直接单测。
   - 全部 `python -W error` 通过；旧 W12 8 个测试 0 退化。

3. **`requirements.txt`**
   - 追加 `pingouin>=0.5.3`（**可选精化路径**，仅在 M1 偏相关阶段启用，缺失时自动降级到 numpy 残差法）。

4. **`CHANGELOG.md`**（本文件）：新增。

### 不改
- `app/ui/widgets/process_analysis_panel.py` 0 改动（UI 是 S5-#3 范围）
- `app/services/ai_prompt.py`、`app/services/process_analysis.py` 0 改动
- `docs/domain/` 0 改动
- `TODO.md / STATUS.md / ROADMAP.md / COMMITMENTS.md` 0 改动（PM 元数据由 PM 维护）

### 验证
- `pytest tests/test_w12_head_tail_attribution.py tests/test_s5_multi_attribution.py -q -W error` → **25 passed**
- `pytest tests/ -q -W error --ignore=tests/ui_smoke_test.py --ignore=tests/run_functional_tests.py` → **142 passed in 10.85s**（基线 125 + 新增 17，0 退化）
- 默认 `multi=False` 下 `report["multi"]` 节点不存在，旧 6 个 W12 行为测试 100% 保留

### 已知限制
- 当前测试环境未安装 `pingouin`（`has_pingouin=False`），全部走 numpy 主路径；`use_pingouin=True` 用户需 `pip install pingouin>=0.5.3` 才能触发精化路径
- M2 取消体感：np.linalg.lstsq 阻塞调用不可中断，已在调用前后插入 `_check_cancel()` 做软取消

---

## 2026-07-13 — W12.2 AI 超时可配置

详见 `docs/changes/w12-head-tail-attribution.md` 末尾段。

---

## 2026-07-13 — W12.1 AI 锁与超时修复

详见 `docs/changes/w12-head-tail-attribution.md` 中段。

---

## 2026-07-10 — W12 机尾指数-s 归因分析模式

详见 `docs/changes/w12-head-tail-attribution.md`。
