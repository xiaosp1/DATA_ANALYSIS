from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.services.data_processor import infer_numeric_series


COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]


class ScatterMatrixChart(QWidget):
    """简易散点图矩阵：对角线显示列名，非对角线为散点。"""

    MAX_POINTS_PER_CELL = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        pg.setConfigOptions(antialias=True, background="w", foreground="#222")
        self.view = pg.GraphicsLayoutWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def clear(self) -> None:
        self.view.clear()
        tip = pg.LabelItem("请选择至少 2 个数值列以绘制散点矩阵", color="#999")
        self.view.addItem(tip)

    def plot_columns(self, df: pd.DataFrame, columns: Iterable[str], title: str = "散点图矩阵") -> list[str]:
        self.clear()
        messages: list[str] = []
        cols = [c for c in columns if c in df.columns]
        if len(cols) < 2:
            label = pg.LabelItem("散点图矩阵至少需要选择 2 个数值列", color="#888")
            self.view.addItem(label)
            return ["散点图矩阵至少需要 2 个数值列。"]

        n = len(cols)
        self.view.addLabel(title, row=0, col=0, colspan=n, size="12pt", bold=True)
        plots = {}
        # pre-convert numeric columns
        data = {}
        for c in cols:
            s = pd.to_numeric(df[c], errors="coerce").dropna()
            arr = s.to_numpy(dtype=float)
            data[c] = arr

        link_ax = None
        for i, yc in enumerate(cols, start=1):
            for j, xc in enumerate(cols):
                pi = self.view.addPlot(row=i, col=j)
                plots[(i, j)] = pi
                pi.hideButtons()
                pi.setMenuEnabled(False)
                if i == 1:
                    pi.setTitle(xc, size="9pt")
                if j == 0:
                    pi.setLabel("left", yc, size="9pt")
                if j > 0:
                    pi.getAxis("left").setStyle(showValues=False)
                if i < n:
                    pi.getAxis("bottom").setStyle(showValues=False)
                else:
                    pi.getAxis("bottom").setLabel(xc, size="9pt")
                pi.showGrid(x=True, y=True, alpha=0.15)
                if xc == yc:
                    # 对角线显示列名文本
                    pi.addItem(pg.TextItem(text=xc, color="#1f77b4", anchor=(0.5, 0.5)))
                    pi.setXRange(-1, 1); pi.setYRange(-1, 1)
                    pi.getAxis("left").setTicks([]); pi.getAxis("bottom").setTicks([])
                    continue
                x = data[xc]
                y = data[yc]
                # align lengths by dropping NaN pairwise
                mx = pd.Series(df[xc]); my = pd.Series(df[yc])
                pair = pd.concat([mx, my], axis=1)
                pair.columns = ["x", "y"]
                pair = pair.apply(pd.to_numeric, errors="coerce").dropna()
                xs = pair["x"].to_numpy(dtype=float)
                ys = pair["y"].to_numpy(dtype=float)
                if xs.size > self.MAX_POINTS_PER_CELL:
                    idx = np.linspace(0, xs.size - 1, self.MAX_POINTS_PER_CELL).astype(int)
                    xs = xs[idx]; ys = ys[idx]
                    messages.append(f"{xc}~{yc}：点数量过多，已采样至 {self.MAX_POINTS_PER_CELL} 个点。")
                pi.plot(xs, ys, pen=None, symbol="o", symbolSize=3, symbolBrush=QColor("#1f77b470"), symbolPen=None)
        # 简单起见，散点矩阵不做轴联动，避免子图过多影响交互
        self.view.ci.setSpacing(2)
        return messages
