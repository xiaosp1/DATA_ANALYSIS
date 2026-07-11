from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.services.descriptive_service import correlation_matrix


class CorrelationHeatmap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        pg.setConfigOptions(antialias=True, background="w", foreground="#222")
        self.plot = pg.PlotWidget()
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self._text_items: list[pg.TextItem] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)

    def clear(self) -> None:
        self.plot.clear()
        for it in self._text_items:
            try:
                self.plot.removeItem(it)
            except Exception:
                pass
        self._text_items.clear()
        self.plot.setTitle("")
        tip = pg.TextItem(text="请在左侧配置并点击\"开始描述统计分析\"", color="#999", anchor=(0.5, 0.5))
        tip.setPos(0.5, 0.5)
        self.plot.addItem(tip)

    def _cmap(self, v: float) -> QColor:
        # diverging blue-white-red centered at 0
        v = max(-1.0, min(1.0, float(v)))
        if v >= 0:
            t = v
            r = int(255)
            g = int(255 * (1 - t) + 60 * t)
            b = int(255 * (1 - t) + 60 * t)
        else:
            t = -v
            r = int(255 * (1 - t) + 60 * t)
            g = int(255 * (1 - t) + 80 * t)
            b = int(255)
        return QColor(r, g, b)

    def set_matrix(self, df: pd.DataFrame, method: str = "pearson") -> list[str]:
        self.clear()
        messages: list[str] = []
        if df is None or df.empty or df.shape[0] != df.shape[1]:
            self.plot.setTitle("相关矩阵无数据")
            return ["无可用的相关矩阵。"]
        labels = list(df.columns)
        n = len(labels)
        mat = df.to_numpy(dtype=float)
        self.plot.setTitle(f"相关系数矩阵（{method}）", color="#222", size="12pt")

        # draw cells as ImageItem; easier & interactive
        # Use ImageItem with color mapping via a 2D of QColor? Simpler approach: loop with QGraphicsRectItem.
        from PySide6.QtWidgets import QGraphicsRectItem
        from PySide6.QtGui import QBrush, QPen
        cell = 1.0
        pen = QPen(QColor("#ddd"))
        pen.setWidthF(0.6)
        for i in range(n):
            for j in range(n):
                v = float(mat[i, j]) if not np.isnan(mat[i, j]) else 0.0
                rect = QGraphicsRectItem(j, n - 1 - i, cell, cell)
                rect.setPen(pen)
                rect.setBrush(QBrush(self._cmap(v)))
                self.plot.addItem(rect)
                txt = pg.TextItem(text=f"{v:.2f}", color="#222", anchor=(0.5, 0.5))
                txt.setPos(j + cell / 2, n - 1 - i + cell / 2)
                self.plot.addItem(txt)
                self._text_items.append(txt)

        # axis labels
        ax_top = self.plot.getAxis("top")
        ax_bottom = self.plot.getAxis("bottom")
        ax_left = self.plot.getAxis("left")
        self.plot.showAxis("top", True)
        self.plot.showAxis("bottom", True)
        self.plot.showAxis("left", True)
        ticks = [(i + 0.5, labels[i]) for i in range(n)]
        ax_bottom.setTicks([ticks])
        ax_top.setTicks([ticks])
        left_ticks = [(n - 1 - i + 0.5, labels[i]) for i in range(n)]
        ax_left.setTicks([left_ticks])
        self.plot.setXRange(0, n, padding=0.02)
        self.plot.setYRange(0, n, padding=0.02)
        self.plot.getViewBox().setMouseEnabled(x=False, y=False)
        self.plot.showGrid(x=False, y=False)
        return messages
