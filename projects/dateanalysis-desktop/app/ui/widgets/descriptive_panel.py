# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class DescriptivePanel(QWidget):
    run_requested = Signal(dict)  # emits config dict

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[str] = []
        self._numeric_columns: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        sel_group = QGroupBox("待分析数值列")
        sel_layout = QVBoxLayout(sel_group)
        self.col_list = QListWidget()
        self.col_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        sel_layout.addWidget(self.col_list)

        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("全选数值列")
        self.clear_sel_btn = QPushButton("清空选择")
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.clear_sel_btn)
        sel_layout.addLayout(btn_row)
        root.addWidget(sel_group)

        opt_group = QGroupBox("图表选项")
        form = QFormLayout(opt_group)

        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(5, 200)
        self.bins_spin.setValue(30)
        form.addRow("直方图 bins：", self.bins_spin)

        self.kde_check = QCheckBox("叠加 KDE 密度曲线")
        self.kde_check.setChecked(True)
        form.addRow("", self.kde_check)

        self.mean_check = QCheckBox("显示均值参考线")
        self.mean_check.setChecked(True)
        form.addRow("", self.mean_check)

        self.median_check = QCheckBox("显示中位数参考线")
        self.median_check.setChecked(True)
        form.addRow("", self.median_check)

        self.iqr_k_spin = QDoubleSpinBox()
        self.iqr_k_spin.setRange(0.5, 5.0)
        self.iqr_k_spin.setSingleStep(0.25)
        self.iqr_k_spin.setValue(1.5)
        form.addRow("箱线图/IQR 系数 k：", self.iqr_k_spin)

        self.corr_combo = QComboBox()
        self.corr_combo.addItem("Pearson", "pearson")
        self.corr_combo.addItem("Spearman", "spearman")
        form.addRow("相关系数方法：", self.corr_combo)

        self.scatter_check = QCheckBox("生成散点图矩阵（列数过多会较慢）")
        self.scatter_check.setChecked(False)
        form.addRow("", self.scatter_check)

        self.qq_check = QCheckBox("生成 Q-Q 图（正态性检验）")
        self.qq_check.setChecked(True)
        form.addRow("", self.qq_check)

        root.addWidget(opt_group)

        self.run_button = QPushButton("开始描述统计分析")
        self.run_button.setStyleSheet("font-weight:bold; padding:6px 8px;")
        root.addWidget(self.run_button)

        self.hint = QLabel("提示：直方图/箱线图/Q-Q/相关矩阵/散点矩阵 均仅对数值列计算；非数值列会在缺失统计中标记无效。")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#666;")
        root.addWidget(self.hint)
        root.addStretch(1)

        self.select_all_btn.clicked.connect(self._select_all)
        self.clear_sel_btn.clicked.connect(self._clear_selection)
        self.run_button.clicked.connect(self._emit_run)

    def set_columns(self, columns: list[str], numeric_columns: list[str]) -> None:
        self._columns = list(columns)
        self._numeric_columns = list(numeric_columns)
        self.col_list.clear()
        for i, c in enumerate(columns):
            item = QListWidgetItem(c)
            self.col_list.addItem(item)
            # 默认选中数值列
            if c in numeric_columns:
                item.setSelected(True)

    def selected_columns(self) -> list[str]:
        return [it.text() for it in self.col_list.selectedItems()]

    def config(self) -> dict:
        return {
            "columns": self.selected_columns(),
            "all_columns": list(self._columns),
            "numeric_columns": list(self._numeric_columns),
            "bins": int(self.bins_spin.value()),
            "show_kde": bool(self.kde_check.isChecked()),
            "show_mean": bool(self.mean_check.isChecked()),
            "show_median": bool(self.median_check.isChecked()),
            "iqr_k": float(self.iqr_k_spin.value()),
            "corr_method": str(self.corr_combo.currentData()),
            "show_scatter_matrix": bool(self.scatter_check.isChecked()),
            "show_qq": bool(self.qq_check.isChecked()),
        }

    def _select_all(self) -> None:
        for i in range(self.col_list.count()):
            self.col_list.item(i).setSelected(True)

    def _clear_selection(self) -> None:
        for i in range(self.col_list.count()):
            self.col_list.item(i).setSelected(False)

    def _emit_run(self) -> None:
        self.run_requested.emit(self.config())
