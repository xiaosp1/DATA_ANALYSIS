from __future__ import annotations

import time
import traceback
import warnings
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QSettings, Qt, QThreadPool
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.services.app_logger import AppLogger
from app.services.data_processing import apply_rules
from app.services.dataset_manager import DatasetManager
from app.services.export_service import ExportError, export_plot_widget_to_png, export_stats_to_csv, export_stats_to_excel
from app.services.file_loader import FileLoadError, load_file
from app.services.stats_service import calculate_batch_stats, stats_to_dataframe
from app.services.time_aggregation import aggregate_by_time
from app.services.worker import Worker
from app.ui.widgets.chart_config_panel import ChartConfigPanel
from app.ui.widgets.chart_options_panel import ChartOptionsPanel
from app.ui.widgets.chart_panel import ChartPanel
from app.ui.widgets.data_table_panel import TablePanel
from app.ui.widgets.dataset_panel import DatasetPanel
from app.ui.widgets.processing_panel import ProcessingPanel
from app.ui.widgets.stats_panel import StatsPanel
from app.utils.timer_utils import format_duration, timed


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("本地数据分析与图表展示软件")
        self.resize(1400, 900)
        self._manager = DatasetManager()
        self.app_logger = AppLogger(Path(__file__).resolve().parents[2] / "logs")
        self._stats_df: pd.DataFrame | None = None
        # Per-dataset column-type cache: dataset_id -> {"numeric": set, "datetime": set}
        self._column_cache: dict[str, dict[str, set]] = {}
        self._busy = False
        self._progress: QProgressDialog | None = None
        self._threadpool = QThreadPool.globalInstance()
        self._settings = QSettings("DateAnalysis", "DateAnalysis")
        self._last_import_dir = self._settings.value("last_import_dir", str(Path.home()), type=str)
        self._last_export_dir = self._settings.value("last_export_dir", str(Path.home()), type=str)
        self._manager.add_listener(self._on_datasets_changed)
        self._install_excepthook()
        self._build_ui()
        self._apply_initial_state()

    # -------------------- UI --------------------

    def _build_ui(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.import_button = QPushButton("导入文件")
        self.import_folder_button = QPushButton("导入文件夹")
        self.export_stats_button = QPushButton("导出统计结果")
        self.export_chart_button = QPushButton("导出图表图片")
        self.clear_button = QPushButton("清空全部")
        self.about_button = QPushButton("关于")
        toolbar.addWidget(self.import_button)
        toolbar.addWidget(self.import_folder_button)
        toolbar.addWidget(self.export_stats_button)
        toolbar.addWidget(self.export_chart_button)
        self.open_log_dir_button = QPushButton("打开日志目录")
        toolbar.addWidget(self.open_log_dir_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addWidget(self.about_button)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        left_scroll.setMinimumWidth(380)

        left = QWidget()
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(8)

        self.dataset_panel = DatasetPanel()
        self.dataset_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.processing_panel = ProcessingPanel()
        self.processing_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.info_group = QGroupBox("当前数据集与分析列")
        self.info_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info_layout = QVBoxLayout(self.info_group)
        self.dataset_info_label = QLabel("当前未加载数据")
        self.dataset_info_label.setWordWrap(True)
        self.analysis_list = QListWidget()
        self.analysis_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        info_layout.addWidget(self.dataset_info_label)
        info_layout.addWidget(QLabel("选择统计列："))
        info_layout.addWidget(self.analysis_list)
        self.chart_options_panel = ChartOptionsPanel()
        self.chart_options_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.chart_config_panel = ChartConfigPanel()
        self.chart_config_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        left_layout.addWidget(self.dataset_panel)
        left_layout.addWidget(self.processing_panel)
        left_layout.addWidget(self.info_group)
        left_layout.addWidget(self.chart_options_panel)
        left_layout.addWidget(self.chart_config_panel)
        left_layout.addStretch(1)

        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_panel = ChartPanel()
        right_layout.addWidget(self.chart_panel, stretch=3)
        self.tabs = QTabWidget()
        self.data_panel = TablePanel()
        self.stats_panel = StatsPanel()
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.tabs.addTab(self.data_panel, "当前数据")
        self.tabs.addTab(self.stats_panel, "统计结果")
        self.tabs.addTab(self.log_panel, "日志/提示")
        right_layout.addWidget(self.tabs, stretch=2)
        self.preview_label = QLabel("数据表预览前1000行；统计与绘图基于当前激活数据集的全量有效数据。大文件自动降采样绘图以保证流畅。")
        self.preview_label.setStyleSheet("color:#666; padding:4px 6px;")
        right_layout.addWidget(self.preview_label)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 1000])

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

        self.import_button.clicked.connect(self._import_files)
        self.import_folder_button.clicked.connect(self._import_folder)
        self.export_stats_button.clicked.connect(self._export_stats)
        self.export_chart_button.clicked.connect(self._export_chart_image)
        self.open_log_dir_button.clicked.connect(self._open_log_directory)
        self.clear_button.clicked.connect(self._clear_all)
        self.about_button.clicked.connect(self._show_about)
        self.dataset_panel.import_requested.connect(self._import_files)
        self.dataset_panel.activate_requested.connect(self._activate_dataset)
        self.dataset_panel.delete_requested.connect(self._delete_dataset)
        self.dataset_panel.export_requested.connect(self._export_dataset)
        self.dataset_panel.merge_requested.connect(self._merge_datasets)
        self.processing_panel.apply_requested.connect(self._apply_processing)
        self.chart_config_panel.analysis_requested.connect(self._run_analysis)
        self.chart_config_panel.chart_requested.connect(self._run_chart_only)
        self.chart_config_panel.reset_requested.connect(lambda: self.log("已重置图表配置。"))
        self.chart_options_panel.granularity_combo.currentIndexChanged.connect(lambda _: self._refresh_chart_if_any())
        self.chart_config_panel.show_points_check.toggled.connect(lambda _: self._refresh_chart_if_any())
        self.chart_config_panel.show_mean_check.toggled.connect(lambda _: self._refresh_chart_if_any())
        self.chart_config_panel.series_option_changed.connect(self._refresh_chart_if_any)


    # -------------------- helpers --------------------

    def _set_busy(self, busy: bool, label: str = "处理中...") -> None:
        self._busy = busy
        if busy:
            if self._progress is None:
                self._progress = QProgressDialog(label, "取消", 0, 0, self)
                self._progress.setWindowTitle("请稍候")
                self._progress.setWindowModality(Qt.WindowModality.WindowModal)
                self._progress.setMinimumDuration(300)
                self._progress.setCancelButton(None)
                self._progress.setAutoClose(True)
                self._progress.setAutoReset(True)
            else:
                self._progress.setLabelText(label)
            self._progress.setValue(0)
            self._progress.show()
            self.statusBar().showMessage(label)
        else:
            if self._progress is not None:
                self._progress.close()
                self._progress = None
            self.statusBar().showMessage("就绪")

    def _progress_cb(self, pct: int, msg: str = "") -> None:
        if self._progress is None:
            return
        self._progress.setValue(max(0, min(100, int(pct))))
        if msg:
            try:
                self._progress.setLabelText(msg)
            except RuntimeError:
                self._progress = None
                return
            self.statusBar().showMessage(msg)

    def _cache_columns_for(self, item) -> dict[str, set]:
        """Identify numeric/datetime columns once per dataset and cache."""
        if item is None:
            return {"numeric": set(), "datetime": set()}
        cache = self._column_cache.get(item.dataset_id)
        if cache is not None:
            return cache
        df = item.df
        numeric = set()
        dt_cols = set()
        for c in df.columns:
            cname = str(c)
            s = df[c]
            if pd.api.types.is_numeric_dtype(s):
                numeric.add(cname)
            if pd.api.types.is_datetime64_any_dtype(s):
                dt_cols.add(cname)
            else:
                # Lightweight heuristic: if column name hints datetime or >=80% parseable
                non_null = s.dropna()
                name_hint = any(k in cname.lower() for k in ["date", "time", "日期", "时间"])
                if not non_null.empty and (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)):
                    sample_n = min(200, len(non_null))
                    sample = non_null.head(sample_n)
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        converted = pd.to_datetime(sample, errors="coerce")
                    ratio = converted.notna().sum() / max(1, len(sample))
                    if ratio >= 0.8 or (name_hint and ratio >= 0.6):
                        dt_cols.add(cname)
        cache = {"numeric": numeric, "datetime": dt_cols}
        self._column_cache[item.dataset_id] = cache
        return cache

    def _invalidate_cache(self, dataset_id: str | None = None) -> None:
        if dataset_id is None:
            self._column_cache.clear()
        else:
            self._column_cache.pop(dataset_id, None)

    def _apply_initial_state(self):
        self.data_panel.set_dataframe(pd.DataFrame({"提示": ["请先导入CSV/XLSX文件"]}))
        self.stats_panel.set_dataframe(pd.DataFrame({"提示": ["完成分析后，这里展示统计结果"]}))
        self.chart_panel.clear()
        self._stats_df = None
        self._refresh_dataset_ui()
        self.log("欢迎使用。支持多文件导入、临时储存区、条件数据处理、时间粒度聚合。耗时记录会输出到日志。")

    def _on_datasets_changed(self):
        self._refresh_dataset_ui()

    def _refresh_dataset_ui(self):
        items = self._manager.items()
        active = self._manager.active_item()
        self.dataset_panel.refresh(items, self._manager.active_id())
        if active is None:
            self.dataset_info_label.setText("当前未加载数据")
            self.analysis_list.clear()
            self.chart_config_panel.set_columns([], [])
            self.processing_panel.set_columns([], [])
            return
        df = active.df
        cache = self._cache_columns_for(active)
        numeric_cols = sorted(cache["numeric"], key=lambda c: list(df.columns).index(c) if c in df.columns else 999)
        self.dataset_info_label.setText(
            f"当前数据集：[{self._kind(active.kind)}] {active.name}\n行数：{len(df)}，列数：{len(df.columns)}"
        )
        self.analysis_list.clear()
        for col in df.columns:
            self.analysis_list.addItem(QListWidgetItem(str(col)))
        self.chart_config_panel.set_columns([str(c) for c in df.columns], numeric_cols)
        self.processing_panel.set_columns([str(c) for c in df.columns], numeric_cols)

    def _kind(self, kind):
        return {"original": "原始", "processed": "临时", "merged": "合并"}.get(kind, kind)


    # -------------------- import (background) --------------------

    _SUPPORTED_TABLE_EXTS = {".csv", ".xlsx", ".xls"}

    def _import_folder(self):
        start_dir = self._last_import_dir or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹（递归导入所有表格）", start_dir)
        if not folder:
            return
        self._last_import_dir = folder
        self._settings.setValue("last_import_dir", self._last_import_dir)
        folder_path = Path(folder)
        paths = sorted(
            str(pp) for pp in folder_path.rglob("*")
            if pp.is_file() and pp.suffix.lower() in self._SUPPORTED_TABLE_EXTS
        )
        if not paths:
            QMessageBox.information(self, "提示", f"文件夹“{folder_path.name}”及子目录中未找到 csv/xlsx/xls 文件。")
            return
        self.log(f"开始导入文件夹：{folder_path}，共发现 {len(paths)} 个表格文件。")
        self._run_background(
            label=f"正在导入文件夹（0/{len(paths)}）...",
            fn=self._worker_import,
            fn_args=(paths,),
            on_success=self._on_import_done,
            on_error=self._on_import_error,
        )

    def _import_files(self):
        start_dir = self._last_import_dir or str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择表格文件", start_dir,
            "表格文件 (*.csv *.xlsx *.xls);;所有文件 (*.*)")
        if not paths:
            return
        self._last_import_dir = str(Path(paths[0]).parent)
        self._settings.setValue("last_import_dir", self._last_import_dir)
        self._run_background(
            label="正在导入文件...",
            fn=self._worker_import,
            fn_args=(paths,),
            on_success=self._on_import_done,
            on_error=self._on_import_error,
        )

    def _worker_import(self, paths, report_progress=None):
        imported = []
        errors = []
        total = len(paths)
        for i, pth in enumerate(paths, start=1):
            name = Path(pth).name
            if report_progress:
                report_progress(int(i / total * 100), f"读取中 ({i}/{total})：{name}")
            try:
                dataset = load_file(pth, has_header=True)
                imported.append(dataset)
            except FileLoadError as exc:
                errors.append((name, str(exc)))
            except Exception as exc:  # noqa: BLE001
                errors.append((name, f"未知错误：{exc}"))
        return {"imported": imported, "errors": errors}

    def _on_import_done(self, result):
        import time as _t
        imported = result["imported"]
        errors = result["errors"]
        t0 = _t.perf_counter()
        for dataset in imported:
            self._manager.import_file(dataset.file_name, dataset.file_path, dataset.df)
            self.log(f"导入成功：{dataset.file_name}，{dataset.row_count}行 {dataset.column_count}列。")
        for item in errors:
            name, msg = item if isinstance(item, tuple) and len(item) == 2 else (str(item), "未知错误")
            QMessageBox.warning(self, "导入失败", f"{name}: {msg}")
            self.log(f"导入失败：{name} - {msg}", level="error")
        self.log(f"[耗时] 导入并落库 {len(imported)} 个文件：{(_t.perf_counter()-t0)*1000:.1f} ms")
        if imported:
            active = self._manager.active_item()
            if active is not None:
                self.data_panel.set_dataframe(active.df)
                self.chart_panel.clear()
                self._stats_df = None
                self.stats_panel.set_dataframe(pd.DataFrame(columns=[
                    "列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
                self.statusBar().showMessage(f"已导入 {len(imported)} 个文件")

    def _on_import_error(self, msg, tb):
        QMessageBox.critical(self, "导入失败", msg)
        self.log(f"导入失败：{msg}\n{tb}", level="error")

    # -------------------- dataset ops --------------------

    def _activate_dataset(self, dataset_id):
        def do_activate(report_progress=None):
            if report_progress:
                report_progress(30, "准备数据集预览...")
            t0 = time.perf_counter()
            item = self._manager.get(dataset_id)
            self._cache_columns_for(item)
            return {"item": item, "elapsed": time.perf_counter() - t0}

        def on_success(result):
            if result is None:
                return
            item = result["item"]
            self._manager.set_active(item.dataset_id)
            with timed("切换并刷新UI", self.log):
                self.data_panel.set_dataframe(item.df)
                self.chart_panel.clear()
                self._stats_df = None
                self.stats_panel.set_dataframe(pd.DataFrame(columns=[
                    "列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
            self.log(f"已切换到数据集：{item.name}（切换耗时 {format_duration(result['elapsed'])}）")
            self.statusBar().showMessage(f"当前数据集：{item.name}")

        def on_error(msg, tb):
            self.log(str(msg), level="warning")
            QMessageBox.warning(self, "提示", str(msg))

        self._run_background("切换数据集...", do_activate, (), on_success, on_error)

    def _delete_dataset(self, dataset_id):
        try:
            item = self._manager.get(dataset_id)
        except KeyError:
            return
        if not item.can_delete:
            self.log("尝试删除原始数据被拦截。", level="warning")
            QMessageBox.information(self, "提示", "原始导入数据不可删除。")
            return
        try:
            self._invalidate_cache(dataset_id)
            self._manager.remove(dataset_id)
            self.log(f"已删除临时数据集：{item.name}")
        except Exception as exc:
            QMessageBox.warning(self, "删除失败", str(exc))

    def _export_dataset(self, dataset_id):
        try:
            item = self._manager.get(dataset_id)
        except KeyError:
            return
        start_dir = str(Path(self._last_export_dir) / item.name)
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出数据集", start_dir,
            "CSV 文件 (*.csv);;Excel 文件 (*.xlsx)")
        if not file_path:
            return
        self._last_export_dir = str(Path(file_path).parent)
        self._settings.setValue("last_export_dir", self._last_export_dir)
        try:
            with timed(f"导出数据集 {item.name}", self.log):
                if selected_filter.startswith("Excel") or file_path.lower().endswith(".xlsx"):
                    if not file_path.lower().endswith(".xlsx"):
                        file_path += ".xlsx"
                    export_stats_to_excel(item.df, file_path)
                else:
                    if not file_path.lower().endswith(".csv"):
                        file_path += ".csv"
                    export_stats_to_csv(item.df, file_path)
            self.log(f"数据集已导出：{file_path}")
            self.statusBar().showMessage(f"数据集已导出：{Path(file_path).name}")
        except ExportError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            self.log(f"导出失败：{exc}", level="error")


    # -------------------- merge --------------------

    def _merge_datasets(self, dataset_ids):
        active = self._manager.active_item()
        if active is None:
            QMessageBox.warning(self, "提示", "请先导入至少一个数据集。")
            return
        # Determine time column (prefer cached datetime columns).
        time_col = None
        cache = self._cache_columns_for(active)
        dt_cols = [c for c in cache["datetime"]]
        if dt_cols:
            time_col = dt_cols[0]
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for c in active.df.columns:
                    s = active.df[c]
                    if pd.api.types.is_datetime64_any_dtype(s):
                        time_col = str(c); break
                    if (s.dtype == object and pd.to_datetime(s, errors="coerce").notna().mean() >= 0.8):
                        time_col = str(c); break
        if time_col is None:
            from PySide6.QtWidgets import QInputDialog
            items = [str(c) for c in active.df.columns]
            time_col, ok = QInputDialog.getItem(self, "选择合并时间列", "按哪一列合并排序：", items, 0, False)
            if not ok:
                return

        def do_merge(report_progress=None):
            """Compute merged DataFrame in worker; don't touch DatasetManager here."""
            import pandas as pd
            from app.services.data_processor import infer_datetime_series
            if report_progress:
                report_progress(20, "读取并对齐数据集...")
            t0 = time.perf_counter()
            frames = []
            sources = []
            tcol = str(time_col)
            for did in dataset_ids:
                item = self._manager.get(did)
                if tcol not in item.df.columns:
                    raise ValueError(f"数据集“{item.name}”缺少时间列：{tcol}")
                work = item.df.copy()
                work[tcol] = infer_datetime_series(work[tcol])
                work = work.dropna(subset=[tcol])
                frames.append(work)
                sources.extend(item.source_files)
                if report_progress:
                    report_progress(40, f"已读取 {len(sources)} 个文件源...")
            if report_progress:
                report_progress(70, "拼接并按时间排序...")
            merged_df = pd.concat(frames, ignore_index=True, sort=False)
            merged_df = merged_df.sort_values(by=tcol, kind="mergesort").reset_index(drop=True)
            return {"df": merged_df, "time_col": tcol, "sources": sources,
                    "elapsed": time.perf_counter() - t0}

        def on_success(result):
            from datetime import datetime as _dt
            name = f"合并结果_{_dt.now().strftime('%H%M%S')}"
            item = self._manager.add_temporary(name, result["df"], kind="merged",
                                               source_files=result["sources"],
                                               metadata={"time_column": result["time_col"]})
            self._invalidate_cache(item.dataset_id)
            self._manager.set_active(item.dataset_id)
            self._cache_columns_for(item)
            self.data_panel.set_dataframe(item.df)
            self.chart_panel.clear()
            self._stats_df = None
            self.stats_panel.set_dataframe(pd.DataFrame(columns=[
                "列名","有效计数","缺失值","最大值","最小值","平均值","中位数","求和","方差","标准差","极差"]))
            self.log(f"已生成合并数据集：{item.name}，按时间列“{result['time_col']}”排序（合并耗时 {format_duration(result['elapsed'])}）。")
            self.statusBar().showMessage(f"已切换到合并数据集：{item.name}")

        self._run_background("正在合并数据集...", do_merge, (), on_success,
                             on_error=lambda m, tb: (QMessageBox.warning(self, "合并失败", m), self.log(f"合并失败：{m}", level="error")))

    # -------------------- processing --------------------

    def _apply_processing(self, rules):
        active = self._manager.active_item()
        if active is None:
            QMessageBox.warning(self, "提示", "请先导入并激活数据集。")
            return
        new_name = f"{active.name}_处理结果"
        rules_snapshot = list(rules)

        def do_process(report_progress=None):
            t0 = time.perf_counter()
            if report_progress:
                report_progress(20, "执行处理规则...")
            processed_df, logs = apply_rules(active.df.copy(), rules_snapshot)
            return {"df": processed_df, "logs": logs,
                    "source_files": list(active.source_files),
                    "from_id": active.dataset_id,
                    "elapsed": time.perf_counter() - t0}

        def on_success(result):
            item = self._manager.add_temporary(
                new_name, result["df"], kind="processed",
                source_files=result["source_files"],
                metadata={"from": result["from_id"]})
            self._invalidate_cache(item.dataset_id)
            self._manager.set_active(item.dataset_id)
            self._cache_columns_for(item)
            self.data_panel.set_dataframe(item.df)
            self.chart_panel.clear()
            self._stats_df = None
            for m in result["logs"]:
                self.log(m)
            self.log(f"已生成临时处理数据集：{item.name}（处理耗时 {format_duration(result['elapsed'])}）")
            self.statusBar().showMessage(f"数据处理完成：{item.name}")

        def on_error(msg, tb):
            QMessageBox.critical(self, "处理失败", msg)
            self.log(f"数据处理失败：{msg}\n{tb}", level="error")

        self._run_background("正在处理数据...", do_process, (), on_success, on_error)

    # -------------------- columns --------------------

    def _selected_analysis_columns(self):
        return [item.text() for item in self.analysis_list.selectedItems()]


    # -------------------- analysis + chart --------------------

    def _run_analysis(self):
        active = self._manager.active_item()
        if active is None:
            QMessageBox.warning(self, "提示", "请先导入数据。")
            return
        selected_cols = self._selected_analysis_columns()
        if not selected_cols:
            QMessageBox.warning(self, "提示", "请在当前数据集信息区域选择至少一个统计列。")
            return
        y_series = self.chart_config_panel.selected_y_series()
        x_col = self.chart_config_panel.selected_x_column()
        granularity = self.chart_options_panel.current_granularity()
        cache = self._cache_columns_for(active)
        numeric_cols = cache["numeric"]
        stats_cols = [c for c in selected_cols if c in numeric_cols]
        for c in selected_cols:
            if c not in numeric_cols:
                self.log(f"列“{c}”不是数值列，统计已跳过。", level="warning")
        if not stats_cols and not y_series:
            QMessageBox.warning(self, "提示", "所选列中无可统计数值列且未勾选Y轴。")
            return

        def do_work(report_progress=None):
            t0 = time.perf_counter()
            if report_progress:
                report_progress(10, "计算统计量...")
            results = calculate_batch_stats(active.df, stats_cols) if stats_cols else []
            stats_df = stats_to_dataframe(results) if results else None
            if report_progress:
                report_progress(60, "准备图表数据...")
            chart_result = self._prepare_chart_data(active.df, x_col, y_series, granularity, cache)
            return {
                "stats_df": stats_df,
                "stats_cols": stats_cols,
                "chart": chart_result,
                "y_series": y_series,
                "x_col": x_col,
                "elapsed": time.perf_counter() - t0,
            }

        def on_success(result):
            if result["stats_df"] is not None:
                self._stats_df = result["stats_df"]
                self.stats_panel.set_dataframe(self._stats_df)
                self.tabs.setCurrentWidget(self.stats_panel)
                self.log(f"统计完成，共 {len(result['stats_cols'])} 列。")
            else:
                self.log("未选择数值统计列，跳过统计。", level="warning")
            chart = result["chart"]
            if chart is not None and result["y_series"]:
                self._render_chart(chart, result["x_col"], result["y_series"])
                self.tabs.setCurrentWidget(self.data_panel)
            else:
                self.log("未勾选Y轴列，已跳过绘图。")
            self.log(f"分析总耗时：{format_duration(result['elapsed'])}")

        def on_error(msg, tb):
            QMessageBox.critical(self, "分析失败", msg)
            self.log(f"分析失败：{msg}\n{tb}", level="error")

        self._run_background("正在分析...", do_work, (), on_success, on_error)

    def _run_chart_only(self):
        if self._manager.active_item() is None:
            QMessageBox.warning(self, "提示", "请先导入数据。")
            return
        y_series = self.chart_config_panel.selected_y_series()
        if not y_series:
            QMessageBox.warning(self, "提示", "请至少勾选一个Y轴列。")
            return
        x_col = self.chart_config_panel.selected_x_column()
        granularity = self.chart_options_panel.current_granularity()
        active = self._manager.active_item()
        cache = self._cache_columns_for(active)

        def do_work(report_progress=None):
            t0 = time.perf_counter()
            if report_progress:
                report_progress(20, "准备图表数据...")
            chart = self._prepare_chart_data(active.df, x_col, y_series, granularity, cache)
            return {"chart": chart, "x_col": x_col, "y_series": y_series,
                    "elapsed": time.perf_counter() - t0}

        def on_success(result):
            if result["chart"] is None:
                return
            self._render_chart(result["chart"], result["x_col"], result["y_series"])
            self.tabs.setCurrentWidget(self.data_panel)
            self.log(f"绘图完成，耗时 {format_duration(result['elapsed'])}")

        def on_error(msg, tb):
            QMessageBox.critical(self, "绘图失败", msg)
            self.log(f"绘图失败：{msg}\n{tb}", level="error")

        self._run_background("正在绘图...", do_work, (), on_success, on_error)

    def _refresh_chart_if_any(self):
        if self.chart_panel.plot_widget.plotItem.listDataItems():
            self._run_chart_only()


    def _prepare_chart_data(self, df, x_col, y_series, granularity, cache):
        """Heavy prep done in worker thread. Returns dict or None."""
        if not x_col or not y_series:
            return None
        y_cols = [n for n, *_ in y_series]
        numeric_set = cache["numeric"]
        bad = [c for c in y_cols if c not in numeric_set]
        if bad:
            raise ValueError(f"Y列必须为数值列：{', '.join(bad)}")

        use_time = x_col in cache["datetime"]
        # If not cached as datetime but column is object/string, do a best-effort check.
        if not use_time and x_col in df.columns:
            s = df[x_col]
            if not pd.api.types.is_numeric_dtype(s):
                non_null = s.dropna()
                if len(non_null) > 0:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        converted = pd.to_datetime(non_null, errors="coerce")
                    if converted.notna().sum() / len(non_null) >= 0.8:
                        use_time = True
                        cache["datetime"].add(x_col)

        chart_df = df[[x_col] + y_cols].copy()
        mean_map: dict[str, float] = {}
        messages: list[str] = []
        x_is_datetime = False

        if use_time:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                chart_df[x_col] = pd.to_datetime(chart_df[x_col], errors="coerce")
            chart_df = chart_df.dropna(subset=[x_col])
            for c in y_cols:
                chart_df[c] = pd.to_numeric(chart_df[c], errors="coerce")
                mean_map[c] = float(pd.to_numeric(df[c], errors="coerce").mean())
            if granularity != "原始":
                agg_df, agg_msgs, x_is_dt, _ = aggregate_by_time(df, x_col, y_cols, granularity)
                messages.extend(agg_msgs)
                chart_df = agg_df
                x_is_datetime = x_is_dt
                for c2 in y_cols:
                    if c2 in chart_df.columns:
                        mean_map[c2] = float(pd.to_numeric(chart_df[c2], errors="coerce").mean())
            else:
                chart_df = chart_df.sort_values(x_col)
                x_is_datetime = True
                messages.append("X轴按日期时间原始顺序展示。")
        else:
            for c in y_cols:
                chart_df[c] = pd.to_numeric(chart_df[c], errors="coerce")
                series_mean = chart_df[c].mean()
                mean_map[c] = float(series_mean) if pd.notna(series_mean) else 0.0
            messages.append("X轴非时间列，时间粒度设置已忽略。")

        return {
            "chart_df": chart_df,
            "mean_map": mean_map,
            "messages": messages,
            "x_is_datetime": x_is_datetime if use_time else False,
            "use_time": use_time,
        }

    def _render_chart(self, prepared: dict, x_col: str, y_series):
        """Runs on UI thread."""
        chart_df = prepared["chart_df"]
        mean_map = prepared["mean_map"]
        messages = prepared["messages"]
        x_is_datetime = prepared["x_is_datetime"]
        granularity = self.chart_options_panel.current_granularity()
        title = f"{x_col} - 多列趋势图" if len(y_series) > 1 else f"{x_col} - {y_series[0][0]} 趋势图"
        with timed("图表渲染", self.log):
            plot_msgs = self.chart_panel.plot_multi_line(
                chart_df, x_col, y_series, mean_map=mean_map,
                title=title,
                show_points=self.chart_config_panel.show_points(),
                show_mean_lines=self.chart_config_panel.show_mean_lines(),
                x_is_datetime=x_is_datetime,
                granularity=granularity if x_is_datetime else "原始",
            )
        messages.extend(plot_msgs)
        for m in messages:
            self.log(m)
        self.statusBar().showMessage("图表已生成")

    # -------------------- export / misc --------------------

    def _export_stats(self):
        if self._stats_df is None or self._stats_df.empty:
            QMessageBox.warning(self, "提示", "当前没有可导出的统计结果，请先完成分析。")
            return
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出统计结果", str(Path.home() / "stats_result"),
            "CSV 文件 (*.csv);;Excel 文件 (*.xlsx)")
        if not file_path:
            return
        try:
            with timed("导出统计结果", self.log):
                if selected_filter.startswith("Excel") or file_path.lower().endswith(".xlsx"):
                    if not file_path.lower().endswith(".xlsx"):
                        file_path += ".xlsx"
                    export_stats_to_excel(self._stats_df, file_path)
                else:
                    if not file_path.lower().endswith(".csv"):
                        file_path += ".csv"
                    export_stats_to_csv(self._stats_df, file_path)
            self.log(f"统计结果已导出：{file_path}")
            self.statusBar().showMessage(f"统计结果已导出：{Path(file_path).name}")
        except ExportError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            self.log(f"导出失败：{exc}", level="error")

    def _export_chart_image(self):
        if not self.chart_panel.plot_widget.plotItem.listDataItems():
            QMessageBox.warning(self, "提示", "当前没有可导出的图表，请先生成折线图。")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出图表图片", str(Path.home() / "chart.png"), "PNG 图片 (*.png)")
        if not file_path:
            return
        if not file_path.lower().endswith(".png"):
            file_path += ".png"
        try:
            with timed("导出图表图片", self.log):
                export_plot_widget_to_png(self.chart_panel.plot_widget, file_path)
            self.log(f"图表已导出：{file_path}")
            self.statusBar().showMessage(f"图表已导出：{Path(file_path).name}")
        except ExportError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            self.log(f"图表导出失败：{exc}", level="error")

    def _clear_all(self):
        self._manager.clear()
        self._stats_df = None
        self.chart_panel.clear()
        self._invalidate_cache()
        self._apply_initial_state()
        self.processing_panel._clear_rules()
        self.log("已清空全部数据与临时储存区。")
        self.statusBar().showMessage("已清空")

    def _show_about(self):
        QMessageBox.information(
            self, "关于",
            "本地数据分析与图表展示软件\n\n"
            "支持多文件导入、临时储存区、条件数据处理、多Y轴折线、平均值线、时间粒度聚合、"
            "结果与图表导出。\n"
            "V1.3: X轴自动时间刻度 + 数据点悬停提示。\n"
            "V1.4: 耗时日志、后台线程计算、进度反馈、绘图自动降采样。")


    # -------------------- background worker plumbing --------------------

    def _run_background(self, label: str, fn, fn_args, on_success, on_error=None):
        if self._busy:
            QMessageBox.information(self, "请稍候", "有任务正在执行，请等待完成后再试。")
            return
        self._set_busy(True, label)
        worker = Worker(fn, *fn_args)

        def _on_result(result):
            self._set_busy(False)
            try:
                on_success(result)
            except Exception as exc:
                self.log(f"UI刷新异常：{exc}", level="error")
                self.app_logger.error("UI刷新异常", exc=exc)
                QMessageBox.critical(self, "错误", str(exc))

        def _on_error(msg, tb):
            self._set_busy(False)
            if on_error is not None:
                try:
                    on_error(msg, tb)
                except Exception as exc:
                    self.log(f"错误回调异常：{exc}", level="error")
            else:
                QMessageBox.critical(self, "操作失败", msg)
                self.log(f"{msg}\n{tb}", level="error")

        def _on_started():
            self.statusBar().showMessage(label)

        worker.signals.started.connect(_on_started)
        worker.signals.result.connect(_on_result)
        worker.signals.error.connect(_on_error)
        worker.signals.progress.connect(self._progress_cb)
        self._threadpool.start(worker)

    # -------------------- logging / hooks --------------------

    def _install_excepthook(self):
        import sys

        def handler(exc_type, exc_value, exc_tb):
            msg = "未捕获异常导致程序异常"
            self.app_logger.error(msg, exc=exc_value)
            try:
                tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                self.log(f"[未捕获异常] {tb_text}", level="error")
            except Exception:
                pass
            sys.__excepthook__(exc_type, exc_value, exc_tb)

        sys.excepthook = handler

    def log(self, msg: str, level: str = "info"):
        ts = __import__("datetime").datetime.now().strftime("%H:%M:%S")
        self.log_panel.appendPlainText(f"[{ts}] {msg}")
        if level == "debug":
            self.app_logger.debug(msg)
        elif level == "warning":
            self.app_logger.warning(msg)
        elif level == "error":
            self.app_logger.error(msg)
        else:
            self.app_logger.info(msg)

    def _open_log_directory(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        log_dir = self.app_logger.logs_directory().resolve()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
        self.log(f"已打开日志目录：{log_dir}")
