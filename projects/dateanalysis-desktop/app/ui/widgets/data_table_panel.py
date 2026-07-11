from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.ui.pandas_model import PandasTableModel


class TablePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = PandasTableModel()
        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_view.verticalHeader().setVisible(True)
        # W10: 允许表格随 Dock 收缩，不要撑破最小宽度
        self.table_view.setMinimumWidth(0)
        self.setMinimumWidth(0)
        self.table_view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table_view)

    def set_dataframe(self, df):
        self.model.set_dataframe(df)
        col_count = self.model.columnCount()
        if col_count <= 20:
            self.table_view.resizeColumnsToContents()
        else:
            self.table_view.horizontalHeader().resizeSections(QHeaderView.ResizeMode.Interactive)
