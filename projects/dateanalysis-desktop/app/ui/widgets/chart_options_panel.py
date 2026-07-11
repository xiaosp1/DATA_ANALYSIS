from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QVBoxLayout, QWidget

from app.services.time_aggregation import GRANULARITIES


class ChartOptionsPanel(QWidget):
    # V1.8 P2：额外发出 Y 轴显示模式变化信号，方便外部按需刷新
    y_mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        gran_group = QGroupBox("时间粒度（仅时间X轴生效）")
        gran_form = QFormLayout(gran_group)
        self.granularity_combo = QComboBox()
        for g in GRANULARITIES:
            self.granularity_combo.addItem(g)
        gran_form.addRow("X轴展示粒度：", self.granularity_combo)
        layout.addWidget(gran_group)

        # V1.8 P2：Y 轴显示模式（原始 / 归一化 0-1 / 双 Y 轴）
        y_group = QGroupBox("Y轴显示")
        y_form = QFormLayout(y_group)
        self.y_mode_combo = QComboBox()
        self.y_mode_combo.addItem("共用 Y 轴（原始值）", "shared")
        self.y_mode_combo.addItem("归一化显示（0-1，看趋势相关性）", "normalized")
        self.y_mode_combo.addItem("双 Y 轴（第一条左轴，其余右轴）", "dual")
        self.y_mode_combo.addItem("小多图（每列独立子图，共享X轴）", "small_multiples")
        self.y_mode_combo.setCurrentIndex(0)
        y_form.addRow("Y 轴模式：", self.y_mode_combo)
        layout.addWidget(y_group)

        self.y_mode_combo.currentIndexChanged.connect(
            lambda _i: self.y_mode_changed.emit(self.current_y_mode())
        )

    def current_granularity(self) -> str:
        return self.granularity_combo.currentText()

    def current_y_mode(self) -> str:
        """返回当前 Y 轴模式："shared" | "normalized" | "dual" | "small_multiples"。"""
        data = self.y_mode_combo.currentData()
        valid = {"shared", "normalized", "dual", "small_multiples"}
        return str(data) if isinstance(data, str) and data in valid else "shared"

    def reset(self) -> None:
        self.granularity_combo.setCurrentIndex(0)
        self.y_mode_combo.setCurrentIndex(0)
