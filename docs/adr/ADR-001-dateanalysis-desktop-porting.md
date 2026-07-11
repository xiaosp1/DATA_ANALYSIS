# ADR-001 — 接收 DateAnalysis 桌面软件作为 PM 首个托管项目

- 日期：2026-07-10
- 状态：Accepted
- 决策者：尘醒（Owner）/ dataanalysis-pm

## 背景
Owner 在 PM 工作空间建立前，已通过 Codex CLI 在 `E:\DEMO\DateAnalysis` 路径下迭代出一个本地桌面数据分析工具（V1.6.1）。现要求：
1. 将该软件迁移到 PM 工作空间；
2. PM 吸收旧 Codex 项目文档/记忆，形成 PM 自己的进度与状态视图。

## 决策
1. **物理迁移**：在 `E:\DEMO\DataAnalysis\projects\dateanalysis-desktop/` 下接收源码、文档、测试、样例数据（排除运行态 `.venv/`、`.git/`、`logs/`、`__pycache__/`、`*.pyc`、`_screenshots/`、`ui_smoke_out/`）。
2. **旧目录处置**：旧路径 `E:\DEMO\DateAnalysis` **不删除、不改写**，作为回退副本保留；新开发、新派工一律在 `projects/dateanalysis-desktop/` 下进行。
3. **事实来源切换**：旧目录下的 `STATUS.md`/`PROJECT.md`/`CONTEXT_MEMORY.md` 等 Codex 自维护文件仅作历史参考；PM 事实来源切换为：
   - 工作空间根 `STATUS.md`（PM 看板）
   - 工作空间根 `COMMITMENTS.md`（承诺账本）
   - `docs/adr/*.md`（决策记录，含本文件）
   - `memory/YYYY-MM-DD.md`（工作日志）
   - `projects/dateanalysis-desktop/PROJECT.md`（软件自身 SSOT，**不再由 PM 直接改写**，需修改时派 documenter/coder Worker）
4. **环境基线**：Python 3.11+ / PySide6 / pandas / numpy / openpyxl / pyqtgraph；以 `requirements.txt` 为准；运行前在新目录下重建 venv。

## 基线版本（V1.6.1，2026-07-06）功能范围
- 导入：CSV/XLSX/XLS（xls 未完整验证）、单文件/文件夹批量导入、路径记忆
- 多文件管理：临时储存区（原始/处理/合并）、按时间列合并+排序
- 数据预览：默认前 1000 行，统计/绘图走全量
- 统计：max/min/mean/median/sum/var/std/range/missing；扩展 CV/偏度/峰度/分位数(P1/P5/Q1/Q3/P95/P99)/IQR/相关矩阵
- 数据处理：按列条件（比大小/空值）删除整行/替换均值；"缩放数值为mm"（单列/全部数值列，支持排除列 auto/manual/none，float32 单精度语义，自动加 (mm) 后缀、重名去重）
- 可视化（pyqtgraph）：
  - 折线趋势：多 Y 轴、自定义颜色、均值线、数据点 tooltip、时间刻度 DateAxisItem
  - 时间粒度聚合：原始/分钟/小时/班次(早08-20/晚20-08)/天/周（均值聚合，仅绘图层）
  - 描述统计：直方图+KDE、多列箱线图+离群点、Q-Q 图（Acklam 近似，无 scipy 依赖）、相关矩阵热力图、散点矩阵
- 分析模式切换：折线趋势 / 描述统计 / 时序监控（时序监控为占位，Phase 2）
- 性能：QThreadPool 后台 Worker + QProgressDialog；单线 >3000 点自动等距降采样；列类型缓存
- 日志：AppLogger 持久化（logs/ 按天滚动，带 traceback），工具栏"打开日志目录"
- 导出：统计结果（CSV/XLSX，按当前结果表）、图表（PNG，按当前 Tab）、数据集（CSV/XLSX）

## 验证基线（迁移时）
- `python -m compileall app tests` → 0 报错（在新目录下验证通过）
- 旧 Codex 时代最后测试记录（源 `STATUS.md`）：`test_scale_feature.py` 14/14 PASS、`test_descriptive_service.py` all passed、`ui_smoke_test.py` offscreen 全过（导入→描述统计→折线→各时间粒度→处理→清空，无崩溃）
- 迁移后尚未重跑单元/冒烟测试（待在新目录重建 venv 后执行，登记首个验证任务）

## 已知风险 / 技术债（随迁移一并继承）
- 大文件表格仍只预览前 1000 行，无虚拟滚动/分页
- `.xls` 未做全量兼容验证
- 均值线为全局开关，未做到按序列单独控制
- 合并策略仅拼接+排序，无去重/时间对齐高级策略
- 旧 `PROJECT.md` 底部存在重复段落（2026-06-29 之后追加的内容和上方段落重复），文档清理待排期
- 时序监控模式（SPC/EWMA/Cpk/ACF）仅为占位 Tab，未实现

## Todo（V1.7 / 下一迭代候选，按优先级）
1. P0：在新目录下重建 venv → 跑通 `test_scale_feature` / `test_descriptive_service` / `ui_smoke_test` 作为新基线（首个派工）
2. P1：扩展数据处理动作（替换中位数 / 替换 0 / 替换固定值、排序、筛选、去重）
3. P2：均值线按序列单独控制、大文件虚拟滚动、`.xls` 兼容验证
4. P3：更多图表类型、时序监控 Phase 2

## 后果
- PM 工作空间内正式拥有一个可运行的桌面软件子项目，与 PM 自身的骨架/脚本/记忆目录隔离。
- 旧 Codex 项目的上下文（功能边界/版本/ADR/已知风险/测试基线）被 PM 一次性吸收，后续迭代全部通过 PM 派工进行。
