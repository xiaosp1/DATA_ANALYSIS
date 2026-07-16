#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for pm_turn_precheck.py (unittest)."""
import json
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

def _write_bytes(path, b):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b)


def _seed_cache(root, file_mtime_pairs):
    """Seed .precheck/last_encoding_scan.json with given relpath→mtime pairs."""
    cache_path = root / pcp.LAST_ENCODING_SCAN_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    snap = {"version": 1, "files": {rel: mt for rel, mt in file_mtime_pairs}}
    cache_path.write_bytes(
        (json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        .encode("utf-8")
    )


class IncrementalEncodingTests(unittest.TestCase):
    """C038: incremental LF/CRLF/BOM detection (NEW/MODIFIED FAIL, pre-existing WARN)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Resolve root to avoid Windows 8.3 short path mismatches between
        # what rel() returns and what we seed into the cache.
        self.root = Path(self.tmp.name).resolve()
        (self.root / "scripts").mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 7, 15, 19, 0, 0, tzinfo=CN_TZ)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_artifact_skips_check(self):
        """Empty scripts dir → no files to scan → WARN ENCODING_SANITY, not FAIL."""
        rep = pcp.Report()
        pcp.check_encoding(self.root, rep)
        items = [(x.level, x.code, x.msg) for x in rep.items]
        fails = [x for x in rep.items
                 if x.level == "FAIL" and x.code == "ENCODING_SANITY"]
        self.assertFalse(fails,
                         msg="empty project must NOT FAIL ENCODING_SANITY, got: "
                         + str(items))

    def test_lf_clean_artifact_passes(self):
        """Last-scan empty + new LF clean file → ENCODING_SANITY OK."""
        _seed_cache(self.root, [])
        good = self.root / "scripts" / "clean_lf.py"
        _write_bytes(good, b"print('hi')\nprint('clean')\n")
        rep = pcp.Report()
        pcp.check_encoding(self.root, rep)
        oks = [x for x in rep.items
               if x.level == "OK" and x.code == "ENCODING_SANITY"]
        fails = [x for x in rep.items
                 if x.level == "FAIL" and x.code == "ENCODING_SANITY"]
        self.assertTrue(oks,
                        msg="expected OK ENCODING_SANITY, got: "
                        + str([(x.level, x.code, x.msg) for x in rep.items]))
        self.assertFalse(fails,
                         msg="did NOT expect FAIL: "
                         + str([f.msg for f in fails]))
        # Cache should now be persisted
        self.assertTrue((self.root / pcp.LAST_ENCODING_SCAN_REL).exists())

    def test_crlf_artifact_fails(self):
        """Last-scan empty + new CRLF file → ENCODING_SANITY FAIL with C038 marker."""
        _seed_cache(self.root, [])
        bad = self.root / "scripts" / "crlf_poison.py"
        _write_bytes(bad, b"print('crlf')\r\nprint('crlf2')\r\n")
        rep = pcp.Report()
        pcp.check_encoding(self.root, rep)
        items = [(x.level, x.code, x.msg) for x in rep.items]
        fails = [x for x in rep.items
                 if x.level == "FAIL" and x.code == "ENCODING_SANITY"]
        self.assertTrue(fails,
                        msg="expected FAIL ENCODING_SANITY, got: " + str(items))
        # message should mention C038 / NEW to distinguish from legacy FAIL
        self.assertTrue(any("C038" in f.msg or "NEW" in f.msg for f in fails),
                        msg="FAIL msg should mention C038/NEW: "
                        + str([f.msg for f in fails]))

    def test_bom_artifact_fails(self):
        """Last-scan empty + new BOM file → ENCODING_SANITY FAIL with C038 marker.
        Note: BOM bytes also break py_compile (U+FEFF non-printable), so the
        actual FAIL message may surface as SYNTAX_ERROR rather than 'BOM:'.
        We accept either 'BOM' or 'U+FEFF' / 'FEFF' as evidence the BOM was
        caught as a NEW/MODIFIED failure.
        """
        _seed_cache(self.root, [])
        bom = self.root / "scripts" / "bom_poison.py"
        _write_bytes(bom, b"\xef\xbb\xbfprint('bom')\n")
        rep = pcp.Report()
        pcp.check_encoding(self.root, rep)
        items = [(x.level, x.code, x.msg) for x in rep.items]
        fails = [x for x in rep.items
                 if x.level == "FAIL" and x.code == "ENCODING_SANITY"]
        self.assertTrue(fails,
                        msg="expected FAIL ENCODING_SANITY for BOM, got: "
                        + str(items))
        # Message should mention C038/NEW (proves it was caught as new file)
        self.assertTrue(any("C038" in f.msg or "NEW" in f.msg for f in fails),
                        msg="FAIL msg should mention C038/NEW: "
                        + str([f.msg for f in fails]))
        # Plus the BOM-specific marker (BOM literal or U+FEFF / FEFF char code)
        self.assertTrue(
            any(("BOM" in f.msg) or ("FEFF" in f.msg.upper()) for f in fails),
            msg="FAIL msg should mention BOM or FEFF: "
            + str([f.msg for f in fails]))


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
