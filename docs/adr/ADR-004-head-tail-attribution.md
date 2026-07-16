# ADR-004 — 归因分析方案（机头→机尾指数-s）

- 日期：2026-07-13
- 状态：Accepted
- 决策者：尘醒（Owner）/ dataanalysis-pm

## 背景
脱模工艺的核心问题是：机头参数（如脱模力、温度、速度等）如何影响机尾指数-s（脱模质量指标，=4 为完美脱模）。需要一套系统化的归因分析引擎，从跨类合并后的数据中自动挖掘关键参数及其理想窗口。

设计要求：
1. 输入是跨类合并数据集（列名带 `[机头]`/`[机尾]` 前缀）；
2. 自动识别目标列（`[机尾]指数-s`）和特征列（`[机头]*` 数值列）；
3. 计算相关系数（Pearson + Spearman），按 |Spearman| 排序；
4. 对 Top 特征进行分组统计（理想值时 vs 偏离时）+ 五分位分箱；
5. 挖掘单特征阈值规则（WHEN 特征≤X THEN 近理想率=Y%）；
6. 综合建议一个工艺窗口；
7. 支持进度上报和取消（大数据量计算时间长）。

## 选项

### 选项 A：基于 pandas 手工实现
- 手工实现 Pearson/Spearman 相关、分箱、分组统计
- 优点：无额外依赖，完全可控
- 缺点：代码量大，需自己处理边界情况

### 选项 B：依赖 sklearn/statsmodels
- 使用 sklearn 的 `correlation` 和 `DecisionTreeRegressor`
- 优点：工业级稳定
- 缺点：引入新依赖；规则挖掘需要额外适配

### 选项 C：scipy 可选 + numpy fallback（选定）
- 优先使用 `scipy.stats.pearsonr` / `spearmanr`（若 scipy 可用）
- 缺失 scipy 时 fallback 到 numpy 手工实现
- 优点：最小依赖；回归友好；边界处理灵活
- 缺点：手工实现需充分测试

## 决定
采用 **scipy 可选 + numpy fallback + 纯函数设计**。

### D1. 归因模式
系统支持三种归因模式，由 `build_head_tail_report` 的 `mode` 参数控制：

| 模式 | 说明 | 使用场景 |
|------|------|----------|
| `tail_only` | 仅机尾单变量统计 | 未跨类合并，只做机尾分布分析 |
| `head_tail` | 机头→机尾归因（当前实现） | 跨类合并后，分析机头参数对机尾的影响 |
| `head_only` | 仅机头统计 | 机头数据自身分析 |

### D2. 相关系数计算
- **Pearson**：衡量线性相关程度，对异常值敏感
- **Spearman**：基于秩次，衡量单调相关，对非线性/异常值鲁棒
- **选择依据**：归因排序使用 `|Spearman|`（工艺关系多为单调非线性），展示时同时显示两种系数
- **实现**：优先 `scipy.stats.pearsonr` / `spearmanr`；fallback 到 numpy 手工实现 `_pearson` / `_spearman`
- **方向判定**：`|r| < 0.1` → "弱相关"；否则 "正相关"/"负相关"

### D3. 分箱与分组统计
对每个 Top 特征：
1. 计算 `near_ideal_mask = (target - ideal_value).abs() <= ideal_tol`
2. 理想组（near_ideal=True）vs 偏离组（near_ideal=False）分别计算 μ ± σ
3. 五分位分箱（`pd.qcut`）：将特征值分为 5 等份，每个箱计算目标均值和近理想率
4. 样本不足时（`< n_buckets * 5`）跳过分箱，仅输出警告

### D4. 规则挖掘
对 Top N 特征的每个：
- 尝试 3 个分位切分点（1/3 分位、中位数、2/3 分位）
- 每个切分点尝试 `≤` 和 `>` 两个方向
- 过滤条件：`n >= max(10, min_samples // 3)`
- 评分函数：`score = pct_near_ideal * (n ^ 0.25)`（兼顾近理想率和样本量）
- 返回 Top N 规则，格式：`WHEN 特征 ≤/> X THEN 近理想率=Y%`

### D5. 进度与取消
- `report_progress(pct, msg)` 回调：5%→100% 多阶段上报
  - 5%: "准备数据"
  - 20%: "计算相关系数"（每处理一个特征递增）
  - 55%: "分组统计与分箱"
  - 78%: "规则挖掘"
  - 92%: "综合工艺窗口"
  - 100%: "完成"
- `cancel_event`：各阶段前检查 `cancel_event.is_set()`，抛出 `AttributionCancelledError`

### D6. AI 集成
- 归因报告通过 `build_head_tail_prompt(report)` 构造 prompt
- 传入仅聚合统计（相关系数表、分箱结果、规则、工艺窗口），**不传原始行数据**
- 系统 prompt 限定输出格式：核心结论 + Top 3 量化分析 + 推荐窗口 + 风险提示

## 后果

### 正面
- **纯函数引擎**：`head_tail_attribution.py` 不依赖 Qt，可在 pytest 中完全测试
- **scipy 可选**：`_HAS_SCIPY` 标志，缺失时 numpy fallback，保证无 scipy 环境可用
- **可解释输出**：相关系数 + 分组统计 + 规则 + 工艺窗口，四维度解读
- **进度/取消**：长时间计算时用户可取消，progress_cb 不阻塞
- **AI 安全**：仅传聚合统计，不传原始行数据

### 负面
- **规则挖掘简单**：仅单特征阈值（未做多特征组合规则），复杂度低于完整决策树
- **分箱固定 5 等份**：不支持自定义分箱数（后续可做参数化）
- **ideal_value 硬编码默认 4.0**：虽可配置但 UI 层未暴露调节入口

## 验收
- `tests/test_w12_head_tail_attribution.py`（121 行）：归因引擎核心功能
- `build_head_tail_prompt()` 确保 prompt 仅包含聚合统计字段
