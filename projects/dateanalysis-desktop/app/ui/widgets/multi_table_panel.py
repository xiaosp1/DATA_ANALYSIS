from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QComboBox, QLabel, QStackedWidget, QVBoxLayout, QWidget

from app.ui.widgets.stats_panel import StatsPanel


class MultiTablePanel(QWidget):
    """支持在同一区域切换展示多张 DataFrame 表格。向后兼容 set_dataframe()。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QHBoxLayout
        top = QHBoxLayout()
        self.label = QLabel("结果表：")
        self.combo = QComboBox()
        self.combo.setMinimumWidth(160)
        top.addWidget(self.label)
        top.addWidget(self.combo)
        top.addStretch(1)
        layout.addLayout(top)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self._tables: dict[str, StatsPanel] = {}
        self._order: list[str] = []

        self.combo.currentIndexChanged.connect(self._on_changed)

    def _on_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._order):
            return
        key = self._order[idx]
        self.stack.setCurrentWidget(self._tables[key])

    def _ensure_table(self, key: str) -> StatsPanel:
        if key not in self._tables:
            panel = StatsPanel()
            self._tables[key] = panel
            self.stack.addWidget(panel)
            self._order.append(key)
            self.combo.addItem(key)
        return self._tables[key]

    def set_table(self, key: str, df: pd.DataFrame) -> None:
        panel = self._ensure_table(key)
        panel.set_dataframe(df)

    def set_dataframe(self, df: pd.DataFrame) -> None:
        """兼容旧调用：默认放到\"综合统计\"表。"""
        self.set_table("综合统计", df)

    def clear_tables(self) -> None:
        for k in list(self._tables.keys()):
            w = self._tables.pop(k)
            self.stack.removeWidget(w)
            w.deleteLater()
        self._order.clear()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.blockSignals(False)

    def show_table(self, key: str) -> None:
        if key in self._tables:
            idx = self._order.index(key)
            self.combo.setCurrentIndex(idx)
