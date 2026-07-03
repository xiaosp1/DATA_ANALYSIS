# 本地数据分析与图表展示软件 - 开发文档

## 1. 技术选型建议

### 1.1 推荐技术栈
- 语言：Python 3.11+
- 桌面 UI：PySide6
- 表格数据处理：pandas
- Excel 读取依赖：openpyxl、xlrd（仅做旧版 xls 兼容，可选）
- 图表库：PyQtGraph（首推，性能好，适合桌面交互）
- 备选图表库：Matplotlib（若更重视静态展示与兼容性）
- 项目管理：requirements.txt + README.md
- 打包（后续）：PyInstaller

### 1.2 推荐理由
- Python + pandas 对表格读取、统计计算非常成熟
- PySide6 是成熟的桌面 GUI 方案，组件完整
- PyQtGraph 对大数据量折线图渲染性能优于纯 Matplotlib 嵌入
- 本地桌面软件天然满足“本地获取表格、数据不外传”的要求

### 1.3 技术约束
- 不依赖后端服务，全部逻辑本地运行
- 首版优先 Windows 可运行
- 不引入过重框架，保持项目结构简单

## 1.4 开发 IDE 与环境依赖

### 开发 IDE
- 推荐 IDE：VS Code
- 结论：可以使用 VS Code 完成本项目全部开发工作，包括代码编辑、终端执行、依赖安装、断点调试、界面运行与问题排查。
- 原因：本项目是本地 Python 桌面应用，核心依赖是 Python 解释器与第三方库，VS Code 可完整承载开发流程。

### 操作系统
- 首版目标运行环境：Windows 10 / Windows 11
- 开发环境建议优先使用 Windows，因为当前项目目录与使用场景均为本地 Windows 桌面。

### Python 版本
- 必需：Python 3.11 或更高版本（建议 3.11.x）
- 注意：
  - 安装时勾选“Add Python to PATH”
  - 建议使用官方 Python 或 conda/miniconda 环境
  - 首版不要混用系统 Python 和多个虚拟环境，避免依赖混乱

### 必须环境依赖
以下依赖为 V1.0 MVP 必需项：
- `PySide6>=6.6`：桌面界面框架
- `pandas>=2.2`：表格读取、数据处理、统计计算
- `numpy>=1.26`：pandas 基础数值计算依赖
- `openpyxl>=3.1`：读取 `.xlsx` Excel 文件
- `pyqtgraph>=0.13`：折线图绘制与交互

可选依赖：
- `xlrd>=2.0.1`：仅当需要兼容旧版 `.xls` 文件时安装
- `chardet>=5.2`：当 CSV 编码识别不稳定时可用于辅助探测

### 推荐 VS Code 插件
为提升开发效率，建议安装以下插件：
- Python（Microsoft 官方插件）
- Pylance（代码补全与类型检查）
- Python Debugger（调试支持）
- Code Spell Checker（可选，检查英文拼写）
- Excel Viewer（可选，快速查看样例数据文件）
- GitLens（可选，若后续使用 Git 管理版本）

### VS Code 开发建议
- 使用 VS Code 内置终端创建并激活虚拟环境
- 选择项目对应的 Python 解释器（虚拟环境中的 Python）
- 优先通过 `python app/main.py` 启动桌面程序
- 调试 GUI 程序时，可在 VS Code 中配置 `launch.json` 直接启动 `app/main.py`
- 若运行 PySide6 程序时界面无响应，优先检查是否把耗时文件读取或统计计算放在了主线程

### 最小环境验证
环境准备完成后，至少应满足以下验证：
- `python --version` 能正确输出 Python 3.11+
- `pip --version` 可正常使用
- 安装依赖后，可在 Python 中成功导入 `PySide6`、`pandas`、`numpy`、`openpyxl`、`pyqtgraph`
- 能启动一个最小 PySide6 窗口而不报错

### 推荐虚拟环境命令（Windows PowerShell）
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 2. 系统架构设计

建议采用分层结构，避免 UI、数据处理、图表逻辑混在一起：

1. UI 层（Presentation Layer）
   - 主窗口
   - 文件导入区
   - 列选择/配置面板
   - 表格视图
   - 图表视图
   - 统计结果视图
   - 日志/消息提示区

2. 应用服务层（Service Layer）
   - 文件加载服务
   - 数据校验服务
   - 统计分析服务
   - 图表配置服务
   - 导出服务（后续）

3. 数据模型层（Model Layer）
   - DataSet（数据集模型）
   - ColumnMeta（列元信息：列名、类型、是否数值列、是否日期列）
   - StatsResult（统计结果模型）
   - ChartConfig（图表配置模型）

4. 工具层（Utils Layer）
   - 文件类型判断
   - 编码探测（CSV 可选）
   - 数值转换
   - 日期解析
   - 错误消息格式化

---

## 3. 目录结构建议

```text
DateAnalysis/
├─ app/
│  ├─ main.py                  # 程序入口
│  ├─ ui/
│  │  ├─ main_window.py        # 主窗口
│  │  ├─ widgets/
│  │  │  ├─ file_panel.py
│  │  │  ├─ column_panel.py
│  │  │  ├─ chart_panel.py
│  │  │  ├─ data_table_panel.py
│  │  │  └─ stats_panel.py
│  ├─ services/
│  │  ├─ file_loader.py
│  │  ├─ data_processor.py
│  │  ├─ stats_service.py
│  │  └─ chart_service.py
│  ├─ models/
│  │  ├─ dataset.py
│  │  ├─ column_meta.py
│  │  ├─ stats_result.py
│  │  └─ chart_config.py
│  └─ utils/
│     ├─ file_utils.py
│     ├─ type_utils.py
│     └─ date_utils.py
├─ tests/
│  ├─ test_stats_service.py
│  ├─ test_file_loader.py
│  └─ test_data_processor.py
├─ sample_data/
│  └─ demo.csv
├─ docs/
│  ├─ REQUIREMENTS.md
│  └─ DEVELOPMENT.md
├─ requirements.txt
└─ README.md
```

---

## 4. 核心数据模型设计

### 4.1 DataSet
用于封装当前加载的数据集。

建议字段：
- `file_name: str`
- `file_path: str`
- `df: pd.DataFrame`
- `columns: list[str]`
- `row_count: int`
- `column_count: int`
- `column_metas: dict[str, ColumnMeta]`

关键方法：
- `get_numeric_columns() -> list[str]`
- `get_datetime_columns() -> list[str]`
- `get_column_series(column_name: str) -> pd.Series`
- `clear()`

### 4.2 ColumnMeta
描述每一列的基础信息。
- `name: str`
- `dtype: str`
- `is_numeric: bool`
- `is_datetime: bool`
- `missing_count: int`
- `sample_values: list`

### 4.3 StatsResult
保存单列或多列统计结果。
- `column_name: str`
- `count: int`
- `missing_count: int`
- `max: float | None`
- `min: float | None`
- `mean: float | None`
- `median: float | None`
- `sum: float | None`
- `variance: float | None`
- `std_dev: float | None`
- `range: float | None`

说明：
- 方差默认使用样本方差（`ddof=1`）
- 标准差默认使用样本标准差（`ddof=1`）

### 4.4 ChartConfig
- `x_column: str`
- `y_column: str`
- `title: str`
- `sort_x_by_datetime: bool`
- `show_points: bool`

---

## 5. 模块设计说明

### 5.1 文件加载模块（file_loader.py）
职责：
- 根据文件扩展名读取 CSV/Excel
- 返回 DataFrame
- 捕获常见异常并转为可读错误信息

处理规则：
- `.csv`：优先 utf-8，失败时尝试 gbk / utf-8-sig
- `.xlsx`：使用 pandas + openpyxl
- `.xls`：可选支持
- 如果用户勾选“首行不是表头”，则设置 `header=None` 并自动生成列名

输出：
- DataSet 对象
- 错误信息（若失败）

### 5.2 数据预处理模块（data_processor.py）
职责：
- 识别列类型
- 对统计列进行数值转换
- 处理空值统计
- 必要时排序 X 轴

建议方法：
- `infer_column_meta(df) -> dict[str, ColumnMeta]`
- `to_numeric_series(series) -> pd.Series`
- `prepare_chart_data(df, x_col, y_col) -> pd.DataFrame`

注意点：
- 统计前必须把 Y 轴列转成数值，无法转换的值置为 NaN
- X 轴若识别为日期，应转为 datetime 并排序
- 若 X 轴不是日期，保持原始顺序

### 5.3 统计计算模块（stats_service.py）
职责：
- 对一个或多个数值列计算统计量

输入：
- DataFrame
- 待统计列名列表

输出：
- `list[StatsResult]`

统计公式说明：
- 最大值：`max()`
- 最小值：`min()`
- 平均值：`mean()`
- 中位数：`median()`
- 方差：`var(ddof=1)`
- 标准差：`std(ddof=1)`
- 极差：`max - min`
- 缺失值：`isna().sum()`

测试要求：
- 正常数值列结果正确
- 含空值时忽略空值
- 全空列返回空结果而非崩溃
- 混合文本数值列可提取数值或报提示

### 5.4 图表模块（chart_service.py / chart_panel.py）
职责：
- 根据 ChartConfig 绘制折线图
- 刷新图表区域
- 处理 X/Y 轴数据转换

实现建议（PyQtGraph）：
- 使用 `PlotWidget`
- X 轴若为日期/时间，需先转换为时间戳再绘制，并用自定义 AxisItem 显示日期文本
- X 轴若为类别文本，可先用索引绘图，再将刻度替换为文本标签

图表交互：
- 支持缩放、平移
- 显示坐标值
- 切换新图时先清空旧图

### 5.5 表格展示模块
职责：
- 展示原始 DataFrame
- 展示统计结果 DataFrame

实现建议：
- 使用 `QTableView` + 自定义 Model，性能更好
- MVP 也可先使用 `QTableWidget`，开发更快，但大文件性能较差
- 若采用 pandas，可先实现“前 1000 行预览”，后续再做虚拟滚动

---

## 6. 主窗口交互逻辑

### 6.1 导入文件流程
1. 用户点击“导入文件”
2. 弹出文件选择框
3. 校验扩展名
4. 调用 `file_loader.load_file()`
5. 成功后：
   - 更新 DataSet
   - 刷新列选择控件
   - 刷新原始数据表
   - 清空旧图表和旧统计结果
   - 在状态栏提示“导入成功”
6. 失败：
   - 弹出错误提示
   - 写入消息日志

### 6.2 分析流程
1. 用户选择分析列（一个或多个，统计区支持多列）
2. 用户选择 X 轴列
3. 用户选择 Y 轴列（图表至少选一个）
4. 点击“开始分析”
5. 执行：
   - 校验 X/Y 列是否存在
   - 校验 Y 轴列是否可转为数值
   - 计算统计结果
   - 生成图表数据
   - 渲染图表
   - 刷新统计结果表格
6. 若存在异常值/空值/类型问题，在消息区提示

---

## 7. UI 详细建议

### 7.1 顶部工具栏
- 导入文件
- 导出结果（P1）
- 清空
- 关于

### 7.2 左侧配置区
建议包含：
- 文件信息组
  - 文件名
  - 行数/列数
- 分析列组
  - 列列表（支持多选，给统计区使用）
- 图表配置组
  - X 轴下拉框
  - Y 轴下拉框
  - “生成图表”按钮
  - 可选：显示数据点复选框
- 操作按钮
  - 开始分析
  - 重置选择

### 7.3 右侧展示区
- 上方：Chart Panel
- 下方：Tab Widget
  - Tab1：原始数据
  - Tab2：统计结果
  - Tab3：日志/提示

---

## 8. 错误处理策略

必须统一处理以下错误：
- 文件不存在 / 被占用
- 文件扩展名不支持
- 编码读取失败
- Excel 引擎缺失
- 列不存在
- Y 列不是数值列
- 数据为空
- 图表数据为空
- 日期解析失败

错误提示原则：
- 用户能看懂
- 包含出错原因
- 尽量给出建议操作
- 控制台记录详细堆栈，但界面展示简洁信息

---

## 9. 开发阶段拆分

### 阶段一：项目骨架（P0）
- 初始化项目目录
- 搭建 PySide6 主窗口
- 接入基础布局
- 跑通空界面

验收：
- 软件可启动
- 主界面分区可见

### 阶段二：文件导入与数据预览（P0）
- 实现 CSV/XLSX 导入
- 解析为 DataFrame
- 在表格中展示原始数据
- 显示文件信息

验收：
- 可导入样例数据
- 可看到列名和数据预览

### 阶段三：列识别与统计计算（P0）
- 自动识别列类型
- 选择分析列
- 计算最大值、最小值、平均值、方差、标准差等
- 结果表格展示

验收：
- 统计结果正确
- 空值/异常值不崩溃

### 阶段四：折线图绘制（P0）
- 选择 X/Y 轴
- 生成折线图
- 支持数值 X 与日期 X 的基础展示
- 图表与结果联动刷新

验收：
- 可正确绘制折线图
- 切换列可重绘

### 阶段五：稳定性与体验优化（P0/P1）
- 错误提示完善
- 日志区
- 重置/清空功能
- 基础可用性测试
- 样例数据准备

验收：
- 常见错误有提示
- 重复导入和重复分析稳定

### 阶段六：增强功能（P1）
- 多 Y 轴
- 导出结果
- 缺失值处理
- 筛选排序

---

## 10. 测试策略

### 10.1 单元测试优先覆盖
- 统计计算正确性
- 文件读取基础逻辑
- 列类型识别
- 空值/异常值处理

### 10.2 手工测试场景
- 导入标准 CSV
- 导入 XLSX
- 选择数值列统计
- 选择文本列作为 X 轴
- 选择日期列作为 X 轴
- 含空值文件
- 含中文列名文件
- 大文件基础性能
- 重复导入多个文件

### 10.3 测试数据建议
准备至少 3 类样例数据：
1. 简单数值趋势数据（适合折线图）
2. 含缺失值和异常值的数据
3. 日期 + 数值的时间序列数据

---

## 11. 依赖清单建议

`requirements.txt` 初始建议：

```txt
PySide6>=6.6
pandas>=2.2
numpy>=1.26
openpyxl>=3.1
pyqtgraph>=0.13
```

可选：
```txt
xlrd>=2.0.1   # 仅当需要兼容 .xls 时添加
chardet>=5.2  # 若需要更稳的 CSV 编码识别
```

---

## 12. 首版开发注意事项

- 不要一开始就追求复杂图表，先把“选列 -> 统计 -> 折线图 -> 结果展示”链路打通
- 表格预览可先限制显示前 1000 行，避免 UI 卡死
- 统计结果要做四舍五入显示，但内部计算保留原始精度
- X 轴为日期时要特别注意排序和刻度显示，这是最容易出体验问题的点
- 统计口径必须在界面或文档中写清楚，避免方差/标准差歧义
- UI 层不要直接写 pandas 计算逻辑，保证后续扩展方便

---

## 13. V1.0 完成定义（DoD）

满足以下条件可认为 V1.0 开发完成：

- 项目可直接启动运行
- 可成功导入本地 CSV/XLSX
- 可在界面查看原始数据
- 可选择分析列
- 可选择折线图 X/Y 轴并成功出图
- 可计算并展示最大值、最小值、平均值、方差、标准差
- 统计结果在界面表格中可见
- 常见错误均有提示且不会导致崩溃
- 有至少一份样例数据可演示完整流程
- README 中写明启动方式与依赖安装方式


---

## 14. V1.1 升级需求补充（本轮实现）

### 14.1 平均值参考线
- 在图表面板中新增“显示平均值线”开关
- 绘图时为每个 Y 列计算有效数据平均值
- 在图中绘制水平参考线：
  - 默认使用与对应 Y 折线相同色系，但采用虚线样式
  - 在线旁边或图例中显示“<列名> 均值: <值>”
- 开关关闭时不绘制平均值线

### 14.2 导出能力
- 工具栏新增导出入口：
  - 导出统计结果
  - 导出图表图片
- 导出统计结果：
  - 若当前已有 `_stats_df`，允许导出为 `.csv` 或 `.xlsx`
  - 导出文件列名保持中文界面一致
- 导出图表：
  - 从当前 PlotWidget 导出为 `.png`
  - 设置合理分辨率，保证文字和线条清晰
- 异常处理：
  - 无统计结果时禁用或提示无法导出统计结果
  - 无图表时禁用或提示无法导出图表
  - 文件保存失败时弹出错误框并写日志

### 14.3 多 Y 轴折线对比
- 左侧配置区从“单个 Y 轴下拉框”升级为“Y 轴多选列表”
- 支持一次选择多个数值列绘制到同一图表中
- 每条折线分配默认调色板颜色：
  - 例如蓝、橙、绿、红、紫、棕
- 每条 Y 列对应一个颜色选择按钮/下拉，允许用户自定义颜色
- 绘图逻辑变更：
  - X 轴仍只有一个
  - 每个 Y 列各自做数值转换、空值过滤、日期排序对齐
  - 以 X 列为公共键对数据做合并/对齐，避免不同序列长度导致错位
- 平均值线按列分别显示时需绑定对应颜色
- 统计功能与图表功能尽量解耦：
  - 统计列继续以“分析列选择”为准
  - 图表 Y 列使用“图表 Y 多选列表”为准

### 14.4 推荐实现细节
- 为每个 Y 系列维护统一结构：列名、颜色、是否显示、平均值
- 图表导出使用 `pyqtgraph.exporters.ImageExporter`
- 统计结果导出复用 pandas 的 `to_csv/to_excel`
- 颜色选择控件可用 `QPushButton + QColorDialog`，按钮背景显示当前颜色

---

## 15. V1.2 架构扩展

### 15.1 数据处理模块设计
新增 `DataProcessingService`，支持规则式数据处理。

#### 处理规则模型
- 列名：作用于哪一列
- 运算符：lt / lte / gt / gte / eq / neq / is_null / not_null
- 阈值：比较值（数值/文本）
- 动作：
  - `delete_row`：删除整行
  - `replace_mean`：替换为该列均值

#### 处理流程
1. 基于当前激活数据集创建副本
2. 按规则顺序执行处理
3. 记录处理日志：删除多少行、替换多少单元格
4. 将结果放入临时储存区，命名为 `<原名>_处理结果_<n>`
5. 自动切换为当前数据集

#### 注意点
- 删除整行会影响所有列
- 替换均值只对数值列有效
- 空值规则不依赖阈值字段
- 连续处理可基于临时数据集再次派生

### 15.2 时间粒度聚合设计
新增 `TimeAggregationService`，用于 X 轴按时间粒度重采样。

#### 支持粒度
- `raw/minute`：原始或按分钟取均值
- `hour`：按小时取均值
- `shift`：按班次聚合
  - 早班：当日 08:00-20:00
  - 晚班：当日 20:00-次日08:00，归属到开始日
- `day`：按天取均值
- `week`：按周取均值

#### 实现方式
- 将 X 列转为 datetime
- 按粒度生成时间标签列
- 对每个 Y 列按时间标签 groupby 取均值
- 聚合结果只用于绘图，不改原始数据表
- 若 X 轴不是时间列，时间粒度控件禁用

### 15.3 多文件与数据集管理
引入 `DatasetManager` 统一管理多份数据。

#### 数据集类型
- `original`：原始导入文件
- `processed`：经数据处理模块生成
- `merged`：多文件合并生成

#### 数据集结构
- `dataset_id`
- `name`
- `kind`（original/processed/merged）
- `source_files`（来源文件列表）
- `created_at`
- `df`
- `can_delete`（原始文件是否允许从临时区移除）

#### 合并策略
- 选择多个 original/processed 数据集后执行合并
- 必须指定时间列
- 按时间列升序排序拼接
- 仅合并同名列，缺少列时填 NaN 并在日志提示
- 合并结果存入临时储存区，命名为 `合并结果_<时间戳>`
- 可通过导出功能保存为本地文件

### 15.4 临时储存区 UI
左侧新增"数据集管理"区域：
- 数据集列表（Tree/List）
- 标记：原始 / 临时 / 合并
- 操作按钮：
  - 切换到该数据集
  - 删除该临时数据集
  - 导出该数据集
- 导入新文件时加入列表，不覆盖已有数据
- 当前激活数据集高亮显示

### 15.5 UI 调整建议
左侧分三个折叠组：
1. 文件/数据集管理
2. 数据处理规则
   - 选择列
   - 选择条件
   - 输入阈值
   - 选择动作
   - 添加规则 / 执行处理
3. 图表配置
   - X 轴
   - Y 轴多选
   - 时间粒度（时间列时启用）
   - 显示点 / 显示均值线

### 15.6 代码新增建议
- `app/models/dataset_item.py`
- `app/services/dataset_manager.py`
- `app/services/data_processing.py`
- `app/services/time_aggregation.py`
- `app/ui/widgets/dataset_panel.py`
- `app/ui/widgets/processing_panel.py`
- `app/ui/widgets/time_granularity_combo.py`
'
---
## 16. 日志与错误追踪模块
### 16.1 设计
- 新增 `app/services/app_logger.py` 封装 `logging`
- 日志级别：debug/info/warning/error
- 文件日志持久化到 `logs/app_YYYY-MM-DD.log`
- 同时输出到控制台（便于调试）
- 未捕获异常通过 `sys.excepthook` 写入日志文件与界面日志区
### 16.2 集成方式
- `MainWindow` 初始化时创建 `AppLogger`
- 所有 `self.log()` 默认写入 info；错误/警告明确标记 level
- 工具栏新增“打开日志目录”按钮，调用系统资源管理器打开 `logs/`
### 16.3 注意点
- 异常时必须记录完整 traceback，便于远程定位 bug
- 日志文件编码统一 UTF-8，避免中文乱码
'
'
---
## 17. 持久化日志系统（已实现）
- 新增 `app/services/app_logger.py`，封装文件日志与控制台日志
- 日志目录：`logs/`
- 日志文件按天滚动：`app_YYYY-MM-DD.log`
- 支持级别：debug/info/warning/error
- 错误日志自动记录 traceback 堆栈
- 主窗口注册全局 `sys.excepthook`，未捕获异常也会写入日志
- 工具栏提供“打开日志目录”按钮，方便定位bug

## 18. 时间粒度聚合修复记录（已修复）
- 修复问题：切换分钟/小时/班次/天/周时报错 `KeyError` / `duplicate keys`
- 根因：聚合后使用临时列 `_time_label`，未重命名回原始X列名；groupby 时带入无关列导致重复键问题
- 修复方案：
  - 聚合后重命名回原时间列名
  - groupby 仅针对选中Y数值列聚合
  - 统一返回 `(df, logs, x_is_datetime, x_column_name)`
- 验证：分钟、小时、班次、天、周均可正常绘图
'

---

## 19. V1.3 需求：X轴时间标签与数据点悬停提示

### 19.1 需求一：X轴时间刻度显示具体时间
**问题**：当前图表X轴时间线使用手动采样的setTicks，标签数量固定且稀少，缩放后无法显示合理的时间刻度。
**技术路线**：
- 时间X轴场景改用pyqtgraph内置的`DateAxisItem`（从`pyqtgraph.Qt`旁的`DateAxisItem`或`pg.DateAxisItem`），自动根据缩放级别生成合理时间格式的刻度。
- 非时间X轴（类别列）继续使用手动刻度。
- 班次聚合后的时间点是整点（08:00/20:00），DateAxisItem会自动按"MM-DD HH:MM"显示。

**风险与注意**：
- pyqtgraph 0.14 中 DateAxisItem 在 `pg.graphicsItems.DateAxisItem`，需确认导入路径。
- DateAxisItem 的X值必须是Unix时间戳（秒），当前代码已用`ts.value/1e9`转换，兼容。

### 19.2 需求二：数据点悬停显示值与时间
**需求**：鼠标悬停到数据点时，显示当前Y值和该点对应的X时间点，时间格式随X轴颗粒度自适应。
**技术路线**：
- 在每条折线上，对数据点单独使用`ScatterPlotItem`（带hoverable=True）而非plot()的symbol参数，以便捕获每个点的hover事件。
- 维护一个点索引映射：(series_name, point_index) -> (x_value, y_value, x_label_text)。
- 为每个ScatterPlotItem连接`sigHovered`信号（pyqtgraph 0.13+支持），在hover回调中用QToolTip显示格式化文本。
- 时间格式自适应策略（基于数据范围/当前粒度）：
  - 若数据跨度>30天：`YYYY-MM-DD`
  - 跨度>1天：`MM-DD HH:MM`
  - 跨度<=1天但有秒精度：`MM-DD HH:MM:SS`
  - 班次聚合：`MM-DD HH:MM 早/晚班`
  - 非时间X轴：直接显示X轴类别值
- 非时间X轴时hover显示X轴原始标签值和Y值。

**风险与注意**：
- ScatterPlotItem的hover事件触发需要symbol有一定大小，symbolBrush需非透明。
- 需要在clear()时断开之前的ScatterPlotItem引用，避免内存泄漏。
- QToolTip定位：直接使用QToolTip.showText全局静态方法，传入hover点的屏幕坐标。

### 19.3 改动文件范围
- `app/ui/widgets/chart_panel.py`：主要改动，引入DateAxisItem、ScatterPlotItem hover、时间格式自适应函数。
- `app/services/time_aggregation.py`：无改动，已有时间列正确。
- `app/ui/main_window.py`：需将当前粒度传递给chart_panel，以便hover时选择时间格式。
- 文档同步更新。

### 19.4 验收标准
- [ ] 时间X轴下，图表X轴显示合理数量的时间刻度，缩放后刻度自适应。
- [ ] 鼠标悬停到任意数据点，显示tooltip包含：系列名、X时间/类别、Y数值。
- [ ] 时间格式随粒度自适应：原始/分钟显示到分钟或秒，小时/班次/天显示到日时，周显示到日期。
- [ ] 不破坏现有功能：多Y折线、颜色、均值线、点显示开关、导出。
- [ ] 非时间X轴场景hover也显示X类别值和Y值。

---

## 20. V1.4 性能优化：耗时日志 + 后台线程 + 进度反馈 + 降采样

### 20.1 问题
- 大文件（十万到百万行）导入、统计、聚合、绘图均在UI主线程同步执行，界面冻结。
- 无耗时记录，无法定位性能瓶颈。
- 图表对每条线绘制所有原始点，20万+点时hover搜索和渲染都慢。
- `_is_datetime_column` 每次绘图都全列重新 `pd.to_datetime` 判断列类型，重复开销。

### 20.2 优化方案与落地

| 优化项 | 实现方式 | 效果 |
|------|--------|-----|
| 耗时日志 | `app/utils/timer_utils.py` 提供 `timed()` 上下文管理器 + `format_duration()`；在导入/绘图/导出/切换/合并/处理/分析各阶段埋点，以 `[耗时] xxx: N ms` 输出到日志面板与文件 | 每步耗时可观测 |
| 后台工作线程 | `app/services/worker.py` 封装 `QRunnable + QThreadPool`，支持 `report_progress(pct,msg)` 回调；`MainWindow._run_background()` 统一启动并回收 | pandas计算不再阻塞UI |
| 进度条 | `QProgressDialog`（模态、最小展示时间300ms，取消按钮隐藏），从worker的 `progress` 信号驱动；短任务只显示状态栏消息 | 长任务有明确反馈 |
| 列类型缓存 | `MainWindow._column_cache[dataset_id] = {"numeric": set, "datetime": set}`，数据集激活时一次性识别，切换列/粒度时复用；缓存失效点：删除数据集/清空 | 消除重复列类型推断 |
| 绘图自动降采样 | `ChartPanel._downsample()` 单线超过3000点时等距采样到3000点左右，保留首尾；符号在<=800点时才显示 | 渲染从O(N)降到O(3000) |
| Hover搜索优化 | 最近点搜索改用 `np.searchsorted` 二分，仅比较最近2个候选点；搜索数据用全量原始点（不丢失精度） | 大数据hover仍毫秒级 |
| 时间戳转换向量化 | 使用 `s.astype("datetime64[ns]").astype("int64")/1e9` 统一为Unix秒，兼容 pandas 2/3 的 datetime64 精度（ns/us/ms） | 消除逐元素Python循环 |
| 标签生成向量化 | 日期strftime用 `Series.dt.strftime().tolist()` 批量生成，再转ndarray索引 | 字符串构造从Python循环改为C级 |
| 线程安全 | Worker中只做DataFrame计算，不调用DatasetManager.add_temporary/set_active等会触发UI通知的方法；这些操作在主线程 `on_success` 回调中执行 | 避免跨线程Qt操作崩溃 |

### 20.3 文件变更
- 新增 `app/utils/timer_utils.py`
- 新增 `app/services/worker.py`
- 修改 `app/ui/widgets/chart_panel.py`：DateAxisItem + 向量化转换 + 降采样 + 二分hover
- 修改 `app/ui/main_window.py`：所有耗时操作走后台Worker，加进度条与耗时埋点，列类型缓存
- 修改 `app/ui/widgets/data_table_panel.py`：避免大数据时 `resizeColumnsToContents()` 阻塞（见20.4）
- 清理__pycache__旧字节码

### 20.4 表格预览细节
- `TablePanel.set_dataframe()` 默认会调用 `resizeColumnsToContents()`，在1000行*多列时仍可能耗费数百毫秒。
- 已改为仅对列数<=30时自动调整列宽，否则使用默认列宽避免卡顿（表格本身已限制预览1000行）。

### 20.5 性能验证（20万行x2数值列x1时间列，本机）
- CSV 读取：~310 ms
- 图表数据准备（原始粒度）：~200 ms
- 图表渲染（自动降采样到3032点/系列）：~210 ms
- 小时聚合：~350 ms
- 双列统计：~20 ms

### 20.6 验收
- [x] 大文件导入/切换/统计/绘图/处理/合并均不再冻结UI
- [x] 耗时日志在日志面板可见
- [x] 长任务期间有模态进度条反馈
- [x] 大数据悬停tooltip仍然准确（使用全量数据做最近点搜索）
- [x] V1.3的X轴时间刻度与悬停tooltip功能保持不变
- [x] 小文件体验不退化

---

## 21. Bug修复记录：X轴时间与数据时间列偏移8小时（时区错位）

### 21.1 现象
- X轴上的时间刻度与数据列里的时间不一致，整体偏移固定小时数（中国大陆为+8小时）。
- 例如 CSV 中 `2026-06-01 08:00:00` 的点，在 X 轴上被绘制到 `16:00:00` 的位置；但 tooltip 文本仍显示 `08:00:00`，造成刻度、点位、tooltip 三者不一致。
- 班次聚合的点位置偏移到下午/次日，标签虽为"08:00早班/20:00晚班"但实际位置错位。

### 21.2 根因
涉及两个组件对时区的处理不匹配：

1. **pandas 时间戳 → Unix epoch 秒的转换语义错误**：
   - V1.3/V1.4 中用 `ts.timestamp()`、`ts.value/1e9`、`s.astype('datetime64[ns]').astype('int64')/1e9` 等方式把 naive datetime（无时区的壁钟时间）转 epoch。
   - Python/pandas 语义：naive datetime 被视为**本地时区时间**，`timestamp()` 返回"本地 08:00 对应的 UTC epoch"。东八区本地 08:00 对应 UTC 00:00，epoch 为 `1780272000`。
   - 但 pandas 3.x 的 `datetime64` 默认精度为 `us`，`astype("int64")` 返回的是把 naive 当 **UTC** 计算的微秒整数，除以 1e9 后得到 `1780300800`（UTC 08:00 的 epoch），实际比正确值大 8×3600=28800 秒。
   - 不同代码路径/不同 pandas 版本语义不一致，导致点位置相对刻度偏移。

2. **pyqtgraph `DateAxisItem` 默认按本地时区渲染 epoch**：
   - `DateAxisItem` 默认 `utcOffset=0` 并不是强制 UTC，而是用系统本地时区（通过 `time.localtime`）把 epoch 转成字符串。
   - 当我们传入错误的 epoch（已偏移8h），轴刻度再叠加一次本地时区偏移就更乱；即使传入正确 epoch，如果轴仍按本地时区渲染，数据里的 UTC 壁钟时间会被加回 8 小时，显示为本地时间，与 CSV 原始时间文本（壁钟）不一致。

两者叠加的直接结果：点位置 / X轴刻度 / tooltip 字符串各自走不同时区语义，必然错位。

### 21.3 解决策略
统一语义：**所有 naive datetime 按 UTC 壁钟处理**，X轴、tooltip、hover 都以"CSV里写的几点就是几点"为标准，不做任何时区换算。

具体改动：
- `ChartPanel.__init__` 中 `DateAxisItem` 改为 `pg.DateAxisItem(orientation="bottom", utcOffset=0)`，明确告诉它 epoch 按 UTC 解释，不再叠加本地时区偏移。
- 新增/重写 `ChartPanel._datetime_to_unix_seconds(s)`：
  - 先用 `pd.to_datetime(s, utc=True).dt.tz_convert("UTC")` 把 naive 列显式标记为 UTC；
  - 再 `to_numpy(dtype="datetime64[ns]").astype("int64")/1e9` 得到纳秒整数后转秒，统一以 UTC 为基准的 epoch，与 `DateAxisItem(utcOffset=0)` 的渲染语义严格对齐；
  - 避免依赖 `Timestamp.timestamp()` / `ts.value` 等在 naive datetime 上带本地时区语义的 API；同时用 `dtype="datetime64[ns]"` 显式指定纳秒，兼容 pandas 3.x 默认 `us` 精度。
- Tooltip 文本本来就是用 `ts.strftime(fmt)` 直接格式化 naive datetime，保持不变；这样 tooltip 文本与 X 轴刻度都是同一个壁钟时间，一致。
- 班次聚合 `_format_shift_label` 仍基于 naive Timestamp 的 `hour`，语义不变。

### 21.4 影响范围
- 修改文件：`app/ui/widgets/chart_panel.py`（仅时间轴相关）。
- 其他服务层（time_aggregation、stats、data_processing）全部处理 naive datetime，未引入时区对象，逻辑不变。
- 非时间 X 轴（类别列）路径不受影响。
- 跨时区机器行为：统一按 UTC 壁钟显示 = CSV 原始时间，不会因为系统时区变化而偏移。

### 21.5 验证
- 构造/使用 `sample_data/time_sample.csv`，对原始/分钟/小时/班次/天/周 全部 6 种粒度逐一验证：首/末点 epoch 经 `time.gmtime` 转换后的日期时分与 tooltip `x_labels[0]` 完全一致。
- 中国大陆（UTC+8）机器不再出现 8 小时偏移。
- 大文件（>10万行）场景的降采样/hover二分搜索逻辑未受影响，性能保持 V1.4 水平。

---

## 22. V1.5 新增：导入文件夹 + 路径记忆

### 22.1 功能清单
- 工具栏新增"导入文件夹"按钮：选择目录后递归遍历所有子目录，自动筛选 `.csv / .xlsx / .xls` 文件，复用现有后台Worker批量导入并显示进度。
- 文件对话框记忆上次目录：
  - `last_import_dir`：导入文件/文件夹默认打开位置
  - `last_export_dir`：导出统计结果/图表/数据集默认打开位置
  - 通过 `QSettings("DateAnalysis","DateAnalysis")` 持久化到系统注册表/配置文件，重启软件后仍然生效。
- 悬停时长需求（原V1.5需求1）已由用户确认取消，保持系统默认QToolTip时长。

### 22.2 技术实现
- `MainWindow.__init__` 中读取/保存 `QSettings`，维护 `self._last_import_dir / self._last_export_dir`，初始值为用户主目录。
- 导入流程：
  - `_import_files` 打开文件对话框时以 `self._last_import_dir` 为起点；选择成功后取第一个文件的父目录写回 `last_import_dir`。
  - 新增 `_import_folder` 调用 `QFileDialog.getExistingDirectory`，用 `Path.rglob("*")` 递归，按后缀白名单 `{".csv",".xlsx",".xls"}` 过滤并排序；随后复用 `_worker_import`/`_on_import_done` 走异步进度条。
  - Worker中不再从子线程调用 `self.log`（避免跨线程UI操作），耗时与错误日志在主线程回调里输出。
- 导出：
  - `_export_dataset/_export_stats/_export_chart_image` 的保存对话框起始路径均使用 `self._last_export_dir/<默认文件名>`；保存成功后写回。
- 白名单仅识别三种表格扩展名，非表格文件（txt/图片/二进制）自动忽略。

### 22.3 风险与边界
- 导入文件夹会递归所有层级；超大量子目录（>1000个）时文件枚举本身很快（仅Path.rglob），读取并发走Worker+进度条，不会阻塞UI。
- QSettings 在 Windows 下写入注册表 `HKCU\Software\DateAnalysis\DateAnalysis`，卸载软件不会自动清理，属正常行为。
- 路径记忆只记录目录，不记录文件名/筛选格式；用户最后一次操作目录作为下次起点，符合常见软件习惯。

### 22.4 验收
- [x] 工具栏"导入文件夹"按钮可点击，递归导入并显示进度条
- [x] 非表格文件自动忽略
- [x] 导入、导出对话框多次打开时记忆上次目录
- [x] 重启软件后路径记忆仍然生效
- [x] 不影响原有单文件导入、导出、后台线程、图表、tooltip、降采样等功能

## 19. 2026-07-03 编码与接口兼容修复记录
- 问题：图表面板中文文案编码损坏导致问号；Y序列三元组与主窗口二元组解包不兼容导致时间粒度分析失败；进度对话框销毁后回调异常
- 修复：恢复中文文案，统一Y序列接口，补充进度控件空值与销毁保护
- 结果：界面问号问题核心点修复，分析/绘图主链路恢复可用
