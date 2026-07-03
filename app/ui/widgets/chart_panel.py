from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsView, QToolTip, QVBoxLayout, QWidget

GRAN_RAW = "原始"
GRAN_MIN = "分钟"
GRAN_HOUR = "小时"
GRAN_SHIFT = "班次"
GRAN_DAY = "天"
GRAN_WEEK = "周"
LABEL_MEAN = "均值"
LABEL_VALUE = "数值"
LABEL_TIME_CAT = "时间/类别"
LABEL_NO_DATA_TITLE = "无有效绘图数据"
LABEL_NO_DATA_MSG = "无有效绘图数据。"
LABEL_Y_MISSING_FMT = "Y 轴列“{}”不存在，已跳过。"
LABEL_Y_NO_VALID_FMT = "Y 轴列“{}”无有效绘图数据，已跳过。"
LABEL_DOWNSAMPLE_FMT = "数据点共 {} 个，已自动降采样至 {} 个点以保证流畅（悬停仍读取原始点）。"
LABEL_SHIFT_AM = " 早班"
LABEL_SHIFT_PM = " 晚班"

_GRANULARITY_TIME_FORMATS = {
    GRAN_RAW: "%Y-%m-%d %H:%M:%S",
    GRAN_MIN: "%Y-%m-%d %H:%M",
    GRAN_HOUR: "%Y-%m-%d %H:%M",
    GRAN_SHIFT: "%Y-%m-%d %H:%M",
    GRAN_DAY: "%Y-%m-%d",
    GRAN_WEEK: "%Y-%m-%d",
}
_MAX_PLOT_POINTS = 3000
_HOVER_TOLERANCE_PX = 14


class ChartPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        pg.setConfigOptions(antialias=True, background="w", foreground="#222222")
        self._date_axis = pg.DateAxisItem(orientation="bottom", utcOffset=0)
        self.plot_widget = pg.PlotWidget(axisItems={"bottom": self._date_axis})
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_widget)
        self._x_is_datetime = False
        self._series_data: list[dict[str, Any]] = []
        self._full_series: dict[str, dict[str, Any]] = {}
        self._mean_labels: list[tuple[Any, float]] = []
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_widget.getViewBox().sigRangeChanged.connect(self._reposition_mean_labels)
        self.clear()

    def clear(self) -> None:
        self.plot_widget.clear()
        self.plot_widget.setTitle("")
        self.plot_widget.setLabel("bottom", "")
        self.plot_widget.setLabel("left", "")
        self._date_axis.setTicks(None)
        self._x_is_datetime = False
        self._series_data = []
        self._full_series = {}
        self._mean_labels = []
        QToolTip.hideText()

    def plot_multi_line(self, chart_df, x_col, series_configs, mean_map, title,
                        show_points=True, show_mean_lines=True, x_is_datetime=False,
                        granularity=GRAN_RAW):
        messages: list[str] = []
        self.clear()
        if chart_df is None or chart_df.empty or not series_configs:
            self.plot_widget.setTitle(LABEL_NO_DATA_TITLE)
            return [LABEL_NO_DATA_MSG]

        data = chart_df.copy()
        x_series = data[x_col]
        if x_is_datetime and pd.api.types.is_datetime64_any_dtype(x_series):
            x_numeric = self._datetime_to_unix_seconds(x_series)
            self._date_axis.setTicks(None)
            self._x_is_datetime = True
        else:
            x_numeric = np.arange(len(data), dtype=float)
            labels = [str(v) for v in x_series.tolist()]
            self._date_axis.setTicks([self._build_category_ticks(labels, max_ticks=12)])
            self._x_is_datetime = False

        fmt = _GRANULARITY_TIME_FORMATS.get(granularity, "%Y-%m-%d %H:%M:%S")
        total_full_points = 0
        total_plot_points = 0

        for spec in series_configs:
            if len(spec) >= 3:
                y_col, color, series_show_mean = spec[0], spec[1], bool(spec[2])
            else:
                y_col, color = spec[0], spec[1]
                series_show_mean = bool(show_mean_lines)

            if y_col not in data.columns:
                messages.append(LABEL_Y_MISSING_FMT.format(y_col))
                continue
            y_data = pd.to_numeric(data[y_col], errors="coerce")
            mask = y_data.notna().to_numpy()
            xs_full = x_numeric[mask]
            ys_full = y_data[mask].to_numpy(dtype=float)
            if self._x_is_datetime:
                ts_subset = x_series[mask]
                if granularity == GRAN_SHIFT:
                    x_labels_full = np.array([self._format_shift_label(t) for t in ts_subset.tolist()], dtype=object)
                else:
                    x_labels_full = np.array(ts_subset.dt.strftime(fmt).tolist(), dtype=object)
            else:
                all_labels = np.array([str(v) for v in x_series.tolist()], dtype=object)
                x_labels_full = all_labels[np.where(mask)[0]]
            if len(xs_full) == 0:
                messages.append(LABEL_Y_NO_VALID_FMT.format(y_col))
                continue

            total_full_points += len(xs_full)
            self._full_series[y_col] = {"name": y_col, "color": color, "xs": xs_full, "ys": ys_full, "x_labels": x_labels_full}
            xs_plot, ys_plot = self._downsample(xs_full, ys_full, _MAX_PLOT_POINTS)
            total_plot_points += len(xs_plot)
            qcolor = QColor(color)
            show_symbols = show_points and len(xs_plot) <= 800
            self.plot_widget.plot(
                xs_plot, ys_plot,
                pen=pg.mkPen(color=qcolor, width=2),
                symbol="o" if show_symbols else None,
                symbolSize=5 if show_symbols else None,
                symbolBrush=qcolor,
                symbolPen=pg.mkPen(color=qcolor, width=1),
                name=y_col,
            )
            self._series_data.append({"name": y_col, "xs": xs_plot, "ys": ys_plot})

            if show_mean_lines and series_show_mean and y_col in mean_map:
                mean_val = float(mean_map[y_col])
                self.plot_widget.addItem(pg.InfiniteLine(pos=mean_val, angle=0, pen=pg.mkPen(color=qcolor, width=1.5, style=Qt.PenStyle.DashLine)))
                label = pg.TextItem(
                    html=f"<span style='color:{qcolor.name()};background-color:rgba(255,255,255,0.92);padding:1px 4px;white-space:nowrap;'>{y_col} {LABEL_MEAN}: {mean_val:.2f}</span>",
                    anchor=(1, 0.5),
                    color=qcolor,
                )
                label.setZValue(100)
                self.plot_widget.addItem(label, ignoreBounds=True)
                self._mean_labels.append((label, mean_val))

        if total_full_points > _MAX_PLOT_POINTS:
            messages.append(LABEL_DOWNSAMPLE_FMT.format(total_full_points, total_plot_points))

        self.plot_widget.setTitle(title, color="#222222", size="12pt")
        self.plot_widget.setLabel("bottom", x_col)
        self.plot_widget.setLabel("left", LABEL_VALUE)
        self.plot_widget.getViewBox().autoRange()
        self._position_mean_labels()
        return messages

    def _reposition_mean_labels(self, *_):
        self._position_mean_labels()

    def _position_mean_labels(self):
        if not self._mean_labels:
            return
        try:
            x_left, x_right = self.plot_widget.getViewBox().viewRange()[0]
            y_bottom, y_top = self.plot_widget.getViewBox().viewRange()[1]
        except Exception:
            return
        span = max(y_top - y_bottom, 1e-9)
        min_gap = span * 0.022
        used = []
        for label, preferred_y in self._mean_labels:
            y = self._assign_mean_label_y(used, float(preferred_y), min_gap)
            y = min(y_top - span * 0.01, max(y_bottom + span * 0.01, y))
            used.append(y)
            label.setPos(x_right, y)

    @staticmethod
    def _assign_mean_label_y(existing, mean_val, min_gap):
        if not existing:
            return mean_val
        for distance in np.arange(0.0, min_gap * 12, min_gap * 0.35):
            for direction in (1, -1) if distance > 0 else (1,):
                candidate = mean_val + direction * distance
                if all(abs(candidate - prev) >= min_gap for prev in existing):
                    return candidate
        return mean_val

    @staticmethod
    def _datetime_to_unix_seconds(s: pd.Series) -> np.ndarray:
        utc_s = pd.to_datetime(s, utc=True).dt.tz_convert("UTC")
        ns = utc_s.to_numpy(dtype="datetime64[ns]").astype("int64")
        return ns.astype(np.float64) / 1_000_000_000.0

    @staticmethod
    def _downsample(xs, ys, max_points):
        n = len(xs)
        if n <= max_points:
            return xs, ys
        step = max(1, n // max_points)
        idx = np.arange(0, n, step)
        if idx[-1] != n - 1:
            idx = np.append(idx, n - 1)
        return xs[idx], ys[idx]

    def _format_shift_label(self, ts):
        if ts is None or ts is pd.NaT or not hasattr(ts, "strftime"):
            return str(ts)
        base = ts.strftime("%m-%d %H:%M")
        return base + (LABEL_SHIFT_AM if 8 <= ts.hour < 20 else LABEL_SHIFT_PM)

    def _build_category_ticks(self, labels, max_ticks=12):
        if not labels:
            return []
        count = len(labels)
        step = max(1, count // max_ticks)
        ticks = [(i, labels[i]) for i in range(0, count, step)]
        if ticks[-1][0] != count - 1:
            ticks.append((count - 1, labels[-1]))
        return ticks

    def _on_mouse_moved(self, scene_pos: QPointF):
        if not self._full_series:
            return
        try:
            sp = QPoint(int(scene_pos.x()), int(scene_pos.y()))
        except Exception:
            return
        if not self.plot_widget.sceneBoundingRect().contains(sp):
            QToolTip.hideText()
            return
        vb = self.plot_widget.getPlotItem().vb
        try:
            mouse_view = vb.mapSceneToView(sp)
        except Exception:
            return
        mx = float(mouse_view.x())
        my = float(mouse_view.y())
        best_dist_px = float("inf")
        best_info = None
        best_idx = -1
        best_name = ""
        for sd in self._full_series.values():
            xs, ys = sd["xs"], sd["ys"]
            if len(xs) == 0:
                continue
            idx = int(np.searchsorted(xs, mx))
            best_local = None
            best_local_dist = float("inf")
            for ci in (idx, idx - 1):
                if 0 <= ci < len(xs):
                    px, py = float(xs[ci]), float(ys[ci])
                    try:
                        pt = vb.mapViewToScene(QPointF(px, py))
                        dist = ((pt.x() - sp.x()) ** 2 + (pt.y() - sp.y()) ** 2) ** 0.5
                    except Exception:
                        dist = abs(py - my) * 100
                    if dist < best_local_dist:
                        best_local_dist = dist
                        best_local = ci
            if best_local is not None and best_local_dist < best_dist_px:
                best_dist_px = best_local_dist
                best_info = sd
                best_idx = best_local
                best_name = sd["name"]
        if best_info is None or best_dist_px > _HOVER_TOLERANCE_PX:
            QToolTip.hideText()
            return
        x_label = best_info["x_labels"][best_idx] if best_idx < len(best_info["x_labels"]) else ""
        color = best_info["color"]
        tooltip = f"<div style='color:{color};font-weight:bold;'>{best_name}</div><div>{LABEL_TIME_CAT}: {x_label}</div><div>{LABEL_VALUE}: {float(best_info['ys'][best_idx]):.4g}</div>"
        gv: QGraphicsView = self.plot_widget
        vp_local = gv.mapFromScene(sp)
        gpos = gv.viewport().mapToGlobal(QPoint(int(vp_local.x()), int(vp_local.y())))
        QToolTip.showText(gpos, tooltip, gv.viewport())
