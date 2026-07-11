#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for pm_turn_precheck.py (unittest)."""
import os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pm_turn_precheck as pcp

CN_TZ = timezone(timedelta(hours=8))

def _write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace("\r\n","\n").encode("utf-8"))

def _touch(p, ts):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists(): p.write_bytes(b"")
    e = ts.timestamp()
    os.utime(p, (e,e))

def _init_pending_old(root, now, target_rel):
    reg = now - timedelta(minutes=45)
    body = (
        "# COMMITMENTS\n\n"
        "| ID | " + "\u65f6\u95f4" + " | " + "\u627f\u8bfa" + " | DoD | " + "\u627f\u8bfa\u65b9" + " | " + "\u72b6\u6001" + " | " + "\u4ea4\u4ed8\u65f6\u95f4" + " | Receipt |\n"
        "|---|---|---|---|---|---|---|---|\n"
        f"| X001 | {reg.strftime('%Y-%m-%d %H:%M')} | write {target_rel} | {target_rel} exists and runs | afe | PENDING | - | - |\n"
    )
    _write(root/"COMMITMENTS.md", body)

class PrecheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/"scripts").mkdir()
        (self.root/"docs"/"adr").mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026,7,9,12,40,0,tzinfo=CN_TZ)
    def tearDown(self):
        self.tmp.cleanup()
    def _clean_commitments(self):
        body = (
            "# COMMITMENTS\n\n"
            "| ID | " + "\u65f6\u95f4" + " | " + "\u627f\u8bfa" + " | DoD | " + "\u627f\u8bfa\u65b9" + " | " + "\u72b6\u6001" + " | " + "\u4ea4\u4ed8\u65f6\u95f4" + " | Receipt |\n"
            "|---|---|---|---|---|---|---|---|\n"
        )
        _write(self.root/"COMMITMENTS.md", body)
    def test_pending_over_30m_fails(self):
        _init_pending_old(self.root, self.now, "scripts/foo.py")
        _touch(self.root/"scripts"/"foo.py", self.now - timedelta(minutes=50))
        rep = pcp.run(self.root, now=self.now)
        fails = [f for f in rep.items if f.level=="FAIL" and f.code=="COMMITMENTS_PENDING"]
        self.assertTrue(fails, msg=[(x.level,x.code,x.msg) for x in rep.items])
        self.assertTrue(rep.has_fail())
    def test_fake_done_without_receipt_fails(self):
        self._clean_commitments()
        last = self.root/"last_assistant.txt"
        _write(last, "\u6211\u5df2\u5b8c\u6210\u3002\u5df2\u6d6eworker\u5728\u8dd1\uff0c\u7ee7\u7eed\u7b49\u3002")
        rep = pcp.run(self.root, last_assistant_file=str(last), now=self.now)
        fails = [f for f in rep.items if f.level=="FAIL" and f.code=="FAKE_DONE"]
        self.assertTrue(fails, msg=[(x.level,x.code,x.msg) for x in rep.items])
        self.assertTrue(rep.has_fail())
    def test_clean_exits_zero(self):
        self._clean_commitments()
        target = self.root/"scripts"/"artifact.py"
        _write(target, "print('hi')\n")
        _touch(target, self.now - timedelta(seconds=20))
        last = self.root/"last_assistant.txt"
        _write(last, "done.\n<tool name=\"write\"></tool>\n")
        rep = pcp.run(self.root, last_assistant_file=str(last), now=self.now)
        fails = [f for f in rep.items if f.level=="FAIL"]
        self.assertEqual(fails, [], msg=[(x.level,x.code,x.msg) for x in rep.items])
        self.assertFalse(rep.has_fail())

if __name__ == "__main__":
    unittest.main()
