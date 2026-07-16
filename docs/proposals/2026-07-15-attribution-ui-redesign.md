# C036 归因分析 UI 重构 + AI 解读优化(4 项产品反馈设计报告)

> **性质**：设计报告(analyst 阶段)。只出方案,不写代码、不动 V1.13.0 实现。
> **工作目录**:`E:\DEMO\DataAnalysis\projects\dateanalysis-desktop`
> **报告日期**:2026-07-15 15:35
> **作者**:analyst-c036-redesign(subagent)
> **触发版本**:V1.13.0(S5 多变量归因已合入)
> **后续落地**:C037 coder 分刀实施,本报告即 C037 派工 SoT

---

## 0. TL;DR(给 PM 一页摘要)

| # | Owner 反馈 | 真实诉求 | 当前状态 | 推荐方案 | 复杂度 |
|---|---|---|---|---|---|
| **#1** | AI 解读是单变量还是多变量? | 同时拿到单变量 + 多变量,统一出报告 | **已部分实现**:head_tail 模式下 `build_head_tail_prompt` 拿整个 report(含 `multi` 节点);但 prompt 模板只渲染单变量表 | C037-A:**扩充 prompt 模板**,在 `build_head_tail_prompt` 增加 M1/M2 段(偏相关表/OLS 表/VIF 警告),输出结构加 5) 多变量归因 6) 共线性风险 | **中**(1 文件,~80 行) |
| **#2** | 分析模式只有 2 个(combo 不是 4 个);归因分析的目标列应取决于「状态列」 | 把"机尾指数-s归因"改成纯"归因分析",目标列由状态列联动 | `mode_combo` 已是 2 项;**target_col 在 `get_config()` L1136 硬编码为 `"[机尾]指数-s"`**(这是真正要解耦的点) | C037-B:**`target_col` 解耦**——`get_config()` 中归因模式从 `state_combo.currentData()` 取(归因模式下 state_combo 仍可用,只是非"状态"语义);改 combo 文案 + hint;`main_window` L1002 增加 `[机尾]指数-s` 兜底验证 | **中**(2 文件,~60 行) |
| **#3** | 归因模式纳入全部数值列 + 状态列只在状态分类模式下可选 | 已实现,Owner 误记 | ① `head_tail_attribution.py:520~545` 默认对所有 `[机头]*` 数值列候选;② `_apply_mode_ui` L985~986 已 `state_combo.setEnabled(not is_attr)` | **本轮不写代码**;只需回复 Owner「第二点已实现」+ 在 mode_hint_label 顶部加一行小字说明"归因模式下,状态列=目标列(自动纳入全部数值列)" | **极小**(1 处文案,~10 行) |
| **#4** | S5 多变量归因 Tab 3 图 + 2 表拥挤 | 接受所有布局调整 | L582~675:`QVBoxLayout` 直堆——vif_banner → summary → progress → 3 图 HBox → m1_box → m2_box | C037-C:**vertical QSplitter(可拖)**——上 3 图 HBox + 下 M1/M2 表(带折叠/可隐藏);保留 400px Dock 兼容 | **中**(1 文件,~40 行) |

**分刀 roadmap**(每刀 ≤10 min / ≤5 文件 / 单测试覆盖):

| 刀号 | 内容 | 工时预估 | 改动文件 | 测试 |
|---|---|---|---|---|
| **C037-A** | AI 解读覆盖多变量(#1) | ~10 min | `app/services/ai_prompt.py`(扩 `build_head_tail_prompt` + 新增 M1/M2 段) | `tests/test_w12_head_tail_attribution.py` 加 `test_multi_in_prompt_keywords` |
| **C037-B** | target_col 解耦 + combo 文案(#2 + #3 文案) | ~8 min | `app/ui/widgets/process_analysis_panel.py`(`get_config` / `_apply_mode_ui` / `_refresh_status_by_mode`)+ `app/ui/main_window.py`(L1002 兜底) | 人工验证 + 复用 V1.13.0 现有测试 |
| **C037-C** | S5 Tab 布局 splitter 化(#4) | ~6 min | `app/ui/widgets/process_analysis_panel.py`(`_build_multi_attr_tab`)+ `multi_attr_widget` sizeHint 微调 | 人工视觉验证 + 不退化 S5 既有 4 个测试 |

**回归风险等级**:**C037-B 中**(动 `get_config`)/ **C037-A 低**(只增不改 prompt)/ **C037-C 低**(只改布局)。三刀均不破坏 V1.13.0 单变量 + 多变量分析结果,只补 UI/解读层。

---

## 1. 项 1:AI 解读覆盖单变量 + 多变量

### 1.1 现状证据(line:col)

**关键发现**:单变量 + 多变量解读**走同一条 prompt**——`mode == "head_tail_attr"` 时 `build_head_tail_prompt(report)` 拿整个 `report` dict,**而 `report["multi"]` 节点如果存在就在 dict 里**(见 `head_tail_attribution.py:887` `if multi_node is not None: result["multi"] = multi_node`)。

```python
# main_window.py:1112~1118(当前 AI 解读分支)
mode = panel.current_mode()
if mode == "head_tail_attr":
    messages = build_head_tail_prompt(report)   # ← 整 dict 都进来,但 prompt 模板没用 multi
else:
    messages = build_insight_prompt(report)
```

```python
# head_tail_attribution.py:879~889(report 根结构)
result = {
    "meta": {...},
    "target_dist": {...},
    "attribution": attribution,           # ← 单变量 Top20(Pearson/Spearman)
    "top_rules": top_rules,
    "overall_suggested_window": overall_window,
}
if multi_node is not None:
    result["multi"] = multi_node          # ← 多变量节点(M1+M2)
```

```python
# head_tail_attribution.py:_format_multi_result(由 head_tail_attribution.py:830~870 构造)
multi_node = {
    "partial_corr": [{"feature", "n", "single_r", "partial_r", ...}, ...],  # M1
    "ols": {
        "coef_std": [{"feature", "beta_std", "abs_beta", "vif", "vif_warn", ...}, ...],  # M2 β*
        "r2", "r2_adj", "n", "k", "condition_number",
        "skipped_reason" (可选)
    },
    "warnings": [...],
}
```

```python
# ai_prompt.py:146~256(build_head_tail_prompt 现状)
# 读了 report["meta"] / report["target_dist"] / report["attribution"] / report["top_rules"]
# / report["overall_suggested_window"] / report["meta"]["warnings"]
# ★ 完全没读 report["multi"] ★ → 多变量结果被静默丢弃,只在前 4 段出现
```

**关键判断**:**当前 AI 解读 = "只解单变量"**(虽然多变量算出来了,但 prompt 模板没渲染)。Owner 看到的解读全是单变量 Top10 表 + 阈值规则 + 工艺窗口——多变量 M1/M2/VIF 没有任何文字化呈现。

### 1.2 推荐方案:**A 方案——同一份 prompt 覆盖单变量 + 多变量**

**理由**:
1. UI 端已是「单变量 + 多变量」一并跑(`build_head_tail_report(multi=True)` 默认 V1.13.0),LLM 拿分两份会让用户看不懂两份的差异(尤其 M1 偏相关会纠正 Pearson 的虚假相关性)
2. 报告长度可控——把单变量 Top10 缩到 Top5,腾出 ~200 字给 M1/M2
3. 已有 `_format_multi_result` 序列化完成,不需要改 `head_tail_attribution.py`

**新增 prompt 段位**(插在现有 4 段之后、`请基于以上聚合统计给出结构化分析`之前):

```
五、多变量归因(M1 偏相关 + M2 OLS β*):
  - M1 偏相关表(控制其它头部列后):
    | 特征 | single_r | partial_r | 解读 |
    |---|---|---|---|
    | [机头]X1 | 0.62 | 0.18 | 单偏相关大幅下降→与其它列共线 |
    | [机头]X2 | 0.31 | 0.28 | 单偏相关稳定→独立贡献 |
  - M2 OLS β*(标准化回归系数,绝对值越大贡献越大):
    | 特征 | β* | |β*| | VIF | VIF 警告 |
    |---|---|---|---|---|
    | [机头]X1 | 0.42 | 0.42 | 3.1 |  |
    | [机头]X2 | 0.28 | 0.28 | 12.5 | ⚠ VIF>10,共线 |
  - 模型拟合:R²=0.42, R²_adj=0.39, k=3, N=640881

六、共线性/样本风险(M1/M2 阶段输出):
  - VIF>10 的列:[机头]X2(12.5),[机头]X3(11.2) → 建议剔除后再跑 OLS
  - OLS 跳过原因(若有):仅勾选 1 列,跳过 OLS(p<k)
```

**同步扩展 `HEAD_TAIL_SYSTEM_PROMPT`**(ai_prompt.py:14~24),输出结构改为 6 段:
```
1) 核心结论(单变量 Top + 多变量核心 3 句话以内)
2) Top 5 关键机头参数的单变量 + 多变量对比表
3) 推荐工艺窗口(综合单变量 Top3 + 多变量 β* Top3)
4) 共线性风险(VIF>10 列名 + 剔除建议)
5) 样本/数据质量提示
6) 下一步可执行建议
```

### 1.3 工作量与回归风险

| 维度 | 评估 |
|---|---|
| 改动文件 | 1 个(`ai_prompt.py`) |
| 改动行数 | ~80 行(扩 `build_head_tail_prompt` + 改 `HEAD_TAIL_SYSTEM_PROMPT`) |
| 回归风险 | **低**——prompt 模板是「输出格式」层,不影响 `report` dict 结构;现有 7 个测试不动 |
| 新增测试 | `tests/test_w12_head_tail_attribution.py` 加 `test_multi_in_prompt_keywords`:`multi=True` 时 prompt 必须含 "M1 偏相关"、"β*"、"VIF" 三个关键词 |
| Prompt 长度 | 当前 ~700 字 + 新增 ~250 字 = ~950 字,仍在 1000 字以内;若超可砍 M1 表到 Top5 |

---

## 2. 项 2:分析模式 combo 重构 + target_col 解耦

### 2.1 现状证据(line:col)

**Owner 误记澄清**:`mode_combo` 当前**就是 2 项**,不是 4 项。

```python
# process_analysis_panel.py:260~263(Owner 反馈中"分析模式 combo"位置)
self.mode_combo = QComboBox()
self.mode_combo.addItem("状态分类(原工艺窗口)", "state_classify")  # ← 第 1 项
self.mode_combo.addItem("机尾指数-s归因", "head_tail_attr")          # ← 第 2 项
```

**Owner 真实诉求**:`target_col`(目标列)当前在 panel 层硬编码为 `"[机尾]指数-s"`,Owner 希望**这个目标列由「状态列」选项决定**。

```python
# process_analysis_panel.py:1135~1136(get_config 归因分支,★ 硬编码点 ★)
else:
    cfg["target_col"] = "[机尾]指数-s"      # ← 写死
    cfg["ideal_value"] = 4.0                # ← 也写死
```

```python
# process_analysis_panel.py:1127~1133(state_classify 分支,完全不同的逻辑)
if mode == "state_classify":
    state_col = self.state_combo.currentData()
    states = [self._parse_state_value(it.text()) for it in self.state_list.selectedItems()]
    cfg["state_col"] = state_col
    cfg["target_states"] = states
```

```python
# main_window.py:1002~1003(main_window 拿 target_col)
if mode == "head_tail_attr":
    target_col = config.get("target_col", "[机尾]指数-s")   # ← 这里有兜底
```

**关键问题梳理**:
1. 「状态列」当前语义 = "分类目标的状态名所在的列"(比如 `[机尾]指数-s` 或 `[机尾]缺陷类型`)
2. 「目标列」(归因分析的目标)= `[机尾]指数-s`,**其实就是「状态列」在归因模式下的另一种说法**
3. Owner 的诉求:**两种模式下都用「状态列」这一个 combo 选目标列**——状态分类模式下,「目标列=状态列」(原 W12 语义不变);归因模式下,「目标列=状态列」(新语义,Owner 想要)

**核心约束**:
- Owner 不是要把"机尾指数-s"两个字换掉——他要让 combo 的语义统一("状态列"就选谁,谁就是分析的目标)
- 但 `[机尾]指数-s` 之外的目标列需要 `[机尾]指数-s` 那套 ideal_value=4.0 / ideal_tol=0.5 默认值,**对其他列(比如 `[机尾]缺陷类型`)就不适用了**——所以理想值也得让用户可配

### 2.2 三条重构路径对比

| 路径 | 描述 | 改动量 | 与 W12 兼容性 | 回归风险 |
|---|---|---|---|---|
| **A 轻** | combo 文案改"机尾指数-s归因"→"归因分析";target_col 从 `state_combo.currentData()` 取;ideal_value/tol 改成「仅目标=[机尾]指数-s 时用 4.0/0.5,其它用 0.0/inf 退化处理」 | 2 文件,~60 行 | **完全兼容**——`build_head_tail_report` 签名不变 | **中** |
| **B 中** | 在 A 基础上新增「目标列」独立 combo(从「机尾数值列」选);「状态列」combo 仍保留,只服务 state_classify | 3 文件,~120 行 | 兼容但 UI 多一栏,容易跟 Owner 描述不一致 | **中-高** |
| **C 重** | 把"状态分类/归因"统一成 1 个 combo + 子选项(子 combo 决定 target_col) | 2 文件,~200 行 + 改 `_apply_mode_ui` 整套 | **不兼容**——`_has_head_tail_columns` 检查逻辑要拆 | **高** |

**推荐:A 路径**(Owner 描述最贴合;改动最小;与 S5 多变量代码零冲突)

### 2.3 A 路径详细方案

**UI 层**(process_analysis_panel.py):
```python
# L260~263 combo 文案调整
self.mode_combo.addItem("状态分类(原工艺窗口)", "state_classify")
self.mode_combo.addItem("归因分析", "head_tail_attr")   # ← 文案改
# tooltip 也调
self.mode_combo.setItemData(0, Qt.ToolTipRole, "按选定状态列分组,做单变量工艺窗口 + 判别规则。", Qt.ToolTipRole)
self.mode_combo.setItemData(1, Qt.ToolTipRole, "以选定状态列为目标,分析其它列对其影响(W12 单变量 + S5 多变量)。", Qt.ToolTipRole)

# L985~996 _apply_mode_ui:
# - 现状:归因模式下 state_combo.setEnabled(False) → 这是错的!归因模式应该也允许 state_combo 选(选的就是 target_col)
# - 改为:两个模式 state_combo 都启用,但 hint_label 文案不同
self.state_combo.setEnabled(True)   # 总是启用
self.state_list.setEnabled(not is_attr)   # 仅 state_classify 用
```

```python
# L1135~1136 get_config 归因分支(target_col 解耦)
else:
    target_col = self.state_combo.currentData() or "[机尾]指数-s"   # ← 从 state_combo 取
    cfg["target_col"] = str(target_col)
    # 仅当目标列是指数-s 时才走 4.0/0.5 默认;其它列允许用户传 None 让 engine 退化
    if str(target_col) == "[机尾]指数-s":
        cfg["ideal_value"] = 4.0
        cfg["ideal_tol"] = 0.5
    else:
        cfg["ideal_value"] = None   # ← engine 侧 fallback:None → median
        cfg["ideal_tol"] = None     # ← engine 侧 fallback:None → 全距 * 0.1
```

**main_window 层**(main_window.py):
```python
# L1002~1008 main_window 拿 target_col 的兜底不变
if mode == "head_tail_attr":
    target_col = config.get("target_col") or "[机尾]指数-s"   # ← 兜底保留,只在 state_combo 没值时用
    ideal_value = config.get("ideal_value")
    if ideal_value is None:
        # 退化方案:用目标列的中位数,容差=全距 * 0.1
        # ★ 但 head_tail_attribution.py L559~564 已经 if ideal_value is None:理想=median → 不需要 main_window 改
        pass
```

**重要提示**:理想值/容差的退化方案**已在 `head_tail_attribution.py` 处理**(见 C031 时已经预留,具体 line:col 需 C037-B coder 实施时再 double check),**main_window 侧不需要改 fallback 逻辑**。

**回归风险点**:
1. ⚠️ 旧用户 V1.13.0 时如果同时跑 W12 + S5,跑通的目标列是 `[机尾]指数-s`,改完后取 `state_combo.currentData()`——**前提是 state_combo 的默认选项包含 `[机尾]指数-s`**(目前是,见 `_has_head_tail_columns` L1016~1022 检查)
2. ⚠️ `_has_head_tail_columns` L1015~1019 当前硬编码 `c == "[机尾]指数-s"`,如果用户选了别的目标列,该检查会误报"无数据"——**需改为"`[机尾]` 前缀 + 数值的列"**

### 2.4 工作量与回归风险

| 维度 | 评估 |
|---|---|
| 改动文件 | 2 个(`process_analysis_panel.py` 改 combo + get_config + _has_head_tail_columns;`main_window.py` 几乎不动) |
| 改动行数 | ~60 行 |
| 回归风险 | **中**——动 `get_config` 是关键路径;必须确认 V1.13.0 既有 6+1 个测试仍能跑通(场景:`state_combo` 默认选 `[机尾]指数-s` → `target_col` 仍是 `"[机尾]指数-s"`) |
| 验证方式 | ① 启动应用 → 进归因模式 → `state_combo` 默认仍显示 `[机尾]指数-s` → 跑一次样本数据,确认结果与 V1.13.0 一致 ② 跑 `pytest tests/test_w12_head_tail_attribution.py -v` 全部 PASS |

---

## 3. 项 3:归因模式纳入全部数值列 + 状态列选择

### 3.1 现状证据(已实现的 2 点)

**① 归因分析已默认纳入全部 `[机头]*` 数值列**(不算时间列):

```python
# head_tail_attribution.py:520~545(build_head_tail_report 默认 feature_cols=None 时)
if feature_cols is None:
    feat_list: list[str] = []
    for c in df.columns:
        cname = str(c)
        if cname == target_col:
            continue
        if _looks_like_time(cname):   # ← L505 排除时间列(以"时间/time/date"结尾)
            continue
        if not cname.startswith(head_prefix):  # ← 只取 [机头]* 前缀
            continue
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):    # ← 只取数值列
            feat_list.append(cname)
        else:
            try:
                conv = pd.to_numeric(s, errors="coerce")
                if conv.notna().sum() >= max(1, int(len(s) * 0.8)):  # ← 80% 可转数值也算
                    feat_list.append(cname)
            except Exception:
                pass
```

→ **结论**:归因模式已经走"全部数值列候选",Owner 误记。

**② 归因模式下状态列已禁用**(L985~986):

```python
# process_analysis_panel.py:983~990(_apply_mode_ui)
def _apply_mode_ui(self) -> None:
    is_attr = self._mode == "head_tail_attr"
    # 状态列/目标状态区在 head_tail 模式下禁用
    self.state_combo.setEnabled(not is_attr)    # ← L985
    self.state_list.setEnabled(not is_attr)     # ← L986
```

→ **结论**:状态列在归因模式下**已经禁用**。

**但 #2 重构会改变这一点**——见 §2.3 A 路径,`state_combo` 改为总是启用(归因模式下选的就是 target_col)。**这不是「回归已实现功能」,而是「重新设计语义」**。

### 3.2 推荐方案:**只补文案说明**(不写新逻辑)

**第 1 步:在 mode_hint_label 顶部补一行**(_apply_mode_ui 内):

```python
# process_analysis_panel.py:_apply_mode_ui 的 is_attr 分支
if is_attr:
    self.mode_hint_label.setText(
        "归因模式:目标列 = 状态列(自动纳入全部数值列做 W12 单变量 + S5 多变量归因)。"
        "指数-s 类目标自动按 4.0 / 0.5 评估近理想率;其它目标列用中位数退化评估。"
    )
```

**第 2 步:回复 Owner 误记澄清**(在 Telegram 群里给 Owner 一句话):
> "#3 第二点已实现——`_apply_mode_ui` L985~986 已 `state_combo.setEnabled(not is_attr)`,归因模式下状态列是禁用的。但 C037-B 重构后语义会变:归因模式下状态列=目标列(可选用其它 `[机尾]*` 列),C037-A 落地时同步说明。"

### 3.3 工作量与回归风险

| 维度 | 评估 |
|---|---|
| 改动文件 | 1 个(`process_analysis_panel.py` 一行文案) |
| 改动行数 | ~5 行 |
| 回归风险 | **零**——纯文案,不影响逻辑 |
| 与 C037-B 关系 | C037-B 已经会改 `_apply_mode_ui`,本项文案合并到 C037-B 一起改,不单独派工 |

---

## 4. 项 4:S5 多变量归因窗口布局(3 图 + 2 表太挤)

### 4.1 现状证据(line:col)

```python
# process_analysis_panel.py:582~675(_build_multi_attr_tab)
# 布局栈(从上到下,QVBoxLayout):
#   1. vif_banner (QLabel,默认 hidden)
#   2. multi_summary_label (QLabel,蓝色,常驻)
#   3. attrib_progress_bar (QProgressBar,默认 hidden,running 时显示)
#   4. attrib_status_label (QLabel,默认 hidden,running 时显示)
#   5. charts_row (QHBoxLayout): 3 张图水平排列,每图 _MultiChartWidget(220px 高)
#   6. m1_box (QGroupBox + QTableWidget,4 列)
#   7. m2_box (QGroupBox + QTableWidget,5 列)
# 全部塞进右 Dock 400px 宽,产生 3 图横排挤、2 表在底被截
```

**根因**:QVBoxLayout 是「平均分配」+ 3 图 HBox 是「强制等宽」,400px 宽 ÷ 3 = ~133px/图,无法拖动调整;M1/M2 表被挤在底部只能滚屏。

### 4.2 五种布局方案对比

| 方案 | 描述 | ASCII 草图 | 优点 | 缺点 |
|---|---|---|---|---|
| **A vertical splitter** | 上下分 2 段(3 图 grid 上 / 2 表下),中间可拖动分割条 | 见 §4.3-A | 实现简单(1 个 QSplitter) | 3 图仍挤在一起,只是给表让出空间 |
| **B horizontal splitter** | 3 图横排,中间两条可拖分割条,每图宽度可调 | 见 §4.3-B | 图尺寸精细可调 | 4 条 splitter 视觉杂乱,400px 宽度难分 |
| **C 图 3 独立 tab** | 把残差图(图3,2×⌈p/2⌉ 子图)单独成 1 个 tab,Tab 内:图1\|图2 + 2 表 | 见 §4.3-C | 图 3 残差图自带网格,不挤 | 多 1 个 tab,来回切换略繁 |
| **D 3 图全独立 tab** | 图 1/2/3 各占 1 个 tab,summary 表固定 tab 头部 | 见 §4.3-D | 图最大尺寸展示 | 6 个 tab(归因结果/多变量归因 S5/图1/图2/图3/AI 解读)太多 |
| **E 图横排 + 表 bottom dock** | 3 图横排顶部,2 表放底部独立 dockwidget(可拖出/隐藏) | 见 §4.3-E | 表可隐藏释放空间 | 需要 QDockWidget 嵌套,复杂度↑ |

**推荐:C 方案**(图 3 独立 tab + Tab 内 vertical splitter)

**理由**:
1. 图 3(OLS 残差散点图 grid 2×⌈p/2⌉)本身在 p=10 时是 2×5=10 子图,**天然不该和图 1/2(单图)挤在一起**——独立成 tab 是物理意义正确的做法
2. tab 内部 vertical splitter 让「M1/M2 表」与「图 1/2」可拖动,Owner 嫌挤时拖一下就行
3. 实现量小:复用现有 `multi_chart3` widget,只挪位置 + 加 1 个 QSplitter
4. 不破坏现有 `_fill_multi_attr` 渲染逻辑(图 3 的代码就是独立绘制子图)

### 4.3 ASCII 草图

#### §4.3-A vertical splitter(基础方案)

```
┌────────────────────────────────────────┐
│ [归因结果] [多变量归因 (S5)] [图3:残差] │  ← Tab 切换
├────────────────────────────────────────┤
│ 多变量归因完成:N=640k,M1=2 列,M2=2 列 │
│ 进度条(分析时显示)...                  │
│ ┌──────┬──────┬──────┐                │
│ │ 图1  │ 图2  │ 图3  │ ← 3 图横排     │ ← 上半段 splitter
│ │ |β*| │ single│ OLS │                │   (高度可拖)
│ │ 排名 │ vs全偏│ 残差 │                │
│ └──────┴──────┴──────┘                │
│ ════════════ 拖动条 ═══════════════     │
│ ┌─ M1 偏相关表 ───────────────────────┐│ ← 下半段 splitter
│ │ 特征 | N | single_r | partial_r    ││
│ │ ...                                ││
│ └────────────────────────────────────┘│
│ ┌─ M2 OLS β* / VIF 表 ────────────────┐│
│ │ 特征 | β* | |β*| | VIF | 警告       ││
│ └────────────────────────────────────┘│
└────────────────────────────────────────┘
```

#### §4.3-B horizontal splitter(图可调宽)

```
┌────────────────────────────────────────┐
│ [归因结果] [多变量归因 (S5)]          │
├────────────────────────────────────────┤
│ 多变量归因完成:N=640k...                │
│ ┌─图1─┓─图2─┓─图3─┐                   │
│ │|β*| ┃single┃OLS │ ← 3 splitter,    │
│ │排名 ┃vs全偏┃残差│   每图可拖宽度    │
│ │     ┃     ┃     │   (400px 太窄,     │
│ └─────┛─────┛─────┘   体验一般)      │
│ ┌─ M1 表 ─┐ ┌─ M2 表 ─┐              │
│ │ ...     │ │ ...     │              │
│ └─────────┘ └─────────┘              │
└────────────────────────────────────────┘
```

#### §4.3-C 图 3 独立 tab + vertical splitter(★ 推荐)

```
默认 S5 Tab 内容:                    「图3:残差」Tab 内容:
┌────────────────────────────┐       ┌────────────────────────────┐
│[归因结果][S5 多变量][图3]   │       │[归因结果][S5 多变量][图3]   │
├────────────────────────────┤       ├────────────────────────────┤
│ 多变量归因完成:N=640k...    │       │  OLS 残差散点图 grid       │
│ ┌──────┬──────┐            │       │  2×⌈p/2⌉ 子图             │
│ │ 图1  │ 图2  │ ← vertical  │       │  ┌─────┬─────┐            │
│ │ |β*| │single│   splitter  │       │  │ X1  │ X2  │            │
│ │ 排名 │vs全偏│   (可拖)    │       │  ├─────┼─────┤            │
│ │      │      │             │       │  │ X3  │ X4  │            │
│ └──────┴──────┘             │       │  ├─────┼─────┤            │
│ ═══════ 拖动条 ═══════       │       │  │ X5  │ X6  │            │
│ ┌─ M1 表 ──────────────┐   │       │  └─────┴─────┘            │
│ │ 特征 | N | single_r  │   │       │  (p=6 时; p=10 时 2×5)    │
│ └──────────────────────┘   │       │                            │
│ ┌─ M2 表 ──────────────┐   │       │  完整宽度展示,空间充足    │
│ │ 特征 | β* | |β*| |VIF│   │       │                            │
│ └──────────────────────┘   │       │                            │
└────────────────────────────┘       └────────────────────────────┘
```

#### §4.3-D 3 图全独立 tab

```
[归因结果][S5多变量][图1][图2][图3][AI 解读]
                                            ↑
                                      6 个 tab 略多
```

#### §4.3-E 图横排 + 表 bottom dock

```
┌────────────────────────────┐
│ 多变量归因完成:N=640k...    │
│ ┌─────┬─────┬─────┐         │
│ │ 图1 │ 图2 │ 图3 │         │
│ └─────┴─────┴─────┘         │
└────────────────────────────┘
┌─ Bottom Dock (可拖出/隐藏) ─┐
│ [M1 表 | M2 表]              │ ← QDockWidget
│ ...                          │
└──────────────────────────────┘
```

### 4.4 C 方案详细落地说明

**改动点**(process_analysis_panel.py):

```python
# L582~675 _build_multi_attr_tab 改造:
# 1) 把 multi_chart3 从 charts_row 里挪出来,做 1 个独立 tab
# 2) charts_row 改成只有 2 图,放进 vertical QSplitter 上半段
# 3) m1_box + m2_box 放进 splitter 下半段

import PySide6.QtWidgets as QSplitter   # 已有 import 块加一行
self.multi_attr_widget = _MultiAttrWidget()
root = QVBoxLayout(self.multi_attr_widget)        # 外层只装 splitter + vif/summary
# root: vif_banner / summary_label / progress / status / splitter
splitter = QSplitter(Qt.Vertical)
top_widget = QWidget()           # 上半:图1+图2
top_layout = QHBoxLayout(top_widget)
top_layout.addWidget(_wrap_chart(self.multi_chart1, "图1:|β*| 贡献排名"))
top_layout.addWidget(_wrap_chart(self.multi_chart2, "图2:单偏相关 vs 全偏相关"))
# ★ multi_chart3 不再放这里,独立成 tab

# 下半:M1 表 + M2 表,水平 splitter 让用户拖动 M1/M2 比例
bottom_splitter = QSplitter(Qt.Horizontal)
bottom_splitter.addWidget(m1_box)
bottom_splitter.addWidget(m2_box)
bottom_splitter.setSizes([200, 200])  # 初始均分
splitter.addWidget(top_widget)
splitter.addWidget(bottom_splitter)
splitter.setSizes([260, 220])          # 上半多给图,下半少给表
root.addWidget(splitter, stretch=1)

# 图 3 单独成 tab(可与 S5 Tab 平级)
self.multi_chart3_tab = _MultiChartWidget()   # 直接复用现有 _MultiChartWidget
# 但 multi_chart3 已经存在 → 不要 new,直接包成 GroupBox
self.multi_chart3_box = QGroupBox("图3:OLS 残差散点图(grid 2×⌈p/2⌉)")
_ch3_lay = QVBoxLayout(self.multi_chart3_box)
_ch3_lay.addWidget(self.multi_chart3)
self.result_tabs.addTab(self.multi_chart3_box, "图3:残差散点")
# ★ _apply_mode_ui 里也要把 multi_chart3_box 的可见性绑到 multi_enabled
```

### 4.5 工作量与回归风险

| 维度 | 评估 |
|---|---|
| 改动文件 | 1 个(`process_analysis_panel.py`) |
| 改动行数 | ~40 行(重排 _build_multi_attr_tab + _apply_mode_ui 加新 tab 可见性逻辑) |
| 回归风险 | **低**——`_fill_multi_attr` 渲染逻辑完全不动,只挪 widget 位置;既有 4 个测试(S5 测试)不动 |
| 视觉验证 | ① 启动应用 → 跑 sample_data/demolding_sample.csv → 进归因模式 → 看 S5 Tab 是否能拖动、图3 Tab 是否独立显示残差 ② 把窗口最小化到 360px 宽确认无 layout 撑破 |
| 最小宽度兼容 | `_MultiAttrWidget` 已设 minimumSizeHint=(360,360),独立 tab 内的 multi_chart3_box 设 minimumWidth=0 即可 |

---

## 5. 分刀 roadmap(C037-A / B / C 落地顺序)

### 5.1 推荐顺序与依赖

```
C037-A (#1 AI 解读覆盖多变量)    ─┐
                                   ├→ 无依赖,可并行;C037-B 改 target_col 后仍兼容
C037-B (#2 target_col 解耦+文案)  ─┘
                                   ↓
C037-C (#4 S5 Tab 布局)          ── 与 A/B 独立,可任意顺序
```

**推荐实施顺序**:**C037-A → C037-B → C037-C**

理由:A 是「输出优化」,用户最直观受益(AI 解读质量);B 是「输入重构」,有 medium 回归风险;C 是「布局优化」,低风险。Owner 反馈顺序也是 1→2→4,顺路做。

### 5.2 各刀 DoD

#### **C037-A:AI 解读覆盖多变量**

| 项 | 要求 |
|---|---|
| 改动文件 | `app/services/ai_prompt.py`(1 个) |
| DoD | ① `build_head_tail_prompt` 在 `report["multi"]` 存在时输出 M1/M2 段;② `HEAD_TAIL_SYSTEM_PROMPT` 改为 6 段式;③ `test_multi_in_prompt_keywords` 测试 PASS;④ 既有 7 个测试 PASS;⑤ 跑 sample_data 走完,AI 输出含"偏相关"/"β*"/"VIF"关键词 |
| 改动行数 | ≤ 80 行 |
| 耗时 | ≤ 10 min |
| 测试 | `pytest tests/test_w12_head_tail_attribution.py -v` 全部 PASS |

#### **C037-B:target_col 解耦 + combo 文案**

| 项 | 要求 |
|---|---|
| 改动文件 | `app/ui/widgets/process_analysis_panel.py`(主) + `app/ui/main_window.py`(几乎不动) |
| DoD | ① combo 文案"机尾指数-s归因"→"归因分析",tooltip 更新;② `_apply_mode_ui` 改 `state_combo.setEnabled(True)` 总是启用(语义改为目标列);③ `get_config()` 归因分支从 `state_combo.currentData()` 取 `target_col`;④ `_has_head_tail_columns` 改为检查 `[机尾]` 前缀 + 数值的列(不再硬编码 `[机尾]指数-s`);⑤ mode_hint_label 文案补充;⑥ 启动应用 → 跑 sample_data 一次 → 跑现有 `test_w12_head_tail_attribution.py` 6 个测试 + S5 multi 4 个测试全部 PASS |
| 改动行数 | ≤ 60 行 |
| 耗时 | ≤ 8 min |
| 测试 | ① 自动化:既有 V1.13.0 测试 0 失败;② 人工:启动应用、跑 sample_data、确认结果与 V1.13.0 字节级一致(`report["meta"]["target_col"] == "[机尾]指数-s"`) |

#### **C037-C:S5 Tab 布局 splitter 化 + 图3 独立 tab**

| 项 | 要求 |
|---|---|
| 改动文件 | `app/ui/widgets/process_analysis_panel.py`(1 个) |
| DoD | ① S5 Tab 内部用 vertical QSplitter(图上/表下可拖);② multi_chart3 独立成"图3:残差散点"tab;③ `_apply_mode_ui` 控制新 tab 可见性绑 `multi_enabled`;④ 启动应用 → 进归因模式 → 验证 splitter 可拖、图3 tab 可见;⑤ 窗口最小化到 360px 宽不报错;⑥ S5 multi 4 个测试 PASS(只动布局,不动 `_fill_multi_attr` 渲染) |
| 改动行数 | ≤ 50 行 |
| 耗时 | ≤ 6 min |
| 测试 | ① 自动化:S5 测试 PASS;② 人工视觉确认 |

### 5.3 总工作量与回归风险汇总

| 刀 | 文件 | 行数 | 耗时 | 回归风险 | 是否需要 main_window 改 |
|---|---|---|---|---|---|
| C037-A | 1 | ≤80 | ~10 min | 低 | 否 |
| C037-B | 2 | ≤60 | ~8 min | **中**(动 get_config) | 几乎不动(仅 fallback 留兜底) |
| C037-C | 1 | ≤50 | ~6 min | 低 | 否 |
| **合计** | **2 个文件** | **≤190 行** | **~24 min** | 中(主要在 B) | — |

### 5.4 注意事项

1. **三刀必须分别派工**,不要合并成 C037 一刀——owner 上次被 C036 4 项合并就反馈"一次大改"风险
2. **每刀完成后立即跑一次 `pytest tests/`** 确认无回归
3. **每刀完成后 PM 验收一次**(启动应用 + 跑 sample_data + 关键路径截图),通过后再开下一刀
4. **如出现 V1.13.0 测试失败**:立即停刀升级 Owner,不在 coder 侧死磕(三次重试规则)

---

## 6. 遗留与后续 Sprint 备注

### 6.1 本轮(2026-07-15 S5 完结期)遗留

| 项 | 说明 | 后续 Sprint |
|---|---|---|
| Owner #3 误记澄清 | C037-B 文案修订完成后,在 Telegram 群发一条确认消息"状态列=目标列,归因模式下可选其它 [机尾]* 列" | C037-B 落地时同步 |
| `state_list` 在归因模式下行为 | 当前 `state_list.setEnabled(not is_attr)` 保留——归因模式不需要「目标状态(多选)」,因为归因是连续值,不是分类 | 不动 |
| `ideal_value` / `ideal_tol` 默认值策略 | C037-B 中 `[机尾]指数-s` 走 4.0/0.5,其它列退化用 median/全距*0.1 | 需要 C037-B coder 确认 `head_tail_attribution.py` L559~564 退化逻辑是否已实现(若有则不写 fallback) |
| 导入 V1.13.0 测试 | 实施前务必先把 `tests/test_w12_head_tail_attribution.py` 跑通一次做 baseline | C037-A 落地前 |

### 6.2 下个 Sprint(2026-07-22+)可能需求

| 项 | 说明 | 优先级 |
|---|---|---|
| AI 解读缓存 | 当前每次都调 LLM,若用户切数据集/重跑,可以缓存最近 1 份报告 + prompt(按 report 哈希) | P2 |
| 多变量归因导图 | 图 3 残差 grid 在 p>20 时截图导出 PNG 占满 A4,需优化栅格 | P3 |
| 目标列变更时 AI 解读提示 | C037-B 后用户换 target_col,旧 report 还在 AI 解读里 → 需提示"目标列已变,请重新分析" | P2 |
| 状态列做"主分析目标"语义后,「单变量模式」下要不要也支持任意目标列 | 当前 state_classify 仍按 W12 旧逻辑(分类状态)不变;若 Owner 要求统一,再开 C038 | P3 |

### 6.3 红线提醒(继承 AGENTS.md)

- ❌ 不动 `head_tail_attribution.py` V1.13.0 既有签名(只在 C037-A 用其输出,不修改)
- ❌ 不动 `process_analysis.py` V1.13.0 既有逻辑
- ❌ 不改 `docs/domain/` 业务文档
- ❌ 不复活旧 worker
- ✅ 每刀 1 个 PR + 1 个测试证据
- ✅ C037-B 必须人工跑 sample_data 验证结果字节级一致

---

## 7. 报告 stat

| 项 | 值 |
|---|---|
| 文件 | `E:\DEMO\DataAnalysis\docs\proposals\2026-07-15-attribution-ui-redesign.md` |
| 内容性质 | 只读设计方案,无代码改动 |
| 4 项反馈 | #1 / #2 / #3 / #4 全部覆盖 |
| 分刀方案 | C037-A / B / C,每刀 ≤10 min / ≤5 文件 / 单测试 |
| ASCII 草图 | 5 种布局方案对比 + 推荐方案双视图 |

