from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator


@contextmanager
def timed(operation: str, logger: Callable[[str, str], Any] | None = None, level: str = "info") -> Iterator[None]:
    """Context manager that logs elapsed time for a block.

    Usage:
        with timed("导入文件", self.log):
            df = pd.read_csv(...)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        msg = f"[耗时] {operation}: {elapsed_ms:.1f} ms"
        if logger is not None:
            try:
                logger(msg, level)
            except TypeError:
                logger(msg)
        else:
            logging.getLogger(__name__).info(msg)


def format_duration(seconds: float) -> str:
    """Human-friendly duration string."""
    if seconds < 1e-3:
        return f"{seconds * 1e6:.0f} us"
    if seconds < 1.0:
        return f"{seconds * 1000:.1f} ms"
    if seconds < 60:
        return f"{seconds:.2f} s"
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes}m {secs:.1f}s"
