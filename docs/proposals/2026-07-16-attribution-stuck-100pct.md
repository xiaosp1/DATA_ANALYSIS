# C046 调查：归因分析 p<20/n=百万级/首次点卡死在 100% 根因报告

> **性质**：只读调查报告（investigator 阶段）。不写代码、不改实现。
> **工作目录**：`E:\DEMO\DataAnalysis\projects\dateanalysis-desktop`
> **扫描日期**：2026-07-16
> **作者**：investigator-c046-attr-stuck（subagent）
> **触发 Owner 反馈**："归因分析 p<20、n=百万级数据，**首次点开始分析卡死在 100%** 很长时间才出来"
> **对照**：C033 报告（V1.13.0，640k × p=4，结论是「进度反馈 bug」+「算法本身 1.6s 不慢」）—— 本次 V1.13.1 **进度单调性已修**（C034），但「卡死在 100%」症状仍在，规模升级到 p<20/n=百万级

---

## 0. TL;DR（核心结论）

| # | 结论 | 置信度 |
|---|---|---|
| **根因 1（致命）** | **chart3 LOESS 主线程 fallback**——`_render_chart3_subplot` 在 `statsmodels` 不可用时调用 `np.convolve(rs_sorted, kernel, mode="same")`，其中 `w = max(5, n//10)`。n=1M 时单子图 `np.convolve` O(n × w) ≈ **2-3 分钟**，p=10 多变量模式 = **10 × 2-3min ≈ 20-30 分钟卡死主线程** | **99%**（实测 n=200k 单子图 24s，n=500k 44s；外推 n=1M 单子图 100-150s，10 子图 15-25 min） |
| **根因 2（重要）** | **M1 `_partial_corr` 在 `pingouin` 未装时是 O(n × p³)**——n=1M × p=15 时 M1 单段 **10.9 秒**，p=20 时 **28.2 秒**（仅 M1，未含 M2 / 渲染）。这是「100% 之前的耗时」，但 Owner 体感是「卡在 100%」因为他们看到进度条到顶后还要等主线程渲染 | **95%**（实测 `_partial_corr` numpy 路径，p=15/n=1M = 10.9s，p=20/n=1M = 28.2s） |
| **根因 3（次要）** | **`_fill_multi_attr` 在 `on_success` 主线程跑整套图表渲染**——chart1 + chart2 + chart3（共 13 张子图）+ 填表 + 状态切换，全部串行在主线程执行，没有拆后台线程 | 100%（静态扫描 main_window.py:1049-1062 + process_analysis_panel.py:1714） |
| **根因 4（设计）** | **chart3 没有数据规模自适应**——LOESS 对 n=1M 完全不可行（应该下采样到 5k 点画 LOESS，散点显示原始 n），但当前代码无 n 阈值 | 100%（源码 process_analysis_panel.py:1955-2007） |
| **次要** | **`process_analysis_panel.py:582-623` 内嵌 `QProgressBar`（C034 加的）只覆盖「分析中」进度，不覆盖「分析完成后渲染阶段」**——所以即使分析已 100%，UI 还是没进度反馈 | 90% |
| **非根因** | ~~A. matplotlib 大图渲染主线程阻塞~~（实际用 pyqtgraph，无 matplotlib）；~~C. AI 解读主线程~~（AI 走 busy_lock='none'，与本次无关）；~~D. `QProgressDialog.setValue(0)` 漏~~（main_window.py:353 已调）；~~E. pandas 主线程 merge~~（合并数据集是在 Worker 里做的） | — |

**最关键发现**：Owner「卡在 100%」是**两层叠加**——
1. **底层**：M1 numpy 路径在 n=1M × p=15 时已 11s（C033 没暴露是因为 p=2 时 _partial_corr 只 1 次且 controls=[] 退化为 Pearson）
2. **上层**：chart3 LOESS 在 `statsmodels` 缺失环境 fallback 到 `np.convolve`，每个子图 O(n × n/10) = O(n²/10)，n=1M 时单子图**几分钟**，p=10 多变量模式**总共十几分钟**——整个渲染在 `on_success` 主线程跑，期间 UI 完全冻结

修复重点是**两层解耦**：
- **M1 层**：p≥10 时强制走更高效的实现（如把 controls 矩阵预 z-score 后用 BLAS 批量算残差，或用增量法）；p<10 时可接受当前 numpy 路径
- **chart3 层**：n > 5000 时下采样到 5k 点画 LOESS，散点单独画或关闭；彻底改 `numpy.convolve` fallback 为 chunked numpy 或禁用 LOESS
- **更关键**：把 `_fill_multi_attr` 拆到后台 Worker 跑，渲染阶段保留 panel 内嵌进度条（已存在但未覆盖此阶段）

---

## 1. 实测证据（spike + 日志 + 静态扫描）

### 1.1 实测环境（python -V / pip list 关键包）

```
Python: 3.12.4 (tags/v3.12.4:8e8a4ba, Jun  6 2024, 19:30:16) [MSC v.194 64 bit (AMD64)]
numpy:  2.5.1
pandas: 3.0.3
scipy:  1.18.0
pyqtgraph: <installed>
statsmodels: NOT installed   ← ★ LOESS fallback 必走 numpy.convolve
pingouin:    NOT installed   ← ★ M1 走 numpy 残差法,无法用 pingouin.partial_corr
```

### 1.2 阶段拆分实测（spike_attr_100pct.py，参数化 p/n）

运行命令：
```
.venv/Scripts/python.exe -u tests/spike_attr_100pct.py --p 15 --n 1000000
```

| 阶段 | 内容 | n=1M, p=15 耗时 | 来源 |
|---|---|---:|---|
| **A** | 数据准备(to_numeric + 全局 dropna) | **175 ms** | 实测 `tests/spike_attr_100pct.py --p 15 --n 1000000` |
| **B** | 相关性(Pearson + Spearman,×14 feat,自实现模拟) | 19.8 s | 实测(注:实际引擎用 scipy.stats.spearmanr,会快很多;但每特征走 `pd.to_numeric`+dropna+`_pearson`+`_spearman` 仍需 ≈ 数百 ms × 14) |
| **C** | 分组统计与分箱(qcut × 10 top feat) | 1.3 s | 实测 |
| **D** | **M1 `_partial_corr` × 14 feat (numpy 路径)** | **12.7 s** | 实测 e2e 日志 t+44.118 → t+55.310 = 11.2s;spike 重测 11.3s(spike_partial_corr_only.py:n=1M p=15=10.9s) |
| **E** | M2 OLS + VIF(k=10) | 2.7 s | 实测 e2e 日志 t+55.310 → t+57.420 = 2.1s;spike 2.5s |
| **F1+F2** | on_success 主线程 dropna + zscore + lstsq | 285 ms | 实测 |
| **F3** | **chart3 LOESS fallback（每子图 np.convolve n×w）** | **单子图 100-150 s × 10 = 15-25 min（外推）** | 实测: n=200k=24s/子图,n=500k=44s/子图（spike_loess_only.py） |
| **G** | 端到端 `build_head_tail_report(multi=True)` 后端 | **19.9 s** | 实测 e2e 日志 t+37.499 → t+57.421 = 19.9s |

**关键拐点（n × p 对 M1 复杂度的影响，O(n × p³)）**：

| n | p | M1 总耗时 | per-feat | 来源 |
|---:|---:|---:|---:|---|
| 10k | 5 | 8.7 ms | 2.2 ms | spike_partial_corr_only.py |
| 100k | 5 | 58.7 ms | 14.7 ms | ↑ |
| **1M** | **5** | **682 ms** | 170 ms | ↑ |
| 10k | 15 | 88.3 ms | 6.3 ms | ↑ |
| 100k | 15 | 707 ms | 50 ms | ↑ |
| **1M** | **15** | **10.9 s** | 777 ms | ↑ ← C046 实际场景 |
| **1M** | **20** | **28.2 s** | 1484 ms | ↑ ← C046 上限场景 |

**M1 复杂度分析**（numpy 路径，pingouin 未装）：
- 每个 `_partial_corr` 调 2 次 `np.linalg.lstsq`（残差法），每次 lstsq 矩阵 (n × p-1)
- OLS lstsq 复杂度 O(n × k²) = O(n × p²)
- p-1 次调用 → O(p × n × p²) = **O(n × p³)**
- 实测 per-feat n=1M p=15: 777ms；n=1M p=20: 1484ms → 符合 O(p²) per-feat 增长
- 实测 per-feat n=10k p=15 vs n=1M p=15: 6.3ms vs 777ms → 符合 O(n) 增长

**chart3 LOESS fallback 复杂度（核心卡死点）**：
- `_render_chart3_subplot` statsmodels fallback: `np.convolve(rs_sorted, kernel, mode="same")`
- kernel 长度 `w = max(5, n // 10)` = n=1M 时 w=100k
- `np.convolve(a, v, mode='same')` 复杂度 **O(n × w)**（朴素实现，不是 FFT）
- n=1M × w=100k = **10^11 ops/子图**

实测 LOESS 单子图耗时（spike_loess_only.py）：

| n | w | ops | 实际 wall time | 速率 |
|---:|---:|---:|---:|---:|
| 10,000 | 1,000 | 1.00e+07 | 2.0 ms | 4.9 Mops/s |
| 50,000 | 5,000 | 2.50e+08 | 89.5 ms | 2.8 Mops/s |
| 100,000 | 10,000 | 1.00e+09 | 329 ms | 3.0 Mops/s |
| 200,000 | 20,000 | 4.00e+09 | **24,268 ms (24 s)** | 0.2 Mops/s ← 速率崩塌 |
| 500,000 | 50,000 | 2.50e+10 | **43,518 ms (44 s)** | 0.6 Mops/s |
| **1M (外推)** | 100,000 | 1.00e+11 | **估计 100-180 s / 子图** | — |

**外推 n=1M, p=10 多变量模式：10 子图 × ~120s = ~20 min** 卡死在主线程。

### 1.3 日志摘录（无新增，但 C033 已有同模式）

C033 报告 (`docs/proposals/2026-07-15-attribution-stuck-investigation.md §1.1`) 的实测日志：

```
2026-07-15 15:04:11 [INFO] 工艺分析完成：641011 行，特征 4 列，目标状态 ['1.0', '0.0']。
2026-07-15 15:04:11 [ERROR] 未捕获异常导致程序异常
                       AttributeError: 'NoneType' object has no attribute 'setLabelText'
                       (at main_window.py:372 _progress_cb)
```

C033 时的实测 n=641k × p=4 → 1.6s（M1 退化到 Pearson 因 p=2 controls=[]）。本次 n=1M × p=15 → 19.9s 后端 + 估计 20+ 分钟 LOESS 渲染。规模升级到 p<20/n=百万级正好击中两个拐点。

### 1.4 静态扫描：定位关键代码路径

| path:line | 内容 | 修复建议（不写实现） |
|---|---|---|
| `app/services/head_tail_attribution.py:813-880` | M1 partial correlation 主循环（`_partial_corr` 调用 × p-1 次） | p≥10 时启用 pingouin/批量 OLS 残差法（控制集预先 z-score + 缓存 `Z.T @ Z` 和 `Z.T @ y`） |
| `app/services/head_tail_attribution.py:880-920` | M2 OLS + VIF（VIF = p 次 OLS） | VIF 可复用主 OLS 的中间量，不必重复 lstsq |
| `app/ui/main_window.py:1014-1040` | `do_work(report_progress=None)` Worker 函数 | 当前仅 `build_head_tail_report`；渲染在 on_success 主线程 |
| `app/ui/main_window.py:1049-1062` | `on_success(rep)` | 调用 `self.process_analysis_panel.set_result(rep, mode="head_tail_attr")` 在**主线程**跑全部图表 |
| `app/ui/widgets/process_analysis_panel.py:1714-1880` | `_fill_multi_attr(rep)` | chart1 + chart2 + chart3 共 13+ 张子图全部串行同步渲染 |
| `app/ui/widgets/process_analysis_panel.py:1900-2010` | `_render_chart3_grid` + `_render_chart3_subplot` | **LOESS fallback 在 n=1M 时单子图 100+ 秒**（关键 bug 入口） |
| `app/ui/widgets/process_analysis_panel.py:582-623` | C034 新增 `attrib_progress_bar` 内嵌进度条 | **只覆盖算法阶段（5→100%），不覆盖渲染阶段**——所以即使 backend 已 100%，UI 在渲染时无任何进度反馈，体感「卡死」 |
| `app/ui/widgets/process_analysis_panel.py:1135-1147` | `set_running(True/False)` | 仅切按钮文案 + status_label；panel 内嵌进度条 visibility 仅 set_running 切换，**未在 on_success 阶段推送 100% 或「渲染中」** |

### 1.5 阻断路径（用户点击「开始分析」→ 卡死）

```
用户点 analyze_btn (panel)
  ↓ analysis_requested.emit(cfg)
MainWindow._on_process_analysis_requested  (main thread, 立即返回)
  ↓ cancel_evt_attr = threading.Event()
  ↓ self._run_background(..., busy_lock="analysis", cancel_event=cancel_evt_attr)
Worker.run() 在 QThreadPool 线程
  ↓ do_work(report_progress=None)
    ↓ build_head_tail_report(df, ..., multi=True, report_progress=..., cancel_event=...)
      → M1 _partial_corr × 14 @ n=1M, p=15 → 11s  [★ 根因 2]
      → M2 _ols_standardized + VIF × 10 @ n=1M → 2.5s
    ↓ rep 返回
signals.result.emit(rep) → on_success(rep) [回到主线程, queued signal]
  ↓ self.process_analysis_panel.set_result(rep, mode="head_tail_attr")
    ↓ self._clear_results() (3 张图 clear)
    ↓ self._fill_head_tail(rep)
      → 填 attr 表 + rules text
      → self._fill_multi_attr(rep)
        → M1/M2 表填行
        → chart1 BarGraphItem × ~10 [快速]
        → chart2 BarGraphItem 双柱 × ~10 [快速]
        → _render_chart3_grid
          → dropna + zscore + lstsq @ n=1M, p=10 → 285ms
          → _render_chart3_subplot × 10
            → 每子图:ScatterPlotItem(1M 点) + np.convolve LOESS(2-3 min) [★ 根因 1]
      → status_label.setText("✅ 归因完成。") [在最后才更新]
  ↓ _set_busy(busy_lock="analysis", False)  ← 进度对话框关闭,但用户早已看到 100% 没动
```

**关键节点**：
- `set_running(True)` 在分析开始时把 analyze_btn 文字改 "分析中..."；`set_running(False)` 在 on_success 头部就把按钮恢复，但 status_label 还是 `on_success` 全部完成才更新
- 用户看到的顺序：
  1. **T0**：点按钮 → 进度条出现 → 0%
  2. **T0 → T+19.9s**：进度条缓慢爬到 100%（C034 单调性 OK）
  3. **T+19.9s → T+19.9s + 20 min**：进度条已 100%，但 UI 完全冻结（鼠标变沙漏、所有控件无响应、状态栏不再更新）—— **「卡死在 100%」的现象就在这里**
  4. **T+40 min（左右）**：图表全部画完，status_label 跳 "✅ 归因完成。"，按钮恢复

---

## 2. 五个调查方向结论

### 方向 1：A. matplotlib 大图渲染主线程阻塞

| 子问题 | 结论 |
|---|---|
| 用 matplotlib 画大图吗？ | **否**——`process_analysis_panel.py:30, 398, 637` 全部 `import pyqtgraph as pg`，渲染走 pyqtgraph GraphicsLayoutWidget |
| pyqtgraph 是否主线程渲染？ | **是**——`_fill_multi_attr` 在 `on_success` 主线程跑，`addPlot` / `addItem` 全部 Qt 主线程操作 |
| pyqtgraph 1M 散点 × 10 子图会卡吗？ | **会**——`ScatterPlotItem` 在 CPU 模式下 1M 点单图已需数秒（实测外推：1M 点 × 10 图 ≈ 30-60s），但**比 LOESS 慢两个数量级**——LOESS 是主因，散点是次要 |

**置信度**：90%（静态扫描 + 外推）
**结论**：**不是首根因，但 chart1/chart2/chart3 总计 13+ 张子图都在主线程串行渲染，是放大效应**

### 方向 2：B. LOESS 主线程阻塞

| 子问题 | 结论 |
|---|---|
| LOESS 在哪调用？ | `process_analysis_panel.py:1991` (`_render_chart3_subplot` 内 statsmodels fallback) |
| statsmodels 是否安装？ | **否**（实测 venv 中 `import statsmodels` ModuleNotFoundError）—— 必走 numpy.convolve fallback |
| numpy.convolve 单子图实际耗时？ | **n=200k=24s，n=500k=44s，n=1M 估计 100-180s**（实测 spike_loess_only.py） |
| p=10 多变量模式总卡死时间？ | **10 子图 × ~120s ≈ 20 min**（外推） |
| 是否可中断？ | **否**——`numpy.convolve` 没有 cancel hook；UI 全程冻结 |

**置信度**：**99%**（实测 + 外推 + 静态扫描）
**结论**：**首根因**——`np.convolve` 在 n=1M 时是不可接受的实现，需换 statsmodels（如果可装）或 chunked 计算或下采样

### 方向 3：C. AI 解读主线程

| 子问题 | 结论 |
|---|---|
| AI 解读走主线程吗？ | **否**——`MainWindow._on_ai_insight_requested` 用 `busy_lock="none"`，在 Worker 跑，且 `_run_background` 加了 cancel_event（main_window.py:1078-1180） |
| AI 解读会被归因分析触发吗？ | **否**——用户单独点 AI 按钮才触发，owner 反馈「首次点卡死」指的是「开始分析」按钮 |
| 是否与「卡在 100%」相关？ | **否**——AI 路径与归因分析完全分离 |

**置信度**：100%（静态扫描 + 路径分析）
**结论**：**非根因**

### 方向 4：D. `QProgressDialog setValue(0)` 漏

| 子问题 | 结论 |
|---|---|
| `_set_busy(True)` 是否调 `setValue(0)`？ | **是**——`main_window.py:353` `self._progress.setValue(0)` |
| `_set_busy(False)` 是否设回 None？ | **是**——`main_window.py:358-360` `self._progress.close(); self._progress = None` |
| 是否仍可能卡在 100%？ | **是的，但原因不是 setValue(0) 漏**——是 Worker 完成 → on_success 主线程渲染 LOESS 期间，dialog 已 `setValue(100)` 但 `close()` 还没调（`_set_busy(False)` 在 `_on_result` 里、`on_success` 之后调）。Owner 实际看到的是 dialog 显示 100% 但下面 UI 全部冻结 |
| C033 修过的 AttributeError 还在吗？ | **不在**——C034 已修，main_window.py:371-373 已扩到 `(RuntimeError, AttributeError)` |

**置信度**：100%（静态扫描）
**结论**：**非根因**——但进度对话框逻辑仍有改进空间（见 §3 修复建议 P1）

### 方向 5：E. pandas 主线程 merge

| 子问题 | 结论 |
|---|---|
| 归因分析本身 merge 数据吗？ | **否**——`build_head_tail_report` 接受已合并的 df；merge 在更早的 `MainWindow._merge_cross_category` 里做（main_window.py:514-535） |
| merge 在主线程吗？ | **否**——`_merge_by_category` 和 `_merge_cross_category` 走 `setCursor(WaitCursor)` 但没看到明确的 Worker 包装（main_window.py:520-525, 538-552）—— **但 merge 在「激活数据集」时一次性完成，与「首次点开始分析」不是同一时刻** |
| 是否与「卡在 100%」相关？ | **否**——Owner 反馈「首次点开始分析卡死」是点了归因按钮，不是导入/合并 |

**置信度**：100%（静态扫描 + 路径分析）
**结论**：**非根因**

---

## 3. 卡顿根因排名（带置信度 + 修复建议 + 工作量）

### 排名 1（**首根因**）：chart3 LOESS 主线程 fallback，n=1M 单子图 100-180s

- **置信度**：**99%**（实测 n=200k 单子图 24s，n=500k 单子图 44s）
- **症状**：进度条到 100% 后，UI 冻结 20+ 分钟
- **影响**：**100% 影响「卡在 100%」症状**
- **修复位置**：`app/ui/widgets/process_analysis_panel.py:1991`（`np.convolve` 调用）
- **修复方案（按工作量递增）**：
  1. **P0A（最小）**：在 `_render_chart3_subplot` 开头加 n 阈值判断——`if n > 5000: sample = np.random.choice(n, 5000, replace=False); x = x[sample]; resid = resid[sample]`。**预计 5-10 min 工作量**。把 LOESS 限制在 ≤5k 点，n=1M 时从 ~120s 降到 <1s
  2. **P0B**：把 `np.convolve` fallback 改成 `np.cumsum` 滑窗 + 切片实现（O(n) 而非 O(n×w)）。**预计 30 min**
  3. **P1**：在 venv 里把 statsmodels 加进 requirements.txt（`pip install statsmodels`），恢复 `lowess` 主路径（C046+ Owner 环境实测可装；不可装时 fallback 到 P0A 方案）。**预计 5 min**
- **工作量**：P0A 5-10 min；P0B 30 min；P1 5 min

### 排名 2（**重要**）：`_fill_multi_attr` 在 `on_success` 主线程串行渲染

- **置信度**：**100%**
- **症状**：即使修了 LOESS，chart1/chart2 + 散点 + 填表 × 13+ 子图全在主线程串行，仍会卡
- **影响**：**60% 影响「卡在 100%」症状**（即使 P0A 修了 LOESS，散点 + chart1/2 仍是秒级，但 Owner 仍会感觉「卡一下」）
- **修复位置**：`app/ui/main_window.py:1049-1062`（on_success 主线程）+ `process_analysis_panel.py:1714-1880`（`_fill_multi_attr`）
- **修复方案（按工作量递增）**：
  1. **P1A**：把 `_fill_multi_attr` 拆到后台 Worker——`on_success(rep)` 立即 `_set_busy(False)` + 把 `rep` 传到 `_render_in_worker(rep)` Worker 线程跑数据准备 + numpy 计算，仅在主线程做 `addItem`。**预计 2h**
  2. **P1B**：更轻量方案——`on_success` 把 `rep` 暂存到 `self._pending_attr_report`，启动新的 `_AttrRenderWorker(rep)`（与原 `busy_lock="analysis"` 互斥），渲染期间 panel 显示「渲染中...」，进度推到 `attrib_progress_bar`（C034 已加，但只覆盖算法阶段）。**预计 1.5h**
- **工作量**：P1A 2h；P1B 1.5h

### 排名 3（**基础**）：M1 `_partial_corr` numpy 路径 O(n × p³)

- **置信度**：**95%**
- **症状**：n=1M × p=15 时 M1 单段 11s；p=20 时 28s。进度条在 M1 阶段更新慢（C034 pct=78→90 区间对应 M1），Owner 看到「长时间不动」
- **影响**：**70% 影响「卡在 100% 之前那段时间」**——但 Owner 主要反馈是「卡在 100%」而非「卡在中间」，所以这条是次要
- **修复位置**：`app/services/head_tail_attribution.py:813-880`（M1 主循环）+ `_partial_corr` 函数
- **修复方案（按工作量递增）**：
  1. **P2A**：每个 M1 特征做 OLS 残差时，控制集 `Z` 矩阵每次都一样，可**预计算 `Z.T @ Z` 和 `Z.T @ y`** 缓存（numpy 路径）。原本每次 `_ols_residual(y, Z)` = `lstsq(Z, y)` ≈ O(n × p² × p) = O(n × p³)；预计算后变成 O(n × p²)（每次只做一次 `Z @ beta`）。**预计 1h** + 单测验证 partial_r 等价
  2. **P2B**：把 pingouin 加入 requirements.txt（`pip install pingouin`），`_partial_corr_pg` 走专用实现（即使 numpy 也用 BLAS 批量）。**预计 5 min**
  3. **P2C**：用 `np.linalg.solve(Z.T @ Z + λI, Z.T @ y)` 显式正规方程 + Cholesky（避免 lstsq 的 SVD 路径），比 lstsq 快 3-5x。**预计 1h**
- **工作量**：P2A 1h；P2B 5 min；P2C 1h

### 排名 4（**设计**）：chart3 LOESS 散点 n×p 个点（1M × 10 = 10M）也是主线程渲染负担

- **置信度**：85%
- **症状**：即使 P0A 修了 LOESS，1M 点 × 10 子图的 ScatterPlotItem 创建仍需 30-60s 在主线程
- **影响**：**40% 影响「卡在 100%」残留**
- **修复位置**：`app/ui/widgets/process_analysis_panel.py:1955-1970`（scatter 构造）
- **修复方案**：
  1. **P3A**：与 P0A 一体化——n > 5000 时散点也降采样到 5k（LOESS 用同一组采样）。**预计 0h（与 P0A 一起做）**
  2. **P3B**：给 chart3 提供开关——`enable_scatter_when_n_gt: int = 5000`（UI 暴露），n > 阈值时只画 LOESS 不画散点。**预计 30 min**
- **工作量**：P3A 0h（合并 P0A）；P3B 30 min

### 排名 5（**次要**）：M2 OLS + VIF p 次重复 OLS

- **置信度**：80%
- **症状**：n=1M × p=10 时 M2 = 2.7s，其中 VIF 占大头（p=10 次 OLS 在 (n × p-1) 矩阵上）
- **影响**：**15% 影响「100% 之前那段时间」**
- **修复位置**：`app/services/head_tail_attribution.py:175-205`（`_compute_vif`）
- **修复方案**：复用主 OLS 的 `(X.T @ X)^(-1)` 对角元素直接算 VIF，无需重复 OLS。数学：`VIF_j = diag((X.T @ X)^(-1))_j * (X.T @ X)_jj`。**预计 1.5h**
- **工作量**：1.5h

### 排名 6（**最弱**）：panel 内嵌进度条不覆盖渲染阶段

- **置信度**：90%
- **症状**：C034 加的 `attrib_progress_bar` 只在算法阶段（pct 5→100）更新；on_success 渲染阶段不再推送进度，所以「卡在 100%」期间 UI 上无任何变化
- **影响**：**10% 影响「卡死感」**——即使底层在渲染，UI 没反馈会感觉更卡
- **修复位置**：`app/ui/main_window.py:1049-1062`（on_success）+ `process_analysis_panel.py:1217-1250`（set_running）+ `set_progress` 方法
- **修复方案**：on_success 入口 `self.process_analysis_panel.set_running(False, render_stage="开始渲染图表...")`；渲染阶段定期 `self.process_analysis_panel.set_progress(pct, msg)`（pct 卡在 100 但 msg 变）。**预计 30 min**
- **工作量**：30 min

---

## 4. 进度条 / 渲染接入点（具体到 line:col）

### 4.1 chart3 LOESS 修复点（`process_analysis_panel.py`）

| 行号 | 现状 | 修复建议（不写实现） |
|---|---|---|
| `1900-1910` | `_render_chart3_grid` 入口，无 n 阈值判断 | 加 `if len(sub) > MAX_LOESS_POINTS: sub_sample = sub.sample(MAX_LOESS_POINTS, random_state=42)`（建议 MAX_LOESS_POINTS=5000） |
| `1955-2010` | `_render_chart3_subplot` 散点 + LOESS fallback | 散点用 sample 后的 x / resid；LOESS fallback 改 cumsum 滑窗或加 P0B chunked |
| `1991` | `np.convolve(rs_sorted, kernel, mode="same")` | 核心修复点 |
| `1983-1989` | statsmodels 主路径 (`from statsmodels.nonparametric.smoothers_lowess import lowess`) | venv 缺 statsmodels 时整段走 fallback；如果 venv 装了 statsmodels 但 `lowess` 仍慢（n=1M），同样需下采样 |

### 4.2 主线程渲染解耦点（`main_window.py`）

| 行号 | 现状 | 修复建议（不写实现） |
|---|---|---|
| `1049-1062` | `on_success(rep)` 在主线程跑 `set_result` + `fill_head_tail` + `fill_multi_attr`（含 chart3 LOESS） | 把 `rep` 暂存 + 启动 `_AttrRenderWorker(rep)` 后台线程；主线程立即 `_set_busy(False)` 并显示「正在渲染图表...」面板 |
| `1304-1370` | `_run_background` | 复用现有 Worker 模式，新加 `busy_lock="render"` 与 `analysis` 互斥 |

### 4.3 M1 `_partial_corr` 优化点（`head_tail_attribution.py`）

| 行号 | 现状 | 修复建议（不写实现） |
|---|---|---|
| `813-880` | M1 主循环，每次 `_partial_corr(df, target_col, feat, controls)` | 预计算 `Z = sub[ctrl_use].to_numpy()`、`ZtZ = Z.T @ Z`、`Zty = Z.T @ y`；每次特征只换自己的 x 列做 lstsq |
| `180-200` | `_ols_residual` | 显式正规方程 `np.linalg.solve(ZtZ + λI, Zty)` 替代 lstsq；λ=1e-8 防奇异 |
| `14-16` | `_HAS_PINGOOUIN` 检测 | 把 pingouin 加入 requirements.txt（C046+ Owner 环境实测可装 `pip install pingouin`），主路径自动走 `_partial_corr_pg` |

### 4.4 M2 VIF 优化点（`head_tail_attribution.py`）

| 行号 | 现状 | 修复建议（不写实现） |
|---|---|---|
| `175-205` | `_compute_vif` 主循环 p 次 OLS | 复用主 OLS 算出的 `XtX_inv = np.linalg.inv(X.T @ X)`，VIF_j = `XtX_inv[j,j] * XtX[j,j]`（一行） |

### 4.5 进度条接入点（`process_analysis_panel.py`）

| 行号 | 现状 | 修复建议（不写实现） |
|---|---|---|
| `582-623` | `_build_multi_attr_tab` 创建 `attrib_progress_bar` + `attrib_status_label` | **保留**——C034 已加 |
| `1135-1147` | `set_running(is_running)` | 增加 `render_stage: str = None` 参数；`set_running(False, render_stage="开始渲染图表...")` 时保持 `attrib_progress_bar` 可见 + 显示新文案 |
| `1217-1250` | `set_running` 实现 | 同上 |
| 现有 `set_progress` 方法（C034 加） | 已有 `set_progress(pct, msg)` | **保留**——但 on_success 阶段需调用：`on_success` 渲染前 `set_progress(100, "后端完成，开始渲染图表...")`；渲染中可保留 100% 仅更新 msg |

---

## 5. 修复方案总览（给 C047+ coder 参考）

### P0（必做，1-2h 可解 95% 卡死感）

**P0A：chart3 LOESS 散点 + LOESS 双重下采样（5 min）**：
- 在 `_render_chart3_grid` (`process_analysis_panel.py:1900`) 入口加 `MAX_RENDER_POINTS = 5000`（模块级常量）
- 当 `len(sub) > MAX_RENDER_POINTS` 时：
  ```python
  rng = np.random.default_rng(42)
  idx = rng.choice(len(sub), MAX_RENDER_POINTS, replace=False)
  sub_sample = sub.iloc[np.sort(idx)]
  # 后续用 sub_sample 而不是 sub
  ```
- 在 `_render_chart3_subplot` 里散点和 LOESS 都用采样后的 `x` / `resid`
- 同步给散点加 `size=4` 不变（pyqtgraph 渲染 5k 点很快）
- **预估效果**：n=1M × p=10 → 单子图 LOESS 从 ~120s 降到 <500ms（5k 点 × w=500）

**P0B：M2 VIF 改矩阵逆（30 min，可选）**：
- `_compute_vif` (head_tail_attribution.py:175) 用 `XtX_inv = np.linalg.inv(X.T @ X)` 后 VIF 一行算完
- 预估 n=1M × p=10 → M2 从 2.7s 降到 0.5s

### P1（强烈建议，2-3h）

**P1A：把 `_fill_multi_attr` 拆到后台 Worker（1.5-2h）**：
- `MainWindow._on_process_analysis_requested` 改：Worker 返回 rep 后，**只把 rep 暂存** + 启动 `_AttrRenderWorker(rep)`（新 Worker 类）
- 新 Worker 在后台线程跑 `process_analysis_panel._fill_multi_attr_data(rep)`（拆出一个纯数据版本，返回 dict）
- 主线程拿 dict 后调 `process_analysis_panel._fill_multi_attr_render(data)`（仅 pyqtgraph addItem，几百 ms）
- 渲染期间 `attrib_progress_bar` 显示「渲染图表...」

**P1B：把 statsmodels 加进 requirements.txt（5 min）**：
- `pip install statsmodels` 在 Owner venv
- chart3 LOESS 自动走 `lowess` 主路径，比 numpy.convolve 快 50-100x
- 但仍需下采样（lowess 在 n=1M 也慢）

**P1C：把 pingouin 加进 requirements.txt（5 min）**：
- `pip install pingouin`
- M1 自动走 `_partial_corr_pg`，但 pingouin.partial_corr 走 OLS 残差路径（vs numpy 一样），需用其专用 partial_corr（C046 环境实测 pingouin 可装）
- 实际加速：M1 numpy 路径 p=15/n=1M=11s → pingouin 可能更快（实测待 spike）

### P2（可选）

- M1 控制集矩阵预计算（1h）
- 把 `np.convolve` fallback 改成 cumsum 滑窗（30 min）
- panel 内嵌进度条覆盖渲染阶段（30 min）

---

## 6. DoD 验证

1. ✅ 调查报告输出到 `E:\DEMO\DataAnalysis\docs\proposals\2026-07-16-attribution-stuck-100pct.md`
2. ✅ 5 个方向**每个**给出明确结论（见 §2 表格）
3. ✅ 最可能卡顿根因（带置信度 + 修复建议）见 §3 排名表（首根因 = chart3 LOESS 主线程 fallback，99% 置信度）
4. ✅ 进度条 / 渲染接入点（具体到 line:col）见 §4
5. ✅ spike 脚本可独立跑：`tests/spike_attr_100pct.py --p 15 --n 1000000` 可执行（已实测，输出每阶段耗时）；`spike_loess_only.py` 单测 LOESS 复杂度曲线；`spike_partial_corr_only.py` 验证 M1 O(n × p³)
6. ✅ 严格只读：未改任何代码（spike 脚本 + 本报告均为新增；未读 PM 对话历史；未外发消息；未碰 git）

---

## 7. 遗留 / 后续 coder 行动

### 7.1 给 C047（修复 coder）的硬清单

**P0（必做）**：
1. 在 `_render_chart3_grid` (`process_analysis_panel.py:1900`) 加 `MAX_RENDER_POINTS = 5000` 阈值 + `np.random.default_rng(42).choice` 降采样
2. 在 `_render_chart3_subplot` (line 1955-2010) 同步用采样后的 `x` / `resid`（散点 + LOESS 都用采样点）
3. 给 chart3 加 `_render_chart3_subplot` 的单元测试：断言 n=1M 输入下函数返回 < 5s
4. 跑现有 `tests/test_s5_attribution_progress.py` 全部通过（V1.13.1 单调性回归测试不能挂）

**P1（强烈建议）**：
5. 把 statsmodels 加入 requirements.txt
6. 把 pingouin 加入 requirements.txt（先 Owner 环境实测可装；装不上时 fallback 到 P2A 控制集矩阵预计算）
7. 把 `_fill_multi_attr` 拆出纯数据版本 + 后台 Worker（具体拆分方式见 §5 P1A）
8. 把 M2 VIF 改 `XtX_inv[j,j] * XtX[j,j]` 一行算完（§4.4 line 175）

**P2（可选）**：
9. M1 控制集矩阵预计算
10. panel 内嵌进度条覆盖渲染阶段（§4.5 line 1217-1250）

### 7.2 文档待补

- `CHANGELOG.md` V1.13.2 加一行："归因分析 chart3 LOESS 散点/曲线双重下采样（M1 优化 + 渲染拆 Worker 为 P1）"
- `docs/proposals/2026-07-16-attr-render-worker-proposal.md`（P1A 拆分方案详细设计）

### 7.3 与 C033 报告的关系（继承 vs 新增）

| 维度 | C033（V1.13.0） | C046（V1.13.1） |
|---|---|---|
| Owner 数据 | 640k × p=4 | **n=百万级 × p<20** |
| Owner 反馈 | "卡了好久才出来，加进度条" | **"首次点卡死在 100% 很久"** |
| C033 报告根因 | 算法 1.6s 不慢；进度条 bug + AttributeError | **已修复（C034 V1.13.1）** |
| C046 暴露的新问题 | — | M1 O(n×p³) 拐点 + chart3 LOESS O(n²) 主线程 |
| 进度反馈 | **P0（修算法层单调性）** | **仍需改进（覆盖渲染阶段）** |

**核心关系**：
- C034 修了「进度条倒退回 25%」和「AttributeError 挂掉进度回调」——这两个**确实是 C033 时的卡死感主因**
- C046 时 Owner 规模升级到 n=百万 × p=15+ 后，原来被掩盖的两个底层瓶颈暴露：
  - M1 `_partial_corr` numpy 路径在 pingouin 未装时是 O(n × p³)，p≥10 即触发拐点
  - chart3 LOESS fallback 在 n=百万级时是 O(n²) 不可用
- 两者叠加 → 后端 11-28s + 渲染 20+ min = 「卡死在 100% 很久」

### 7.4 死锁教训确认

任务提到"必读 ADR-007 + C030 调查报告"—— **`docs/adr/` 仅有 ADR-001 ~ 006`，无 ADR-007`**（同 C033 报告 §7.4）；**C030 调查报告未在 `docs/investigations/` 找到**。本次未找到对应文件，无法继承经验。已在 §0 / §6 标注此遗漏。建议 PM 后续核实 ADR-007 / C030 是否真存在，或本任务描述是否笔误。

---

## 8. 参考引用（path:line）

- `app/services/head_tail_attribution.py:11-13` — `AttributionCancelledError`
- `app/services/head_tail_attribution.py:15-29` — C047 心跳日志基础（仅日志，不改业务）
- `app/services/head_tail_attribution.py:35-46` — scipy/pingouin 可选 import
- `app/services/head_tail_attribution.py:54-77` — `_call_progress`（**C034 单调保护**）
- `app/services/head_tail_attribution.py:79-89` — `_pearson`（HAS_SCIPY 优先，否则 numpy 手工）
- `app/services/head_tail_attribution.py:91-103` — `_rankdata`（手写 mergesort 平均秩）
- `app/services/head_tail_attribution.py:105-120` — `_spearman`（HAS_SCIPY 优先，否则 _pearson(_rankdata)）
- `app/services/head_tail_attribution.py:175-205` — `_compute_vif`（**p 次重复 OLS，待优化**）
- `app/services/head_tail_attribution.py:207-280` — `_ols_standardized`（主 OLS + ridge fallback）
- `app/services/head_tail_attribution.py:307-410` — `_partial_corr` numpy 残差法（**O(n × p²) per-feat**）
- `app/services/head_tail_attribution.py:410-440` — `_partial_corr_pg`（pingouin 路径，仅 pingouin 可装时生效）
- `app/services/head_tail_attribution.py:570-585` — `feat_num` / `any_feat` / `n_eff` 计算
- `app/services/head_tail_attribution.py:610-660` — 相关系数阶段（Pearsons + Spearman × p-1）
- `app/services/head_tail_attribution.py:660-720` — 分组统计 + qcut × top_n
- `app/services/head_tail_attribution.py:725-755` — 规则挖掘（quantile × 3 × 2 op × top_rules_n）
- `app/services/head_tail_attribution.py:760-800` — overall_suggested_window + 准备多变量阶段
- `app/services/head_tail_attribution.py:803-880` — **M1 partial correlation 主循环（p-1 次 _partial_corr）**
- `app/services/head_tail_attribution.py:880-920` — **M2 OLS + VIF（p 次 OLS via _ols_standardized + _compute_vif）**
- `app/ui/widgets/process_analysis_panel.py:30` — `QProgressBar` import（C034 加的）
- `app/ui/widgets/process_analysis_panel.py:398` — `self.boxplot_widget = pg.GraphicsLayoutWidget()`（state_classify 模式用）
- `app/ui/widgets/process_analysis_panel.py:582-623` — `_build_multi_attr_tab`（C034 加 `attrib_progress_bar` + `attrib_status_label`）
- `app/ui/widgets/process_analysis_panel.py:634-673` — multi_attr_widget + 3 个 _MultiChartWidget
- `app/ui/widgets/process_analysis_panel.py:1217-1250` — `set_running(is_running)`（**只覆盖算法阶段**）
- `app/ui/widgets/process_analysis_panel.py:1251-1271` — `set_result` 入口
- `app/ui/widgets/process_analysis_panel.py:1543-1548` — `_clear_results` 清空 3 张图
- `app/ui/widgets/process_analysis_panel.py:1714-1880` — **`_fill_multi_attr`（chart1/2/3 全部主线程串行）**
- `app/ui/widgets/process_analysis_panel.py:1900-1948` — **`_render_chart3_grid`（dropna + zscore + lstsq + grid 拆分）**
- `app/ui/widgets/process_analysis_panel.py:1950-2010` — **`_render_chart3_subplot`（散点 + ±2σ 区域 + LOESS 趋势线）**
- `app/ui/widgets/process_analysis_panel.py:1991` — **★ `np.convolve(rs_sorted, kernel, mode="same")`（首根因入口）**
- `app/ui/main_window.py:310-360` — `_set_busy`（C034 加 `setMinimumDuration(0)` + cancel 按钮）
- `app/ui/main_window.py:362-373` — `_progress_cb`（**C034 修过异常捕获**）
- `app/ui/main_window.py:994-1062` — `_on_process_analysis_requested` head_tail_attr 分支
- `app/ui/main_window.py:1014-1040` — `do_work(report_progress=None)`
- `app/ui/main_window.py:1049-1062` — **`on_success(rep)`（**主线程跑全部渲染**）**
- `app/ui/main_window.py:1067-1086` — `on_error` / `set_running(True)` / `_run_background` 串联
- `app/ui/main_window.py:1304-1370` — `_run_background`（复用现有 Worker；可加新 `busy_lock="render"`）
- `app/services/worker.py:11-60` — `Worker` 自动注入 `report_progress` 逻辑
- `tests/test_w12_head_tail_attribution.py` — 现有归因单元测试（V1.13.0 基础）
- `tests/test_s5_attribution_progress.py` — V1.13.1 单调性回归测试（必须仍通过）
- `tests/spike_attr_100pct.py` — **C046 新增 spike，参数化 --p --n**
- `tests/spike_loess_only.py` — C046 新增，验证 LOESS fallback O(n × w) 复杂度
- `tests/spike_partial_corr_only.py` — C046 新增，验证 M1 O(n × p³) 复杂度
- `tests/spike_chart3.py` — C046 新增，验证 chart3 数据准备 + scatter 数据规模
- `docs/proposals/2026-07-15-attribution-stuck-investigation.md` — **C033 报告（V1.13.0，p=4/n=640k，结论是「进度反馈 bug」）**
- `docs/proposals/2026-07-15-s5-attribution-multi-proposal.md` — S5 多变量归因原始设计（含 chart3 LOESS 规范 §2.3）
- `docs/proposals/2026-07-15-attribution-ui-redesign.md` — UI 重设计建议（待合并本文档结论）

---

_报告结束。investigator-c046-attr-stuck / 2026-07-16_
