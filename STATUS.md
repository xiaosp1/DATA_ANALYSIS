# STATUS — 数据分析 PM

> 最后更新：2026-07-11 15:05
> 当前 Sprint：Sprint 3 ✅ V1.11.0 W11 交付，待 Owner 桌面验证 AI 解读真连通

## 当前状态：🟢 V1.11.0 W11 完成，108 passed / 0 warnings（-W error）

## 托管项目
- **项目名**：DateAnalysis（本地数据分析与图表展示桌面软件）
- **路径**：E:\DEMO\DataAnalysis\projects\dateanalysis-desktop\n- **当前有效版本**：V1.11.0（W4-W11 累计）。启动：双击 `启动 DateAnalysis.bat`。
- **V1.11 基线**：compileall 0；`pytest tests/ -q -W error --ignore=tests/ui_smoke_test.py` → **108 passed in 6.41s，0 warnings**
- **ai_config 实测**：load_default_ai_config() 在 Owner 机器上返回 `base_url=http://10.135.136.21:8317/v1, model=gpt-5.5, api_key=<from OPENAI_API_KEY>` —— 超时根因已修：软件现在会自动读 ~/.codex/config.toml 的内网代理地址与模型，不再硬编码走外网 api.openai.com

## V1.11.0 / W11 修复点（AI 解读超时根因修复）

### 根因
- 软件之前硬编码 base_url=https://api.openai.com/v1, model=gpt-4o-mini，完全不读 ~/.codex/config.toml 和 OPENAI_BASE_URL 环境变量，而 Owner 环境下实际跑的是内网代理 http://10.135.136.21:8317/v1 上的 gpt-5.5，导致请求发往外网必然超时/拒绝
- 超时 30s 偏短；错误信息笼统；面板不显示当前 endpoint

### 修复
- **新模块 `app/services/ai_config.py`**：load_default_ai_config() 纯函数，优先级 codex config.toml → OPENAI_BASE_URL/OPENAI_API_BASE/OPENAI_MODEL 环境变量 → https://api.openai.com/v1/gpt-4o-mini 兜底；api_key 只从 OPENAI_API_KEY 读，不从 codex config 读；任何解析失败静默回退
- **ProcessAnalysisPanel 默认值改造**：启动时从 ai_config 取 openai 的默认 base_url/model；QSettings 记忆的用户值优先，ai_config 次之，PRESET 最后；blockSignals 防止默认值误记为用户输入；所有 provider 保持 base_url/model 可编辑；底部状态 idle 时显示 "就绪（endpoint: …，模型: …）"
- **AIClient**：
  - 默认 timeout 30→60s
  - HTTPError 细分：401/403 鉴权失败；404 提示 base_url 路径/模型不匹配；429 限流；5xx 服务端错误（带 detail）
  - URLError：连接失败/拒绝/无法解析主机 → "无法连接到 <host>，请检查 base_url 是否在当前网络可达（如内网代理需要连 VPN/办公网）"
  - TimeoutError/socket.timeout → "请求超时（60s），请检查网络或 base_url 是否可达"
  - 任何错误消息不包含 api_key（on_error 回调再做一次 replace 防御）
  - 非 custom provider 也接受传入 base_url/model 覆盖 preset（W9 保留）
- **main_window**：AIClient 构造时始终传 url/model（去掉旧的 provider=='custom' 判断）；on_error 红字提示到 AI 状态栏并写 error 日志；移除冗余的 env_key 自动 set_api_key（面板已自管）

### 文件改动（7 个）
- app/services/ai_config.py（新）
- app/services/ai_client.py（超时+错误信息细化）
- app/ui/widgets/process_analysis_panel.py（默认值走 ai_config + idle 状态显示 endpoint）
- app/ui/main_window.py（透传参数+错误日志+删除冗余 env_key 注入）
- tests/test_w11_ai_config.py（新，5 个 offscreen 单测）
- tmp/ 下清理了临时生成器脚本
- CHANGELOG/STATUS/COMMITMENTS/TODO（PM 归档）

## 承诺中（v1.1）

| 承诺ID | 登记时间 | Agent | 承诺 | 状态 | 关闭时间 | Receipt |
|--------|----------|-------|------|------|----------|---------|
| C001-C007 | … | … | …（略） | CLOSED | — | — |
| C008 | 2026-07-11 14:06 | PM | V1.11.0 W11 AI解读超时修复 | CLOSED | 2026-07-11 15:05 | 108 passed 6.41s 0 warnings；ai_config 实测读到内网代理 |

## 阻塞/风险
- 无工程阻塞。双击 bat 试用 AI 解读。
- 真连通性验证（能否从 10.135.136.21:8317 拿到 AI 响应）必须在 Owner 桌面做（pytest 全部 mock，不发真实请求）。
- 若点"生成解读"仍失败，AI 状态栏现在会给出明确错误（鉴权/404模型不支持/连接被拒/超时），把错误文字贴给我即可定位。
- ui_smoke_test.py 仍未纳入自动回归。
- meta_write.py 在 PowerShell 下 --stdin bug 待修；本轮元数据仍走 PowerShell UTF-8 无 BOM 直写。