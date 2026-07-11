# Getting Started — 数据分析 PM

> 新手上路 / 环境搭建（占位版）

## 前置依赖
- OpenClaw Gateway 运行中，Main（🦞龙虾1号）已完成本 PM 的注册与群绑定
- Node.js v24+（系统 PATH）；如后续涉及特定技术栈（Python / dotnet / 数据库等），在此补充
- Codex CLI 已全局安装（`npm i -g @openai/codex` 或同等版本）

## PM 启动流程
1. PM 会话唤醒后先读：`AGENTS.md → TODO.md → STATUS.md → ROADMAP.md → docs/architecture.md`
2. 确认当前 Sprint 目标与活跃 Issue
3. 按派工模板 spawn Worker，明确 DoD
4. 交付后验收 → 归档（更新 STATUS/CHANGELOG/ADR/memory）
5. 上下文到 70% 立即归档并提醒 Owner 执行 `/compact`

## 常用命令（占位）
- （具体命令按项目技术栈补充）

## 常见问题
- Q：Worker 超时 / 改文件过多怎么办？A：拆任务重派，不要让 Worker 扛。
- Q：重启后记忆丢失？A：文件是 Source of Truth，按 AGENTS.md §7 恢复流程读文件即可。
