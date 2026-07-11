from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.services.descriptive_service import distribution_data


COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]


class HistogramChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        pg.setConfigOptions(antialias=True, background="w", foreground="#222222")
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.addLegend(offset=(10, 10))
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

    def plot_columns(
        self,
        df: pd.DataFrame,
        columns: Iterable[str],
        bins: int = 30,
        show_kde: bool = True,
        show_mean: bool = True,
        show_median: bool = True,
        iqr_k: float = 1.5,
        title: str = "直方图 + KDE",
    ) -> list[str]:
        self.clear()
        messages: list[str] = []
        self.plot.setTitle(title, color="#222", size="12pt")
        self.plot.setLabel("bottom", "数值")
        self.plot.setLabel("left", "密度 (归一化)")

        for idx, col in enumerate(columns):
            if col not in df.columns:
                messages.append(f"列\"{col}\"不存在，已跳过。")
                continue
            d = distribution_data(df, col, bins=bins, iqr_k=iqr_k)
            if d.edges.size == 0 or d.counts.size == 0:
                messages.append(f"列\"{col}\"无有效数值，无法绘制直方图。")
                continue
            color = COLORS[idx % len(COLORS)]
            qcolor = QColor(color)
            # 画柱状：用 step-filled 或矩形。为简洁用 draw style 'steps' 不行，这里用 BarGraphItem
            width = float(d.edges[1] - d.edges[0]) if len(d.edges) > 1 else 1.0
            centers = (d.edges[:-1] + d.edges[1:]) / 2.0
            total = float(d.counts.sum()) if d.counts.sum() > 0 else 1.0
            # 使用"密度"归一化：每个 bin 的频数 / (总数 * bin宽)，这样多列量纲不同也能在同图比较分布形状
            density = d.counts.astype(float) / (total * width)
            bg = pg.BarGraphItem(x=centers, height=density, width=width * 0.92, brush=pg.mkBrush(qcolor), pen=pg.mkPen(color=qcolor, width=0.8), opacity=0.6, name=col)
            self.plot.addItem(bg)

            # KDE 已经是密度尺度，直接画；若用户关闭KDE就不画
            if show_kde and d.kde_x is not None and d.kde_y is not None:
                self.plot.plot(d.kde_x, d.kde_y, pen=pg.mkPen(color=qcolor, width=2.2), name=f"{col} KDE")

            from PySide6.QtCore import Qt as _Qt
            for val, label, style in [
                (d.mean if show_mean else None, "均值", _Qt.PenStyle.DashLine),
                (d.median if show_median else None, "中位数", _Qt.PenStyle.DotLine),
            ]:
                if val is None:
                    continue
                self.plot.addItem(pg.InfiniteLine(pos=float(val), angle=90, pen=pg.mkPen(color=qcolor, width=1.2, style=style), label=label, labelOpts={"color": color, "position": 0.92 if "均值" in label else 0.80}))

            outlier_n = int(d.outliers.size)
            if outlier_n > 0:
                messages.append(f"{col}：IQR(k={iqr_k}) 检测到离群点 {outlier_n} 个。")
        self.plot.getViewBox().autoRange()
        return messages
