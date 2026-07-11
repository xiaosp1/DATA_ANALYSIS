from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class PandasTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, preview_rows: int = 1000, parent=None):
        super().__init__(parent)
        self._preview_rows = preview_rows
        self._df = df if df is not None else pd.DataFrame()
        self._display_df = self._prepare_display(self._df)

    def _prepare_display(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        if df.shape[0] > self._preview_rows:
            return df.head(self._preview_rows).copy()
        return df.copy()

    def set_dataframe(self, df: pd.DataFrame | None) -> None:
        self.beginResetModel()
        self._df = df if df is not None else pd.DataFrame()
        self._display_df = self._prepare_display(self._df)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return int(self._display_df.shape[0])

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return int(self._display_df.shape[1])

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            value = self._display_df.iat[index.row(), index.column()]
            if pd.isna(value):
                return ""
            return str(value)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < self._display_df.shape[1]:
                return str(self._display_df.columns[section])
        else:
            if 0 <= section < self._display_df.shape[0]:
                return str(section + 1)
        return None
