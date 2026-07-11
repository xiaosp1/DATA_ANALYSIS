# Architecture — 数据分析 PM

**脱模优化 / 数据分析**项目 PM workspace。

目标（占位，待 Sprint 1 对齐）：围绕生产过程中的"脱模"环节，进行数据采集、清洗、分析，沉淀优化策略，形成可复用的数据分析能力，辅助现场决策。

具体数据源、指标体系、建模方式、交付形态将在 Sprint 1 与 Owner 对齐后在此处细化。

## 当前状态
- 🟡 Workspace 骨架已初始化，尚未开展具体业务/开发。
- 技术栈 / 模块划分 / 目录约定待 Sprint 1 与 Owner 对齐后补充。

## Workspace 结构（按 AGENT-OS.md §2）
- `AGENTS.md` / `SOUL.md` / `IDENTITY.md` / `USER.md` / `TOOLS.md` / `HEARTBEAT.md`：PM 操作手册/身份/工具
- `TODO.md` / `STATUS.md` / `ROADMAP.md`：项目状态看板（PM 工作台）
- `docs/architecture.md`：系统架构（本文）
- `docs/getting-started.md`：新手上路
- `docs/adr/`：架构决策记录
- `docs/domain/`：领域知识
- `docs/progress/`：里程碑/月度进度
- `src/`、`tests/`、`scripts/`：源代码/测试/脚本（PM workspace 初始为空，按需填充）
- `skills/`：项目专属 Skill（区别于全局 `global/` 库）
- `memory/`：PM 工作日志（30 天滚动）

## 后续补充
- 业务目标 & 非功能目标
- 模块划分 & 关键依赖
- 外部接口 / 数据流向
- 部署形态
