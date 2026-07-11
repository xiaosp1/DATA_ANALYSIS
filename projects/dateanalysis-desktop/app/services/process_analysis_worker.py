"""工艺分析后台 Worker（QRunnable）。

复用 services/worker.py 中的通用 Worker 其实就够了，这里提供一个命名化的
封装，便于未来扩展进度上报（比如 fit_greedy_tree 逐状态完成时回传进度）。
"""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class ProcessAnalysisSignals(QObject):
    started = Signal()
    finished = Signal(dict)   # report dict
    failed = Signal(str, str)  # (msg, traceback)
    progress = Signal(str, int)  # (msg, percent 0-100)


class ProcessAnalysisWorker(QRunnable):
    """在后台线程调用 build_analysis_report。"""

    def __init__(self, fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = ProcessAnalysisSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:  # noqa: D401
        self.signals.started.emit()
        try:
            # 注入进度回调（若被调用函数接受）
            import inspect

            try:
                sig = inspect.signature(self.fn)
                if "report_progress" in sig.parameters:
                    self.kwargs["report_progress"] = lambda pct, msg="": self.signals.progress.emit(str(msg), int(pct))
            except (TypeError, ValueError):
                pass
            self.signals.progress.emit("开始分析...", 5)
            result = self.fn(*self.args, **self.kwargs)
            self.signals.progress.emit("分析完成", 100)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            self.signals.failed.emit(str(exc), tb)
        else:
            self.signals.finished.emit(dict(result))
