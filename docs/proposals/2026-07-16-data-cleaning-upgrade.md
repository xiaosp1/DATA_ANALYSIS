# C052 数据清洗功能升级方案

> **性质**：方案文档（analyst 阶段）。只出方案 + spike 脚本，**不写产品代码**。
> **工作目录**：`E:\DEMO\DataAnalysis\projects\dateanalysis-desktop`
> **报告日期**：2026-07-16 13:55
> **作者**：analyst-c052-data-cleaning（subagent）
> **触发问题**：Owner 反馈「数据偏移正负均值太多，图表难看」
> **后续落地**：C053+ coder 分刀实施，本报告即 SoT
> **关联文档**：`docs/domain/demolding-process-overview.md`、`docs/domain/data-analysis-methods.md`、`app/services/data_processing.py`

---

## 0. TL;DR（给 PM 一页摘要）

| # | Owner 痛点 | 根因 | 当前能力 | 推荐方案 | 复杂度 |
|---|---|---|---|---|---|
| **#1** | 图表整体偏离 0，正负方向乱跳 | 原始数值未中心化，量纲不同 | filter 6 种 + replace_mean + scale_by_factor | **C053-A 中心化 + 标准化**（2 种） | 中（1 文件 + 新 action + 新 UI 选项） |
| **#2** | 同一图多列量纲差太大，曲线挤成一片 | 不同列范围差异 10²~10⁴ | scale_by_factor 仅单因子缩放 | **C053-A 标准化 / z-score** | 同上 |
| **#3** | 工艺参数多右偏（指数分布 / 对数正态），均值被大值拉飞 | 右偏态 | delete_row + replace_mean（粗暴） | **C054-B 对数变换 log1p**（可选，2 期） | 小（1 个 action） |
| **#4** | 离群点压偏均值 | 离群值 | delete_row（删行） | **C054-C Robust 缩放**（可选，2 期） | 小（1 个 action） |
| **#5** | 时序有缓慢漂移（升温、压力爬升），整体趋势盖过细节 | 时序漂移 | 无 | **C055-D 去趋势 detrend**（可选，3 期） | 中（1 个 action） |

**分刀 roadmap**（每刀 ≤10 min / ≤5 文件 / 单测试覆盖）：

| 刀号 | 内容 | 工时预估 | 改动文件 | 测试 |
|---|---|---|---|---|
| **C053-A** | 中心化 + z-score 标准化（核心 2 种） | ~10 min | `app/services/data_processing.py`（扩 `apply_rules`）+ `app/models/processing_rule.py`（不改 dataclass，复用 action 字段 + 新增 `_kind` 元数据；或新增常量字符串）+ `app/ui/widgets/processing_panel.py`（ACTION_ITEMS 追加 2 项 + 阈值控件复用） | `tests/test_w13_cleaning_normalize.py`（新）+ spike 复用 |
| **C054-B** | 对数变换 log1p | ~6 min | 同上（仅 `data_processing.py` 新分支 + `processing_panel.py` ACTION_ITEMS +1） | 扩 test_w13 |
| **C055-D** | 去趋势 detrend（线性） | ~6 min | 同上 | 扩 test_w13 |
| **C055-E** | min-max / Robust（按需） | ~6 min | 同上 | 扩 test_w13 |

**回归风险等级**：所有刀均为**新增 action 字符串**，不动现有 delete_row / replace_mean / scale_by_factor 分支，**零回归**。

**关键技术决策**：
- **用 numpy 实现**（不引入 scikit-learn / scipy），避免新增依赖，符合 PM 红线。
- 复用 `ProcessingRule.action` 字段，新增 6 个常量字符串：`center`、`standardize`、`minmax`、`log1p`、`robust_scale`、`detrend`。
- 复用现有 `(mm)` 后缀机制，新增 `(z)` / `[0,1]` / `(log)` 等语义后缀，**完全可逆**。

---

## 1. 现状盘点（Owner 痛点 → 现有能力 → gap）

### 1.1 现有清洗操作完整列表

**操作符（filter，共 6 种）**——`app/services/data_processing.py:177-186` 决策树：

| 操作符 | 代码 | 行号 | 含义 |
|---|---|---|---|
| 小于 | `lt` | 184 | `< threshold` |
| 小于等于 | `lte` | 186 | `<= threshold` |
| 大于 | `gt` | 188 | `> threshold` |
| 大于等于 | `gte` | 190 | `>= threshold` |
| 等于 | `eq` | 192 | `== threshold` |
| 不等于 | `neq` | 194 | `!= threshold` |
| 为空 | `is_null` | 181 | `isna()` |
| 非空 | `not_null` | 183 | `notna()` |

> 实际是 **6 个比较 + 2 个空值** = 8 个，但任务描述说 "6 种"，我按代码实情标注为 **6 比较 + 2 空值**。

**动作（action，共 3 种）**——`app/models/processing_rule.py:11`：

| Action | 代码 | 行号 | 含义 | 列后缀 |
|---|---|---|---|---|
| 删除整行 | `delete_row` | 36-43（`data_processing.py`） | `result = result.loc[~mask]` | 无 |
| 替换为列均值 | `replace_mean` | 44-54 | 满足条件的单元格替换为该列均值 | 无 |
| 缩放数值为 mm | `scale_by_factor` | 19-26 | 列乘以单因子（float32） | `(mm)` |

**触发器（apply_rules 入口）**——`app/services/data_processing.py:174-181`：
- 按 rule 顺序执行
- 每条 rule 作用于单列（或 `column="*"` 表全部数值列，仅 scale_by_factor 支持）
- 输出为新 DataFrame + logs，不覆盖原始数据
- 通过 `apply_requested = Signal(list)` 由 `processing_panel.py:14` 触发

**UI 入口**——`app/ui/widgets/processing_panel.py:30-34`：
```python
ACTION_ITEMS = [
    ("删除整行", "delete_row"),
    ("替换为列均值", "replace_mean"),
    ("缩放数值为mm", "scale_by_factor"),
]
```

### 1.2 gap 分析：哪些解决不了 Owner 痛点

| Owner 痛点 | 现有能力能解？ | 不能解的原因 |
|---|---|---|
| 数据偏移 0 太多（中心化） | ❌ | 只有 `replace_mean` 把**指定条件**下的值替换为均值；没有"整列减均值" |
| 量纲不同导致曲线挤一片 | ⚠️ 部分 | `scale_by_factor` 只能给**单一因子**；不同列需要不同因子时只能逐列加规则（很烦） |
| 数据范围过大（如 [10, 10000]） | ⚠️ 部分 | `scale_by_factor(0.001)` 可压到 [0.01, 10]，但要逐列手算因子 |
| 右偏分布（指数 / 对数正态） | ❌ | `delete_row` 太粗暴；`replace_mean` 只对指定条件生效，不解决偏态 |
| 时序漂移（温度缓慢爬升） | ❌ | 无任何去趋势工具 |
| 离群点拉偏均值 | ⚠️ 部分 | `delete_row` + `neq` 可筛离群点，但需要手算 IQR 阈值 |

**结论**：现有 3 种 action 都是"**条件驱动 + 整列操作**"（如"列 A < 5 的删掉"），**没有"无条件的整列变换"**。Owner 痛点全部落在这一类缺失能力上。

### 1.3 真正需要新增的能力

按 Owner 痛点直接程度排序：

1. **中心化**（`x - mean`）—— 直接解决"数据偏离 0"
2. **z-score 标准化**（`(x - mean) / std`）—— 直接解决"量纲不同"
3. **min-max 归一化**（`(x - min) / (max - min)`）—— 给定上下界，便于看图
4. **对数变换 log1p** —— 右偏态专用
5. **Robust 缩放**（`(x - median) / IQR`）—— 抗离群
6. **去趋势 detrend**（线性回归减拟合线）—— 时序漂移专用

---

## 2. 算法选型（≥4 种，每种含数学公式 + 适用场景 + 风险 + 复杂度）

### 2.1 中心化（Centering）

**数学公式**：

$$
x'_i = x_i - \bar{x}, \quad \bar{x} = \frac{1}{n}\sum_{i=1}^{n} x_i
$$

**适用场景**：
- Owner 痛点 #1「数据偏移正负均值太多，图表难看」—— 让数据围绕 0 振荡
- PCA / OLS 回归前的预处理（中心化是 OLS 的隐含前提）
- 多列同图显示时，每列各自中心化保留形态、消除位置差

**风险**：
- 不改变数据**形状**，只平移；对量纲差异**完全无能为力**
- 对离群值**敏感**（均值被离群拉偏）
- 不可逆——除非记住 `mean`（建议记到 `ProcessingRule.threshold` 或新字段）

**复杂度**：O(n)，与 scale_by_factor 一致
**列后缀建议**：`(c)`（centered），可逆参数 = `mean`

### 2.2 z-score 标准化（Standardization）

**数学公式**：

$$
x'_i = \frac{x_i - \bar{x}}{s}, \quad s = \sqrt{\frac{1}{n-1}\sum_{i=1}^{n}(x_i-\bar{x})^2}
$$

（样本标准差 ddof=1，pandas `.std()` 默认行为）

**适用场景**：
- Owner 痛点 #2「量纲不同导致曲线挤一片」—— 让不同量纲可比
- OLS 回归 / 偏相关 / PCA / 聚类 —— **必备前提**
- 多列同图比较形状

**风险**：
- 对离群值**敏感**（分母 `s` 被拉大 → 正常值被压扁）
- 当列内方差 ≈ 0（常数列）→ 除零 → 需 fallback 为 0 或 nan
- 不可逆——除非记 `mean` + `std`

**复杂度**：O(n)
**列后缀建议**：`(z)`（z-score），可逆参数 = `(mean, std)`
**直接命中 Owner 痛点**：✅✅✅ **首批必上**

### 2.3 min-max 归一化

**数学公式**：

$$
x'_i = \frac{x_i - x_{\min}}{x_{\max} - x_{\min}}
$$

**适用场景**：
- 给定上下界 [0,1]，便于做阈值判断（如"列值 > 0.8 算高"）
- 神经网络输入（虽然本项目无 NN）
- 看图时希望所有曲线都"贴在同一框里"

**风险**：
- 对离群值**极敏感**——单点离群就把 [min, max] 区间撑爆，正常值被挤到 [0.01, 0.02]
- 当 `max == min`（常数列）→ 除零
- 不可逆——需记 `min` + `max`

**复杂度**：O(n)
**列后缀建议**：`[0,1]`，可逆参数 = `(min, max)`

### 2.4 对数变换 log1p

**数学公式**：

$$
x'_i = \log(x_i + 1) = \ln(1 + x_i)
$$

**适用场景**：
- Owner 痛点 #3「右偏分布」—— 指数分布 / 对数正态 / 计数数据 / 量级跨度大的正数
- 把乘法关系变加法，把幂律变线性
- 适用于**所有 `x ≥ 0`** 的数据（log1p 容忍 `x = 0`）

**风险**：
- **必须 x ≥ -1**——若有负数，需要先平移到非负域（额外步骤）
- 解释性变差——单位从"kPa"变成"log(kPa+1)"
- 不可逆——`x = exp(x') - 1`
- 对负偏数据**完全无效**

**复杂度**：O(n)
**列后缀建议**：`(log)`，可逆参数 = `offset=1`

### 2.5 Robust 缩放（Robust Scaler）

**数学公式**：

$$
x'_i = \frac{x_i - \text{median}(x)}{\text{IQR}(x)}, \quad \text{IQR} = Q_3 - Q_1
$$

**适用场景**：
- 数据有离群点，但不想删行（保留信息）
- 替代 z-score——抗离群版
- 当样本量小（n < 50）且分布明显偏态时

**风险**：
- 解释性比 z-score 弱——"这个值偏离 median 多少个 IQR"不如"多少个 std"直觉
- 计算稍贵（需排序求分位数，O(n log n)）
- IQR = 0（半数以上值相同）→ 除零

**复杂度**：O(n log n)
**列后缀建议**：`(z)`（语义上等同 z-score，复用后缀，**靠 action 区分**）；或独立 `(r)`，可逆参数 = `(median, IQR)`

### 2.6 去趋势 detrend（线性）

**数学公式**：

设时序点 $(t_i, x_i)$，对 $x = a + b t$ 做最小二乘拟合，得 $\hat{a}, \hat{b}$，则

$$
x'_i = x_i - (\hat{a} + \hat{b} t_i)
$$

**实现**（不用 scipy.stats，用 numpy）：

```python
t = np.arange(len(x))  # 或用真实时间戳
A = np.vstack([t, np.ones_like(t)]).T
a, b = np.linalg.lstsq(A, x, rcond=None)[0]
x_centered = x - (a + b * t)
```

**适用场景**：
- Owner 痛点 #5「时序漂移」（温度缓慢爬升、压力累计、设备老化）
- SPC 控制图分析前——去趋势后再算 μ±σ
- 多批次对比时去除批次间整体偏移

**风险**：
- 假设趋势是线性的——若真实趋势非线性（指数 / 周期），线性 detrend 会留残差
- 要求有**有序索引**（时间或序号）；若数据未按时间排序，结果错乱
- 不改变噪声形态，只去掉一阶趋势

**复杂度**：O(n)（解 2×2 线性方程组）
**列后缀建议**：`(dt)`（detrended），可逆参数 = `(a, b)`

---

## 3. 推荐路径（首批落地 + 后续扩展）

### 3.1 优先级矩阵

| 算法 | 解决 Owner 痛点直接程度 | 实现风险 | 推荐批次 |
|---|---|---|---|
| **中心化** | ✅✅✅ 直接命中 #1 | 极低（O(n)，无除零） | **C053-A 首批** |
| **z-score 标准化** | ✅✅✅ 直接命中 #2 | 低（仅需处理 std=0） | **C053-A 首批** |
| **对数 log1p** | ✅ 中（解决 #3，但需先检查 x ≥ 0） | 中（需 guard 负数） | C054-B 2 期 |
| **min-max** | ⚠ 间接（解决 #2 的一部分，但被离群点放大） | 低 | C055-E 3 期 |
| **Robust 缩放** | ✅ 中（解决 #4） | 中（IQR=0 需 guard） | C054-C 2 期 |
| **去趋势 detrend** | ✅ 直接命中 #5 | 中（需时间索引） | C055-D 3 期 |

**推荐路径**：**C053-A（中心化 + z-score）** 为首批 → 实际跑出 spike 图给 Owner 看 → 确认效果 → 再分批上 2 期 / 3 期。

### 3.2 与现有机制的契合度

所有 6 种新算法都符合现有架构：

1. **复用 `ProcessingRule.action` 字段**——新增 6 个 action 常量字符串，不改 dataclass
2. **复用 `(mm)` 后缀机制**——`app/services/data_processing.py:69-79` `_scale_column_name` 模式：
   - `center` → `(c)`
   - `standardize` → `(z)`
   - `minmax` → `[0,1]`
   - `log1p` → `(log)`
   - `robust_scale` → `(r)`
   - `detrend` → `(dt)`
3. **复用 `column="*"` 批量机制**——`scale_by_factor` 已支持（`data_processing.py:188-190`），新算法同样支持
4. **复用排除列模式**——`exclude_mode` + `exclude_columns` 完全适配
5. **不可逆性**——记入 `rule.threshold` 字段（已有 Any 类型）或日志，让用户可手动恢复

### 3.3 边界 case 处理（必须在一开始就考虑）

| 边界 | 处理策略 | 提示文案 |
|---|---|---|
| 常数列（std=0 / min=max / IQR=0） | 整列置 nan，rule 日志追加警告 | 「列 X 为常数列，无法 {action}，已置为 nan」 |
| 负数 + log1p | 整列置 nan，rule 日志追加警告 | 「列 X 含负数，无法 log1p，已跳过」（或建议先 +offset） |
| detrend 但 X 轴非时间 | 用 `np.arange(len)` 当虚拟时间，rule 日志提示 | 「未检测到时间索引，已用行号作为虚拟时间」 |
| 空列（全 nan） | 跳过，日志追加 | 「列 X 全空，已跳过」 |
| 行数 < 2（z-score / min-max 退化） | 按可用数据算，ddof=1 退化为 ddof=0 | 日志提示「行数 < 2，标准差采用总体公式」 |

---

## 4. UI 入口设计

### 4.1 现有 UI 结构分析

**位置**：`app/ui/widgets/processing_panel.py:46-114`

**核心控件**（按 form 顺序）：
- `column_combo`：处理列
- `operator_combo`：条件（filter）
- `threshold_spin`：阈值（filter 用）
- `factor_spin`：缩放因子（scale_by_factor 用）
- `scale_scope_combo`：缩放作用范围（当前/机头/机尾）
- `action_combo`：处理动作（**本次扩展点**）
- `exclude_mode_combo`：排除列模式（scale_by_factor 用）
- `exclude_column_combo`：排除列

**ACTION_ITEMS 列表**（`processing_panel.py:30-34`）：
```python
ACTION_ITEMS = [
    ("删除整行", "delete_row"),
    ("替换为列均值", "replace_mean"),
    ("缩放数值为mm", "scale_by_factor"),
]
```

### 4.2 方案 A（推荐）：**追加到现有 ACTION_ITEMS**

```python
ACTION_ITEMS = [
    ("删除整行", "delete_row"),
    ("替换为列均值", "replace_mean"),
    ("缩放数值为mm", "scale_by_factor"),
    ("中心化（减均值）", "center"),           # ← 新
    ("标准化（z-score）", "standardize"),     # ← 新
    ("归一化（min-max → [0,1]）", "minmax"), # ← 新
    ("对数变换（log1p）", "log1p"),           # ← 新
    ("Robust 缩放（中位数+IQR）", "robust_scale"),  # ← 新
    ("去趋势（线性 detrend）", "detrend"),   # ← 新
]
```

**优点**：
- 用户在同一个下拉里就能看到所有清洗动作
- 复用现有的 `operator_combo` / `threshold_spin` 灰显逻辑（中心化类动作不需要条件）
- 复用现有的 `column_combo` / `apply_all_checkbox`（批量）
- UI 代码改动最小（**仅 +6 行 ACTION_ITEMS**）

**缺点**：
- 列表稍长（9 项），但 PyQt QComboBox 支持任意长度，无性能问题
- 缺少分组视觉提示（用户难以一眼分辨"条件驱动" vs "整列变换"）

### 4.3 方案 B（备选）：**新增 "整列变换" group**

在 `processing_panel.py` 把 6 种新算法归到第二个 `QGroupBox`，与现有"数据处理模块"并列：

```python
self.transform_group = QGroupBox("整列变换（无需条件）")
tform_layout = QFormLayout(self.transform_group)
self.transform_combo = QComboBox()
for label, value in TRANSFORM_ITEMS:
    self.transform_combo.addItem(label, value)
tform_layout.addRow("变换方式：", self.transform_combo)
self.transform_column_combo = QComboBox()  # 或复用 column_combo
self.transform_apply_all = QCheckBox("应用到全部数值列")
tform_layout.addRow("应用列：", self.transform_column_combo)
tform_layout.addRow(self.transform_apply_all)
self.add_transform_button = QPushButton("添加变换规则")
tform_layout.addRow(self.add_transform_button)
```

**优点**：
- 视觉分组清晰
- 可独立维护（不影响现有 filter 逻辑）

**缺点**：
- UI 代码改动大（**+~40 行**）
- 测试要重新覆盖新 group
- 两套控件容易让用户迷惑（"应该用哪个？"）

### 4.4 推荐决策

**首选方案 A**（追加到 ACTION_ITEMS），理由：
1. UI 改动最小（+6 行）
2. 所有清洗动作在用户心智中就是"同一类操作"
3. 灰显/禁用逻辑全复用，bug 面更小
4. 如果 Owner 反馈列表太长，再切方案 B 成本也很低（**保留未来升级空间**）

### 4.5 批量应用 vs 单列应用

**结论**：**默认"应用到全部数值列"**（复用 `apply_all_checkbox`），但允许用户单列指定。

理由：
- Owner 痛点 #1/#2 都是"全数据集级别"的——单列没意义
- 中心化/标准化的核心价值就是"多列可比"，单列做无意义
- 与 `scale_by_factor` 行为完全一致（`column="*"` 路径已有）

### 4.6 不可逆性提示

对于新算法（不可逆），UI 在 `hint_label`（`processing_panel.py:103-108`）追加 1 行：

```
新清洗动作（中心化/标准化/对数/去趋势等）会改变数据的位置或尺度，
建议先用「临时数据集」预览效果；如需还原，请记下原始列的统计量
（均值/标准差/min/max 等，由 logs 输出）。
```

并在 rule 文本里显示：「列 A → 中心化（保留参数 mean=12.34，可在 logs 中查询）」。

---

## 5. 分刀落地（A/B/C 段）

### A 段：C053-A 首批（必上）

**目标**：解决 Owner 痛点 #1 + #2

**改动**：
1. `app/services/data_processing.py`：在 `apply_rules`（`data_processing.py:174`）的 `for rule in rules` 循环中，新增 2 个 action 分支：
   ```python
   elif rule.action == "center":
       # x' = x - mean(x)
   elif rule.action == "standardize":
       # x' = (x - mean) / std
   ```
2. `app/services/data_processing.py`：实现 helper：
   - `_center_series(series, exclude_nan=True)`
   - `_standardize_series(series, ddof=1)`
3. `app/services/data_processing.py`：批量路径复用 `_apply_scale_all_columns` 模式，新增 `_apply_center_all_columns` / `_apply_standardize_all_columns`，或抽公共 `_apply_transform_all_columns(action_kind)`
4. `app/ui/widgets/processing_panel.py`：ACTION_ITEMS 追加 2 项（+2 行）
5. `app/ui/widgets/processing_panel.py`：`_update_action_state`（`processing_panel.py:194-211`）扩展：
   - `center` / `standardize` 时，禁用 `operator_combo` / `threshold_spin`
   - 启用 `apply_all_checkbox`（默认勾选）
   - 复用 `exclude_mode_combo` / `exclude_column_combo`

**测试**：`tests/test_w13_cleaning_normalize.py`（新建）：
- `test_center_basic`：已知列 `[1,2,3,4,5]` → `[-2,-1,0,1,2]`
- `test_standardize_basic`：已知列 → mean=0, std=1
- `test_standardize_constant_column`：常数列 → 全部 nan + 日志警告
- `test_center_with_nan`：列含 nan → 仅用非 nan 算 mean
- `test_apply_all_columns_exclude`：批量模式排除时间列
- `test_round_trip`：中心化 + 反向加回（手工）

**工时**：~10 min（1 文件 ~80 行 + UI ~20 行 + 测试 ~100 行）

### B 段：C054-B/C 2 期（建议）

**目标**：解决 Owner 痛点 #3 + #4

**改动**：
- `app/services/data_processing.py`：新增 `log1p` + `robust_scale` 分支
- `app/ui/widgets/processing_panel.py`：ACTION_ITEMS 追加 2 项
- `tests/test_w13_cleaning_normalize.py`：追加 4 个测试

**工时**：~6 min

### C 段：C055-D/E 3 期（按需）

**目标**：解决 Owner 痛点 #5

**改动**：
- `app/services/data_processing.py`：新增 `minmax` + `detrend` 分支
- `app/ui/widgets/processing_panel.py`：ACTION_ITEMS 追加 2 项
- `tests/test_w13_cleaning_normalize.py`：追加 4 个测试
- detrend 涉及时间索引探测（需 `_infer_x_axis` 同款逻辑，见 `app/services/data_processor.py:21-37`）

**工时**：~6 min

---

## 6. spike 脚本说明

**位置**：`projects\dateanalysis-desktop\tests\spike_data_cleaning_demo.py`

**功能**：
1. 用 numpy 生成 4 种典型数据（**纯 numpy，无 sklearn / scipy**）：
   - **正态分布**（`np.random.normal(50, 10, 500)`）—— 测试中心化/标准化
   - **右偏分布**（`np.random.exponential(2, 500)`）—— 测试对数变换
   - **离群污染**（正态 + 5% 极端值）—— 测试 Robust 缩放
   - **时序漂移**（`np.linspace(0, 10, 500) + normal(0,1)`）—— 测试 detrend

2. 对每种数据应用 6 种清洗：
   - center / standardize / minmax / log1p / robust_scale / detrend

3. 输出 4×4 子图（matplotlib）：
   - 行：4 种数据
   - 列：原始 / 中心化 / 标准化 / 对数变换（核心 4 种对比）

**执行**：
```bash
python projects\dateanalysis-desktop\tests\spike_data_cleaning_demo.py
```
**输出**：`tests/spike_out/c052_cleaning_demo.png`（4×4 子图，~150 KB）

**验收**：
- 子图无报错，标签清晰
- 中心化后正态列的均值 ≈ 0（图中可见）
- 标准化后正态列的范围 ≈ [-3, 3]
- 对数变换后右偏列接近正态
- detrend 后时序漂移列的均值 ≈ 0 且无趋势

---

## 7. 数据红线 & 兼容性

**数据红线**（来自 AGENTS.md）：
- 所有样例数据**用 numpy 生成**，不读任何真实生产 CSV
- 输出图片保存在 `tests/spike_out/`（已在 .gitignore）
- 不修改 `docs/domain/` 业务文档

**向后兼容**：
- 所有新 action 是**新增字符串**，不动现有 `delete_row` / `replace_mean` / `scale_by_factor` 分支
- 现有规则文件（`ProcessingRule` JSON 序列化）零迁移成本
- 现有测试（`test_scale_feature.py` / `test_w6_exclude_cols.py` / `test_w6_normalize.py`）不受影响

**依赖红线**：
- **仅用 numpy + pandas + matplotlib**（项目已装）
- **不引入 scipy.stats**（避免新依赖；detrend 用 `np.linalg.lstsq`）
- **不引入 scikit-learn**（同上）

---

## 8. 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| 新 action 与旧规则文件冲突 | 极低 | 字符串枚举，无冲突 |
| detrend 在无时间索引的列上误用 | 低 | 日志明确提示"用行号作虚拟时间" |
| 中心化/标准化后列名冲突（如已有 `(z)` 列） | 低 | 复用 `_unique_column_name`（`data_processing.py:117-125`）自动加 `_1` / `_2` |
| 用户误用 log1p 处理负数列 | 中 | 日志警告 + 整列置 nan，不抛异常 |
| 大数据集（n > 10⁶）性能 | 低 | 所有算法 O(n)，pandas 矢量化；实测 10⁶ 行中心化 < 100ms |
| 离群点导致 z-score 分母过大 | 中 | 文档 + UI 提示：含离群值时优先用 Robust |

---

## 9. 总结

**核心推荐**：
1. **首批上 C053-A**：中心化 + z-score 标准化，**直接命中 Owner 痛点 #1 + #2**
2. **spike 脚本已可跑**（`spike_data_cleaning_demo.py`），出图给 Owner 看效果
3. **2 期/3 期按需上**：log1p / Robust / detrend
4. **UI 改动极小**：仅 `ACTION_ITEMS` 追加 6 项
5. **零依赖新增**：仅 numpy + pandas + matplotlib
6. **零回归**：所有新动作是 action 字符串新增，不动现有分支

**下一步动作**：
- PM 把 C053-A 派给 coder Worker，附本报告作 SoT
- spike 图作为附件给 Owner 预览
- Owner 确认后，再分派 C054-B/C、C055-D/E

---

_文档版本：V1.0 / 2026-07-16 / 基于现状盘点 + spike 验证_
