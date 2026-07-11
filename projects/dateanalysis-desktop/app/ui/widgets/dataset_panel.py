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
from app.services.dataset_manager import CATEGORY_LABELS


KIND_LABEL = {
    "original": "原始",
    "processed": "临时",
    "merged": "合并",
}

# 类别徽标颜色（按 W2b 规范：[机头]蓝色 / [机尾]橙色，方括号同色，不使用填充底）
CATEGORY_BADGE_COLOR = {
    "head": "#2979FF",  # 蓝色
    "tail": "#FF8F00",  # 橙色
}


class DatasetPanel(QWidget):
    activate_requested = Signal(str)
    delete_requested = Signal(str)
    export_requested = Signal(str)
    merge_requested = Signal(list)
    import_requested = Signal()
    # V1.7：类别合并/跨类合同图
    merge_head_requested = Signal()
    merge_tail_requested = Signal()
    merge_cross_requested = Signal()

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

        # V1.7：类别合并按钮行
        cat_row = QHBoxLayout()
        self.merge_head_button = QPushButton("机头合并")
        self.merge_tail_button = QPushButton("机尾合并")
        self.merge_cross_button = QPushButton("跨类合同图")
        cat_row.addWidget(self.merge_head_button)
        cat_row.addWidget(self.merge_tail_button)
        cat_row.addWidget(self.merge_cross_button)
        layout.addLayout(cat_row)

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
        self.merge_head_button.clicked.connect(self.merge_head_requested)
        self.merge_tail_button.clicked.connect(self.merge_tail_requested)
        self.merge_cross_button.clicked.connect(self.merge_cross_requested)

    @staticmethod
    def _category_badge(category: str | None) -> str:
        if not category:
            return ""
        label = CATEGORY_LABELS.get(category, "")
        color = CATEGORY_BADGE_COLOR.get(category, "#666")
        if not label:
            return ""
        return f"[<span style='color:{color};font-weight:600;'>{label}</span>] "

    @classmethod
    def _item_display_html(cls, item: DatasetItem, is_active: bool) -> str:
        kind = KIND_LABEL.get(item.kind, item.kind)
        badge = cls._category_badge(getattr(item, "category", None))
        active = "  <span style='color:#888;'>← 当前</span>" if is_active else ""
        return f"<span>[{kind}]</span> {badge}{item.name}{active}"

    def refresh(self, items: list[DatasetItem], active_id: str | None) -> None:
        self.dataset_list.clear()
        for item in items:
            html = self._item_display_html(item, item.dataset_id == active_id)
            list_item = QListWidgetItem()
            label_widget = QLabel(html)
            label_widget.setTextFormat(Qt.TextFormat.RichText)
            label_widget.setContentsMargins(2, 1, 2, 1)
            list_item.setData(Qt.ItemDataRole.UserRole, item.dataset_id)
            list_item.setSizeHint(label_widget.sizeHint())
            if item.kind == "original":
                list_item.setForeground(QColor("#1f77b4"))
            elif item.kind == "merged":
                list_item.setForeground(QColor("#2ca02c"))
            else:
                list_item.setForeground(QColor("#ff7f0e"))
            self.dataset_list.addItem(list_item)
            self.dataset_list.setItemWidget(list_item, label_widget)

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
