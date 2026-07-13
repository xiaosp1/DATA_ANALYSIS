# W12 机尾指数-s 归因分析模式（方案B）交付说明

## 做了什么
1. **新模块 `app/services/head_tail_attribution.py`**：纯函数 `build_head_tail_report(df, target_col, ..., report_progress=None)`，在已合并好的 [机头]/[机尾] 宽表上：
   - 自动识别 `[机头]*` 数值列作为特征，`[机尾]指数-s` 作为目标
   - 理想区间判定：`|target-4| ≤ 0.5` 视为"近理想"
   - 逐特征 pairwise 计算 Pearson / Spearman 相关系数
   - 对 Top N 特征做理想/偏离分组 μ±σ 窗口 + 五分位桶分析
   - 用三分位切点做单特征阈值规则挖掘（避免跑决策树导致卡顿）
   - 综合 Top3 特征输出 `overall_suggested_window`
   - 全程通过 `report_progress(pct, msg)` 回调上报进度（10→40→70→90→100）
   - scipy 可选；缺失时 fallback 到 numpy 手工实现 Spearman（平均秩 + Pearson on ranks）

2. **`app/services/ai_prompt.py`** 新增 `build_head_tail_prompt(report)`：
   - 专用 SYSTEM_PROMPT，4 段式结构（核心结论 / Top3 量化 / 推荐窗口 / 风险与下一步）
   - user prompt 只传聚合统计（相关系数表、Top 规则、综合窗口、警告），不传原始行

3. **`app/services/process_analysis.py`** 给 `build_analysis_report` 增加可选 `progress_callback=None` 参数，在 10/40/75/95 四个关键节点粗粒度上报，修复 W12 P0-1（旧模式进度条不动）。

4. **`app/ui/widgets/process_analysis_panel.py`**：
   - 顶部新增"分析模式"QComboBox：「状态分类（原工艺窗口）」/「机尾指数-s归因」
   - 新模式下自动禁用状态列/目标状态区、特征列过滤为 `[机头]*` 前缀
   - 新增"归因结果"Tab：摘要 + Top 特征表（N/Pearson/Spearman/方向/理想μ±σ/推荐窗口）+ 规则文本
   - `set_result(rep, mode=...)` 按模式走不同渲染路径；旧模式完全保持原有箱线图/摘要/窗口/规则/重要性视图
   - 导出按钮在新模式下导出 attribution CSV（特征/Pearson/Spearman/方向/理想窗口/偏离窗口）

5. **`app/ui/main_window.py`**：
   - `_on_process_analysis_requested` 按 `config["mode"]` 分发：`state_classify` 走原有流程（带 rp 回调）；`head_tail_attr` 校验列前缀并调用新引擎
   - `_on_ai_insight_requested` 按当前模式选 `build_insight_prompt`/`build_head_tail_prompt`
   - `_on_process_analysis_export` 拆分 `_export_state_classify_csv`/`_export_head_tail_csv`，新模式不弹箱线图导出
   - 所有重计算仍在 Worker 线程（`_run_background` 的 `do_work`），`on_success` 仅做 widget 组装

6. **`requirements.txt`**：追加 `scipy>=1.10,<2.0`、`xlrd==1.2.0`（P0-3：老 .xls 读取）。

7. **测试 `tests/test_w12_head_tail_attribution.py`**：8 个用例覆盖
   - 强相关/噪声列排名正确
   - 理想窗口均值/推荐区间合理
   - 缺目标列/缺机头列抛错
   - 进度回调按阶段触发
   - 目标分布/规则结构正确
   - prompt 关键字段出现、不含原始行
   - 显式传 feature_cols 子集生效

## 验证
- `pytest tests/ -q -W error --ignore=tests/ui_smoke_test.py --ignore=tests/run_functional_tests.py`
  → **116 passed in 12.61s**（原 108 + 新 8，未退化）
- `QT_QPA_PLATFORM=offscreen` 下 UI 模块可正常实例化、模式切换逻辑正确
- 合成数据端到端验证：f1 强负/正相关排名第一，规则命中高近理想率切点，综合窗口落于模拟值附近

## 已知限制 / 后续可做
- V1 归因结果用 QTableWidget + QPlainTextEdit 展示，未做 pyqtgraph 横向条形图/相关系数热图；后续可美化。
- 单特征规则只在三分位+中位数切点搜索，不是完整决策树（性能优先，避免大数据集卡顿）；若后续要更高精度规则再考虑 CART。
- Spearman 的 numpy fallback 是平均秩实现，与 scipy 结果在并列秩很多时会有小数级差异（已用合成数据验证方向和排序一致）。
- 未做交互"先跨类合并"引导按钮；当前用红字提示 + 禁用「开始分析」按钮。
- 新模式导出 CSV 不导出 PNG（没有箱线图）；后续若加相关条形图可追加导出。

## W12.1 AI锁与超时修复

### 问题
- AI 解读 HTTP 请求耗时 60s+，期间 `main_window._busy=True` 把所有按钮（切Tab/看数据/调配置/导入）全部锁死，弹"有任务正在执行，请等待完成后再试"
- 全局 QProgressDialog 取消按钮被 `setCancelButton(None)` 禁掉，用户无法中断 AI 请求；进度条 0% 不动，像卡死
- 默认 `timeout=60s` 偏长且错误信息未指向"可重试/检查网络/VPN"

### 改动
1. **`app/services/ai_client.py`**
   - 默认 `timeout` 60s → **30s**，并提供显式 timeout 参数校验（None 回退 30s）
   - 新增 `AICancelledError`（继承 `AIClientError`）
   - `chat()` 新增可选 `cancel_event: threading.Event` 参数，在构造请求前、urlopen 之后、读完响应之后各检查一次；若已 set 则抛 `AICancelledError("用户已取消")`
   - 超时错误文案改为："请求超时（30s），可点重试；若多次超时请检查 base_url 是否可达、VPN/办公网是否正常"
   - 注意：urllib 阻塞读期间无法强杀线程，"取消"是**软取消**——UI 立即恢复，后台线程跑到超时/完成后结果被丢弃

2. **`app/ui/main_window.py`**（粒度锁拆分）
   - 把单一 `self._busy` 拆成两把锁：
     - `self._dataset_busy`：保护会改数据集的操作（导入/文件夹导入/类别导入/切换激活/合并/数据处理），彼此互斥
     - `self._analysis_busy`：保护分析/绘图/描述统计/工艺分析（state_classify 与 head_tail_attr 同锁，避免 QProgressDialog 复用冲突），同一时刻只跑一个
   - AI 请求走 **`busy_lock="none"`**，不占任何全局锁，不弹全局 QProgressDialog；状态/按钮由 ProcessAnalysisPanel 自管，期间用户可自由切 Tab、调配置、看数据、切换激活数据集
   - `_set_busy(lock, busy, label)` 改成按锁操作；同一时刻只弹一个 QProgressDialog（dataset 或 analysis 谁先启动谁占）；dataset/analysis 之间**互不阻塞**
   - 全局进度条的取消按钮恢复为"后台继续"（点击仅收起弹窗视觉，不强杀线程）
   - `_on_ai_insight_requested`：在 UI 线程创建 `threading.Event` 作为 cancel_event，通过 `panel.set_ai_cancel_callback(lambda: evt.set())` 注入；用 `req_id = id(evt)` 与 `self._ai_cancel_event` 做过期丢弃——用户点停止或发起新请求后，旧线程回来的结果直接丢弃
   - on_error 用"用户已取消"子串识别取消（Worker 把 exception 转成 str，丢失类型信息），取消时面板显示"已取消"而非失败红字
   - `_clear_all` 会 set 掉已有 cancel_event，避免清空后旧请求回来污染 UI

3. **`app/ui/widgets/process_analysis_panel.py`**
   - AI 按钮行新增 **「停止」** 按钮 `ai_cancel_btn`，默认 disabled；发起 AI 请求时 enable，完成/失败/取消/清数据时 disable
   - 新增 `_ai_running` 状态位；`_emit_ai_insight` 先检查是否已有请求在跑，避免重入
   - 新增 `set_ai_cancel_callback(fn)` 纯 Python 回调（面板不依赖 threading），停止按钮点击时调 callback 并显示"已请求停止..."
   - 新增 `set_ai_finished()`，统一在 AI 成功/失败/取消后清 `_ai_running`、禁用停止按钮、按 key+report 重新刷新生成按钮状态
   - `set_ai_result()` 改为调用 `set_ai_finished()`（旧代码 on_success 路径漏了恢复按钮 enable，修复）
   - `set_dataset()` 重置 `_ai_running=False`，避免切数据后按钮状态残留
   - 请求开始时状态栏文案升级为"请求中...（endpoint:xxx 模型:xxx，最多等 30s，可点『停止』）"

4. **测试 `tests/test_w12_ai_busy_fix.py`**（9 个用例）
   - AIClient 默认 timeout=30s
   - pre-set cancel_event 立即抛 AICancelledError
   - urlopen 返回后 cancel_event.set 也抛 AICancelledError
   - socket.timeout 错误文案含"30s"/"重试"/"VPN"
   - HTTPError 不泄露 API Key
   - success 路径在 cancel_event 未 set 时正常返回
   - 面板存在停止按钮且初始 disabled
   - 停止按钮回调被调用、状态显示"已请求停止"
   - `set_ai_finished()` 恢复按钮并禁用停止按钮

### 不改的
- Worker / QThreadPool 线程模型未动，未引入 asyncio
- head_tail_attribution / process_analysis 引擎 0 改动
- dataset 操作间仍互斥；analysis 操作间仍互斥（同一时刻只跑一个，面板级状态栏提示"有分析任务正在执行"）

### 验证
- `pytest tests/ -q -W error --ignore=tests/ui_smoke_test.py --ignore=tests/run_functional_tests.py`
  → **125 passed in 10.36s**（原 116 + 新 9，0 退化）
- AI 请求期间可自由切 Tab/勾选特征/切换激活/调粒度；"再点一次 AI"会被面板自管状态拦下；"开始工艺分析"会被 analysis 锁拦下（状态栏提示"有分析任务正在执行，请稍候再试"），不弹 QMessageBox
- 点「停止」按钮后，按钮立即恢复可点，状态显示"已取消"；后台 urllib 线程在 30s 内自然结束，结果被丢弃
- 断网/base_url 不通时，30s 内必定返回并显示带"重试/VPN"提示的红字

### 已知限制
- urllib 阻塞读无法真正强杀线程，点击"停止"只是软取消——线程会在后台继续跑到 timeout/响应返回，但其结果会被 `req_id` 比对丢弃，不影响 UI。若后续要真正中断，可改用 `requests` with streaming/chunked 并在循环里检查 event，或用 `QNetworkAccessManager` 支持 abort。

## W12.2 AI超时可配置

### 需求
Owner 希望自己填 AI 请求的超时时间，不要硬编码 30s；网络慢/内网代理场景可调大。

### 改动
1. **`app/ui/widgets/process_analysis_panel.py`**
   - AI 工具栏新增 **"超时(s)"标签 + QSpinBox**，范围 5~300 秒，步长 5，默认 30
   - Tooltip：`AI 请求最长等待时间（秒），超时后提示失败。网络慢/内网代理可适当调大。`
   - QSettings 持久化 key：`ai_timeout_sec`，下次启动记住用户设的值
   - 放在第三行（与 Base URL 并列左对齐），保持第一行 提供商/模型、第二行 Base URL 的 3 行布局结构，不破坏 Dock 最小宽度
   - 提供 `ai_timeout_sec() -> int` 方法返回当前值（带 5~300 边界保护）
   - SpinBox 在 AI 请求期间禁用（和 provider/base_url/model/配置Key 一致），完成/失败/停止后恢复
   - `ai_insight_requested` 信号签名从 `(str, str, str, str)` 扩展为 `(str, str, str, str, int)`，第 5 个参数为 `timeout_sec`
   - 状态栏文案改为动态：`最多等{timeout_sec}s`

2. **`app/ui/main_window.py`**
   - `_on_ai_insight_requested` 槽函数增加第 5 个参数 `timeout_sec`，带 int 转换与 5~300 边界保护
   - 构造 `AIClient` 时传 `timeout=float(_timeout_sec)` 而不是硬编码 30.0
   - 其余逻辑（cancel_event / req_id / 双锁 / none 锁 / 停止按钮 / 错误脱敏）完全不变

3. **`app/services/ai_client.py`**
   - `__init__` 的 `timeout` 参数增加防御性 fallback：`0 / None / 负数 / NaN / 非数字字符串` 一律回退到 30.0
   - 原有签名兼容，外部传 `timeout=60` 仍然直接生效

4. **测试 `tests/test_w12_ai_busy_fix.py`**（在原有 9 个用例基础上追加）
   - 扩展 `test_default_timeout_is_30s`：新增 timeout=0 / -5 / "abc" 三种非法输入均回退 30.0 的断言

### DoD 验证
- `pytest tests/ -q -W error --ignore=tests/ui_smoke_test.py --ignore=tests/run_functional_tests.py`
  → **125 passed in 16.09s**（0 退化，0 新增失败）
- 代码改动文件数：**3 个源码 + 1 个测试 = 4 个**（含测试，符合 ≤4 文件约束）
- 右 Dock 最小宽度仍为 400px（`test_dock_minimum_widths` 通过），3 行布局未破坏
- SpinBox 默认值 30，QSettings 持久化，重启后保留
- 填 60 → AIClient.timeout=60.0；填 5 → 5.0；填 0 → fallback 30.0
- AI 请求期间 spin/provider/base_url/model/配置Key 全部禁用，完成后恢复
- 向后兼容：生成解读 / 重新生成 / 停止 / 双锁 / 取消 / 错误脱敏 / 机尾归因模式全部不坏

### 已知限制
- 超时仅作用于单次 HTTP 请求整体（含连接+读），不是流式分块超时；若后续切到 streaming 再细化。
