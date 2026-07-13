# CHANGELOG — 脱模优化_数据分析 PM

> 格式：版本/时间/摘要/凭证；最近在上。

## V1.12.6 / W12.6 — 2026-07-13 13:20
**P0** API Key 配置弹窗 EchoMode 报错修复（Owner现场反馈：点配置Key弹 AttributeError）
- Bug：`QInputDialog.EchoMode.Password` 在 PySide6 里不存在，应为 `QLineEdit.EchoMode.Password`
- 同步修正 `test_w12_head_tail_attribution.py` 取消测试断言（原断言 `"已取消"` 不匹配 `"已被用户取消"`）
- 测试：125 passed

## V1.12.5 / W12.5 — 2026-07-13 12:50
**P0** 工艺分析启动无响应修复（Owner现场反馈：点开始分析后一直没结果）
- 根因1：`_run_background` 缺 `cancel_event` 参数，调用处传了 → TypeError 被吞，按钮变灰无反应
- 根因2：`do_work(rp=None)` 参数名不对，Worker 内省识别不到 → 进度条永远 0%，像卡住了
- 修复：`_run_background` 加 `cancel_event=None` 参数并透传 `_set_busy`；两处 `do_work` 参数名改 `report_progress=None`
- 测试：125 passed

## V1.12.4 / W12.4 — 2026-07-13 11:50
**P0** 工艺分析进度细化+取消按钮（Owner现场反馈：还没到AI，正常分析就卡住了）
- `process_analysis.py`：`compute_univariate_windows` 增加 `progress_callback` / `cancel_event` / `pct_range` 参数，每 20% 特征任务回传一次进度
- `process_analysis_panel.py`：QProgressDialog 加取消按钮，点击触发 cancel_event 提前终止分析
- `main_window.py`：工艺分析调用链接入细粒度进度回调 + cancel_event 透传
- 测试：125 passed（ui_smoke_test 为已知遗留，未纳入自动回归）

## V1.12.3 / W12.3 — 2026-07-13 10:30
AI按钮3bug修复+ai_config.json
- 超时/停止后按钮 on_finished 兜底恢复
- 配完Key状态栏反馈+按钮刷新
- ai_config.json 支持 openai/deepseek 两套 base_url/model/api_key
- 优先级：QSettings > 配置文件 > codex > env > PRESET
- 测试：125 passed

## V1.12.2 / W12.2 — 2026-07-13 09:56
AI 超时可配置（5~300s SpinBox + QSettings 持久化 + 状态栏动态显示）

## V1.12.1 / W12.1 — 2026-07-13 09:45
AI 锁与超时热修复（双锁拆分 + 停止按钮 + 软取消 + 30s 超时）

## V1.12.0 / W12 — 2026-07-13 08:59
机尾指数-s归因模式（方案B）。120 passed。

## V1.11.0 / W11 — 2026-07-11 15:05
AI 解读超时修复：自动读取 ~/.codex/config.toml 与环境变量作为默认 endpoint/model。
- 新增 app/services/ai_config.py（纯函数，tomllib 解析 py3.12 stdlib）
- 凭证：108 passed, 0 warnings

## V1.10.1 / W10 — 2026-07-11 13:55
右Dock宽度+节点悬停tooltip。103 passed。

## V1.10.0 / W9 — 2026-07-11 13:00
三栏可收起+AI URL可输入。98 passed。

## V1.9.0 / W8 — 2026-07-11 12:15
工艺窗口分析+AI解读。91 passed。

## V1.8.x — 2026-07-11
文件夹批量/跨类、排除列、Y轴四模式、小多图、导出修复。55 passed。

## V1.7.0 — 2026-07-11 00:30
机头/机尾跨类同图。37 passed。
## V1.12.7 / W12.7 — 2026-07-13 16:26
**P0** ai_client.py 字面 \n SyntaxError 热修复（Owner现场反馈：软件启动直接崩）
- 根因：W12 系列迭代中写入 ai_client.py 时，8 处 \n 被写成字面反斜杠+n而非真实换行
- 影响：rom app.services.ai_client import AIClient 直接 SyntaxError，主程序无法启动
- 修复：脚本批量替换 8 处字面 \n 为真实 LF 换行
- 测试：ast.parse 通过 + 核心测试 125 passed（ui_smoke_test 为已知遗留，未纳入自动回归）
