from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.dataset_item import DatasetItem


KIND_LABEL = {
    "original": "原始",
    "processed": "临时",
    "merged": "合并",
}


class DatasetPanel(QWidget):
    activate_requested = Signal(str)
    delete_requested = Signal(str)
    export_requested = Signal(str)
    merge_requested = Signal(list)
    import_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        group = QGroupBox("数据集管理（临时储存区）")
        layout = QVBoxLayout(group)

        self.dataset_list = QListWidget()
        self.dataset_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.dataset_list)

        button_row1 = QHBoxLayout()
        self.import_button = QPushButton("导入文件")
        self.activate_button = QPushButton("切换到选中")
        button_row1.addWidget(self.import_button)
        button_row1.addWidget(self.activate_button)
        layout.addLayout(button_row1)

        button_row2 = QHBoxLayout()
        self.merge_button = QPushButton("合并选中")
        self.export_button = QPushButton("导出选中")
        self.delete_button = QPushButton("删除选中")
        button_row2.addWidget(self.merge_button)
        button_row2.addWidget(self.export_button)
        button_row2.addWidget(self.delete_button)
        layout.addLayout(button_row2)

        self.info_label = QLabel("原始数据不可删除；处理/合并结果为临时数据，可保存或删除。")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color:#666;")
        layout.addWidget(self.info_label)

        root.addWidget(group)

        self.import_button.clicked.connect(self.import_requested)
        self.activate_button.clicked.connect(self._on_activate)
        self.merge_button.clicked.connect(self._on_merge)
        self.export_button.clicked.connect(self._on_export)
        self.delete_button.clicked.connect(self._on_delete)

    def refresh(self, items: list[DatasetItem], active_id: str | None) -> None:
        self.dataset_list.clear()
        for item in items:
            label = f"[{KIND_LABEL.get(item.kind, item.kind)}] {item.name}"
            if item.dataset_id == active_id:
                label += "  ← 当前"
            list_item = QListWidgetItem(label)
            list_item.setData(Qt.ItemDataRole.UserRole, item.dataset_id)
            if item.kind == "original":
                list_item.setForeground(QColor("#1f77b4"))
            elif item.kind == "merged":
                list_item.setForeground(QColor("#2ca02c"))
            else:
                list_item.setForeground(QColor("#ff7f0e"))
            self.dataset_list.addItem(list_item)

    def selected_ids(self) -> list[str]:
        result = []
        for item in self.dataset_list.selectedItems():
            result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def _on_activate(self) -> None:
        ids = self.selected_ids()
        if len(ids) != 1:
            return
        self.activate_requested.emit(ids[0])

    def _on_merge(self) -> None:
        ids = self.selected_ids()
        if len(ids) < 2:
            return
        self.merge_requested.emit(ids)

    def _on_export(self) -> None:
        ids = self.selected_ids()
        if len(ids) != 1:
            return
        self.export_requested.emit(ids[0])

    def _on_delete(self) -> None:
        ids = self.selected_ids()
        for dataset_id in ids:
            self.delete_requested.emit(dataset_id)
