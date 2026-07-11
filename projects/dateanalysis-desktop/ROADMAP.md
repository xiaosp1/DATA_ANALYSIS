# DateAnalysis 项目路线图（ROADMAP）

> 本文档是版本里程碑规划的一页式视图；实现细节与变更日志以 `PROJECT.md`、`CONTEXT_MEMORY.md`、`docs/ANALYSIS_METHODOLOGY.md` 为准。
> 产品领域：丁腈手套卷边长度视觉检测的本地数据分析软件。核心指标：虎口距 / 拇指距 / 中指距（+ 中点 x/y 辅助）。
> 技术栈：Python 3.11+ / PySide6 / pandas / numpy / pyqtgraph / openpyxl，**不引入 scipy** 等硬依赖。

## 版本全景（五层分析方法论）

| 版本 | 分析层 | 核心能力 | 状态 |
|---|---|---|---|
| V1.0–V1.2 | 基础可视化 | CSV/XLSX 导入、多 Y 折线、时间聚合、数据处理、临时储存区 | ✅ 已发布 |
| V1.3–V1.5 | 交互与性能 | DateAxisItem、悬停提示、后台 Worker、降采样、文件夹导入、路径记忆 | ✅ 已发布 |
| V1.6 | 基础层（描述统计） | 综合统计/分位数/缺失/箱线/相关矩阵、直方图+KDE、箱线图、Q-Q、相关热力图、散点矩阵、分析模式切换框架 | ✅ 已发布（V1.6.1 修复包待 tag） |
| **V1.7** | **监控层（时序稳定性/SPC）** | **I-MR / X-bar R / EWMA 控制图、Nelson 判异、Cp/Cpk、ACF 自相关、滑窗 MA/MStd、班次/小时对比、MonitorPanel** | 🚧 **进行中（今晚目标）** |
| V1.8 | 诊断层 | 变点检测（PELT 纯 numpy 简化版）、异常归因、多变量协同、子组划分策略 | 🔮 规划中 |
| V1.9 | 建模层 | 脱模结果关联、逻辑回归、简单 SHAP（纯 numpy 近似）、工艺参数回归 | 🔮 规划中 |
| V2.0 | 优化层 | 质量预测、贝叶斯优化（超参简化）、闭环建议、报告自动生成 | 🔮 远期 |

## V1.7 验收标准（Definition of Done）

### 1. 服务层 `app/services/timeseries_service.py`（纯 numpy/pandas，不引 scipy）
- [x] `imr_chart(series)` → 返回 `(x, cl, ucl_i, lcl_i, mr, ucl_mr, lcl_mr, sigma_est)`
- [x] `xbar_r_chart(series, subgroup_size)` → 子组均值/极差、X̄ 控制限、R 控制限
- [x] `ewma(series, lam, sigma_est=None)` → EWMA 序列、UCL/LCL（随 t 变化收敛到稳态）
- [x] `nelson_rules(series, cl, sigma)` → dict[rule_name -> list[int]]（命中点下标），至少覆盖：
  - R1: 点在 ±3σ 外
  - R2: 连续 9 点在 CL 同侧
  - R3: 连续 6 点递增/递减
  - R4: 连续 14 点交替升降
  - R5: 连续 3 点中 2 点在 ±2σ 外同侧
  - R6: 连续 5 点中 4 点在 ±1σ 外同侧
  - R7: 连续 15 点在 ±1σ 内（分层不足）
  - R8: 连续 8 点在 ±1σ 外两侧
- [x] `process_capability(series, lsl, usl)` → Cp/Cpk/Pp/Ppk（缺 LSL/USL 返回 None 并附消息）
- [x] `acf(series, max_lag)` → 自相关系数序列 + 95% 置信带 ±1.96/√n
- [x] `rolling_stats(series, window)` → MA、MStd（min_periods=max(2, window//4)）
- [x] `by_period(series, time_index, period)` → DataFrame（小时/班次/周几分组箱线统计）
- 所有函数对 NaN/空/常量列鲁棒，不抛异常，返回空结构 + 消息列表。

### 2. UI 面板 `app/ui/widgets/monitor_panel.py`（左侧参数区，遵循 DescriptivePanel 风格）
- 时间列下拉（自动选 datetime 列，无则给提示）
- Y 列（单选，默认第一个数值列；后续可扩多选）
- 控制图类型：I-MR / X-bar R / EWMA
- 子组大小（仅 X-bar R 启用，默认 5，范围 2-50）
- EWMA λ（默认 0.2，范围 0.05-0.95）
- 滑窗 N（默认 30，范围 5-500，供滚动统计与 ACF 最大滞后用）
- USL / LSL（可选浮点，空表示不做 Cpk）
- Nelson 规则 8 条复选（默认全开 R1-R4）
- 附加图开关：滑窗 MA±σ、ACF、时段对比（班次/小时/周几三选一）
- 按钮："开始时序监控分析"；发 `run_requested(dict)` 信号。

### 3. 图表组件 `app/ui/widgets/spc_chart.py` + `rolling_chart.py` + `acf_chart.py` + `period_compare_chart.py`
- SPC 图：原序列 + CL/UCL/LCL 虚线，超控制限点红圈，Nelson 命中点用不同 marker/色，图例区分规则
- EWMA 与控制限同时绘制
- X-bar R 双面板（上：子组均值+X̄控制限，下：子组极差+R控制限）
- 滚动图：原序列灰线 + MA 粗线 + ±1σ/±2σ 填色带
- ACF 图：柱状 + 95% 置信带虚线 + lag 轴
- 时段对比：箱线（班次/小时/周几），复用 boxplot 风格色板
- 容器 `MonitorChartsPanel`（QTabWidget）：SPC / 滚动统计 / ACF / 时段对比 四 Tab，空态显示"请配置并开始分析"，无乱码

### 4. MainWindow 集成（`app/ui/main_window.py`）
- 把占位 `monitor_page` 换成 `MonitorPanel` 实例 `self.monitor_panel`
- 新增 `self.monitor_charts_panel` 挂到 `chart_tabs` 第三个 Tab（"时序监控"）
- 数据集切换/清空时同步清空 monitor 结果与图表
- 新增 `_run_monitor_analysis(config)`：Worker 后台跑 timeseries_service 全套计算 → 主线程渲染图表 + 填结果表（"判异结果"表：点序号/时间/值/规则；"过程能力"表：Cp/Cpk/Pp/Ppk/均值/σ/USL/LSL）
- `_current_chart_export_target` 的 mode 2 返回当前可见 monitor 子图，支持导出 PNG
- `_export_stats` 在监控模式下导出"判异结果"或"过程能力"表
- 不要破坏 V1.5/V1.6 任何已有功能（折线/描述统计/处理/合并/导出）。

### 5. 测试
- `tests/test_timeseries_service.py`：覆盖 I-MR/X-bar R/EWMA/Nelson/Cpk/ACF/rolling/by_period 各函数；包含常量列、空列、NaN、已知分布（np.random.seed(42)）的断言
- `tests/ui_smoke_test.py` 扩展：导入真实 13k 行 CSV 后跑一次时序监控（I-MR + EWMA + Cpk 设 USL/LSL），断言日志无 ERROR、结果表非空、SPC 图能 grab 到 PNG
- 所有已有测试 0 回归。

### 6. 文档
- PROJECT.md 追加 V1.7 章节（能力+ADR+耗时）
- CONTEXT_MEMORY.md 更新到 V1.7 状态、关键文件索引
- README.md 追加 V1.7 功能说明与截图占位
- 清理所有临时 _*.py / _*.md 文件；代码 UTF-8 无 BOM、无 `????` 乱码。

## V1.7 非目标（明确不做）
- 不做实时数据接入/串口/网络流；仍是离线 CSV/XLSX 批量分析
- 不引入数据库；临时数据集继续内存
- 不做用户系统/云同步
- 不做多变量控制图（Hotelling T² 等留给 V1.8）
- 不装 scipy/statsmodels；所有算法纯 numpy 实现

## 进度追踪
- 2026-07-03 晚：V1.6.1 修复包（乱码/mkPen/scipy 可选/progress 空保护/prepare 健壮性）已验证通过
- 2026-07-03 深夜—07-04 晨：V1.7 实现+测试（Codex 子会话执行，龙虾1号 PM 调度）
