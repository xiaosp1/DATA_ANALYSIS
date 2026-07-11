#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_precheck_v2.py - unit tests for pm_turn_precheck v2 (head/tail/epoch/bypass/turn_gate)."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, tempfile, time, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pm_turn_precheck as pc

CN_TZ = timezone(timedelta(hours=8))
LF = b"\n"


def _write(p: Path, text: str) -> None:
    p.write_bytes(text.encode("utf-8").replace(b"\r\n", LF).replace(b"\r", LF))


def _mk_root():
    tmp = Path(tempfile.mkdtemp(prefix="precheck_v2_"))
    (tmp / "scripts").mkdir(parents=True)
    (tmp / "docs" / "adr").mkdir(parents=True)
    (tmp / "memory").mkdir(parents=True)
    _write(tmp / "COMMITMENTS.md",
           "# COMMITMENTS\n"
           "| ID | 登记时间 | 承诺 | DoD | 承诺方 | 状态 | 交付时间 | Receipt |\n"
           "|---|---|---|---|---|---|---|---|\n")
    _write(tmp / "scripts" / "dummy.py", "# dummy\nprint('ok')\n")
    _write(tmp / "docs" / "adr" / "dummy.md", "# dummy\n")
    old = time.time() - 20 * 60
    for rel in ("COMMITMENTS.md", "scripts/dummy.py", "docs/adr/dummy.md"):
        os.utime(tmp / rel, (old, old))
    return tmp


def _run_cli(root, *args, now=None):
    cmd = [sys.executable, str(ROOT / "scripts" / "pm_turn_precheck.py"),
           "--project-root", str(root)] + list(args)
    if now is not None:
        cmd += ["--now", now.strftime("%Y-%m-%dT%H:%M:%SZ")]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       env={**os.environ, "PYTHONUTF8": "1"}, cwd=str(root))
    return p.returncode, p.stdout, p.stderr


class PrecheckV2Test(unittest.TestCase):

    def setUp(self):
        self.tmp = _mk_root()
        self.ep_dir = self.tmp / ".precheck"
        if self.ep_dir.exists():
            shutil.rmtree(self.ep_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_01_head_writes_epoch_file(self):
        rc, out, err = _run_cli(self.tmp, "--mode", "head")
        ep = self.ep_dir / "last_head.json"
        self.assertTrue(ep.exists(), msg="epoch missing. out=" + out)
        data = json.loads(ep.read_text(encoding="utf-8"))
        for k in ("timestamp", "pid", "cwd", "summary", "head_ok"):
            self.assertIn(k, data)
        self.assertTrue(data["head_ok"], msg="head_ok should be True on clean root. out=" + out)
        self.assertEqual(rc, 0, msg="head rc should be 0. out=" + out)
        self.assertIn("EPOCH", out)

    def test_02_tail_fails_without_head(self):
        rc, out, err = _run_cli(self.tmp, "--mode", "tail")
        self.assertNotEqual(rc, 0)
        self.assertIn("HEAD_NOT_RUN", out)

    def test_03_tail_fails_with_stale_head(self):
        now = datetime(2026, 7, 10, 0, 0, 0, tzinfo=CN_TZ)
        _run_cli(self.tmp, "--mode", "head", now=now)
        future = now + timedelta(minutes=20)
        rc, out, err = _run_cli(self.tmp, "--mode", "tail", now=future)
        self.assertNotEqual(rc, 0)
        self.assertIn("HEAD_STALE", out)

    def test_04_tail_fails_with_failed_head(self):
        self.ep_dir.mkdir(exist_ok=True)
        ep = self.ep_dir / "last_head.json"
        _write(ep, json.dumps({
            "timestamp": datetime.now(tz=CN_TZ).isoformat(),
            "pid": os.getpid(), "cwd": str(self.tmp),
            "summary": "0 OK, 0 WARN, 1 FAIL", "head_ok": False
        }))
        rc, out, err = _run_cli(self.tmp, "--mode", "tail")
        self.assertNotEqual(rc, 0)
        self.assertIn("HEAD_FAILED", out)

    def test_05_bypass_detection(self):
        _run_cli(self.tmp, "--mode", "head")
        art = self.tmp / "_artifacts.json"
        _write(art, json.dumps({"tools": [
            {"name": "write"},
            {"name": "exec"},
        ]}))
        rc, out, err = _run_cli(self.tmp, "--mode", "tail",
                                "--turn-artifacts", str(art))
        self.assertNotEqual(rc, 0)
        self.assertIn("BYPASSED_HEAD_GATE", out)

    def test_06_tail_no_visible_output(self):
        _run_cli(self.tmp, "--mode", "head")
        art = self.tmp / "_artifacts.json"
        _write(art, json.dumps({"tools": [
            {"name": "pm_turn_precheck"}
        ]}))
        rc, out, err = _run_cli(self.tmp, "--mode", "tail",
                                "--turn-artifacts", str(art))
        self.assertNotEqual(rc, 0)
        self.assertIn("NO_VISIBLE_OUTPUT", out)

    def test_07_fake_done_tail(self):
        _run_cli(self.tmp, "--mode", "head")
        art = self.tmp / "_artifacts.json"
        _write(art, json.dumps({"tools": [
            {"name": "pm_turn_precheck"}
        ]}))
        last = self.tmp / "_last.txt"
        _write(last, "已经装好了，搞定了，没问题了")
        rc, out, err = _run_cli(self.tmp, "--mode", "tail",
                                "--turn-artifacts", str(art),
                                "--last-assistant-file", str(last))
        self.assertNotEqual(rc, 0)
        self.assertIn("FAKE_DONE_TAIL", out)

    def test_08_degraded_mode(self):
        # head without any extra args should not crash, must emit DEGRADED_MODE
        rc, out, err = _run_cli(self.tmp, "--mode", "head")
        self.assertNotIn("Traceback", err)
        self.assertIn("DEGRADED_MODE", out)

    def test_09_backwards_compat(self):
        rc, out, err = _run_cli(self.tmp)  # no --mode => head default
        ep = self.ep_dir / "last_head.json"
        self.assertTrue(ep.exists())
        self.assertEqual(rc, 0, msg="default mode should pass on clean root; out=" + out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
