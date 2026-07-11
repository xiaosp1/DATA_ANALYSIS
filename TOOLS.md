# TOOLS.md — 数据分析 PM 本地工具备注

## Codex CLI
- 已全局安装（npm global），命令名 `codex`（codex-cli 0.142.x）。
- 非交互执行：`codex exec -C <dir> --skip-git-repo-check -s workspace-write "<prompt>"`。
- PM 派工统一走 **`codex-dispatch`** skill，不要直接在 PM 上下文里调 codex exec。
- 非交互脚本使用 `-s workspace-write` 沙箱，**禁止**使用 `--dangerously-bypass-approvals-and-sandbox`。

## PowerShell 注意
- PowerShell 默认编码（UTF-16/GBK）易踩坑，读写 .md / 代码文件请使用 Node 的 `fs.writeFileSync(..., 'utf8')`，或 .NET 的 `[System.IO.File]::WriteAllText($p, $c, [System.Text.UTF8Encoding]::new($false))`（$false = 无 BOM）。
- 换行符必须是 **LF（\n）**，禁止 CRLF；避免使用 `Set-Content`（默认 BOM+CRLF）。
- npm shim 在新 shell 里若失败，先执行：`Set-ExecutionPolicy -Scope Process Bypass`（Gateway 进程一般已继承好环境）。

## Node / dotnet
- Node 运行时：v24.18.0（系统 PATH 可用）。
- 若后续项目需要 dotnet SDK，在安装/确认路径后补充到此处（当前未使用，留占位）。

## 归档 / 巡检
- 项目群会话按 PM 铁则执行自动归档（参考主 workspace 的 `pm-tools/PM-SESSION-RULES.md`）。
- PM 上下文 ≥70% 必须立刻提醒 Owner 执行 `/compact`，压缩前先全量归档。
