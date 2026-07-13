# TODO — 数据分析 PM

> 最后更新：2026-07-13 16:41

## 🔥 P0 阻塞
- 无

## 🚧 进行中
- 等Owner桌面验证 V1.12.6（W12全系列）：
  1. 关掉旧软件，双击 `启动 DateAnalysis.bat` 重启
  2. 机尾指数-s归因模式
  3. 工艺分析能出结果+进度条走动+取消按钮可终止
  4. API Key 配置弹窗不报错（密码模式）
  5. AI期间不锁全局+可停止+超时可配置
  6. 超时/停止后按钮恢复
  7. 配完Key按钮亮+状态栏反馈
  8. ai_config.json 可用（openai/deepseek各一套）

## 📋 Backlog（V1.13 候选）
- [ ] P1: 描述统计KDE移后台/降采样（BUG-2）
- [ ] P1: merge_by_category / merge_cross_category 走后台线程（BUG-5）
- [ ] P1: 折线图选项变更加300ms debounce（RISK-3）
- [ ] P1: dataset/analysis级QProgressDialog加取消按钮（RISK-7）
- [ ] P2: AI 真·硬中断（QNetworkAccessManager 或 requests+streaming）
- [ ] P2: AI 解读"自由问答入口"
- [ ] P2: tooltip 加「均值: xxx」
- [ ] P2: 数据处理动作扩展
- [ ] P2: 均值线按序列单独控制
- [ ] P2: 大文件表格虚拟滚动/分页
- [ ] P2: 工具栏按钮在窄屏下拉收纳
- [ ] P2: 重缩放"复原数值"精度
- [ ] P2: 双Y轴右轴均值标签
- [ ] P2: 两数据集对齐UI入口
- [ ] P2: 工艺分析导出截图移后台
- [ ] P2: TablePanel列宽自动调整卡顿
- [ ] P2: 清理死代码
- [ ] P2: excepthook弹友好提示
- [ ] P3: 更多图表类型
- [ ] P3: 时序监控 Phase 2
- [ ] P3: GitHub上传
- [ ] P3: scripts/pm_meta_write.py PowerShell --stdin bug

## ✅ 最近完成
- [x] W12.7 V1.12.7: ai_client.py 字面 \n SyntaxError 热修复——8处字面反斜杠+n替换为真实换行，主程序可启动；ast.parse通过 + 125 passed（2026-07-13 16:26）
- [x] W12.6 V1.12.6: API Key配置弹窗EchoMode修复——QInputDialog.EchoMode → QLineEdit.EchoMode.Password；同步修正 head_tail_attribution 取消测试；125 passed（2026-07-13 13:20）
- [x] W12.5 V1.12.5: 工艺分析启动无响应修复——_run_background加cancel_event参数并透传_set_busy；do_work参数名改report_progress匹配Worker内省；125 passed（2026-07-13 12:50）
- [x] W12.4 V1.12.4: 工艺分析进度细化+取消按钮——compute_univariate_windows加progress_callback/cancel_event；每20%特征回传进度；QProgressDialog取消按钮；cancel_event提前终止；125 passed（2026-07-13 11:50）
- [x] W12.3 V1.12.3: AI按钮3bug修复+ai_config.json——超时/停止后按钮on_finished兜底恢复；配完Key状态栏反馈+按钮刷新；ai_config.json支持openai/deepseek两套base_url/model/api_key；125 passed（2026-07-13 10:30）
- [x] W12.2 V1.12.2: AI超时可配置（5~300s SpinBox+QSettings持久化+状态栏动态显示）（2026-07-13 09:56）
- [x] W12.1 V1.12.1: AI锁与超时热修复（双锁拆分+停止按钮+软取消+30s超时）（2026-07-13 09:45）
- [x] W12 V1.12.0: 机尾指数-s归因模式（方案B）（2026-07-13 08:59）
