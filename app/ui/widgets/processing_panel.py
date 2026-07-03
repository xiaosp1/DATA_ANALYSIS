from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.processing_rule import ProcessingRule


OPERATOR_ITEMS = [
    ("小于", "lt"),
    ("小于等于", "lte"),
    ("大于", "gt"),
    ("大于等于", "gte"),
    ("等于", "eq"),
    ("不等于", "neq"),
    ("为空", "is_null"),
    ("非空", "not_null"),
]

ACTION_ITEMS = [
    ("删除整行", "delete_row"),
    ("替换为列均值", "replace_mean"),
]


class ProcessingPanel(QWidget):
    apply_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[str] = []
        self._numeric_columns: set[str] = set()
        self._rules: list[ProcessingRule] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        group = QGroupBox("数据处理模块")
        layout = QVBoxLayout(group)

        form = QFormLayout()
        self.column_combo = QComboBox()
        self.operator_combo = QComboBox()
        for label, value in OPERATOR_ITEMS:
            self.operator_combo.addItem(label, value)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-1e12, 1e12)
        self.threshold_spin.setDecimals(4)
        self.action_combo = QComboBox()
        for label, value in ACTION_ITEMS:
            self.action_combo.addItem(label, value)
        form.addRow("处理列：", self.column_combo)
        form.addRow("条件：", self.operator_combo)
        form.addRow("阈值：", self.threshold_spin)
        form.addRow("处理动作：", self.action_combo)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self.add_rule_button = QPushButton("添加规则")
        self.clear_rules_button = QPushButton("清空规则")
        button_row.addWidget(self.add_rule_button)
        button_row.addWidget(self.clear_rules_button)
        layout.addLayout(button_row)

        self.rule_list = QListWidget()
        layout.addWidget(self.rule_list)

        self.apply_button = QPushButton("执行处理并放入临时区")
        layout.addWidget(self.apply_button)

        self.hint_label = QLabel("处理后的数据不会覆盖原始数据，而是生成临时数据集。")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color:#666;")
        layout.addWidget(self.hint_label)

        root.addWidget(group)

        self.add_rule_button.clicked.connect(self._add_rule)
        self.clear_rules_button.clicked.connect(self._clear_rules)
        self.apply_button.clicked.connect(self._apply_rules)
        self.operator_combo.currentIndexChanged.connect(self._update_threshold_state)

    def set_columns(self, columns: list[str], numeric_columns: list[str]) -> None:
        self._columns = columns
        self._numeric_columns = set(numeric_columns)
        self.column_combo.clear()
        for col in columns:
            self.column_combo.addItem(col)
        self._update_threshold_state()

    def _update_threshold_state(self) -> None:
        op = self.operator_combo.currentData()
        self.threshold_spin.setEnabled(op not in {"is_null", "not_null"})
        action = self.action_combo.currentData()
        col = self.column_combo.currentText()
        if action == "replace_mean" and col not in self._numeric_columns:
            pass

    def _add_rule(self) -> None:
        col = self.column_combo.currentText()
        op = self.operator_combo.currentData()
        action = self.action_combo.currentData()
        threshold = self.threshold_spin.value() if op not in {"is_null", "not_null"} else None
        if action == "replace_mean" and col not in self._numeric_columns:
            QMessageBox.warning(self, "提示", "替换为列均值仅适用于数值列。")
            return
        rule = ProcessingRule(column=col, operator=op, threshold=threshold, action=action)
        self._rules.append(rule)
        op_label = self.operator_combo.currentText()
        action_label = self.action_combo.currentText()
        if threshold is None:
            text = f"{col} {op_label} -> {action_label}"
        else:
            text = f"{col} {op_label} {threshold} -> {action_label}"
        self.rule_list.addItem(QListWidgetItem(text))

    def _clear_rules(self) -> None:
        self._rules.clear()
        self.rule_list.clear()

    def _apply_rules(self) -> None:
        if not self._rules:
            QMessageBox.warning(self, "提示", "请先添加至少一条处理规则。")
            return
        self.apply_requested.emit(list(self._rules))
