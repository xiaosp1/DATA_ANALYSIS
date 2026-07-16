# ADR-005 — 跨类图表架构（机头/机尾同图 + 小多图 + 双Y轴）

- 日期：2026-07-13
- 状态：Accepted
- 决策者：尘醒（Owner）/ dataanalysis-pm

## 背景
V1.7 引入机头/机尾双类别后，需要在同一个图表中同时显示两类数据。两类数据特点：
- 列名不同（跨类合并后加 `[机头]`/`[机尾]` 前缀）
- 数值量级可能不同（因各自有不同的 mm 缩放 factor）
- 时间戳可能不同步（跨类 outer join，一侧可能有 NaN）

原有 V1.6.1 图表只支持"同量级多Y"（所有Y列共用一个 Y 轴），无法满足机头/机尾同图显示的需求。

## 选项

### 选项 A：双 Y 轴（左右独立缩放）
- 第一条 Y 列挂在左轴（原始缩放），其余挂在右轴（独立缩放）
- 优点：直观，两边各自保持原始量级
- 缺点：只有 2 组 Y 列（左/右），超过 2 个量级无法区分

### 选项 B：归一化到 [0, 1]
- 所有 Y 列独立缩放到 [0, 1]，共用一个 Y 轴
- 优点：可以看趋势相关性，不受量级影响
- 缺点：丢失原始数值信息，无法直接读数值

### 选项 C：小多图（Small Multiples）
- 每个 Y 列独立子图，纵向堆叠，共享 X 轴
- 优点：每列独立 Y 轴缩放，互不干扰；多列时布局清晰
- 缺点：页面占用大，列数多时不可用

### 选项 D：多模式并存（选定方案）
- 允许用户选择 Y 轴显示模式
- 同时实现共享轴/双Y/归一化/小多图四种模式
- 优点：覆盖所有使用场景，用户按需选择
- 缺点：实现复杂度较高

## 决定
采用 **选项 D（多模式并存）**，在 `ChartOptionsPanel` 中提供 Y 轴模式选择器。

### D1. Y 轴模式枚举

```python
y_mode_combo:
  "shared"         → 共用 Y 轴（原始值）       # V1.6.1 默认行为
  "normalized"     → 归一化显示（0-1）          # 看趋势相关性
  "dual"           → 双 Y 轴（第一条左轴，其余右轴） # 两类量级差异大
  "small_multiples"→ 小多图（每列独立子图）       # 列数多或量级差异大
```

### D2. 双 Y 轴实现

```
ChartPanel.plot_multi_line(y_axis_mode="dual")
  │
  ├── 计算有效 Y 列数
  │     └── 若有效列 ≤ 1 → 退化为 "shared"（单列双轴无意义）
  │
  ├── 左轴 ViewBox (vb_left):
  │     - 第一条有效 Y 列挂左轴
  │     - 均值线 + 均值标签在左轴
  │
  └── 右轴 ViewBox (vb_right):
        - 第二条及以后 Y 列挂右轴
        - 均值线在右轴 ViewBox 上绘制
        - 均值标签不绘制（避免与左轴标签错位）
        │
        ├── _setup_right_axis():
        │     - 创建新 ViewBox
        │     - showAxis("right")
        │     - linkToView(vb2) + setXLink(vb1)
        │     - 绑定 sigResized/sigRangeChanged 同步几何
        │
        └── _teardown_right_axis():
              - 断开同步信号
              - 从 scene 移除 vb2
              - 清理所有右轴 PlotDataItem / InfiniteLine
```

**关键设计**：右轴 ViewBox 在主 ViewBox 缩放/移动时同步几何（`sigRangeChanged` + `sigResized`），确保双轴 X 轴联动一致。

### D3. 小多图实现

```
ChartPanel.plot_multi_line(y_axis_mode="small_multiples")
  │
  ├── 隐藏 plot_widget，显示 _sm_widget (GraphicsLayoutWidget)
  │
  ├── 每个 Y 列一个 PlotItem，纵向堆叠（row=i, col=0）
  │
  ├── 共享 X 轴：
  │     - 第一个子图创建 DateAxisItem
  │     - 后续子图 setXLink(第一个子图)
  │     - 非底行隐藏 X 轴刻度标签（避免重复）
  │
  ├── 联动光标：
  │     - 每个子图安装 InfiniteLine（竖线）
  │     - 鼠标移动时 _on_sm_mouse_moved 在所有子图同步竖线位置
  │     - tooltip 在命中子图内找最近点
  │
  └── _teardown_small_multiples():
        - 销毁所有子图
        - 恢复单图态
```

### D4. 归一化模式

归一化在 `ChartConfigPanel` 中实现（用户勾选每个 Y 列的"归一化"复选框）：
- 每条 Y 列独立做 `(x - min) / (max - min)` 归一化
- 归一化后的值传入 `ChartPanel`，以 `y_mode="normalized"` 绘制
- 共用左 Y 轴，数值范围 [0, 1]

### D5. 跨类合并数据集的特殊处理

跨类合并后，列名带 `[机头]`/`[机尾]` 前缀，图表绘制时：
- 列选择面板正常显示带前缀的列名
- 图例显示完整列名（含前缀）
- 时间粒度聚合对带前缀列分别 mean，缺失窗口为 NaN
- 描述统计对所有数值列（含前缀列）生效
- 归因分析自动识别 `[机头]` 前缀的数值列为特征

### D6. 导出适配

- `ChartPanel.current_export_widget()` 返回当前应截图导出的 widget：
  - 小多图模式 → 导出 `_sm_widget`
  - 其他模式 → 导出 `plot_widget`
- `ChartPanel.has_plotted_data()` 守卫导出：检查当前视图是否有数据
- 导出 PNG 使用 `plot_widget.grab()` / `_sm_widget.grab()` → `QPixmap.save()`

## 后果

### 正面
- **四种模式覆盖所有场景**：shared（默认）、normalized（相关性分析）、dual（量级差异）、small_multiples（列数多）
- **双轴同步**：X 轴联动通过 `setXLink` + 几何同步实现，用户体验一致
- **小多图联动光标**：跨子图竖线 + tooltip，便于多列对比
- **退化策略**：单列双轴自动退化为 shared，避免无效 UI
- **导出适配**：current_export_widget 确保小多图模式导出正确 widget

### 负面
- **实现复杂**：`ChartPanel` 约 800 行，是代码库中最复杂的模块
- **均值标签仅左轴**：双 Y 轴模式下右轴均值线有但标签不绘制（避免错位），后续需改进
- **小多图性能**：列数极多时创建大量 PlotItem，可能影响渲染性能（当前有采样上限兜底）
- **Y 轴模式切换需重新绘图**：当前实现为每次模式切换调用 `plot_multi_line` 重绘，未增量更新

## 验收
- `tests/test_w6_dual_axis.py`（142 行）：双Y轴图表绘制
- `tests/test_w7_small_multiples.py`（203 行）：小多图布局
- `tests/test_w6_normalize.py`（49 行）：归一化显示
- `tests/test_w6_chart_options.py`（34 行）：图表选项面板
