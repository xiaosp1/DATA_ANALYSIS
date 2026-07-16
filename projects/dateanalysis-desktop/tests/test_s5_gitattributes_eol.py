"""S5：验证仓库根 .gitattributes 强制 *.md / *.py 使用 LF 行尾（C031 修复）。

非业务测试，不依赖 app.*。
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GITATTR = REPO_ROOT / ".gitattributes"


def test_gitattributes_has_md_and_py_lf_rules():
    assert GITATTR.exists(), f".gitattributes missing at {GITATTR}"
    text = GITATTR.read_text(encoding="utf-8")
    assert "*.md text eol=lf" in text
    assert "*.py text eol=lf" in text


@pytest.mark.skipif(not (REPO_ROOT / ".git").exists(), reason="not in git repo")
def test_git_check_attr_recognises_md_as_text_eol_lf():
    with tempfile.TemporaryDirectory(dir=REPO_ROOT) as tmp:
        target = Path(tmp) / "sample.md"
        target.write_bytes(b"# sample\nhello\n")
        try:
            proc = subprocess.run(
                ["git", "check-attr", "-a", str(target)],
                cwd=str(REPO_ROOT),
                capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            pytest.skip("git not on PATH")
        assert proc.returncode == 0, proc.stderr
        assert "eol: lf" in proc.stdout, proc.stdout
