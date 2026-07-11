# CHANGELOG — 脱模优化_数据分析 PM

> 格式：版本/时间/摘要/凭证；最近在上。

## V1.11.0 / W11 — 2026-07-11 15:05
AI 解读超时修复：自动读取 ~/.codex/config.toml 与环境变量作为默认 endpoint/model。
- 新增 app/services/ai_config.py（纯函数，tomllib 解析 py3.12 stdlib）：load_default_ai_config() 按 codex config.toml → OPENAI_BASE_URL/OPENAI_API_BASE/OPENAI_MODEL 环境变量 → 硬编码预设 的优先级返回默认 base_url/model/api_key；api_key 只从 OPENAI_API_KEY 读，不从 codex config 读；任何解析失败静默回退
- ProcessAnalysisPanel：__init__ 调 load_default_ai_config() 作为 openai provider 默认值；_on_ai_provider_changed 默认值优先级 QSettings 用户值 > ai_config > PRESETS > 空；用 blockSignals 填默认值避免误记为用户输入；所有 provider 保持 base_url/model 可编辑（W10）；新增 _idle_status_text() 在面板底部显示"就绪（endpoint: …，模型: …）"
- AIClient：默认超时 30→60s；HTTPError 细分：401/403 鉴权失败、404 提示 base_url/模型错误、429 限流、5xx 服务端错误；URLError 连接失败给出"请检查 base_url 是否在当前网络可达"明确提示；TimeoutError→"请求超时（60s）"；所有错误不泄露 api_key；非 custom provider 也接受传入 base_url/model 覆盖 preset（W9 保留）
- main_window：构造 AIClient 时始终传入 base_url/url/model（没有 provider 判断），on_error 回调红字展示到面板 AI 状态+error 日志；移除冗余的 env_key 自动 set_api_key（面板已自管）
- 新增 tests/test_w11_ai_config.py（5 个 offscreen 单测）
- 凭证：compileall 0；`pytest -W error --ignore=tests/ui_smoke_test.py` **108 passed in 6.41s，0 warnings**（103+5）

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