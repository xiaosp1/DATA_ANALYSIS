# 数据分析 PM

> 所属项目：脱模优化 / 数据分析
> Agent ID：`dataanalysis-pm` | 角色：Project PM（项目调度器）

本工作空间是 **[数据分析 PM](https://github.com/openclaw/openclaw)** 的项目调度中枢，遵循 [AGENT-OS.md](https://github.com/openclaw/openclaw) v1.1 规范。

## 当前状态

🟡 **V1.12.7 已交付** — 125 passed / 0 warnings，待 Owner 桌面验证

从 V1.0 骨架初始化到 V1.12.7 全量功能（含归因分析、AI 集成、工艺分析、多数据集操作），6 天交付 12 轮迭代。

## PM 职责

- 📋 接收需求、拆解 Issue、维护看板（TODO / STATUS / ROADMAP）
- 🚀 派工 Worker（coder / documenter / investigator / tester）
- ✅ 验收交付、更新 CHANGELOG / ADR / memory
- ⬆️ 识别阻塞、风险，及时升级 Owner 或 Main

## 目录说明

| 路径 | 内容 | 维护者 |
|------|------|--------|
| `AGENTS.md` | PM 操作手册（引用 AGENT-OS 规范 + 项目特例） | PM |
| `STATUS.md` | 当前项目状态看板 | PM |
| `TODO.md` | Issue 队列（P0 阻塞 / 进行中 / Backlog） | PM |
| `ROADMAP.md` | Sprint 路线图 | PM |
| `COMMITMENTS.md` | 承诺账本（完成态契约） | PM |
| `docs/adr/` | 架构决策记录 | Worker + PM |
| `docs/domain/` | 业务领域知识（工艺 SOP、数据规范） | Documenter Worker |
| `docs/architecture.md` | 系统架构文档 | Investigator Worker |
| `projects/dateanalysis-desktop/` | 真实桌面软件代码（69 .py / 12K LOC） | Codex Worker |
| `scripts/` | PM 基础设施工具 | PM |
| `memory/` | PM 工作日志（30 天滚动） | PM |

## 发版快照

| 版本 | 日期 | 摘要 |
|------|------|------|
| V1.12.7 | 07-13 | ai_client SyntaxError 热修复（125 passed）|
| V1.12.0 | 07-13 | 归因分析、AI 锁/超时/可停止/可配置（120→125 passed）|
| V1.11.0 | 07-11 | 双数据集交叉分析、AI 超时修复（112→125 passed）|
| V1.10.0 | 07-11 | 三栏布局、AI URL 可输入（98→103 passed）|
| V1.9.0 | 07-11 | 工艺窗口分析 + AI 解读（91 passed）|
| V1.8.x | 07-11 | 批量导入/排除列/多图模式/导出（55→91 passed）|
| V1.7.0 | 07-11 | 机头/机尾跨类同图（37 passed）|
| V1.6.0 | 07-10 | 核心分析模块（描述统计/相关性/工艺窗口，32 passed）|
| V1.0~V1.5 | 07-09~07-10 | MVP Demo、PyQt 桌面骨架、基础功能（0→32）|

## 汇报线

- 📩 专属群：脱模优化_数据分析项目群（Telegram）
- ⬆️ 汇报：向 Main（🦞龙虾1号，`agent:main:main`）

## 快速入口

- [STATUS.md](./STATUS.md) — 当前状态看板
- [TODO.md](./TODO.md) — Issue 队列
- [ROADMAP.md](./ROADMAP.md) — 路线图
- [CHANGELOG.md](./CHANGELOG.md) — 版本变更
- [AGENTS.md](./AGENTS.md) — PM 操作手册
