# 数据分析方法论

> 本文件记录项目中实现的各项数据分析方法的技术细节、算法参数与业务含义，基于 `app/services/` 中实际代码实现。

---

## 1. 描述统计

**入口**：`app/services/descriptive_service.py::calculate_descriptive_stats()`

对单列数值数据计算完整描述统计量：

| 指标 | 方法 | 说明 |
|------|------|------|
| 有效计数/缺失值 | `dropna()` | 区分 NULL 和非数值无效值 |
| 均值/中位数 | `mean()` / `median()` | 基本集中趋势 |
| 方差/标准差 | `var(ddof=1)` / `std(ddof=1)` | **样本无偏估计**（N-1 自由度） |
| 偏度 | `skew()` | 分布对称性，负偏=长尾向左 |
| 峰度 | `kurt()` | 峰态（基于 Fisher 定义，正态=0） |
| 变异系数 CV | `std/mean` | 相对离散程度 |
| 分位数 P1/P5/Q1/Q3/P95/P99 | `quantile()` | 9 个分位点覆盖全分布 |
| IQR 离群点 | Q1-1.5×IQR ~ Q3+1.5×IQR | 箱线图 outlier 识别 |

**分布可视化**：直方图（默认 30 bin）+ KDE（Silverman 规则带宽）+ 箱线图三合一。

---

## 2. 相关性分析

**入口**：`app/services/stats_service.py::correlation_matrix()`

### 2.1 Pearson 相关系数
- 衡量线性相关程度
- 输入：`DataFrame.corr(method='pearson')`

### 2.2 Spearman 秩相关系数
- 衡量单调相关关系（对非线性单调关系更鲁棒）
- 实现：优先使用 `scipy.stats.spearmanr`，缺失时回退到 numpy 手工实现（基于平均秩 + Pearson）
- 空值安全：自动 dropna 配对

### 2.3 散点矩阵
- 支持多变量两两散点图
- X 轴支持 datetime 自动识别（80% 可解析为日期）

---

## 3. 工艺窗口分析（单变量分状态窗口）

**入口**：`app/services/process_analysis.py::compute_univariate_windows()`

对每个 **状态 × 特征** 组合计算：

1. **基本统计**：count, mean, std, min, max, P1/P5/P25/P50/P75/P95/P99
2. **1σ 窗口**：[μ - σ, μ + σ] — 约覆盖 68% 数据（正态假设下）
3. **2σ 窗口**：[μ - 2σ, μ + 2σ] — 约覆盖 95% 数据
4. **可靠性标记**：当组内样本 < 30 时标记 `unreliable=True`

**进度支持**：每 20% 特征任务回传进度回调 `(pct, msg)`，支持 `cancel_event` 取消。

---

## 4. 规则挖掘（贪心分类树）

**入口**：`app/services/process_analysis.py::fit_greedy_tree()`

### 4.1 目标
对二分类（目标状态 vs 其他）递归贪心分裂，生成可读的判别规则。

### 4.2 算法参数
- **最大深度**：3（硬编码默认，可配置 `max_depth`）
- **最小叶节点样本**：30（`min_samples_leaf`）
- **分裂准则**：Gini 不纯度减少量（Gain）
- **候选阈值**：特征的 9 个分位点（10%/20%/.../90%）
- **停止条件**：达到 max_depth / 叶节点样本 < 2×min_samples / 纯度 >95% / 纯度 <5%

### 4.3 规则排序
使用 **F0.5 评分**（precision 权重更高）：
```
F0.5 = 1.25 × P × R / (0.25 × P + R)
Score = F0.5 × support^0.3
```
默认返回 Top 8 条规则。

### 4.4 输出格式
```python
{
    "conditions": [{"feature": "列名", "op": "<=", "threshold": 值}],
    "support": 覆盖样本数,
    "precision": 精确率,
    "recall": 召回率,
    "state": 目标状态
}
```

---

## 5. 特征重要性（ANOVA F 值）

**入口**：`app/services/process_analysis.py::compute_feature_importance()`

简化版 **单因素方差分析**，衡量特征对不同状态的区分能力：

```
F = (SSB / (k-1)) / (SSW / (n-k))
```

- SSB：组间平方和（组均值与总均值差异）
- SSW：组内平方和（组内偏离组均值）
- k：组数，n：总样本数
- 忽略 NaN，样本不足组跳过
- 常数列或组数 < 2 时 F=0
- 结果按 F 值降序排列，F 越大说明该特征对状态区分能力越强

---

## 6. 机头→机尾归因分析

**入口**：`app/services/head_tail_attribution.py::build_head_tail_report()`

针对 **指数-s** 的跨类归因，分析机头工艺参数对机尾质量的影响。

### 6.1 目标分布统计
- 均值、标准差、最小值、最大值
- 精确等于理想值(4.0)的占比
- 近理想值(|Δ|≤0.5)的占比
- 指数-s 值频次分布

### 6.2 相关系数表
对 Top N 特征计算 Pearson + Spearman 双相关系数：
- 优先使用 `scipy.stats.pearsonr` / `scipy.stats.spearmanr`
- 缺失 scipy 时回退到 numpy 手工实现
- 相关性方向：|r|<0.1 为"弱相关"，否则为正/负相关

### 6.3 分组统计（理想 vs 偏离）
- **理想组**：指数-s 在 3.5~4.5 范围内的样本
- **偏离组**：不在该范围内的样本
- 分别计算两组中特征列的 μ±σ 窗口
- 对比差异大小判断特征重要性

### 6.4 五分位分箱分析
- 使用 `pd.qcut` 将特征分为 5 个等频箱
- 每箱统计：目标均值、近理想率
- 样本不足 (< 5×n_buckets) 时跳过

### 6.5 阈值规则挖掘
对 Top 特征寻找最佳单阈值：
- 候选阈值：特征的 1/3 分位、中位数、2/3 分位
- 方向：≤ 或 >
- 评分：`near_ideal_rate × n^0.25`（兼顾命中率与样本量）
- 输出格式：`WHEN 特征 ≤/>X THEN 近理想率=Y%`

### 6.6 综合工艺窗口
Top 3 特征的理想样本 μ±σ 综合推荐范围。

---

## 7. 时间聚合

**入口**：`app/services/time_aggregation.py::aggregate_by_time()`

| 粒度 | 方法 | 说明 |
|------|------|------|
| 原始 | 不聚合 | 保留原始行 |
| 分钟 | `dt.floor("min")` | 分钟内取平均 |
| 小时 | `dt.floor("h")` | 小时内取平均 |
| 天 | `dt.floor("D")` | 天内取平均 |
| 周 | `dt.to_period("W-MON")` | 周一到周为周期 |
| 班次 | 自定义 `shift_label` | 早班 08:00-20:00，晚班 20:00-次日 08:00 |

---

## 8. 数据处理规则

**入口**：`app/services/data_processing.py::apply_rules()`

### 8.1 数值缩放（scale_by_factor）
- 使用 **float32 单精度** 乘法实现像素→mm 单位转换
- 列名自动添加 `(mm)` / `（mm）` 后缀
- 排除列模式：auto（自动跳过 datetime/文本/布尔列）、manual（手动指定）、none（不排除）
- 支持批量缩放（`column="*"` 对所有数值列缩放）
- 支持按类别批量缩放（`scale_datasets_by_category`），已缩放数据集默认跳过避免重复乘

### 8.2 行删除（delete_row）
基于条件掩码删除行，如排除异常值。

### 8.3 均值替换（replace_mean）
将满足条件的值替换为列均值。

### 8.4 支持的操作符
`lt` / `lte` / `gt` / `gte` / `eq` / `neq` / `is_null` / `not_null`

---

## 9. AI 解读集成

**入口**：`app/services/ai_client.py` + `app/services/ai_prompt.py`

### 9.1 供应商支持
- **OpenAI**：默认 `gpt-4o-mini`，`https://api.openai.com/v1`
- **DeepSeek**：`deepseek-chat`，`https://api.deepseek.com/v1`
- **自定义**：任意兼容 OpenAI 格式的 API

### 9.2 凭证优先级
QSettings > `ai_config.json`（TOML 格式） > codex 配置 > 环境变量 > 预设

### 9.3 数据安全
- **仅传聚合统计，不传原始行数据**（符合项目数据红线）
- `build_insight_prompt()`：工艺分析结果 → AI prompt
- `build_head_tail_prompt()`：机头→机尾归因报告 → AI prompt
- 超时默认 30s，可配置 5~300s，使用 watchdog 线程硬超时

### 9.4 AI 输出结构
工艺分析：稳定区工艺窗口总结 + 关键特征阈值 + 风险点 + 可执行建议
归因分析：核心结论(3句话) + Top3量化分析 + 推荐工艺窗口 + 风险点

---

## 10. 时间对齐（merge_asof）

**入口**：`app/services/process_analysis.py::align_by_time()`

将右表按时间就近匹配到左表：
- 使用 `pd.merge_asof`，`direction="nearest"`
- 容差：±1 秒（可配置 `tolerance_sec`）
- 右表同名列加 `_y` 后缀
- 用于跨类合并（机头数据与机尾数据的时间对齐）

---

## 11. 方法选择指南

| 分析需求 | 推荐方法 | 方法编号 |
|----------|---------|---------|
| 数据质量评估 | 描述统计 + 缺失值汇总 | §1, §2 |
| 参数间关系 | 相关性矩阵 + 散点图 | §2 |
| 各状态下参数分布 | 单变量工艺窗口 | §3 |
| 关键影响因素排序 | ANOVA F 值 | §5 |
| 状态判别规则 | 贪心分类树 | §4 |
| 机头→机尾传导分析 | 跨类归因报告 | §6 |
| 时序平滑展示 | 时间聚合 | §7 |
| 自动化解读 | AI 解读 | §9 |

---

_文档版本：V1.0 / 2026-07-14 / 基于代码实现整理_
