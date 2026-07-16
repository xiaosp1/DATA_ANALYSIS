# ADR-006 — 后台任务调度与数据隔离策略

- 日期：2026-07-13
- 状态：Accepted
- 决策者：尘醒（Owner）/ dataanalysis-pm

## 背景
桌面应用中所有耗时操作（统计计算、描述统计、工艺分析、归因分析、AI 请求、图表渲染）都需要在后台线程执行，同时需要保证：
1. 用户操作期间 UI 不会卡顿；
2. 同一类操作互斥（不会同时触发两个数据集合并或两个工艺分析）；
3. 不同类操作可以并行（如数据集操作时可以做 AI 请求）；
4. 原始数据不被处理/合并操作覆盖。

## 选项

### 选项 A：单全局锁 + QProgressDialog
- 单一 `_busy` 标志，任何耗时操作进行时阻塞所有其他操作
- 优点：实现简单
- 缺点：体验差——数据集操作时 AI 也无法用，分析时无法修改数据

### 选项 B：分类粒度锁 + 后台线程池（选定）
- 按操作类型分锁：dataset（数据集操作）、analysis（分析操作）、AI 独立（无锁）
- 通过 `_run_background()` 统一入口封装
- 优点：多类操作可并行，用户体验好
- 缺点：需仔细设计锁边界

### 选项 C：asyncio 异步 + Qt event loop 集成
- 完全异步化，用 asyncio.gather 并发执行
- 优点：真正的异步，天然支持取消
- 缺点：与 PySide6 集成复杂，pandas 大部分操作不原生 async

## 决定
采用 **选项 B（分类粒度锁 + QThreadPool）**。

### D1. 粒度锁设计

```python
# MainWindow 中的三把锁
_dataset_busy      # 数据集操作互斥（导入/合并/缩放/删除/处理）
_analysis_busy     # 分析操作互斥（统计/描述统计/工艺分析/归因分析/绘图）
_ai_busy           # AI 状态标记（不占全局锁，仅 UI 面板内部互斥）

# 三类锁之间互不阻塞：
#   dataset + analysis → 可并行（如：数据集缩放时可以做分析）
#   dataset + ai       → 可并行
#   analysis + ai      → 可并行
```

### D2. `_run_background()` 统一入口

`MainWindow._run_background()` 是**所有**后台任务的统一调度入口，接收 9 个参数：

```python
def _run_background(
    self, label, fn, fn_args, on_success, on_error=None,
    busy_lock="dataset",              # 'dataset' | 'analysis' | 'none'
    on_started=None,                  # 可选：线程启动时回调
    on_finished=None,                 # 可选：无论成功/失败都会回调
    cancel_event=None,                # 可选：threading.Event 用于软取消
):
```

- `busy_lock="dataset"`：占 `_dataset_busy` 锁，弹 QProgressDialog
- `busy_lock="analysis"`：占 `_analysis_busy` 锁，弹 QProgressDialog（状态栏提示而非弹窗）
- `busy_lock="none"`：不占锁，不弹全局对话框（AI 请求走此模式）
- 锁释放在 on_success/on_error 回调中统一执行（finally 语义）

### D3. 数据隔离策略

```
DatasetManager 管理的三个数据集生命周期：

1. 原始数据（kind='original'）:
   - can_delete = False（不可删除）
   - 任何处理操作（规则/缩放）都产生新副本
   - 导入时创建，"清空全部"时释放

2. 处理结果（kind='processed'）:
   - can_delete = True（可删除）
   - 通过 DatasetManager.add_temporary() 创建
   - source_files 记录来源数据集 ID

3. 合并结果（kind='merged'）:
   - can_delete = True（可删除）
   - 通过 DatasetManager.merge_by_category() 或 merge_cross_category() 创建
   - 命名约定：机头_合并 / 机尾_合并 / 机头+机尾_跨类合并
```

**关键约束**：所有数据处理操作（`apply_rules()`）都**浅拷贝**后操作新 DataFrame，原始 DataFrame 始终不变。

### D4. AI 独立锁设计

AI 请求不占用 `_dataset_busy` / `_analysis_busy`，而是：
- `ProcessAnalysisPanel` 内部管理 `_ai_busy` 状态
- 支持 AI 请求与数据集操作/分析操作并行
- 通过 `req_id` 机制防止旧请求结果覆盖新请求（`_on_ai_insight_requested` 中用 `id(cancel_event)` 做请求标识）

### D5. PandasTableModel 预览策略

- `PandasTableModel` 仅展示前 1000 行（`_preview_rows=1000`）用于 `QTableView` 预览
- 统计计算、图表绘制、分析均基于**全量数据**（`self._df` 存全量）
- `set_dataframe()` 时自动裁剪为 preview_df，通过 `beginResetModel()/endResetModel()` 触发 QTableView 刷新
- 列数 ≤20 时自动 resizeColumnsToContents，>20 时保持 Interactive

### D6. 错误处理与日志

- `MainWindow._install_excepthook()` 注册 `sys.excepthook`，捕获未处理异常写入日志 + 弹出对话框
- `AppLogger` 按天滚动：`logs/app_YYYY-MM-DD.log`（DEBUG 级别），stdout 输出 INFO 级别
- 图表渲染/导出/处理等操作使用 `timed()` 上下文管理器记录耗时

## 后果

### 正面
- **多类并行**：数据集操作期间用户仍可用 AI 功能，互不阻塞
- **统一入口**：所有后台任务通过 `_run_background()` 管理，进度/取消/锁释放逻辑一致
- **数据隔离**：原始数据不可被处理覆盖，临时储存区机制保证"撤销"可行
- **大文件预览**：1000 行预览 + 全量计算，兼顾性能与精度
- **错误兜底**：excepthook + 分级日志，异常不导致静默失败

### 负面
- **锁粒度需要维护**：新增后台操作时需正确选择 busy_lock 类型，否则可能并发冲突
- **cancel_event 需显式传入**：只有显式传入 cancel_event 的操作才能被取消（AI/归因有，统计计算无）
- **QProgressDialog 取消语义**：收起 ≠ 线程终止，用户可能误以为取消了但实际上后台仍在运行
- **Pandas 不可逆**：处理结果虽然存副本，但 pandas 的 in-place 操作（如 `df[col] = ...`）不可逆
