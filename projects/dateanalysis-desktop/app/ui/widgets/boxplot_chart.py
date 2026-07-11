from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QVBoxLayout, QWidget

from app.services.descriptive_service import distribution_data


COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]


class BoxPlotChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        pg.setConfigOptions(antialias=True, background="w", foreground="#222222")
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=False, y=True, alpha=0.2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)

    def clear(self) -> None:
        self.plot.clear()
        self.plot.setTitle("")
        self.plot.setLabel("bottom", "")
        self.plot.setLabel("left", "")
        tip = pg.TextItem(text="请在左侧配置并点击\"开始描述统计分析\"", color="#999", anchor=(0.5, 0.5))
        tip.setPos(0.5, 0.5)
        self.plot.addItem(tip)

    def plot_columns(self, df: pd.DataFrame, columns: Iterable[str], iqr_k: float = 1.5, title: str = "箱线图") -> list[str]:
        self.clear()
        messages: list[str] = []
        self.plot.setTitle(title, color="#222", size="12pt")
        self.plot.setLabel("bottom", "列")
        self.plot.setLabel("left", "数值")

        ticks = []
        x_positions = []
        all_ys = []
        valid_cols = []
        for i, col in enumerate(columns):
            if col not in df.columns:
                messages.append(f"列\"{col}\"不存在，已跳过。")
                continue
            d = distribution_data(df, col, bins=2, iqr_k=iqr_k)
            if d.q1 is None or d.q3 is None:
                messages.append(f"列\"{col}\"无有效数值，无法绘制箱线图。")
                continue
            x = float(i + 1)
            valid_cols.append((col, d, x, i))
            x_positions.append(x)
            ticks.append((x, col))
            all_ys.append(d.edges.min())
            all_ys.append(d.edges.max())
            if d.outliers.size:
                all_ys.append(float(d.outliers.min()))
                all_ys.append(float(d.outliers.max()))

        if not valid_cols:
            self.plot.setTitle("无有效绘图数据")
            return ["无有效数值列，箱线图未绘制。"]

        for col, d, x, idx in valid_cols:
            color = COLORS[idx % len(COLORS)]
            qcolor = QColor(color)
            pen = QPen(qcolor, 2.0)
            whisker_pen = QPen(qcolor, 1.8, Qt.PenStyle.SolidLine)
            median_pen = QPen(QColor("#222222"), 2.2)
            box_brush = QBrush(QColor(qcolor.red(), qcolor.green(), qcolor.blue(), 110))

            q1 = float(d.q1)
            q3 = float(d.q3)
            med = float(d.median)
            mean = float(d.mean) if d.mean is not None else None
            lo = float(d.iqr_lower)
            hi = float(d.iqr_upper)
            # 须线端点（不超过数据范围）
            valid_arr = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
            data_lo = float(np.nanmin(valid_arr))
            data_hi = float(np.nanmax(valid_arr))
            whisker_lo = max(lo, data_lo)
            whisker_hi = min(hi, data_hi)
            w = 0.55
            # 箱体
            rect = QGraphicsRectItem(QRectF(x - w / 2, q1, w, q3 - q1))
            rect.setPen(pen)
            rect.setBrush(box_brush)
            self.plot.addItem(rect)
            # 中位线（黑色加粗，清晰可见）
            self.plot.plot([x - w/2, x + w/2], [med, med], pen=median_pen)
            # 须线
            self.plot.plot([x, x], [q1, whisker_lo], pen=whisker_pen)
            self.plot.plot([x, x], [q3, whisker_hi], pen=whisker_pen)
            self.plot.plot([x - w/3, x + w/3], [whisker_lo, whisker_lo], pen=whisker_pen)
            self.plot.plot([x - w/3, x + w/3], [whisker_hi, whisker_hi], pen=whisker_pen)
            # 均值点
            if mean is not None:
                self.plot.plot([x], [mean], pen=None, symbol="o", symbolSize=7, symbolBrush=pg.mkBrush("#ffd400"), symbolPen=pg.mkPen(color=color, width=1.0))
            # 离群点
            if d.outliers.size:
                xs = np.full_like(d.outliers, x, dtype=float)
                self.plot.plot(xs, d.outliers.astype(float), pen=None, symbol="o", symbolSize=7,
                               symbolBrush=pg.mkBrush(QColor(qcolor.red(), qcolor.green(), qcolor.blue(), 180)),
                               symbolPen=pg.mkPen(color=QColor("#b00"), width=1.2))
                messages.append(f"{col}：检测到离群点 {d.outliers.size} 个。")

        ax = self.plot.getAxis("bottom")
        ax.setTicks([ticks])
        if all_ys:
            ymin, ymax = float(min(all_ys)), float(max(all_ys))
            pad = max(1e-6, (ymax - ymin) * 0.05)
            self.plot.setXRange(0.3, len(valid_cols) + 0.7, padding=0)
            self.plot.setYRange(ymin - pad, ymax + pad, padding=0)
        return messages
