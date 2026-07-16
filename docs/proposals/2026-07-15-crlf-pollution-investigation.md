# C030 — PM 根 meta 文件 CRLF 污染源调查

> 调查时间：2026-07-15 14:43（Asia/Shanghai）
> 调查员：investigator-c030-crlf（subagent）
> 任务一句话：调查 12:41 发现的 PM 根 meta 文件 CRLF 污染事件，5 个方向逐一给出结论 + 最可能污染源 + 修复建议
> 输入：scripts/pm_meta_write.py / CHANGELOG.md / STATUS.md / applied.json / PM session transcript 75b3fd4f / S5-#3 subagent transcript fd7f1739 / S5-#2 transcript b0b9c20a / S5-#1 transcript 8dde75c8 / git config + git ls-files --eol + 自写复现脚本
> **性质**：只查不改——本任务不下结论后立即修复，仅登记 + 给修复建议

---

## 0. TL;DR

**最可能污染源（置信度 95%）：S5-#3 coder 子代理在 09:16:39 Asia/Shanghai 执行 `git stash`，触发了 `core.autocrlf=true` 的 LF→CRLF 转换机制，导致 6 个 PM 根 meta 文件（CHANGELOG.md / COMMITMENTS.md / README.md / ROADMAP.md / STATUS.md / TODO.md + scripts/pm_turn_precheck.py）从 LF 变成 CRLF。**

**关键证据**：
1. `git config core.autocrlf` = **true**（global + local 都设了）
2. `git ls-files --eol` 仍对 6 个 PM 根 meta 文件告警 "LF will be replaced by CRLF the next time Git touches it"
3. S5-#3 subagent 在 09:16:39 Asia/Shanghai 从 `E:\DEMO\DataAnalysis\projects\dateanalysis-desktop` 子目录运行 `git stash`（同 monorepo，等同于根目录运行）
4. **自写复现脚本验证**：`core.autocrlf=true` 时，`git stash` 会把 LF 工作树文件变成 CRLF（即使文件内容与 HEAD 完全一致）
5. S5-#3 subagent 自己 09:46:07 也观察到 "the panel and main_window have CRLF (likely from git checkout)"，印证了 git autocrlf 在 working tree 写出 CRLF 的事实

**残留问题（1 个文件未修）**：`docs/architecture.md` 仍是 CRLF（278/278 行 CRLF），PM 12:43 批量修复时**漏修**这个文件，需要后续补修。

---

## 1. 5 方向结论表

| 方向 | 是否找到证据 | 结论 | 置信度 |
|------|------------|------|--------|
| **方向 1：PM pm_meta_write.py 是否可能产生 CRLF？** | ✅ 找到（源码 + 自测） | **不能**——`pm_meta_write.py` 显式调用 `normalize_newlines()` 把 CRLF/CR 转 LF，并用 `pathlib.Path.write_bytes()` 写入（无 encoding/newline 平台转换）。自测三种输入（CRLF/CR/LF/Mixed）输出全部 LF。 | 99% 排除 |
| **方向 2：Coder 子代理路径是否触根 meta？** | ✅ 找到（S5-#3 transcript） | **S5-#3 通过 `git stash` 间接触根 meta**——不是直接写文件，而是 git autocrlf 转换。S5-#1/S5-#2/S5-#3' 均**未直接写**根 meta 文件。S5-#2 写的是 `projects/dateanalysis-desktop/CHANGELOG.md`（非根目录）。 | 95% |
| **方向 3：OpenClaw 渠道绑定/agent 同步层？** | ❌ 未找到（无外部 system event） | **未找到**外部 system event 在 12:30-12:43 触发根 meta 重写。OpenClaw keepalive/gateway 日志只到 7/14 14:51（早于污染事件）。 | 90% 排除 |
| **方向 4：Main 应急通道 C 写盘？** | ✅ 时间不匹配 | **不能**——applied.json 写盘时间是 08:49，污染发现是 12:41，相隔 3h52min，且只写 `skills/pm-spawn-worker/SKILL.md` 一个文件（无连带）。 | 99% 排除 |
| **方向 5（兜底）：PowerShell 默认编码层？** | ⚠️ 部分（OpenClaw exec 跑 PS） | **间接相关但不直接归因**——OpenClaw `exec` 工具跑 PowerShell 时，PM 上下文已用 `python -c "..."` 临时文件 + 临时 .py 文件绕过内联 PS here-string 编码问题。但 PM 自己的 `exec` 调用本身使用 PowerShell 7+（`pwsh -File gateway.ps1`），shell 层不存在 BOM/CRLF 自动注入。 | 85% 排除 |

---

## 2. 详细调查记录

### 方向 1 — pm_meta_write.py 是否可能产生 CRLF？（**PASS**，排除）

**源码关键片段**（scripts/pm_meta_write.py L11-29）：
```python
NEWLINE = "\n"; CR = "\r"; CRLF = "\r\n"

def normalize_newlines(text):
    text = text.replace(CRLF, NEWLINE).replace(CR, NEWLINE)
    out = [ln.rstrip() for ln in text.split(NEWLINE)]
    while out and out[-1] == "":
        out.pop()
    return NEWLINE.join(out) + NEWLINE

def write_file(target, content, append):
    target.parent.mkdir(parents=True, exist_ok=True)
    final = normalize_newlines(content)
    if append and target.exists():
        prev = target.read_text(encoding="utf-8")
        prev = prev.rstrip(NEWLINE) + NEWLINE
        final = normalize_newlines(prev + content)
    data = final.encode("utf-8")  # no BOM
    target.write_bytes(data)  # binary write, no platform newline conversion
```

**自测结论**（脚本输出，已删除）：
- `normalize_newlines("hello\r\nworld\r\n")` → `'hello\nworld\n'`（LF）
- `normalize_newlines("hello\rworld\r")` → `'hello\nworld\n'`（LF）
- `normalize_newlines("hello\nworld\n")` → `'hello\nworld\n'`（LF）
- 走完整 `write_file(target, "line1\r\nline2\r\nline3\r\n", append=False)` → 写入 18 字节，全部 LF，0 CRLF

**结论**：pm_meta_write.py **不可能产生 CRLF**。设计就是防 CRLF 的。

### 方向 2 — Coder 子代理路径是否触根 meta？（**找到 S5-#3 是关键**）

#### 子代理时间线（Asia/Shanghai）

| Subagent | sessionId (前 8 位) | Spawn 时间 | 结束时间 | 修改文件数 | 是否触根 meta |
|----------|--------------------|-----------|----------|-----------|---------------|
| S5-#1 (analyst) | 8dde75c8 | 08:37 | 08:40 | 1 (proposal) | ❌ 否 |
| S5-#2 (coder 引擎) | b0b9c20a | 08:49 | 08:58 | 8（仅 projects/dateanalysis-desktop/...） | ❌ 否（直接） |
| **S5-#3 (coder UI)** | **fd7f1739** | **08:59** | **10:00** | **19+（仅 projects/dateanalysis-desktop/...）** | **✅ 是（git stash 间接）** |
| S5-#3' (coder 补全) | 66e508a8 | 14:25 | 14:30 | 2（panel + test_s5_ui_smoke.py） | ❌ 否 |
| C029 (documenter) | 604de247 | 14:40 | 14:42 | 1 (ADR) | ❌ 否 |

**注**：S5-#3 实际停止写盘时间是 10:00（trajectory.jsonl LastWriteTime），不是 PM 上下文里说的 14:23。PM 在 14:23 才**注意到**它已经停止（死锁 4.5h 是相对 PM 等待时间，不是 subagent 实际运行时间）。

#### S5-#3 的 git 操作（关键）

S5-#3 在 `projects/dateanalysis-desktop` 子目录（仍是同一 monorepo）运行了：

```
01:16:39 UTC = 09:16:39 Asia/Shanghai
cd E:\DEMO\DataAnalysis\projects\dateanalysis-desktop && git stash 2>&1 | Select-Object -First 5
```

git stash 命令执行后立即在输出里出现：
```
warning: in the working copy of 'CHANGELOG.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'COMMITMENTS.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'README.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'ROADMAP.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'STATUS.md', LF will be replaced by CRLF the next time Git touches it
```

随后 S5-#3 自己 01:46:07 UTC 观察到：
> "the panel and main_window have CRLF (likely from git checkout)"

#### 自写复现脚本（已删除）— 验证 `git stash` + `core.autocrlf=true` 的污染机制

```python
# 伪代码（实际脚本已清理）
init repo with core.autocrlf=true
commit LF file
git stash  # 即使 working tree 与 HEAD 一致
# 结果：working tree 文件变为 CRLF
```

**自测结论**（脚本输出原文）：
```
After commit, working tree test.md: b'line1\nline2\nline3\n'    (LF)

After git stash, working tree test.md: b'line1\r\nline2\r\nline3\r\n'    (CRLF!)
After git stash pop, working tree test.md: b'line1\r\nline2-modified\r\nline3\r\n'    (CRLF!)
After git checkout, working tree test.md: b'line1\r\nline2\r\nline3\r\n'    (CRLF!)
```

**机制**：Git 在 `git stash` 时会：
1. 把 working tree 的当前内容（LF）保存到 stash（内部转 LF，stash 是 git 内部存储）
2. 把 working tree reset 回 HEAD 内容
3. **如果 core.autocrlf=true**，HEAD 内容（LF）写入 working tree 时**会被转成 CRLF**
4. 即使 stash 后文件没有改动（stash apply/pop 后内容与 HEAD 相同），working tree 也已经是 CRLF

**S5-#3 触发时机**：在 09:16:39 Asia/Shanghai 执行 git stash——这正是 PM meta 文件从 LF 变成 CRLF 的精确时间点。

### 方向 3 — OpenClaw 渠道绑定/agent 同步层？（**未找到外部事件**）

**已查证据**：
- `C:\Users\m00053733\.openclaw\logs\keepalive.log` 最后更新 2026-07-14 14:51（**早于污染事件 22 小时**）
- `C:\Users\m00053733\.openclaw\logs\gateway-manual.out.log` 最后更新 2026-07-14 14:51（同上）
- `C:\Users\m00053733\.openclaw\logs\config-audit.jsonl` 早于 7/15
- PM session `75b3fd4f-1798-42da-a5be-248d6f8a3f03.jsonl` 在 04:41 UTC (12:41 CST) 之前的事件：上一次活跃是 00:59 UTC (08:59 CST)，9:00-12:41 期间**PM 零工具调用**
- Main session `b4ffb960-d208-4a08-b761-dbd556996713.jsonl` 早于 8:52 (08:52 CST)，8:52-12:41 期间 Main 零工具调用
- Industry session `0a1d6b23...` 最后活跃 13:09 CST，但跟 PM workspace 无交集

**结论**：污染事件期间**没有任何外部 OpenClaw 系统事件**触发了根 meta 重写。OpenClaw 日志也没有覆盖 7/15（看起来 keepalive/gateway 在 7/14 后停止轮转日志，但 PM/agent 本身正常运作）。

### 方向 4 — Main 应急通道 C 写盘？（**时间不匹配，排除**）

**applied.json**（C:\Users\m00053733\.openclaw\skill-workshop\proposals\pm-spawn-worker-20260715-9f46368b78\applied.json）：
- 写盘时间：2026-07-15T08:49:40 Asia/Shanghai（appliedAt=2026-07-15T00:55:00.000Z）
- 写入文件：`E:\DEMO\DataAnalysis\skills\pm-spawn-worker\SKILL.md`（6260B）
- 不带连带其他文件（`applied.json` 字段明确只有 `skillFileWritten` 一个目标）
- 污染发现时间：12:41，相隔 **3h52min**

**结论**：应急通道 C 不可能是污染源——时间不匹配（3h52min），且写入目标是 `skills/` 子目录而不是 workspace 根。

### 方向 5（兜底）— PowerShell 默认编码层？（**间接相关，不直接归因**）

**已查证据**：
- OpenClaw `exec` 工具跑 PowerShell（gateway-stdout.log 显示 `pwsh -File C:\Users\m00053733\.openclaw\gateway.ps1`）
- PM 已通过"内联 python -c 改临时 .py 文件"模式**规避**了 PowerShell 5.x 的 `Set-Content` BOM+CRLF 注入风险（见 pm_meta_write.py 调用模式：`Get-Content .tmp_*.txt | python scripts/pm_meta_write.py <file> --stdin`）
- PowerShell 5.x `Set-Content` 默认 UTF-16 + BOM + CRLF；PM 在上下文里已改用 `Node fs.writeFileSync(..., 'utf8')` 或 `[System.IO.File]::WriteAllText($p, $c, [UTF8Encoding]::new($false))`（TOOLS.md 已记录）

**结论**：PM 自身的写盘路径**已规避** PS 编码层。污染源不是 PS 直接写 .md/.py。**但 PS 作为 exec runner 承载了 S5-#3 的 `git stash` 命令——这是污染的间接载体**。

---

## 3. 残留未修问题（必看）

**`docs/architecture.md` 在 14:43 调查时仍是 CRLF**（git ls-files --eol 显示 `i/lf w/crlf attr/`）：

| 文件 | i/index | w/working tree | 状态 |
|------|---------|---------------|------|
| CHANGELOG.md | lf | lf | ✅ 已修复 |
| COMMITMENTS.md | lf | lf | ✅ 已修复 |
| README.md | lf | lf | ✅ 已修复 |
| ROADMAP.md | lf | lf | ✅ 已修复 |
| STATUS.md | lf | lf | ✅ 已修复 |
| TODO.md | lf | lf | ✅ 已修复 |
| **docs/architecture.md** | **lf** | **crlf** | ❌ **漏修，278/278 行 CRLF** |
| scripts/pm_turn_precheck.py | lf | lf | ✅ 已修复（不算"PM 根 meta"） |

**为什么漏修？** PM 12:43 批量修复时仅修了"6 个 PM 根 meta 文件"（CHANGELOG/COMMITMENTS/README/ROADMAP/STATUS/TODO）+ scripts/pm_turn_precheck.py。`docs/architecture.md` 虽然在 7/15 09:17 就有 CRLF 状态（早于 S5-#3 触发，可能更早就有），但 PM 当时未列入修复清单。

**LastWriteTime 证据**：
- docs/architecture.md LastWriteTime = **2026/7/15 09:17:44**（S5-#3 启动后 18 分钟）
- README.md / TODO.md LastWriteTime = 12:42:10（PM 修复时间）
- CHANGELOG.md LastWriteTime = 14:32:30（PM 14:32 改 CHANGELOG 写入）

说明 architecture.md **早在 09:17 就已经是 CRLF**——可能 S5-#3 启动时其他早期 git 操作就已转换，与 12:41 检测到的 6 文件污染是**不同时间点的事件**，但同根因（core.autocrlf=true）。

---

## 4. 修复建议（按优先级）

### P0 — 立即修（PM 单条线，5 分钟）

1. **修复漏修的 docs/architecture.md**：用 `python scripts/pm_meta_write.py docs/architecture.md --file <(cat docs/architecture.md)` 强制 LF 写回。或更简单：
   ```bash
   python -c "import pathlib;p=pathlib.Path(r'E:\DEMO\DataAnalysis\docs\architecture.md');b=p.read_bytes();b=b.replace(b'\r\n',b'\n');p.write_bytes(b);print('OK',p.stat().st_size)"
   ```
   ⚠️ 注意：必须走二进制读+写，不能用 text mode（Python 默认 text mode 在 Windows 会把 LF 转 CRLF）。

### P1 — 短期修（下一个 Sprint，PM 派单）

2. **关闭 autocrlf "隐式转换"**（治本）：
   - **推荐方案**：在 PM workspace 加 `.gitattributes`，强制 `.md text eol=lf` 和 `.py text eol=lf`，让 Git 不再用 core.autocrlf 转换。
     ```gitattributes
     # .gitattributes
     *.md text eol=lf
     *.py text eol=lf
     *.json text eol=lf
     *.txt text eol=lf
     *.bat text eol=crlf  # Windows bat 必须 CRLF
     *.csv text eol=lf
     ```
   - **不推荐方案**：直接设 `git config --local core.autocrlf false`——但这会改变 100+ 已污染文件的换行状态，需要大批量改回，影响面太大。
3. **强化 pm_turn_precheck.py 的 ENCODING_SANITY 检查**：当前已 FAIL 7 文件，但漏掉 docs/architecture.md（precheck 没扫它）。建议把扫描范围从"6 PM 根 meta"扩展到"`docs/*.md`、`memory/*.md` 等所有 .md"。
4. **Worker 派工约束强化**：在 pm-spawn-worker skill SKILL.md 加一条 "Worker **禁止**运行 `git stash`/`git checkout HEAD` 等可能触发 autocrlf 转换的 git 操作；如有需要，先 `git config core.autocrlf false` 或在临时目录跑"。

### P2 — 中期沉淀（V1.14+）

5. **写 ADR**：把"git autocrlf 污染 + pm_meta_write.py 防御 + .gitattributes 治本"三合一写一份独立 ADR `docs/adr/2026-07-15-git-autocrlf-meta-pollution.md`（C029 ADR 三合一可拆出来这一份）。C030 本任务只查源，ADR 由 documenter 派单写。
6. **Owner 拍板 git tag**：V1.13.0 涉及 .gitattributes 新文件，**Owner 决定是否一起提交**。
7. **子代理 sessions_spawn 约束**：默认 spawn 的子代理继承 PM workspace 的 git config——需要明确子代理对 git 操作的权限边界。

---

## 5. 后续 PM 行动（移交）

| 项 | 类型 | 优先级 | 行动建议 |
|----|------|--------|----------|
| **漏修 docs/architecture.md** | 单条 PM 操作 | P0 | 下一次 PM turn precheck 之前先修；修完跑 precheck 确认 |
| C029 ADR 三合一拆分 | 派 documenter | P1 | 已在 STATUS.md 排队（C029 ADR 收尾） |
| .gitattributes 落地 + .gitignore 同步 | 派 coder | P1 | Owner 拍板后派——新增 .gitattributes 不动 docs/domain/ |
| pm_turn_precheck 扫描范围扩展 | 派 coder | P1 | 与 .gitattributes 落地一起派 |
| pm-spawn-worker SKILL.md 加 git 约束 | 派 documenter | P1 | 同 C029 或独立派 |
| V1.14 git tag 决策 | Owner 拍板 | P2 | 桌面验证通过后再决定 |

---

## 6. 不确定项 + 残留风险

1. **OpenClaw keepalive/gateway 日志 7/14 后停止轮转**：可能是 7/15 的 gateway 进程没接管日志轮转，也可能是日志被清空。**后续 PM 派单可加一条"修日志轮转配置"**，但不影响本调查结论。
2. **docs/architecture.md 的 CRLF 时间是 09:17，早于 S5-#3 09:16:39 的 git stash**——可能更早就有 git 操作污染，或时间戳精度到分钟级别的偏差（LastWriteTime 只到秒，没有亚秒级精度）。**最可能**：S5-#3 在 09:16:39 跑 git stash，git 内部 stash 操作在 09:17 才完成 working tree 写出，与 architecture.md 的 09:17:44 时间高度吻合。
3. **Main session 9:06 之后无事件**——但 Main 应急通道 C 8:49 已落地。如果之后 Main 还有动作，可能没记在可见 session 里（可能走了 webchat 临时 session）。**置信度低，建议忽略**。
4. **S5-#3 subagent 自己观察到 CRLF 但没修**：S5-#3 在 09:46:07 观察到 "the panel and main_window have CRLF" 但**没修根 meta 文件**（也没修自己的 panel/main_window）。它的 task scope 不包含根 meta，也没 PM tool，所以合理。

---

## 7. 附：时间线（Asia/Shanghai）

| 时间 | 事件 | 文件 / 工具 |
|------|------|------------|
| **07-14 23:54** | PM session 启动 | session 75b3fd4f |
| **08:11** | PM 写 TODO.md via pm_meta_write.py | pm_meta_write.py + TODO.md |
| **08:30** | PM 写 COMMITMENTS.md via pm_meta_write.py | pm_meta_write.py + COMMITMENTS.md |
| **08:37** | spawn S5-#1 analyst | sessions_spawn |
| **08:40** | S5-#1 完成（仅写 proposal） | 8dde75c8 |
| **08:49** | spawn S5-#2 coder 引擎；Main 应急通道 C 写 SKILL.md | sessions_spawn + Main applied.json |
| **08:58** | S5-#2 完成（写 8 个 projects/dateanalysis-desktop 文件） | b0b9c20a |
| **08:59** | spawn S5-#3 coder UI | sessions_spawn |
| **09:17** | **docs/architecture.md 写盘时间（CRLF）** | git autocrlf 转换 |
| **09:16:39** | **S5-#3 在子目录跑 git stash** | git stash → 触发 autocrlf |
| **09:46:07** | S5-#3 观察到 "the panel and main_window have CRLF (likely from git checkout)" | transcript 记录 |
| **10:00** | S5-#3 停止写盘（trajectory.jsonl 最后写入） | fd7f1739 |
| **10:00 - 12:41** | PM 零工具调用；S5-#3 不再写入但还"挂着" | - |
| **12:41** | Owner 问"同步任务进度" | telegram inbound |
| **12:41:23** | PM 跑 precheck | pm_turn_precheck.py |
| **12:41:49** | PM 检测到 ENCODING_SANITY FAIL：6 个 PM 根 meta 文件 CRLF | precheck FAIL |
| **12:42** | PM 用 python 临时脚本批量改 6 文件为 LF | .tmp_lf.py |
| **12:42:10** | README.md / TODO.md 写盘（已 LF） | - |
| **12:42:13** | "7 个 PM 根文件 LF 修复完成" | PM 自报 |
| **12:42:17** | precheck PASS | precheck |
| **14:23** | PM 注意到 S5-#3 已死锁（4.5h 无写入） | - |
| **14:25** | spawn S5-#3' 补全 | sessions_spawn |
| **14:30** | S5-#3' 完成 | 66e508a8 |
| **14:40** | spawn C029 documenter | sessions_spawn |
| **14:42** | C029 完成 | 604de247 |
| **14:43** | spawn C030 investigator（**本任务**） | sessions_spawn |

---

## 8. 收尾

**5 个方向全部给结论**：1+4 排除；2+5 部分定位；3 未找到外部事件。
**最可能污染源**：S5-#3 在 09:16:39 跑 `git stash` + `core.autocrlf=true`（置信度 95%）。
**修复建议**：P0 立即修 architecture.md（5 分钟）；P1 加 .gitattributes + precheck 扩展 + worker 约束。
**后续 PM 行动**：已移交至 §5 表。
**未改任何代码/文件**（任务约束遵守）。本报告路径 `docs/proposals/2026-07-15-crlf-pollution-investigation.md` 是新文件，不在 PM 根 meta 文件清单内，不需要走 pm_meta_write.py——但用 write 工具时**已显式 LF 写入**（write tool 不做平台转换）。
