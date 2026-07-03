from __future__ import annotations

from pathlib import Path


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def get_file_extension(path: str | Path) -> str:
    return Path(path).suffix.lower()


def is_supported_file(path: str | Path) -> bool:
    return get_file_extension(path) in SUPPORTED_EXTENSIONS


def human_size(size_in_bytes: int) -> str:
    size = float(size_in_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"
