---
name: "pm-spawn-worker"
description: "PM 派工 SOP：worker agent 创建 + sessions_spawn 模板 + DoD 验收。coder/analyst/documenter/investigator 四类。"
---

# pm-spawn-worker — PM 派工 SOP

> 派生自 OpenClaw 多 Agent 通信机制（docs.openclaw.ac.cn/tools/subagents）
> 与 AGENT-OS.md §6 派工约束对齐
> 项目：脱模优化_数据分析 PM

> ⚠️ **应用通道说明（2026-07-15）**：本 skill 因 skill_workshop apply 工具 bug（Owner approve 信号未落盘，4 次 apply 均 "Approval timed out"）由 Main 侧走应急通道 C 落盘。提案原始内容见 `C:\Users\m00053733\.openclaw\skill-workshop\proposals\pm-spawn-worker-20260715-9f46368b78\PROPOSAL.md`，磁盘一致性由 Main 侧保证，待工具 bug 修复后由索引 reindex 自然吸收。

## 适用场景

PM 收到 Owner 需求 → 拆解为 Issue → 需要派 worker（coder/analyst/documenter/investigator）执行 → 验收交付物 → 归档结果。

## 不适用

- PM 自己能直接做的轻量操作（precheck、读看板、写 status）
- 需要人工介入的对话、决策、拍板

## 前置检查（每轮派工前必跑）

1. `python scripts/pm_turn_precheck.py --project-root E:\DEMO\DataAnalysis` 必须 PASS
2. 目标 worker agent 配置存在于 `C:\Users\m00053733\.openclaw\agents\<name>\agent\`，含 `IDENTITY.md` + `SOUL.md`
3. 目标 worker agent 在 PM 的 `subagents.allowAgents` 白名单内（默认仅 PM 自己）
4. 已写入 COMMITMENTS.md 状态 PENDING

## Worker 四类（项目模板）

### analyst
- **任务**：扫现有代码/文档/数据 → 出"扩展点 + 算法选型 + 草图" 3 件套
- **Tools**：read、exec（只读）、memory_search
- **DoD**：1 份 markdown 报告（≤ 50KB），含原文引用 + 数据截图
- **不写**：不写代码、不改文件、不派工

### coder
- **任务**：实现功能/修 bug/写测试
- **Tools**：read、write、edit、exec（限 workspace-write 沙箱）、python skill
- **DoD**：tests 全绿 + 0 warnings + 代码/测试文件已落盘 + stat 字节数证据
- **不改**：TODO/STATUS/ROADMAP/COMMITMENTS、docs/domain/、SOUL/IDENTITY

### documenter
- **任务**：业务文档新增/修订（docs/domain/）、ADR 撰写
- **Tools**：read、write、edit、memory_search
- **DoD**：docs/domain/ 或 docs/adr/ 文件落盘 + 来源链接 + PM 验收
- **不改**：代码、meta 文件

### investigator
- **任务**：调查 bug/性能/兼容性 → 出根因报告 + 修复建议
- **Tools**：read、exec（只读）、memory_search
- **DoD**：根因报告（含日志/截图/堆栈证据）+ 修复方案分步骤
- **不写**：不直接改代码（建议给 coder）

## sessions_spawn 模板

```python
sessions_spawn(
    task='''
# 任务一句话
<任务>

# 工作目录
E:\\DEMO\\DataAnalysis\\projects\\dateanalysis-desktop

# 读取文件（≤5）
- app/services/head_tail_attribution.py
- app/ui/widgets/process_analysis_panel.py
- tests/test_w12_head_tail_attribution.py
- docs/domain/脱模工艺概述.md

# Skills
python, write-tests, spike

# DoD（≤3条）
1. tests 全绿 + 0 warnings
2. X 文件落盘，stat 字节数记录
3. STATUS/CHANGELOG 已同步

# 输出要求
- 主程序可启动
- 8 条新用例覆盖多列归因
- 单对单回归 6 条仍 pass

# 严禁
- 不改 TODO/STATUS/ROADMAP/COMMITMENTS/docs/domain/
- 不读 PM 对话历史
- 不外发消息
- 不跑 `git stash` / `git checkout HEAD` / `git reset --hard` 等会触发 core.autocrlf=true 隐式转换的 git 命令
- 如必须暂存改动，使用 `git stash --keep-index` 或直接 `apply_patch` / `write` 工具落盘
- 若发现文件被 git 改成 CRLF，立即报告 PM，不要默默接受
''',
    taskName='s5_attribution_multi',
    label='analyst-s5-attribution',
    model='INTCO-Thinking',
    thinking='high',
    mode='run',
    cleanup='delete',
    sandbox='require',
)
```

## 派生流程（10 步）

1. **PM 拆 Issue** → TODO.md 加进行中条目
2. **写 COMMITMENTS** → PENDING 状态
3. **检查 worker agent 配置** → 如不存在则走"创建 worker agent"流程（见下）
4. **白名单确认** → 编辑 PM 配置允许该 worker
5. **sessions_spawn** → 用上面的模板
6. **sessions_yield** → 等推送式完成（不轮询）
7. **PM 读 worker 报告** → 走 DoD 验收清单
8. **接受** → 更新 COMMITMENTS RECEIPT → CLOSED → 同步 STATUS/TODO/ROADMAP/CHANGELOG
9. **打回** → 明确打回原因（≤3条）→ 重派（计入重试上限）
10. **失败 ≥2 次同类** → 升级 Owner，不死磕

## 创建 worker agent（首次需要）

```powershell
# 1. 复制模板
Copy-Item C:\Users\m00053733\.openclaw\workspace\AGENT-OS.md `
          C:\Users\m00053733\.openclaw\agents\coder\agent\AGENTS.md

# 2. 创建 IDENTITY.md / SOUL.md / USER.md / TOOLS.md
# 参考 PM 同名文件，去掉 PM 专属内容

# 3. 加入 PM 白名单
# 编辑 C:\Users\m00053733\.openclaw\agents\dataanalysis-pm\agent\openclaw.json
# agents.list[].subagents.allowAgents: ["coder", "analyst", ...]
```

## 验收清单（PM 收到 worker 报告后逐条勾）

- [ ] tests 全绿（pytest 输出）
- [ ] 0 warnings（pyflakes/ruff 输出）
- [ ] 代码文件落盘 + stat 字节数（`Get-ChildItem` 输出）
- [ ] 未越界改禁区文件
- [ ] CHANGELOG.md 已加本次条目
- [ ] 原文引用到位（worker 报告里有 path:line）
- [ ] sample 数据跑通的回归证据（stat/截图）

## 失败处理

- **超时**（>10 min / >50 calls）→ 立即拆小重派
- **同任务 2 次失败** → 升级 Owner，不死磕
- **越界改禁区** → 立即 reject，通知 Owner，纳入审计

## 跟其他 skill 的关系

- **必须先有** `python` / `write-tests` / `spike` 等基础 skill
- **可并行沉淀** `codex-dispatch`（如未来要 Codex CLI 走原生 ACP）
- **不替代** `pm_turn_precheck.py` 闸门

## 参考

- OpenClaw docs: docs.openclaw.ac.cn/tools/subagents
- AGENT-OS.md §6 派工约束
- 项目 AGENTS.md §1 派工约束（与主规范对齐）

## 应急通道元数据（2026-07-15 应急落盘后由工具 bug 修复者审计）

- 提案原始 ID：pm-spawn-worker-20260715-9f46368b78
- 提案 storage：C:\Users\m00053733\.openclaw\skill-workshop\proposals\pm-spawn-worker-20260715-9f46368b78\
- 落盘执行者：Main session agent:main:main
- 触发：skill_workshop apply 第 4 次超时（Owner 已明确 approve，工具未落盘 approve 信号）
- 配套 ADR：docs/adr/2026-07-15-skill-workshop-approve-timeout.md（待补）
