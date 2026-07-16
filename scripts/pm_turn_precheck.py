#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pm_turn_precheck.py - PM turn hard gate v2 (head/tail) (A015).

Pure stdlib only. No subprocess / shell calls. Runs even when exec is broken.

Modes:
  head (default): run 6 base checks + write .precheck/last_head.json epoch marker.
  tail: run head checks + verify head epoch + BYPASS detection + TURN_GATE real
        implementation + FAKE_DONE_TAIL; FAIL on bypass/stale/failed-head/no-output.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

CN_TZ = timezone(timedelta(hours=8))
ACTIVE = {"PENDING", "EXECUTING", "VERIFYING"}
RECEIPT_TOOLS = {
    "write", "apply_patch", "edit", "exec", "shell_command", "message",
    "sessions_send", "sessions_spawn", "start_process", "process",
    "image_generate", "video_generate", "web_fetch", "web_search", "read",
}
MUTATING_TOOLS = {
    "write", "apply_patch", "edit", "exec", "shell_command", "sessions_spawn",
    "sessions_send", "start_process",
}
OUTPUT_TOOLS = {
    "message", "sessions_send", "sessions_spawn", "exec", "shell_command",
    "start_process",
}
DECL_DONE_WORDS = (
    "完成了", "done", "已完成", "已派", "在跑", "继续等", "收到继续", "搞定",
    "finished", "已交付", "装好了", "搞定了", "已关闭", "closed", "成功",
    "success", "ok 了", "修好了", "配置好了",
)
DECL_DISPATCH_WORDS = (
    "已派", "派给", "派出", "dispatch", "spawn", "codex exec", "在跑", "继续等",
)
EPOCH_REL = Path(".precheck") / "last_head.json"
EPOCH_STALE_MIN = 10
LAST_ENCODING_SCAN_REL = Path(".precheck") / "last_encoding_scan.json"
TURN_OUTPUT_WINDOW_SEC = 300  # 5 minutes

PATH_PATTERNS = [
    r"([A-Za-z]:[\/][^\s|`<>\"']+)",
    r"(?:^|[\s(|])(scripts[\/][^\s|`<>\"')]+)",
    r"(?:^|[\s(|])(tests[\/][^\s|`<>\"')]+)",
    r"(?:^|[\s(|])(docs[\/][^\s|`<>\"')]+)",
    r"(?:^|[\s(|])(memory[\/][^\s|`<>\"')]+)",
    r"(?:^|[\s(|])(src[\/][^\s|`<>\"')]+)",
]
PATH_RES = [re.compile(p) for p in PATH_PATTERNS]
TIME_FMTS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%fZ",
)
WHITELIST_GLOBS = [
    "scripts/*.py",
    "docs/adr/*.md",
    "memory/*.md",
    "*.md",
]
SKIP_DIRS = {".git", ".precheck", "__pycache__", "node_modules", ".venv", "venv"}


@dataclass
class F:
    level: str
    code: str
    msg: str


@dataclass
class Report:
    items: list = field(default_factory=list)

    def add(self, level, code, msg):
        self.items.append(F(level, code, msg))

    def counts(self):
        c = {"OK": 0, "WARN": 0, "FAIL": 0}
        for x in self.items:
            c[x.level] += 1
        return c

    def has_fail(self):
        return any(x.level == "FAIL" for x in self.items)

    def has_code(self, code, level=None):
        for x in self.items:
            if x.code == code and (level is None or x.level == level):
                return True
        return False


def parse_ts(s):
    if not s:
        return None
    s = str(s).strip()
    if not s or s == "-":
        return None
    if s.endswith("Z"):
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            ).astimezone(CN_TZ)
        except ValueError:
            pass
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
                tzinfo=timezone.utc
            ).astimezone(CN_TZ)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN_TZ)
        return dt.astimezone(CN_TZ)
    except Exception:
        pass
    for f in TIME_FMTS:
        try:
            return datetime.strptime(s, f).replace(tzinfo=CN_TZ)
        except ValueError:
            pass
    return None


def rel(p, root):
    try:
        return str(Path(p).resolve().relative_to(root))
    except Exception:
        return str(p)


def _safe_read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_read_json(path):
    txt = _safe_read_text(path)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def parse_commitments(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [x.strip() for x in line.strip("|").split("|")]
        if len(parts) < 8:
            continue
        cid = parts[0]
        if cid == "ID" or cid.startswith("-"):
            continue
        status = parts[5].upper()
        if status not in ACTIVE:
            continue
        out.append({
            "id": cid, "reg": parts[1], "promise": parts[2], "dod": parts[3],
            "owner": parts[4], "status": status, "deliv": parts[6],
            "receipt": parts[7],
        })
    return out


def extract_paths(text):
    seen = []
    for r in PATH_RES:
        for m in r.finditer(text or ""):
            cand = m.group(1)
            while cand and cand[-1] in ".,;)":
                cand = cand[:-1]
            cut = None
            for i2, ch in enumerate(cand):
                if ord(ch) > 127:
                    cut = i2
                    break
            if cut is not None and cut > 0:
                cand = cand[:cut].rstrip(".,;)/" + chr(92))
            if len(cand) >= 5 and cand not in seen:
                seen.append(cand)
    return seen


def check_commitments(root, now, rep):
    cm = root / "COMMITMENTS.md"
    if not cm.exists():
        rep.add("FAIL", "COMMITMENTS_PENDING",
                "COMMITMENTS.md missing: " + rel(cm, root))
        return
    rows = parse_commitments(cm)
    if not rows:
        rep.add("OK", "COMMITMENTS_PENDING",
                "no active PENDING/EXECUTING/VERIFYING")
        return
    for r in rows:
        blob = r["promise"] + " | " + r["dod"] + " | " + r["receipt"]
        paths = extract_paths(blob)
        reg = parse_ts(r["reg"]) or now
        age = (now - reg).total_seconds() / 60.0
        if not paths:
            msg = r["id"] + " (" + r["status"] + ") no target path parseable; reg " + str(int(age)) + "m"
            rep.add("FAIL" if age > 30 else "WARN", "COMMITMENTS_PENDING",
                    msg + (" >30m stale" if age > 30 else ""))
            continue
        for tp in paths:
            t = Path(tp)
            if not t.is_absolute():
                t = root / t
            try:
                mt = datetime.fromtimestamp(t.stat().st_mtime, tz=CN_TZ)
                since = (now - mt).total_seconds() / 60.0
                if since > 30:
                    rep.add("FAIL", "COMMITMENTS_PENDING",
                            r["id"] + " (" + r["status"] + ") " + rel(t, root)
                            + " mtime " + str(int(since)) + "m >30m stale")
                elif since > 10:
                    rep.add("WARN", "COMMITMENTS_PENDING",
                            r["id"] + " (" + r["status"] + ") " + rel(t, root)
                            + " mtime " + str(int(since)) + "m >10m no progress")
                else:
                    rep.add("OK", "COMMITMENTS_PENDING",
                            r["id"] + " (" + r["status"] + ") " + rel(t, root)
                            + " mtime fresh (" + str(int(since)) + "m)")
            except FileNotFoundError:
                msg = r["id"] + " (" + r["status"] + ") target missing " + rel(t, root) + "; reg " + str(int(age)) + "m"
                rep.add("FAIL" if age > 30 else "WARN", "COMMITMENTS_PENDING",
                        msg + (" >30m stale" if age > 30 else ""))


def _sess_start(rec, now):
    if not isinstance(rec, dict):
        return None
    for k in ("started_at", "start_time", "spawned_at", "created_at", "ts"):
        v = rec.get(k)
        if v:
            ts = parse_ts(str(v))
            if ts:
                return ts
    return None


def _sess_done(rec):
    if not isinstance(rec, dict):
        return True
    for k in ("finished_at", "end_time"):
        if rec.get(k):
            return True
    ec = rec.get("exit_code")
    if isinstance(ec, int):
        return True
    st = (rec.get("status") or rec.get("state") or "").lower()
    if st in ("done", "finished", "complete", "completed", "closed",
              "failed", "exited", "success", "ok"):
        return True
    if rec.get("done") is True:
        return True
    return False


def check_worker_timeout(root, workers_path, now, rep):
    if not workers_path:
        rep.add("WARN", "WORKER_TIMEOUT", "no workers file, skip")
        return
    wp = Path(workers_path)
    if not wp.is_absolute():
        wp = root / wp
    if not wp.exists():
        rep.add("WARN", "DEGRADED_MODE",
                "workers file missing (" + rel(wp, root) + "), skipping WORKER_TIMEOUT")
        return
    data = _safe_read_json(wp)
    if data is None:
        rep.add("WARN", "DEGRADED_MODE",
                "workers file unparseable (" + rel(wp, root) + "), skipping WORKER_TIMEOUT")
        return
    sessions = []
    if isinstance(data, list):
        sessions = data
    elif isinstance(data, dict):
        for key in ("sessions", "workers", "spawns", "children"):
            if isinstance(data.get(key), list):
                sessions = data[key]
                break
        if not sessions:
            for v in data.values():
                if isinstance(v, dict):
                    sessions.append(v)
    alive = 0
    for rec in sessions:
        if not isinstance(rec, dict):
            continue
        sid = rec.get("id") or rec.get("session_id") or rec.get("pid") or "<unknown>"
        if _sess_done(rec):
            rep.add("OK", "WORKER_TIMEOUT", "session " + str(sid) + " finished")
            continue
        ts = _sess_start(rec, now)
        if ts is None:
            rep.add("WARN", "WORKER_TIMEOUT",
                    "session " + str(sid) + " no parseable start time")
            continue
        age = (now - ts).total_seconds()
        alive += 1
        if age > 600:
            rep.add("FAIL", "WORKER_TIMEOUT",
                    "worker/session " + str(sid) + " running " + str(int(age))
                    + "s >600s timeout, kill/re-dispatch")
        else:
            rep.add("OK", "WORKER_TIMEOUT",
                    "session " + str(sid) + " running " + str(int(age))
                    + "s within timeout")
    if alive == 0:
        rep.add("OK", "WORKER_TIMEOUT",
                "no alive worker sessions over threshold")


TOOL_NAME_RES = [
    re.compile(r'"name"\s*:\s*"([A-Za-z_][\w\-]*)"'),
    re.compile(r'<tool\s+name="([A-Za-z_][\w\-]*)"'),
    re.compile(r'<invoke[^>]*name="([A-Za-z_][\w\-]*)"'),
    re.compile(r'<function\s+name="([A-Za-z_][\w\-]*)"'),
]


def _extract_tool_names(text):
    tools = []
    if not text:
        return tools
    for rx in TOOL_NAME_RES:
        for m in rx.finditer(text):
            tools.append(m.group(1).lower())
    return tools


def _load_tools(transcript, last_assistant_file):
    text_parts = []
    tools = []
    if transcript:
        tp = Path(transcript)
        if tp.exists():
            raw = _safe_read_text(tp) or ""
            text_parts.append(raw)
            tools.extend(_extract_tool_names(raw))
    if last_assistant_file:
        ap = Path(last_assistant_file)
        if ap.exists():
            raw = _safe_read_text(ap) or ""
            text_parts.append(raw)
            tools.extend(_extract_tool_names(raw))
    return "\n".join(text_parts), tools


def _newest_mtime(paths, root):
    newest = None
    for p in paths:
        cand = Path(p)
        if not cand.is_absolute():
            cand = root / cand
        try:
            mt = datetime.fromtimestamp(cand.stat().st_mtime, tz=CN_TZ)
            if newest is None or mt > newest:
                newest = mt
        except OSError:
            continue
    return newest


def _last_exec_row(rows):
    latest = None
    for r in rows:
        if r["status"] != "EXECUTING":
            continue
        ts = parse_ts(r["reg"])
        if ts is None:
            continue
        if latest is None or ts > latest[0]:
            latest = (ts, r)
    return latest[1] if latest else None


def _last_spawn_info(workers_path, now):
    if not workers_path:
        return None, None
    wp = Path(workers_path)
    if not wp.exists() or not wp.is_file():
        return None, None
    data = _safe_read_json(wp)
    if not isinstance(data, dict) and not isinstance(data, list):
        return None, None
    sess = []
    if isinstance(data, list):
        sess = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        for k in ("sessions", "workers", "spawns"):
            if isinstance(data.get(k), list):
                sess = [x for x in data[k] if isinstance(x, dict)]
                break
        if not sess:
            sess = [v for v in data.values() if isinstance(v, dict)]
    sid = None
    ts = None
    for rec in sess:
        if _sess_done(rec):
            continue
        st = _sess_start(rec, now)
        if st is None:
            continue
        if ts is None or st > ts:
            ts = st
            sid = rec.get("id") or rec.get("session_id")
    return sid, ts


def check_need_poll(root, transcript, last_assistant_file, workers_path, now, rep):
    cm = root / "COMMITMENTS.md"
    rows = parse_commitments(cm) if cm.exists() else []
    sid, spawn_ts = _last_spawn_info(workers_path, now)
    row = _last_exec_row(rows)
    if row and spawn_ts is None:
        spawn_ts = parse_ts(row["reg"])
        sid = sid or row["id"]
    if spawn_ts is None:
        rep.add("OK", "NEED_POLL", "no recent exec/spawn detected")
        return
    age = (now - spawn_ts).total_seconds()
    tgt_paths = []
    if row:
        tgt_paths = extract_paths(
            row["promise"] + " | " + row["dod"] + " | " + row["receipt"])
    newest = _newest_mtime(tgt_paths, root)
    if age > 180 and (newest is None or newest < spawn_ts + timedelta(seconds=180)):
        rep.add("FAIL", "NEED_POLL",
                "worker/session " + str(sid) + " stuck (" + str(int(age))
                + "s >180s), kill and re-dispatch")
    elif age > 60 and (newest is None or newest < spawn_ts):
        rep.add("WARN", "NEED_POLL",
                "need to poll " + str(sid) + " (" + str(int(age))
                + "s since spawn, no observed progress)")
    else:
        rep.add("OK", "NEED_POLL",
                "session " + str(sid) + " within poll window (" + str(int(age)) + "s)")


def check_fake_done(transcript, last_assistant_file, rep, mode="head",
                    turn_has_output=False):
    have_text = False
    if transcript and Path(transcript).exists():
        have_text = True
    if last_assistant_file and Path(last_assistant_file).exists():
        have_text = True
    if not have_text:
        if mode == "head":
            rep.add("OK", "FAKE_DONE", "no last assistant/transcript text provided")
        return
    text, tools = _load_tools(transcript, last_assistant_file)
    if not text:
        if mode == "head":
            rep.add("OK", "FAKE_DONE", "no last assistant text provided")
        return
    lower = text.lower()
    done_hit = any(w.lower() in lower for w in DECL_DONE_WORDS)
    dispatch_hit = any(w.lower() in lower for w in DECL_DISPATCH_WORDS)
    last_tool = tools[-1] if tools else ""
    if mode == "tail":
        if done_hit and not turn_has_output:
            rep.add("FAIL", "FAKE_DONE_TAIL",
                    "declared done with no visible output (no files/messages/exec)")
        else:
            rep.add("OK", "FAKE_DONE", "completion claim matches visible output")
        return
    if done_hit and (not tools or last_tool not in RECEIPT_TOOLS):
        rep.add("FAIL", "FAKE_DONE",
                "declarative completion without tool receipt")
        return
    if dispatch_hit and last_tool not in (
            "sessions_spawn", "exec", "shell_command", "sessions_send",
            "message", "start_process", "apply_patch", "write", "edit"):
        rep.add("FAIL", "FAKE_DONE",
                "declared dispatch/spawn but last tool call missing receipt")
        return
    rep.add("OK", "FAKE_DONE",
            "completion/dispatch claims aligned with tool calls")


def _iter_whitelist_files(root):
    seen = set()
    root_resolved = root.resolve()
    for gl in WHITELIST_GLOBS:
        for p in root.glob(gl):
            try:
                rp = p.resolve()
            except OSError:
                continue
            if not p.is_file():
                continue
            try:
                rel_parts = rp.relative_to(root_resolved).parts
            except ValueError:
                rel_parts = rp.parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            if rp in seen:
                continue
            seen.add(rp)
            yield rp
    for sub in ("memory", Path("docs") / "adr", "scripts"):
        d = root / sub
        if not d.exists():
            continue
        for p in d.rglob("*"):
            try:
                rp = p.resolve()
            except OSError:
                continue
            if not p.is_file():
                continue
            try:
                rel_parts = rp.relative_to(root_resolved).parts
            except ValueError:
                rel_parts = rp.parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            if rp in seen:
                continue
            if rp.suffix not in (".py", ".md", ".txt", ".json"):
                continue
            seen.add(rp)
            yield rp


def _turn_has_file_output(root, now, window_sec=TURN_OUTPUT_WINDOW_SEC):
    cutoff = now - timedelta(seconds=window_sec)
    newest = None
    newest_path = None
    count = 0
    for p in _iter_whitelist_files(root):
        try:
            st = p.stat()
        except OSError:
            continue
        mt = datetime.fromtimestamp(st.st_mtime, tz=CN_TZ)
        if newest is None or mt > newest:
            newest = mt
            newest_path = p
        if mt >= cutoff:
            count += 1
    has = (newest is not None and newest >= cutoff)
    return has, count, newest, newest_path


def _turn_artifacts_has_output(artifacts):
    if not artifacts:
        return False, []
    calls = []
    if isinstance(artifacts, list):
        calls = artifacts
    elif isinstance(artifacts, dict):
        for k in ("tools", "calls", "tool_calls", "events"):
            if isinstance(artifacts.get(k), list):
                calls = artifacts[k]
                break
    has = False
    names = []
    for c in calls:
        name = ""
        has_stdout = False
        if isinstance(c, dict):
            name = (c.get("name") or c.get("tool") or c.get("type") or "").lower()
            has_stdout = bool(c.get("stdout") or c.get("output")
                              or c.get("result") or c.get("response")
                              or c.get("content"))
        elif isinstance(c, str):
            name = c.lower()
        else:
            continue
        if name:
            names.append(name)
        if name in OUTPUT_TOOLS:
            if name in ("message", "sessions_send", "sessions_spawn"):
                has = True
            elif has_stdout:
                has = True
    return has, names


def _is_precheck_tool(name):
    if not name:
        return False
    n = name.lower().replace("-", "_")
    return ("precheck" in n) or ("pm_turn_precheck" in n)


def check_bypass(root, turn_artifacts_path, rep):
    if not turn_artifacts_path:
        rep.add("WARN", "DEGRADED_MODE",
                "--turn-artifacts not provided, skipping BYPASS detection")
        return None
    tap = Path(turn_artifacts_path)
    if not tap.is_absolute():
        tap = root / tap
    if not tap.exists():
        rep.add("WARN", "DEGRADED_MODE",
                "turn-artifacts missing (" + rel(tap, root) + "), skipping BYPASS detection")
        return None
    data = _safe_read_json(tap)
    if data is None:
        rep.add("WARN", "DEGRADED_MODE",
                "turn-artifacts unparseable (" + rel(tap, root) + "), skipping BYPASS detection")
        return None
    calls = []
    if isinstance(data, list):
        calls = data
    elif isinstance(data, dict):
        for k in ("tools", "calls", "tool_calls", "events"):
            if isinstance(data.get(k), list):
                calls = data[k]
                break
    first_name = None
    mutating_seen = False
    tool_names = []
    for c in calls:
        nm = ""
        if isinstance(c, dict):
            nm = (c.get("name") or c.get("tool") or c.get("type") or "").lower()
        elif isinstance(c, str):
            nm = c.lower()
        else:
            continue
        if not nm:
            continue
        tool_names.append(nm)
        if first_name is None:
            first_name = nm
        if nm in MUTATING_TOOLS:
            mutating_seen = True
    if first_name is None:
        rep.add("WARN", "BYPASS", "turn-artifacts had no recognizable tool calls")
        return tool_names
    if not _is_precheck_tool(first_name) and mutating_seen:
        rep.add("FAIL", "BYPASSED_HEAD_GATE",
                "first tool call was '" + first_name + "', not precheck, but mutating tools were present")
    else:
        rep.add("OK", "BYPASS",
                "first tool is precheck-compatible ('" + first_name + "')")
    return tool_names


def check_turn_gate(root, now, artifacts, rep):
    file_has, file_count, newest, newest_path = _turn_has_file_output(root, now)
    art_has, _art_tools = _turn_artifacts_has_output(artifacts)
    has_output = file_has or art_has
    if has_output:
        bits = []
        if file_has:
            bits.append(str(file_count) + " file(s) updated (newest="
                        + (rel(newest_path, root) if newest_path else "?")
                        + " " + (newest.strftime("%H:%M:%S") if newest else "-") + ")")
        if art_has:
            bits.append("output-producing tool calls in artifacts")
        rep.add("OK", "TURN_HAS_VISIBLE_OUTPUT", "; ".join(bits))
    else:
        rep.add("FAIL", "NO_VISIBLE_OUTPUT",
                "turn produced no files, no messages, no exec output; turn must have a receipt or ask a blocking question")
    return has_output


def _check_inline_python_violation(turn_artifacts_path, rep):
    """T003: Detect 'python -c "..."' long inline commands that trigger
    PowerShell escaping bugs.  FAIL if found – PM must use temp script file."""
    if not turn_artifacts_path:
        return
    tap = Path(turn_artifacts_path)
    if not tap.is_absolute():
        tap = Path.cwd() / turn_artifacts_path
    if not tap.exists():
        return
    data = _safe_read_json(tap)
    if not isinstance(data, (list, dict)):
        return
    calls = []
    if isinstance(data, list):
        calls = data
    else:
        for k in ("tools", "calls", "tool_calls", "events"):
            if isinstance(data.get(k), list):
                calls = data[k]
                break
    for c in calls:
        if not isinstance(c, dict):
            continue
        nm = (c.get("name") or c.get("tool") or c.get("type") or "").lower()
        if nm != "exec":
            continue
        cmd = str(c.get("command") or c.get("cmd") or c.get("input") or "")
        # Pattern: python -c "..." where the content after -c has newlines
        # (i.e. it was a multi-line python -c that PowerShell mangled)
        if not cmd:
            continue
        # Check for python -c pattern
        cmd_lower = cmd.lower()
        # Match: python -c "..." or python -c '...'
        import re as _re
        inline_match = _re.search(r"python\s+-c\s+[\"'](.{20,})[\"']", cmd, _re.DOTALL)
        if inline_match:
            content = inline_match.group(1)
            # If content contains real newlines (0x0A) or backslash-n sequences,
            # it's a long inline script that will get mangled by PowerShell
            if "\n" in content or "\\n" in content:
                rep.add("FAIL", "TOOL_SYNTAX_VIOLATION",
                        "T003: DO NOT use python -c with multi-line content. "
                        "Use a temp .py script file instead. Command was too long. "
                        "See: AGENTS.md § 'Python inline exec forbidden'")
                return


def check_turn_gate_head(rep):
    rep.add("OK", "TURN_GATE", "head mode; TURN_GATE enforced at tail")


def _encoding_targets(root, n=5):
    """Return list of files to scan for BOM/CRLF.

    Always scans (deterministically):
      - docs/*.md   (new — C031, exclude docs/domain/ via rglob guard below)
      - memory/*.md (existing)
      - docs/adr/*.md (existing)
      - scripts/*.py (existing)
    Plus top-N most-recently-modified root *.md (existing meta files).
    Skips docs/domain/ per project rule (business doc exclusion zone).
    """
    seen = set()
    out = []

    def _add(p):
        try:
            rp = p.resolve()
        except OSError:
            return
        if not p.is_file():
            return
        if rp in seen:
            return
        if any(part in SKIP_DIRS for part in rp.parts):
            return
        # docs/domain/ exclusion zone (C031: business docs off-limits)
        rel_parts = rp.parts
        if "docs" in rel_parts and "domain" in rel_parts:
            return
        seen.add(rp)
        out.append(p)

    # Deterministic full scan: docs/*.md + memory/*.md + docs/adr/*.md + scripts/*.py
    for gl in ("docs/*.md", "memory/*.md", "docs/adr/*.md", "scripts/*.py"):
        for p in root.glob(gl):
            _add(p)
    # Top-N most-recent root *.md (preserve original 'recent root meta' sampling)
    root_md = []
    for p in root.glob("*.md"):
        try:
            root_md.append((p.stat().st_mtime, p))
        except OSError:
            pass
    root_md.sort(reverse=True)
    for _, p in root_md[:n]:
        _add(p)
    return out


def check_encoding(root, rep):
    files = _encoding_targets(root, n=5)
    if not files:
        rep.add("WARN", "ENCODING_SANITY",
                "no scripts/*.py or docs/adr/*.md found to sample")
        return
    bad = []
    syntax_bad = []
    last = _load_last_scan(root)
    new_or_modified = []
    for p in files:
        b = p.read_bytes() if p.exists() else b""
        probs = []
        if b[:3] == b"\xef\xbb\xbf":
            probs.append("BOM")
        if b"\r" in b:
            probs.append("CR")
        try:
            b.decode("utf-8")
        except UnicodeDecodeError:
            probs.append("NON_UTF8")
        # Track which files are new or modified since last scan (C038)
        try:
            mt = p.stat().st_mtime
        except OSError:
            mt = 0.0
        # Normalize to forward slashes for cross-platform cache key stability
        # (Windows rel() returns backslashes; cache keys must be uniform).
        relp = rel(p, root).replace("\\", "/")
        prev_mt = last.get(relp)
        is_new_or_modified = (prev_mt is None) or (mt > prev_mt + 0.0001)
        if probs:
            bad.append(relp + ":" + ",".join(probs))
        # PY_COMPILE: syntax check for .py files
        if p.suffix == ".py" and b:
            try:
                code = b.decode("utf-8", errors="replace")
                compile(code, str(p), "exec")
            except (SyntaxError, ValueError, TypeError) as e:
                # Detect literal \n vs real newline issue (write tool bug)
                # b"\\n" in bytes is literal backslash (5C) + n (6E)
                if b"\\n" in b:
                    syntax_bad.append(
                        relp + ": SYNTAX_ERROR (\n escaped as literal backslash-n, "
                        "likely write tool bug: " + str(e).splitlines()[0][:120]
                    )
                else:
                    syntax_bad.append(
                        relp + ": SYNTAX_ERROR: " + str(e).splitlines()[0][:120]
                    )
        if is_new_or_modified:
            new_or_modified.append(relp)
    # Partition bad/syntax into new-or-modified (FAIL) vs old (WARN for compat)
    new_bad = [x for x in bad if x.split(":", 1)[0] in new_or_modified]
    old_bad = [x for x in bad if x.split(":", 1)[0] not in new_or_modified]
    new_syntax = [x for x in syntax_bad if x.split(":", 1)[0] in new_or_modified]
    old_syntax = [x for x in syntax_bad if x.split(":", 1)[0] not in new_or_modified]
    if syntax_bad:
        if new_syntax:
            rep.add("FAIL", "ENCODING_SANITY",
                    "py_compile failed (NEW/MODIFIED file, C038): "
                    + " | ".join(new_syntax))
        if old_syntax:
            rep.add("WARN", "ENCODING_SANITY",
                    "py_compile failed (pre-existing file, not re-checked as FAIL): "
                    + " | ".join(old_syntax))
        if not new_syntax:
            # only old syntax bad -> downgrade to WARN
            pass
    elif new_bad:
        rep.add("FAIL", "ENCODING_SANITY",
                "encoding bad (NEW/MODIFIED file, C038): "
                + " | ".join(new_bad))
        if old_bad:
            rep.add("WARN", "ENCODING_SANITY",
                    "encoding bad (pre-existing, not re-checked as FAIL): "
                    + " | ".join(old_bad))
    elif old_bad:
        rep.add("WARN", "ENCODING_SANITY",
                "encoding bad (pre-existing, not re-checked as FAIL): "
                + " | ".join(old_bad))
    else:
        rep.add("OK", "ENCODING_SANITY",
                "sample " + str(len(files))
                + " recent .py/.md UTF-8 no BOM LF-only, py_compile OK"
                + (" (" + str(len(new_or_modified)) + " new/modified)" if new_or_modified else ""))
    # Always save current scan snapshot for next-run diff (C038 incremental)
    try:
        _save_last_scan(root, files)
    except Exception:
        # Cache write failure is non-fatal; precheck already reported
        pass


def _epoch_path(root):
    return root / EPOCH_REL


def _last_encoding_scan_path(root):
    return root / LAST_ENCODING_SCAN_REL


def _load_last_scan(root):
    """Load previous encoding-scan snapshot.

    Returns dict[relpath:str -> mtime:float]. Empty dict if cache missing/corrupt.
    C038: powers incremental CRLF/BOM/NON_UTF8 detection across turns.
    """
    p = _last_encoding_scan_path(root)
    if not p.exists():
        return {}
    data = _safe_read_json(p)
    if not isinstance(data, dict):
        return {}
    files = data.get("files")
    if not isinstance(files, dict):
        return {}
    out = {}
    for k, v in files.items():
        if not isinstance(k, str):
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _save_last_scan(root, files):
    """Persist current encoding-scan snapshot for next-run diff.

    Writes UTF-8 LF no-BOM via tmp+os.replace (same atomic style as write_epoch).
    Stores relpath -> mtime. C038 incremental cache.
    """
    p = _last_encoding_scan_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    snap = {"version": 1, "files": {}}
    for f in files:
        try:
            # Use the same rel() helper that check_encoding uses, so the cache
            # key matches what the next-run diff will look up. This also keeps
            # Windows 8.3 short paths consistent across write/read turns.
            # Normalize to forward slashes for cross-platform cache key
            # stability (matches the diff-side lookup in check_encoding).
            relp = rel(f, root).replace("\\", "/")
            mt = float(Path(f).stat().st_mtime)
        except (OSError, ValueError):
            continue
        snap["files"][relp] = mt
    tmp = p.with_suffix(".json.tmp")
    txt = json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp.write_bytes(txt.encode("utf-8"))
    os.replace(tmp, p)


def write_epoch(root, now, summary, head_ok):
    p = _epoch_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "timestamp": now.astimezone(CN_TZ).isoformat(timespec="seconds"),
        "pid": os.getpid(),
        "cwd": str(root.resolve()),
        "summary": summary,
        "head_ok": bool(head_ok),
    }
    tmp = p.with_suffix(".json.tmp")
    txt = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp.write_bytes(txt.encode("utf-8"))
    os.replace(tmp, p)
    return p


def check_epoch_tail(root, now, rep):
    p = _epoch_path(root)
    if not p.exists():
        rep.add("FAIL", "HEAD_NOT_RUN",
                "no " + str(EPOCH_REL).replace("\\", "/") + " found; head gate was bypassed")
        return None
    data = _safe_read_json(p)
    if not isinstance(data, dict):
        rep.add("FAIL", "HEAD_NOT_RUN",
                str(EPOCH_REL).replace("\\", "/") + " unparseable; head gate state corrupt")
        return None
    ts = parse_ts(data.get("timestamp"))
    if ts is None:
        rep.add("FAIL", "HEAD_STALE",
                str(EPOCH_REL).replace("\\", "/") + " has invalid timestamp")
        return data
    age_min = (now - ts).total_seconds() / 60.0
    if age_min > EPOCH_STALE_MIN:
        rep.add("FAIL", "HEAD_STALE",
                "last head gate was " + ("%.1f" % age_min) + " minutes ago (>"
                + str(EPOCH_STALE_MIN) + "min)")
        return data
    if not data.get("head_ok", False):
        rep.add("FAIL", "HEAD_FAILED",
                "last head gate had FAILs, they must be resolved first")
        return data
    rep.add("OK", "HEAD_VERIFIED",
            "head gate ok (age " + ("%.1f" % age_min) + "m, pid=" + str(data.get("pid")) + ")")
    return data


def _check_inputs_present(root, transcript, last_assistant_file, workers,
                          turn_artifacts, rep):
    checks = [
        ("transcript", transcript),
        ("last_assistant_file", last_assistant_file),
        ("workers", workers),
    ]
    if turn_artifacts is not None:
        checks.append(("turn_artifacts", turn_artifacts))
    for name, path in checks:
        if not path:
            rep.add("WARN", "DEGRADED_MODE",
                    name + " not provided, skipping " + name.upper() + "-dependent checks")
            continue
        pp = Path(path)
        if not pp.is_absolute():
            pp = root / pp
        if not pp.exists():
            rep.add("WARN", "DEGRADED_MODE",
                    name + " missing (" + rel(pp, root) + "), skipping "
                    + name.upper() + "-dependent checks")


def _run_head_checks(root, transcript, last_assistant_file, workers, now, rep):
    """Run the v1-compatible 6 base checks (TURN_GATE is head placeholder)."""
    try:
        check_commitments(root, now, rep)
    except Exception as e:
        rep.add("FAIL", "COMMITMENTS_PENDING", "internal error: " + str(e))
    try:
        check_worker_timeout(root, workers, now, rep)
    except Exception as e:
        rep.add("FAIL", "WORKER_TIMEOUT", "internal error: " + str(e))
    try:
        check_need_poll(root, transcript, last_assistant_file, workers, now, rep)
    except Exception as e:
        rep.add("FAIL", "NEED_POLL", "internal error: " + str(e))
    try:
        check_fake_done(transcript, last_assistant_file, rep, mode="head")
    except Exception as e:
        rep.add("FAIL", "FAKE_DONE", "internal error: " + str(e))
    try:
        check_turn_gate_head(rep)
    except Exception as e:
        rep.add("FAIL", "TURN_GATE", "internal error: " + str(e))
    try:
        check_encoding(root, rep)
    except Exception as e:
        rep.add("FAIL", "ENCODING_SANITY", "internal error: " + str(e))
    try:
        check_tool_patterns_head(root, last_assistant_file, rep)
    except Exception as e:
        rep.add("FAIL", "TOOL_PATTERNS", "internal error: " + str(e))


def check_tool_patterns_head(root, last_assistant_file, rep):
    """T003: Check exec patterns in last-assistant text (head mode fallback).

    When turn-artifacts is not available, grep the assistant's message text
    for exec commands matching dangerous patterns.
    """
    if not last_assistant_file:
        return
    ap = Path(last_assistant_file)
    if not ap.exists():
        return
    text = _safe_read_text(ap)
    if not text:
        return
    # Extract exec commands from text
    exec_match = re.findall(
        r'exec\s*\(\s*["\']([^"\'])',
        text,
    )
    for cmd in exec_match:
        for pattern, msg in [
            (r"python\s+-c\s+[\"\'](.{50,})", "python -c long inline"),
            (r"Set-Content", "Set-Content write"),
            (r"Out-File", "Out-File write"),
        ]:
            if re.search(pattern, cmd, re.IGNORECASE):
                rep.add("FAIL", "TOOL_PATTERNS",
                        "T003: " + msg + " found in exec: " + cmd[:80])
                return
    rep.add("OK", "TOOL_PATTERNS", "no dangerous patterns in exec commands")


def check_tool_patterns(root, turn_artifacts_path, rep):
    """T003: Scan turn-artifacts for exec commands matching dangerous patterns.

    Catches:
      - python -c with long content (PowerShell escaping bug)
      - Set-Content / Out-File / Write-Host writing to files
      - cat > heredoc / sed -i / echo > file
      - 任何写文件模式（A012 禁令）
    """
    if not turn_artifacts_path:
        rep.add("WARN", "TOOL_PATTERNS",
                "--turn-artifacts not provided, skipping TOOL_PATTERNS")
        return
    tap = Path(turn_artifacts_path)
    if not tap.is_absolute():
        tap = root / tap
    if not tap.exists():
        rep.add("WARN", "TOOL_PATTERNS",
                "turn-artifacts missing, skipping TOOL_PATTERNS")
        return
    data = _safe_read_json(tap)
    if not isinstance(data, (list, dict)):
        return
    calls = []
    if isinstance(data, list):
        calls = data
    else:
        for k in ("tools", "calls", "tool_calls", "events"):
            if isinstance(data.get(k), list):
                calls = data[k]
                break

    # Dangerous patterns: each is (regex, friendly_message)
    DANGEROUS_PATTERNS = [
        (r"python\s+-c\s+[\"\'](.{50,})[\"\']",
         "python -c with long inline code (>50 chars): PowerShell escaping bug. Use temp .py file."),
        (r"Set-Content\s+[\"']?\S+[\"']?\s*[-\s]\w*Encoding",
         "Set-Content with -Encoding: GBK/BOM/CRLF corruption risk."),
        (r"Set-Content\s+.*[\"'][\r\n]",
         "Set-Content with here-string/inline content: write content is not safe in exec."),
        (r"Out-File\s+.*[-\s]\w*Encoding",
         "Out-File with -Encoding: encoding corruption risk."),
        (r"Write-Host\s+.*>\s*\S+",
         "Write-Host > file: stdout redirect, content may be mangled."),
        (r"Write-Output\s+.*>\s*\S+",
         "Write-Output > file: redirect output, encoding risk."),
        (r"echo\s+.*>\s*\S+\.(py|js|ts|json|yaml|yml|md)",
         "echo > file (cmd): write file content via echo."),
        (r"cat\s+>.*<<", r"cat > ... << heredoc: bash heredoc write."),
        (r"\bsed\s+-i\b",
         "sed -i: in-place file editing via shell."),
        (r"tee\s+.*>\s*\S+\.(py|js|ts|json)",
         "tee > file: redirecting to source file."),
        (r"\bif\s+.*[-]RedirectStandardOutput\b",
         "RedirectStandardOutput > file: redirecting command output to source file."),
    ]

    for c in calls:
        if not isinstance(c, dict):
            continue
        nm = (c.get("name") or c.get("tool") or c.get("type") or "").lower()
        if nm != "exec":
            continue
        cmd = str(c.get("command") or c.get("cmd") or c.get("input") or "")
        if not cmd:
            continue
        for pattern, msg in DANGEROUS_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE | re.DOTALL):
                # Trim command for display (max 100 chars)
                cmd_snippet = cmd[:100].replace("\n", "\\n").replace("\r", "\\r")
                rep.add("FAIL", "TOOL_PATTERNS",
                        "exec command blocked: " + msg
                        + " | cmd=" + cmd_snippet + "...")
                return

    rep.add("OK", "TOOL_PATTERNS",
            "no dangerous exec patterns detected in turn")


def _load_artifacts(root, turn_artifacts, rep):
    """Load turn-artifacts JSON if provided and exists; return parsed or None."""
    if not turn_artifacts:
        return None
    tap = Path(turn_artifacts)
    if not tap.is_absolute():
        tap = root / tap
    if not tap.exists():
        return None
    return _safe_read_json(tap)


def run(root, mode="head", last_assistant_file=None, transcript=None,
        workers=None, turn_artifacts=None, now=None):
    if now is None:
        now = datetime.now(tz=CN_TZ)
    root = Path(root).resolve()
    rep = Report()

    # 1) degraded warnings for missing external inputs (non-fatal)
    _check_inputs_present(root, transcript, last_assistant_file, workers,
                          turn_artifacts, rep)

    # 2) always run base head checks
    _run_head_checks(root, transcript, last_assistant_file, workers, now, rep)

    artifacts_data = _load_artifacts(root, turn_artifacts, rep)

    if mode == "head":
        # Epoch marker: always write, head_ok=true iff no FAIL so far
        head_ok = not rep.has_fail()
        counts = rep.counts()
        summary_str = "{OK} OK, {WARN} WARN, {FAIL} FAIL".format(**counts)
        try:
            ep = write_epoch(root, now, counts, head_ok)
            rep.add("OK" if head_ok else "WARN", "EPOCH",
                    "wrote " + str(EPOCH_REL).replace("\\", "/")
                    + " head_ok=" + str(head_ok).lower()
                    + " summary=" + summary_str)
        except Exception as e:
            rep.add("FAIL", "EPOCH", "failed to write epoch: " + str(e))
        return rep

    # mode == "tail"
    # 3) verify head epoch (must exist, fresh, ok)
    epoch_data = check_epoch_tail(root, now, rep)

    # 4) bypass detection (degrades gracefully)
    check_bypass(root, turn_artifacts, rep)

    # 5) T003: exec command pattern check (tail: uses turn-artifacts)
    try:
        check_tool_patterns(root, turn_artifacts, rep)
    except Exception as e:
        rep.add("FAIL", "TOOL_PATTERNS", "internal error: " + str(e))

    # 6) real TURN_GATE: visible output check (files / artifacts)
    turn_has_output = check_turn_gate(root, now, artifacts_data, rep)

    # 7) FAKE_DONE_TAIL: declared done + no visible output
    try:
        check_fake_done(transcript, last_assistant_file, rep, mode="tail",
                        turn_has_output=turn_has_output)
    except Exception as e:
        rep.add("FAIL", "FAKE_DONE_TAIL", "internal error: " + str(e))

    return rep


def print_report(rep):
    for f in rep.items:
        print(f.level + " " + f.code + ": " + f.msg)
    c = rep.counts()
    print("SUMMARY: {OK} OK, {WARN} WARN, {FAIL} FAIL".format(**c))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="PM turn hard gate v2 (head/tail)")
    ap.add_argument("--mode", choices=("head", "tail"), default="head",
                    help="head=turn start (default); tail=turn end")
    ap.add_argument("--last-assistant-file", default=None)
    ap.add_argument("--transcript", default=None)
    ap.add_argument("--workers", default=None)
    ap.add_argument("--turn-artifacts", default=None,
                    help="JSON file listing this turn's tool calls")
    ap.add_argument("--project-root",
                    default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--now", default=None)
    args = ap.parse_args(argv)
    root = Path(args.project_root).resolve()
    now = parse_ts(args.now) if args.now else datetime.now(tz=CN_TZ)
    if now is None:
        print("FAIL OPTIONS: --now timestamp unparseable", file=sys.stderr)
        sys.exit(2)
    rep = run(root, mode=args.mode,
              last_assistant_file=args.last_assistant_file,
              transcript=args.transcript, workers=args.workers,
              turn_artifacts=args.turn_artifacts, now=now)
    print_report(rep)
    sys.exit(1 if rep.has_fail() else 0)


if __name__ == "__main__":
    main()
