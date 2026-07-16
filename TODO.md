## 🔥 P0 阻塞

### C046 归因分析 100% 卡死（Owner 09:52 反馈 / investigator 调查 / PENDING / ~5m+ running）
- **症状**：归因分析点击后进度走到 100%，然后**卡死不再响应**
- **已知条件**：p<20 / n=百万级 / **首次点就卡**（不是第二次）
- **已排除**：C033/C034 已修的是"进度倒退视觉错觉"，不是这个
- **怀疑方向**：
  - A. matplotlib 大图渲染在主线程阻塞（百万行画点慢）
  - B. 第 3 张图 LOESS 计算在主线程阻塞（p<20 也不能排除）
  - C. AI 解读在主线程发请求（如果开关开着）
  - D. QProgressDialog / QProgressBar 没及时 `setValue(0)` 重置
  - E. pandas 在主线程做 merge / 大数据 prepare
- **DoD**：5 方向调查 + 最可能源 + line:col 接入点 + spike 脚本可跑 + 修复建议分步骤
- **进度**：10:00 spawn → ~10:09 running

### C047 5Hz 心跳日志 ✅ CLOSED 10:08（7m30s）
- **范围**：`head_tail_attribution.py` + `process_analysis_panel.py`
- **结果**：
  - `head_tail_attribution.py` 33349 → 35096 (+1747B)
  - `process_analysis_panel.py` 94433 → 95552 (+1119B)
  - 7 埋点齐：`_call_progress` + `build_head_tail_report` 入口/出口 + M1/M2 计算前后 + LOESS 三出口 + AI 解读 ENTER/EXIT + 图 3 ENTER/EXIT
  - 200ms 限流验证（5x 同 (pct,msg) → 1 print；pct 变化强制打）
  - 185 passed / 2 warnings（与 baseline 同）
  - LF 干净 / 无 BOM / py_compile OK
- **Owner 桌面指引**：双击 `启动 DateAnalysis.bat` 重启（命令行窗口别关）→ 点归因分析 → 把 `[ATTR]` 日志复制给我

## 📋 Backlog（V1.13.2 / Sprint 6 候选）
- [ ] P1：描述统计KDE移后台/降采样（BUG-2）
- [ ] P1：merge_by_category / merge_cross_category 走后台线程（BUG-5）
- [ ] P1：折线图选项变更加300ms debounce（RISK-3）
- [ ] P1：dataset/analysis级QProgressDialog加取消按钮（RISK-7）
- [ ] P2：AI 真·硬中断（QNetworkAccessManager 或 requests+streaming）
- [ ] P2：AI 解读"自由问答入口"
- [ ] P2：VIF 自动剔除阈值（待 Owner 决策）
- [ ] P2：tooltip 加「均值: xxx」
- [ ] P2：数据处理动作扩展
- [ ] P2：均值线按序列单独控制
- [ ] P2：大文件表格虚拟滚动/分页
- [ ] P2：工具栏按钮在窄屏下拉收纳
- [ ] P2：重缩放"复原数值"精度
- [ ] P2：双Y轴右轴均值标签
- [ ] P2：两数据集对齐UI入口
- [ ] P2：工艺分析导出截图移后台
- [ ] P2：TablePanel列宽自动调整卡顿
- [ ] P2：清理死代码
- [ ] P2：excepthook弹友好提示
- [ ] P2：进度节流到 5 Hz（C033 排名 5）—— C047 心跳已实现，但 RP callback 本身仍 5Hz 节流待合并
- [ ] P2：VIF 分块化使 np.linalg.lstsq 可中断（C033 排名 4）
- [ ] P2：AI 解读缓存
- [ ] P2：目标列变更提示
- [ ] P2：多变量 p>20 导出优化
- [ ] P3：更多图表类型
- [ ] P3：时序监控 Phase 2
- [ ] P3：GitHub 上传
- [ ] P3：scripts/pm_meta_write.py PowerShell --stdin bug（已发现）
- [ ] P3：pm-spawn-worker 改进（30min 主动 stat 子代理）
- [ ] P3：ADR-007 事件 B 状态改「已闭环」+ cross-ref ADR-008（V1.13.1 git tag 时一起做）

## ✅ 最近完成
- [x] **C047 5Hz 心跳日志 CLOSED**（2026-07-16 10:08 / 7m30s / 2 文件 / 185 passed）
- [x] **V1.13.1 候选 / Sprint 5+**：185 passed / 0 warnings（C034 + C037-A + C037-B + C037-C + C031 + ADR-007/008）（2026-07-15 19:55）
- [x] **C038 跨 PM 同步 4 阶段全部 CLOSED**（2026-07-15 19:55 / 22min / 7 PM workspace 全部生效）
- [x] **C045 README ADR-019 索引追加**（2026-07-15 19:55）
- [x] **C044 sync 验证 7 PM workspace**（2026-07-15 19:53 / 28/28 字节数一致）
- [x] **C043 ADR-019 落档**（2026-07-15 19:45 / 27457B）
- [x] **C042 AFE 真值源改 precheck**（2026-07-15 19:38 / +5050B）
- [x] **C041 PM 上报 Main 路径 A**（2026-07-15 19:32）
- [x] **C040 跨 PM 落地路径调研**（2026-07-15 19:23 / 推荐路径 A 5/5）
- [x] **C037-B target_col 解耦 ACCEPTED**（2026-07-15 18:32）—— 已进 V1.13.1
- [x] **C037-C S5 Tab splitter ACCEPTED**（2026-07-15 18:22）—— 已进 V1.13.1
- [x] **C037-A AI 解读覆盖多变 CLOSED**（2026-07-15 16:01）—— 已进 V1.13.1
- [x] **C034 修归因卡顿**：170 passed / 4 文件改动 / 6 测试 / 单调保护（2026-07-15 15:56）
- [x] **C036 重构设计**：34968B / 4 项 + 分刀 A/B/C + 5 种 ASCII 布局对比（2026-07-15 15:54）
- [x] **C032 ADR-008 独立**：git autocrlf 技术决策（11369B）（2026-07-15 15:33）
- [x] **C031 CRLF 治本 3 件套**：.gitattributes + precheck 扩扫 + pm-spawn-worker 改（2026-07-15 15:34）
- [x] **C033 卡顿根因调查**：算法 1.6s 跑完，"卡"是进度条倒回视觉错觉（2026-07-15 15:44）
- [x] **C030 CRLF 根因调查**：95% 置信度为 S5-#3 git stash + autocrlf=true（2026-07-15 14:55）
- [x] **C029 ADR-007 三合一**：skill-workshop apply bug + CRLF + 子代理死锁（2026-07-15 14:46）
- [x] **V1.13.0 / S5-#1 归因分析升级**：162 passed / 0 warnings（2026-07-15 14:31）
- [x] W12.7 V1.12.7: ai_client.py 字面 \n SyntaxError 热修复（2026-07-13 16:26）

### C046 归因分析 100% 卡死 ✅ CLOSED 10:39（41m50s 超红线 4x）
- **根因**：★1 LOESS fallback `np.convolve(n, w=n/10)` 单子图 n=1M 时 100-180s × 10 子图 = 15-25min 主线程冻结（99%）
- **次要**：M1 `_partial_corr` numpy O(n×p³) p=15/n=1M=11s（95%）
- **设计**：`_fill_multi_attr` 主线程串行（100%）+ chart3 无 n 阈值自适应（100%）
- **PM 独立复验**：spike_loess_only 实测 n=200k=19.7s / n=500k=48.5s（与报告一致）
- **产物**：`docs/proposals/2026-07-16-attribution-stuck-100pct.md` 35979B + 4 spike 脚本
- **PM 自查**：41m50s 超 10min 红线 4x，下次 investigator 任务拆小（如"先跑 spike 出数据"再写报告）

### C049 折线图配置后"开始分析"卡死 + 折线图不显示 🆕 PENDING
- **症状**：折线图配置完成后点"开始分析" → 卡死 + 折线图不显示
- **Owner 反馈时间**：10:39
- **与 C046 关系**：暂不确定（折线图 vs 归因分析是不同的功能模块，但都涉及大数据集 + 主线程）
- **PM 立场**：不瞎猜，先收 4 个关键细节
- **阻塞**：等 Owner 答以下细节才能派工

### C048 待派工（归因分析修复）
- 方案 A（强烈推荐）：P0A 单工单（5min，chart3 降采样 MAX_RENDER_POINTS=5000）
- 方案 B：A + P0B（35min，+ VIF 一行算完）
- 方案 C：全部 P0A + P0B + P1A + P1B（半天）
- **等 Owner 决策**
