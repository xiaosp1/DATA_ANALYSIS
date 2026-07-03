from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtGui import QPixmap


class ExportError(Exception):
    pass


def export_stats_to_csv(df: pd.DataFrame, path: str | Path) -> None:
    try:
        df.to_csv(path, index=False, encoding="utf-8-sig")
    except Exception as exc:
        raise ExportError(f"导出统计结果 CSV 失败：{exc}") from exc


def export_stats_to_excel(df: pd.DataFrame, path: str | Path) -> None:
    try:
        df.to_excel(path, index=False)
    except Exception as exc:
        raise ExportError(f"导出统计结果 Excel 失败：{exc}") from exc


def export_plot_widget_to_png(plot_widget, path: str | Path) -> None:
    try:
        pixmap: QPixmap = plot_widget.grab()
        ok = pixmap.save(str(path), "PNG")
        if not ok:
            raise ExportError("保存 PNG 失败。")
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f"导出图表图片失败：{exc}") from exc
