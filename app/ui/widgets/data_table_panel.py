from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QTableView, QVBoxLayout, QWidget

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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table_view)

    def set_dataframe(self, df):
        self.model.set_dataframe(df)
        # resizeColumnsToContents() iterates every cell and can be slow on many
        # columns or wide content. Only auto-size when the frame is small.
        col_count = self.model.columnCount()
        if col_count <= 20:
            self.table_view.resizeColumnsToContents()
        else:
            self.table_view.horizontalHeader().resizeSections(QHeaderView.ResizeMode.Interactive)
