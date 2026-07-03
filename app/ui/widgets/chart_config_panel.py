from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]


class _YSeriesItem(QWidget):
    color_changed = Signal(str, str)
    toggled = Signal(str, bool)
    mean_toggled = Signal(str, bool)

    def __init__(self, column_name: str, color: str, checked: bool = True, show_mean: bool = True, parent=None):
        super().__init__(parent)
        self.column_name = column_name
        self._color = color
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.checkbox = QCheckBox(column_name)
        self.checkbox.setChecked(checked)
        self.mean_checkbox = QCheckBox("均值线")
        self.mean_checkbox.setChecked(show_mean)
        self.mean_checkbox.setToolTip("控制该Y序列是否显示平均值参考线")
        self.color_button = QPushButton()
        self.color_button.setFixedWidth(28)
        layout.addWidget(self.checkbox, stretch=1)
        layout.addWidget(self.mean_checkbox)
        layout.addWidget(self.color_button)
        self._refresh()
        self.color_button.clicked.connect(self._choose_color)
        self.checkbox.toggled.connect(lambda v: self.toggled.emit(self.column_name, v))
        self.mean_checkbox.toggled.connect(lambda v: self.mean_toggled.emit(self.column_name, v))

    def _refresh(self) -> None:
        self.color_button.setStyleSheet(f"background-color: {self._color}; border:1px solid #888; min-height:18px;")

    def _choose_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, f"选择“{self.column_name}”颜色")
        if c.isValid():
            self._color = c.name()
            self._refresh()
            self.color_changed.emit(self.column_name, self._color)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def color(self) -> str:
        return self._color

    def show_mean_line(self) -> bool:
        return self.mean_checkbox.isChecked()

    def set_show_mean_line(self, value: bool) -> None:
        self.mean_checkbox.setChecked(bool(value))


class ChartConfigPanel(QWidget):
    analysis_requested = Signal()
    chart_requested = Signal()
    reset_requested = Signal()
    series_option_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[str] = []
        self._numeric_columns: list[str] = []
        self._y_widgets: dict[str, _YSeriesItem] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        chart_group = QGroupBox("折线图配置")
        chart_layout = QVBoxLayout(chart_group)
        form = QFormLayout()
        self.x_combo = QComboBox()
        form.addRow("X 轴列：", self.x_combo)
        chart_layout.addLayout(form)

        chart_layout.addWidget(QLabel("Y 轴列（多选 + 颜色 + 均值线）："))
        self.y_list = QListWidget()
        self.y_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        chart_layout.addWidget(self.y_list)

        option_row = QHBoxLayout()
        self.show_points_check = QCheckBox("显示数据点")
        self.show_points_check.setChecked(True)
        self.show_mean_check = QCheckBox("启用均值线总开关")
        self.show_mean_check.setChecked(True)
        option_row.addWidget(self.show_points_check)
        option_row.addWidget(self.show_mean_check)
        chart_layout.addLayout(option_row)

        hint = QLabel("总开关关闭时隐藏全部均值线；开启后可在每个Y列后单独控制。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        chart_layout.addWidget(hint)

        button_row = QHBoxLayout()
        self.analyze_button = QPushButton("开始分析")
        self.chart_button = QPushButton("仅生成折线图")
        self.reset_button = QPushButton("重置")
        button_row.addWidget(self.analyze_button)
        button_row.addWidget(self.chart_button)
        button_row.addWidget(self.reset_button)
        chart_layout.addLayout(button_row)
        root.addWidget(chart_group)
        root.addStretch(1)

        self.analyze_button.clicked.connect(self.analysis_requested)
        self.chart_button.clicked.connect(self.chart_requested)
        self.reset_button.clicked.connect(self._on_reset)
        self.show_mean_check.toggled.connect(lambda _: self.series_option_changed.emit())

    def set_columns(self, columns: list[str], numeric_columns: list[str]) -> None:
        self._columns = columns
        self._numeric_columns = numeric_columns
        self.x_combo.blockSignals(True)
        self.x_combo.clear()
        self.y_list.clear()
        self._y_widgets.clear()
        for c in columns:
            self.x_combo.addItem(c)
        global_mean = self.show_mean_lines()
        for i, c in enumerate(numeric_columns):
            w = _YSeriesItem(
                c,
                DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
                checked=(i == 0),
                show_mean=global_mean,
            )
            w.toggled.connect(lambda *_: self.series_option_changed.emit())
            w.color_changed.connect(lambda *_: self.series_option_changed.emit())
            w.mean_toggled.connect(lambda *_: self.series_option_changed.emit())
            self._y_widgets[c] = w
            item = QListWidgetItem()
            item.setSizeHint(w.sizeHint())
            self.y_list.addItem(item)
            self.y_list.setItemWidget(item, w)
        self.x_combo.blockSignals(False)

    def selected_x_column(self) -> str:
        return self.x_combo.currentText()

    def selected_y_series(self) -> list[tuple[str, str, bool]]:
        return [
            (name, w.color(), bool(w.show_mean_line() and self.show_mean_check.isChecked()))
            for name, w in self._y_widgets.items()
            if w.is_checked()
        ]

    def show_points(self) -> bool:
        return self.show_points_check.isChecked()

    def show_mean_lines(self) -> bool:
        return self.show_mean_check.isChecked()

    def _on_reset(self) -> None:
        if self.x_combo.count():
            self.x_combo.setCurrentIndex(0)
        for i, w in enumerate(self._y_widgets.values()):
            w.checkbox.setChecked(i == 0)
            w.set_show_mean_line(True)
        self.show_points_check.setChecked(True)
        self.show_mean_check.setChecked(True)
        self.reset_requested.emit()
        self.series_option_changed.emit()
