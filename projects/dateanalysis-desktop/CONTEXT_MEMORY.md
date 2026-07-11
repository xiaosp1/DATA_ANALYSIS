# CONTEXT_MEMORY

## 当前状态
- 版本：V1.6（基础层：描述统计与分布可视化已完成；时序监控 SPC/EWMA/Cpk 规划为 V1.7）
- 最近改动：分析模式切换 UI 重构 + 描述性统计分析（基础层）全套落地
- 下一阶段：时序分析与稳定性（监控层）- I-MR/X-bar R/EWMA 控制图、Nelson 判异、滑动窗口、Cpk、ACF

## 产品目标（对齐 ANALYSIS_METHODOLOGY.md）
本软件服务于"丁腈手套卷边长度视觉检测"数据分析业务，指标为中指尖/拇指尖/虎口三个距离。分析方法分为四层：
1. 基础层：描述性统计（V1.6 已实现）
2. 监控层：时序稳定性 / SPC（V1.7 计划）
3. 诊断层：异常检测 / 变点 / 多变量协同
4. 建模层：脱模关联 / 工艺参数回归 / SHAP
5. 优化层：质量预测 / 贝叶斯优化 / 闭环
核心数据字段当前包含：时间戳 + 三个距离；强烈建议后续采集补充"脱模结果标签"和"模座/手模编号"。

## V1.6 UI 架构（重要）
- 主窗口 `app/ui/main_window.py` 新增"分析模式"概念，用三个 QPushButton(Checkable) + QButtonGroup 实现：
  - mode 0：折线趋势（V1.5 原有功能保持 0 回归）
  - mode 1：描述统计（V1.6 新）
  - mode 2：时序监控（占位，Phase 2 接入）
- 左侧参数区使用 `QStackedWidget`（`self.mode_stack`）随模式切换：
  - 趋势页：info_group（数据集信息+统计列多选）+ ChartOptionsPanel（时间粒度）+ ChartConfigPanel（X/Y/颜色/均值线/点）
  - 描述统计页：`DescriptivePanel`
  - 时序监控页：占位 QWidget（待替换为 MonitorPanel）
- 右侧图表区使用 `QTabWidget`（`self.chart_tabs`）：折线趋势 / 描述统计 / 时序监控；
  其中"描述统计"Tab 内嵌 `DescriptiveChartsPanel`（再分 5 个子 Tab：直方图+KDE、箱线图、Q-Q 图、相关矩阵、散点矩阵）。
- 下方结果区由单一 `StatsPanel` 升级为 `MultiTablePanel`（`app/ui/widgets/multi_table_panel.py`），支持按表名下拉切换。
- 顶部工具栏不变（导入文件/文件夹、导出统计/图表、打开日志目录、清空、关于）。

## V1.6 新增功能清单（基础层）
- 描述统计配置面板 `app/ui/widgets/descriptive_panel.py`
  - 数值列多选（默认全选数值列、提供全选/清空按钮）
  - 直方图 bins、KDE 开关、均值/中位数参考线开关
  - IQR 系数 k（默认 1.5，范围 0.5-5.0）
  - 相关方法 Pearson / Spearman
  - 散点矩阵开关、Q-Q 图开关
- 描述统计服务 `app/services/descriptive_service.py`
  - 扩展 StatsResult：missing_rate / cv / skewness / kurtosis / q1 / q3 / iqr / p01 / p05 / p95 / p99
  - batch_descriptive_stats / descriptive_to_dataframe：综合统计表
  - quantile_table：P0/P1/P5/P25/P50/P75/P95/P99/P100
  - missing_summary：缺失(空)/非数值无效/总无效/有效数值/占比
  - correlation_matrix：Pearson/Spearman 相关矩阵
  - boxplot_stats：Min/Q1/Median/Q3/Max/IQR 上下界/离群点数
  - distribution_data：直方图分箱 + Silverman KDE（纯 numpy，不依赖 scipy）、IQR 离群点
  - _kde_1d：Silverman 带宽 + 高斯核，向量化；_norm_ppf：Acklam 近似逆正态 CDF（Q-Q 用，避免引 scipy）
- 新增图表组件
  - histogram_chart.py：BarGraphItem 柱状 + KDE 折线（按 N*binwidth 缩放）+ 均值/中位数 InfiniteLine
  - boxplot_chart.py：多列并排箱线（QGraphicsRectItem 画箱体、须线/端线/中位线、均值黄点、离群散点）
  - qq_chart.py：理论分位数 vs 样本分位数散点 + y=x 参考线（Acklam PPF）
  - correlation_chart.py：QGraphicsRectItem 逐格绘制蓝-白-红发散色热力图 + 单元格数值 TextItem
  - scatter_matrix_chart.py：GraphicsLayoutWidget 网格散点，对角线显示列名，每格最多 2000 点自动采样，>6 列自动截断
  - descriptive_charts_panel.py：QTabWidget 容器聚合以上 5 图 + render() 一次生成
- MainWindow 新逻辑
  - `_run_descriptive_analysis(config)`：走 Worker 后台，成功后填充 `_desc_tables`（5 张 DataFrame）+ desc_charts_panel.render + 切换到描述统计图表 Tab 和结果区
  - 数据集切换/清空会清空 `_desc_tables` 与 `desc_charts_panel`，避免串数据
  - _export_stats 按当前模式导出选中的表；_export_chart_image 按 `chart_tabs.currentIndex()` 导出当前图（折线/描述/监控），并回写 last_export_dir
- 结果表集合（描述模式）：综合统计 / 分位数 / 缺失-无效 / 箱线统计 / 相关矩阵
- 单测 `tests/test_descriptive_service.py`：覆盖基础统计、缺失/无效、常量列、空列、分位数、相关矩阵、分布、缺失汇总、箱线离群点

## 功能累计（保留）
- CSV/XLSX 单文件/文件夹递归批量导入；QSettings 记忆导入/导出目录
- 多数据集管理（原始/处理/合并）+ 临时储存区
- 规则式数据处理（lt/lte/gt/gte/eq/neq/is_null/not_null → delete_row / replace_mean）
- 折线趋势：多 Y 折线 + 颜色自定义 + 均值线（总开关+单序列开关）+ 数据点开关
- 时间粒度聚合：原始/分钟/小时/班次(早08-20/晚20-08)/天/周，按窗口均值
- DateAxisItem(utcOffset=0) 自动时间刻度，naive 时间按 UTC 壁钟转 epoch，修复 +8h 错位
- hover tooltip：系列名、时间/类别、数值，最近点二分搜索（14px 阈值），全量原始点
- 自动降采样：单线 >3000 点等距采样到约 3000 点
- QThreadPool 后台 Worker + QProgressDialog（最小展示 300ms），所有重计算不阻塞 UI
- 耗时日志、持久化日志（logs/app_YYYY-MM-DD.log）+ sys.excepthook + 打开日志目录
- 导出：统计结果 CSV/XLSX、当前图表 PNG、数据集 CSV/XLSX

## 关键文件索引
- app/main.py：入口
- app/ui/main_window.py：主窗口（模式切换 + 趋势 + 描述统计 + 导出 + 清空/切换/导入/合并/处理/后台 Worker 调度）
- app/ui/widgets/chart_panel.py：折线趋势图（DateAxisItem、降采样、hover、均值线标签自动避让）
- app/ui/widgets/chart_config_panel.py：Y 序列三元组 (column, color, show_mean) 配置
- app/ui/widgets/chart_options_panel.py：时间粒度下拉
- app/ui/widgets/descriptive_panel.py：描述统计参数面板
- app/ui/widgets/descriptive_charts_panel.py：描述统计图 5-Tab 容器
- app/ui/widgets/{histogram_chart,boxplot_chart,qq_chart,correlation_chart,scatter_matrix_chart}.py
- app/ui/widgets/multi_table_panel.py：多表切换容器（兼容 set_dataframe）
- app/ui/widgets/dataset_panel.py / processing_panel.py / data_table_panel.py / stats_panel.py / pandas_model.py
- app/services/{file_loader,data_processor,data_processing,dataset_manager,time_aggregation,stats_service,export_service,worker,app_logger,descriptive_service}.py
- app/models/{dataset,dataset_item,stats_result,chart_config,processing_rule}.py
- app/utils/{file_utils,type_utils,timer_utils}.py
- tests/test_descriptive_service.py：描述统计服务单测
- sample_data/：demo_sales.csv/xlsx、shop_day1.csv、shop_day2_bad.csv（含 -999 异常值）、time_sample.csv
- docs/{REQUIREMENTS,DEVELOPMENT,ANALYSIS_METHODOLOGY}.md / PROJECT.md / README.md

## 开发约定 / 注意
- 所有重 pandas 计算必须在 Worker 线程里执行；禁止在子线程调用 DatasetManager.add_temporary/set_active/remove/clear，这些必须放在主线程 on_success 回调（防跨线程 Qt 崩溃）。
- 时间语义：naive datetime 一律按 UTC 壁钟处理（pd.to_datetime(utc=True)→datetime64[ns]→int64/1e9），DateAxisItem(utcOffset=0)。
- 方差/标准差使用样本统计口径 ddof=1。
- 表格预览只显示前 1000 行；列数 >20 时不做 resizeColumnsToContents。
- 绘图单线 >3000 点自动等距降采样，hover 仍用全量数据。
- 中文界面文案统一中文；编码统一 UTF-8；不再允许出现 cp936 写入造成的问号/乱码。
- 不要引入 scipy 作为硬依赖：Q-Q 用 Acklam 近似 PPF、KDE 用 numpy 实现；若 Phase 2 确需更高级统计（PELT/EWMA 优化）再评估依赖。
- 切换数据集/清空必须同步清空 _desc_tables 和 desc_charts_panel，避免旧结果残留。

## 运行
```powershell
.\.venv\Scripts\Activate.ps1
python app\main.py
```

## 已知边界 / 待办（V1.7 时序监控）
- 多 Y 均值线当前为全局总开关 + 单序列勾选已在 ChartConfigPanel 支持；时序监控图将沿用单序列独立均值线风格。
- .xls 未完整验证。
- 临时数据集关闭软件不持久化。
- 散点矩阵列数 >6 自动截断；每格最多 2000 点。
- Q-Q 图参考线用 y = μ + σ·x 的截距/斜率形式，是直观参考线，不是严格回归拟合。
- 描述统计中"偏度/峰度"使用 pandas 默认（Fisher 峰度，正态为 0）。

## V1.7 计划（时序监控层）
1. timeseries_service：滑动均值/滑动标准差、线性趋势斜率+R²、按小时/班次/周几聚合、I-MR 控制限、X-bar R 控制限、EWMA（λ 默认 0.2）、Nelson 判异规则（点出 3σ、连续 9 同侧、连续 6 趋势、连续14交替等）、Cp/Cpk（需 USL/LSL）、ACF 自相关系数
2. MonitorPanel（左栏）：时间列、Y 列（单选为主）、窗口 N、EWMA λ、子组大小、USL/LSL、控制图类型切换
3. 新图：spc_chart（I-MR/X-bar R/EWMA 三模式，控制限虚线、超限红标、判异规则点标记+图例）、rolling_chart（原序列+MA+MStd 双轴）、period_compare_chart（班次/小时并排箱线）、acf_chart
4. 接入右侧"时序监控"Tab；结果区新增"判异结果表"（点序号/时间/值/触发规则）
5. 导出适配到时序模式；文档同步到 V1.7

## 变更日志（追加）
- 2026-07-03 V1.6：UI 重构为"分析模式"框架（折线/描述/监控）；描述统计基础层落地（扩展统计量、分位数、缺失、相关矩阵、箱线统计、直方图+KDE、箱线图、Q-Q 图、相关热力图、散点矩阵）；结果区升级为多表切换；导出按当前模式/当前图表/当前表工作；切换/清空正确清理描述统计结果；全部重计算走 Worker；新增 descriptive_service 单测 9 项通过。
