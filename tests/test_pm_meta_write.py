#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for pm_meta_write.py."""
import pathlib, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "pm_meta_write.py"


def run(args, stdin_text=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin_text, capture_output=True, text=True, encoding="utf-8",
    )


class MetaWriteTests(unittest.TestCase):
    def test_writes_utf8_nobom_lf(self):
        with tempfile.TemporaryDirectory() as td:
            tgt = pathlib.Path(td) / "out.md"
            r = run([str(tgt), "--text", "# h\r\nline2\r\n", "--quiet"])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            data = tgt.read_bytes()
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), "BOM found")
            self.assertEqual(data.count(b"\r"), 0, "CR found")
            self.assertTrue(data.endswith(b"\n"))
            text = data.decode("utf-8")
            self.assertIn("# h", text)
            self.assertIn("line2", text)
            self.assertIn("META_WRITE_RECEIPT", r.stdout)

    def test_stdin_mode(self):
        with tempfile.TemporaryDirectory() as td:
            tgt = pathlib.Path(td) / "out.md"
            r = run([str(tgt), "--stdin", "--quiet"], stdin_text="hello world\n")
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertIn("META_WRITE_RECEIPT", r.stdout)
            self.assertEqual(tgt.read_text(encoding="utf-8"), "hello world\n")

    def test_append_mode(self):
        with tempfile.TemporaryDirectory() as td:
            tgt = pathlib.Path(td) / "out.md"
            run([str(tgt), "--text", "first\n", "--quiet"])
            r = run([str(tgt), "--text", "second\n", "--append", "--quiet"])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            text = tgt.read_text(encoding="utf-8")
            self.assertIn("first", text)
            self.assertIn("second", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
