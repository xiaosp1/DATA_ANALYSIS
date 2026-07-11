#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pm_meta_write.py - unified writer for PM metadata files.

Enforces: UTF-8 no BOM, LF newlines, write+read-back, sha256, stat, receipt.
Exit 0 on success, 1 on error. Prints META_WRITE_RECEIPT on success.

Usage:
  python scripts/pm_meta_write.py <path> --text "inline content"
  python scripts/pm_meta_write.py <path> --stdin
  python scripts/pm_meta_write.py <path> --file <src> [--append] [--quiet]
"""
from __future__ import annotations
import argparse, hashlib, pathlib, sys
from datetime import datetime

NEWLINE = "\n"
CR = "\r"
CRLF = "\r\n"


def normalize_newlines(text):
    text = text.replace(CRLF, NEWLINE).replace(CR, NEWLINE)
    out = [ln.rstrip() for ln in text.split(NEWLINE)]
    while out and out[-1] == "":
        out.pop()
    return NEWLINE.join(out) + NEWLINE


def write_file(target, content, append):
    target.parent.mkdir(parents=True, exist_ok=True)
    final = normalize_newlines(content)
    if append and target.exists():
        prev = target.read_text(encoding="utf-8")
        prev = prev.rstrip(NEWLINE) + NEWLINE
        final = normalize_newlines(prev + content)
    data = final.encode("utf-8")  # no BOM
    target.write_bytes(data)
    rb = target.read_bytes()
    if rb != data:
        raise RuntimeError("post-write bytes mismatch")
    st = target.stat()
    return {
        "path": str(target.resolve()),
        "size": st.st_size,
        "sha256": hashlib.sha256(rb).hexdigest(),
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "head": final.split(NEWLINE)[:30],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--text")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    sources = sum(1 for x in (args.text, args.stdin, args.file) if x)
    if sources != 1:
        sys.stderr.write("ERROR: exactly one of --text/--stdin/--file required\n"); return 2
    if args.text is not None:
        content = args.text
    elif args.stdin:
        content = sys.stdin.read()
    elif args.file:
        content = pathlib.Path(args.file).read_text(encoding="utf-8")
    else:
        return 2
    target = pathlib.Path(args.path)
    if not target.is_absolute():
        target = pathlib.Path.cwd() / target
    try:
        info = write_file(target, content, args.append)
    except Exception as e:
        sys.stderr.write("ERROR: write failed: " + str(e) + "\n"); return 1
    if not args.quiet:
        print("--- head (first 30 lines) ---")
        for i, line in enumerate(info["head"], 1):
            print("{:>3}| {}".format(i, line))
        print("--- /head ---")
    print("META_WRITE_RECEIPT path={path} size={size} sha256={sha256} mtime={mtime}".format(**info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
