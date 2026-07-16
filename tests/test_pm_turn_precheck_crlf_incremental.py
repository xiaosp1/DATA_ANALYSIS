#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C038 — pm_turn_precheck incremental CRLF/BOM detection tests.

Validates that ``check_encoding`` FAILs on files that are NEW or MODIFIED since
the previous precheck scan (cached at ``.precheck/last_encoding_scan.json``),
while keeping pre-existing polluted files as WARN (backward compat with
historical CRLF that pre-dates this guardrail).

Test matrix (≥4):
  1. test_first_scan_empty_cache          → first scan, no cache file → {}.
  2. test_new_crlf_file_fails             → last-scan empty + new CRLF file → FAIL.
  3. test_new_lf_clean_file_ok            → last-scan empty + new LF clean file → OK.
  4. test_modified_existing_file_to_crlf_fails → last-scan with old LF mtime + same
                                                file overwritten with CRLF → FAIL.
  5. test_pre_existing_crlf_with_cache_warns  → cache contains file with old
                                                mtime + file still CRLF → WARN,
                                                NOT FAIL (backward compat).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure scripts/ on path so we can import pm_turn_precheck without packaging.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pm_turn_precheck as pcp  # noqa: E402

CN_TZ = timezone(timedelta(hours=8))


def _write_bytes(path, b):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b)


def _touch(p, ts):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_bytes(b"")
    e = ts.timestamp()
    os.utime(p, (e, e))


def _seed_cache(root, file_mtime_pairs):
    """Seed .precheck/last_encoding_scan.json with given relpath→mtime pairs."""
    cache_path = root / pcp.LAST_ENCODING_SCAN_REL
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    snap = {"version": 1, "files": {rel: mt for rel, mt in file_mtime_pairs}}
    cache_path.write_bytes(
        (json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        .encode("utf-8")
    )


class IncrementalCrlfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Resolve root to avoid Windows 8.3 short path mismatches between
        # what rel() returns and what we seed into the cache.
        self.root = Path(self.tmp.name).resolve()
        (self.root / "scripts").mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 7, 15, 18, 0, 0, tzinfo=CN_TZ)

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- test 1 ----------
    def test_first_scan_empty_cache(self):
        """No cache file present → _load_last_scan returns {}."""
        self.assertFalse((self.root / pcp.LAST_ENCODING_SCAN_REL).exists())
        last = pcp._load_last_scan(self.root)
        self.assertEqual(last, {})

    # ---------- test 2 ----------
    def test_new_crlf_file_fails(self):
        """Last-scan empty + new CRLF file → ENCODING_SANITY FAIL."""
        _seed_cache(self.root, [])  # empty cache
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
        # Cache should now be persisted
        self.assertTrue((self.root / pcp.LAST_ENCODING_SCAN_REL).exists())

    # ---------- test 3 ----------
    def test_new_lf_clean_file_ok(self):
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

    # ---------- test 4 ----------
    def test_modified_existing_file_to_crlf_fails(self):
        """Cache contains clean mtime + same file now CRLF → FAIL."""
        good = self.root / "scripts" / "was_clean.py"
        _write_bytes(good, b"print('a')\nprint('b')\n")
        old_mtime = (self.now - timedelta(minutes=10)).timestamp()
        _seed_cache(self.root, [
            ("scripts/was_clean.py", old_mtime),
        ])
        # Now mutate to CRLF (newer mtime, real pollution).
        _write_bytes(good, b"print('a')\r\nprint('b')\r\n")
        rep = pcp.Report()
        pcp.check_encoding(self.root, rep)
        items = [(x.level, x.code, x.msg) for x in rep.items]
        fails = [x for x in rep.items
                 if x.level == "FAIL" and x.code == "ENCODING_SANITY"]
        self.assertTrue(fails, msg="expected FAIL ENCODING_SANITY, got: "
                        + str(items))

    # ---------- test 5 (bonus) ----------
    def test_pre_existing_crlf_with_cache_warns(self):
        """Cache already contains CRLF file → only WARN (not FAIL).
        Backward compat: don't re-fail on legacy CRLF that was scanned before.
        """
        bad = self.root / "scripts" / "legacy_crlf.py"
        _write_bytes(bad, b"print('legacy')\r\nprint('still bad')\r\n")
        # Seed cache with the file's current mtime to simulate "scanned
        # last turn, file unchanged since" (C038 semantics: mt > prev_mt
        # means modified; equal means unchanged → WARN, not FAIL).
        mtime_now = bad.stat().st_mtime
        _seed_cache(self.root, [
            ("scripts/legacy_crlf.py", mtime_now),
        ])
        rep = pcp.Report()
        pcp.check_encoding(self.root, rep)
        fails = [x for x in rep.items
                 if x.level == "FAIL" and x.code == "ENCODING_SANITY"]
        warns = [x for x in rep.items
                 if x.level == "WARN" and x.code == "ENCODING_SANITY"]
        self.assertFalse(fails,
                         msg="pre-existing CRLF must NOT FAIL after C038: "
                         + str([f.msg for f in fails]))
        self.assertTrue(warns,
                        msg="expected WARN for pre-existing CRLF: "
                        + str([(x.level, x.code, x.msg) for x in rep.items]))


if __name__ == "__main__":
    unittest.main()
