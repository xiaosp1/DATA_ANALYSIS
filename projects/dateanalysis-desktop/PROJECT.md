# PROJECT: 本地数据分析与图表展示软件

> 本文档是项目的唯一事实来源（Single Source of Truth）。所有进度、决策、风险都以这里为准。

## 1. 项目愿景
- 做一款本地运行的桌面数据分析工具，支持表格导入、数据处理、列选择、多Y折线图、时间粒度聚合、统计计算、结果导出，并在界面中完整展示原始、处理、合并数据与分析结果。
- 当前版本：**V1.7.0**（机头/机尾双类别 + 独立单像素精度 + 跨类合同图 outer join）
- 目标平台：Windows 本地桌面

## 2. 当前里程碑
- **V1.7** ✅ 已完成（2026-07-10/11）：跨类别（机头/机尾）同图显示（详见 ADR-002）。
- **V1.6.1** ✅ 已完成：数值缩放为mm + 排除列 + float32 单精度。
- **V1.6** ✅ 已完成：分析模式切换（折线趋势/描述统计/时序监控）+ 描述统计基础层。
- **V1.5** ✅ 已完成：导入文件夹 + 路径记忆。
- **V1.4** ✅ 已完成：耗时日志 + 后台线程 + 进度反馈 + 绘图自动降采样。
- **V1.3** ✅ 已完成：X轴时间刻度（DateAxisItem）+ 数据点悬停 tooltip。
- **V1.2** ✅ 已完成：独立数据处理模块 + 时间粒度聚合 + 多文件导入与合并 + 临时储存区。
- **V1.1** ✅ 已完成：多Y对比 + 颜色选择 + 均值线 + 导出。
- **V1.0** ✅ 已完成：MVP 导入/预览/统计/基础折线图。

## 3. 任务看板
### Doing
- 无

### Done（最新：V1.7.0 跨类合同图）
- [x] **V1.7.0 跨类别（机头/机尾）同图显示**（ADR-002）：
  - 新增两类文件概念：机头 / 机尾；导入时用户手动选择类别 + 输入单像素精度 factor；QSettings 记忆 factor。
  - 数据模型：`DatasetItem` 新增 `category`（`head`/`tail`/`None`）、`pixel_factor`、`scaled` 字段，默认值向后兼容。
  - 数据处理："缩放数值为mm"支持按类别批量缩放（作用范围=当前数据集 / 所有机头 / 所有机尾），两类 factor 独立；已缩放集合 `scaled=True` 防重复乘；float32 单精度语义、排除列、自动跳时间/文本/布尔、`(mm)` 后缀、重名去重全部沿用。
  - 合并：
    - 同类别合并（`机头_合并`/`机尾_合并`）沿用 concat + 时间排序，存入临时储存区；
    - 跨类合并按 `时间` outer join，非时间列加 `[机头]`/`[机尾]` 前缀，已有 `(mm)` 后缀保持在列名末尾；单侧缺失保持 NaN，不做前向/后向填充，不做容差对齐。
  - UI：
    - 工具栏新增"导入机头文件"/"导入机尾文件" + factor 对话框（QInputDialog.getDouble），与原有"导入文件/文件夹"（未分类路径）并存；
    - 数据集列表显示 `[机头]/[机尾]` 类别徽标；
    - 新增"机头合并/机尾合并/跨类合同图"三个操作按钮；
    - 数据处理面板"作用范围"下拉新增"所有机头/所有机尾"；
    - 跨类合同图数据集上，多Y折线、6 种时间粒度（原始/分钟/小时/班次/天/周）聚合、描述统计、导出均直接支持，前缀列名在图例/统计表/列选择面板中正确显示。
- [x] V1.6.1 数值缩放为mm + 排除列 + float32 单精度。
- [x] 分析模式切换：折线趋势 / 描述统计 / 时序监控 三大模式，左侧面板 + 右侧图表 Tab 联动切换。
- [x] 描述统计（基础层）：
  - 综合统计表扩展：有效计数/缺失/最大/最小/均值/中位数/求和/方差/标准差/极差 + 缺失率/变异系数CV/偏度/峰度/Q1/Q3/IQR/P1/P5/P95/P99
  - 分位数表、缺失/无效统计表、箱线统计表、相关系数矩阵表
  - 直方图 + KDE 叠加、均值/中位数参考线、IQR 离群点标记
  - 箱线图（多列并排）、Q-Q 图（Acklam 近似正态分位数，无 scipy 依赖）
  - 相关矩阵热力图（Pearson/Spearman）、散点图矩阵（采样上限）
  - 所有重计算走 QThreadPool 后台 Worker，大样本不卡 UI
- [x] 结果区多表切换；导出适配当前选中表/图表 Tab。

### Todo（V1.8 候选 / 后续迭代）
- [ ] 跨类合并结果实测导出 PNG/CSV/XLSX 端到端回归
- [ ] "导入文件夹"入口补类别+factor 流程（当前文件夹导入走未分类路径）
- [ ] factor 修改后对已缩放/已合并数据集的"重缩放/重合并"提示与一键刷新
- [ ] 扩展数据处理动作：替换中位数、替换0、替换固定值
- [ ] 排序、筛选、重复值删除
- [ ] 每条Y序列单独控制均值线
- [ ] 大文件表格虚拟滚动/分页
- [ ] 更多图表类型
- [ ] `.xls`完整兼容测试

### 历史版本 Done（归档）
- [x] V1.3：X轴时间刻度（DateAxisItem）+ 数据点悬停 tooltip
- [x] V1.4：耗时日志、后台线程、进度反馈、绘图自动降采样、列类型缓存
- [x] V1.0 MVP：导入、预览、统计、基础折线图
- [x] V1.1：多Y对比、颜色选择、均值线、导出
- [x] V1.2：数据处理、时间聚合、多文件、临时储存区

## 4. 关键决策（ADR）
- ADR-001: Python + PySide6 + pandas + PyQtGraph
- ADR-002: V1.7 跨类别（机头/机尾）同图显示：outer join + 前缀 + NaN 独立 + 按类别 factor
- ADR-003: 方差/标准差默认样本统计（ddof=1）
- ADR-005: 原始数据前1000行预览，统计/绘图基于全量有效数据
- ADR-006: Y轴升级为多Y多选+颜色配置
- ADR-008: DatasetManager统一管理多数据集
- ADR-009: 处理/合并结果不覆盖原始数据，统一进入临时储存区
- ADR-010: 时间粒度聚合默认取窗口均值，只影响绘图层
- ADR-011: 引入AppLogger持久化操作日志与异常堆栈，按天滚动保存到 logs/
- ADR-012: X轴时间展示改用 pyqtgraph.DateAxisItem 自动刻度；悬停提示用 sigMouseMoved 最近点搜索 + QToolTip
- ADR-013: 所有pandas重计算移入QThreadPool后台Worker，UI线程只做渲染；长任务用QProgressDialog反馈；图表单线>3000点自动等距降采样
- ADR-014: “缩放数值为mm”乘法统一使用 float32 单精度语义（先转 float32 相乘再回 float64），满足单像素精度要求
- ADR-015: 批量缩放默认自动排除时间/日期列（含文本日期，转换成功率 ≥80% 判定为日期列），用户可手动覆盖
- ADR-016: ProcessingRule 新增 exclude_mode / exclude_columns 可选字段，默认值向后兼容

## 5. 风险与待优化
- 大文件表格性能风险：当前仍为预览前1000行
- 班次标签可读性可优化
- `.xls`未完成全量验证
- 均值线为全局开关，后续可细化为按序列控制
- V1.7 范围外遗留：
  - 跨类合并结果的端到端导出实测
  - "导入文件夹"批量导入机头/机尾（当前走未分类路径）
  - factor 修改后已缩放/已合并数据集的重缩放提示
- 合并策略：同类别=concat+排序；跨类别=outer join；后续可按需加容差/最近邻对齐。

## 6. 项目日记

### 2026-07-10/11 V1.7.0 跨类合同图
- 方案 ADR-002 落地：机头/机尾双类别导入、独立 factor、按类别批量 mm 缩放、跨类 outer join 合并、[机头]/[机尾] 前缀列名、同图多Y对比。
- 数据模型：`DatasetItem` 新增 `category/pixel_factor/scaled` 三字段，默认值保证旧路径 0 回归。
- 服务层：`DatasetManager.merge_by_category` / `merge_cross_category` / `merge_uncategorized`；`data_processing.scale_datasets_by_category` 按类别批量缩放，沿用 float32/排除列/(mm)后缀语义。
- UI：工具栏类别导入按钮 + factor 对话框、QSettings 记忆 factor、数据集类别徽标、三按钮合并（机头/机尾/跨类）、处理面板作用范围扩展、跨类数据集上多Y/时间粒度/描述统计直连。
- 测试：`tests/test_cross_category.py` 覆盖 outer join/前缀/NaN/同类别回归；`tests/test_scale_feature.py` 补按类别批量缩放用例；`tests/ui_smoke_test.py` offscreen 扩展跨类路径（导入机头/机尾 → 两类合并 → 跨类合并 → 6 种粒度 → 描述统计 → 按类别批量缩放 → 清空）。
- 验证：compileall 0 报错；test_scale_feature / test_cross_category / test_descriptive_service 全绿；ui_smoke_test offscreen 单类+跨类路径全过；版本号统一升至 V1.7.0。

### 2026-07-06 V1.6.1 功能补全：排除列 + float32单精度mm缩放
- 功能增强："缩放数值为mm"支持**排除列**。新增排除列模式（自动=时间/日期列 / 手动指定列 / 不排除）。
- 精度语义：缩放乘法使用 float32（单精度）执行，结果回写 float64 兼容 pandas 后续处理。
- 列名处理：缩放后自动追加 `(mm)` 后缀；已有 mm 后缀不重复；重名自动加 `_1/_2`。
- 健壮性：非法因子/因子=1.0/手动排除不存在列/文本格式日期/文本列/布尔列均安全处理。
- 涉及文件：`app/models/processing_rule.py`、`app/services/data_processing.py`、`app/ui/widgets/processing_panel.py`、`tests/test_scale_feature.py`。
- 验证：compileall 全绿，test_scale_feature 14/14 PASS，test_descriptive_service 全过，ui_smoke_test offscreen 全过。

### 2026-07-03 V1.6.1 修复包
- 修复：5 个描述统计图表 clear() 残留占位 TextItem/LabelItem 叠加显示问题。
- 新增：数据处理动作"缩放数值为mm"（单列/全部数值列，自动跳文本/日期/布尔，列名自动加 (mm)）。
- 修复：boxplot_chart.py / qq_chart.py 中 pg.mkPen 传参类型错误；Q-Q 图强依赖 scipy 改用纯 numpy Acklam ppf；_prepare_chart_data 对 y_series 解包/pd.to_numeric/重复列名的健壮性；四个图表空态占位文案乱码；关于对话框版本说明滞后；_progress_cb 空对象异常。
- 同日修复 UI 问号/乱码问题、Y 序列三元组解包兼容、进度回调空保护。
- 验证：py_compile 全绿，test_descriptive_service 全过，QQ 图无 scipy 可跑，ui_smoke_test offscreen 全过。

### 2026-07-02（V1.5）
- 新增工具栏"导入文件夹"按钮；递归识别 csv/xlsx/xls 并批量异步导入，进度条反馈。
- 新增路径记忆：所有导入/导出对话框默认打开上次使用的目录，QSettings 持久化。
- 修复时区偏移 bug：X 轴 DateAxisItem 统一 utcOffset=0，naive 时间按 UTC 壁钟转 epoch。

### 2026-06-30（V1.4）
- 新增耗时日志：导入/统计/聚合/绘图/导出/切换/处理/合并均输出 [耗时]。
- 新增后台 Worker 线程（QThreadPool + QRunnable）+ 模态进度对话框（300ms 后自动显示）。
- 图表自动降采样：单线 >3000 点等距采样到约 3000 点，hover 仍读取全量原始点。
- 时间戳转换向量化，兼容 pandas 3 datetime64[us] 默认精度；列类型缓存。
- 修复表格列宽自适应多列时卡顿。

### 2026-06-30（V1.3）
- X 轴时间刻度改用 DateAxisItem 自动适配。
- 新增数据点鼠标悬停 tooltip（系列名、时间/类别、数值），时间格式随粒度自适应。

### 2026-06-29
- 完成 V1.0 MVP：CSV/XLSX 导入、原始数据预览、统计结果、单折线图。
- 完成 V1.1：多 Y 轴折线、颜色选择、均值线、统计结果导出、图表导出。
- 完成 V1.2：数据处理模块、时间粒度聚合、多文件导入/切换、按时间合并、临时储存区切换/导出/删除。
- 新增持久化日志系统，异常堆栈写入本地 logs 目录；左侧面板滚动优化完成。
- 已更新 README、REQUIREMENTS、DEVELOPMENT、CONTEXT_MEMORY 归档。
- 运行验证：编译通过、核心逻辑通过、窗口启动通过。
