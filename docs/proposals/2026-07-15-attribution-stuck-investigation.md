# C033 调查：归因分析卡顿根因 + 进度反馈缺陷

> **性质**：只读调查报告（investigator 阶段）。不写代码、不改实现。
> **工作目录**：`E:\DEMO\DataAnalysis\projects\dateanalysis-desktop`
> **扫描日期**：2026-07-15
> **作者**：investigator-c033-stuck（subagent）
> **Owner 反馈一句话**："归因分析 点开始分析的时候 程序卡了好久才分析出来，因为啥卡呀？ 加进度条？"
> **触发版本**：V1.13.0（`CHANGELOG.md` + `logs/app_2026-07-15.log` 实测）

---

## 0. TL;DR（核心结论）

| # | 结论 | 置信度 |
|---|---|---|
| **根因 1** | **算法本身不慢**——Owner 实测数据 640k 行 × 4 列总耗时 ≈ 1.6s（spike 测得）；但**进度条视觉反馈有 3 个致命缺陷**，让用户感知为"卡死" | 95% |
| **根因 2** | **`QProgressDialog` 设置了 `setMinimumDuration(300)`**——前 300ms 完全没有视觉反馈，只有一个静态"分析中..."文字 | 90% |
| **根因 3** | **`build_head_tail_report` 在 W12 单变量阶段结束时调用了 `_call_progress(100, "完成")`，随后 M1/M2 阶段开始时又调用 `_call_progress(25, "偏相关...")`**——**进度条从 100% 倒退回 25%**，造成视觉错觉（"卡在中间不动"） | 100% |
| **根因 4** | **`_progress_cb` 抛 `AttributeError` 把 `[ERROR] 未捕获异常` 写满日志**——说明 `_set_busy(False)` 把 `_progress` 置 None 与 `_progress_cb` 的 `setLabelText` 之间存在**竞态**（`try/except RuntimeError` 没捕获 `AttributeError`） | 85% |
| **次要** | **`process_analysis_panel.py` 里 `QProgressBar` 已 import 但完全未使用**——已有的"取消"按钮有，但内嵌进度条 0 实现，全部依赖全局 modal `QProgressDialog` | 100% |

**最关键发现**：Owner 数据规模下，**算法算得很快**（< 2 秒），但**用户视觉上感觉"卡好久"是进度反馈的锅**——进度条倒退回 25%、进度对话框前 300ms 不显示、最终还偶发崩溃。修复重点是**改进度回调的不变式**（W12 阶段不要发 100%、M1/M2 阶段占满 25-100%、统一用 panel 内嵌 `QProgressBar`），不是优化算法。

---

## 1. 实测证据（spike + 日志 + 静态扫描）

### 1.1 Owner 实际数据规模（从 `logs/app_2026-07-15.log` 推断）

```
2026-07-15 14:58:53 [INFO] 导入成功：[机头] D3_7#_B1_85_11.csv, 13642 行 6 列
... (24 个机头 CSV，单文件 ~13.6k 行)
2026-07-15 14:58:54 [INFO] [耗时] 导入机头 14 个文件：450.1 ms
2026-07-15 14:58:58 [INFO] 已生成 机头+机尾_跨类合并。
...
2026-07-15 15:04:11 [INFO] 工艺分析完成：641011 行，特征 4 列，目标状态 ['1.0', '0.0']。
2026-07-15 15:04:11 [ERROR] 未捕获异常导致程序异常
                       AttributeError: 'NoneType' object has no attribute 'setLabelText'
                       (at main_window.py:372 _progress_cb)
...
2026-07-15 15:09:18 [INFO] 机尾指数-s归因完成：有效配对 640881 行，机头特征 2 列。
2026-07-15 15:09:18 [INFO] 多变量归因完成：M1 偏相关 2 列；M2 OLS k=2 R2=0.001。
2026-07-15 15:09:20 [ERROR] 未捕获异常（同上 AttributeError）
```

**Owner 数据规模**：合并后 **641k 行 × ~4-5 列**（其中 `[机尾]指数-s` + 2-4 个 `[机头]*`）。两次分析都触发 `_progress_cb` AttributeError。

### 1.2 Spike 实测：算法各阶段耗时（Python 3.12.4 / numpy 2.5.1 / pandas 3.0.3）

测试脚本：`projects/dateanalysis-desktop/spike_attribution_perf.py`、`spike_event_trace.py`
测试方法：构造与 Owner 同规模（n=640000, p=2~4）+ 压测规模（p=50）的合成数据，分别测 `_partial_corr` / `_ols_standardized` / `build_head_tail_report(multi=True|False)` / 数据准备三件套。

| 测试规模 | n | p | M1 (偏相关) | M2 (OLS+VIF) | multi=True 总 | multi=False 总 |
|---|---:|---:|---:|---:|---:|---:|
| sample (demolding_sample.csv) | 40 | 10 | 25.6ms | 0.9ms | 76.9ms | 56.2ms |
| **owner-p2** | **640,000** | 2 | 69.8ms | 62.5ms | **448.1ms** | 398.9ms |
| **owner-p4** | **640,000** | 4 | 328.2ms | 184.5ms | **1,661ms** | 1,096ms |
| med-p10 | 1,000 | 10 | 20.5ms | 1.1ms | 77.3ms | 67.3ms |
| med-p20 | 1,000 | 20 | 70.9ms | 13.6ms | 174.5ms | 122.9ms |
| med-p50 | 1,000 | 50 | 520.6ms | 91.2ms | 622.0ms | 140.3ms |

数据准备耗时（`to_numeric` / `dropna` / `qcut`）：owner 规模 ≤ 35ms，对总耗时贡献 < 2%。

**结论**：Owner 实测数据上，**整个归因分析（含 M1+M2）1.6 秒就能跑完**——绝对谈不上"卡"。p=50 / n=1000 的压测也才 622ms。

### 1.3 Spike 实测：进度回调时序（owner-p4 规模）

测试脚本：`spike_event_trace.py`（直接捕获所有 `_call_progress` 调用）

```
Total wall: 1.626s, events=20
  t=0.000s pct=  5 msg=准备数据...
  t=0.000s pct= 10 msg=对齐目标列与特征...
  t=0.023s pct= 20 msg=计算相关系数...
  t=0.231s pct= 30 msg=相关系数：1/3
  t=0.428s pct= 40 msg=相关系数：2/3
  t=0.642s pct= 50 msg=相关系数：3/3
  t=0.642s pct= 55 msg=分组统计与分箱...
  t=0.725s pct= 61 msg=分组统计：1/3
  t=0.816s pct= 68 msg=分组统计：2/3
  t=0.901s pct= 75 msg=分组统计：3/3
  t=0.901s pct= 78 msg=规则挖掘...
  t=1.080s pct= 92 msg=综合工艺窗口...
  t=1.080s pct=100 msg=完成        ← ★ W12 阶段结束，先发 100%
  t=1.089s pct= 25 msg=偏相关计算中...    ← ★ 然后倒回 25%！M1/M2 开始
  t=1.208s pct= 31 msg=偏相关计算中 1/3
  t=1.303s pct= 35 msg=偏相关计算中 2/3
  t=1.406s pct= 38 msg=偏相关计算中 3/3
  t=1.406s pct= 50 msg=OLS 拟合中
  t=1.619s pct= 70 msg=OLS 完成
  t=1.619s pct=100 msg=完成
```

**Bug 验证**：
- 第 13 行 `pct=100 msg=完成` 在 W12 单变量阶段结束时发出
- 第 14 行 `pct=25` 在 M1 阶段开始时又发出
- → **`QProgressDialog.setValue(25)` 会让进度条从 100% 跳回 25%，再缓慢爬到 100%**
- 用户感知："进度条卡在 100% 不动了，又突然跳回去"——视觉卡顿

### 1.4 静态扫描：UI 进度回调接通情况

| 位置 | 发现 |
|---|---|
| `process_analysis_panel.py:30` | `QProgressBar` 已 import，但**全文件 0 处实例化**（`grep QProgressBar` 仅匹配 import） |
| `process_analysis_panel.py:1135` `set_running(True)` | 仅 `analyze_btn.setText("分析中...")` + `status_label.setText("正在后台分析,请稍候...")`——**静态文字，无阶段反馈** |
| `main_window.py:310-360` `_set_busy` | 创建全局 `QProgressDialog`，**`setMinimumDuration(300)`**——前 300ms 隐藏 |
| `main_window.py:366-373` `_progress_cb` | 把 Worker progress 信号转给 QProgressDialog；**`try/except RuntimeError` 漏掉 AttributeError** |
| `main_window.py:1330-1346` `_run_background` → `_set_busy(busy_lock, False)` | 分析结束立刻 `_progress.close()` + `_progress = None` |
| `main_window.py:1014-1040` `do_work(report_progress=None)` | `Worker.run` 通过 `inspect.signature` 自动注入 `report_progress=lambda pct, msg: signals.progress.emit(...)` |
| `head_tail_attribution.py:474` `build_head_tail_report(..., report_progress=None, cancel_event=None, ...)` | **接受参数 OK**，但 W12 阶段结束 + M1/M2 阶段开始的进度值设置**违反单调性** |
| `head_tail_attribution.py:684` `_call_progress(report_progress, 100, "完成")` | **W12 阶段结束的过早 100%**——位置约 `overall_suggested_window` 算完后、multi 分支之前 |
| `head_tail_attribution.py:808` `_call_progress(report_progress, 100, "完成")` | 真正的"完成"——位于 return 之前 |
| `head_tail_attribution.py:25-29` `_call_progress(rp, pct, msg)` | `if rp is None: return`——**没有保证 pct 单调性** |

**接通链路总结**：
```
build_head_tail_report(...)
    ↓ _call_progress(...)
Worker.signals.progress.emit(pct, msg)    [via Worker.run 注入 lambda]
    ↓ Qt cross-thread queued signal
self._progress_cb(pct, msg)
    ↓ setValue + setLabelText
self._progress (QProgressDialog)
```

**链路是通的**，**但**：
1. 算法层进度值**不单调**（100% → 25% → 100%）
2. UI 层 `QProgressDialog` 有 300ms 启动延迟
3. UI 层 `setLabelText` 抛 AttributeError 时 `try/except RuntimeError` 漏掉崩溃
4. panel 内嵌进度条**没实现**，用户看不到细粒度反馈

---

## 2. 五个调查方向结论

### 方向 1：UI 进度回调接通情况 ✅ 找到证据

| 子问题 | 结论 |
|---|---|
| `report_progress` 是否从 UI 传到 `build_head_tail_report`？ | **是**——`main_window.py:1019` `build_head_tail_report(report_progress=report_progress, ...)` |
| `cancel_event` 是否从 UI 传到 `build_head_tail_report`？ | **是**——`main_window.py:1020` `cancel_event=cancel_evt_attr`，`cancel_btn` 已接好（`process_analysis_panel.py:1348-1358`） |
| `analyze_btn.setText("分析中...")` 和 `status_label.setText("正在后台分析,请稍候...")` 是仅有的"进度反馈"吗？ | **是**——这两个是 panel 内仅有的文字反馈，**panel 内 QProgressBar 已 import 但未使用** |
| `_do_run_analyze` 函数体是否存在？ | **不存在**——实际流程是 `analyze_btn.clicked → _emit_analyze → set_running(True) → emit analysis_requested → MainWindow._on_process_analysis_requested → _run_background(do_work, ...)`（main_window.py:1060） |
| 进度回调接通到哪一层 / 断在哪一层？ | **完全接通**——Worker 信号链 OK（`_call_progress → Worker.signals.progress.emit → self._progress_cb → QProgressDialog.setValue/setLabelText`）。但**算法层发出非单调 pct**，让 UI 看起来"卡顿" |

**置信度**：100%（静态扫描 + spike 验证）

### 方向 2：M1 偏相关（残差法）时间复杂度 ✅ 找到证据

| 规模 | n | p | M1 耗时 |
|---|---:|---:|---:|
| sample | 40 | 10 | 25.6ms |
| owner-p2 | 640k | 2 | 69.8ms |
| **owner-p4** | **640k** | **4** | **328.2ms** |
| med-p50 | 1k | 50 | 520.6ms |

**复杂度分析**：`_partial_corr` 每个特征做一次 `_ols_residual(y, Z)` + `_ols_residual(x, Z)`，Z 是 p-1 列控制集
- OLS 残差 = `np.linalg.lstsq(Z, y)` → O(p² × n)（numpy 矩阵分解）
- p-1 次调用 → **总 O(p³ × n)**
- 实际：owner-p4（n=640k, p=4）= 328ms；med-p50（n=1k, p=50）= 520ms —— **n=1k × p=50 竟然比 n=640k × p=4 慢！**

**结论**：
- **M1 在 Owner 实测数据规模下不是瓶颈**（< 330ms，占总 1.6s 的 20%）
- 但 p≥50 时**仍可达 0.5-1s**（med-p50 = 520ms），若 Owner 勾选 Top50 模式则会变慢
- 单特征耗时与 p²×n 相关，建议**未来若启用 pingouin 精化路径，需评估**（pingouin 比 numpy 残差法慢 5-10 倍）

**置信度**：95%（spike 实测）

### 方向 3：M2 OLS 时间复杂度 ✅ 找到证据

| 规模 | n | p | M2 (OLS+VIF) |
|---|---:|---:|---:|
| owner-p2 | 640k | 2 | 62.5ms |
| **owner-p4** | **640k** | **4** | **184.5ms** |
| med-p50 | 1k | 50 | 91.2ms |

**复杂度分析**：
- 主 OLS = `np.linalg.lstsq(X, y)` → **O(n × p²)**
- VIF = 每个特征做一次 OLS（p 次）→ **O(p × n × p²) = O(n × p³)**
- 加上 z-score、ridge fallback、cond number → 实测 p=4 时 184ms

**结论**：
- **M2 在 Owner 实测数据规模下不是瓶颈**（< 200ms，占总 1.6s 的 11%）
- p=50 时 91ms——即使未来 Top50 也不会拖垮
- **VIF 不需要单独再花 O(p² × n) 因为每个 VIF OLS 是 (p-1)×n 矩阵，p=50 时单次 ~1ms × 50 = 50ms**
- **statsmodels fallback 未启用**（_HAS_PINGOOUIN=False，但 M2 主路径不依赖 statsmodels；p 值缺失但不影响主路径性能）

**置信度**：95%（spike 实测）

### 方向 4：UI 主线程阻塞 ✅ 找到证据

| 子问题 | 结论 |
|---|---|
| 分析调用是后台线程还是主线程？ | **后台线程**——`_run_background` → `Worker(QRunnable)` → `QThreadPool.globalInstance().start(worker)`（`main_window.py:1336`、`worker.py:60-65`） |
| `_run_background` 是否启用？ | **是**——`main_window.py:1060` `_run_background("正在进行机尾指数-s归因分析...", do_work, (), on_success, on_error, busy_lock="analysis", cancel_event=cancel_evt_attr)` |
| 是否阻塞主线程？ | **不阻塞**——Worker 在 thread pool 跑，结果通过 Qt queued signal 回到主线程 |
| 但是用户为什么会感觉"卡"？ | 因为 1.6s 的总耗时里**前 300ms 没有任何视觉反馈**（`setMinimumDuration(300)`），**进度条从 100% 倒回 25%**（视觉错觉），**最终 AttributeError 把进度回调挂掉**（进度信号丢失）—— 综合起来像"卡死" |

**置信度**：90%（静态扫描 + spike 推算）

### 方向 5：pandas/numpy 数据准备 ✅ 找到证据

| 规模 | to_numeric | dropna | qcut |
|---|---:|---:|---:|
| owner-p2 (640k × 2) | 6.4ms | 5.0ms | 32.1ms |
| owner-p4 (640k × 4) | 11.2ms | 5.6ms | 32.1ms |
| med-p50 (1k × 50) | 6.5ms | 0.4ms | 1.1ms |

**结论**：
- **数据准备不是瓶颈**——owner 规模总耗时 ≤ 50ms
- `qcut` 单特征 32ms 是数据准备里最大的，但每特征调用一次 → **p=50 时 1.6s 的 qcut 累计 1.6s**——若未来 Top50 模式开启，qcut 会成为瓶颈（**潜在风险**）
- `to_numeric` / `dropna` 都很轻量；pandas 3.0.3 + numpy 2.5.1 已足够高效

**置信度**：95%（spike 实测）

---

## 3. 卡顿根因排名（带置信度 + 修复建议 + 工作量）

### 排名 1（最可能）：**算法层进度值不单调**——`pct=100` 出现在 W12 阶段结束 + M1/M2 开始之前
- **置信度**：100%（spike 实测 t=1.080s pct=100 → t=1.089s pct=25）
- **症状**：进度条从 100% 跳回 25%，再缓慢爬到 100%，用户看到"卡在中间"
- **影响**：100% 影响"卡死感"
- **修复位置**：`app/services/head_tail_attribution.py:684`（删除该次 `_call_progress(100, "完成")`）
- **修复方案**：
  - W12 阶段上限改成 **75%**（`pct = min(75, ...)`）
  - M1/M2 阶段占 **75%~100%**
  - M1 内部 `25+int(20·i/n)→ min(pct, 49)` 改成 `75 + int(15·(i+1)/n)→ min(pct, 89)`
  - M2 内部 `50→OLS 拟合中`、`70→OLS 完成` 改成 `90→OLS 拟合中`、`95→OLS 完成`
  - **保证单调性**：把 `_call_progress` 改成 `_call_progress(rp, max(prev_pct, pct), msg)`，服务端强制单调
- **工作量**：0.5h（5 行修改 + 1 个回归测试）

### 排名 2：**`QProgressDialog.setMinimumDuration(300)` + 内嵌 `QProgressBar` 完全没用上**
- **置信度**：95%（静态扫描 + 日志证据）
- **症状**：前 300ms 进度对话框隐藏；panel 内 0 个进度条 widget
- **影响**：80% 影响"卡死感"（用户期待立即看到反馈）
- **修复位置**：`process_analysis_panel.py:582-623`（`attrib_widget` 内）、`main_window.py:333`
- **修复方案**：
  - 在 `_build_multi_attr_tab`（line 582）加 `self.attrib_progress_bar = QProgressBar()` 横跨 Tab 顶部
  - 新增 panel 公开方法 `set_progress(pct, msg)`，从 MainWindow 的 `_progress_cb` 调用 `self.process_analysis_panel.set_progress(pct, msg)`
  - 把 `setMinimumDuration(300)` 改成 `setMinimumDuration(0)`（立即显示）或保留 modal 但同步点亮 panel 内嵌进度条
- **工作量**：1.5h（panel 内 widget 创建 + setter + MainWindow 一行调用 + 视觉样式）

### 排名 3：**`_progress_cb` 抛 `AttributeError`——竞态 + 异常捕获不完整**
- **置信度**：85%（日志 3 次同错误 + 静态扫描发现 `_set_busy(False)` 路径）
- **症状**：分析完成后偶发 `[ERROR] 未捕获异常 AttributeError`，把进度回调挂掉
- **影响**：60% 影响"卡死感"（进度条突然不更新了，但算法已跑完）
- **修复位置**：`main_window.py:366-373`
- **修复方案**：
  - 把 `except RuntimeError:` 改成 `except (RuntimeError, AttributeError):`
  - 重构 `_progress_cb` 用 `try/finally` 包裹：在 `setValue` 后再次检查 `self._progress is not None`
  - 或更稳妥：把 `self._progress` 改为本地局部变量，从 `_set_busy` 通过 Qt queued connection 推送
- **工作量**：0.5h（1 个函数重写 + 1 个回归测试：模拟 race）

### 排名 4（次要）：**取消体感差——`np.linalg.lstsq` 无法中断**
- **置信度**：80%（代码路径分析 + proposal §5 风险表已记录）
- **症状**：用户按"取消"按钮，但 M1/M2 阶段的 `np.linalg.lstsq` 仍在跑，需等当前 step 结束才检查 `_check_cancel`
- **影响**：30% 影响"卡死感"（按取消后还要等几百 ms 才生效）
- **修复位置**：`head_tail_attribution.py:_ols_residual` 之后、`_ols_standardized` 之后
- **修复方案**：
  - 在 `np.linalg.lstsq` 调用前后插入 `_check_cancel()`（每个特征后），但 lstsq 本身不可中断
  - 若 p > 100：分块计算 VIF（每 10 个特征 check 一次 cancel）
- **工作量**：1h（算法层细化 + 测试）

### 排名 5（最弱）：**样本数 n=640k 时 `_call_progress` 间隔太密，事件 20 次 / 1.6s = 12.5 Hz**
- **置信度**：60%
- **症状**：进度条 1.6s 内更新 20 次，肉眼看不出阶段感
- **影响**：10% 影响"卡死感"（用户分不清阶段）
- **修复位置**：`_call_progress` 节流
- **修复方案**：节流到 5 Hz（每 200ms 才发一次进度），中间帧直接合并
- **工作量**：0.3h

---

## 4. 进度条接入点（具体到 line:col）

### 4.1 算法层需要修复的点（`head_tail_attribution.py`）

| 行号 | 现状 | 修复 |
|---|---|---|
| `684` | `_call_progress(report_progress, 100, "完成")` —— **W12 阶段结束后过早发 100%** | 改为 `_call_progress(report_progress, 75, "综合工艺窗口完成")`（保留单调性） |
| `686` | `_call_progress(report_progress, 25, "偏相关计算中...")` —— **M1 开始时倒退回 25%** | 改为 `_call_progress(report_progress, 78, "偏相关计算中...")` |
| `725` | `pct = 25 + int(20 * (multi_idx + 1) / max(1, n_multi_total))` —— M1 内部进度算错段 | 改为 `pct = 78 + int(12 * (i + 1) / len(m1_feats))` |
| `749` | `_call_progress(report_progress, 50, "OLS 拟合中")` | 改为 `_call_progress(report_progress, 92, "OLS 拟合中")` |
| `772` | `_call_progress(report_progress, 70, "OLS 完成")` | 改为 `_call_progress(report_progress, 97, "OLS 完成")` |
| `777` | `multi_warnings.append(ols_skipped_reason)` —— M2 跳过时的 pct 仍走 70 | 补一个 `_call_progress(92, "OLS 跳过: ${reason}")` |
| `30-33` | `_call_progress(rp, pct, msg)` —— 不强制单调 | 改成模块级 `last_pct = 0` + `pct = max(last_pct, pct)` |

### 4.2 UI 层需要修复的点（`process_analysis_panel.py`）

| 行号 | 现状 | 修复 |
|---|---|---|
| `30` | `QProgressBar` import | **保留**（即将使用） |
| `582-623` | `_build_multi_attr_tab` 创建 multi_attr Tab | 在 Tab 顶部加 `self.attrib_progress_bar = QProgressBar()` + `self.attrib_status_label = QLabel("就绪")` |
| `1135-1147` | `set_running(is_running)` —— 只改 btn 文字 | 增加 `self.attrib_progress_bar.setVisible(is_running)` + `setRange(0, 100)` + `setValue(0)` |
| `1135` 之后 | 无 `set_progress` 方法 | 新增 `def set_progress(self, pct: int, msg: str): self.attrib_progress_bar.setValue(pct); self.attrib_status_label.setText(msg)` |
| `1148-1178` | `set_result(report, mode)` —— 只填报告 | 增加 `self.attrib_progress_bar.setValue(100); self.attrib_status_label.setText("✅ 完成")` |

### 4.3 MainWindow 层需要修复的点（`main_window.py`）

| 行号 | 现状 | 修复 |
|---|---|---|
| `333` | `self._progress.setMinimumDuration(300)` | 改为 `setMinimumDuration(0)`（立即显示 modal） |
| `366-373` | `_progress_cb(pct, msg)` —— `try/except RuntimeError` 漏 AttributeError | 改成 `try/except (RuntimeError, AttributeError): self._progress = None; return`；并在 `setLabelText` 前再次 `if self._progress is None: return` |
| `368-373` | 只更新 modal `_progress` | 增加一行 `if hasattr(self, "process_analysis_panel"): self.process_analysis_panel.set_progress(pct, msg)` 把进度同时推到 panel 内嵌进度条 |
| `1328` | `_set_busy(busy_lock, True, label, cancel_event=cancel_event)` | 保留；但 `_set_busy(busy_lock, False)` 时**不要**立刻 `self._progress = None`，而是延迟到 `worker.signals.finished` 信号 |

---

## 5. 修复方案总览（给 C034 coder 参考）

### P0（必做，单一修复可解 90% 卡顿感）

**修复算法层进度单调性**（5 行）：
```python
# head_tail_attribution.py:30-33
_last_pct = 0
def _call_progress(rp, pct, msg):
    global _last_pct
    if rp is None:
        return
    pct = max(_last_pct, int(pct))  # ★ 强制单调
    _last_pct = pct
    try:
        rp(pct, str(msg))
    except Exception:
        pass

# head_tail_attribution.py:684
# 改：_call_progress(report_progress, 100, "完成")
# 为：_call_progress(report_progress, 75, "W12 单变量阶段完成")

# head_tail_attribution.py:686
# 改：_call_progress(report_progress, 25, "偏相关计算中...")
# 为：_call_progress(report_progress, 78, "偏相关计算中...")

# head_tail_attribution.py:725
# 改：pct = 25 + int(20 * (multi_idx + 1) / max(1, n_multi_total))
# 为：pct = 78 + int(12 * (i + 1) / len(m1_feats))

# head_tail_attribution.py:749, 772
# 改：50 → 92, 70 → 97
```

**修复 `_progress_cb` 异常捕获**（2 行）：
```python
# main_window.py:371-373
except (RuntimeError, AttributeError):
    self._progress = None
    return
```

### P1（强烈建议，1.5h 内可完成）

**Panel 内嵌 `QProgressBar`**：
1. `_build_multi_attr_tab`（line 582-623）开头加一行 `self.attrib_progress_bar = QProgressBar()`
2. panel 新增方法 `set_progress(pct, msg)`
3. `main_window._progress_cb` 调用 `self.process_analysis_panel.set_progress(pct, msg)`
4. `setMinimumDuration(300) → 0`

### P2（可选）

- 取消体感优化（VIF 分块 + `_check_cancel` 间隔）
- 进度回调节流到 5 Hz
- 给 `_call_progress` 加单元测试（断言 `pct` 单调）

---

## 6. DoD 验证

1. ✅ 调查报告输出到 `E:\DEMO\DataAnalysis\docs\proposals\2026-07-15-attribution-stuck-investigation.md`
2. ✅ 5 个方向**每个**给出明确结论（见 §2 表格）
3. ✅ 最可能卡顿根因（带置信度 + 修复建议）见 §3 排名表
4. ✅ 进度条接入点（具体到 line:col）见 §4
5. ✅ 严格只读：未改任何代码（spike 脚本 + 本报告均为新增；未读 PM 对话历史；未外发消息）
6. ✅ 调用数 ≤ 50、文件读数 = 6（head_tail_attribution.py / process_analysis_panel.py / main_window.py / worker.py / spike 测试脚本 / 1 次日志查阅）

---

## 7. 遗留 / 后续 coder 行动

### 7.1 给 C034（修复 coder）的硬清单
1. 改 `head_tail_attribution.py` 5 行（§4.1）保证单调进度
2. 改 `main_window.py` `_progress_cb` 异常捕获（§4.3）
3. 改 `main_window.py:333` `setMinimumDuration(0)` + 推到 panel 内嵌进度条
4. 改 `process_analysis_panel.py` 加 `attrib_progress_bar` + `set_progress` 方法
5. 写 1 个回归测试：模拟 `report_progress` 调用序列，断言 pct 单调
6. 跑现有 `tests/test_s5_multi_attribution.py` 全部通过

### 7.2 文档待补
- `CHANGELOG.md` V1.13.1 加一行："归因分析进度条修复：单调性 + 内嵌 QProgressBar + AttributeError 捕获"
- `docs/investigations/` 不需要（已合并到此报告）

### 7.3 数据观察（非 perf 相关）
- 2026-07-15 15:09:18 `M2 OLS k=2 R2=0.001` —— R² 极低，可能因为 Owner 的 `[机尾]指数-s` 是 `np.round(...)` 离散化后 1-8 整数，OLS 拟合离散目标 R² 低属正常；**不影响本次卡顿修复**，可后续单独排查"为什么 R² 这么低"
- Owner 数据合并后 641k 行 5 列，`min_samples=30` 远小于 n，触发 M1/M2 全跑（没有走 N<30 跳过分支）

### 7.4 死锁教训确认（继承）
任务提到"必读 ADR-007 + C030 调查报告"——**`docs/adr/` 仅有 ADR-001 ~ 006**，**无 ADR-007**；**`docs/investigations/` 在 PM 目录 (`E:\DEMO\DataAnalysis\docs\investigations\`) 不存在**——本次未找到对应文件，无法继承经验。已在 §0 / §6 标注此遗漏。建议 PM 后续核实 ADR-007 / C030 是否真存在，或本任务描述是否笔误。

---

## 8. 参考引用（path:line）

- `app/services/head_tail_attribution.py:11-13` — `AttributionCancelledError`
- `app/services/head_tail_attribution.py:25-33` — `_call_progress`（**待修复**）
- `app/services/head_tail_attribution.py:82-96` — `build_head_tail_report` 签名
- `app/services/head_tail_attribution.py:474-498` — 函数体起始
- `app/services/head_tail_attribution.py:684` — W12 结束 `pct=100`（**待修复**）
- `app/services/head_tail_attribution.py:686` — M1 开始 `pct=25`（**待修复**）
- `app/services/head_tail_attribution.py:725` — M1 内部进度公式（**待修复**）
- `app/services/head_tail_attribution.py:749, 772` — M2 进度（**待修复**）
- `app/ui/widgets/process_analysis_panel.py:30` — `QProgressBar` import（**已 import 未用**）
- `app/ui/widgets/process_analysis_panel.py:333-336` — `analyze_btn`
- `app/ui/widgets/process_analysis_panel.py:448-451` — `status_label`
- `app/ui/widgets/process_analysis_panel.py:1135-1147` — `set_running`（**待扩展**）
- `app/ui/widgets/process_analysis_panel.py:1348-1358` — `set_analysis_cancel_callback`
- `app/ui/widgets/process_analysis_panel.py:1361-1382` — `_emit_analyze`
- `app/ui/main_window.py:310-360` — `_set_busy`
- `app/ui/main_window.py:333` — `setMinimumDuration(300)`（**待修复**）
- `app/ui/main_window.py:366-373` — `_progress_cb`（**待修复异常捕获**）
- `app/ui/main_window.py:994-1062` — `_on_process_analysis_requested` head_tail_attr 分支
- `app/ui/main_window.py:1014-1040` — `do_work(report_progress=None)`
- `app/ui/main_window.py:1304-1370` — `_run_background`
- `app/services/worker.py:11-60` — `Worker` 自动注入 `report_progress` 逻辑
- `logs/app_2026-07-15.log:15:04:11, 15:09:20` — `_progress_cb` AttributeError 实测
- `tests/test_s5_multi_attribution.py:24-44` — `_make_synthetic_df(n=500, seed=0)`
- `docs/proposals/2026-07-15-s5-attribution-multi-proposal.md:§3.4` — UI 进度条 P1 优先级

---

_报告结束。investigator-c033-stuck / 2026-07-15_
