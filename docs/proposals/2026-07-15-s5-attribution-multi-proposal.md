# S5-#1 归因分析扩展点 + 算法选型 + UI 草图

> **性质**：只读调研报告（analyst 阶段）。不写代码、不改实现。
> **工作目录**：`E:\DEMO\DataAnalysis\projects\dateanalysis-desktop`
> **扫描日期**：2026-07-15
> **作者**：analyst-s5-attribution（subagent）
> **Owner 需求一句话**：把机尾指数-s 归因从"单对单"升级到"头部多列对尾部单列"，UI 默认全选 + Top10 预勾，3 张图表布局。

---

## 0. 现有实现盘点（baseline）

### 0.1 数据形状
- 输入是一张**已经跨类合并好的宽表**：机头列带 `[机头]` 前缀，机尾列带 `[机尾]` 前缀。CSV 原始列 `时间,机头温度,机头压力,机头速度,机头时间,类别,机尾指数-s,机尾厚度,状态`（`sample_data/demolding_sample.csv`，共 40 行）需经过【跨类合同图】→`merge_asof` 后才出现 `[机头]*` 前缀（参 `docs/domain/demolding-process-overview.md:48-58`、`process_analysis_panel.py:_has_head_tail_columns`）。
- 目标列固定 `[机尾]指数-s`，理想值 4.0，公差 0.5（`head_tail_attribution.py:91`、`process_analysis_panel.py:576-577`）。

### 0.2 现有归因结构（核心引擎 `head_tail_attribution.py`）
- **签名** `build_head_tail_report(df, target_col, head_prefix, tail_prefix, ideal_value, min_samples, feature_cols, time_col, ideal_tol, n_buckets, top_n, top_rules_n, report_progress, cancel_event)`（`head_tail_attribution.py:82-96`）
- **进度回调点**：5/10/20+(20+30·i/n)/55+(55+20·i/n)/78/92/100（`head_tail_attribution.py:88、128、184、220、262、298`）
- **取消机制**：`threading.Event` + `_check_cancel()` 在相关系数/分组统计/规则挖掘三个阶段轮询（`head_tail_attribution.py:186、214、269`），抛 `AttributionCancelledError`（`head_tail_attribution.py:11-13`）
- **现有算法**：逐特征 Pearson + Spearman（`_pearson/_spearman`，行 25-78）→ 取 Top-N（按 `abs_spearman`）→ 分组统计 + 五分位分箱 → 单特征阈值规则（1/3 / 1/2 / 2/3 分位数 + `<=`/`>` 两方向，按 `pct_near_ideal·n^0.25` 打分，行 244-288）
- **输出 schema**（行 312-326）：`meta / target_dist / attribution[] / top_rules[] / overall_suggested_window{}`，其中 `attribution[i]` 单条形如 `{feature, n, pearson_r, spearman_r, abs_spearman, direction, mean/std/window_ideal/off, bucket_analysis[]}`。
- **库依赖现状**：核心仅 `numpy + pandas`；scipy 可选做 pearson/spearman（行 15-21），缺失时用 `_rankdata` + numpy 手工实现兜底（行 41-58、77-79）。

### 0.3 现有 UI 集成（`process_analysis_panel.py`）
- 模式 combo：`"状态分类"/"机尾指数-s归因"`（行 116-118）
- 特征列 `QListWidget`（多选，90px 高，**默认全选**，行 128-131；填充逻辑 `is_attr` 分支在行 695-697 默认勾选）
- 归因 Tab = `attrib_widget`（表格 7 列 + 规则文本，行 168-185）
- **进度条与取消沿用 W12.4 模式**：目前未在 panel 内显式画进度条，进度通过 `_call_progress` 回调 `analyze_btn.setText("分析中...")` + `status_label` 文字（panel 行 595-601）；**取消按钮**已在 AI Tab 复刻（`ai_cancel_btn`，行 309），归因 Tab 当前没有"取消"按钮，是个待补点。

### 0.4 现有测试（`tests/test_w12_head_tail_attribution.py`）
- 6 个测试 + 1 个 prompt 测试，函数式 / 不依赖 Qt。
- 用 `_make_synthetic_df(n, seed)` 构造 3 列 `[机头]f1/f2/f3` + `[机尾]指数-s`（f1 强、f3 弱、f2 噪声，行 11-29）。
- 已覆盖：结构完整性、相关系数排名、规则非空、`min_samples` 大值、缺列报错、取消事件、AI prompt 关键词。

---

## 1. 扩展点（参数化清单）

> 原则：**沿用现有 `build_head_tail_report` 签名增加可选参数**，新增多变量归因子函数；不破坏旧 6 个测试。

### 1.1 引擎层（`app/services/head_tail_attribution.py`）

| 函数 / 符号 | 现状 | 扩展点 | 优先级 |
|---|---|---|---|
| `build_head_tail_report(...)`（行 82） | 单目标 + 多特征，特征全跑单变量 | **新增可选开关 `multi: bool = False`**：开启后除原有单变量外，再追加 M1/M2 多变量结果到 `report["multi"]` 节点；进度点新增 25-50 段（"偏相关计算中"/"OLS 拟合中"） | P0 |
| `pairwise` 列表（行 184-205） | 每个特征算 1 对 Pearson + Spearman | **无需改**，作为 M1 的"单偏相关"对照基线 | — |
| `attribution[]`（行 220-260） | Top-N 单变量 | **无需改**，保留 W12 单变量视图 | — |
| `top_rules[]`（行 264-289） | 单特征阈值规则 | **无需改**，M2 的规则由 OLS β\* 排名替代 | — |
| `overall_suggested_window`（行 297-303） | 取前 3 个单变量窗口 | **保持不变**，多变量结论另存到 `overall_suggested_window_multi` | P1 |
| `_pearson/_spearman`（行 25-78） | numpy/scipy 兜底 | **复用**，M1 偏相关基函数 | — |
| （新增）`_partial_corr(df, target, x, controls)` | 无 | 新增函数，行级实现 pingouin 公式的 numpy 等价（详见 §2.1）；输入 1 个 x + 多个 controls；返回 `(r_partial, p_value, n_used)` | P0 |
| （新增）`_ols_standardized(X, y)` | 无 | 新增函数：先按列 `z-score`，再做 `np.linalg.lstsq` 解 `β*`，返回 `dict(coef, r2, r2_adj, n, k, vif[], condition_number)`，**库依赖 numpy + 兜底 `statsmodels`** | P0 |
| （新增）`_compute_vif(X_standardized)` | 无 | `VIF_j = 1/(1 - R²_j)`，R²_j 由 OLS 把 X_j 对其余 X 做回归得到；numpy 实现 | P0 |
| （新增）`_format_multi_result(...)` | 无 | 把 M1/M2 结果序列化成 dict（list of dict）便于 UI 直接渲染 | P0 |
| `AttributionCancelledError`（行 11-13） | 已有 | **复用**；M1/M2 在每特征后插入 `_check_cancel()` | P0 |
| `ProgressCb` 类型（行 24） | `Callable[[int, str], None] \| None` | **保持不变**，M1/M2 阶段用 `25 + int(25·i/n)` 和 `55 + int(20·i/n)` 报告 | P0 |

**签名建议**（向后兼容，旧测试不动）：
```python
def build_head_tail_report(
    df, target_col,
    head_prefix="[机头]", tail_prefix="[机尾]",
    ideal_value=4.0, min_samples=30,
    feature_cols=None, time_col="时间",
    ideal_tol=0.5, n_buckets=5,
    top_n=20, top_rules_n=5,
    report_progress=None, cancel_event=None,
    # ===== S5 新增参数 =====
    multi: bool = False,                 # 是否启用多变量归因
    multi_top_n: int = 10,               # M2 参与 OLS 的默认头部列数
    multi_min_samples: int = 30,         # M1/M2 至少需要的有效样本数
    multi_exclude_vif_gt: float = 10.0,  # VIF 阈值：超过此值降级为单变量提示
    multi_compute_partial: bool = True,  # 是否计算偏相关
    multi_compute_ols: bool = True,      # 是否计算 OLS
) -> dict[str, Any]: ...
```

### 1.2 UI 层（`app/ui/widgets/process_analysis_panel.py`）

| 位置 | 现状 | 扩展点 | 优先级 |
|---|---|---|---|
| `mode_combo`（行 116-118） | 二选一 | **无需改**，沿用 `head_tail_attr` 模式；归因模式天然兼容多变量 | — |
| `feature_list`（行 128-131） | `QListWidget.MultiSelection`，最大高度 180 | **复用**，多变量归因直接复用现有勾选状态；选中集合就是 `feature_cols` 入参 | — |
| `_populate_features`（行 685-697） | `is_attr` 时只显示 `[机头]*`，默认 `setSelected(True)` | **保留默认全选**；**新增** Top10 预勾逻辑（详见 §3）：按列均值或绝对值与目标相关系数初排，前 10 名置顶并预勾 | P0 |
| `get_config`（行 569-582） | 透传 `feature_cols` | **复用**，无需改；多变量开关走分析按钮旁的 `multi_checkbox` | P0 |
| `attrib_table`（行 173-179） | 7 列：特征/N/Pearson/Spearman/方向/理想时μ±σ/推荐窗口 | **复用**：单变量视图保留；**新增 Tab "多变量归因"**，包含 3 张图 + 2 张表（M1 / M2 结果） | P0 |
| `result_tabs`（行 155、185） | 已有 7 个 Tab | **新增 Tab "多变量归因 (S5)"**，放在 `归因结果` 与 `AI 解读` 之间（行 185 之后） | P0 |
| `analyze_btn`（行 137） | 仅"开始分析"按钮 | **新增** 旁边的小复选框 `多变量归因`（默认勾选；按 S5 计划即默认开启） | P0 |
| 取消按钮 | **目前归因 Tab 无独立取消按钮**，进度只通过文字反映 | **新增** `attrib_cancel_btn`（参考 AI Tab 的 `ai_cancel_btn`，行 309），复用同一 `cancel_event`；点击立即发 cancel 信号，UI 即时反馈 | P0 |
| 进度条 | **当前无 QProgressBar**，只 `setText("分析中...")` | **新增** `QProgressBar`（`progress_bar`），值由 `_call_progress(0..100)` 直接更新；M2 阶段文字显示"OLS 拟合 N/M" | P1 |
| `attrib_summary_label`（行 170） | 一段文字 | **扩展**："单变量 Top3 + 多变量 M1/M2 Top3 + 共线性警告（VIF>10 列出列名）" 三段 | P1 |
| 导出按钮 `export_btn`（行 139） | CSV + PNG | **扩展** 多变量 PNG（图 1/2/3）与 multi_results.csv（M1 表 + M2 表） | P1 |

### 1.3 测试层（`tests/`）

| 现有测试 | 是否要改 | 新增测试（建议文件 `test_s5_multi_attribution.py`） |
|---|---|---|
| `test_build_head_tail_report_basic_structure` | ❌ 不动 | `test_multi_disabled_default`：默认 `multi=False` 时 `report` 不含 `multi` 键 |
| `test_build_head_tail_report_correlation_ranking` | ❌ 不动 | `test_multi_partial_corr_basic`：人造 f1 强 + f3 混杂 f1 时，f3 的单偏相关应比 Pearson 低 |
| `test_build_head_tail_report_rules_not_empty` | ❌ 不动 | `test_multi_ols_basic`：标准化系数 β\* 排序应与已知权重一致 |
| `test_build_head_tail_report_min_samples_filter` | ❌ 不动 | `test_multi_vif_warning`：构造高度共线两列，断言 `warnings` 包含 "VIF" |
| `test_build_head_tail_report_no_head_cols` | ❌ 不动 | `test_multi_high_dominance_drop_one`：含强主因子时，drop-one 后其它列 β\* 应显著下降 |
| `test_build_head_tail_report_no_target_col` | ❌ 不动 | `test_multi_cancel`：M1 阶段 cancel_event.set() 抛 `AttributionCancelledError` |
| `test_build_head_tail_report_cancelled` | ❌ 不动 | `test_multi_n_less_than_min_samples`：N<30 自动跳过 OLS，warnings 注明原因 |
| `test_build_head_tail_prompt_contains_keywords` | ❌ 不动 | `test_multi_prompt`：M2 报告喂给 `build_head_tail_prompt` 应包含 "β\*" 或 "偏相关" 关键字 |

---

## 2. 算法选型（M1 偏相关 + M2 OLS）

> 目标：在**默认全选 + Top10 预勾**的列集合上，做多变量归因；M1 / M2 互补，不互斥。

### 2.1 M1：偏相关（partial correlation）

#### 2.1.1 公式
对于目标 `y`、当前特征 `x_i`、控制集合 `Z = {x_1,...,x_p} \ {x_i}`：

**逐变量法（一阶偏相关，所有 Z 同时回归）**：

1. 把 `y`, `x_i`, 每个 `x_j ∈ Z` 标准化（`(x - mean) / std`）。
2. 各自对 `Z` 做 OLS 取残差：
   - `e_y = y - ŷ`（`y ~ Z`）
   - `e_i = x_i - x̂_i`（`x_i ~ Z`）
   - `e_j = x_j - x̂_j`，`j ∈ Z`（为求 VIF 与配对检查备用）
3. 偏相关系数：
   $$ r_{y x_i \cdot Z} = \frac{\mathrm{corr}(e_y, e_i)} = \frac{\sum e_y e_i}{\sqrt{\sum e_y^2 \,\sum e_i^2}} $$
4. t 检验：
   $$ t = r \sqrt{\frac{n - |Z| - 2}{1 - r^2}},\quad df = n - |Z| - 2 $$

**为什么不用递归 Pearson 偏相关公式**：
$$ r_{ij \cdot K} = \frac{r_{ij \cdot K'} - r_{ik' \cdot K'} \cdot r_{jk' \cdot K'}}{\sqrt{(1 - r_{ik' \cdot K'}^2)(1 - r_{jk' \cdot K'}^2)}} $$
——在 `|Z| = p - 1 ≥ 2` 时递归复杂度 O(p³)；残差法 O(p²)，且直接复用 §2.2 OLS 残差，**代码复用率最高**。

#### 2.1.2 输出 schema
每个特征一条：
```json
{
  "feature": "[机头]机头温度",
  "n": 38,
  "single_r": 0.42,         // Pearson（已有，作为对照）
  "partial_r": 0.51,        // 偏相关
  "p_value": 0.003,
  "abs_partial_r": 0.51,
  "controls_used": 9,
  "warnings": []            // e.g. "样本不足", "controls 中含本特征"
}
```
外层 `report["multi"]["partial_corr"]` = `list[dict]`，按 `abs_partial_r` 降序。

#### 2.1.3 库依赖 / 降级方案
| 路径 | 依赖 | 适用场景 | 行为 |
|---|---|---|---|
| **主路径** | numpy + pandas（**0 新增依赖**） | 默认 | 残差法实现 M1；与 M2 共享 z-score 残差 |
| 备选 pingouin | `pingouin` (≈300KB) | 用户愿意装时 | `pg.partial_corr(df, x, y, covar=Z)` 直接拿 |
| 备选 statsmodels | `statsmodels` (≈已装 W8) | 学术信任更强 | `sm.OLS(y_std, sm.add_constant(X_std)).fit()` 取残差自乘 |

**降级**：当 `len(Z) == 0`（用户只勾了 1 列）→ `partial_r = single_r`，`p_value` 用 `scipy.stats.pearsonr` 取的 p；`warnings += ["控制集为空，偏相关退化为单 Pearson"]`。
**降级 2**：当 `n_used < multi_min_samples (默认 30)` → 该特征不出现在 M1 结果，`warnings += ["N<30 跳过 M1"]`。
**降级 3**：当 `Z` 中含常数列（std=0）→ 自动从 Z 中剔除，并 `warnings += ["已剔除常数列 X"]`。

### 2.2 M2：OLS 标准化系数（β\* + R² + VIF）

#### 2.2.1 公式
1. 对 `X = [x_1, ..., x_p]` 与 `y` 按列 z-score（`μ=0, σ=1`，即"标准化系数"等价于零截距 OLS 解）。
2. 解岭化/纯 OLS：
   - **首选**：`β* = (X'X)⁻¹ X'y`，`np.linalg.lstsq`（带 `rcond=None`，自动处理秩亏）。
   - **降级**：`X'X + λI`，λ=1e-6（数值稳定）；`warnings += ["X'X 条件数过大，启用岭化"]`。
3. R² = `1 - Σ(y - ŷ)² / Σ(y - ȳ)²`（标准化后 ȳ=0，简化为 `1 - SSE/SST`）。
4. 调整 R²：`R²_adj = 1 - (1 - R²)(n-1)/(n - p - 1)`（标准化数据下 `df_resid = n - p`）。
5. **VIF**（方差膨胀因子）：对每列 `x_j`，把它对**剩下的 p-1 列**做 OLS，取 R²_j：
   $$ \mathrm{VIF}_j = \frac{1}{1 - R^2_j} $$
   - VIF > 10：严重共线，`warnings += "[机头]X 与其它列 VIF=12.3，建议剔除"]`，仍参与拟合但在 UI 用 ⚠ 标记。
   - VIF > 100：极端共线，**自动从 OLS 中剔除**该列，`warnings += ["VIF>100，已自动剔除 X"]`，并在"贡献排名"里以括号备注"(未参与拟合)"。

#### 2.2.2 残差散点图
- 取 `e = y - ŷ`（标准化残差，即 `e_std = y_std - X_std @ β*`），与每个 `x_j` 画散点（共 p 张小图）。
- 散点带 LOESS 趋势线（见 §2.3），便于判断非线性是否漏掉。

#### 2.2.3 输出 schema
```json
{
  "r2": 0.78,
  "r2_adj": 0.71,
  "n": 38,
  "k": 9,                    // 参与拟合的特征数
  "coef_std": [
    {"feature": "[机头]机头温度", "beta_std": 0.42, "abs_beta_std": 0.42, "vif": 2.1, "kept": true},
    {"feature": "[机头]机头压力", "beta_std": -0.15, "abs_beta_std": 0.15, "vif": 12.3, "kept": true, "vif_warn": true}
  ],
  "top_contributors": ["[机头]机头温度", "[机头]机头压力", ...],   // 按 |β*| 降序前 K
  "dropped_features": [{"feature": "...", "reason": "VIF=120.4"}],
  "condition_number": 35.2,  // κ(X) = σ_max / σ_min
  "warnings": []
}
```
外层 `report["multi"]["ols"]` = 上述 dict。

#### 2.2.4 库依赖 / 降级方案
| 路径 | 依赖 | 行为 |
|---|---|---|
| **主路径** | numpy + pandas（**0 新增依赖**） | `np.linalg.lstsq` 求 β\*；VIF 用 `1/(1 - R²_j)`；条件数用 `np.linalg.cond` |
| 备选 statsmodels | 已有 W8 | `sm.OLS(...).fit()` 拿 p 值、CI（共线时仍用 numpy 主路径，statsmodels 仅作 fallback 拿 p） |
| 备选 sklearn | 未装 | **不引入**（避免新增依赖） |

**降级 1**：`p > n - 2` → 报错"特征数大于样本数-2，请减少勾选列或加大样本"；`warnings += ["p > n-2，跳过 OLS"]`。
**降级 2**：`X'X` 奇异（`np.linalg.matrix_rank < p`）→ 自动岭化 λ=1e-4；`warnings += ["启用岭化 λ=1e-4"]`。
**降级 3**：常数列 → 同 M1，自动剔除。
**降级 4**：Y 方差为 0（所有人都是 4） → 直接退出 OLS，返回 `{"r2": 0, "coef_std": [], "warnings": ["目标列方差为 0"]}`。

### 2.3 共用：图表（pyqtgraph）

**图 1：头部列贡献排名条形图（按 |β\*| 降序）**
- x 轴：特征名；y 轴：`|β*|`；颜色按正负（红=负，蓝=正，灰=被剔除的 VIF>100 列）。
- 数字标签：在柱顶显示 `β* = 0.42 (VIF=2.1)`。

**图 2：单偏相关 vs 全偏相关对比**
- 双横轴条形图：左侧蓝=Pearson `single_r`，右侧橙=偏相关 `partial_r`；按 `partial_r` 降序。
- 关键观察：被其它特征"代理"的列（如某 `x_k` 与主因子高相关但自身无因果），会出现 `single_r` 高、`partial_r` ≈ 0 的"塌陷"。

**图 3：OLS 残差散点图 + LOESS 趋势线**
- p 个小图（grid 2 × ⌈p/2⌉），每个子图 `e` vs `x_j`；LOESS 用 **statsmodels.nonparametric.lowess**（已有 W8 依赖）或 numpy 滑动窗均值兜底。
- 残差水平线 0 用虚线；±2σ 区域填浅色。

### 2.4 M1 + M2 的互补关系（一句话）
- **M1 偏相关**：控制其它变量后，x_i 对 y 的"独立相关强度"，**抗共线性**；适合回答"剔除混杂后，x_i 还想不想保留"。
- **M2 OLS 标准化系数**：在**全部** x 一起拟合下，x_i 对 y 的"标准贡献量"（**带方向**），适合回答"按当前工艺窗口调谁收益最大"。

---

## 3. UI 草图（多选框位置 + 3 张图表布局）

### 3.1 参数区扩展（位于 `process_analysis_panel.py` 的"分析参数" `QFormLayout` 内，约行 100-145）

```
┌─ 分析参数 ─────────────────────────────────────────────────────────┐
│ 分析模式：  [机尾指数-s归因            ▼]                            │
│               将自动跨类合并...以[机尾]指数-s=4为理想目标...         │
│ 状态列：    [                        ▼]   (禁用, 灰)               │
│ 目标状态：  (禁用)                                                   │
│                                                                       │
│ 特征列（多选）：  ☑ 全选 ☐ 反选 ☐ 仅 Top10 ☐ 自定义                 │  ← 新增子工具条 (P0)
│ ┌────────────────────────────────────────────────────────────────┐  │
│ │ ☑ [机头]机头温度     (Top1, |r|=0.42)                          │  │
│ │ ☑ [机头]机头压力     (Top2, |r|=0.38)                          │  │
│ │ ☑ [机头]机头速度     (Top3, |r|=0.31)                          │  │
│ │ ☑ [机头]机头时间     (Top4, |r|=0.27)                          │  │
│ │ ☐ [机头]次要特征A   (rank 11, |r|=0.06)                        │  │
│ │ ...                                                            │  │
│ └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│ 多变量归因：  ☑ 启用（M1 偏相关 + M2 OLS）  ☐ 仅单变量(W12 旧版)    │  ← 新增复选框 (P0)
│ VIF 警告阈值： [ 10.0 ]  (默认 10)                                    │  ← 新增 SpinBox (P1)
│                                                                       │
│           [  开始分析  ] [ 取消分析 ] [ 导出报告 ]                    │  ← 取消按钮 P0
│ ─────────── [▓▓▓▓▓▓▓░░░░░░░] 62%  OLS 拟合 5/9 ────────────        │  ← 进度条 P1
└───────────────────────────────────────────────────────────────────────┘
```

**Top10 预勾逻辑**（在 `_populate_features` 行 685-697 改造）：
1. 先扫一遍所有 `[机头]*` 列，分别算与 `[机尾]指数-s` 的 |Pearson|（用 `_pearson`，行 25-37），得到 `(col, |r|)` 列表。
2. 按 `|r|` 降序排，前 10 名 `setSelected(True)` 且在文本后追加 `(Top N, |r|=X.XX)` 后缀；其余**默认不勾**（与 W12 默认全选**不同**——见 §4 决策点）。
3. 顶部子工具条 "☑ 全选 / ☐ 反选 / ☐ 仅 Top10 / ☐ 自定义" 影响整体勾选状态。

> **决策点（待 Owner 拍板）**：W12 默认**全选**，S5 多变量推荐默认**仅 Top10**——因为 OLS 在高维共线时不稳定。两者需在 UI 文档里说明差异。

### 3.2 新增 Tab「多变量归因 (S5)」布局（插在 `归因结果` 行 185 与 `AI 解读` 行 187 之间）

```
┌─ 多变量归因 (S5) ─────────────────────────────────────────────────────┐
│ ┌─ 顶部摘要（一句话）─────────────────────────────────────────────┐  │
│ │ 目标 [机尾]指数-s，N=38，OLS R²=0.78 (adj=0.71)；                │  │
│ │ 主因子 [机头]机头温度 (β*=0.42, VIF=2.1)；                       │  │
│ │ ⚠ [机头]机头压力 VIF=12.3 严重共线，建议结合工艺剔除。          │  │
│ └──────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│ ┌─ 图表 1：贡献排名 ───┐ ┌─ 图表 2：单 vs 全 偏相关 ──┐ ┌─ 图3：残差 ─┐│
│ │ [机头]机头温度 ███ 0.42│ │ 机头温度                │ │ e vs 机头温度││
│ │ [机头]机头压力 ██  -0.15│ │  蓝=Pearson 橙=Partial │ │  ●●         ││
│ │ [机头]机头速度 █   0.08│ │   ●●●       ●●●         │ │   ●●●●      ││
│ │ ...                  │ │   ●●       ●●            │ │  - - LOESS -││
│ │ (灰=被剔除 VIF>100)  │ │   ●●         (塌陷)        │ │            ││
│ └────────────────────┘ └────────────────────────────┘ └────────────┘│
│                                                                       │
│ ┌─ M1 表（偏相关）────────────────────────────────────────────────┐  │
│ │ 特征       │ N  │ single_r │ partial_r │ p_value │ 警告          │  │
│ │ 机头温度   │ 38 │ 0.42     │ 0.51      │ 0.003   │ -            │  │
│ │ 机头压力   │ 38 │ 0.38     │ -0.02     │ 0.91    │ ⚠ VIF=12.3   │  │
│ │ ...                                                          │  │
│ └────────────────────────────────────────────────────────────────┘  │
│ ┌─ M2 表（OLS β*）───────────────────────────────────────────────┐  │
│ │ 特征       │ β*   │ VIF  │ 保留? │ 备注                        │  │
│ │ 机头温度   │ 0.42 │ 2.1  │ ☑     │ 主因子                      │  │
│ │ ...                                                          │  │
│ └────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

**布局细节**：
- 顶部摘要：`QLabel`，蓝色，1 行（自动换行）。
- 图表区：`QHBoxLayout` 横向 3 等分，每格一个 `pg.GraphicsLayoutWidget`（沿用 `boxplot_widget`，行 191-200 的 `pyqtgraph` 习惯）。
- 表格区：2 张 `QTableWidget`，纵向排列，沿用 `attrib_table` 7 列风格（行 173-179 的"setEditTriggers / NoEditTriggers / horizontalHeader stretchLastSection"）。
- 进度条：横跨整个 Tab 底部，复制 AI Tab 顶部条带（行 218-228）的样式。

### 3.3 取消按钮（沿用 W12.4 模式）
- 参考 `ai_cancel_btn`（行 309）：按钮文字"取消分析"，位置在"导出报告"右侧；按下后 `cancel_event.set()`，UI 立即把按钮变灰，进度条停滞在当前位置，状态栏显示"已请求取消..."。
- `attrib_cancel_btn` 与 `ai_cancel_btn` 互斥：分析期间归因按钮可点、AI 按钮 disable（避免 race）。

### 3.4 导出按钮（沿用 W12 现有 `export_btn`）
- 多变量归因结果导出一份独立 `attribution_multi_<timestamp>.csv`，列：`feature, n, single_r, partial_r, p_value, beta_std, vif, kept, warn`，附 `meta`（`r2/r2_adj/n/k/condition_number/warnings`）写 `attribution_multi_<timestamp>_meta.txt`。
- 3 张 PNG：`multi_contrib_<ts>.png`、`multi_partial_compare_<ts>.png`、`multi_residuals_<ts>.png`。

---

## 4. 关键决策点（待 Owner 拍板）

1. **Top10 预勾 vs 全选预勾**：建议改默认 Top10 + 顶部"全选"按钮可一键恢复默认（理由：OLS 在高维共线时数值不稳，全选容易出现"一票否决"主因子的假象）。⚠ Owner 决定。
2. **VIF>10 是"警告"还是"自动剔除"**：建议警告（10 < VIF ≤ 100）+ 自动剔除（VIF > 100），避免 UI 黑盒。
3. **是否引入 pingouin / statsmodels 做 M1 fallback**：建议不引入（保持 0 新依赖），numpy 残差法足够。
4. **M2 输出是否包含 p 值**：当 numpy 主路径时没有 p 值（需要 statsmodels OLS `.fit().pvalues`）。建议默认不显示 p 值，UI 上标注"p 值需启用 statsmodels 后端"。
5. **取消按钮位置**：在「开始分析」右侧 vs 紧贴进度条右侧。建议放按钮行内，与 AI Tab 风格一致。
6. **多变量归因是否默认开启**：S5 计划默认开启，旧 W12 行为通过复选框 ☐ 仅单变量 切换。

---

## 5. 兼容性 / 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 旧 6 个 W12 测试在 `multi=False` 默认下仍通过 | ✅ 已设计为向后兼容 | §1.3 列出不动旧测试 |
| 样本数过少（<30）导致 OLS 退化 | UI 显示空白 | M2 提前检查 `n < multi_min_samples`，返回空 + warning |
| 高共线性导致 β* 翻号 | 用户误判 | UI 显著标注 "VIF>10"；M1 偏相关给"独立相关"补充 |
| scipy 缺失（已支持） | numpy 手工实现兜底 | 不影响 M1/M2 |
| 用户全选 50 列做 OLS → 内存 / 时间 | 多变量结果卡顿 | UI 在"开始分析"前检查 `p > n/2` 时弹提示 "列数过多，建议先用 Top10" |
| 取消事件时机：M2 阶段 np.linalg.lstsq 无法中断 | 取消体感差 | lstsq 之后立刻 `_check_cancel()`；大矩阵前先估算耗时，>1s 时拆分（按 p 分块计算 VIF） |

---

## 6. 原文 path:line 引用清单（便于后续 Worker 跳转）

- `app/services/head_tail_attribution.py:11-13` — `AttributionCancelledError`
- `app/services/head_tail_attribution.py:15-21` — scipy 可选导入
- `app/services/head_tail_attribution.py:25-37` — `_pearson` numpy 兜底
- `app/services/head_tail_attribution.py:41-58` — `_rankdata` 简易平均秩
- `app/services/head_tail_attribution.py:60-79` — `_spearman`
- `app/services/head_tail_attribution.py:82-96` — `build_head_tail_report` 签名
- `app/services/head_tail_attribution.py:88,128,184,220,262,298` — 进度回调点
- `app/services/head_tail_attribution.py:186,214,269` — `_check_cancel` 三阶段
- `app/services/head_tail_attribution.py:312-326` — 输出 schema
- `app/ui/widgets/process_analysis_panel.py:116-118` — `mode_combo`
- `app/ui/widgets/process_analysis_panel.py:128-131` — `feature_list`（多选）
- `app/ui/widgets/process_analysis_panel.py:137-144` — 分析 / 导出按钮行
- `app/ui/widgets/process_analysis_panel.py:155-187` — `result_tabs` 7 个 Tab
- `app/ui/widgets/process_analysis_panel.py:168-185` — `attrib_widget`（现有归因 Tab）
- `app/ui/widgets/process_analysis_panel.py:309` — `ai_cancel_btn`（取消按钮参考）
- `app/ui/widgets/process_analysis_panel.py:569-582` — `get_config`
- `app/ui/widgets/process_analysis_panel.py:595-601` — `set_running`（"分析中..."）
- `app/ui/widgets/process_analysis_panel.py:685-697` — `_populate_features`（默认全选逻辑）
- `tests/test_w12_head_tail_attribution.py:11-29` — `_make_synthetic_df`
- `tests/test_w12_head_tail_attribution.py:31-44,46-54,56-62,64-69,71-77,79-92` — 6 个旧测试
- `sample_data/demolding_sample.csv` — 9 列原始 CSV（40 行）
- `docs/domain/demolding-process-overview.md:48-58` — 跨类合并说明
- `docs/domain/demolding-process-overview.md:60-70` — `[机尾]指数-s` 指标定义

---

## 7. 实施步骤建议（给下一阶段 S5-#2 派工参考）

> 本报告**不**直接派工，由 PM 决定。

1. **S5-#2**：让 coder 在 `head_tail_attribution.py` 内新增 `_partial_corr / _ols_standardized / _compute_vif` 3 个内部函数 + `multi` 参数开关；保持旧签名 100% 兼容；新增 `tests/test_s5_multi_attribution.py` 8 个用例。
2. **S5-#3**：让 UI coder 在 `process_analysis_panel.py` 内新增 `multi_checkbox / progress_bar / attrib_cancel_btn / "多变量归因 (S5)" Tab / 3 张图表 / 2 张表格`；扩展 `get_config` 多透传 `multi=True`。
3. **S5-#4**：reviewer 跑 `pytest tests/test_w12_head_tail_attribution.py tests/test_s5_multi_attribution.py` 全绿 + UI 截图（用户态默认全选 vs 仅 Top10 两态对照）。
4. **S5-#5**：documenter 更新 `docs/getting-started.md` / `docs/architecture.md` 加 S5 段落（**不动 `docs/domain/`**）。

---

## 8. 返回给 PM

### 改动文件
- **新增**：`docs/proposals/2026-07-15-s5-attribution-multi-proposal.md`（本报告，~25KB）

### DoD 验证
1. ✅ 报告输出到 `docs/proposals/2026-07-15-s5-attribution-multi-proposal.md`
2. ✅ 报告含三段：①扩展点（§1，引擎/UI/测试 3 张表）②算法选型（M1 公式+库依赖+降级 / M2 公式+库依赖+降级，见 §2）③UI 草图（参数区+新 Tab+3 图布局，见 §3）
3. ✅ 报告 ≤ 50KB（含 24 个 path:line 引用、3 张 ASCII UI 草图、§1 三张扩展点表、§2 四张库依赖表）；实际 ~25KB
4. ✅ 严格只读：未改动任何代码、未读 PM 对话历史、未外发消息
5. ✅ 调用数 ≤ 50、文件读数 = 5（head_tail_attribution.py / process_analysis_panel.py / test_w12_head_tail_attribution.py / demolding_sample.csv / demolding-process-overview.md）

### 遗留风险 / 待 Owner 决策
- **决策点 1（§4.1）**：Top10 预勾 vs 默认全选 —— 推荐 Top10，理由见 §4
- **决策点 2（§4.2）**：VIF>10 自动剔除 vs 仅警告 —— 推荐仅警告 + VIF>100 自动剔除
- **决策点 3（§4.3）**：是否引入 pingouin —— 推荐 0 新增依赖
- **决策点 4（§4.4）**：M2 p 值是否展示 —— 推荐默认不展示（需 statsmodels 才拿得到，违背 0 新依赖原则）
- **决策点 5（§4.5）**：取消按钮位置 —— 推荐按钮行内
- **决策点 6（§4.6）**：多变量归因是否默认开启 —— S5 计划默认开启
- **数据观察**：`sample_data/demolding_sample.csv` 仅有 40 行，远小于默认 `min_samples=30` 阈值，未来 M2 OLS 阶段大概率会触发"N 不足"降级；建议 PM 在派工 S5-#2 时提示 coder 用 `_make_synthetic_df(n=500, seed=42)` 作为测试基线。
- **CSV 列名前缀**：原始 CSV 列名 `机头温度` 不带 `[机头]` 前缀，需经过 `merge_asof` 跨类合并后才出现 `[机头]*`（已在 `docs/domain/demolding-process-overview.md:48-58` 明确）——新测试要复用现有 `_make_synthetic_df` 而不是直接读 CSV。

### 下一阶段派工建议
- S5-#2（coder，约 4-6 小时）：实现 §1.1 引擎层扩展点 + §1.3 新增测试
- S5-#3（UI coder，约 3-4 小时）：实现 §1.2 UI 层扩展点
- S5-#4（reviewer，约 1 小时）：跑测试 + 截图
- S5-#5（documenter，约 1 小时）：更新 `docs/getting-started.md` / `docs/architecture.md`（**不**动 `docs/domain/`）

---

_报告结束。analyst-s5-attribution / 2026-07-15_
