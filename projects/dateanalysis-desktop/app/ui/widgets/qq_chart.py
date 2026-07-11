from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from app.services.data_processor import infer_numeric_series


try:
    from scipy.stats import norm as _norm  # type: ignore
    _HAS_SCIPY = True
except ImportError:  # pragma: no cover - optional dependency
    _norm = None
    _HAS_SCIPY = False


COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]




def _norm_ppf(p: np.ndarray) -> np.ndarray:
    # Peter J. Acklam 近似逆正态 CDF，精度约 1e-9
    p = np.asarray(p, dtype=float)
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]
    plow = 0.02425
    phigh = 1 - plow
    q = np.empty_like(p)
    # lower region
    low = p < plow
    ql = np.sqrt(-2 * np.log(p[low]))
    q[low] = (((((c[0]*ql+c[1])*ql+c[2])*ql+c[3])*ql+c[4])*ql+c[5]) /             ((((d[0]*ql+d[1])*ql+d[2])*ql+d[3])*ql+1)
    # upper region
    high = p > phigh
    qu = np.sqrt(-2 * np.log(1 - p[high]))
    q[high] = -(((((c[0]*qu+c[1])*qu+c[2])*qu+c[3])*qu+c[4])*qu+c[5]) /              ((((d[0]*qu+d[1])*qu+d[2])*qu+d[3])*qu+1)
    # middle region
    mid = ~(low | high)
    qm = p[mid] - 0.5
    r = qm * qm
    q[mid] = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*qm /             (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    return q



def _norm_ppf_dispatch(probs: np.ndarray) -> np.ndarray:
    if _HAS_SCIPY and _norm is not None:
        return _norm.ppf(probs)
    return _norm_ppf(probs)
class QQChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        pg.setConfigOptions(antialias=True, background="w", foreground="#222222")
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.addLegend(offset=(10, 10))
        self.plot.setAspectLocked(False)
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

    def plot_columns(self, df: pd.DataFrame, columns: Iterable[str], title: str = "Q-Q 图（vs 正态）") -> list[str]:
        self.clear()
        messages: list[str] = []
        self.plot.setTitle(title, color="#222", size="12pt")
        self.plot.setLabel("bottom", "理论正态分位数")
        self.plot.setLabel("left", "样本分位数")

        any_drawn = False
        xs_all = []
        ys_all = []
        for idx, col in enumerate(columns):
            if col not in df.columns:
                messages.append(f"列\"{col}\"不存在，已跳过。")
                continue
            s = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
            if s.size < 8:
                messages.append(f"列\"{col}\"有效样本过少（<8），跳过 Q-Q 图。")
                continue
            s_sorted = np.sort(s)
            n = s_sorted.size
            # Blom 分位偏移
            probs = (np.arange(1, n + 1) - 0.375) / (n + 0.25)
            # 不引入 scipy 依赖：用 Acklam 近似计算正态分布分位数
            theoretical = _norm_ppf_dispatch(probs)
            color = COLORS[idx % len(COLORS)]
            qcolor = QColor(color)
            self.plot.plot(theoretical, s_sorted, pen=None, symbol="o", symbolSize=5, symbolBrush=color, symbolPen=pg.mkPen(color=color, width=0.8), name=col)
            # y=x 参考线（对每个列用该列均值/斜率）
            mu = float(s_sorted.mean())
            sigma = float(s_sorted.std(ddof=1)) if n > 1 else 1.0
            if sigma <= 0:
                sigma = 1.0
            lo, hi = float(theoretical.min()), float(theoretical.max())
            self.plot.plot([lo, hi], [mu + sigma * lo, mu + sigma * hi], pen=pg.mkPen(color=color, width=1.2, style=Qt.PenStyle.DashLine))
            xs_all.extend([lo, hi]); ys_all.extend([mu + sigma * lo, mu + sigma * hi])
            any_drawn = True

        if not any_drawn:
            self.plot.setTitle("无有效绘图数据")
            messages.append("无可绘制 Q-Q 图的数值列。")
        self.plot.getViewBox().autoRange()
        return messages
