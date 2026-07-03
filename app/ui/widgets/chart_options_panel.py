from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QVBoxLayout, QWidget

from app.services.time_aggregation import GRANULARITIES


class ChartOptionsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        group = QGroupBox("时间粒度（仅时间X轴生效）")
        form = QFormLayout(group)
        self.granularity_combo = QComboBox()
        for g in GRANULARITIES:
            self.granularity_combo.addItem(g)
        form.addRow("X轴展示粒度：", self.granularity_combo)
        layout.addWidget(group)

    def current_granularity(self) -> str:
        return self.granularity_combo.currentText()

    def reset(self) -> None:
        self.granularity_combo.setCurrentIndex(0)
