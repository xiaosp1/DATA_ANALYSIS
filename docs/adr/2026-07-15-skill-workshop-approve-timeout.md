# ADR-007 — 2026-07-15 工具/流程异常三合一登记

- 日期：2026-07-15
- 状态：已记录（事件 A 应急处置已闭环 / 事件 B 处置已闭环但根因待查 / 事件 C 教训已落地 PM 工作记忆）
- 决策者：dataanalysis-pm（事件记录） / 尘醒（Owner，工具 bug followup 需 Owner 转发工具维护方）

> **ADR 性质说明**：本 ADR 偏离传统 ADR 模板（选项对比→决策）格式，因为涉及的不是单一决策选择，而是 **3 个独立但相关的工具/流程异常的结构化登记**。保留 ADR 的核心结构（背景 / 决定 / 后果）但用「事件 A/B/C + 共同根因」替代「选项 A/B/C」。未来 PM / Owner 翻查本 ADR 时，可快速定位凭证、缓解措施与未决事项。

---

## 背景

2026-07-15 在 OpenClaw 多 Agent 协作基础设施层发生 3 个独立的工具/流程异常。它们各自触发条件不同，但都暴露了基础设施稳定性边界：

- **事件 A**：`skill_workshop apply` 工具未识别 Owner 在 PM 群渠道发出的 approve 字符串，4 次重试均 "Approval timed out"
- **事件 B**：PM 工作空间根目录 7 个元数据文件被外部进程从 LF 改为 CRLF 行尾（污染源未明）
- **事件 C**：Sprint 5 / Issue #3 子代理在写入 1746 行单文件第 3 图中段停摆，4.5h 无产出

3 个事件独立发生、各自处置，但合并登记是为避免事件散落在 CHANGELOG / STATUS / COMMITMENTS 三处文件难以追溯。事件 A 已闭环（应急通道 C 落盘 skill），事件 B 处置已闭环但根因待 C030 investigator 查证，事件 C 教训已落地 PM 派工 SOP。

---

## 事件 A：skill_workshop apply 工具 bug（严重）

- **时间**：2026-07-15 08:30 ~ 08:50（apply 4 次重试窗口约 20 分钟）
- **症状**：Owner 在 PM 工作群（Telegram chat_id `-5312459332`）明确发出 `"approve pm-spawn-worker apply"` 消息 + PM 已 `mkdir` 目标目录 `E:\DEMO\DataAnalysis\skills\pm-spawn-worker\`，skill_workshop apply 连续 4 次返回 `"Approval timed out"`。
- **根因（Main 侧 C-20260715-18 报告）**：
  1. `skill_workshop apply` 工具对 Owner 在 OpenClaw Windows Tray 渠道发出的 approve 字符串未走通工具侧审批门（审批门解析缺陷）；
  2. agent 域过滤问题——`proposals.json` 健康但从非 origin agent profile 调 `list/inspect` 找不到该 pending proposal。
- **影响**：Sprint 5 派工通路阻塞——PM 无法正式 install `pm-spawn-worker` skill 模板。
- **应急措施（Main 走应急通道 C）**：
  - `write` 工具直接落盘 `E:\DEMO\DataAnalysis\skills\pm-spawn-worker\SKILL.md` (6260B) — 见 CHANGELOG.md `[meta] 2026-07-15 08:49` 段
  - 登记 `C:\Users\m00053733\.openclaw\skill-workshop\proposals\pm-spawn-worker-20260715-9f46368b78\applied.json` (1219B, `appliedBy=agent:main:main`, `appliedVia=emergency-channel-c`)
- **凭证**：
  - `C:\Users\m00053733\.openclaw\skill-workshop\proposals\pm-spawn-worker-20260715-9f46368b78\applied.json:1`（schema = `openclaw.skill-workshop.applied.v1`）
  - `C:\Users\m00053733\.openclaw\skill-workshop\proposals\pm-spawn-worker-20260715-9f46368b78\applied.json:4`（`appliedBy=agent:main:main`）
  - `C:\Users\m00053733\.openclaw\skill-workshop\proposals\pm-spawn-worker-20260715-9f46368b78\applied.json:5`（`appliedVia=emergency-channel-c`）
  - `C:\Users\m00053733\.openclaw\skill-workshop\proposals\pm-spawn-worker-20260715-9f46368b78\applied.json:20-24`（followup.toolBugReport 明示两处 bug）
  - `E:\DEMO\DataAnalysis\skills\pm-spawn-worker\SKILL.md` 6260B / 2026-07-15 08:49:40
  - `E:\DEMO\DataAnalysis\CHANGELOG.md` `[meta] 2026-07-15 08:49` 段（应急通道 C 触发条件登记）
- **教训**：
  - PM spawn 模板不依赖 `skill_workshop apply` 状态——Sprint 5 派工通路在 apply 失败情况下也能工作（C026/C028 派工单已验证独立可用）
  - 应急通道 C（`write` 工具直落盘 + `applied.json` 登记）作为工具 bug 期间的可用 fallback
- **未决**：
  - 工具 bug 修复（已记入 `applied.json:20-24` `followup.toolBugReport`，需 Owner 转工具维护方）
  - agent 域过滤问题：origin agent profile 与跨 agent 调用的 list/inspect 行为差异需规范

---

## 事件 B：PM 根 meta 文件 CRLF 污染源未明（中）

- **时间**：2026-07-15 12:41 发现，12:43 修复（约 2 分钟闭环处置，根因未明）
- **症状**：PM 工作空间根目录 7 个文件（`scripts/pm_turn_precheck.py` / `TODO.md` / `STATUS.md` / `ROADMAP.md` / `README.md` / `CHANGELOG.md` / `COMMITMENTS.md`）行尾被外部写入从 LF 改为 CRLF，precheck `ENCODING_SANITY` FAIL。
- **修复**：
  - 批量 `\r\n` → `\n` + 去孤立 `\r`（无 BOM / utf-8）
  - 19 个文件恢复 LF（含根 meta + 一些嵌套文件）
  - 修复后 precheck PASS
- **可疑源（已排查）**：
  1. PM 未通过 `pm_meta_write.py` 改这些文件（`pm_meta_write.py` 写时是 LF）—— 见 `E:\DEMO\DataAnalysis\scripts\pm_meta_write.py:1-99`（2997B，强制 LF 写入逻辑）
  2. coder 路径未触根 meta（coder worker 只写 `projects/dateanalysis-desktop/**`）
  3. OpenClaw 渠道绑定 / agent 同步机制？（待查）
  4. skill_workshop apply 应急通道 C 的 Main `write` 工具？（Main write 的是 `skills/pm-spawn-worker/SKILL.md`，未触根 meta）
- **凭证**：
  - `E:\DEMO\DataAnalysis\scripts\pm_meta_write.py` 2997B / 2026-07-10 01:09:03（可疑源 #1 排查依据）
  - `E:\DEMO\DataAnalysis\scripts\pm_turn_precheck.py` 39712B / 2026-07-15 12:42:10（precheck `ENCODING_SANITY` 触发）
  - `E:\DEMO\DataAnalysis\COMMITMENTS.md` 「异常登记」段（07-15 12:41 发现时间锚点）
  - `E:\DEMO\DataAnalysis\STATUS.md` 「已知系统事件」段（CRLF 污染事件登记）
- **教训**：A011 硬闸门 + `ENCODING_SANITY` 救命——如未做此检查，CRLF 污染可能在 CI 或 Owner 桌面执行 `python` / `git diff` 时再爆（Windows 默认 CRLF 兼容场景下 git 误报 / `python` 脚本被卡 `\r`）。
- **未决**：污染源未明——需 investigator 查证（C030 排队中，等待 C029 ADR 闭环后派）。

---

## 事件 C：Sprint 5 / Issue #3 子代理死锁（高）

- **时间**：
  - 2026-07-15 08:58 spawn
  - 09:51 最后文件写入
  - 14:23 Owner 拉 PM 发现死锁（4.5h 无写入）
- **症状**：
  - `subagents` 列表 `active=[]`，`recent=[]`
  - `sessions` 列表只有 PM 自己
  - S5-#3 子代理未声明完成
  - 最后文件写入停于 `process_analysis_panel.py` line 1746 第 3 图（OLS 残差散点图）中段
- **已落盘半成品**（子代理死锁前已写入磁盘）：
  - `build_multi_params`（纯函数）
  - `_MultiChartWidget` 类
  - `_MultiAttrWidget` 类
  - `ProcessAnalysisPanel` 子工具条 + 使能开关 + 前 2 张图
  - 14 个 `test_s5_3_ui_multi_attribution.py` 测试（不破坏）
  - 第 3 张图未完工
- **根因（推测）**：
  1. 单任务量过大（1746 行一次性写）
  2. 子代理 context 爆掉
  3. subagent 默认 `model=INTCO-Thinking` 对超大单文件写入稳定性待验证
- **缓解措施（S5-#3' 重派）**：
  - 限制 ≤3 文件改动
  - 强制拆函数
  - 频繁落盘
  - 7 分钟预警
  - **效果验证**：6 分钟完成（C028 14:30 ACCEPTED）
- **凭证**：
  - `E:\DEMO\DataAnalysis\COMMITMENTS.md` C027 行（FAILED + 14:23 关闭 + 4.5h 死锁记录）
  - `E:\DEMO\DataAnalysis\COMMITMENTS.md` C028 行（14:25 派 S5-#3' / 14:30 ACCEPTED / 「死锁教训执行到位」Receipt）
  - `E:\DEMO\DataAnalysis\COMMITMENTS.md` 「异常登记」段（死锁详情 + 缓解措施）
  - `E:\DEMO\DataAnalysis\STATUS.md` 「Sprint 5 完成摘要」表 S5-#3 行（FAILED 14:23）
  - `E:\DEMO\DataAnalysis\STATUS.md` 「Sprint 5 完成摘要」表 S5-#3' 行（ACCEPTED 14:30）
  - `E:\DEMO\DataAnalysis\STATUS.md` 「已知系统事件」段（4.5h 死锁登记）
  - `E:\DEMO\DataAnalysis\CHANGELOG.md` V1.13.0 段（死锁 + 教训执行 Receipt）
- **教训（写入 PM 工作记忆）**：
  - PM 派工时 Worker 单任务硬约束不仅是 AGENT-OS §5「10min / 50 calls」，还要考虑「单任务复杂度」——超大单文件改动应主动拆小
  - 拆函数（每个 widget/方法独立）+ 频繁落盘（每个函数完成后立即 write）+ 小步迭代是抗死锁的三件套
- **PM 监控改进**：每 30 分钟主动 `stat` 子代理相关文件，不再死等推送（Owner 反馈后修订）

---

## 共同根因（系统层）

3 个事件都与 OpenClaw 多 Agent 协作基础设施稳定性相关：

1. **审批门解析缺陷**：skill_workshop apply 工具对 Owner 在 PM 群渠道的 approve 信号未走通（事件 A）
2. **跨 agent 一致性**：agent 域过滤问题导致 `proposals.json` 健康但 list 不到（事件 A）+ CRLF 污染源可能是 OpenClaw 写入层 / 同步层（事件 B）
3. **subagent 大任务 context 边界**：单任务量过大导致子代理死锁（事件 C）

三者提示：**OpenClaw 多 Agent 基础设施尚未对"边界场景"做充分错误处理**——审批失败、跨 agent 写入、subagent context 爆炸三类异常均无内置 fallback。

---

## 决定

合并入 ADR-007 是为了**避免 3 个独立事件散落在 CHANGELOG / STATUS / COMMITMENTS 三处文件难以追溯**。决定如下：

1. **事件 A**：保留应急通道 C 作为 skill_workshop apply bug 修复前的可用 fallback；工具 bug 已记入 `applied.json:20-24` followup 字段，等 Owner 转工具维护方。
2. **事件 B**：处置已闭环（19 文件 LF 恢复），根因待 C030 investigator 查证。C030 在 C029 ADR 闭环后派。
3. **事件 C**：PM 派工 SOP 增补已落地（S5-#3' 派工单验证有效）；PM 监控频率改进（30 分钟主动 stat）已写入 PM 工作记忆。
4. **未来类似异常**：继续合并到本 ADR 增补段，或新增 ADR-NNN 引用本 ADR。

---

## 后果

### 正面
1. **Sprint 5 派工通路解阻塞**（应急通道 C 验证可用，C025/C026/C028 派工不受影响）
2. **PM spawn 模板独立可用**——未来 sprint 不依赖 skill_workshop apply 状态
3. **PM 派工 SOP 增补**——超大单文件改动应主动拆小（拆函数 + 频繁落盘 + 小步迭代）已写入工作记忆
4. **PM 监控频率改进**——30 分钟主动 stat 一次子代理相关文件，不再死等推送
5. **A011 硬闸门救命**——`ENCODING_SANITY` 提前发现 CRLF 污染，避免 CI / Owner 桌面执行时再爆

### 负面 / 未决
1. **skill_workshop apply 工具 bug 未修**——需 Owner 转工具维护方
2. **agent 域过滤问题未规范**——origin agent profile 与跨 agent 调用的 list/inspect 行为差异
3. **CRLF 污染源未明**——C030 investigator 排队中（C029 闭环后派）
4. **subagent 大任务 context 边界**——基础设施层无内置 fallback，PM 只能靠 SOP 约束绕开

### 后续 ADR 提示
- 如 C030 investigator 查实 CRLF 污染源，建议在 ADR-007 增补段记录，或新增 ADR-008 引用本 ADR
- 如工具维护方修复 skill_workshop apply bug，建议新增 ADR-009 登记修复时间 + 行为变更
- 如未来 subagent 死锁再次发生且根因指向基础设施层而非单任务量，建议新增 ADR-010 升级问题严重度

---

## 关联承诺

| 承诺ID | 状态 | 与本 ADR 关系 |
|--------|------|----------------|
| C025 | CLOSED | Sprint 5 Issue#1 归因分析升级——本 ADR 登记其子代理死锁事件 |
| C027 | FAILED | S5-#3 多变量归因 UI + 3 张图表——本 ADR 事件 C 主凭证 |
| C028 | CLOSED | S5-#3' 补全 UI 第3图——本 ADR 事件 C 缓解措施效果验证 |
| C029 | PENDING | 写本 ADR（documenter worker 当前任务）——闭环后状态改 CLOSED |
| C030 | ⏳ 排队 | 查 CRLF 污染源（investigator worker）——本 ADR 事件 B 未决项 |

---

## 变更历史

| 日期 | 版本 | 变更 | 作者 |
|------|------|------|------|
| 2026-07-15 | v1 | 初稿登记 3 事件（A 闭环 / B 处置闭环根因待查 / C 教训落地） | documenter Worker（C029） |
