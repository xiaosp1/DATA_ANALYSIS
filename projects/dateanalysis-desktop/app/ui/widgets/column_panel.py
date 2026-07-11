from __future__ import annotations

from PySide6.QtCore import Signal, Qt
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

    def __init__(self, column_name: str, color: str, checked: bool = True, parent=None):
        super().__init__(parent)
        self.column_name = column_name
        self._color = color
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.checkbox = QCheckBox(column_name)
        self.checkbox.setChecked(checked)
        self.color_button = QPushButton()
        self.color_button.setFixedWidth(32)
        self.color_button.setToolTip("点击修改该序列颜色")
        layout.addWidget(self.checkbox, stretch=1)
        layout.addWidget(self.color_button)

        self._refresh_color_button()
        self.color_button.clicked.connect(self._choose_color)
        self.checkbox.toggled.connect(self._on_toggled)

    def _refresh_color_button(self) -> None:
        self.color_button.setStyleSheet(
            f"background-color: {self._color}; border: 1px solid #888; min-height: 18px;"
        )

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, f"选择“{self.column_name}”颜色")
        if color.isValid():
            self._color = color.name()
            self._refresh_color_button()
            self.color_changed.emit(self.column_name, self._color)

    def _on_toggled(self, checked: bool) -> None:
        self.toggled.emit(self.column_name, checked)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def color(self) -> str:
        return self._color


class ColumnPanel(QWidget):
    analysis_requested = Signal()
    chart_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[str] = []
        self._numeric_columns: list[str] = []
        self._y_widgets: dict[str, _YSeriesItem] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        file_group = QGroupBox("文件信息")
        file_form = QFormLayout(file_group)
        self.file_name_label = QLabel("未导入文件")
        self.row_col_label = QLabel("-")
        file_form.addRow("文件：", self.file_name_label)
        file_form.addRow("行列：", self.row_col_label)
        root.addWidget(file_group)

        column_group = QGroupBox("分析列选择（统计）")
        column_layout = QVBoxLayout(column_group)
        self.column_list = QListWidget()
        self.column_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        column_layout.addWidget(self.column_list)
        root.addWidget(column_group)

        chart_group = QGroupBox("折线图配置")
        chart_layout = QVBoxLayout(chart_group)
        chart_form = QFormLayout()
        self.x_combo = QComboBox()
        chart_form.addRow("X 轴列：", self.x_combo)
        chart_layout.addLayout(chart_form)

        chart_layout.addWidget(QLabel("Y 轴列（可多选，可改颜色）："))
        self.y_list = QListWidget()
        self.y_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        chart_layout.addWidget(self.y_list)

        option_row = QHBoxLayout()
        self.show_points_check = QCheckBox("显示数据点")
        self.show_points_check.setChecked(True)
        self.show_mean_check = QCheckBox("显示平均值线")
        self.show_mean_check.setChecked(True)
        option_row.addWidget(self.show_points_check)
        option_row.addWidget(self.show_mean_check)
        chart_layout.addLayout(option_row)

        root.addWidget(chart_group)

        button_row = QHBoxLayout()
        self.analyze_button = QPushButton("开始分析")
        self.chart_button = QPushButton("仅生成折线图")
        self.reset_button = QPushButton("重置选择")
        button_row.addWidget(self.analyze_button)
        button_row.addWidget(self.chart_button)
        button_row.addWidget(self.reset_button)
        root.addLayout(button_row)

        root.addStretch(1)

        self.analyze_button.clicked.connect(self.analysis_requested)
        self.chart_button.clicked.connect(self.chart_requested)
        self.reset_button.clicked.connect(self._on_reset)

    def set_columns(self, columns: list[str], numeric_columns: list[str]) -> None:
        self._columns = columns
        self._numeric_columns = numeric_columns
        self.column_list.clear()
        self.y_list.clear()
        self._y_widgets.clear()
        self.x_combo.blockSignals(True)
        self.x_combo.clear()

        for col in columns:
            item = QListWidgetItem(col)
            self.column_list.addItem(item)
            self.x_combo.addItem(col)

        for index, col in enumerate(numeric_columns):
            color = DEFAULT_COLORS[index % len(DEFAULT_COLORS)]
            widget = _YSeriesItem(col, color, checked=(index == 0))
            widget.color_changed.connect(self._on_y_color_changed)
            widget.toggled.connect(self._on_y_toggled)
            self._y_widgets[col] = widget
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.y_list.addItem(item)
            self.y_list.setItemWidget(item, widget)

        if self.x_combo.count() > 0:
            self.x_combo.setCurrentIndex(0)

        self.x_combo.blockSignals(False)

    def _on_y_color_changed(self, column_name: str, color: str) -> None:
        pass

    def _on_y_toggled(self, column_name: str, checked: bool) -> None:
        pass

    def set_file_info(self, file_name: str, row_count: int, col_count: int) -> None:
        self.file_name_label.setText(file_name)
        self.row_col_label.setText(f"{row_count} 行 × {col_count} 列")

    def clear_file_info(self) -> None:
        self.file_name_label.setText("未导入文件")
        self.row_col_label.setText("-")

    def selected_analysis_columns(self) -> list[str]:
        return [item.text() for item in self.column_list.selectedItems()]

    def selected_x_column(self) -> str:
        return self.x_combo.currentText()

    def selected_y_series(self) -> list[tuple[str, str]]:
        result = []
        for name, widget in self._y_widgets.items():
            if widget.is_checked():
                result.append((name, widget.color()))
        return result

    def show_points(self) -> bool:
        return self.show_points_check.isChecked()

    def show_mean_lines(self) -> bool:
        return self.show_mean_check.isChecked()

    def _on_reset(self) -> None:
        self.column_list.clearSelection()
        if self.x_combo.count() > 0:
            self.x_combo.setCurrentIndex(0)
        for index, widget in enumerate(self._y_widgets.values()):
            widget.checkbox.setChecked(index == 0)
        self.show_points_check.setChecked(True)
        self.show_mean_check.setChecked(True)
        self.reset_requested.emit()
