from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


class AppLogger:
    def __init__(self, logs_dir: str | Path = "logs"):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("DateAnalysis")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        self._current_date = datetime.now().strftime("%Y-%m-%d")
        self._file_path = self.logs_dir / f"app_{self._current_date}.log"

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = logging.FileHandler(self._file_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(formatter)
        self._logger.addHandler(stream_handler)

    def _rotate_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            for handler in list(self._logger.handlers):
                if isinstance(handler, logging.FileHandler):
                    self._logger.removeHandler(handler)
                    handler.close()
            self._current_date = today
            self._file_path = self.logs_dir / f"app_{today}.log"
            handler = logging.FileHandler(self._file_path, encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            self._logger.addHandler(handler)

    @property
    def current_log_file(self) -> Path:
        self._rotate_if_needed()
        return self._file_path

    def logs_directory(self) -> Path:
        return self.logs_dir

    def debug(self, msg: str):
        self._rotate_if_needed(); self._logger.debug(msg)

    def info(self, msg: str):
        self._rotate_if_needed(); self._logger.info(msg)

    def warning(self, msg: str):
        self._rotate_if_needed(); self._logger.warning(msg)

    def error(self, msg: str, exc: Exception | None = None):
        self._rotate_if_needed()
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self._logger.error(f"{msg}\n{tb}")
        else:
            self._logger.error(msg)

    def exception(self, msg: str):
        self._rotate_if_needed()
        self._logger.exception(msg)
