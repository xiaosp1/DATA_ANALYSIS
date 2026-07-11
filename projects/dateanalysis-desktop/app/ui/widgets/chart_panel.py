from __future__ import annotations

import logging
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
LABEL_DUAL_DEGRADE = "仅1条Y列，双Y轴已退化为单轴。"
LABEL_DUAL_MODE_LOG = "Y轴显示模式：双Y轴（首列左轴，其余右轴）"
LABEL_SM_MODE_LOG = "Y轴显示模式：小多图（每列独立子图，共享X轴）"

_GRANULARITY_TIME_FORMATS = {
    GRAN_RAW: "%Y-%m-%d %H:%M:%S",
    GRAN_MIN: "%Y-%m-%d %H:%M",
    GRAN_HOUR: "%Y-%m-%d %H:%M",
    GRAN_SHIFT: "%Y-%m-%d %H:%M",
    GRAN_DAY: "%Y-%m-%d",
    GRAN_WEEK: "%Y-%m-%d",
}
_MAX_PLOT_POINTS = 3000
# W10: 悬停命中容差（像素）。原值 14px 在高密度/缩放下体验较差，调到 18px。
_HOVER_TOLERANCE_PX = 18

_log = logging.getLogger(__name__)


class ChartPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        pg.setConfigOptions(antialias=True, background="w", foreground="#222222")
        self._date_axis = pg.DateAxisItem(orientation="bottom", utcOffset=0)
        self.plot_widget = pg.PlotWidget(axisItems={"bottom": self._date_axis})
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)

        # W7：小多图容器（默认隐藏）。每个子图是一个独立 PlotItem，纵向堆叠、共享 X 轴。
        self._sm_widget = pg.GraphicsLayoutWidget()
        self._sm_widget.hide()
        self._sm_plots: list[pg.PlotItem] = []
        self._sm_vlines: list[pg.InfiniteLine] = []
        self._sm_curves: list[pg.PlotDataItem] = []
        self._sm_mean_lines: list[pg.InfiniteLine] = []
        self._sm_full_series: list[dict[str, Any]] = []
        self._sm_x_is_datetime = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot_widget)
        layout.addWidget(self._sm_widget)
        self._x_is_datetime = False
        self._series_data: list[dict[str, Any]] = []
        self._full_series: dict[str, dict[str, Any]] = {}
        self._mean_labels: list[tuple[Any, float, str]] = []  # (label, preferred_y, axis: 'left'|'right')
        # W7B：记录当前 Y 轴模式（shared/normalized/dual/small_multiples），用于导出/守卫判定。
        self._current_y_mode: str | None = None
        # 双 Y 轴辅助
        self._right_vb: pg.ViewBox | None = None
        self._right_pdis: list[pg.PlotDataItem] = []
        self._right_mean_lines: list[pg.InfiniteLine] = []
        self._vb_sync_connected: bool = False

        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_widget.getViewBox().sigRangeChanged.connect(self._reposition_mean_labels)
        self.clear()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def clear(self) -> None:
        # 清理右轴（每次 clear 重建，避免旧 vb 残留）
        self._teardown_right_axis()
        self.plot_widget.clear()
        self.plot_widget.setTitle("")
        self.plot_widget.setLabel("bottom", "")
        self.plot_widget.setLabel("left", "")
        self.plot_widget.setLabel("right", "")
        try:
            self.plot_widget.plotItem.hideAxis("right")
        except Exception:
            pass
        self._date_axis.setTicks(None)
        self._x_is_datetime = False
        self._series_data = []
        self._full_series = {}
        self._mean_labels = []
        # W7B：清空调制模式（_teardown_small_multiples 会恢复到单图态）。
        self._current_y_mode = None
        # W7：清理小多图
        self._teardown_small_multiples()
        QToolTip.hideText()

    # ------------------------------------------------------------------
    # export / guard helpers (W7B)
    # ------------------------------------------------------------------
    def current_export_widget(self) -> QWidget:
        """返回当前应当被截图导出的 QWidget（小多图模式下返回 _sm_widget）。"""
        if self._current_y_mode == "small_multiples" and self._sm_widget.isVisible():
            return self._sm_widget
        return self.plot_widget

    def has_plotted_data(self) -> bool:
        """返回当前视图中是否有已绘制的曲线（用于导出/刷新守卫）。"""
        if self._current_y_mode == "small_multiples":
            return any(len(p.listDataItems()) > 0 for p in self._sm_plots)
        return bool(self.plot_widget.plotItem.listDataItems())

    def plot_multi_line(self, chart_df, x_col, series_configs, mean_map, title,
                        show_points=True, show_mean_lines=True, x_is_datetime=False,
                        granularity=GRAN_RAW, y_axis_mode: str = "shared"):
        """绘制多 Y 折线图。

        y_axis_mode:
          - "shared"     共用左 Y 轴，显示原始值
          - "normalized" 共用左 Y 轴，已在外部归一化到 [0,1]
          - "dual"       双 Y 轴：第一条曲线挂左轴，其余曲线挂右轴。
            数据不归一化（使用原始值）。若只有 1 条 Y 列，自动退化为 shared
            行为，并返回提示消息。右轴曲线的均值 TextItem 为避免与左轴
            标签错位，当前版本不绘制（均值线仍正常绘制在右轴 ViewBox 上）。
        """
        if y_axis_mode not in ("shared", "normalized", "dual", "small_multiples"):
            y_axis_mode = "shared"
        messages: list[str] = []
        self.clear()
        # W7B：记录本次绘制的 Y 轴模式，供 current_export_widget / has_plotted_data 使用。
        self._current_y_mode = y_axis_mode
        if chart_df is None or chart_df.empty or not series_configs:
            self.plot_widget.setTitle(LABEL_NO_DATA_TITLE)
            return [LABEL_NO_DATA_MSG]

        # W7：small_multiples 分派
        if y_axis_mode == "small_multiples":
            _log.info(LABEL_SM_MODE_LOG)
            sm_msgs = self._plot_small_multiples(
                chart_df, x_col, series_configs, mean_map, title,
                show_points=show_points, show_mean_lines=show_mean_lines,
                x_is_datetime=x_is_datetime, granularity=granularity,
            )
            messages.extend(sm_msgs)
            return messages

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

        # 规范化 series_configs（与原逻辑一致）
        specs: list[tuple[str, str | None, bool]] = []
        for spec in series_configs:
            if len(spec) >= 3:
                y_col, color, series_show_mean = spec[0], spec[1], bool(spec[2])
            else:
                y_col, color = spec[0], spec[1]
                series_show_mean = bool(show_mean_lines)
            specs.append((y_col, color, series_show_mean))

        # dual 模式：只有 1 条 Y 时退化
        effective_mode = y_axis_mode
        if y_axis_mode == "dual":
            # 计算有效列数（实际存在且有数据的）
            valid_count = 0
            for y_col, _c, _sm in specs:
                if y_col not in data.columns:
                    continue
                yd = pd.to_numeric(data[y_col], errors="coerce")
                if yd.notna().any():
                    valid_count += 1
            if valid_count <= 1:
                effective_mode = "shared"
                messages.append(LABEL_DUAL_DEGRADE)
                _log.info(LABEL_DUAL_DEGRADE)
            else:
                _log.info(LABEL_DUAL_MODE_LOG)

        use_dual = effective_mode == "dual"

        # 设置标题/底部轴
        self.plot_widget.setTitle(title, color="#222222", size="12pt")
        self.plot_widget.setLabel("bottom", x_col)

        right_vb: pg.ViewBox | None = None
        if use_dual:
            right_vb = self._setup_right_axis()

        vb_left = self.plot_widget.plotItem.vb
        first_valid_y_name: str | None = None

        for idx, (y_col, color, series_show_mean) in enumerate(specs):
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
            is_left = (not use_dual) or (idx == 0)
            axis_side = "left" if is_left else "right"
            target_vb = vb_left if is_left else right_vb
            self._full_series[y_col] = {
                "name": y_col,
                "color": color or "#1f77b4",
                "xs": xs_full,
                "ys": ys_full,
                "x_labels": x_labels_full,
                "viewbox": target_vb,
                "axis": axis_side,
            }

            xs_plot, ys_plot = self._downsample(xs_full, ys_full, _MAX_PLOT_POINTS)
            total_plot_points += len(xs_plot)
            qcolor = QColor(color) if color else QColor("#1f77b4")
            show_symbols = show_points and len(xs_plot) <= 800
            pen = pg.mkPen(color=qcolor, width=2)
            sym_pen = pg.mkPen(color=qcolor, width=1)
            sym_brush = qcolor

            if is_left:
                curve = self.plot_widget.plot(
                    xs_plot, ys_plot,
                    pen=pen,
                    symbol="o" if show_symbols else None,
                    symbolSize=5 if show_symbols else None,
                    symbolBrush=sym_brush,
                    symbolPen=sym_pen,
                    name=y_col,
                )
                first_valid_y_name = y_col
            else:
                pdi = pg.PlotDataItem(
                    xs_plot, ys_plot,
                    pen=pen,
                    symbol="o" if show_symbols else None,
                    symbolSize=5 if show_symbols else None,
                    symbolBrush=sym_brush,
                    symbolPen=sym_pen,
                    name=y_col,
                )
                assert right_vb is not None
                right_vb.addItem(pdi)
                self._right_pdis.append(pdi)
                # 手动加入图例（plot_widget.plot 会自动加，但 addItem 到 vb2 不会）
                try:
                    self.plot_widget.plotItem.legend.addItem(pdi, y_col)
                except Exception:
                    pass

            self._series_data.append({"name": y_col, "xs": xs_plot, "ys": ys_plot, "axis": axis_side})

            # 均值线 / 均值标签
            if show_mean_lines and series_show_mean and y_col in mean_map:
                mean_val = float(mean_map[y_col])
                mean_pen = pg.mkPen(color=qcolor, width=1.5, style=Qt.PenStyle.DashLine)
                iline = pg.InfiniteLine(pos=mean_val, angle=0, pen=mean_pen)
                target_vb.addItem(iline)
                if not is_left:
                    self._right_mean_lines.append(iline)

                # 右轴均值标签为避免与左轴标签错位，当前版本不绘制（docstring 已说明）
                if is_left:
                    label = pg.TextItem(
                        html=(
                            f"<span style='color:{qcolor.name()};background-color:rgba(255,255,255,0.92);"
                            f"padding:1px 4px;white-space:nowrap;'>{y_col} {LABEL_MEAN}: {mean_val:.2f}</span>"
                        ),
                        anchor=(1, 0.5),
                        color=qcolor,
                    )
                    label.setZValue(100)
                    self.plot_widget.addItem(label, ignoreBounds=True)
                    self._mean_labels.append((label, mean_val, axis_side))

        if total_full_points > _MAX_PLOT_POINTS:
            messages.append(LABEL_DOWNSAMPLE_FMT.format(total_full_points, total_plot_points))

        # 轴标签
        if use_dual:
            if first_valid_y_name:
                self.plot_widget.setLabel("left", first_valid_y_name)
            else:
                self.plot_widget.setLabel("left", LABEL_VALUE)
            self.plot_widget.setLabel("right", LABEL_VALUE)
            # 自动范围
            vb_left.enableAutoRange()
            if right_vb is not None:
                right_vb.enableAutoRange()
                # 初次同步几何
                self._sync_right_vb()
        else:
            self.plot_widget.setLabel("left", LABEL_VALUE)
            self.plot_widget.getViewBox().autoRange()

        self._position_mean_labels()
        return messages

    # ------------------------------------------------------------------
    # W7: Small Multiples
    # ------------------------------------------------------------------
    def _teardown_small_multiples(self) -> None:
        """销毁小多图布局，恢复单图模式。"""
        try:
            self._sm_widget.clear()
        except Exception:
            pass
        self._sm_widget.hide()
        self._sm_plots = []
        self._sm_vlines = []
        self._sm_curves = []
        self._sm_mean_lines = []
        self._sm_full_series = []
        self._sm_x_is_datetime = False
        self.plot_widget.show()

    def _setup_sm_date_axis(self, plot_item: pg.PlotItem, fmt: str | None) -> pg.DateAxisItem:
        """给小多图子图安装 DateAxisItem（仅最底行显示标签）。"""
        date_axis = pg.DateAxisItem(orientation="bottom", utcOffset=0)
        plot_item.setAxisItems({"bottom": date_axis})
        return date_axis

    def _on_sm_mouse_moved(self, scene_pos: QPointF) -> None:
        """小多图模式下，跨子图联动竖线光标 + tooltip。"""
        if not self._sm_plots:
            return
        try:
            sp = QPoint(int(scene_pos.x()), int(scene_pos.y()))
        except Exception:
            return
        # 找命中的子图
        target_vb = None
        target_idx = -1
        mx_view = None
        for i, p in enumerate(self._sm_plots):
            try:
                vb = p.vb
                if vb.sceneBoundingRect().contains(sp):
                    mv = vb.mapSceneToView(sp)
                    target_vb = vb
                    target_idx = i
                    mx_view = float(mv.x())
                    break
            except Exception:
                continue
        # 竖线联动（对所有子图）
        if target_vb is not None and mx_view is not None:
            for i, p in enumerate(self._sm_plots):
                vl = self._sm_vlines[i] if i < len(self._sm_vlines) else None
                if vl is None:
                    continue
                try:
                    vl.show()
                    vl.setPos(mx_view)
                except Exception:
                    pass
        else:
            for vl in self._sm_vlines:
                try:
                    vl.hide()
                except Exception:
                    pass
            QToolTip.hideText()
            return

        # W10: tooltip——在命中子图内找最近点
        try:
            hit = self._sm_find_nearest(scene_pos)
        except Exception:
            hit = None
        if hit is None:
            QToolTip.hideText()
            return
        plot_index, data_index, dist_px = hit
        if plot_index < 0 or dist_px > _HOVER_TOLERANCE_PX:
            QToolTip.hideText()
            return
        sd = self._sm_full_series[plot_index] if 0 <= plot_index < len(self._sm_full_series) else None
        if sd is None:
            QToolTip.hideText()
            return
        tooltip = self._format_tooltip(sd, data_index)
        try:
            gv: QGraphicsView = self._sm_widget
            vp_local = gv.mapFromScene(QPointF(scene_pos))
            gpos = gv.viewport().mapToGlobal(QPoint(int(vp_local.x()), int(vp_local.y())))
            QToolTip.showText(gpos, tooltip, gv.viewport())
        except Exception:
            pass

    def _sm_find_nearest(self, scene_pos) -> tuple[int, int, float] | None:
        """Internal helper for tests & _on_sm_mouse_moved.

        返回 ``(plot_index, data_index, dist_px)``，表示最近点所在子图、该子图曲线上
        的数据索引、以及鼠标到该渲染点的像素距离。越界/无数据返回 None。
        当前实现每个子图只绘制 1 条曲线，未来若扩展多曲线可在此处遍历。
        """
        try:
            sp = QPoint(int(scene_pos.x()), int(scene_pos.y()))
        except Exception:
            return None
        best: tuple[int, int, float] | None = None
        for pi, plot_item in enumerate(self._sm_plots):
            try:
                vb = plot_item.vb
                if not vb.sceneBoundingRect().contains(sp):
                    continue
                mv = vb.mapSceneToView(sp)
                mx = float(mv.x())
            except Exception:
                continue
            sd = self._sm_full_series[pi] if pi < len(self._sm_full_series) else None
            if sd is None:
                continue
            xs = np.asarray(sd.get("xs"))
            ys = np.asarray(sd.get("ys"))
            if xs.size == 0 or ys.size == 0:
                continue
            idx = int(np.searchsorted(xs, mx))
            best_local = None
            best_local_dist = float("inf")
            for ci in (idx, idx - 1):
                if 0 <= ci < len(xs):
                    px, py = float(xs[ci]), float(ys[ci])
                    try:
                        pt = vb.mapViewToScene(QPointF(px, py))
                        dist = float(((pt.x() - sp.x()) ** 2 + (pt.y() - sp.y()) ** 2) ** 0.5)
                    except Exception:
                        continue
                    if dist < best_local_dist:
                        best_local_dist = dist
                        best_local = ci
            if best_local is not None:
                if best is None or best_local_dist < best[2]:
                    best = (pi, best_local, best_local_dist)
        return best

    def _plot_small_multiples(self, chart_df, x_col, series_configs, mean_map, title,
                              show_points=True, show_mean_lines=True,
                              x_is_datetime=False, granularity=GRAN_RAW):
        """小多图（Small Multiples）：每个 Y 列一个子图，纵向堆叠，共享 X 轴。"""
        messages: list[str] = []
        # 先确保单图被隐藏、双轴等清理（clear() 已做了 _teardown_small_multiples）
        self.plot_widget.hide()
        self._sm_widget.show()

        data = chart_df.copy()
        x_series = data[x_col]
        if x_is_datetime and pd.api.types.is_datetime64_any_dtype(x_series):
            x_numeric = self._datetime_to_unix_seconds(x_series)
            self._sm_x_is_datetime = True
        else:
            x_numeric = np.arange(len(data), dtype=float)
            self._sm_x_is_datetime = False

        fmt = _GRANULARITY_TIME_FORMATS.get(granularity, "%Y-%m-%d %H:%M:%S") if self._sm_x_is_datetime else None

        # 规范化 series_configs
        specs: list[tuple[str, str | None, bool]] = []
        for spec in series_configs:
            if len(spec) >= 3:
                y_col, color, series_show_mean = spec[0], spec[1], bool(spec[2])
            elif len(spec) == 2:
                y_col, color = spec[0], spec[1]
                series_show_mean = bool(show_mean_lines)
            else:
                y_col = spec[0]
                color = None
                series_show_mean = bool(show_mean_lines)
            specs.append((y_col, color, series_show_mean))

        # 过滤有效列
        valid_specs: list[tuple[str, str | None, bool]] = []
        valid_xs: list[np.ndarray] = []
        valid_ys: list[np.ndarray] = []
        valid_xlabels: list[np.ndarray] = []
        valid_means: list[float] = []
        total_full_points = 0
        total_plot_points = 0

        for y_col, color, series_show_mean in specs:
            if y_col not in data.columns:
                messages.append(LABEL_Y_MISSING_FMT.format(y_col))
                continue
            y_data = pd.to_numeric(data[y_col], errors="coerce")
            mask = y_data.notna().to_numpy()
            xs_full = x_numeric[mask]
            ys_full = y_data[mask].to_numpy(dtype=float)
            if len(xs_full) == 0:
                messages.append(LABEL_Y_NO_VALID_FMT.format(y_col))
                continue
            if self._sm_x_is_datetime:
                ts_subset = x_series[mask]
                if granularity == GRAN_SHIFT:
                    x_labels_full = np.array([self._format_shift_label(t) for t in ts_subset.tolist()], dtype=object)
                else:
                    x_labels_full = np.array(ts_subset.dt.strftime(fmt).tolist(), dtype=object)
            else:
                all_labels = np.array([str(v) for v in x_series.tolist()], dtype=object)
                x_labels_full = all_labels[np.where(mask)[0]]
            valid_specs.append((y_col, color, series_show_mean))
            valid_xs.append(xs_full)
            valid_ys.append(ys_full)
            valid_xlabels.append(x_labels_full)
            mv = mean_map.get(y_col)
            try:
                valid_means.append(float(mv) if mv is not None else float(np.nanmean(ys_full)))
            except Exception:
                valid_means.append(float("nan"))
            total_full_points += len(xs_full)

        n = len(valid_specs)
        if n == 0:
            self._sm_widget.addLabel(LABEL_NO_DATA_TITLE)
            messages.append(LABEL_NO_DATA_MSG)
            return messages

        self._sm_plots = []
        self._sm_vlines = []
        self._sm_curves = []
        self._sm_mean_lines = []
        self._sm_full_series = []

        bottom_date_axis: pg.DateAxisItem | None = None
        for i in range(n):
            y_col, color, series_show_mean = valid_specs[i]
            qcolor = QColor(color) if color else QColor("#1f77b4")

            if i == 0:
                plot_item: pg.PlotItem = self._sm_widget.addPlot(row=i, col=0)
            else:
                plot_item = self._sm_widget.addPlot(row=i, col=0)

            # 日期轴：所有子图都装 DateAxisItem（setXLink 后共用范围），非底行隐藏刻度标签
            if self._sm_x_is_datetime:
                date_axis = self._setup_sm_date_axis(plot_item, fmt)
                if i == n - 1:
                    bottom_date_axis = date_axis
            else:
                # 类别轴：只在最底行设置 ticks
                labels = [str(v) for v in x_series.tolist()]
                if i == n - 1:
                    plot_item.getAxis("bottom").setTicks([self._build_category_ticks(labels, max_ticks=12)])
                else:
                    plot_item.getAxis("bottom").setTicks([])

            # 隐藏非底行的 X 轴刻度标签
            if i != n - 1:
                plot_item.hideAxis("bottom")

            plot_item.showGrid(x=True, y=True, alpha=0.2)
            plot_item.setMouseEnabled(x=True, y=True)
            plot_item.setMenuEnabled(False)

            # 子标题（列名，带颜色）
            title_html = (
                f"<span style='color:{qcolor.name()};font-weight:bold;font-size:11pt;'>{y_col}</span>"
            )
            plot_item.setTitle(title_html)
            plot_item.setLabel("left", LABEL_VALUE)

            # 共享 X 轴：link 到第一个子图
            if i > 0:
                plot_item.setXLink(self._sm_plots[0])

            xs_full = valid_xs[i]
            ys_full = valid_ys[i]
            x_labels_full = valid_xlabels[i]
            self._sm_full_series.append({
                "name": y_col,
                "xs": xs_full,
                "ys": ys_full,
                "color": qcolor.name(),
                "x_labels": x_labels_full,
            })

            xs_plot, ys_plot = self._downsample(xs_full, ys_full, _MAX_PLOT_POINTS)
            total_plot_points += len(xs_plot)

            show_symbols = show_points and len(xs_plot) <= 800
            pen = pg.mkPen(color=qcolor, width=2)
            sym_pen = pg.mkPen(color=qcolor, width=1)
            sym_brush = qcolor
            curve = plot_item.plot(
                xs_plot, ys_plot,
                pen=pen,
                symbol="o" if show_symbols else None,
                symbolSize=5 if show_symbols else None,
                symbolBrush=sym_brush,
                symbolPen=sym_pen,
                name=y_col,
            )
            self._sm_curves.append(curve)

            # 均值虚线（不加文字标签，避免拥挤）
            mean_val = valid_means[i]
            if show_mean_lines and series_show_mean and np.isfinite(mean_val):
                mean_pen = pg.mkPen(color=qcolor, width=1.5, style=Qt.PenStyle.DashLine)
                iline = pg.InfiniteLine(pos=mean_val, angle=0, pen=mean_pen)
                plot_item.addItem(iline)
                self._sm_mean_lines.append(iline)
            else:
                self._sm_mean_lines.append(None)  # type: ignore

            # 共享竖线光标
            vline_pen = pg.mkPen(color="#555555", width=1, style=Qt.PenStyle.DashLine)
            vline = pg.InfiniteLine(pos=0, angle=90, pen=vline_pen, movable=False)
            vline.hide()
            plot_item.addItem(vline)
            self._sm_vlines.append(vline)

            # 自动 Y 范围
            plot_item.enableAutoRange(axis=pg.ViewBox.YAxis)

            self._sm_plots.append(plot_item)

        # 最底行显示 X 轴标签
        if self._sm_plots:
            bottom = self._sm_plots[-1]
            if self._sm_x_is_datetime:
                bottom.setLabel("bottom", x_col)
            else:
                bottom.setLabel("bottom", x_col)

        # 鼠标联动：所有子图 vb 的 sigMouseMoved / scene 移动都连到统一处理
        # GraphicsLayoutWidget 的 scene 与 plot_widget 共享 QGraphicsScene？实际它们是各自的 QGraphicsView。
        # 我们在 _sm_widget 的 viewport 上安装事件过滤器最简单——这里直接连接每个子图 vb 的 scene sigMouseMoved。
        try:
            self._sm_scene = self._sm_widget.scene()
            # 避免重复连接：用一个标记
            if not getattr(self, "_sm_mouse_connected", False):
                self._sm_scene.sigMouseMoved.connect(self._on_sm_mouse_moved)
                self._sm_mouse_connected = True
        except Exception:
            pass

        if total_full_points > _MAX_PLOT_POINTS:
            messages.append(LABEL_DOWNSAMPLE_FMT.format(total_full_points, total_plot_points))
        return messages

    # ------------------------------------------------------------------
    # dual Y-axis helpers
    # ------------------------------------------------------------------
    def _setup_right_axis(self) -> pg.ViewBox:
        """创建并绑定右侧 ViewBox；与主 vb 同步 X 轴与几何。"""
        plot_item = self.plot_widget.plotItem
        plot_item.showAxis("right")
        vb1 = plot_item.vb
        vb2 = pg.ViewBox()
        plot_item.scene().addItem(vb2)
        plot_item.getAxis("right").linkToView(vb2)
        vb2.setXLink(vb1)
        # 让 vb2 跟随主 vb 的鼠标交互与背景色保持一致
        vb2.setMouseEnabled(x=True, y=True)
        vb2.setMenuEnabled(False)
        self._right_vb = vb2
        self._right_pdis = []
        self._right_mean_lines = []
        if not self._vb_sync_connected:
            vb1.sigResized.connect(self._sync_right_vb)
            vb1.sigRangeChanged.connect(self._sync_right_vb)
            self._vb_sync_connected = True
        return vb2

    def _teardown_right_axis(self) -> None:
        """销毁右轴 ViewBox，避免 scene 中残留。"""
        plot_item = self.plot_widget.plotItem
        vb2 = getattr(self, "_right_vb", None)
        if vb2 is None:
            self._right_vb = None
            self._right_pdis = []
            self._right_mean_lines = []
            return
        try:
            # 断开同步信号
            vb1 = plot_item.vb
            try:
                vb1.sigResized.disconnect(self._sync_right_vb)
            except Exception:
                pass
            try:
                vb1.sigRangeChanged.disconnect(self._sync_right_vb)
            except Exception:
                pass
            self._vb_sync_connected = False
            # 移除右轴上的 PlotDataItem
            for pdi in list(self._right_pdis):
                try:
                    vb2.removeItem(pdi)
                except Exception:
                    pass
                try:
                    plot_item.legend.removeItem(pdi)
                except Exception:
                    pass
            for il in list(self._right_mean_lines):
                try:
                    vb2.removeItem(il)
                except Exception:
                    pass
            # 从 scene 移除 vb2
            try:
                scene = plot_item.scene()
                if scene is not None:
                    scene.removeItem(vb2)
            except Exception:
                pass
            # 解除右轴 link
            try:
                plot_item.hideAxis("right")
            except Exception:
                pass
        finally:
            self._right_vb = None
            self._right_pdis = []
            self._right_mean_lines = []

    def _sync_right_vb(self, *_args) -> None:
        vb2 = self._right_vb
        if vb2 is None:
            return
        vb1 = self.plot_widget.plotItem.vb
        try:
            vb2.setGeometry(vb1.sceneBoundingRect())
            vb2.linkedViewChanged(vb1, vb2.XAxis)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # mean labels
    # ------------------------------------------------------------------
    def _reposition_mean_labels(self, *_):
        self._position_mean_labels()

    def _position_mean_labels(self):
        """将均值标签放置到左轴 viewRange 最右侧。

        右轴均值标签为避免错位当前版本不绘制，故这里只处理 axis=='left' 的标签。
        """
        if not self._mean_labels:
            return
        vb_left = self.plot_widget.getViewBox()
        try:
            x_left, x_right = vb_left.viewRange()[0]
            y_bottom, y_top = vb_left.viewRange()[1]
        except Exception:
            return
        span = max(y_top - y_bottom, 1e-9)
        min_gap = span * 0.022
        used: list[float] = []
        for label, preferred_y, axis_side in self._mean_labels:
            if axis_side != "left":
                continue
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

    # ------------------------------------------------------------------
    # conversions / downsampling
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # hover tooltip (supports dual axis / small multiples)
    # ------------------------------------------------------------------
    def _format_tooltip(self, sd: dict[str, Any], idx: int) -> str:
        """W10: 可单测的 tooltip 文本构造器。输入 series dict 和数据点索引。"""
        name = str(sd.get("name", ""))
        color = sd.get("color", "#1f77b4") or "#1f77b4"
        xs = sd.get("xs")
        ys = sd.get("ys")
        if xs is None or ys is None or idx < 0 or idx >= len(ys):
            return ""
        y_val = float(ys[idx])
        x_labels = sd.get("x_labels")
        if x_labels is not None and idx < len(x_labels):
            x_label = str(x_labels[idx])
        else:
            x_label = f"{float(xs[idx]):.4g}"
        return (
            f"<div style='color:{color};font-weight:bold;'>{name}</div>"
            f"<div>{LABEL_TIME_CAT}: {x_label}</div>"
            f"<div>{LABEL_VALUE}: {y_val:.4g}</div>"
        )

    def _nearest_for_vb(self, vb, sp: QPoint) -> tuple[dict[str, Any] | None, int, float]:
        """W10: 抽出来便于复用/单测——在给定 ViewBox 里找离 scene 点 sp 最近的全量数据点。

        返回 ``(series_dict, data_index, dist_px)``；未命中返回 ``(None, -1, inf)``。
        注意：查找基于 ``_full_series`` 中 viewbox==vb 的序列，始终使用
        全量 xs/ys（而非降采样后的 xs_plot/ys_plot），确保 tooltip 显示真实值。
        """
        try:
            mouse_view = vb.mapSceneToView(sp)
        except Exception:
            return None, -1, float("inf")
        mx = float(mouse_view.x())
        best_dist_px = float("inf")
        best_info: dict[str, Any] | None = None
        best_idx = -1
        for sd in self._full_series.values():
            if sd.get("viewbox") is not vb:
                continue
            xs = np.asarray(sd["xs"])
            ys = np.asarray(sd["ys"])
            if xs.size == 0:
                continue
            # xs 已按时间排序且单调递增；searchsorted 定位插入点，检查前后两点
            idx = int(np.searchsorted(xs, mx))
            best_local = None
            best_local_dist = float("inf")
            for ci in (idx, idx - 1):
                if 0 <= ci < len(xs):
                    px, py = float(xs[ci]), float(ys[ci])
                    try:
                        pt = vb.mapViewToScene(QPointF(px, py))
                        dist = float(((pt.x() - sp.x()) ** 2 + (pt.y() - sp.y()) ** 2) ** 0.5)
                    except Exception:
                        continue
                    if dist < best_local_dist:
                        best_local_dist = dist
                        best_local = ci
            if best_local is not None and best_local_dist < best_dist_px:
                best_dist_px = best_local_dist
                best_info = sd
                best_idx = best_local
        return best_info, best_idx, best_dist_px

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

        vb_left = self.plot_widget.getPlotItem().vb
        vb_right = self._right_vb
        right_visible = (
            vb_right is not None
            and self.plot_widget.plotItem.getAxis("right") is not None
            and self.plot_widget.plotItem.getAxis("right").isVisible()
        )

        best_info, best_idx, best_dist_px = self._nearest_for_vb(vb_left, sp)
        if right_visible and vb_right is not None:
            r_info, r_idx, r_dist = self._nearest_for_vb(vb_right, sp)
            if r_info is not None and r_dist < best_dist_px:
                best_info, best_idx, best_dist_px = r_info, r_idx, r_dist

        if best_info is None or best_dist_px > _HOVER_TOLERANCE_PX:
            QToolTip.hideText()
            return
        tooltip = self._format_tooltip(best_info, best_idx)
        gv: QGraphicsView = self.plot_widget
        vp_local = gv.mapFromScene(sp)
        gpos = gv.viewport().mapToGlobal(QPoint(int(vp_local.x()), int(vp_local.y())))
        QToolTip.showText(gpos, tooltip, gv.viewport())
