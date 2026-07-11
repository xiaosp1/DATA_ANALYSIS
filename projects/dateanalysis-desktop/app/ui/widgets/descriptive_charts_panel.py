from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from app.ui.widgets.boxplot_chart import BoxPlotChart
from app.ui.widgets.correlation_chart import CorrelationHeatmap
from app.ui.widgets.histogram_chart import HistogramChart
from app.ui.widgets.qq_chart import QQChart
from app.ui.widgets.scatter_matrix_chart import ScatterMatrixChart


class DescriptiveChartsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.hist = HistogramChart()
        self.box = BoxPlotChart()
        self.qq = QQChart()
        self.corr = CorrelationHeatmap()
        self.scatter = ScatterMatrixChart()

        self._placeholder = QLabel("请在左侧配置并点击\"开始描述统计分析\"")
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet("color:#888; padding:24px;")

        self.tabs.addTab(self.hist, "直方图+KDE")
        self.tabs.addTab(self.box, "箱线图")
        self.tabs.addTab(self.qq, "Q-Q 图")
        self.tabs.addTab(self.corr, "相关矩阵")
        self.tabs.addTab(self.scatter, "散点矩阵")

    def render(
        self,
        df: pd.DataFrame,
        numeric_cols: list[str],
        *,
        bins: int = 30,
        show_kde: bool = True,
        show_mean: bool = True,
        show_median: bool = True,
        iqr_k: float = 1.5,
        corr_method: str = "pearson",
        show_scatter_matrix: bool = True,
        show_qq: bool = True,
    ) -> list[str]:
        messages: list[str] = []
        messages += self.hist.plot_columns(df, numeric_cols, bins=bins, show_kde=show_kde,
                                           show_mean=show_mean, show_median=show_median, iqr_k=iqr_k)
        messages += self.box.plot_columns(df, numeric_cols, iqr_k=iqr_k)
        if show_qq:
            messages += self.qq.plot_columns(df, numeric_cols)
        else:
            self.qq.clear()
        from app.services.descriptive_service import correlation_matrix
        corr = correlation_matrix(df, numeric_cols, method=corr_method)
        messages += self.corr.set_matrix(corr, method=corr_method)
        if show_scatter_matrix and len(numeric_cols) >= 2:
            # Cap to 6 columns to avoid NxN blowup
            cols = numeric_cols[:6]
            if len(numeric_cols) > 6:
                messages.append(f"散点矩阵仅显示前 6 个数值列（避免图形过密）。")
            messages += self.scatter.plot_columns(df, cols)
        else:
            self.scatter.clear()
        return messages

    def clear(self) -> None:
        self.hist.clear(); self.box.clear(); self.qq.clear(); self.corr.clear(); self.scatter.clear()
