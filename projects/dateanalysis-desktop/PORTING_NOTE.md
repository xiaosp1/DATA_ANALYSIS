# PORTING_NOTE — DateAnalysis 桌面软件迁移记录

> 迁移时间：2026-07-10 21:15 (Asia/Shanghai)
> 执行人：数据分析 PM (dataanalysis-pm)

## 迁移源 → 目标
- **源路径（历史工作目录）**：`E:\DEMO\DateAnalysis`（Codex CLI 在 2026-06-29 ~ 2026-07-07 期间开发）
- **目标路径（当前 PM 工作空间下）**：`E:\DEMO\DataAnalysis\projects\dateanalysis-desktop`
- **原路径现状**：保留不动，不删除、不改写，作为回退副本；后续确认无回归后由 Owner 决定是否清理。

## 复制范围
- ✅ 复制：`app/`（全部源码）、`docs/`（需求/开发/方法论）、`tests/`（功能/单元/冒烟测试 + 测试数据）、`sample_data/`
- ✅ 根级文档：`README.md`、`requirements.txt`、`PROJECT.md`（SSOT）、`PROJECT_OVERVIEW.md`、`CONTEXT_MEMORY.md`、`ROADMAP.md`、`STATUS.md`、`_codex_brief.md`、`学习日志.md`、`草稿.md`、`.gitignore`
- ❌ 未复制（运行态/可再生物）：`.venv/`、`.git/`、`logs/`、`_screenshots/`、`__pycache__/`、`*.pyc`、`tests/ui_smoke_out/`（上一次冒烟输出 PNG/CSV）

## 复制验收
- 文件数：68
- 总字节数：1,412,683（约 1.35 MiB）
- 编译冒烟：`python -m compileall app tests` 全部通过（0 报错）
- 换行/编码：统一 LF + UTF-8 无 BOM，已清理复制过程中产生的 `__pycache__`

## 注意事项
1. 旧目录 `E:\DEMO\DateAnalysis` 是历史 Codex 会话的工作目录，内部 `STATUS.md`/`PROJECT.md` 是旧 Codex 自维护的状态，**不作为 PM 事实来源**；PM 事实来源以工作空间根的 `STATUS.md` + 本目录下本 `PORTING_NOTE.md` + `docs/adr/` 为准。
2. 运行前需在新路径下重建 venv：
   ```powershell
   cd E:\DEMO\DataAnalysis\projects\dateanalysis-desktop
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python app\main.py
   ```
3. 该项目是**桌面软件**（PySide6），与 PM 工作空间根的 `src/`（预留业务分析脚本目录）互不干扰；软件代码统一放 `projects/dateanalysis-desktop/`。
