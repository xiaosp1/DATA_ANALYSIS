# CONTEXT_MEMORY

## 当前状态
- 版本：V1.4（性能优化已完成）
- 最近改动：耗时日志 / 后台线程 / 进度条 / 绘图自动降采样 / 列类型缓存

## 功能累计
- 工具栏新增"导入文件夹"按钮：递归识别目录下 csv/xlsx/xls 批量导入
- 文件对话框记忆上次使用目录（QSettings持久化）
- CSV/XLSX多文件导入、切换、按时间合并
- 临时储存区（原始/处理/合并）
- 数据处理：按条件删除整行、替换列均值
- 多Y折线、颜色自定义、平均值参考线开关
- 时间粒度：分钟/小时/班次（早8晚8两班）/天/周
- X轴时间刻度使用 pyqtgraph.DateAxisItem 自动适配，缩放时自适应
- 数据点悬停 tooltip：显示系列名、时间点（随粒度自适应格式）、数值
- 统计结果导出 CSV/XLSX、图表 PNG 导出、数据集导出
- 持久化日志：logs/app_YYYY-MM-DD.log，含堆栈traceback，工具栏可打开日志目录
- 左侧控制面板已加滚动区域
- 【V1.4】所有 pandas 重计算（导入/统计/绘图准备/处理/合并/切换）跑在 QThreadPool 后台线程；UI 线程只做渲染，长任务有 QProgressDialog 模态进度提示
- 【V1.4】耗时日志：所有主要操作在日志面板和日志文件输出 [耗时] xxx: N ms
- 【V1.4】绘图自动降采样：单线超过3000点时等距采样到约3000点；hover 最近点搜索仍用全量数据
- 【V1.4】时间戳转Unix秒使用向量化方式（astype datetime64[ns]→int64/1e9），兼容 pandas 3 默认 datetime64[us]
- 【V1.4】列类型（numeric/datetime）按 dataset_id 缓存，切换列/粒度时复用
- 【V1.4】表格预览>20列时不再调用 resizeColumnsToContents，避免卡顿

## 关键文件
- app/services/worker.py：QRunnable Worker + QThreadPool 封装，支持 report_progress
- app/utils/timer_utils.py：timed() 上下文管理器 + format_duration()
- app/services/app_logger.py：持久化日志
- app/services/time_aggregation.py：时间聚合
- app/services/dataset_manager.py：多数据集管理/合并
- app/services/data_processing.py：条件数据处理
- app/ui/main_window.py：主窗口（已改为异步调度 + 进度条）
- app/utils/timer_utils.py：耗时计时工具
- app/services/worker.py：QThreadPool后台Worker
- app/ui/widgets/chart_panel.py：图表（DateAxisItem + 降采样 + 二分hover）
- app/ui/widgets/data_table_panel.py：表格预览（列数>20不再自适应列宽）
- logs/：运行日志目录

## 运行
```powershell
.\.venv\Scripts\Activate.ps1
python app\main.py
```

## 已知边界 / 注意
- 【V1.4.1 修复】X轴时区偏移：时间戳统一按UTC壁钟处理，DateAxisItem设utcOffset=0，转换使用pd.to_datetime(utc=True)→datetime64[ns]→int64/1e9；不再依赖Timestamp.timestamp()
- 原始数据预览前 1000 行；统计/绘图基于全量有效数据
- 均值线全局开关，未做单序列开关
- .xls 未完整验证
- 临时数据集关闭软件不持久化
- 悬停 tooltip 基于最近点搜索，像素阈值 14px
- 自动降采样为均匀等距采样，未做基于视口的LTTB；zoom不触发重新采样
- Worker 线程内禁止调用任何会触发 DatasetManager._notify 的方法（manager.add_temporary/set_active/remove/clear），这些必须放到主线程 on_success 回调里执行，避免跨线程Qt操作



- 2026-07-03：修复UI乱码问号问题，恢复chart_config_panel/chart_panel中文文案，修复Y序列三元组解包错误，补充进度回调空对象保护。

## 2026-07-03 修复记录
- 问题：UI问号乱码 + 时间粒度分析报错 + 进度回调偶发异常
- 原因：
  - chart_config_panel.py / chart_panel.py 中文文案编码损坏
  - y_series 已升级为三元组但主窗口仍按二元组解包
  - _progress_cb 未对None/已销毁控件做保护
- 修复：
  - 恢复两个面板中文文案
  - 主窗口改为 `[n for n, *_ in y_series]`
  - 修复标题/粒度常量/提示文本
  - progress回调增加RuntimeError/None保护
- 验证：编译通过，窗口正常启动
