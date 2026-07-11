# DateAnalysis · 本地数据分析与图表展示软件

> **项目主文档（Project Overview）** — 本文档是项目对外/对内的一页式总览。详细技术细节、变更日志、需求条目、开发规范见 `docs/` 与本文末尾「文档索引」。
>
> 最新版本：**V1.6.1（基础层-描述统计，修复包）** ｜ 下一版本：**V1.7（监控层-SPC时序稳定性）**
> 更新时间：2026-07-04

---

## 一、项目是什么

一款**纯本地运行**的桌面数据分析工具，面向丁腈手套产线视觉检测场景（虎口距 / 拇指距 / 中指距 / 中点x/y），也可通用到其它结构化 CSV/XLSX 时序数据。

核心价值：
- 📁 **不联网、不上传** — 产线数据不出车间；
- 📊 **开箱即用** — 拖入CSV/XLSX就能出图、出统计、出报表；
- 🧪 **覆盖五层分析** — 从基础可视化到 SPC 控制图/过程能力/异常判异，循序渐进；
- 🛠 **工程友好** — Python + PySide6 桌面端，pandas/numpy/pyqtgraph 轻量栈，无重依赖。

---

## 二、功能矩阵（按版本）

| 模块 | V1.0–V1.2 基础可视化 | V1.3–V1.5 交互与性能 | V1.6 基础层-描述统计 | V1.7 监控层-SPC（开发中） |
|------|---|---|---|---|
| **数据导入** | CSV/XLSX 导入、预览前1000行 | + 文件夹批量递归导入、路径记忆 | 同左 | 同左 |
| **多文件管理** | 切换、按时间拼接合并、临时储存区（原始/处理/合并） | 同左 | 同左 | 同左 |
| **数据处理** | 条件删行 / 替换均值 | 同左 | + 统计面板可在处理后数据集上跑 | + 扩展替换中位数/0/固定值、去重 |
| **折线图** | 单X多Y、颜色、均值线、数据点 | + DateAxisItem时间刻度、悬停tooltip、>3000点自动降采样 | + 分析模式切换（折线趋势/描述统计/时序监控） | 同左 |
| **时间聚合** | 原始/分钟/小时/班次/天/周 均值聚合 | + 时区语义修复（naive=UTC壁钟） | 同左 | 同左 |
| **描述统计** | 基础 max/min/mean/median/sum/var/std/range/缺失 | 同左 | + CV/偏度/峰度/Q1/Q3/IQR/P1/P5/P95/P99/缺失率；直方图+KDE、箱线图、Q-Q图、相关矩阵热力图、散点矩阵 | 同左 |
| **时序监控（SPC）** | — | — | 框架预留 | 🚧 I-MR / X̄-R / EWMA 控制图、Nelson 8条判异规则、Cp/Cpk/Pp/Ppk、ACF自相关、滑窗MA±σ、时段(班次/小时/周几)对比 |
| **导出** | 统计CSV/XLSX、图表PNG、数据集CSV/XLSX | + 按当前表/当前图导出 | 同左 | + SPC判异结果/过程能力表导出 |
| **性能** | 同步执行，大文件会卡顿 | + QThreadPool后台Worker、进度对话框、耗时日志 | 同左 | 同左 |
| **日志** | — | + 持久化日志（logs/按天滚动）+ 错误堆栈 | 同左 | 同左 |

---

## 三、技术栈

```
语言：        Python 3.12（兼容 3.11+）
GUI 框架：     PySide6（Qt for Python）
表格/计算：    pandas, numpy
图表：        pyqtgraph（高性能科学绘图）
Excel读写：    openpyxl
打包：        —（暂未打包，本地 Python 环境运行；后续可走 PyInstaller）
```

**约束**：**不引入 scipy / statsmodels / sklearn**，所有统计/控制图算法纯 numpy/pandas 实现，保持桌面端轻量、零C扩展依赖（便于后续打包分发到无Python环境的产线电脑）。

---

## 四、快速开始

### 环境要求
- Windows 10 / 11
- Python 3.11+（推荐 VS Code 内置 Python 3.12）

### 启动
```powershell
# 1. 进入项目目录
cd E:\DEMO\DateAnalysis\n\n# 2. 创建并激活虚拟环境（首次）\npython -m venv .venv\n.\.venv\Scripts\Activate.ps1\n\n# 3. 安装依赖\npip install -r requirements.txt\n\n# 4. 运行\npython app\main.py
```

### 典型使用流程
1. **导入**：工具栏「导入文件」或「导入文件夹」加载 CSV/XLSX；
2. **切换数据集**：左侧临时储存区选择「原始 / 处理结果 / 合并结果」；
3. **选分析模式**：折线趋势 / 描述统计 / 时序监控；
4. **配置列**：选时间列、Y列，设置时间粒度/SPC参数；
5. **开始分析**：后台Worker跑完自动出图出表；
6. **数据处理（可选）**：在「数据处理模块」添加条件规则（删行/替换均值）生成处理后数据集；
7. **导出**：按需要导出统计表、当前图表、或整个数据集。

---

## 五、项目架构

```
DateAnalysis/
├─ app/
│  ├─ main.py                     # 应用入口
│  ├─ models/
│  │  └─ dataset_manager.py       # DatasetManager：多数据集统一管理
│  ├─ services/                   # 业务逻辑层（无UI依赖，可单测）
│  │  ├─ data_service.py          # 导入/预览/处理/合并/导出
│  │  ├─ chart_service.py         # 折线图数据准备/时间聚合
│  │  ├─ descriptive_service.py   # V1.6 描述统计（纯numpy）
│  │  └─ timeseries_service.py    # V1.7 SPC算法（I-MR/EWMA/Nelson/Cpk/ACF）
│  ├─ ui/
│  │  ├─ main_window.py           # 主窗口，集成三大模式
│  │  └─ widgets/
│  │     ├─ chart_config_panel.py # 折线趋势配置面板
│  │     ├─ chart_panel.py        # 折线图面板
│  │     ├─ descriptive_panel.py  # 描述统计配置
│  │     ├─ descriptive_charts_panel.py  # 描述统计多图容器
│  │     ├─ monitor_panel.py      # V1.7 SPC配置面板
│  │     ├─ spc_chart.py / rolling_chart.py / acf_chart.py / period_compare_chart.py
│  │     └─ multi_table_panel.py  # 多表切换（综合/分位数/缺失/箱线/相关/判异）
│  └─ utils/
│     └─ logger.py                # AppLogger 持久化日志
├─ docs/                          # 详细文档（见索引）
├─ logs/                          # 运行日志（按天滚动）
├─ sample_data/                   # 示例数据
├─ tests/                         # pytest 单测 + UI冒烟
├─ requirements.txt
├─ README.md                      # 面向新用户的使用说明
├─ PROJECT.md                     # 项目事实来源（SSOT）
├─ ROADMAP.md                     # 版本路线图
├─ CONTEXT_MEMORY.md              # AI/PM上下文记忆
└─ 学习日志.md                     # 开发过程记录
```

**分层原则**：
- **UI 层 (`ui/`)** 只管展示与信号转发；
- **服务层 (`services/`)** 是纯计算逻辑，不依赖 Qt，可独立单测；
- **模型层 (`models/`)** 管数据生命周期；
- **所有重计算走 QThreadPool Worker**，不卡UI线程，>300ms自动弹进度框。

---

## 六、当前版本状态（V1.6.1）

### ✅ 已发布能力
- CSV/XLSX(X) 导入、批量文件夹导入、路径记忆；
- 多文件按时间合并、临时储存区三类数据集分离；
- 条件数据处理（删行/替换均值）；
- 多Y轴折线、每条Y独立颜色/均值线开关、时间粒度聚合（原始/分钟/小时/班次/天/周）；
- 描述统计：综合统计/分位数/缺失/箱线统计/相关矩阵五张表 + 直方图+KDE/箱线图/Q-Q图/相关热力图/散点矩阵五张图；
- 后台线程 + 进度反馈 + 图表自动降采样 + 数据点悬停tooltip；
- 持久化日志（logs/ 按天滚动，错误带traceback）；
- 统计结果/图表/数据集导出；
- V1.6.1 修复包：解决中文乱码、pg.mkPen类型错误、Q-Q图强依赖scipy、进度对话框空对象异常、图表clear()残留占位等。

### 🐛 已知风险/待办
- 大文件表格预览仍限前1000行（全量计算不受影响）；
- 数据处理动作暂缺「替换中位数/替换0/替换固定值/排序/去重」；
- `.xls` 老格式未做全量兼容验证；
- 均值线目前是全局开关，后续细化到每Y序列；
- 未打包为exe，需本地Python环境运行。

---

## 七、路线图（五层方法论）

| 版本 | 分析层 | 能力 | 状态 |
|---|---|---|---|
| V1.0–V1.2 | 基础可视化 | 导入/多Y/时间聚合/处理/临时储存区 | ✅ 已发布 |
| V1.3–V1.5 | 交互与性能 | DateAxis/悬停/后台Worker/降采样/批量导入/日志 | ✅ 已发布 |
| V1.6 (.1) | 基础层-描述统计 | 综合统计/分位数/直方图/箱线/Q-Q/相关矩阵/散点矩阵 | ✅ 已发布 |
| **V1.7** | **监控层-SPC** | I-MR / X̄-R / EWMA / Nelson 8规则 / Cp/Cpk / ACF / 滑窗 / 时段对比 | 🚧 **开发中** |
| V1.8 | 诊断层 | 变点检测(PELT)、异常归因、多变量协同、子组策略 | 🔮 规划中 |
| V1.9 | 建模层 | 脱模结果关联、逻辑回归、近似SHAP、工艺参数回归 | 🔮 规划中 |
| V2.0 | 优化层 | 质量预测、贝叶斯优化、闭环参数建议、报告自动生成 | 🔮 远期 |

**V1.7 DoD（验收标准）摘要**：
- 服务层 `timeseries_service.py` 覆盖 I-MR/X̄-R/EWMA/Nelson/Cpk/ACF/rolling/by_period，纯numpy，NaN鲁棒；
- UI层 `MonitorPanel` + `MonitorChartsPanel`（四Tab：SPC/滚动/ACF/时段对比）；
- MainWindow 集成模式切换、后台Worker、导出适配，V1.5/V1.6零回归；
- 测试：`test_timeseries_service.py` 算法覆盖 + `ui_smoke_test.py` 真实13k行CSV冒烟；
- 文档更新：PROJECT/CONTEXT_MEMORY/README；清理临时脚本、无BOM无乱码。

---

## 八、关键决策记录（ADR 节选）

| ID | 决策 | 理由 |
|---|---|---|
| ADR-001 | Python + PySide6 + pandas + pyqtgraph | 桌面端+科学绘图+数据处理生态成熟 |
| ADR-003 | 方差/标准差用 ddof=1（样本统计） | 工程上样本估计更合理 |
| ADR-005 | 表格预览前1000行，统计/绘图基于全量 | 不牺牲正确性下保证UI流畅 |
| ADR-008 | DatasetManager 统一管理原始/处理/合并三类数据集 | 状态集中，UI不直接持有DataFrame |
| ADR-009 | 处理/合并结果不覆盖原始数据，进入临时储存区 | 可追溯、可回退 |
| ADR-010 | 时间粒度聚合只影响绘图层，不改原始数据 | 避免多级聚合误差累积 |
| ADR-011 | AppLogger 持久化按天滚动到 logs/ | 产线问题回溯 |
| ADR-012 | X轴用 pyqtgraph.DateAxisItem + 悬停tooltip | 解决时间标签稀疏、可读性差 |
| ADR-013 | 重计算进 QThreadPool Worker，>3000点自动降采样 | 大文件不卡UI |
| （V1.7新增） | 不引入 scipy/statsmodels，SPC算法纯numpy实现 | 便于打包分发、降低安装门槛 |
| （V1.7新增） | naive datetime 按UTC壁钟转epoch，DateAxisItem(utcOffset=0) | 消除+8小时时区错位 |

---

## 九、项目对脱模数据分析的价值（业务对接）

本软件与当前在做的「**脱模优化数据分析**」（`E:\项目\脱模优化\`）直接对口：\n\n| 脱模分析需求 | DateAnalysis 对应能力 |
|---|---|
| 25个CSV数据盘点、描述统计 | V1.6 描述统计模式可直接打开CSV一键出综合统计+直方图+箱线+相关矩阵 |
| 跨批次稳定性对比 | V1.6 多文件导入+多Y对比；V1.7 SPC可上线后直接做控制图/Cpk |
| 异常轨迹/异常批次识别 | V1.7 Nelson判异规则+EWMA，可定位超控制限/趋势/分层异常点 |
| 周期切分/特征工程 | 目前在 Jupyter/独立脚本完成，后续可扩展为"周期切分"数据处理动作（V1.8候选） |
| 给工艺/质量部出具报告 | 导出图表PNG+统计CSV/XLSX；V2.0规划自动报告生成 |

简单说：**夜间跑的独立 Python 分析脚本，核心能力会逐步"收编"到这个桌面软件里**，最终形成一个产线工艺工程师自己就能用的SPC工具。

---

## 十、文档索引

| 文档 | 作用 | 位置 |
|---|---|---|
| **项目主文档（本文）** | 一页式总览，给人/自己看全貌 | `PROJECT_OVERVIEW.md` |
| README | 新用户快速上手 | `README.md` |
| REQUIREMENTS | 需求条目（功能点详细定义） | `docs/REQUIREMENTS.md` |
| DEVELOPMENT | 开发规范/环境/调试/常见问题 | `docs/DEVELOPMENT.md` |
| ANALYSIS_METHODOLOGY | 五层分析方法论与算法说明 | `docs/ANALYSIS_METHODOLOGY.md` |
| PROJECT.md | 项目SSOT（进度/ADR/变更日志） | `PROJECT.md` |
| ROADMAP.md | 版本路线图与DoD | `ROADMAP.md` |
| CONTEXT_MEMORY.md | AI协作上下文记忆（文件索引/约定） | `CONTEXT_MEMORY.md` |
| 学习日志.md | 开发过程踩坑与心得 | `学习日志.md` |

---

## 十一、下一步（你可以怎么推进）

如果要继续往下干，当前有三条可走的路，告诉我选哪条：

1. **🚀 直接冲 V1.7**：按 ROADMAP 把 SPC 监控层（I-MR/EWMA/Nelson/Cpk/ACF）落地，可直接用在脱模数据上做异常判异；
2. **🧹 V1.6.2 打磨**：先把已知待办补上（替换中位数/去重/排序、xls兼容、均值线单Y控制），再冲V1.7；
3. **📦 打包发布**：用 PyInstaller 打成 exe，给产线同事直接用（需要补图标/版本号/安装说明）。

按你昨晚"干活"的节奏，我建议**先推 V1.7 的服务层+单测**，今晚就能把 SPC 算法跑起来，明天再挂 UI。等你一句话。
