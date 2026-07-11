from __future__ import annotations

import time
import traceback
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QSettings, Qt, QThreadPool
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor
from PySide6.QtWidgets import (
    QDockWidget,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QButtonGroup,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStatusBar,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.services.app_logger import AppLogger
from app.services.data_processing import apply_rules, scale_datasets_by_category
from app.services.dataset_manager import CATEGORY_LABELS, DatasetManager
from app.services.export_service import ExportError, export_plot_widget_to_png, export_stats_to_csv, export_stats_to_excel
from app.services.file_loader import FileLoadError, load_file
from app.services.stats_service import calculate_batch_stats, stats_to_dataframe
from app.services.time_aggregation import aggregate_by_time
from app.services.worker import Worker
from app.ui.widgets.chart_config_panel import ChartConfigPanel
from app.ui.widgets.chart_options_panel import ChartOptionsPanel
from app.ui.widgets.chart_panel import ChartPanel
from app.ui.widgets.data_table_panel import TablePanel
from app.ui.widgets.multi_table_panel import MultiTablePanel
from app.ui.widgets.dataset_panel import DatasetPanel
from app.ui.widgets.processing_panel import ProcessingPanel
from app.utils.timer_utils import format_duration, timed
from app.services.descriptive_service import (
    batch_descriptive_stats, boxplot_stats, correlation_matrix,
    descriptive_to_dataframe, missing_summary, quantile_table,
)
from app.ui.widgets.descriptive_charts_panel import DescriptiveChartsPanel
from app.ui.widgets.descriptive_panel import DescriptivePanel
from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel
from app.services.process_analysis import build_analysis_report, infer_columns
from app.services.ai_client import AIClient, AIClientError
from app.services.ai_prompt import build_insight_prompt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("本地数据分析与图表展示软件")
        self.resize(1400, 900)
        self._manager = DatasetManager()
        self.app_logger = AppLogger(Path(__file__).resolve().parents[2] / "logs")
        self._stats_df: pd.DataFrame | None = None
        self._desc_tables: dict[str, pd.DataFrame] = {}
        self._column_cache: dict[str, dict[str, set]] = {}
        self._busy = False
        self._progress: QProgressDialog | None = None
        self._threadpool = QThreadPool.globalInstance()
        self._settings = QSettings("DateAnalysis", "DateAnalysis")
        self._last_import_dir = self._settings.value("last_import_dir", str(Path.home()), type=str)
        self._last_export_dir = self._settings.value("last_export_dir", str(Path.home()), type=str)
        self._category_factors: dict[str, float] = {
            "head": float(self._settings.value("head_pixel_factor", 1.0, type=float) or 1.0),
            "tail": float(self._settings.value("tail_pixel_factor", 1.0, type=float) or 1.0),
        }
        self._category_exclude_cols: dict[str, list[str]] = {
            "head": self._parse_exclude_columns(str(self._settings.value("head_exclude_columns", "时间", type=str) or "时间")),
            "tail": self._parse_exclude_columns(str(self._settings.value("tail_exclude_columns", "未脱模-s,指数-s", type=str) or "未脱模-s,指数-s")),
        }
        self._manager.add_listener(self._on_datasets_changed)
        self._install_excepthook()
        self._build_ui()
        self._apply_initial_state()
        for cat, fac in self._category_factors.items():
            self.processing_panel.set_category_factor(cat, float(fac))
        self._refresh_scale_hint()

    def _build_ui(self):
        toolbar = QToolBar("主工具栏"); toolbar.setMovable(False); self.addToolBar(toolbar)
        self.import_button = QPushButton("导入文件")
        self.import_folder_button = QPushButton("导入文件夹")
        self.import_head_button = QPushButton("导入机头文件")
        self.import_tail_button = QPushButton("导入机尾文件")
        self.import_head_folder_button = QPushButton("导入机头文件夹")
        self.import_tail_folder_button = QPushButton("导入机尾文件夹")
        self.export_stats_button = QPushButton("导出统计结果")
        self.export_chart_button = QPushButton("导出图表图片")
        self.clear_button = QPushButton("清空全部")
        self.about_button = QPushButton("关于")
        for b in (self.import_button, self.import_folder_button): toolbar.addWidget(b)
        toolbar.addSeparator()
        for b in (self.import_head_button, self.import_tail_button, self.import_head_folder_button, self.import_tail_folder_button): toolbar.addWidget(b)
        toolbar.addSeparator()
        self.toggle_left_dock_btn = QPushButton("侧栏"); self.toggle_left_dock_btn.setCheckable(True)
        self.toggle_right_dock_btn = QPushButton("信息面板"); self.toggle_right_dock_btn.setCheckable(True)
        toolbar.addWidget(self.toggle_left_dock_btn); toolbar.addWidget(self.toggle_right_dock_btn)
        toolbar.addSeparator()
        toolbar.addWidget(self.export_stats_button); toolbar.addWidget(self.export_chart_button)
        self.open_log_dir_button = QPushButton("打开日志目录"); toolbar.addWidget(self.open_log_dir_button)
        toolbar.addWidget(self.clear_button); toolbar.addWidget(self.about_button)

        left_scroll = QScrollArea(); left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setMinimumWidth(0)
        left_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left = QWidget(); left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        left_layout = QVBoxLayout(left); left_layout.setSpacing(8)
        self.dataset_panel = DatasetPanel(); self.dataset_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.processing_panel = ProcessingPanel(); self.processing_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.mode_group = QGroupBox("分析模式")
        mode_layout = QVBoxLayout(self.mode_group)
        mode_row = QHBoxLayout()
        self.mode_trend_button = QPushButton("折线趋势"); self.mode_desc_button = QPushButton("描述统计"); self.mode_monitor_button = QPushButton("时序监控")
        for b in (self.mode_trend_button, self.mode_desc_button, self.mode_monitor_button): b.setCheckable(True)
        self.mode_trend_button.setChecked(True)
        for b in (self.mode_trend_button, self.mode_desc_button, self.mode_monitor_button): mode_row.addWidget(b)
        mode_layout.addLayout(mode_row)
        self._mode_button_group = QButtonGroup(self)
        self._mode_button_group.addButton(self.mode_trend_button, 0)
        self._mode_button_group.addButton(self.mode_desc_button, 1)
        self._mode_button_group.addButton(self.mode_monitor_button, 2)
        self.mode_stack = QStackedWidget()

        trend_page = QWidget(); trend_layout = QVBoxLayout(trend_page); trend_layout.setContentsMargins(0,0,0,0)
        self.info_group = QGroupBox("当前数据集与分析列"); self.info_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info_layout = QVBoxLayout(self.info_group)
        self.dataset_info_label = QLabel("当前未加载数据"); self.dataset_info_label.setWordWrap(True)
        self.analysis_list = QListWidget(); self.analysis_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        info_layout.addWidget(self.dataset_info_label); info_layout.addWidget(QLabel("选择统计列：")); info_layout.addWidget(self.analysis_list)
        self.chart_options_panel = ChartOptionsPanel(); self.chart_options_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.chart_config_panel = ChartConfigPanel(); self.chart_config_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        trend_layout.addWidget(self.info_group); trend_layout.addWidget(self.chart_options_panel); trend_layout.addWidget(self.chart_config_panel); trend_layout.addStretch(1)
        self.mode_stack.addWidget(trend_page)

        self.descriptive_panel = DescriptivePanel(); self.mode_stack.addWidget(self.descriptive_panel)
        monitor_page = QWidget(); monitor_layout = QVBoxLayout(monitor_page); monitor_layout.setContentsMargins(8,8,8,8)
        self._monitor_placeholder = QLabel("时序监控面板开发中...（控制图 I-MR / X-bar R / EWMA / Cpk / ACF）")
        self._monitor_placeholder.setWordWrap(True); self._monitor_placeholder.setStyleSheet("color:#888; padding:16px;")
        monitor_layout.addWidget(self._monitor_placeholder); monitor_layout.addStretch(1)
        self.mode_stack.addWidget(monitor_page)
        mode_layout.addWidget(self.mode_stack)
        left_layout.addWidget(self.dataset_panel); left_layout.addWidget(self.processing_panel)
        left_layout.addWidget(self.mode_group); left_layout.addStretch(1)
        left_scroll.setWidget(left)

        self.left_dock = QDockWidget("数据与配置", self); self.left_dock.setObjectName("LeftDataConfigDock"); self.left_dock.setWidget(left_scroll)
        self.left_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.left_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

        central = QWidget(); self.setCentralWidget(central)
        central_layout = QVBoxLayout(central); central_layout.setContentsMargins(0,0,0,0); central_layout.setSpacing(0)
        self.chart_tabs = QTabWidget()
        self.chart_panel = ChartPanel(); self.chart_tabs.addTab(self.chart_panel, "折线趋势")
        self.desc_charts_panel = DescriptiveChartsPanel(); self.chart_tabs.addTab(self.desc_charts_panel, "描述统计")
        self._monitor_chart_placeholder = QLabel("时序监控图表区（控制图 / EWMA / 滑动窗口 / ACF）将在此展示")
        self._monitor_chart_placeholder.setWordWrap(True); self._monitor_chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter); self._monitor_chart_placeholder.setStyleSheet("color:#888; padding:24px;")
        self.chart_tabs.addTab(self._monitor_chart_placeholder, "时序监控")
        central_layout.addWidget(self.chart_tabs, stretch=1)
        self.preview_label = QLabel("数据表预览前1000行；统计与绘图基于当前激活数据集的全量有效数据。大文件自动降采样绘图以保证流畅。")
        self.preview_label.setStyleSheet("color:#666; padding:4px 6px;"); central_layout.addWidget(self.preview_label)

        self.data_panel = TablePanel()
        self.stats_panel = MultiTablePanel()
        self.stats_panel.set_table("综合统计", pd.DataFrame(columns=["列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
        self.log_panel = QPlainTextEdit(); self.log_panel.setReadOnly(True); self.log_panel.setMinimumWidth(0)
        self.log_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.process_analysis_panel = ProcessAnalysisPanel()
        self.info_tabs = QTabWidget(); self.info_tabs.setDocumentMode(True); self.info_tabs.setUsesScrollButtons(True); self.info_tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.info_tabs.addTab(self.data_panel, "当前数据")
        self.info_tabs.addTab(self.stats_panel, "统计结果")
        self.info_tabs.addTab(self.log_panel, "日志提示")
        self.info_tabs.addTab(self.process_analysis_panel, "工艺分析")
        self.tabs = self.info_tabs

        self.right_dock = QDockWidget("信息面板", self); self.right_dock.setObjectName("RightInfoDock"); self.right_dock.setWidget(self.info_tabs)
        self.right_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.right_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)
        self.left_dock.setMinimumWidth(340); self.right_dock.setMinimumWidth(400); self._apply_dock_size_policies()
        self.process_analysis_panel.ai_insight_requested.connect(self._on_ai_insight_requested)
        self.resizeDocks([self.left_dock, self.right_dock], [400, 520], Qt.Orientation.Horizontal)

        self.toggle_left_dock_btn.toggled.connect(self._on_toggle_left_dock)
        self.toggle_right_dock_btn.toggled.connect(self._on_toggle_right_dock)
        self.left_dock.visibilityChanged.connect(self._sync_left_dock_btn)
        self.right_dock.visibilityChanged.connect(self._sync_right_dock_btn)
        self.toggle_left_dock_btn.setChecked(True); self.toggle_right_dock_btn.setChecked(True)
        self.setStatusBar(QStatusBar()); self.statusBar().showMessage("就绪")

        self.import_button.clicked.connect(self._import_files); self.import_folder_button.clicked.connect(self._import_folder)
        self.import_head_button.clicked.connect(lambda: self._import_category(mode="files", category="head"))
        self.import_tail_button.clicked.connect(lambda: self._import_category(mode="files", category="tail"))
        self.import_head_folder_button.clicked.connect(lambda: self._import_category(mode="folder", category="head"))
        self.import_tail_folder_button.clicked.connect(lambda: self._import_category(mode="folder", category="tail"))
        self.export_stats_button.clicked.connect(self._export_stats); self.export_chart_button.clicked.connect(self._export_chart_image)
        self.open_log_dir_button.clicked.connect(self._open_log_directory); self.clear_button.clicked.connect(self._clear_all); self.about_button.clicked.connect(self._show_about)
        self.dataset_panel.import_requested.connect(self._import_files); self.dataset_panel.activate_requested.connect(self._activate_dataset)
        self.dataset_panel.delete_requested.connect(self._delete_dataset); self.dataset_panel.export_requested.connect(self._export_dataset)
        self.dataset_panel.merge_requested.connect(self._merge_datasets); self.dataset_panel.merge_head_requested.connect(lambda: self._merge_by_category("head"))
        self.dataset_panel.merge_tail_requested.connect(lambda: self._merge_by_category("tail")); self.dataset_panel.merge_cross_requested.connect(self._merge_cross_category)
        self.processing_panel.apply_requested.connect(self._apply_processing); self.processing_panel.scale_category_requested.connect(self._scale_category_datasets)
        self.processing_panel.refresh_scale_hint_requested.connect(self._refresh_scale_hint)
        self.chart_config_panel.analysis_requested.connect(self._run_analysis); self.chart_config_panel.chart_requested.connect(self._run_chart_only)
        self.chart_config_panel.reset_requested.connect(lambda: self.log("已重置图表配置。"))
        self.chart_options_panel.granularity_combo.currentIndexChanged.connect(lambda _: self._refresh_chart_if_any())
        self.chart_options_panel.y_mode_changed.connect(lambda _m: self._refresh_chart_if_any())
        self.chart_config_panel.show_points_check.toggled.connect(lambda _: self._refresh_chart_if_any())
        self.chart_config_panel.show_mean_check.toggled.connect(lambda _: self._refresh_chart_if_any())
        self.chart_config_panel.series_option_changed.connect(self._refresh_chart_if_any)
        self.descriptive_panel.run_requested.connect(self._run_descriptive_analysis)
        self.process_analysis_panel.analysis_requested.connect(self._on_process_analysis_requested)
        self.process_analysis_panel.export_requested.connect(self._on_process_analysis_export)
        self._mode_button_group.idClicked.connect(self._on_mode_changed)
        self._restore_dock_state()


    def _apply_dock_size_policies(self) -> None:
        from PySide6.QtWidgets import QAbstractItemView, QTableView
        exp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for tv in self.info_tabs.findChildren(QTableView):
            try:
                tv.setMinimumWidth(0); tv.setSizePolicy(exp)
                tv.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
                tv.horizontalHeader().setStretchLastSection(True)
            except Exception:
                pass
        try:
            self.log_panel.setMinimumWidth(0)
        except Exception:
            pass
        self.info_tabs.setMinimumWidth(0); self.info_tabs.setSizePolicy(exp)

    def closeEvent(self, event):
        try: self._save_dock_state()
        except Exception: pass
        super().closeEvent(event)

    def _on_toggle_left_dock(self, checked: bool) -> None:
        if self.left_dock.isVisible() != bool(checked): self.left_dock.setVisible(bool(checked))

    def _on_toggle_right_dock(self, checked: bool) -> None:
        if self.right_dock.isVisible() != bool(checked): self.right_dock.setVisible(bool(checked))

    def _sync_left_dock_btn(self, visible: bool) -> None:
        self.toggle_left_dock_btn.blockSignals(True); self.toggle_left_dock_btn.setChecked(bool(visible)); self.toggle_left_dock_btn.blockSignals(False)

    def _sync_right_dock_btn(self, visible: bool) -> None:
        self.toggle_right_dock_btn.blockSignals(True); self.toggle_right_dock_btn.setChecked(bool(visible)); self.toggle_right_dock_btn.blockSignals(False)

    def _save_dock_state(self) -> None:
        try:
            self._settings.setValue("window/geometry", self.saveGeometry()); self._settings.setValue("window/state", self.saveState())
            self._settings.setValue("dock/left_visible", self.left_dock.isVisible()); self._settings.setValue("dock/right_visible", self.right_dock.isVisible())
        except Exception: pass

    def _restore_dock_state(self) -> None:
        try:
            geom = self._settings.value("window/geometry", None); state = self._settings.value("window/state", None)
            if geom is not None and state is not None: self.restoreGeometry(geom); self.restoreState(state)
            lv = self._settings.value("dock/left_visible", True, type=bool); rv = self._settings.value("dock/right_visible", True, type=bool)
            if self._settings.contains("dock/left_visible"): self.left_dock.setVisible(bool(lv))
            if self._settings.contains("dock/right_visible"): self.right_dock.setVisible(bool(rv))
        except Exception: pass
        finally:
            self.left_dock.setMinimumWidth(340); self.right_dock.setMinimumWidth(400)
            if self.right_dock.width() < 400: self.resizeDocks([self.right_dock], [520], Qt.Orientation.Horizontal)
            if self.left_dock.width() < 340: self.resizeDocks([self.left_dock], [400], Qt.Orientation.Horizontal)

    def _on_mode_changed(self, mode_id: int) -> None:
        self.mode_stack.setCurrentIndex(mode_id); self.chart_tabs.setCurrentIndex(mode_id)
        if mode_id == 0: self.log("已切换到：折线趋势模式")
        elif mode_id == 1: self.log("已切换到：描述统计模式")
        else: self.log("已切换到：时序监控模式")

    def _set_busy(self, busy: bool, label: str = "处理中...") -> None:
        self._busy = busy
        if busy:
            if self._progress is None:
                self._progress = QProgressDialog(label, "取消", 0, 0, self); self._progress.setWindowTitle("请稍候")
                self._progress.setWindowModality(Qt.WindowModality.WindowModal); self._progress.setMinimumDuration(300)
                self._progress.setCancelButton(None); self._progress.setAutoClose(True); self._progress.setAutoReset(True)
            else:
                self._progress.setLabelText(label)
            self._progress.setValue(0); self._progress.show(); self.statusBar().showMessage(label)
        else:
            if self._progress is not None: self._progress.close(); self._progress = None
            self.statusBar().showMessage("就绪")

    def _progress_cb(self, pct: int, msg: str = "") -> None:
        if self._progress is None: return
        self._progress.setValue(max(0, min(100, int(pct))))
        if msg:
            try: self._progress.setLabelText(msg)
            except RuntimeError: self._progress = None; return
            self.statusBar().showMessage(msg)

    def _cache_columns_for(self, item) -> dict[str, set]:
        if item is None: return {"numeric": set(), "datetime": set()}
        cache = self._column_cache.get(item.dataset_id)
        if cache is not None: return cache
        df = item.df; numeric = set(); dt_cols = set()
        for c in df.columns:
            cname = str(c); s = df[c]
            if pd.api.types.is_numeric_dtype(s): numeric.add(cname)
            if pd.api.types.is_datetime64_any_dtype(s): dt_cols.add(cname)
            else:
                non_null = s.dropna()
                name_hint = any(k in cname.lower() for k in ["date","time","日期","时间"])
                if not non_null.empty and (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)):
                    sample = non_null.head(min(200,len(non_null)))
                    with warnings.catch_warnings(): warnings.simplefilter("ignore"); converted = pd.to_datetime(sample, errors="coerce")
                    ratio = converted.notna().sum()/max(1,len(sample))
                    if ratio >= 0.8 or (name_hint and ratio >= 0.6): dt_cols.add(cname)
        cache = {"numeric": numeric, "datetime": dt_cols}; self._column_cache[item.dataset_id] = cache; return cache

    def _invalidate_cache(self, dataset_id: str | None = None) -> None:
        if dataset_id is None: self._column_cache.clear()
        else: self._column_cache.pop(dataset_id, None)

    def _apply_initial_state(self):
        self.data_panel.set_dataframe(pd.DataFrame({"提示": ["请先导入CSV/XLSX文件"]}))
        self.stats_panel.clear_tables()
        self.stats_panel.set_table("综合统计", pd.DataFrame(columns=["列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
        self.chart_panel.clear(); self._stats_df = None; self._refresh_dataset_ui()
        self.log("欢迎使用。支持多文件导入、临时储存区、条件数据处理、时间粒度聚合。耗时记录会输出到日志。")

    def _on_datasets_changed(self):
        self._refresh_dataset_ui(); self._refresh_scale_hint()

    def _refresh_dataset_ui(self):
        items = self._manager.items(); active = self._manager.active_item()
        self.dataset_panel.refresh(items, self._manager.active_id())
        if active is None:
            self.dataset_info_label.setText("当前未加载数据"); self.analysis_list.clear()
            self.chart_config_panel.set_columns([], []); self.processing_panel.set_columns([], [])
            self._refresh_process_analysis_panel(); return
        df = active.df; cache = self._cache_columns_for(active)
        numeric_cols = sorted(cache["numeric"], key=lambda c: list(df.columns).index(c) if c in df.columns else 999)
        self.dataset_info_label.setText(f"当前数据集：[{self._kind(active.kind)}] {active.name}\n行数：{len(df)}，列数：{len(df.columns)}")
        self.analysis_list.clear()
        for col in df.columns: self.analysis_list.addItem(QListWidgetItem(str(col)))
        self.chart_config_panel.set_columns([str(c) for c in df.columns], numeric_cols)
        self.processing_panel.set_columns([str(c) for c in df.columns], numeric_cols)
        self.descriptive_panel.set_columns([str(c) for c in df.columns], numeric_cols)
        self._refresh_process_analysis_panel()

    def _kind(self, kind):
        return {"original":"原始","processed":"临时","merged":"合并"}.get(kind, kind)


    _SUPPORTED_TABLE_EXTS = {".csv", ".xlsx", ".xls"}

    def _import_folder(self):
        start_dir = self._last_import_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹（递归导入所有表格）", start_dir)
        if not folder: return
        self._last_import_dir = folder; self._settings.setValue("last_import_dir", self._last_import_dir)
        folder_path = Path(folder)
        paths = sorted(str(pp) for pp in folder_path.rglob("*") if pp.is_file() and pp.suffix.lower() in self._SUPPORTED_TABLE_EXTS)
        if not paths:
            QMessageBox.information(self, "提示", f"文件夹“{folder_path.name}”及子目录中未找到 csv/xlsx/xls 文件。"); return
        self.log(f"开始导入文件夹：{folder_path}，共发现 {len(paths)} 个表格文件。")
        self._run_background(label=f"正在导入文件夹（0/{len(paths)}）...", fn=self._worker_import, fn_args=(paths,), on_success=self._on_import_done, on_error=self._on_import_error)

    def _import_files(self):
        start_dir = self._last_import_dir or str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(self, "选择表格文件", start_dir, "表格文件 (*.csv *.xlsx *.xls);;所有文件 (*.*)")
        if not paths: return
        self._last_import_dir = str(Path(paths[0]).parent); self._settings.setValue("last_import_dir", self._last_import_dir)
        self._run_background(label="正在导入文件...", fn=self._worker_import, fn_args=(paths,), on_success=self._on_import_done, on_error=self._on_import_error)

    def _worker_import(self, paths, report_progress=None):
        imported = []; errors = []; total = len(paths)
        for i, pth in enumerate(paths, 1):
            name = Path(pth).name
            if report_progress: report_progress(int(i/total*100), f"读取中 ({i}/{total})：{name}")
            try: imported.append(load_file(pth, has_header=True))
            except FileLoadError as exc: errors.append((name, str(exc)))
            except Exception as exc: errors.append((name, f"未知错误：{exc}"))
        return {"imported": imported, "errors": errors}

    def _on_import_done(self, result):
        import time as _t
        imported = result["imported"]; errors = result["errors"]; t0 = _t.perf_counter()
        for dataset in imported:
            self._manager.import_file(dataset.file_name, dataset.file_path, dataset.df)
            self.log(f"导入成功：{dataset.file_name}，{dataset.row_count}行 {dataset.column_count}列。")
        for item in errors:
            name, msg = item if isinstance(item, tuple) and len(item)==2 else (str(item), "未知错误")
            QMessageBox.warning(self, "导入失败", f"{name}: {msg}"); self.log(f"导入失败：{name} - {msg}", level="error")
        self.log(f"[耗时] 导入并落库 {len(imported)} 个文件：{(_t.perf_counter()-t0)*1000:.1f} ms")
        if imported:
            active = self._manager.active_item()
            if active is not None:
                self.data_panel.set_dataframe(active.df); self.chart_panel.clear(); self._stats_df = None
                self.stats_panel.clear_tables()
                self.stats_panel.set_table("综合统计", pd.DataFrame(columns=["列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
                self.statusBar().showMessage(f"已导入 {len(imported)} 个文件")

    def _on_import_error(self, msg, tb):
        QMessageBox.critical(self, "导入失败", msg); self.log(f"导入失败：{msg}\n{tb}", level="error")

    @staticmethod
    def _parse_exclude_columns(raw):
        if raw is None: return []
        seen = set(); out = []
        for part in str(raw).split(","):
            name = part.strip()
            if not name or name in seen: continue
            seen.add(name); out.append(name)
        return out

    def _persist_category_exclude_columns(self, category, cols):
        key = "head_exclude_columns" if category == "head" else "tail_exclude_columns"
        self._settings.setValue(key, ",".join(cols))

    def _ask_category_factor(self, category):
        label = CATEGORY_LABELS[category]
        default_factor = float(self._category_factors.get(category,1.0) or 1.0)
        default_exclude = list(self._category_exclude_cols.get(category) or [])
        dlg = QDialog(self); dlg.setWindowTitle(f"{label}单像素精度 factor"); form = QFormLayout(dlg)
        sp = QDoubleSpinBox(dlg); sp.setDecimals(6); sp.setRange(0.000001,1e9); sp.setSingleStep(0.01); sp.setValue(default_factor if default_factor>0 else 1.0)
        form.addRow("单像素→mm 换算因子（必须 > 0）：", sp)
        ee = QLineEdit(dlg); ee.setPlaceholderText("逗号分隔，例：时间, 未脱模-s, 指数-s"); ee.setText(", ".join(default_exclude))
        form.addRow("排除列（数值但不是像素数据）：", ee)
        hint = QLabel("排除列会跳过 factor 乘法；时间/日期/文本列会被自动识别跳过。"); hint.setWordWrap(True); hint.setStyleSheet("color:#666;"); form.addRow("", hint)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dlg)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject); form.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted: self.log(f"已取消导入{label}。", level="info"); return None
        factor = float(sp.value())
        if not (factor > 0 and np.isfinite(factor)): QMessageBox.warning(self,"提示",f"{label} factor 必须为大于 0 的有限数值。"); return None
        exclude_list = self._parse_exclude_columns(ee.text())
        self._category_factors[category] = factor
        self._settings.setValue("head_pixel_factor" if category=="head" else "tail_pixel_factor", factor)
        self.processing_panel.set_category_factor(category, factor)
        self._category_exclude_cols[category] = exclude_list; self._persist_category_exclude_columns(category, exclude_list)
        return factor, exclude_list

    def _collect_category_paths(self, mode, category):
        label = CATEGORY_LABELS[category]; start_dir = self._last_import_dir or str(Path.home())
        if mode == "folder":
            folder = QFileDialog.getExistingDirectory(self, f"选择{label}文件夹（递归导入所有表格）", start_dir)
            if not folder: return None
            self._last_import_dir = folder; self._settings.setValue("last_import_dir", self._last_import_dir)
            paths = sorted(str(pp) for pp in Path(folder).rglob("*") if pp.is_file() and pp.suffix.lower() in self._SUPPORTED_TABLE_EXTS)
            if not paths: QMessageBox.information(self,"提示",f"文件夹及子目录中未找到 csv/xlsx/xls 文件。"); return None
            return paths
        paths,_ = QFileDialog.getOpenFileNames(self, f"选择{label}表格文件", start_dir, "表格文件 (*.csv *.xlsx *.xls);;所有文件 (*.*)")
        if not paths: return None
        self._last_import_dir = str(Path(paths[0]).parent); self._settings.setValue("last_import_dir", self._last_import_dir)
        return paths

    def _import_category(self, mode, category):
        if category not in CATEGORY_LABELS or mode not in {"files","folder"}: return
        label = CATEGORY_LABELS[category]; paths = self._collect_category_paths(mode, category)
        if not paths: return
        asked = self._ask_category_factor(category)
        if asked is None: return
        factor, exclude_list = asked; mode_label = "文件夹" if mode=="folder" else "文件"
        self.log(f"开始导入{label}{mode_label} {len(paths)} 个，factor={factor:g}，排除列={exclude_list}。")
        def on_done(result): self._on_category_import_done(result, category, factor, exclude_list)
        self._run_background(label=f"正在导入{label}{mode_label}...", fn=self._worker_import, fn_args=(paths,), on_success=on_done, on_error=self._on_import_error)

    def _on_category_import_done(self, result, category, factor, exclude_list=None):
        import time as _t
        imported = result.get("imported", []); errors = result.get("errors", []); label = CATEGORY_LABELS.get(category, category); t0 = _t.perf_counter()
        new_items = []
        for dataset in imported:
            item = self._manager.import_file(dataset.file_name, dataset.file_path, dataset.df)
            item.category = category; item.pixel_factor = factor; item.scaled = False; new_items.append(item)
            self.log(f"导入成功：[{label}] {dataset.file_name}，{dataset.row_count}行 {dataset.column_count}列，factor={factor:g}。")
        for it in errors:
            name, msg = it if isinstance(it, tuple) and len(it)==2 else (str(it),"未知错误")
            QMessageBox.warning(self,"导入失败",f"{name}: {msg}"); self.log(f"导入失败：{name} - {msg}", level="error")
        self.log(f"[耗时] 导入{label} {len(imported)} 个文件：{(_t.perf_counter()-t0)*1000:.1f} ms")
        if new_items:
            eff = list(exclude_list) if exclude_list is not None else list(self._category_exclude_cols.get(category) or [])
            self._category_exclude_cols[category] = list(dict.fromkeys(eff)); self._persist_category_exclude_columns(category, self._category_exclude_cols[category])
            self.log(f"按类别缩放 {label}，factor={factor:g}，排除列={self._category_exclude_cols[category]}")
            try:
                self.setCursor(Qt.CursorShape.WaitCursor)
                logs = scale_datasets_by_category(self._manager, category, float(factor), exclude_mode="auto", exclude_columns=list(self._category_exclude_cols[category]))
            except Exception as exc:
                QMessageBox.critical(self,"导入后批量缩放失败",str(exc)); self.log(f"{label}导入后批量缩放异常：{exc}", level="error"); logs = []
            finally:
                self.unsetCursor()
            for m in logs: self.log(m)
            self._invalidate_cache(); self._refresh_dataset_ui()
            last = new_items[-1]
            try: live_last = self._manager.get(last.dataset_id)
            except Exception: live_last = last
            self._manager.set_active(live_last.dataset_id)
            try: self._cache_columns_for(live_last)
            except Exception: pass
            self.data_panel.set_dataframe(live_last.df); self.chart_panel.clear(); self._stats_df = None
            self.stats_panel.clear_tables()
            self.stats_panel.set_table("综合统计", pd.DataFrame(columns=["列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
            self._refresh_scale_hint(); self.statusBar().showMessage(f"已导入{label}文件 {len(imported)} 个并完成按类别缩放")


    def _activate_dataset(self, dataset_id):
        def do_activate(report_progress=None):
            if report_progress: report_progress(30,"准备数据集预览...")
            t0 = time.perf_counter(); item = self._manager.get(dataset_id); self._cache_columns_for(item)
            return {"item": item, "elapsed": time.perf_counter()-t0}
        def on_success(result):
            if result is None: return
            item = result["item"]; self._manager.set_active(item.dataset_id)
            with timed("切换并刷新UI", self.log):
                self.data_panel.set_dataframe(item.df); self.chart_panel.clear(); self.desc_charts_panel.clear()
                self._desc_tables = {}; self._stats_df = None; self.stats_panel.clear_tables()
                self.stats_panel.set_table("综合统计", pd.DataFrame(columns=["列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
            self.log(f"已切换到数据集：{item.name}（切换耗时 {format_duration(result['elapsed'])}）"); self.statusBar().showMessage(f"当前数据集：{item.name}")
        def on_error(msg, tb): self.log(str(msg), level="warning"); QMessageBox.warning(self,"提示",str(msg))
        self._run_background("切换数据集...", do_activate, (), on_success, on_error)

    def _delete_dataset(self, dataset_id):
        try: item = self._manager.get(dataset_id)
        except KeyError: return
        if not item.can_delete: self.log("尝试删除原始数据被拦截。", level="warning"); QMessageBox.information(self,"提示","原始导入数据不可删除。"); return
        try: self._invalidate_cache(dataset_id); self._manager.remove(dataset_id); self.log(f"已删除临时数据集：{item.name}")
        except Exception as exc: QMessageBox.warning(self,"删除失败",str(exc))

    def _export_dataset(self, dataset_id):
        try: item = self._manager.get(dataset_id)
        except KeyError: return
        start_dir = str(Path(self._last_export_dir)/item.name)
        file_path, selected_filter = QFileDialog.getSaveFileName(self,"导出数据集",start_dir,"CSV 文件 (*.csv);;Excel 文件 (*.xlsx)")
        if not file_path: return
        self._last_export_dir = str(Path(file_path).parent); self._settings.setValue("last_export_dir", self._last_export_dir)
        try:
            with timed(f"导出数据集 {item.name}", self.log):
                if selected_filter.startswith("Excel") or file_path.lower().endswith(".xlsx"):
                    if not file_path.lower().endswith(".xlsx"): file_path += ".xlsx"
                    export_stats_to_excel(item.df, file_path)
                else:
                    if not file_path.lower().endswith(".csv"): file_path += ".csv"
                    export_stats_to_csv(item.df, file_path)
            self.log(f"数据集已导出：{file_path}"); self.statusBar().showMessage(f"数据集已导出：{Path(file_path).name}")
        except ExportError as exc: QMessageBox.critical(self,"导出失败",str(exc)); self.log(f"导出失败：{exc}", level="error")

    def _merge_datasets(self, dataset_ids):
        active = self._manager.active_item()
        if active is None: QMessageBox.warning(self,"提示","请先导入至少一个数据集。"); return
        time_col = None; cache = self._cache_columns_for(active); dt_cols = [c for c in cache["datetime"]]
        if dt_cols: time_col = dt_cols[0]
        else:
            with warnings.catch_warnings(): warnings.simplefilter("ignore")
            for c in active.df.columns:
                s = active.df[c]
                if pd.api.types.is_datetime64_any_dtype(s): time_col = str(c); break
                if s.dtype == object and pd.to_datetime(s, errors="coerce").notna().mean() >= 0.8: time_col = str(c); break
        if time_col is None:
            items = [str(c) for c in active.df.columns]; time_col, ok = QInputDialog.getItem(self,"选择合并时间列","按哪一列合并排序：", items, 0, False)
            if not ok: return
        def do_merge(report_progress=None):
            if report_progress: report_progress(20,"读取并对齐数据集...")
            t0 = time.perf_counter(); frames = []; sources = []; tcol = str(time_col)
            for did in dataset_ids:
                item = self._manager.get(did)
                if tcol not in item.df.columns: raise ValueError(f"数据集“{item.name}”缺少时间列：{tcol}")
                from app.services.data_processor import infer_datetime_series
                work = item.df.copy(); work[tcol] = infer_datetime_series(work[tcol]); work = work.dropna(subset=[tcol])
                frames.append(work); sources.extend(item.source_files)
                if report_progress: report_progress(40, f"已读取 {len(sources)} 个文件源...")
            if report_progress: report_progress(70,"拼接并按时间排序...")
            from datetime import datetime as _dt
            merged = pd.concat(frames, ignore_index=True, sort=False).sort_values(by=tcol, kind="mergesort").reset_index(drop=True)
            return {"df": merged, "time_col": tcol, "sources": sources, "elapsed": time.perf_counter()-t0}
        def on_success(result):
            from datetime import datetime as _dt
            name = f"合并结果_{_dt.now().strftime('%H%M%S')}"
            item = self._manager.add_temporary(name, result["df"], kind="merged", source_files=result["sources"], metadata={"time_column": result["time_col"]})
            self._invalidate_cache(item.dataset_id); self._manager.set_active(item.dataset_id); self._cache_columns_for(item)
            self.data_panel.set_dataframe(item.df); self.chart_panel.clear(); self._stats_df = None
            self.stats_panel.clear_tables()
            self.stats_panel.set_table("综合统计", pd.DataFrame(columns=["列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
            self.log(f"已生成合并数据集：{item.name}，按时间列“{result['time_col']}”排序（合并耗时 {format_duration(result['elapsed'])}）"); self.statusBar().showMessage(f"已切换到合并数据集：{item.name}")
        self._run_background("正在合并数据集...", do_merge, (), on_success, on_error=lambda m,tb:(QMessageBox.warning(self,"合并失败",m), self.log(f"合并失败：{m}", level="error")))

    def _merge_by_category(self, category):
        label = CATEGORY_LABELS.get(category, str(category))
        try:
            self.setCursor(Qt.CursorShape.WaitCursor); item = self._manager.merge_by_category(category)
        except ValueError as exc: QMessageBox.warning(self, f"{label}合并失败", str(exc)); self.log(f"{label}合并失败：{exc}", level="warning"); return
        except Exception as exc: QMessageBox.critical(self, f"{label}合并失败", str(exc)); self.log(f"{label}合并异常：{exc}", level="error"); return
        finally: self.unsetCursor()
        self._invalidate_cache(item.dataset_id); self.log(f"已生成 {label}_合并（{item.dataset_id}）。"); self._refresh_dataset_ui()
        try: self._manager.set_active(item.dataset_id); self.data_panel.set_dataframe(item.df); self.chart_panel.clear(); self._stats_df = None
        except Exception as exc: self.log(f"切换到{label}合并结果失败：{exc}", level="warning")

    def _merge_cross_category(self):
        oh = [it for it in self._manager.items() if it.kind=="original" and getattr(it,"category",None)=="head"]
        ot = [it for it in self._manager.items() if it.kind=="original" and getattr(it,"category",None)=="tail"]
        miss = []
        if not oh: miss.append("机头")
        if not ot: miss.append("机尾")
        if miss: QMessageBox.warning(self,"提示",f"请先导入{'/'.join(miss)}文件后再进行跨类合同图。"); return
        try:
            self.setCursor(Qt.CursorShape.WaitCursor); item = self._manager.merge_cross_category()
        except ValueError as exc: QMessageBox.warning(self,"跨类合同图失败",str(exc)); self.log(f"跨类合同图失败：{exc}", level="warning"); return
        except Exception as exc: QMessageBox.critical(self,"跨类合同图失败",str(exc)); self.log(f"跨类合同图异常：{exc}", level="error"); return
        finally: self.unsetCursor()
        self._invalidate_cache(item.dataset_id); self.log("已生成 机头+机尾_跨类合并。")
        try: self._manager.set_active(item.dataset_id)
        except Exception: pass
        self._refresh_dataset_ui()
        try: self.data_panel.set_dataframe(item.df); self.chart_panel.clear(); self._stats_df = None
        except Exception as exc: self.log(f"刷新跨类合并视图失败：{exc}", level="warning")


    def _find_scaled_originals(self, category, factor=None):
        diff=[]; same=[]
        for it in self._manager.items():
            if it.kind!="original" or getattr(it,"category",None)!=category or not getattr(it,"scaled",False): continue
            pf = float(getattr(it,"pixel_factor",None) or 0.0)
            if factor is None or abs(pf-float(factor))>1e-9: diff.append((it,pf))
            else: same.append((it,pf))
        return diff, same

    def _refresh_scale_hint(self):
        try:
            pp = self.processing_panel
            if pp.action_combo.currentData()!="scale_by_factor": pp.set_scale_warning(None); return
            scope = pp.scale_scope_combo.currentData()
            if scope not in ("head","tail"): pp.set_scale_warning(None); return
            label = CATEGORY_LABELS.get(scope, scope); factor = float(pp.factor_spin.value())
            diff, same = self._find_scaled_originals(scope, factor); total = len(diff)+len(same)
            if total == 0: pp.set_scale_warning(None); return
            if diff:
                old = sorted({f"{pf:g}" for _,pf in diff}); ot = ",".join(old[:3])+("..." if len(old)>3 else "")
                pp.set_scale_warning(f"⚠️ 该类别已有 {len(diff)} 个{label}数据集按旧 factor={ot} 缩放，点击\"执行处理\"将询问是否强制重新缩放。")
            else:
                pp.set_scale_warning(f"⚠️ 该类别已有 {len(same)} 个{label}数据集已按当前 factor={factor:g} 缩放，执行时将自动跳过。")
        except Exception:
            try: self.processing_panel.set_scale_warning(None)
            except Exception: pass

    def _scale_category_datasets(self, category, factor, exclude_mode, exclude_columns):
        label = CATEGORY_LABELS.get(category, str(category))
        if category not in CATEGORY_LABELS: QMessageBox.warning(self,"提示",f"未知类别：{category}"); return
        if not (factor>0 and np.isfinite(factor)): QMessageBox.warning(self,"提示","缩放因子必须为大于 0 的有限数值。"); return
        force=False; rescale=[]
        diff, same = self._find_scaled_originals(category, factor)
        if diff:
            old = sorted({pf for _,pf in diff})
            rep = f"{old[0]:g}" if len(old)==1 else ",".join(f"{pf:g}" for pf in old[:3])+("..." if len(old)>3 else "")
            ans = QMessageBox.question(self,"检测到已缩放数据集",f"检测到 {len(diff)} 个{label}数据集已按旧 factor={rep} 缩放。\n是否强制重新缩放？（将清除 (mm) 后缀并按新 factor={factor:g} 重新乘，原列名恢复）", QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes: force=True; rescale=[it for it,_ in diff]
            else: self.log(f"已跳过 {len(diff)} 个已缩放数据集（旧 factor≠当前 factor）。")
        if same: self.log(f"已跳过 {len(same)} 个已缩放数据集（factor 与当前 {factor:g} 相同）。")
        try:
            self.setCursor(Qt.CursorShape.WaitCursor)
            mode = exclude_mode or "auto"
            eff = list(exclude_columns) if exclude_columns else (list(self._category_exclude_cols.get(category) or []) if mode=="auto" else [])
            self.log(f"按类别缩放 {label}，factor={factor:g}，排除列={eff}")
            logs = scale_datasets_by_category(self._manager, category, float(factor), exclude_mode=mode, exclude_columns=eff, force_rescale=force, rescale_targets=rescale)
        except Exception as exc:
            QMessageBox.critical(self,"批量缩放失败",str(exc)); self.log(f"{label}批量缩放异常：{exc}", level="error"); return
        finally: self.unsetCursor()
        for m in logs: self.log(m)
        self._category_factors[category] = float(factor)
        self._settings.setValue("head_pixel_factor" if category=="head" else "tail_pixel_factor", float(factor))
        active = self._manager.active_item(); self._invalidate_cache(); self._refresh_dataset_ui()
        if active is not None and active.kind=="original" and getattr(active,"category",None)==category:
            try: self.data_panel.set_dataframe(active.df)
            except Exception: pass
        self._refresh_scale_hint(); self.statusBar().showMessage(f"{label}批量缩放完成。")

    def _apply_processing(self, rules):
        active = self._manager.active_item()
        if active is None: QMessageBox.warning(self,"提示","请先导入并激活数据集。"); return
        new_name = f"{active.name}_处理结果"; snap = list(rules)
        def do_work(report_progress=None):
            t0 = time.perf_counter()
            if report_progress: report_progress(20,"执行处理规则...")
            pdf, logs = apply_rules(active.df.copy(), snap)
            return {"df":pdf, "logs":logs, "source_files":list(active.source_files), "from_id":active.dataset_id, "elapsed":time.perf_counter()-t0}
        def on_success(result):
            item = self._manager.add_temporary(new_name, result["df"], kind="processed", source_files=result["source_files"], metadata={"from":result["from_id"]})
            self._invalidate_cache(item.dataset_id); self._manager.set_active(item.dataset_id); self._cache_columns_for(item)
            self.data_panel.set_dataframe(item.df); self.chart_panel.clear(); self._stats_df = None
            for m in result["logs"]: self.log(m)
            self.log(f"已生成临时处理数据集：{item.name}（处理耗时 {format_duration(result['elapsed'])}）"); self.statusBar().showMessage(f"数据处理完成：{item.name}")
        def on_error(msg, tb): QMessageBox.critical(self,"处理失败",msg); self.log(f"数据处理失败：{msg}\n{tb}", level="error")
        self._run_background("正在处理数据...", do_work, (), on_success, on_error)

    def _selected_analysis_columns(self):
        return [it.text() for it in self.analysis_list.selectedItems()]


    def _run_analysis(self):
        active = self._manager.active_item()
        if active is None: QMessageBox.warning(self,"提示","请先导入数据。"); return
        cols = self._selected_analysis_columns()
        if not cols: QMessageBox.warning(self,"提示","请在当前数据集信息区域选择至少一个统计列。"); return
        ys = self.chart_config_panel.selected_y_series(); x = self.chart_config_panel.selected_x_column()
        gran = self.chart_options_panel.current_granularity(); cache = self._cache_columns_for(active); num = cache["numeric"]
        sc = [c for c in cols if c in num]
        for c in cols:
            if c not in num: self.log(f"列\"{c}\"不是数值列，统计已跳过。", level="warning")
        if not sc and not ys: QMessageBox.warning(self,"提示","所选列中无可统计数值列且未勾选Y轴。"); return
        def do_work(rp=None):
            t0 = time.perf_counter()
            if rp: rp(10,"计算统计量...")
            res = calculate_batch_stats(active.df, sc) if sc else []
            sdf = stats_to_dataframe(res) if res else None
            if rp: rp(60,"准备图表数据...")
            ym = self.chart_options_panel.current_y_mode()
            cr = self._prepare_chart_data(active.df, x, ys, gran, cache, y_mode=ym)
            return {"stats_df":sdf,"stats_cols":sc,"chart":cr,"y_series":ys,"x_col":x,"elapsed":time.perf_counter()-t0}
        def on_success(r):
            if r["stats_df"] is not None:
                self._stats_df = r["stats_df"]; self.stats_panel.set_table("综合统计", self._stats_df); self.tabs.setCurrentWidget(self.stats_panel)
                self.log(f"统计完成，共 {len(r['stats_cols'])} 列。")
            else: self.log("未选择数值统计列，跳过统计。", level="warning")
            ch = r["chart"]; yf = ch.get("y_series_norm") if isinstance(ch,dict) else None
            if ch is not None and (yf or r["y_series"]):
                self._render_chart(ch, r["x_col"], yf or r["y_series"]); self.tabs.setCurrentWidget(self.data_panel)
            else: self.log("未勾选Y轴列，已跳过绘图。")
            self.log(f"分析总耗时：{format_duration(r['elapsed'])}")
        def on_error(msg,tb): QMessageBox.critical(self,"分析失败",msg); self.log(f"分析失败：{msg}\n{tb}", level="error")
        self._run_background("正在分析...", do_work, (), on_success, on_error)

    def _run_chart_only(self):
        if self._manager.active_item() is None: QMessageBox.warning(self,"提示","请先导入数据。"); return
        ys = self.chart_config_panel.selected_y_series()
        if not ys: QMessageBox.warning(self,"提示","请至少勾选一个Y轴列。"); return
        x = self.chart_config_panel.selected_x_column(); gran = self.chart_options_panel.current_granularity()
        active = self._manager.active_item(); cache = self._cache_columns_for(active)
        def do_work(rp=None):
            t0 = time.perf_counter()
            if rp: rp(20,"准备图表数据...")
            ym = self.chart_options_panel.current_y_mode()
            cr = self._prepare_chart_data(active.df, x, ys, gran, cache, y_mode=ym)
            return {"chart":cr,"x_col":x,"y_series":ys,"elapsed":time.perf_counter()-t0}
        def on_success(r):
            ch = r["chart"]
            if ch is None: return
            yf = ch.get("y_series_norm") if isinstance(ch,dict) else None
            self._render_chart(ch, r["x_col"], yf or r["y_series"]); self.tabs.setCurrentWidget(self.data_panel)
            self.log(f"绘图完成，耗时 {format_duration(r['elapsed'])}")
        def on_error(msg,tb): QMessageBox.critical(self,"绘图失败",msg); self.log(f"绘图失败：{msg}\n{tb}", level="error")
        self._run_background("正在绘图...", do_work, (), on_success, on_error)

    def _refresh_chart_if_any(self):
        if self.chart_panel.has_plotted_data(): self._run_chart_only()

    @staticmethod
    def _dedup_columns(cols):
        ct={}; out=[]
        for c in cols:
            if c not in ct: ct[c]=0; out.append(c)
            else: ct[c]+=1; out.append(f"{c}__dup{ct[c]}")
        return out

    @staticmethod
    def _normalize_chart_df_01(cdf, yc):
        out = cdf.copy(); mm={}
        for c in yc:
            if c not in out.columns: continue
            s = pd.to_numeric(out[c], errors="coerce")
            lo = float(s.min()) if s.notna().any() else 0.0
            hi = float(s.max()) if s.notna().any() else 0.0
            rng = hi-lo
            if not np.isfinite(rng) or rng <= 0: out[c] = 0.0; mm[c]=0.0; continue
            out[c] = (s-lo)/rng; m = float(out[c].mean()); mm[c] = m if pd.notna(m) else 0.0
        return out, mm

    def _prepare_chart_data(self, df, x_col, y_series, granularity, cache, y_mode="shared"):
        norm=[]; seen=set()
        if not y_series or not x_col: return None
        for item in y_series:
            name=None; color=None; show_mean=False
            try:
                if isinstance(item,str): name=item
                elif isinstance(item,(tuple,list)):
                    if len(item)==1: name=item[0]
                    elif len(item)==2: name,color=item[0],item[1]
                    elif len(item)>=3: name,color,show_mean=item[0],item[1],bool(item[2])
                if not isinstance(name,str) or not name or name in seen: continue
                seen.add(name)
                if color is not None and not isinstance(color,str): color=str(color)
                norm.append((name,color,show_mean))
            except Exception: continue
        if not norm: return None
        yc=[n for n,_,_ in norm]
        try: dfw=df.copy()
        except Exception: dfw=df
        try: dup=bool(dfw.columns.duplicated().any())
        except Exception: dup=False
        if dup: dfw=dfw.copy(); dfw.columns=self._dedup_columns([str(c) for c in dfw.columns])
        if x_col not in dfw.columns: raise KeyError(f"X 轴列不存在：{x_col}")
        msgs=[]; nset=cache.get("numeric",set()) if isinstance(cache,dict) else set()
        vyc=[]; vs=[]
        for name,color,sm in norm:
            if name not in dfw.columns: msgs.append(f"列\"{name}\"不存在，已跳过。"); continue
            if name not in nset: msgs.append(f"列\"{name}\"非数值列，已跳过。"); continue
            vyc.append(name); vs.append((name,color,sm))
        if not vyc:
            return {"chart_df":dfw.iloc[0:0],"mean_map":{},"messages":msgs+["无可绘图的Y数值列。"],"x_is_datetime":False,"use_time":False,"y_series_norm":[],"y_mode":"shared"}
        norm=vs; yc=vyc
        use_time=False; dset=cache.get("datetime",set()) if isinstance(cache,dict) else set()
        if x_col in dset: use_time=True
        else:
            sx=dfw[x_col]
            if not pd.api.types.is_numeric_dtype(sx):
                nn=sx.dropna()
                if len(nn)>0:
                    with warnings.catch_warnings(): warnings.simplefilter("ignore"); cv=pd.to_datetime(nn,errors="coerce")
                    if cv.notna().sum()/max(1,len(nn))>=0.8: use_time=True
        cdf=dfw[[x_col]+yc].copy(); mm={}; xdt=False
        def _sn(s):
            try: return pd.to_numeric(s,errors="coerce")
            except Exception: msgs.append(f"列\"{getattr(s,'name','')}\"数值转换失败，已填充为 NaN。"); return pd.Series(np.nan,index=s.index,dtype=float)
        if use_time:
            with warnings.catch_warnings(): warnings.simplefilter("ignore"); cdf[x_col]=pd.to_datetime(cdf[x_col],errors="coerce")
            cdf = cdf.dropna(subset=[x_col])
            for c in yc:
                cdf[c]=_sn(cdf[c])
                try:
                    mv=float(_sn(dfw[c]).mean())
                    if pd.notna(mv): mm[c]=mv
                except Exception: pass
            if granularity!="原始":
                ad,am,xd,_=aggregate_by_time(dfw,x_col,yc,granularity); msgs.extend(am); cdf=ad; xdt=xd
                for c2 in yc:
                    if c2 in cdf.columns:
                        cdf[c2]=_sn(cdf[c2])
                        try:
                            mv=float(cdf[c2].mean())
                            if pd.notna(mv): mm[c2]=mv
                        except Exception: pass
            else: cdf=cdf.sort_values(x_col); xdt=True; msgs.append("X轴按日期时间原始顺序展示。")
        else:
            for c in yc:
                cdf[c]=_sn(cdf[c])
                try: mv=cdf[c].mean(); mm[c]=float(mv) if pd.notna(mv) else 0.0
                except Exception: mm[c]=0.0
            msgs.append("X轴非时间列，时间粒度设置已忽略。")
        mode=y_mode if y_mode in ("shared","normalized","dual","small_multiples") else "shared"
        if mode=="normalized": cdf,mm=self._normalize_chart_df_01(cdf,yc); msgs.append("Y轴已按各列 min-max 归一化到 [0,1]，仅用于绘图显示。")
        return {"chart_df":cdf,"mean_map":mm,"messages":msgs,"x_is_datetime":xdt if use_time else False,"use_time":use_time,"y_series_norm":norm,"y_mode":mode}

    def _render_chart(self, prep, x_col, y_series):
        cdf=prep["chart_df"]; mm=prep["mean_map"]; msgs=prep["messages"]; xdt=prep["x_is_datetime"]; ym=prep.get("y_mode","shared"); gran=self.chart_options_panel.current_granularity()
        title=f"{x_col} - 多列趋势图" if len(y_series)>1 else f"{x_col} - {y_series[0][0]} 趋势图"
        with timed("图表渲染", self.log):
            pm = self.chart_panel.plot_multi_line(cdf, x_col, y_series, mean_map=mm, title=title, show_points=self.chart_config_panel.show_points(), show_mean_lines=self.chart_config_panel.show_mean_lines(), x_is_datetime=xdt, granularity=gran if xdt else "原始", y_axis_mode=ym)
            if ym=="normalized": self.chart_panel.plot_widget.setLabel("left","归一化值 (0-1)")
            elif ym=="shared": self.chart_panel.plot_widget.setLabel("left","数值")
        msgs.extend(pm)
        for m in msgs: self.log(m)
        self.statusBar().showMessage("图表已生成")


    def _run_descriptive_analysis(self, config):
        active = self._manager.active_item()
        if active is None: QMessageBox.warning(self,"提示","请先导入数据。"); return
        cols = config.get("columns") or []
        if not cols: QMessageBox.warning(self,"提示","请先在描述统计面板选择至少一列。"); return
        def do_work(rp=None):
            t0=time.perf_counter(); df=active.df
            if rp: rp(10,"计算描述统计量...")
            nc=[c for c in cols if c in df.columns]
            res=batch_descriptive_stats(df,nc); sdf=descriptive_to_dataframe(res)
            if rp: rp(35,"计算分位数表...")
            qt=quantile_table(df,nc)
            if rp: rp(50,"缺失/无效统计...")
            ms=missing_summary(df,df.columns.tolist())
            if rp: rp(65,"相关矩阵...")
            cr=correlation_matrix(df,nc,method=config.get("corr_method","pearson"))
            bx=boxplot_stats(df,nc,iqr_k=config.get("iqr_k",1.5))
            return {"stats_df":sdf,"quantile_df":qt,"missing_df":ms,"corr_df":cr,"box_df":bx,"config":config,"numeric_cols":nc,"elapsed":time.perf_counter()-t0}
        def on_success(r):
            cfg=r["config"]; nc=r["numeric_cols"]
            with timed("描述统计渲染", self.log):
                self._desc_tables={"综合统计":r["stats_df"],"分位数":r["quantile_df"],"缺失/无效":r["missing_df"],"箱线统计":r["box_df"],"相关矩阵":r["corr_df"]}
                self.stats_panel.clear_tables()
                for k,v in self._desc_tables.items(): self.stats_panel.set_table(k,v)
                self.chart_tabs.setCurrentIndex(1)
                ms = self.desc_charts_panel.render(active.df,nc,bins=cfg.get("bins",30),show_kde=cfg.get("show_kde",True),show_mean=cfg.get("show_mean",True),show_median=cfg.get("show_median",True),iqr_k=cfg.get("iqr_k",1.5),corr_method=cfg.get("corr_method","pearson"),show_scatter_matrix=cfg.get("show_scatter_matrix",False),show_qq=cfg.get("show_qq",True))
                for m in ms: self.log(m)
            self.log(f"描述统计完成，共 {len(nc)} 列（总耗时 {format_duration(r['elapsed'])}）。")
            self.tabs.setCurrentWidget(self.stats_panel); self.stats_panel.show_table("综合统计")
        def on_error(msg,tb): QMessageBox.critical(self,"描述统计失败",msg); self.log(f"描述统计失败：{msg}\n{tb}", level="error")
        self._run_background("正在计算描述统计...", do_work, (), on_success, on_error)

    def _refresh_process_analysis_panel(self):
        active = self._manager.active_item()
        if active is None or active.df is None or active.df.empty:
            self.process_analysis_panel.set_dataset(None,[],[],[],[]); return
        df=active.df; cache=self._cache_columns_for(active)
        nc=sorted(cache["numeric"], key=lambda c: list(df.columns).index(c) if c in df.columns else 999)
        dc=sorted(cache["datetime"])
        inf=infer_columns(df); sc=list(inf.get("state_col_candidates",[]))
        if not sc:
            for c in df.columns:
                s=df[c]
                if str(c) in dc: continue
                if pd.api.types.is_numeric_dtype(s):
                    try:
                        if int(s.nunique(dropna=True))<=12: sc.append(str(c))
                    except Exception: pass
        self.process_analysis_panel.set_dataset(df,time_col_options=dc,state_col_options=sc,numeric_cols=nc,datetime_cols=dc)

    def _on_process_analysis_requested(self, config):
        active = self._manager.active_item()
        if active is None or active.df is None:
            QMessageBox.warning(self,"提示","请先导入并激活一个数据集。"); self.process_analysis_panel.set_running(False); return
        sc=config.get("state_col"); ts=config.get("target_states"); fc=config.get("feature_cols")
        if not sc or not fc: QMessageBox.warning(self,"提示","请选择状态列和至少一个特征列。"); self.process_analysis_panel.set_running(False); return
        df=active.df
        def do_work(rp=None):
            if rp: rp(10,"正在识别列与计算统计量...")
            return build_analysis_report(df,state_col=sc,feature_cols=fc,target_states=ts,min_samples=30)
        def on_success(rep):
            self.process_analysis_panel.set_running(False)
            if rep is None: self.log("工艺分析返回空结果。", level="warning"); return
            self.process_analysis_panel.set_result(rep)
            if "error" in rep: self.log(f"工艺分析失败：{rep['error']}", level="warning"); QMessageBox.warning(self,"分析失败",rep["error"]); return
            self.tabs.setCurrentWidget(self.process_analysis_panel)
            meta=rep.get("meta",{}); self.log(f"工艺分析完成：{meta.get('n_rows',0)} 行，特征 {len(meta.get('feature_cols',[]))} 列，目标状态 {meta.get('target_states',[])}。")
        def on_error(msg,tb): self.process_analysis_panel.set_running(False); QMessageBox.critical(self,"工艺分析失败",msg); self.log(f"工艺分析失败：{msg}\n{tb}", level="error")
        self.process_analysis_panel.set_running(True)
        self._run_background("正在进行工艺分析...", do_work, (), on_success, on_error)

    def _on_ai_insight_requested(self, provider, base_url, model, api_key):
        report = self.process_analysis_panel.report()
        if not report or "error" in report: self.process_analysis_panel.set_ai_status("请先完成工艺分析。"); return
        url=(base_url or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            self.process_analysis_panel.set_ai_status("Base URL 需以 http:// 或 https:// 开头")
            self.process_analysis_panel.ai_generate_btn.setEnabled(True); self.process_analysis_panel.ai_regenerate_btn.setEnabled(True)
            self.statusBar().showMessage("Base URL 需以 http:// 或 https:// 开头",5000); self.log("AI 解读已取消：Base URL 需以 http:// 或 https:// 开头", level="error"); return
        try: messages = build_insight_prompt(report)
        except Exception as exc: self.process_analysis_panel.set_ai_status(f"失败: 构造 prompt 出错 {exc}"); self.process_analysis_panel.ai_result_browser.setPlainText(""); return
        self.log(f"AI 解读请求中 provider={provider} model={model}")
        def do_work(rp=None):
            client = AIClient(provider=provider, base_url=url, api_key=api_key, model=model)
            return client.chat(messages, temperature=0.3)
        def on_success(text):
            self.process_analysis_panel.set_ai_result(text); self.log(f"AI 解读完成，返回 {len(text or '')} 字。")
        def on_error(msg,tb):
            sm = str(msg).replace(api_key,"***") if api_key else str(msg)
            self.process_analysis_panel.set_ai_status(f"失败: {sm}"); self.process_analysis_panel.ai_result_browser.setPlainText("")
            self.process_analysis_panel.ai_generate_btn.setEnabled(True); self.process_analysis_panel.ai_regenerate_btn.setEnabled(True)
            self.log(f"AI 解读失败：{sm}", level="error")
        self._run_background("AI 解读请求中...", do_work, (), on_success, on_error)

    def _on_process_analysis_export(self):
        report = self.process_analysis_panel.report()
        if not report or "error" in report: QMessageBox.warning(self,"提示","没有可导出的分析结果，请先执行分析。"); return
        start_dir = str(Path(self._last_export_dir)/"process_window")
        csv_path,_ = QFileDialog.getSaveFileName(self,"导出工艺窗口 CSV", start_dir+".csv","CSV 文件 (*.csv)")
        if not csv_path: return
        rows=[]
        for st,body in report.get("univariate",{}).items():
            for ft,info in (body.get("features",{}) if isinstance(body,dict) else {}).items():
                w1=info.get("window_1sigma",(None,None)); w2=info.get("window_2sigma",(None,None))
                rows.append({"状态":st,"特征":ft,"样本数":info.get("count",0),"均值":info.get("mean"),"标准差":info.get("std"),"μ±σ_下界":w1[0],"μ±σ_上界":w1[1],"μ±2σ_下界":w2[0],"μ±2σ_上界":w2[1],"P5":info.get("p5"),"P95":info.get("p95")})
        odf = pd.DataFrame(rows)
        try: odf.to_csv(csv_path,index=False,encoding="utf-8-sig")
        except Exception as exc: QMessageBox.critical(self,"导出失败",f"CSV 写入失败：{exc}"); self.log(f"工艺分析 CSV 导出失败：{exc}", level="error"); return
        self._last_export_dir = str(Path(csv_path).parent); self._settings.setValue("last_export_dir", self._last_export_dir); self.log(f"工艺窗口 CSV 已导出：{csv_path}")
        dpng = str(Path(csv_path).with_suffix(".png"))
        png_path,_ = QFileDialog.getSaveFileName(self,"导出箱线图 PNG", dpng,"PNG 图片 (*.png)")
        if not png_path: return
        try: export_plot_widget_to_png(self.process_analysis_panel.boxplot_widget, png_path)
        except ExportError as exc: QMessageBox.critical(self,"导出失败",str(exc)); self.log(f"工艺分析 PNG 导出失败：{exc}", level="error"); return
        self.log(f"工艺箱线图 PNG 已导出：{png_path}")


    def _export_stats(self):
        df=None; tn=None; mid=self._mode_button_group.checkedId()
        if mid==1 and self._desc_tables:
            k=self.stats_panel.combo.currentText(); df=self._desc_tables.get(k); tn=k
        if df is None and self._stats_df is not None and not self._stats_df.empty: df=self._stats_df; tn="综合统计"
        if df is None or df.empty: QMessageBox.warning(self,"提示","当前没有可导出的统计结果，请先完成分析。"); return
        dn = "stats_result" if not tn else f"stats_{tn}"
        sd = str(Path(self._last_export_dir)/dn)
        fp, sf = QFileDialog.getSaveFileName(self,"导出统计结果",sd,"CSV 文件 (*.csv);;Excel 文件 (*.xlsx)")
        if not fp: return
        try:
            with timed("导出统计结果", self.log):
                if sf.startswith("Excel") or fp.lower().endswith(".xlsx"):
                    if not fp.lower().endswith(".xlsx"): fp += ".xlsx"
                    export_stats_to_excel(df, fp)
                else:
                    if not fp.lower().endswith(".csv"): fp += ".csv"
                    export_stats_to_csv(df, fp)
            self._last_export_dir = str(Path(fp).parent); self._settings.setValue("last_export_dir", self._last_export_dir)
            self.log(f"统计结果已导出：{fp}（{tn}）"); self.statusBar().showMessage(f"统计结果已导出：{Path(fp).name}")
        except ExportError as exc: QMessageBox.critical(self,"导出失败",str(exc)); self.log(f"导出失败：{exc}", level="error")

    def _current_chart_export_target(self):
        idx = self.chart_tabs.currentIndex()
        if idx == 0: return self.chart_panel.current_export_widget(), "trend_chart.png", "折线趋势图"
        if idx == 1:
            w = self.desc_charts_panel.tabs.currentWidget()
            nm = {0:"histogram_kde",1:"boxplot",2:"qq",3:"correlation",4:"scatter_matrix"}
            return w, f"{nm.get(self.desc_charts_panel.tabs.currentIndex(),'descriptive')}.png", "描述统计图"
        return None,None,None

    def _export_chart_image(self):
        t,dn,hint = self._current_chart_export_target()
        if t is None: QMessageBox.warning(self,"提示","当前模式暂无图表可导出。"); return
        if self.chart_tabs.currentIndex()==0 and not self.chart_panel.has_plotted_data():
            QMessageBox.warning(self,"提示","当前没有可导出的图表，请先生成折线图。"); return
        sd = str(Path(self._last_export_dir)/(dn or "chart.png"))
        fp,_ = QFileDialog.getSaveFileName(self,"导出图表图片",sd,"PNG 图片 (*.png)")
        if not fp: return
        if not fp.lower().endswith(".png"): fp += ".png"
        try:
            with timed("导出图表图片", self.log): export_plot_widget_to_png(t, fp)
            self._last_export_dir = str(Path(fp).parent); self._settings.setValue("last_export_dir", self._last_export_dir)
            self.log(f"{hint}已导出：{fp}"); self.statusBar().showMessage(f"图表已导出：{Path(fp).name}")
        except ExportError as exc: QMessageBox.critical(self,"导出失败",str(exc)); self.log(f"图表导出失败：{exc}", level="error")

    def _clear_all(self):
        self._manager.clear(); self._stats_df=None; self._desc_tables={}
        self.chart_panel.clear(); self.desc_charts_panel.clear()
        self._invalidate_cache(); self._apply_initial_state()
        self.processing_panel._clear_rules()
        self.process_analysis_panel.set_dataset(None,[],[],[],[])
        self.log("已清空全部数据与临时储存区。"); self.statusBar().showMessage("已清空")

    def _show_about(self):
        t = "关于 DateAnalysis V1.11.0"
        txt = ("本地数据分析与图表展示软件 V1.11.0\n\n"
               "支持多文件/文件夹导入、机头/机尾双类别导入与跨类合同图、\n"
               "临时储存区、条件数据处理、按类别批量 mm 缩放、多Y轴折线、平均值线、\n"
               "时间粒度聚合、描述统计、工艺分析、AI 解读、结果与图表导出。\n\n"
               "V1.11：AI 解读默认读取 ~/.codex/config.toml/环境变量的内网代理 base_url+model；\n"
               "      timeout=60s；错误信息细分；idle 显示 endpoint/model；错误不泄露 Key。")
        QMessageBox.information(self, t, txt)

    def _run_background(self, label, fn, fn_args, on_success, on_error=None):
        if self._busy: QMessageBox.information(self,"请稍候","有任务正在执行，请等待完成后再试。"); return
        self._set_busy(True, label); worker = Worker(fn, *fn_args)
        def _on_result(result):
            self._set_busy(False)
            try: on_success(result)
            except Exception as exc: self.log(f"UI刷新异常：{exc}", level="error"); self.app_logger.error("UI刷新异常", exc=exc); QMessageBox.critical(self,"错误",str(exc))
        def _on_error(msg, tb):
            self._set_busy(False)
            if on_error is not None:
                try: on_error(msg,tb)
                except Exception as exc: self.log(f"错误回调异常：{exc}", level="error")
            else: QMessageBox.critical(self,"操作失败",msg); self.log(f"{msg}\n{tb}", level="error")
        def _on_started(): self.statusBar().showMessage(label)
        worker.signals.started.connect(_on_started); worker.signals.result.connect(_on_result); worker.signals.error.connect(_on_error); worker.signals.progress.connect(self._progress_cb)
        self._threadpool.start(worker)

    def _install_excepthook(self):
        import sys
        def handler(et, ev, tb):
            self.app_logger.error("未捕获异常导致程序异常", exc=ev)
            try:
                tb_text = "".join(traceback.format_exception(et, ev, tb))
                self.log(f"[未捕获异常] {tb_text}", level="error")
            except Exception: pass
            sys.__excepthook__(et, ev, tb)
        sys.excepthook = handler

    def log(self, msg, level="info"):
        ts = __import__("datetime").datetime.now().strftime("%H:%M:%S"); line = f"[{ts}] {msg}"
        if level == "error":
            fmt = QTextCharFormat(); fmt.setForeground(QColor("#c62828"))
            self.log_panel.moveCursor(QTextCursor.MoveOperation.End)
            cur = self.log_panel.textCursor(); cur.insertText(line+"\n", fmt); self.log_panel.moveCursor(QTextCursor.MoveOperation.End)
        else:
            self.log_panel.appendPlainText(line)
        if level=="debug": self.app_logger.debug(msg)
        elif level=="warning": self.app_logger.warning(msg)
        elif level=="error": self.app_logger.error(msg)
        else: self.app_logger.info(msg)

    def _open_log_directory(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        d = self.app_logger.logs_directory().resolve()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d))); self.log(f"已打开日志目录：{d}")
