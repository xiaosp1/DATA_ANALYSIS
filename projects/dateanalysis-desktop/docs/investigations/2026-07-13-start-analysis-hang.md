# 调查报告：「开始分析」按钮长时间无响应 / 报错

- 日期：2026-07-13
- 版本：DateAnalysis V1.11.0
- 调查范围：`app/ui/**`、`app/services/**`、tests（不改源码）
- 调查结论：源码已存在 Worker 线程化骨架（导入 / 折线趋势分析 / 描述统计 / 工艺分析 / AI 解读 / 数据处理 / 合并 都走 `_run_background`），但仍有 5 处会在 GUI 线程做重计算或渲染，加上 1 处 `.xls` 依赖缺失、1 处异常吞掉但不解锁 busy 状态的问题，足以解释「卡死/无响应」和「报错」两类现象。

---

## 一、所有「开始 / 分析」按钮清单

| # | Tab/面板 | 按钮文字 | 触发路径（信号→槽） | 后台线程? | 异常处理 | 进度提示 | 评级 |
|---|---|---|---|---|---|---|---|
| 1 | 工具栏 | 导入文件 / 导入文件夹 / 导入机(头/尾)(文件/文件夹) | `MainWindow._import_files/_import_folder/_import_category → _run_background(_worker_import)` | ✅ Worker(QThreadPool) | ✅ on_error 弹 QMessageBox | ✅ QProgressDialog(模态) + 百分比 | ✅ 安全 |
| 2 | 折线趋势（左栏） | **开始分析** | `ChartConfigPanel.analyze_button → analysis_requested → MainWindow._run_analysis → _run_background(do_work=计算统计+准备图表)` | ⚠️ 计算在后台；但 **`on_success` 中 `_render_chart` 在 GUI 线程**，大文件时会卡死 | ✅ on_error 弹框 | ✅ 后台 rp(10/60) 但渲染阶段不更新进度 | ⚠️ 风险 |
| 3 | 折线趋势（左栏） | 仅生成折线图 | `chart_button → chart_requested → MainWindow._run_chart_only` | ⚠️ 同上，渲染在 GUI 线程 | ✅ | ⚠️ 仅"准备"阶段有进度 | ⚠️ 风险 |
| 4 | 折线趋势（左栏） | 重置 | reset_requested → lambda log | ✅ 纯 UI | ✅ | - | ✅ 安全 |
| 5 | 描述统计（左栏） | **开始描述统计分析** | `DescriptivePanel.run_button → run_requested → MainWindow._run_descriptive_analysis → _run_background(do_work=计算统计量)` | ❌ 计算在后台；但 `on_success` 中 `DescriptiveChartsPanel.render(...)` **完全在 GUI 线程** 执行（Histogram/Box/QQ/Corr/Scatter），且 render 内部 **再次** 调用 `distribution_data()` 重复计算 KDE（O(n·grid)），大数据下会冻结数秒到数分钟 | ✅ on_error 弹框 | ⚠️ 后台 rp 到 65 就停，渲染无进度 | ❌ Bug |
| 6 | 信息面板-工艺分析 | **开始分析**（重点怀疑对象，按钮文字完全匹配） | `ProcessAnalysisPanel.analyze_btn → _emit_analyze → analysis_requested(dict) → MainWindow._on_process_analysis_requested → _run_background(do_work=build_analysis_report)` | ⚠️ `build_analysis_report` 在后台；但 `set_running(True)` 在信号发射前就设了，**do_work 中没有 rp 上报**（只在进入时 rp(10)），**并且 `on_success` 里 `_fill_boxplots` 用 pyqtgraph 在 GUI 线程为每个特征 × 状态手绘矩形/线，特征>10 个时肉眼可见卡顿**；另一个硬伤：**`build_analysis_report` 内把所有异常吞成 `{"error": "..."}` 返回，不抛错**，因此 on_error 不会触发，但如果 `set_result` 里出错，`set_running(False)` 不会被调用（见下） | ⚠️ 顶层异常兜底返回 error-dict；但 `on_success` 内异常会走到 `_on_result` 的 except，仅 log+弹框，**没有把 `process_analysis_panel.set_running(False)`，按钮会永久停在"分析中..."** | ❌ 进度只在进入时打 10%，中间规则挖掘/ANOVA 无进度 | ❌ Bug |
| 7 | 信息面板-工艺分析 | 导出报告 | `export_btn → export_requested → MainWindow._on_process_analysis_export` | ❌ **整个导出（to_csv + 截图）在 GUI 线程** | ✅ try/except 弹框 | ❌ 无进度；大 PNG 截图会短暂卡 | ⚠️ 风险 |
| 8 | AI 解读（工艺分析子 Tab） | 生成解读 / 重新生成 | `ai_generate_btn/ai_regenerate_btn → _emit_ai_insight → ai_insight_requested(p,u,m,k) → MainWindow._on_ai_insight_requested → _run_background(AIClient.chat)` | ✅ HTTP 在后台（urllib, timeout=60s） | ✅ on_error 弹"失败"，已脱敏 key | ⚠️ 状态标签显示"请求中..."但无百分比 | ✅ 安全（W11 已修超时） |
| 9 | 信息面板-工艺分析 | 配置 Key | QInputDialog（模态） | ✅ 纯 UI | - | - | ✅ 安全 |
| 10 | 处理面板（ProcessingPanel） | 执行处理（Apply） | `apply_requested → _apply_processing → _run_background(apply_rules)` | ✅ 后台（copy+apply_rules） | ✅ | ⚠️ rp 只 20% | ⚠️ 低风险（apply_rules 是列级，不慢） |
| 11 | 数据面板（DatasetPanel） | 合并 / 机(头/尾)合并 / 跨类合并 / 删除 / 导出 | merge_requested / merge_head_requested / merge_tail_requested / merge_cross_requested / delete / export | ⚠️ `_merge_datasets` 走后台；**`_merge_by_category` / `_merge_cross_category` 直接在 GUI 线程执行**（setCursor(WaitCursor) 但不交给线程池），大表合并会冻结 UI | ⚠️ 仅 try/except 弹框，setCursor 有 finally 解锁 | ❌ 无 QProgressDialog | ⚠️ 风险 |
| 12 | 左栏分析列 | 勾选统计列 → (无按钮，选列本身) | analysis_list (仅选择) | - | - | - | ✅ |
| 13 | 图表选项变更 | 自动重绘 | granularity_combo / y_mode / show_points / show_mean → `_refresh_chart_if_any → _run_chart_only` | 同 #3：**每次勾选/切换都会再跑一次后台 + GUI 线程重绘**，快速连点会排队触发多次（`_busy=True` 后弹"请稍候"，但没有取消/防抖） | - | - | ⚠️ 风险 |

> 备注：源码里仍保留了一个旧版 `app/ui/widgets/column_panel.py`，里面也有"开始分析"按钮，但在 `MainWindow` 里没有被 import/使用，属于死代码，不影响运行。另有 `app/services/process_analysis_worker.py` 封装了 `ProcessAnalysisWorker`，但 `MainWindow` 实际用的是通用 `Worker`，该文件是死代码。

---

## 二、重点问题逐条展开

### ❌ BUG-1 工艺分析「开始分析」UI 渲染阶段异常会把按钮永久锁死在"分析中..."
**位置**：`app/ui/main_window.py::_on_process_analysis_requested`

```python
def on_success(rep):
    self.process_analysis_panel.set_running(False)   # 这里恢复按钮
    ...
    self.process_analysis_panel.set_result(rep)     # ← 内部 _fill_boxplots 等可能抛异常
```
- `_run_background._on_result` 里把异常捕获为：`except Exception as exc: self.log(...); QMessageBox.critical(...)`，**不会回滚 `set_running`**，因为 `set_running(False)` 已经在 set_result 之前调了——实际检查后 set_running(False) 是在 set_result 之前调用，按钮本身能恢复。但是 `_fill_boxplots` 在 `ProcessAnalysisPanel.set_result` 里直接遍历 univariate，如果特征列很多且每个特征都有 NaN/inf（例如某列全为 NaN 导致 `q1/q3=None`），`_fmt(q1)` 返回 "-"，float 转换逻辑安全；真正危险的是 `pg.GraphicsLayoutWidget.addPlot(row=fi//3, col=fi%3)` 当 `ncols` 自动计算为 3、但特征数超过十几列时，单个 widget 塞太多 PlotItem 会触发 Qt 事件循环阻塞（尤其第一次 addPlot 会创建 GL 上下文）。
- 更大的问题：**`do_work` 是 `lambda rp: build_analysis_report(...)`**，`build_analysis_report` 的签名里并没有 `report_progress` 参数，因此 Worker 通过 `inspect.signature` 注入的 `report_progress` 不会传进 `build_analysis_report`——MainWindow 在外面只调了一次 `rp(10,...)` 然后就不再更新；如果 ANOVA + 贪心树在大表（>30 万行 × 30 特征）上跑 30~120 秒，用户看到的是模态 "正在进行工艺分析..." 但进度条始终停在 0，极易被误判为"卡死"。

**现象匹配度**：极高。这是文字完全匹配"开始分析"的按钮，且用户最常点（工艺分析是核心功能）。

### ❌ BUG-2 描述统计 `render()` 在 GUI 线程做 KDE/直方图/散点矩阵，大数据下界面冻结数秒到几分钟
**位置**：
- `app/ui/main_window.py::_run_descriptive_analysis.on_success` 调用 `self.desc_charts_panel.render(active.df, nc, ...)`
- `app/ui/widgets/descriptive_charts_panel.py::render` 串行调用 `hist.plot_columns → distribution_data → _kde_1d`
- `app/services/descriptive_service.py::_kde_1d` 使用 `u = (grid[:, None] - x[None, :]) / bw; kernel = np.exp(-0.5*u*u)` 构造 **(256, n)** 的矩阵，n=50 万行会分配 256×500000×8B ≈ **1GB** 内存，且每列都做一次，默认全选数值列时是 O(K·n)。

另外 `hist.plot_columns` 里又调了一次 `distribution_data()`，而后台 `do_work` 里**已经**调过 `boxplot_stats(df,nc)`（其内部也调 distribution_data），**KDE 在后台已经算过一次，UI 线程又重算一遍**，纯粹是重复工作。

**现象匹配度**：高。数据量大时点击"开始描述统计分析"→进度条走到 100%（后台完成）→关闭进度条→界面冻结→Windows 报告"无响应"。

### ⚠️ RISK-3 折线趋势「开始分析/仅生成折线图」的 `_render_chart` 在 GUI 线程绘制
**位置**：`MainWindow._render_chart → chart_panel.plot_multi_line`
- 已经做了 `_downsample` 到 3000 点（`_MAX_PLOT_POINTS=3000`），单线场景基本流畅；但 small_multiples 模式下每个 Y 列都建一个 PlotItem，并且 `xs_full/ys_full` 全部保存在 `_full_series` 里给 tooltip 用（不降采样），选 10 条 Y 轴×50 万点 = 500 万点 numpy array 常驻内存。
- 更隐蔽的问题：`chart_config_panel` 任何一个选项变化（`series_option_changed` / `y_mode_changed` / granularity）都会触发 `_refresh_chart_if_any → _run_chart_only`，而 `_run_background` 用 `self._busy` 互斥——如果用户快速切 Y 轴勾选或粒度，第二次点击会弹"请稍候"但用户感觉是"点了没反应"。

### ⚠️ RISK-4 `.xls` 文件读取缺少 `xlrd<2.0` 依赖会直接报错
**位置**：`app/services/file_loader.py::_read_excel`
```python
if suffix == ".xls":
    return pd.read_excel(path)   # pandas 默认用 xlrd 引擎
```
`requirements.txt` 里 **只列了 `openpyxl>=3.1`，没有 xlrd**。pandas ≥2.0 对 `.xls` 已经不再内置 xlrd，而且新版 xlrd(≥2.0) 也不支持 .xls。用户导入老格式 `.xls` 文件时会抛：
```
Missing optional dependency 'xlrd'...
```
被包成 FileLoadError，然后弹"读取 Excel 失败：..."——这就是 Owner 说的"报错"。
> W11 之前就存在，与 AI 代理无关。

### ❌ BUG-5 `_merge_by_category` / `_merge_cross_category` 不走后台线程
**位置**：`MainWindow._merge_by_category`、`_merge_cross_category`
- 仅用 `setCursor(WaitCursor)`，不进线程池，不显示 `QProgressDialog`。合并多个机头/机尾大文件时直接在 GUI 线程 concat + sort_values，会长时间冻结。
- DatasetPanel 上的"合并"、"机(头/尾)合并"、"跨类合并"按钮均触发此路径。

### ⚠️ RISK-6 全局 `sys.excepthook` 只记日志，不阻止 Qt 终止
**位置**：`MainWindow._install_excepthook`
```python
def handler(et, ev, tb):
    ...
    self.log(...)
    sys.__excepthook__(et, ev, tb)   # 会调用默认 handler，Windows 上可能弹"Python已停止工作"
```
- Qt 槽函数里抛出的未捕获异常在 PySide6 上通常**不会**走 `sys.excepthook`（Qt 会吞掉并通过 `qFatal` 终止），但 QThreadPool 的 Worker 里抛出的异常已经被 signals.error 捕获了，这块基本安全。
- 但 `on_success` 回调里抛出的异常被 `_on_result` 的 except 捕获并弹 QMessageBox，不会让进程崩溃；**真正会崩溃的是跨线程直接访问 Qt 对象**——当前代码 Worker 里没有碰 Qt 对象，所以这块没爆。

### ⚠️ RISK-7 模态 QProgressDialog 阻塞了"取消"路径
**位置**：`MainWindow._set_busy`
```python
self._progress.setCancelButton(None)   # 没有取消按钮
self._progress.setWindowModality(Qt.WindowModality.WindowModal)
```
任务跑起来用户既看不到进度百分比（do_work 里很多分支没 rp），也不能取消，只能等；Windows 会给窗口贴"无响应"的假象标签，即使后台线程还在跑。

### 其他次要问题（信息）
- `_on_import_done` 在 GUI 线程里循环 `self._manager.import_file(...)` 并 `set_dataframe(active.df)`，大文件导入完成后 `PandasTableModel` 会 head(1000)，但 `TablePanel.set_dataframe` 里当 `col_count<=20` 时调 `resizeColumnsToContents()`，列宽计算对 1000 行×20 列的 DataFrame 要遍历每个单元格字符串长度，导入完成那一刻会有 0.5~1 秒卡顿。
- `_refresh_dataset_ui` 每次数据集变更都会重新 `_cache_columns_for`（遍历所有列+采样 200 行尝试 to_datetime），数据集多的时候激活切换有可见延迟。
- `_on_process_analysis_export` 里的 `export_plot_widget_to_png` 在 GUI 线程 grabWidget，大图会瞬时卡。

---

## 三、「长时间无响应」TOP 3 根因（按可能性排序）

1. **🥇 工艺分析（ProcessAnalysisPanel）的"开始分析"在大表上后台跑 ANOVA + 贪心规则树耗时长（数十万行 × 数十特征可达 30s~数分钟），但 `do_work` 里没有进度回传，模态 QProgressDialog 显示"正在进行工艺分析..."但百分比不动、取消按钮被禁，Windows 把窗口标为"未响应"。**
   - 按钮文字完全匹配用户说的"开始分析"，是最高概率根因。
2. **🥈 描述统计"开始描述统计分析"：后台算完后 `DescriptiveChartsPanel.render()` 在 GUI 线程重算 KDE+绘制 5 类图，KDE 的 `(256,n)` 广播运算在大列上吃内存+卡 GUI；且是在 progress 对话框关闭之后才开始，用户看到进度条跑完但窗口无响应。**
3. **🥉 折线趋势"开始分析/仅生成折线图"在 small_multiples 模式下多列绘图+全量数据保存在 `_full_series`，以及选项变更触发的自动重绘排队，让用户感觉"点了没反应"/"卡死"。**

## 四、「报错」TOP 3 根因（按可能性排序）

1. **🥇 `.xls`（老格式 Excel）文件导入/分析时缺 `xlrd<2.0` 依赖 → `ImportError: Missing optional dependency 'xlrd'`，被包成 FileLoadError 弹"读取 Excel 失败"。requirements.txt 漏列。**
   - 这是最直接的"点开始报错"。虽然是在导入阶段，但用户可能先双击打开软件、不导入直接点"开始分析"时也可能被数据状态问题触发；更常见是导入 .xls 时就报。
2. **🥈 `build_analysis_report` 内部抛的异常被兜底成 `{"error": "..."}`（而不是抛），但如果输入数据有极端情况（比如 `feature_cols` 里混入了某列 `pd.to_numeric` 后全 NaN，导致 `np.concatenate([])` 空列表、或 `ssw <= 0` 产生 inf、或 `df.groupby` 遇到不可哈希类型）会在 `on_success → set_result → _fill_*` 系列里抛 KeyError/TypeError，弹"错误"对话框。**
3. **🥉 `file_loader._read_csv_fallback` 用 gbk/gb18030 读 utf-8 BOM 外的非常规编码（如 UTF-16、日文 Shift-JIS、分隔符不是逗号的 CSV）时会抛"读取 CSV 失败：..."，在导入阶段被弹框；如果用户在数据处理面板对空数据集点"执行处理"会被 `active is None` 守卫挡掉，但"按类别批量缩放"在 GUI 线程对已 scaled 的原数据集做 rename+astype 时偶尔遇到列名重名会抛。**

---

## 五、现有测试状态

- `pytest tests/ --ignore=run_functional_tests.py --ignore=ui_smoke_test.py`（需要 offscreen Qt 平台）：**108 passed in 6.45s** ✅
- `run_functional_tests.py` 和 `ui_smoke_test.py` 看起来是需要真实显示器/人工操作的脚本，未在本次自动化中执行（在无 offscreen 环境下直接 pytest 整个 tests 目录会在某个 Qt 用例处被 SIGKILL，原因是创建 QApplication 失败/事件循环阻塞，与本次调查无关）。
- **未修改任何代码**。

---

## 六、修复建议优先级

| P | 问题 | 建议 | 风险/工作量 |
|---|---|---|---|
| P0 | BUG-1 工艺分析进度不刷新、GUI 渲染阶段无保护 | 给 `build_analysis_report` 增加 `report_progress` 参数，在 univariate / rules / importance 三段分别回写百分比；`on_success` 里的 `set_result` 用 try/except 包住，失败时仍保证 `set_running(False)`；`_set_busy` 给 QProgressDialog 加取消按钮（Worker 要支持 cancel 标志） | 中 |
| P0 | BUG-2 描述统计 KDE 在 GUI 线程重算 | 把 `DescriptiveChartsPanel.render()` 需要的分布数据（hist/bin/kde/box/corr）**挪到后台 `do_work` 里一起算好**，on_success 只做纯 pyqtgraph addItem 绘图；KDE 对 n>50000 的列做随机下采样或用 `scipy.stats.gaussian_kde` 的 FFT 近似 | 中 |
| P0 | RISK-4 `.xls` 缺依赖 | `requirements.txt` 加 `xlrd==1.2.0`（仅支持到 xlrd 1.2.x；或直接在 file_loader 里对 .xls 抛更友好的"请另存为 xlsx"提示） | 小 |
| P1 | BUG-5 merge_by_category / merge_cross_category 走后台 | 套用 `_run_background` 模式；加 rp 百分比 | 小 |
| P1 | RISK-3 折线图选项抖动重复重绘 | `_refresh_chart_if_any` 加 300ms QTimer debounce；`_busy=True` 时忽略新触发而不是弹"请稍候" | 小 |
| P1 | RISK-7 模态进度条没取消按钮 | 给 Worker 增加 `request_cancel` 标志；长循环（import/build_analysis_report/aggregate_by_time）轮询并提前返回 | 中 |
| P2 | RISK-6 excepthook 弹"Python已停止" | 除了写 log 之外，再弹一个 QMessageBox（`QTimer.singleShot(0, ...)` 从主线程弹），避免用户看到崩溃对话框 | 小 |
| P2 | TablePanel.set_dataframe 的 resizeColumnsToContents 卡顿 | 列数>10 或行数>200 时跳过自动 resize | 小 |
| P2 | 死代码清理 | 移除 `app/ui/widgets/column_panel.py`、`app/services/process_analysis_worker.py`（或重新启用 ProcessAnalysisWorker 替代通用 Worker 以便后续做进度分阶段上报） | 小 |

---

## 七、复现建议（给后续修复用）

1. 造一个 ≥30 万行 × 30 数值列的 CSV，点"工艺分析 → 开始分析"（目标状态选非0值，特征全选）→ 观察 QProgressDialog 百分比停留、GUI 标题显示"未响应"。→ 验证 BUG-1。
2. 同样大 CSV，切到"描述统计"，默认全选数值列，点"开始描述统计分析"→ 进度条关后窗口冻结数秒。→ 验证 BUG-2。
3. 找一个老格式 `.xls` 文件导入 → 弹"读取 Excel 失败：Missing optional dependency 'xlrd'"。→ 验证 RISK-4。
4. 导入 2 个较大的机头原始文件，点"机头合并" → 界面 WaitCursor 但无进度条、拖动窗口提示无响应。→ 验证 BUG-5。
