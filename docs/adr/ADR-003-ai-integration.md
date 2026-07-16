# ADR-003 — AI 集成方案

- 日期：2026-07-13
- 状态：Accepted
- 决策者：尘醒（Owner）/ dataanalysis-pm

## 背景
工艺窗口分析和机尾归因分析产生聚合统计报告后，需要向工艺工程师提供 AI 增强的解读能力。设计要求：
1. AI 请求不阻塞 UI 主线程；
2. 支持用户随时取消正在进行中的 AI 请求；
3. 支持多提供商（OpenAI、DeepSeek、自定义 base_url）；
4. API Key 不硬编码在代码中，需外部配置；
5. 慢网络环境下（如慢代理分块返回）能正确超时，不会无限挂起。

## 选项

### 选项 A：requests + 全局取消标志
- 使用 `requests` 库，通过全局 `threading.Event` 轮询取消
- 优点：API 简洁
- 缺点：需要额外依赖；取消只能轮询检查，无法真正中断 socket 读

### 选项 B：urllib + watchdog 线程 + 软取消
- 使用 Python 标准库 `urllib.request`（无需额外依赖）
- 用 watchdog 线程做硬总超时（deadline 到则关 socket）
- 用户取消通过 `threading.Event` 传递，在请求各阶段检查后抛出 `AICancelledError`
- 优点：零额外依赖；硬超时真正关闭 socket；取消响应迅速
- 缺点：需手动处理 HTTPError 解析、socket close 的异常边界

### 选项 C：aiohttp 异步
- 使用异步 HTTP 客户端
- 优点：真正的异步取消
- 缺点：需引入 asyncio 复杂化现有同步线程模型；PySide6 事件循环与 asyncio 集成成本

## 决定
采用 **选项 B**（stdlib urllib + watchdog 硬超时 + 软取消）。

### D1. 配置加载链（优先级从高到低）
1. **QSettings** 用户偏好值（`ai_base_url` / `ai_model` / `ai_api_key`）
2. **ai_config.json**（项目级，位于启动工作目录）：
   ```json
   {
     "providers": {
       "openai":   {"base_url": "...", "model": "...", "api_key": "..."},
       "deepseek": {"base_url": "...", "model": "...", "api_key": "..."}
     }
   }
   ```
3. **~/.codex/config.toml**（通过 `tomllib` 读取 `openai_base_url` / `model`）
4. **环境变量**：`OPENAI_BASE_URL` / `OPENAI_API_BASE` / `OPENAI_MODEL` / `OPENAI_API_KEY`
5. **默认值**：`https://api.openai.com/v1`, `gpt-4o-mini`

### D2. 取消机制设计
- **硬超时（watchdog）**：构造 `AIClient` 时设定 `timeout`（默认 30s）。发起请求时启动 daemon 线程，在 `timeout` 秒后关闭底层 socket，强制 `urlopen/resp.read` 抛出 `TimeoutError/URLError`。确保总耗时 ≤ timeout。
- **软取消（cancel_event）**：`AIClient.chat()` 接受 `cancel_event: threading.Event | None`。在请求前、读取中、解析后各阶段检查 `cancel_event.is_set()`，若已设置则立即抛出 `AICancelledError`。此异常被上层捕获后清理 watchdog 线程。
- **双锁拆分**：AI 请求不占用全局 `_dataset_busy` / `_analysis_busy` 锁，面板自行管理 `is_ai_busy` 状态。AI 请求可与 dataset/analysis 操作并行执行。

### D3. 错误分类
```
HTTP 401/403  → "鉴权失败，请检查 API Key 是否正确"
HTTP 404      → "接口不存在，可能是 base_url 路径错误或模型不被支持"
HTTP 429      → "请求被限流，稍后重试"
HTTP 5xx      → "服务端错误" + 服务端 detail
TimeoutError  → "请求超时，可调整超时设置"
URLError      → 检测 reason 文本：
                  - "timed out" / "closed" / "broken pipe" / "connection reset" → 按超时处理
                  - "refused" / "getaddrinfo" / "network is unreachable" → 连接不可达提示
                  - 其他 → "网络错误（<type>）"
```

### D4. 可配置超时
- `AIClient(timeout=30.0)` 支持构造时指定超时秒数
- UI 面板中可配置超时值（当前默认 30 秒）
- watchdog 线程在 deadline 到达后执行 socket close 的异常边界全部 catch+pass

## 后果

### 正面
- **零 HTTP 客户端依赖**：使用 stdlib urllib，不引入 requests/aiohttp 依赖
- **真正的硬超时**：watchdog 线程直接关 socket，不依赖 urllib 的 connect/read 单次超时
- **快速取消**：cancel_event 在各阶段被检查，用户点"取消"后 AI 请求快速响应退出
- **错误语义清晰**：AI panel 可根据错误类型展示不同提示，不暴露 API Key 内容
- **多提供商**：preset 机制（openai/deepseek/custom）支持灵活切换

### 负面
- **urllib 无超时重试**：需上层自行实现重试逻辑（当前未实现，视为技术债）
- **无流式响应**：等待完整 JSON 响应后解析，大响应可能占用较多内存
- **socket close 非优雅**：watchdog 关 socket 可能导致 `BadStatusLine` 等异常，已统一归入超时类处理
- **tomllib 仅 Python 3.11+**：若回退到 3.10 需改用 `tomli`

## 验证
- `tests/test_w11_ai_config.py`（116 行）：AI 配置加载链
- `tests/test_w8b_ai.py`（214 行）：AI 客户端功能
- `tests/test_w12_ai_busy_fix.py`（160 行）：AI 忙状态修复
