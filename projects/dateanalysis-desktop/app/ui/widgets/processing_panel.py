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
    ("缩放数值为mm", "scale_by_factor"),
]

EXCLUDE_MODE_ITEMS = [
    ("自动=时间/日期列", "auto"),
    ("手动指定列", "manual"),
    ("不排除", "none"),
]

# V1.7：缩放作用范围
SCALE_SCOPE_CURRENT = "current"
SCALE_SCOPE_HEAD = "head"
SCALE_SCOPE_TAIL = "tail"

SCALE_SCOPE_ITEMS = [
    ("当前数据集", SCALE_SCOPE_CURRENT),
    ("所有机头文件", SCALE_SCOPE_HEAD),
    ("所有机尾文件", SCALE_SCOPE_TAIL),
]


class ProcessingPanel(QWidget):
    apply_requested = Signal(list)
    # V1.7：按类别批量缩放：(category_code, factor, exclude_mode, exclude_columns)
    #   category_code: 'head' / 'tail'
    scale_category_requested = Signal(str, float, str, list)
    # V1.8：面板上需要主窗口根据当前 manager 状态刷新“重缩放提示”。
    #       触发时机：scope 切换 / factor 改变 / 列改变时。
    refresh_scale_hint_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns: list[str] = []
        self._numeric_columns: set[str] = set()
        self._rules: list[ProcessingRule] = []
        # 记住每个类别最后一次输入的 factor，外部可通过 set_category_factor 刷新
        self._category_factor: dict[str, float] = {"head": 1.0, "tail": 1.0}
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
        self.factor_spin = QDoubleSpinBox()
        self.factor_spin.setRange(1e-9, 1e6)
        self.factor_spin.setDecimals(6)
        self.factor_spin.setValue(1.0)
        self.factor_spin.setSingleStep(0.01)
        self.action_combo = QComboBox()
        for label, value in ACTION_ITEMS:
            self.action_combo.addItem(label, value)
        self.exclude_mode_combo = QComboBox()
        for label, value in EXCLUDE_MODE_ITEMS:
            self.exclude_mode_combo.addItem(label, value)
        self.exclude_column_combo = QComboBox()
        # V1.7：缩放作用范围
        self.scale_scope_combo = QComboBox()
        for label, value in SCALE_SCOPE_ITEMS:
            self.scale_scope_combo.addItem(label, value)

        form.addRow("处理列：", self.column_combo)
        form.addRow("条件：", self.operator_combo)
        form.addRow("阈值：", self.threshold_spin)
        form.addRow("缩放因子(单像素精度，例:像素→mm)：", self.factor_spin)
        form.addRow("作用范围(缩放)：", self.scale_scope_combo)
        form.addRow("处理动作：", self.action_combo)
        form.addRow("排除列模式：", self.exclude_mode_combo)
        form.addRow("排除列：", self.exclude_column_combo)
        layout.addLayout(form)

        self.apply_all_checkbox = QCheckBox("应用到全部数值列（除排除列外；自动忽略文本/日期/布尔）")
        layout.addWidget(self.apply_all_checkbox)

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

        self.hint_label = QLabel(
            "处理后的数据不会覆盖原始数据，而是生成临时数据集。"
            "缩放为 mm 时：除排除列外的数值列统一乘以单像素精度（float32 单精度乘法），"
            "并自动重命名列为 xxx(mm)；时间/日期列默认自动跳过。"
            "作用范围选“所有机头/机尾文件”时，将直接对该类别下尚未缩放的原始文件批量执行，不生成临时副本。"
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color:#666;")
        layout.addWidget(self.hint_label)

        # V1.8：已缩放数据集重算提示（红字/橙字，默认隐藏）
        self.scale_warn_label = QLabel("")
        self.scale_warn_label.setWordWrap(True)
        self.scale_warn_label.setStyleSheet("color:#D84315; font-weight:600;")
        self.scale_warn_label.setVisible(False)
        layout.addWidget(self.scale_warn_label)

        root.addWidget(group)

        self.add_rule_button.clicked.connect(self._add_rule)
        self.clear_rules_button.clicked.connect(self._clear_rules)
        self.apply_button.clicked.connect(self._apply_rules)
        self.operator_combo.currentIndexChanged.connect(self._update_threshold_state)
        self.action_combo.currentIndexChanged.connect(self._update_action_state)
        self.apply_all_checkbox.toggled.connect(self._update_scale_controls)
        self.exclude_mode_combo.currentIndexChanged.connect(self._update_scale_controls)
        self.scale_scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        self.factor_spin.valueChanged.connect(self._on_factor_changed)
        # V1.8：任何影响重缩放提示的变化都要求主窗口刷新
        self.scale_scope_combo.currentIndexChanged.connect(lambda _: self.refresh_scale_hint_requested.emit())
        self.factor_spin.valueChanged.connect(lambda _v: self.refresh_scale_hint_requested.emit())
        self.action_combo.currentIndexChanged.connect(lambda _: self.refresh_scale_hint_requested.emit())
        self._update_action_state()

    # ---- V1.8 重缩放提示 ----
    def set_scale_warning(self, text: str | None) -> None:
        """在面板下方显示/隐藏醒目警告。text=None 或空串则隐藏。"""
        if not text:
            self.scale_warn_label.setText("")
            self.scale_warn_label.setVisible(False)
            return
        self.scale_warn_label.setText(text)
        self.scale_warn_label.setVisible(True)

    # ---- external helpers ----
    def set_category_factor(self, category: str, factor: float) -> None:
        if factor is None or factor <= 0:
            return
        self._category_factor[category] = float(factor)
        # 若当前正在该类别的 scope，同步到输入框
        if self.action_combo.currentData() == "scale_by_factor":
            self._on_scope_changed()

    def set_columns(self, columns: list[str], numeric_columns: list[str]) -> None:
        self._columns = columns
        self._numeric_columns = set(numeric_columns)
        self.column_combo.clear()
        for col in columns:
            self.column_combo.addItem(col)
        self._refresh_exclude_columns()
        self._update_threshold_state()
        self._update_action_state()

    def _refresh_exclude_columns(self) -> None:
        current = self.exclude_column_combo.currentData()
        self.exclude_column_combo.clear()
        self.exclude_column_combo.addItem("（无）", "")
        for col in self._columns:
            self.exclude_column_combo.addItem(col, col)
        if current:
            idx = self.exclude_column_combo.findData(current)
            if idx >= 0:
                self.exclude_column_combo.setCurrentIndex(idx)

    def _update_threshold_state(self) -> None:
        op = self.operator_combo.currentData()
        if self.action_combo.currentData() != "scale_by_factor":
            self.threshold_spin.setEnabled(op not in {"is_null", "not_null"})

    def _on_scope_changed(self) -> None:
        if self.action_combo.currentData() != "scale_by_factor":
            return
        scope = self.scale_scope_combo.currentData()
        if scope in ("head", "tail"):
            # 切换到按类别时，自动填入该类别上次的 factor（不覆盖用户正在编辑的临时值的体验：
            # 仅在初次切换或 factor 为默认 1.0 时填入，避免覆盖用户输入）
            self.factor_spin.blockSignals(True)
            self.factor_spin.setValue(self._category_factor.get(scope, 1.0))
            self.factor_spin.blockSignals(False)
            # 类别范围强制"全部数值列"并禁用列选择
            self.apply_all_checkbox.setChecked(True)
            self.apply_all_checkbox.setEnabled(False)
            self.column_combo.setEnabled(False)
            self.exclude_mode_combo.setEnabled(True)
            exclude_mode = self.exclude_mode_combo.currentData()
            self.exclude_column_combo.setEnabled(exclude_mode == "manual")
        else:
            self.apply_all_checkbox.setEnabled(True)
            self._update_scale_controls()

    def _on_factor_changed(self, _value: float) -> None:
        # 用户编辑 factor 时同步回当前类别的记忆值（仅当 scope 为类别时）
        if self.action_combo.currentData() != "scale_by_factor":
            return
        scope = self.scale_scope_combo.currentData()
        if scope in ("head", "tail"):
            self._category_factor[scope] = float(self.factor_spin.value())

    def _update_action_state(self) -> None:
        action = self.action_combo.currentData()
        if action == "scale_by_factor":
            self.operator_combo.setEnabled(False)
            self.threshold_spin.setEnabled(False)
            self.factor_spin.setEnabled(True)
            self.apply_all_checkbox.setEnabled(self.scale_scope_combo.currentData() == SCALE_SCOPE_CURRENT)
            self.scale_scope_combo.setEnabled(True)
            self._on_scope_changed()
        else:
            self.operator_combo.setEnabled(True)
            self.factor_spin.setEnabled(False)
            self.apply_all_checkbox.setEnabled(False)
            self.apply_all_checkbox.setChecked(False)
            self.exclude_mode_combo.setEnabled(False)
            self.exclude_column_combo.setEnabled(False)
            self.column_combo.setEnabled(True)
            self.scale_scope_combo.setEnabled(False)
            self._update_threshold_state()

    def _update_scale_controls(self) -> None:
        if self.action_combo.currentData() != "scale_by_factor":
            return
        scope = self.scale_scope_combo.currentData()
        if scope in ("head", "tail"):
            # 由 _on_scope_changed 管
            return
        apply_all = self.apply_all_checkbox.isChecked()
        self.column_combo.setEnabled(not apply_all)
        self.exclude_mode_combo.setEnabled(apply_all)
        exclude_mode = self.exclude_mode_combo.currentData() if apply_all else "none"
        self.exclude_column_combo.setEnabled(apply_all and exclude_mode == "manual")
        if apply_all and exclude_mode == "manual" and self.exclude_column_combo.count() <= 1:
            self._refresh_exclude_columns()

    def _selected_exclude_info(self) -> tuple[str, list[str]]:
        if not self.apply_all_checkbox.isChecked():
            return "none", []
        mode = self.exclude_mode_combo.currentData() or "auto"
        if mode == "manual":
            selected = self.exclude_column_combo.currentData()
            return mode, [selected] if selected else []
        if mode == "none":
            return mode, []
        return "auto", []

    def _scale_rule_text(self, factor: float, target_col: str, exclude_mode: str, exclude_columns: list[str]) -> str:
        if target_col == "*":
            base = "全部数值列"
        else:
            base = f"列“{target_col}”"
        text = f"{base} × {factor:.6g}（float32 单精度）→ mm"
        if target_col == "*":
            if exclude_mode == "auto":
                return f"{text}；排除：自动=时间/日期列"
            if exclude_mode == "manual" and exclude_columns:
                return f"{text}；排除列：{', '.join(exclude_columns)}"
            if exclude_mode == "none":
                return f"{text}；排除：无"
        return text

    def _add_rule(self) -> None:
        col = self.column_combo.currentText()
        op = self.operator_combo.currentData()
        action = self.action_combo.currentData()
        if action == "scale_by_factor":
            factor = self.factor_spin.value()
            if factor <= 0:
                QMessageBox.warning(self, "提示", "缩放因子必须大于 0。")
                return
            target_col = "*" if self.apply_all_checkbox.isChecked() else col
            exclude_mode, exclude_columns = self._selected_exclude_info()
            if target_col != "*" and target_col not in self._numeric_columns:
                QMessageBox.warning(self, "提示", "缩放仅适用于数值列。")
                return
            if exclude_mode == "manual" and not exclude_columns:
                QMessageBox.warning(self, "提示", "手动排除模式下请选择要排除的列。")
                return
            rule = ProcessingRule(
                column=target_col,
                operator="none",
                threshold=factor,
                action="scale_by_factor",
                exclude_mode=exclude_mode,
                exclude_columns=list(exclude_columns),
            )
            self._rules.append(rule)
            scope_label = self.scale_scope_combo.currentText()
            prefix = f"[{scope_label}] " if self.scale_scope_combo.currentData() != SCALE_SCOPE_CURRENT else ""
            self.rule_list.addItem(
                QListWidgetItem(prefix + self._scale_rule_text(factor, target_col, exclude_mode, exclude_columns))
            )
            return

        threshold = self.threshold_spin.value() if op not in {"is_null", "not_null"} else None
        if action == "replace_mean" and col not in self._numeric_columns:
            QMessageBox.warning(self, "提示", "替换为列均值仅适用于数值列。")
            return
        rule = ProcessingRule(column=col, operator=op, threshold=threshold, action=action)
        self._rules.append(rule)
        op_label = self.operator_combo.currentText()
        action_label = self.action_combo.currentText()
        if threshold is None:
            text = f"{col} {op_label} → {action_label}"
        else:
            text = f"{col} {op_label} {threshold} → {action_label}"
        self.rule_list.addItem(QListWidgetItem(text))

    def _clear_rules(self) -> None:
        self._rules.clear()
        self.rule_list.clear()

    def _apply_rules(self) -> None:
        # V1.7：若当前为按类别批量缩放，直接发射专用信号，不走 rules 流
        if self.action_combo.currentData() == "scale_by_factor":
            scope = self.scale_scope_combo.currentData()
            if scope in ("head", "tail"):
                factor = float(self.factor_spin.value())
                if factor <= 0:
                    QMessageBox.warning(self, "提示", "缩放因子必须大于 0。")
                    return
                # 类别批量下同样遵守排除列设置
                exclude_mode = self.exclude_mode_combo.currentData() or "auto"
                if exclude_mode == "manual":
                    selected = self.exclude_column_combo.currentData()
                    exclude_columns = [selected] if selected else []
                    if not exclude_columns:
                        QMessageBox.warning(self, "提示", "手动排除模式下请选择要排除的列。")
                        return
                elif exclude_mode == "none":
                    exclude_columns = []
                else:
                    exclude_columns = []
                # 同步记忆值
                self._category_factor[scope] = factor
                self.scale_category_requested.emit(scope, factor, exclude_mode, exclude_columns)
                return

        if not self._rules:
            QMessageBox.warning(self, "提示", "请先添加至少一条处理规则。")
            return
        self.apply_requested.emit(list(self._rules))
