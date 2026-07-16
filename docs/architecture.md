# Architecture — 脱模优化数据分析桌面软件

> 项目名称：脱模优化_数据分析
> 代码路径：`projects/dateanalysis-desktop/`
> 当前版本：V1.8.0（含 AI 集成、归因分析、小多图/双Y轴等能力）

---

## 1. 项目简介

本软件是一款面向脱模工艺优化的本地桌面数据分析工具，运行于 Windows 平台。核心功能包括：

- **数据导入**：CSV / XLSX / XLS 文件，支持单文件、批量、文件夹递归导入
- **多数据集管理**：原始导入 + 临时储存区（处理/合并/跨类），互不覆盖
- **统计分析**：综合统计、描述统计（CV/偏度/峰度/分位数/相关矩阵/散点矩阵/箱线图/QQ 图）
- **可视化**：pyqtgraph 多 Y 折线图（共享/双Y/归一化/小多图），支持时间粒度聚合、悬停 tooltip
- **数据处理**：按列条件删除行/替换均值/缩放为 mm（float32 单精度）
- **工艺窗口分析**：自动列识别 → 单变量工艺窗口 → 贪心分类树规则挖掘 → ANOVA 特征重要性
- **归因分析**：机头参数对机尾指数-s 的 Spearman/Pearson 相关 + 分箱 + 规则挖掘
- **AI 集成**：可选调用 OpenAI-compatible API（OpenAI/DeepSeek），基于聚合统计生成解读
- **导出**：统计结果（CSV/XLSX）、图表（PNG）、数据集

---

## 2. 技术栈

| 类别 | 技术 | 版本要求 | 用途 |
|------|------|----------|------|
| UI 框架 | PySide6 (Qt for Python) | >= 6.6 | 主窗口、面板、Dock、控件 |
| 图表引擎 | pyqtgraph | >= 0.13 | 高性能实时折线图/散点矩阵 |
| 数据处理 | pandas | >= 2.2 | DataFrame、合并、聚合 |
| 数值计算 | numpy | >= 1.26 | 数组运算、KDE、降采样 |
| 统计 | scipy | >= 1.10, < 2.0 | 可选，Pearson/Spearman 相关系数 |
| Excel I/O | openpyxl, xlrd | openpyxl>=3.1, xlrd==1.2.0 | .xlsx/.xls 读取 |
| 配置加载 | tomllib | Python 3.11+ stdlib | 读取 ~/.codex/config.toml |
| HTTP 请求 | urllib (stdlib) | — | AI API 调用（非 requests） |
| 日志 | Python logging stdlib | — | 按天滚动写入 logs/ |
| 运行时 | Python | 3.12 | 目标版本 |

---

## 3. 模块架构

```
app/
├── main.py                          # 入口：QApplication + MainWindow
├── models/                          # 数据模型层（纯 Python 对象）
│   ├── dataset_item.py              #   数据集条目（原始/处理/合并 + 类别/缩放状态）
│   ├── dataset.py                   #   文件级数据集（含列元信息）
│   ├── processing_rule.py           #   数据处理规则（删除/替换/缩放）
│   ├── stats_result.py              #   单列统计结果
│   └── chart_config.py              #   图表配置
├── services/                        # 业务逻辑层（无 Qt 依赖，可单测）
│   ├── file_loader.py               #   CSV/Excel 加载 + 编码自动探测
│   ├── dataset_manager.py           #   多数据集 CRUD + 合并（同类/跨类/时间列）
│   ├── data_processor.py            #   列类型推断 + 图表数据准备
│   ├── data_processing.py           #   规则引擎 + 按类别批量 mm 缩放
│   ├── stats_service.py             #   综合统计（max/min/mean/var/std 等）
│   ├── descriptive_service.py       #   描述统计（CV/偏度/峰度/KDE/箱线图/QQ/相关矩阵）
│   ├── process_analysis.py          #   工艺窗口分析引擎（列识别/单变量窗口/规则挖掘/特征重要性）
│   ├── process_analysis_worker.py   #   工艺分析 QRunnable 封装
│   ├── head_tail_attribution.py     #   机头→机尾归因分析（相关系数/分箱/规则挖掘/工艺窗口）
│   ├── time_aggregation.py          #   时间粒度聚合（原始/分钟/小时/班次/天/周）
│   ├── export_service.py            #   导出（CSV/XLSX/PNG）
│   ├── worker.py                    #   通用 QThreadPool Worker 封装
│   ├── app_logger.py                #   应用日志（按天滚动）
│   ├── ai_client.py                 #   AI API 客户端（stdlib urllib + watchdog 硬超时 + 软取消）
│   ├── ai_config.py                 #   AI 配置加载链（json → codex config → env → preset）
│   └── ai_prompt.py                 #   AI prompt 构造（工艺分析/归因分析）
├── ui/
│   ├── main_window.py               #   MainWindow：主窗口 + 全部信号绑定 + 业务编排
│   └── widgets/
│       ├── chart_panel.py           #     折线趋势图表（pyqtgraph PlotWidget + 小多图 + 双Y轴）
│       ├── data_table_panel.py      #     数据预览 TablePanel（QTableView + pandas 模型）
│       ├── multi_table_panel.py     #     多标签统计结果表
│       ├── dataset_panel.py         #     数据集列表/激活/删除/合并/导出
│       ├── processing_panel.py      #     数据处理面板（规则/缩放/排除列）
│       ├── chart_config_panel.py    #     图表配置（列选择/颜色/均值线/系列选项）
│       ├── chart_options_panel.py   #     图表选项（时间粒度/Y 轴模式）
│       ├── descriptive_panel.py     #     描述统计面板（按钮+列选择+结果表）
│       ├── descriptive_charts_panel.py # 描述统计图表（直方图/KDE/箱线图/QQ/相关矩阵/散点矩阵）
│       ├── process_analysis_panel.py # 工艺分析面板 + AI 解读集成
│       └── (其他辅助面板)
└── utils/
    ├── file_utils.py                #   文件工具
    ├── timer_utils.py               #   耗时计时/格式化
    └── type_utils.py                #   类型安全转换
```

### 依赖关系（顶层 → 底层）

```
main_window.py
  ├── widgets/*                     # 各功能面板
  ├── services/ai_client.py         # AI（独立子图）
  ├── services/export_service.py    # 导出（独立）
  ├── services/worker.py            # 后台线程调度
  └── models/                       # 数据模型
```

**关键约束**：`services/` 下的核心分析模块（`process_analysis.py`、`head_tail_attribution.py`、`descriptive_service.py`）**不依赖 Qt**，可在 pytest 中直接单测。

---

## 4. 关键目录结构说明

### `app/models/` — 数据模型
- **`DatasetItem`**：数据集运行时对象，包含 `dataset_id`、`name`、`kind`（original/processed/merged）、`df`（pandas DataFrame）、`source_files`、`can_delete`、以及 V1.7 扩展的 `category`（head/tail/None）、`pixel_factor`、`scaled`。
- **`ProcessingRule`**：数据处理规则对象，描述删除行、替换均值、按因子缩放三种操作。
- **`DataSet` / `ColumnMeta`**：文件加载时的元数据模型。

### `app/services/` — 业务逻辑
- 纯 Python 层，**不耦合 Qt**，保证可测试性和未来迁移能力。
- 分析引擎（`process_analysis.py`、`head_tail_attribution.py`）采用**纯函数**设计，输入 DataFrame，输出 dict 报告。
- AI 客户端（`ai_client.py`）使用 Python 标准库 `urllib`，不依赖 requests。

### `app/ui/widgets/` — UI 组件
- 每个面板继承 `QWidget`，通过信号/槽与 `MainWindow` 通信。
- `ChartPanel` 是最大最复杂的组件（约 800 行），封装 pyqtgraph PlotWidget，支持：
  - 多 Y 折线图（shared/dual/normalized/small_multiples）
  - 自动降采样（>3000 点）
  - 悬停 tooltip
  - 均值线
  - 小多图（Small Multiples）布局

### `app/utils/` — 工具层
- 类型安全转换、计时器、文件工具。

### `tests/` — 测试
- 19 个测试文件，覆盖功能层和 UI 层。
- `ui_smoke_test.py`：端到端冒烟测试（PySide6 offscreen 模式），当前因 Qt 6.8+ offscreen 渲染限制，标记为"需手动执行"。

---

## 5. 数据流向

```
CSV/XLSX 文件
    │
    ▼
file_loader.py → DataSet(df, column_metas)
    │
    ▼
DatasetManager.import_file() → DatasetItem(original, can_delete=False)
    │
    ├─── 数据处理（ProcessingRule）──► data_processing.py → DatasetItem(processed, can_delete=True)
    │
    ├─── 同类别合并 ──────────────► DatasetManager.merge_by_category() → DatasetItem(merged)
    │
    ├─── 跨类合并 ────────────────► DatasetManager.merge_cross_category() → DatasetItem(merged, [机头]/[机尾] 前缀)
    │
    ▼
图表绘制路径：
  data/merged DataFrame
    → data_processor.py → prepare_multi_y_chart_data()
    → time_aggregation.py → aggregate_by_time()（可选时间粒度）
    → ChartPanel.plot_multi_line() → pyqtgraph PlotWidget
    │
    ▼
分析路径：
  DataFrame
    → process_analysis.py: infer_columns() → 自动识别时间列/状态列/特征列
    → compute_univariate_windows() → 每个状态×特征的 μ±σ/μ±2σ 窗口
    → fit_greedy_tree() → 贪心分类树规则
    → compute_feature_importance() → ANOVA F 值
    → AI: build_insight_prompt(report) → AIClient.chat() → OpenAI/DeepSeek API
    │
    ▼
  head_tail_attribution.py: build_head_tail_report() → 相关系数 + 分箱 + 规则
    → AI: build_head_tail_prompt(report) → AIClient.chat()
    │
    ▼
导出路径：
  StatsResult → export_service.py → CSV / XLSX
  ChartPanel → export_plot_widget_to_png() → PNG
  DataFrame → export_stats_to_csv/to_excel → CSV / XLSX
```

---

## 6. 线程模型

```
QApplication (主线程 / UI 线程)
    │
    ├── QThreadPool.globalInstance()
    │     │
    │     ├── Worker (通用) ───► QRunnable.run() → 任意 callable
    │     │                          │
    │     │                          ├── report_progress(pct, msg) → Signal → QProgressDialog
    │     │                          ├── result → Signal → on_success callback
    │     │                          └── error → Signal → on_error callback
    │     │
    │     └── ProcessAnalysisWorker ──► build_analysis_report()
    │
    ├── QProgressDialog
    │     ├── 非取消 → 收起弹窗，线程继续后台运行
    │     └── 带 cancel_event → set() → Worker/Analysis 抛出异常退出
    │
    └── QSettings (同步写，不阻塞)
```

- **关键设计**：`QProgressDialog` 的"取消"按钮默认行为是**收起弹窗，不中断线程**（用户选择后台继续）。只有显式传入 `cancel_event` 的操作（AI 请求、归因分析等）才会被软取消。
- **粒度锁**：`_dataset_busy`（数据集操作互斥）+ `_analysis_busy`（分析操作互斥）+ AI 独立（不占全局锁），支持多锁间并行。

---

## 7. AI 集成架构

```
AI Panel (process_analysis_panel.py)
    │
    ├── ai_config.json (项目级配置)
    │     { "providers": { "openai": { "base_url", "model", "api_key" }, ... } }
    │
    ├── QSettings (用户偏好，优先级低于 ai_config.json)
    │
    ├── ai_config.py: load_default_ai_config()
    │     优先级链：QSettings → ai_config.json → ~/.codex/config.toml → 环境变量 → 默认
    │
    ├── ai_client.py: AIClient
    │     ├── 构造：provider + base_url + model + api_key + timeout
    │     ├── chat(messages, temperature, cancel_event)
    │     │     ├── 硬超时：watchdog 线程 + socket.close() 强制中断
    │     │     ├── 软取消：cancel_event.set() → AICancelledError
    │     │     └── 错误分类：HTTP 401/403/429/5xx / 超时 / 连接拒绝
    │     └── 使用 stdlib urllib，不依赖 requests
    │
    └── ai_prompt.py: build_insight_prompt() / build_head_tail_prompt()
          输入：分析/归因报告 dict（仅聚合统计，不传原始行数据）
          输出：[system, user] 消息列表
```

**安全设计**：AI 请求只传递聚合统计（μ/σ/规则/重要性等），不传递原始行数据，确保生产数据不泄露。

---

## 8. 测试架构

### 测试文件清单（19 个文件）

| 文件 | 行数 | 覆盖范围 |
|------|------|----------|
| `test_scale_feature.py` | 330 | 缩放规则引擎（单列/全列/排除列/因子校验/force_rescale） |
| `test_cross_category.py` | 238 | 同类别合并/跨类 outer join/前缀/NaN 行为 |
| `test_descriptive_service.py` | 121 | 描述统计计算（分位数/偏度/峰度/IQR/KDE/箱线图） |
| `test_w8a_analysis_engine.py` | 276 | 工艺窗口分析（列识别/单变量窗口/规则挖掘/特征重要性） |
| `test_w12_head_tail_attribution.py` | 121 | 机尾归因分析（相关系数/分箱/规则挖掘） |
| `test_w10_tooltip_dock.py` | 237 | Tooltip 命中精度 + Dock 布局 |
| `test_w6_dual_axis.py` | 142 | 双Y轴图表绘制 |
| `test_w7_small_multiples.py` | 203 | 小多图布局 |
| `test_w8b_ai.py` | 214 | AI 客户端功能 |
| `test_w11_ai_config.py` | 116 | AI 配置加载链 |
| `test_w6_chart_options.py` | 34 | 图表选项面板 |
| `test_w6_exclude_cols.py` | 66 | 排除列模式 |
| `test_w6_normalize.py` | 49 | 归一化显示 |
| `test_w9_layout.py` | 193 | 窗口布局 |
| `test_w12_ai_busy_fix.py` | 160 | AI 忙状态修复 |
| `test_w8a_panel.py` | 134 | 工艺分析面板 |
| `run_functional_tests.py` | — | 测试运行器 |
| `ui_smoke_test.py` | 479 | 端到端冒烟测试（offscreen 模式，需手动执行） |

### 测试策略
- **单元层**：纯 Python 服务层（`services/*.py`）全部可单测，不依赖 Qt。
- **UI 层**：部分 UI 组件可单元测试（ChartPanel 的降采样/tooltip 函数），部分需要 offscreen Qt（已启用 `QSG_RENDERER=software`）。
- **回归**：每次迭代至少跑 `test_scale_feature.py` + `test_cross_category.py` + `test_w8a_analysis_engine.py` 作为回归基线。
- **验证基线**：`test_scale_feature.py` 14/14 PASS、`test_descriptive_service.py` all passed。

---

## 9. 非功能设计

- **UI 响应性**：所有 pandas 重计算移入 `QThreadPool` 后台，UI 线程只做渲染和交互。
- **图表性能**：单线 >3000 点自动等距降采样；大样本描述统计通过 `ProgressCb` 反馈进度。
- **数据隔离**：原始数据 `can_delete=False`，处理/合并结果 `can_delete=True`，不覆盖原始。
- **配置持久化**：QSettings 存储窗口状态、导入/导出路径、类别 factor、排除列。
- **日志**：`AppLogger` 按天滚动写入 `logs/app_YYYY-MM-DD.log`，异常带 traceback。
- **编码兼容**：CSV 自动探测 UTF-8-sig/UTF-8/GBK/GB18030。
