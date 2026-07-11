# TODO — 数据分析 PM

> 最后更新：2026-07-11 16:40

## 🔥 P0 阻塞
- 无

## 🚧 进行中
- 等 Owner 试用 V1.11.0 W11：双击 bat 后，AI解读Tab应默认显示endpoint为内网代理、模型gpt-5.5，点「生成解读」应当连通返回结果（真连通性需桌面验证）

## 📋 Backlog（V1.12+ 候选）
- [ ] P2: AI 解读"自由问答入口"（W12 已立项但未完成：两次子代理执行失败，按 Owner 指令暂不死磕，后续做极简单轮版）
- [ ] P2: tooltip 加上「均值: xxx」（鼠标离均值线近时）
- [ ] P2: 数据处理动作扩展（替换中位数/0/固定值、排序、筛选、去重）
- [ ] P2: 均值线按序列单独控制
- [ ] P2: 大文件表格虚拟滚动/分页
- [ ] P2: `.xls` 完整兼容验证
- [ ] P2: 工具栏按钮在窄屏下的下拉收纳
- [ ] P2: 重缩放"复原数值"精度问题（float32 回退，需保留原始副本）
- [ ] P2: 双 Y 轴模式右轴均值标签 TextItem
- [ ] P2: 两数据集对齐（align_by_time 已有 API，需 UI 入口）
- [ ] P3: 更多图表类型
- [ ] P3: 时序监控 Phase 2（SPC/EWMA/Cpk/ACF）
- [ ] P3: GitHub 上传（待 Owner 提供账户/仓库名/可见性）
- [ ] P3: scripts/pm_meta_write.py 在 PowerShell 下 --stdin 管道 bug 修复（ADR-017 工具链跟进）

## ✅ 最近完成
- [x] W11 V1.11.0: AI解读超时根因修复——自动读 ~/.codex/config.toml + 环境变量拿内网代理 base_url/gpt-5.5；AIClient timeout=60s+友好错误；idle状态显示当前endpoint；on_error不泄露key（2026-07-11 15:05，108 passed 6.41s 0 warnings；ai_config 实测读到 http://10.135.136.21:8317/v1 + gpt-5.5）
- [x] W10 V1.10.1: 右Dock最小宽度400+AI工具栏3行布局+节点悬停tooltip（单图容差18px+小多图补齐）（2026-07-11 13:55，103 passed）
- [x] W9 V1.10.0: 三栏可收起（QDockWidget双侧）+AI URL全provider可编辑+持久化（2026-07-11 13:00，98 passed）
- [x] W8b: AI 解读（OpenAI/DeepSeek/自定义） 2026-07-11 12:15，91 passed
- [x] W8a: 工艺窗口分析 2026-07-11
- [x] W7: 小多图+导出修复 2026-07-11 10:20
