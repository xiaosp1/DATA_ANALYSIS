# ADR-008 — git autocrlf=true + git stash 触发 LF→CRLF 隐式转换污染 PM meta 文件

- 日期：2026-07-15
- 状态：已记录（待 Owner 决定是否纳入 V1.13.0 git tag）
- 决策者：dataanalysis-pm（事件记录与修复建议） / 尘醒（Owner，`.gitattributes` 落地与 git tag 决策）

> **ADR 性质说明**：本 ADR 是从 ADR-007（三合一工具/流程异常登记）拆出的独立技术决策 ADR，专门记录并解决「git autocrlf=true + worker git stash 触发的 LF→CRLF 隐式转换」问题。ADR-007 事件 B 段是事件登记与应急处置的「症状面」，本 ADR-008 是「根因面 + 治本方案」。两者通过事件 ID 交叉引用，避免重复登记。

---

## 背景

2026-07-15 12:41（Asia/Shanghai）PM 端 `precheck` 跑 `ENCODING_SANITY` 命中 FAIL，发现 PM 工作空间根目录 7 个 meta 文件（`scripts/pm_turn_precheck.py` / `TODO.md` / `STATUS.md` / `ROADMAP.md` / `README.md` / `CHANGELOG.md` / `COMMITMENTS.md`）行尾从 LF 被外部进程改为 CRLF。12:43 PM 端用 python 临时脚本批量修复 19 个文件恢复 LF（无 BOM / utf-8），precheck 随即 PASS。

C030 investigator 完整调查（详见 `docs/proposals/2026-07-15-crlf-pollution-investigation.md`）以 **95% 置信度** 确认最可能污染源：

**S5-#3 coder 子代理在 09:16:39 Asia/Shanghai 执行 `git stash`，触发了 PM workspace 的 `core.autocrlf=true`（global + local 都设了）的 LF→CRLF 转换机制，把 working tree 中 6 个 PM 根 meta 文件从 LF 静默转成 CRLF。**

残留未修问题：`docs/architecture.md` 仍为 CRLF（278/278 行 CRLF，LastWriteTime 09:17:44）—— PM 12:43 批量修复时漏修，需后续补修。

---

## 事件时间线（Asia/Shanghai，节选）

| 时间 | 事件 | 关键证据 |
|------|------|----------|
| 09:16:39 | **S5-#3 coder 子代理在 `projects/dateanalysis-desktop` 子目录（同一 monorepo）跑 `git stash`** | transcript `fd7f1739` |
| 09:17:44 | `docs/architecture.md` LastWriteTime 落在 CRLF 状态 | `dir` 输出 |
| 09:46:07 | S5-#3 自己观察到 "the panel and main_window have CRLF (likely from git checkout)" | transcript `fd7f1739` |
| 12:41:23 | PM 跑 `pm_turn_precheck.py` | precheck |
| 12:41:49 | precheck ENCODING_SANITY FAIL：6 个 PM 根 meta 文件 + `pm_turn_precheck.py` 本身 CRLF | precheck 输出 |
| 12:42–12:43 | PM 用 python 临时脚本批量改 19 文件为 LF | `.tmp_lf.py` |
| 12:43 | precheck PASS | precheck |
| 14:43 | C030 investigator 落盘调查报告（含 .gitattributes 修复建议） | `docs/proposals/2026-07-15-crlf-pollution-investigation.md` |

**触发机制**（C030 自写复现脚本验证）：

1. `core.autocrlf=true` 时，Git 在 `git stash` 操作中会先把 working tree 当前内容保存到 stash，再 reset 回 HEAD 内容。
2. **HEAD 内容（LF）写入 working tree 时被 autocrlf 静默转为 CRLF**。
3. 即使 stash 后文件未改动（stash apply/pop 后内容与 HEAD 相同），working tree 也已经是 CRLF。
4. S5-#3 在子目录跑 `git stash` 等同于根目录运行（同一 monorepo）→ 6 个 PM 根 meta 文件被波及。

---

## 选项

### 选项 A：.gitattributes 强制 LF + precheck 扩扫 + worker git 约束（三件套，**选定**）

**三件套同时落地**：

1. **`.gitattributes` 强制 LF**：
   ```gitattributes
   # .gitattributes — 强制 LF，避免 core.autocrlf 隐式转换
   *.md   text eol=lf
   *.py   text eol=lf
   *.json text eol=lf
   *.txt  text eol=lf
   *.csv  text eol=lf
   *.bat  text eol=crlf  # Windows bat 必须 CRLF
   ```
   - `.gitattributes` 在新机器 clone 后立刻生效，优先级高于 `core.autocrlf`（推荐顺序 .gitattributes > local config > global config）

2. **`pm_turn_precheck.py` 的 `ENCODING_SANITY` 扫描范围扩展**：从「6 个 PM 根 meta」扩展到 `docs/**/*.md` + `memory/**/*.md` + 所有根目录 `.md/.py`，早发现文档子目录的 CRLF 污染。

3. **`pm-spawn-worker` SKILL.md 加 worker git 约束**：Worker **禁止**运行 `git stash` / `git checkout HEAD` / `git reset --hard` 等可能触发 autocrlf 转换的 git 操作；如必须 git stash，先 `git config core.autocrlf false` 或在临时目录跑。

### 选项 B：全局 `git config --global core.autocrlf false`

- 直接关闭隐式转换，治标不治本。
- 缺点：改变 100+ 已污染文件的换行状态，需要大批量改回，影响面太大；且 Owner 桌面/其他机器仍可能设 autocrlf=true，跨机不可靠。

### 选项 C：不改，依赖 precheck `ENCODING_SANITY` 早发现

- 仅靠 precheck 兜底，治标不治本。
- 缺点：每次污染都要人工介入修；precheck FAIL 时已经污染完成；下次 git stash / checkout / reset 还会再污染；CI 或 Owner 桌面执行 `python` / `git diff` 时仍可能爆（Windows 默认 CRLF 兼容场景下 git 误报 / `python` 脚本被卡 `\r`）。

---

## 决定

采用 **选项 A（三件套）**。

理由：

1. **三件套互补**：`.gitattributes` 治本（机器级强制 LF）+ precheck 兜底（早发现未扫到的子目录）+ worker 约束（避免再触发）。
2. **跨机一致性**：`.gitattributes` 随 repo 走，新机器 clone 立刻生效，不依赖全局 git config。
3. **代价可控**：`.gitattributes` 是 1 个新文件（< 200B），precheck 扩扫是 1 个脚本改动，worker 约束是 SKILL.md 加 1 条——三个改动都很小。
4. **可验证**：C032 完成后另开 investigator issue 验证 `.gitattributes` 在 Owner 全局 `core.autocrlf=true` 机器上确实生效（避免「.gitattributes 优先级不够」的潜在风险）。

### D1. `.gitattributes` 内容

```gitattributes
# Force LF for source/text files to override core.autocrlf
# See ADR-008: docs/adr/2026-07-15-git-autocrlf-meta-pollution.md
*.md   text eol=lf
*.py   text eol=lf
*.json text eol=lf
*.txt  text eol=lf
*.csv  text eol=lf
*.bat  text eol=crlf
```

### D2. precheck 扫描范围扩展

`pm_turn_precheck.py` 的 `ENCODING_SANITY` 检查当前扫描 6 个 PM 根 meta + `pm_turn_precheck.py` 本身。扩展后扫描：

- 根目录：所有 `.md`、`.py`（CHANGELOG / COMMITMENTS / README / ROADMAP / STATUS / TODO + pm_turn_precheck.py + pm_meta_write.py）
- `docs/**/*.md`（包括 docs/adr/*.md、docs/proposals/*.md、docs/architecture.md、docs/domain/**/*.md 等）
- `memory/**/*.md`（如果存在）
- `skills/**/*.md`（SKILL.md 系列）

实现方式：用 `pathlib.Path.rglob('*.md')` 替代硬编码列表 + 排除 `docs/domain/`（业务文档禁区，PM 不直接修）。

### D3. worker git 约束

在 `skills/pm-spawn-worker/SKILL.md` 的派工约束段加一条：

> Worker **禁止**在 PM workspace 内运行 `git stash` / `git checkout HEAD` / `git reset --hard` / `git restore` 等可能触发 `core.autocrlf` 隐式转换的 git 操作。如确需 stash 类操作，必须先在子 shell 跑 `git -c core.autocrlf=false stash`，避免污染 PM 工作树。

### D4. 残留漏修文件处置

`docs/architecture.md` 当前仍是 CRLF（278/278 行），PM 12:43 批量修复时漏修。处置：

- **本 ADR 落地前**：先单条 PM 操作修复 architecture.md 为 LF（不纳入三件套；P0 优先级，5 分钟）。
- **修复后**：跑 precheck 确认 PASS，归档「漏修补单」到 STATUS.md 异常登记段。

---

## 后果

### 正面

1. **下次 git stash / checkout / reset 不会再触发 LF→CRLF 隐式转换**——`.gitattributes` 在 commit 后立刻生效。
2. **跨机一致性**——新机器 clone（即使全局 `core.autocrlf=true`）也走 `.gitattributes` 强制 LF。
3. **precheck 早发现**——`docs/**/*.md` / `memory/**/*.md` 子目录的 CRLF 污染不再漏网。
4. **worker 收到明确约束**——避免 worker 再触发同类污染。
5. **PM 防御体系完整化**——`.gitattributes`（机器层）+ precheck（早发现）+ worker 约束（防触发）+ `pm_meta_write.py`（写时 LF）+ 业务禁区 `docs/domain/`（隔离保护）五重防护。

### 代价

1. **`.gitattributes` 新文件需 commit**——待 Owner 决定是否纳入 V1.13.0 git tag。
2. **precheck 扫描范围扩大**——运行时间会略增（从扫描 ~10 文件扩展到 ~30-50 文件），仍在秒级。
3. **`pm-spawn-worker` SKILL.md 需补一条 worker git 约束**——文档小改。

### 风险

1. **`.gitattributes` 在某些 git 版本下优先级可能不够**——如果 Owner 全局 `core.autocrlf=true`（机器级配置）未改，理论上有边缘情况优先级争议。**缓解**：C032 完成后另开 investigator issue，**实测验证** `.gitattributes` 在 Owner 桌面机器上确实生效（跑 `git stash` + 检查 working tree 仍是 LF）。
2. **precheck 扫描扩展可能误报**——`docs/domain/` 业务文档中如果存在合法的 CRLF 文件，扩展扫描可能误报。**缓解**：扫描时排除 `docs/domain/**`（业务禁区，PM 不直接修）。
3. **worker 约束可能影响 coder 正常工作流**——某些场景 coder 必须 stash。**缓解**：约束写「必须在子 shell 跑 `git -c core.autocrlf=false stash`」而非「禁止 stash」。

### 后续

1. **派 investigator 验证 `.gitattributes` 实际生效**（C032 完成后另开 issue 优先级 P1）。
2. **派 coder 落地 `.gitattributes` + precheck 扩扫**（C031 已在 STATUS.md 排队，待 Owner 拍板后派）。
3. **派 documenter 补 pm-spawn-worker SKILL.md 的 worker git 约束段**（同 C029 收尾或独立派）。
4. **补修漏修的 `docs/architecture.md`**（本 ADR 落地前单条 PM 操作优先修）。
5. **Owner 拍板 V1.13.0 git tag 是否纳入 `.gitattributes`**（P2，需桌面验证通过后再决定）。
6. **更新 ADR-007 事件 B 段为「已闭环」**——本 ADR 落地后，事件 B 根因已查实 + 治本方案已选，可在 ADR-007 事件 B 段状态改为「已闭环」，并 cross-reference 本 ADR。

---

## 参考

- **C030 调查报告**：`docs/proposals/2026-07-15-crlf-pollution-investigation.md`（95% 置信度根因 + P0/P1/P2 修复建议 + 5 方向排查 + 时间线）
- **ADR-007 事件 B 段**：`docs/adr/2026-07-15-skill-workshop-approve-timeout.md`（事件登记与应急处置的「症状面」，本 ADR 是「根因面」）
- **C031 修复实施**：commit hash 待 Owner 决定后补（`.gitattributes` + precheck 扩扫 + worker 约束三件套）
- **PM 防御体系**：
  - `scripts/pm_meta_write.py`（写时 LF 强制，2997B）
  - `scripts/pm_turn_precheck.py`（ENCODING_SANITY 早发现，39712B，C031 后扩扫到 docs/**/*.md）
  - `skills/pm-spawn-worker/SKILL.md`（worker 派工约束，C031 后加 git 约束）
  - `docs/domain/`（业务文档禁区，PM 不直接修，避免误改合法 CRLF 业务文档）
- **相关 ADR**：
  - ADR-007 事件 B：症状登记 + 应急处置（12:41-12:43 闭环，根因当时未明）
  - ADR-008（本 ADR）：根因 + 治本方案（C030 闭环后拆出）

---

## 变更历史

| 日期 | 版本 | 变更 | 作者 |
|------|------|------|------|
| 2026-07-15 | v1 | 初稿：从 ADR-007 事件 B 拆出独立 ADR，登记根因（git autocrlf=true + worker git stash）+ 三件套治本方案（.gitattributes + precheck 扩扫 + worker 约束） | documenter Worker（C032） |
