from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class WorkerSignals(QObject):
    """Signals for a Worker runnable."""

    started = Signal()
    finished = Signal()
    error = Signal(str, str)  # (message, traceback)
    result = Signal(object)   # return value
    progress = Signal(int, str)  # (percent 0-100, message)


class Worker(QRunnable):
    """Run a callable in a QThreadPool; communicates via signals.

    The callable receives a `report_progress(percent, msg)` kwarg if it
    accepts it (detected by introspection) so it can publish progress.
    """

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:  # noqa: D401
        self.signals.started.emit()
        try:
            import inspect

            try:
                sig = inspect.signature(self.fn)
                if "report_progress" in sig.parameters:
                    self.kwargs["report_progress"] = lambda pct, msg="": self.signals.progress.emit(int(pct), msg)
            except (TypeError, ValueError):
                pass
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            self.signals.error.emit(str(exc), tb)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class ThreadPool:
    """Thin wrapper around QThreadPool.default() with convenience run method."""

    _instance: "ThreadPool | None" = None

    def __init__(self) -> None:
        self.pool = QThreadPool.globalInstance()

    @classmethod
    def instance(cls) -> "ThreadPool":
        if cls._instance is None:
            cls._instance = ThreadPool()
        return cls._instance

    def start(self, worker: Worker) -> None:
        self.pool.start(worker)
