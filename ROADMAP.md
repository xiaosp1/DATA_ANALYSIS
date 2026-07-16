# ROADMAP — 数据分析 PM

> 最后更新：2026-07-15 16:00
> 所属项目：脱模优化 / 数据分析桌面软件（DateAnalysis）

## Sprint 完成情况

| Sprint | 周期 | 交付范围 | 状态 |
|--------|------|----------|------|
| Sprint 0 | 07-07 | Workspace 骨架初始化、PM 文件落地、AGENT-OS v1.0→v1.1 升级 | ✅ 完成 |
| Sprint 1 | 07-08 | 领域文档 V0.1、数据清洗+可视化技术选型、ADR-001 | ✅ 完成 |
| Sprint 2 | 07-09~07-10 | MVP 可运行 Demo、PyQt 桌面骨架、核心分析模块（描述统计+相关性+工艺窗口）| ✅ 完成 |
| Sprint 3 | 07-11~07-12 | 图表交互（双Y轴/多图/折叠/小多小图）、数据导入/排除/批处理、SPC 控制图、工艺分析+AI解读、数据集对比/合并、三栏布局、交叉分析 | ✅ 完成 |
| Sprint 4 | 07-13 | W12 全系列：归因模式、AI 锁/超时/可配置、3bug修复、进度条细化、启动无响应修复、EchoMode热修复、字面\\n SyntaxError 修复 | ✅ 完成（V1.12.7，125 passed）|
| Sprint 5 | 07-15 | 归因分析升级——头部多列→尾部单列多元归因：M1偏相关+M2 OLS β*/R²/VIF；3张图表（\|β*\|排名 / 单偏vs全偏 / OLS残差+LOESS）；子工具条（全选/反选/Top10/自定义）；使能开关默认开启；pingouin可选精化 | ✅ 完成（V1.13.0，162 passed）|
| **Sprint 5+** | **07-15** | **C034 修归因卡顿（进度条单调+异常捕获+Panel 内嵌 QProgressBar）+ C037-A AI 解读覆盖多变量（M1偏相关+M2 OLS β*+VIF醒目）+ C031 CRLF 治本 3 件套（.gitattributes+precheck 扩扫+pm-spawn-worker 加 worker git 约束）+ ADR-007/008 落地** | **✅ 完成（V1.13.1 候选，175 passed）** |

## 当前状态
- **当前基线**：**V1.13.1 候选**（175 passed / 0 warnings，待 Owner 桌面二次验证）
- **上一基线**：V1.13.0（162 passed）
- **状态**：🟡 **待 Owner 桌面验证 V1.13.1 + 拍板 C037-B/C 是否进入 Sprint 6**

## Sprint 5+ 验收清单（V1.13.1 候选）

### 桌面验证（Owner 必跑）
1. 关掉旧软件，双击 `启动 DateAnalysis.bat` 重启
2. **多变量归因开关默认勾选**——确认「☑ 多变量归因 (S5)」在分析参数区
3. **子工具条** 4 个按钮响应——「全选」「反选」「仅 Top10」「自定义」
4. **新 Tab「多变量归因 (S5)」** 出现，含 3 张图
5. **第 1 图**——头部列贡献排名（|β*| 降序，红蓝灰配色）
6. **第 2 图**——单偏 vs 全偏对比条形图（关键观察：被代理列 partial_r 塌陷）
7. **第 3 图**——OLS 残差散点图 + LOESS 趋势线 + ±2σ 填充（grid 2×⌈p/2⌉）
8. **取消按钮** 行内可点，进度条走动
9. **VIF 警告**——若某列 VIF>10，UI 顶部黄色 banner 提示「[机头]X VIF=12.3 建议剔除」（**仅警告**）
10. **pingouin 缺失时**——UI 不崩，numpy 主路径自动接管
11. **进度条单调递增**——C034 修复后从 0→75→78→92→97→100，不再"100→25 倒退"
12. **多变量归因 Tab 自动切换**——C034 `set_running` 扩展，进度可见
13. **AI 解读现在覆盖多变量**——C037-A 升级，6 段式（W12 4 段 + M1 + M2 OLS β* + VIF 醒目横幅）
14. **AI 解读里 VIF 警告醒目**——C037-A 模板首位横幅
15. 取消按钮按下不再 AttributeError——C034 None 安全

### Owner 拍板后续（不阻塞 V1.13.1）
- [ ] git tag v1.13.1
- [ ] C037-B 是否进入 Sprint 6（target_col 解耦 + combo 文案 + #3 同步，**PM 纠偏：4 处硬编码 + feature_cols 默认行为确认**）
- [ ] C037-C 是否进入 Sprint 6（S5 Tab splitter + 图3 独立 tab）
- [ ] VIF 自动剔除功能是否要做（先理解 VIF 是什么）
- [ ] pingouin 实际安装还是不装（当前仅 requirements.txt 占位）
- [ ] **C038** 待 Owner 拍板：子代理 `write` 工具默认 CRLF 救火方案（PM 救火已做，治本需修子代理 `write` 工具默认行为 / precheck ENCODING_SANITY 加"新增文件即时 LF 检查" / 接受现状）
- [ ] **C035** C032 followup：验证 .gitattributes 在 Owner 全局 `core.autocrlf=true` 机器上是否真的 override

## Sprint 6 候选（等 Owner 拍板）

### P1 优先（Owner 15:33 4 项反馈落地路径）
- [ ] **C037-B**：target_col 解耦 + combo 文案 + #3 同步（中等风险，2 文件改动）
- [ ] **C037-C**：S5 Tab splitter + 图3 独立 tab（低风险，1 文件改动）
- [ ] 描述统计KDE移后台/降采样（BUG-2）
- [ ] merge_by_category / merge_cross_category 走后台线程（BUG-5）
- [ ] 折线图选项变更加300ms debounce（RISK-3）
- [ ] dataset/analysis级QProgressDialog加取消按钮（RISK-7）

### P2 后续
- [ ] AI 真·硬中断（QNetworkAccessManager 或 requests+streaming）
- [ ] AI 解读"自由问答入口"
- [ ] VIF 自动剔除（仅警告 → 自动剔除阈值 100）
- [ ] tooltip 加「均值: xxx」
- [ ] 数据处理动作扩展
- [ ] 均值线按序列单独控制
- [ ] 大文件表格虚拟滚动/分页
- [ ] 工具栏按钮在窄屏下拉收纳
- [ ] 重缩放"复原数值"精度
- [ ] 双Y轴右轴均值标签
- [ ] 两数据集对齐UI入口
- [ ] 工艺分析导出截图移后台
- [ ] TablePanel列宽自动调整卡顿
- [ ] 清理死代码
- [ ] excepthook弹友好提示
- [ ] 第 3 张图 PNG export（参考图 1/2 路径）
- [ ] 进度节流到 5 Hz（C033 排名 5）
- [ ] VIF 分块化使 np.linalg.lstsq 可中断（C033 排名 4）
- [ ] AI 解读缓存
- [ ] 目标列变更提示
- [ ] 多变量 p>20 导出优化

### P3 远期
- [ ] 更多图表类型
- [ ] 时序监控 Phase 2
- [ ] GitHub 上传

## 治理 / 基础设施 followup
- [x] ADR-007 skill-workshop apply bug + CRLF + 子代理死锁三合一（CLOSED 14:46）
- [x] ADR-008 git autocrlf 独立技术决策（CLOSED 15:33）
- [x] C031 .gitattributes + precheck 扩扫 + pm-spawn-worker 加 worker git 约束（CLOSED 15:34）
- [x] docs/architecture.md LF 修复 P0（CLOSED 14:55）
- [ ] C035 gitattributes 验证（C032 followup）
- [ ] C038 子代理 `write` 工具默认 CRLF 治本（PM 救火已做）
- [ ] pm-spawn-worker 改进（30min 主动 stat 子代理）
- [ ] ADR-007 事件 B 段状态改为「已闭环」+ cross-ref ADR-008（V1.13.1 git tag 时一起做）
- [ ] ui_smoke_test 进一步纳入自动回归
- [ ] 数据红线 .gitignore 审计
