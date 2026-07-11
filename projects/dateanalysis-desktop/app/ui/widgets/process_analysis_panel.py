"""W8a 工艺分析 Tab UI 面板。

包含参数区（状态列/目标状态/特征列/分析按钮/导出按钮）+ 结果区（Tab 多页）+ 状态标签。
信号：analysis_requested(config)、export_requested()。
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGraphicsRectItem,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from app.services.ai_config import load_default_ai_config

_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


class ProcessAnalysisPanel(QWidget):
    analysis_requested = Signal(dict)
    export_requested = Signal()
    ai_insight_requested = Signal(str, str, str, str)  # provider, base_url, model, api_key

    # 轻量 XOR 混淆固定 key（不是强加密，仅防同事随手翻 QSettings 注册表看到明文）
    _OBFUSCATE_KEY = "DateAnalysis-AI-Key-Obf-v1!"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._df: pd.DataFrame | None = None
        self._numeric_cols: list[str] = []
        self._datetime_cols: list[str] = []
        self._report: dict[str, Any] | None = None
        self._api_keys: dict[str, str] = {}
        # W9：每个 provider 记忆用户自定义过的 base_url / model（None 表示尚未手动改过）
        self._user_base_url: dict[str, str] = {}
        self._user_model: dict[str, str] = {}
        self._settings = QSettings("DateAnalysis", "DateAnalysis")
        self._load_user_ai_settings()
        # W11：从 ~/.codex/config.toml / env 加载默认 base_url/model/api_key
        self._ai_defaults = load_default_ai_config()
        _def_key = (self._ai_defaults.get("api_key") or "").strip()
        if _def_key:
            self._api_keys["openai"] = _def_key
        self._build_ui()

    # ---------------- UI 构建 ----------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # 参数区
        params = QGroupBox("分析参数")
        form = QFormLayout(params)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.state_combo = QComboBox()
        form.addRow("状态列：", self.state_combo)

        self.state_list = QListWidget()
        self.state_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.state_list.setMaximumHeight(90)
        form.addRow("目标状态（多选）：", self.state_list)

        self.feature_list = QListWidget()
        self.feature_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.feature_list.setMaximumHeight(180)
        form.addRow("特征列（多选）：", self.feature_list)

        btn_row = QHBoxLayout()
        self.analyze_btn = QPushButton("开始分析")
        self.analyze_btn.setDefault(True)
        self.analyze_btn.setMinimumWidth(80)
        self.analyze_btn.setStyleSheet("font-weight:bold; padding:5px 10px;")
        self.export_btn = QPushButton("导出报告")
        self.export_btn.setMinimumWidth(80)
        self.export_btn.setToolTip("导出报告（CSV + PNG）")
        self.export_btn.setEnabled(False)
        btn_row.addWidget(self.analyze_btn)
        btn_row.addWidget(self.export_btn)
        btn_row.addStretch(1)
        form.addRow("", self._wrap(btn_row))

        root.addWidget(params)

        # 结果区
        self.result_tabs = QTabWidget()
        self.result_tabs.setDocumentMode(True)
        self.result_tabs.setUsesScrollButtons(True)
        self.result_tabs.setElideMode(Qt.TextElideMode.ElideNone)

        # 1. 摘要
        self.summary_table = QTableWidget(0, 4)
        self.summary_table.setHorizontalHeaderLabels(["状态值", "样本数", "占比", "可信度"])
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_tabs.addTab(self.summary_table, "摘要")

        # 2. 工艺窗口
        self.window_table = QTableWidget(0, 8)
        self.window_table.setHorizontalHeaderLabels(
            ["状态", "特征", "样本数", "均值μ", "σ", "μ±σ", "μ±2σ", "P5-P95"]
        )
        self.window_table.horizontalHeader().setStretchLastSection(True)
        self.window_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_tabs.addTab(self.window_table, "工艺窗口")

        # 3. 规则
        self.rules_text = QPlainTextEdit()
        self.rules_text.setReadOnly(True)
        self.result_tabs.addTab(self.rules_text, "规则")

        # 4. 特征重要性
        self.imp_table = QTableWidget(0, 2)
        self.imp_table.setHorizontalHeaderLabels(["特征", "F 值（ANOVA）"])
        self.imp_table.horizontalHeader().setStretchLastSection(True)
        self.imp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_tabs.addTab(self.imp_table, "特征重要性")

        # 5. 箱线图
        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        self.boxplot_widget = pg.GraphicsLayoutWidget()
        self.result_tabs.addTab(self.boxplot_widget, "箱线图")

        # 6. AI 解读
        self._build_ai_tab()

        # W10: 各子内容设最小宽度 0，避免表格/文本撑破 Dock
        _sp_exp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for tbl in (self.summary_table, self.window_table, self.imp_table):
            tbl.setMinimumWidth(0)
            tbl.setSizePolicy(_sp_exp)
            tbl.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.rules_text.setMinimumWidth(0)
        self.rules_text.setSizePolicy(_sp_exp)

        root.addWidget(self.result_tabs, stretch=1)

        # 警告/状态
        self.status_label = QLabel("请先导入数据并选择特征列，点击「开始分析」。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#b26a00; padding:4px 6px; background:#fff8e1; border-radius:4px;")
        root.addWidget(self.status_label)

        # 信号
        self.state_combo.currentIndexChanged.connect(self._on_state_col_changed)
        self.analyze_btn.clicked.connect(self._emit_analyze)
        self.export_btn.clicked.connect(self.export_requested.emit)

    # ---------------- AI 解读 Tab ----------------
    def _build_ai_tab(self) -> None:
        self.ai_tab = QWidget()
        ai_root = QVBoxLayout(self.ai_tab)
        ai_root.setContentsMargins(6, 6, 6, 6)
        ai_root.setSpacing(6)

        # W10: AI 工具栏两行布局——第一行 提供商+模型；第二行 Base URL；第三行按钮靠右
        # 避免在 400px Dock 内单行塞太多控件导致按钮/输入框被截断
        tool_grid = QGridLayout()
        tool_grid.setHorizontalSpacing(6)
        tool_grid.setVerticalSpacing(4)

        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItem("OpenAI", "openai")
        self.ai_provider_combo.addItem("DeepSeek", "deepseek")
        self.ai_provider_combo.addItem("自定义", "custom")
        self.ai_provider_combo.setMinimumWidth(0)

        self.ai_model_edit = QLineEdit()
        self.ai_model_edit.setMinimumWidth(0)
        self.ai_model_edit.setPlaceholderText("模型名")

        self.ai_base_url_edit = QLineEdit()
        self.ai_base_url_edit.setMinimumWidth(0)
        self.ai_base_url_edit.setPlaceholderText("Base URL")

        tool_grid.addWidget(QLabel("提供商："), 0, 0)
        tool_grid.addWidget(self.ai_provider_combo, 0, 1)
        tool_grid.addWidget(QLabel("模型："), 0, 2)
        tool_grid.addWidget(self.ai_model_edit, 0, 3)
        tool_grid.addWidget(QLabel("Base URL："), 1, 0)
        tool_grid.addWidget(self.ai_base_url_edit, 1, 1, 1, 3)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.ai_set_key_btn = QPushButton("配置 Key")
        self.ai_set_key_btn.setMinimumWidth(70)
        self.ai_generate_btn = QPushButton("生成解读")
        self.ai_generate_btn.setMinimumWidth(80)
        self.ai_regenerate_btn = QPushButton("重新生成")
        self.ai_regenerate_btn.setMinimumWidth(80)
        self.ai_generate_btn.setEnabled(False)
        self.ai_regenerate_btn.setEnabled(False)
        btn_row.addWidget(self.ai_set_key_btn)
        btn_row.addWidget(self.ai_generate_btn)
        btn_row.addWidget(self.ai_regenerate_btn)

        tool_grid.setColumnStretch(1, 1)
        tool_grid.setColumnStretch(3, 2)

        ai_root.addLayout(tool_grid)
        ai_root.addLayout(btn_row)

        self.ai_result_browser = QTextBrowser()
        self.ai_result_browser.setOpenExternalLinks(False)
        self.ai_result_browser.setMinimumWidth(0)
        self.ai_result_browser.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self.ai_result_browser.setPlainText("请先完成工艺分析并配置 API Key，再点击『生成解读』。")
        ai_root.addWidget(self.ai_result_browser, stretch=1)

        self.ai_status_label = QLabel("就绪")
        self.ai_status_label.setWordWrap(True)
        self.ai_status_label.setStyleSheet("color:#555; padding:4px 6px; background:#f5f5f5; border-radius:4px;")
        ai_root.addWidget(self.ai_status_label)

        self.result_tabs.addTab(self.ai_tab, "AI 解读")

        # signals
        self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
        self.ai_set_key_btn.clicked.connect(self._on_ai_set_key_clicked)
        self.ai_generate_btn.clicked.connect(self._emit_ai_insight)
        self.ai_regenerate_btn.clicked.connect(self._emit_ai_insight)
        # W9：所有 provider 下均可编辑 base_url / model；输入变化时持久化
        self.ai_base_url_edit.textEdited.connect(self._on_ai_base_url_edited)
        self.ai_model_edit.textEdited.connect(self._on_ai_model_edited)

        # 默认 openai，同步默认 base_url/model
        self._on_ai_provider_changed(0)
        # 尝试从 QSettings 加载 openai key（若有）
        self._load_api_key_from_settings("openai")
        # W11：初始显示当前 endpoint/model
        self.set_ai_status(self._idle_status_text())

    # W9: per-provider base_url/model 持久化
    def _load_user_ai_settings(self) -> None:
        for provider in ("openai", "deepseek", "custom"):
            bu = self._settings.value(f"ai_base_url_{provider}", "", type=str) or ""
            md = self._settings.value(f"ai_model_{provider}", "", type=str) or ""
            if bu.strip():
                self._user_base_url[provider] = bu.strip()
            if md.strip():
                self._user_model[provider] = md.strip()

    def _on_ai_base_url_edited(self, text: str) -> None:
        provider = self.ai_provider_combo.currentData() or "openai"
        val = (text or "").strip()
        if val:
            self._user_base_url[provider] = val
            self._settings.setValue(f"ai_base_url_{provider}", val)

    def _on_ai_model_edited(self, text: str) -> None:
        provider = self.ai_provider_combo.currentData() or "openai"
        val = (text or "").strip()
        if val:
            self._user_model[provider] = val
            self._settings.setValue(f"ai_model_{provider}", val)

    def _on_ai_provider_changed(self, _idx: int) -> None:
        from app.services.ai_client import AIClient
        provider = self.ai_provider_combo.currentData() or "openai"
        preset = AIClient.PRESETS.get(provider)
        # W11：所有 provider 均可编辑 base_url/model（W10 保留非只读）
        self.ai_base_url_edit.setReadOnly(False)
        self.ai_model_edit.setReadOnly(False)
        # W11：默认值优先级——QSettings 用户值 > ai_config（codex/env）> PRESETS > 空串
        settings_url = (self._settings.value(f"ai_base_url_{provider}", "", type=str) or "").strip()
        settings_model = (self._settings.value(f"ai_model_{provider}", "", type=str) or "").strip()
        if provider == "openai":
            fallback_url = (self._ai_defaults.get("base_url") or "").strip()
            fallback_model = (self._ai_defaults.get("model") or "").strip()
            default_url = settings_url or fallback_url or (preset["base_url"] if preset else "")
            default_model = settings_model or fallback_model or (preset["default_model"] if preset else "")
        elif provider == "deepseek":
            fallback_url = preset["base_url"] if preset else ""
            fallback_model = preset["default_model"] if preset else ""
            default_url = settings_url or fallback_url
            default_model = settings_model or fallback_model
        else:  # custom
            default_url = settings_url
            default_model = settings_model
        # block signals to avoid spurious textEdited writes（避免把默认值当成用户值保存）
        self.ai_base_url_edit.blockSignals(True)
        self.ai_model_edit.blockSignals(True)
        self.ai_base_url_edit.setText(default_url)
        self.ai_model_edit.setText(default_model)
        self.ai_base_url_edit.blockSignals(False)
        self.ai_model_edit.blockSignals(False)
        # 同步 _user_base_url/_user_model 内存缓存（仅当 QSettings 中确实有用户值）
        if settings_url:
            self._user_base_url[provider] = settings_url
        else:
            self._user_base_url.pop(provider, None)
        if settings_model:
            self._user_model[provider] = settings_model
        else:
            self._user_model.pop(provider, None)
        self._load_api_key_from_settings(provider)
        # W11：若 _ai_defaults 为 openai 提供了 api_key 且 settings 里没有覆盖，使用默认 key
        if provider == "openai" and not self._api_keys.get(provider):
            _def_key = (self._ai_defaults.get("api_key") or "").strip()
            if _def_key:
                self._api_keys[provider] = _def_key
        self._refresh_ai_button_state()

    def _on_ai_set_key_clicked(self) -> None:
        provider = self.ai_provider_combo.currentData() or "openai"
        cur = self._api_keys.get(provider, "")
        text, ok = QInputDialog.getText(
            self,
            "输入 API Key（仅保存在本机 QSettings）",
            f"请输入 {provider} 的 API Key：",
            echo=QInputDialog.EchoMode.Password,
            text="",
        )
        if not ok:
            return
        key = text.strip()
        self.set_api_key(key)
        if key:
            self._save_api_key_to_settings(provider, key)
        else:
            self._clear_api_key_from_settings(provider)

    def _emit_ai_insight(self) -> None:
        if self._report is None or "error" in self._report:
            self.set_ai_status("请先完成工艺分析并得到有效结果。")
            return
        cfg = self.get_ai_config()
        url = (cfg.get("base_url") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            self.set_ai_status("Base URL 需以 http:// 或 https:// 开头")
            self.ai_generate_btn.setEnabled(True)
            self.ai_regenerate_btn.setEnabled(True)
            return
        key = self._api_keys.get(cfg["provider"], "")
        if not key:
            self.set_ai_status("请先配置 API Key")
            return
        self.set_ai_status("请求中...")
        self.ai_result_browser.setPlainText("AI 分析中，请稍候...")
        self.ai_generate_btn.setEnabled(False)
        self.ai_regenerate_btn.setEnabled(False)
        self.ai_insight_requested.emit(cfg["provider"], cfg["base_url"], cfg["model"], key)

    def _refresh_ai_button_state(self) -> None:
        provider = self.ai_provider_combo.currentData() or "openai"
        has_key = bool(self._api_keys.get(provider, ""))
        has_report = bool(self._report and "error" not in self._report)
        enabled = bool(has_key and has_report)
        self.ai_generate_btn.setEnabled(enabled)
        self.ai_regenerate_btn.setEnabled(enabled)
        if not has_key:
            self.ai_generate_btn.setToolTip("请先配置 API Key")
        elif not has_report:
            self.ai_generate_btn.setToolTip("请先完成工艺分析")
        else:
            self.ai_generate_btn.setToolTip("")

    # ---- API Key 存取（轻量 XOR 混淆，不是加密） ----
    @staticmethod
    def _obfuscate(text: str) -> str:
        key = ProcessAnalysisPanel._OBFUSCATE_KEY
        if not text:
            return ""
        xs = []
        for i, ch in enumerate(text.encode("utf-8")):
            xs.append(ch ^ ord(key[i % len(key)]))
        import base64
        return base64.b64encode(bytes(xs)).decode("ascii")

    @staticmethod
    def _deobfuscate(text: str) -> str:
        import base64
        key = ProcessAnalysisPanel._OBFUSCATE_KEY
        if not text:
            return ""
        try:
            raw = base64.b64decode(text.encode("ascii"))
        except Exception:
            return ""
        out = bytes(b ^ ord(key[i % len(key)]) for i, b in enumerate(raw))
        try:
            return out.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _save_api_key_to_settings(self, provider: str, key: str) -> None:
        self._settings.setValue(f"ai_api_key_{provider}", self._obfuscate(key))

    def _load_api_key_from_settings(self, provider: str) -> None:
        stored = self._settings.value(f"ai_api_key_{provider}", "", type=str) or ""
        self._api_keys[provider] = self._deobfuscate(stored) if stored else ""

    def _clear_api_key_from_settings(self, provider: str) -> None:
        self._settings.remove(f"ai_api_key_{provider}")
        self._api_keys.pop(provider, None)

    # ---- 对外 AI API ----
    def set_ai_config(self, provider: str, base_url: str, model: str) -> None:
        idx = self.ai_provider_combo.findData(provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        # W9：所有 provider 可编辑
        self.ai_base_url_edit.setReadOnly(False)
        self.ai_model_edit.setReadOnly(False)
        self.ai_base_url_edit.blockSignals(True)
        self.ai_model_edit.blockSignals(True)
        self.ai_base_url_edit.setText(base_url or "")
        self.ai_model_edit.setText(model or "")
        self.ai_base_url_edit.blockSignals(False)
        self.ai_model_edit.blockSignals(False)
        if (base_url or "").strip():
            self._user_base_url[provider] = base_url.strip()
            self._settings.setValue(f"ai_base_url_{provider}", base_url.strip())
        if (model or "").strip():
            self._user_model[provider] = model.strip()
            self._settings.setValue(f"ai_model_{provider}", model.strip())
        self._refresh_ai_button_state()

    def get_ai_config(self) -> dict[str, str]:
        return {
            "provider": self.ai_provider_combo.currentData() or "openai",
            "base_url": self.ai_base_url_edit.text().strip(),
            "model": self.ai_model_edit.text().strip(),
        }

    def set_api_key(self, key: str) -> None:
        provider = self.ai_provider_combo.currentData() or "openai"
        self._api_keys[provider] = (key or "").strip()
        self._refresh_ai_button_state()

    def get_api_key(self) -> str:
        provider = self.ai_provider_combo.currentData() or "openai"
        return self._api_keys.get(provider, "")

    def set_ai_result(self, text: str) -> None:
        self.ai_result_browser.setPlainText(text or "")
        self.set_ai_status("解读完成")
        self.ai_generate_btn.setEnabled(True)
        self.ai_regenerate_btn.setEnabled(True)
        self._refresh_ai_button_state()

    def _idle_status_text(self) -> str:
        # W11：展示当前 endpoint / model，便于用户确认是否走代理
        return (
            f"就绪（endpoint: {self.ai_base_url_edit.text()}，"
            f"模型: {self.ai_model_edit.text()}）"
        )

    def set_ai_status(self, msg: str) -> None:
        self.ai_status_label.setText(str(msg) if msg else "就绪")

    # ---------------- wrap helper ----------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    # ---------------- 对外 API ----------------
    def set_dataset(
        self,
        df: pd.DataFrame | None,
        time_col_options: Iterable[str] = (),
        state_col_options: Iterable[str] = (),
        numeric_cols: Iterable[str] = (),
        datetime_cols: Iterable[str] = (),
    ) -> None:
        """由 MainWindow 在切换/导入/清空时调用，填充下拉与列表。"""
        self._df = df
        self._numeric_cols = [str(c) for c in numeric_cols]
        self._datetime_cols = [str(c) for c in datetime_cols]

        self.state_combo.blockSignals(True)
        self.state_combo.clear()
        state_opts = [str(c) for c in state_col_options]
        for c in state_opts:
            self.state_combo.addItem(c, c)
        # 默认选第一个（外部已经按关键词排好序）
        self.state_combo.blockSignals(False)

        self._populate_state_values()
        self._populate_features(time_col_options)

        # 清空结果
        self._report = None
        self._clear_results()
        self.export_btn.setEnabled(False)
        if df is None or len(df) == 0:
            self.status_label.setText("当前无数据集。")
        else:
            self.status_label.setText(f"已加载 {len(df)} 行 × {len(df.columns)} 列，请选择参数后点「开始分析」。")
        self._refresh_ai_button_state()
        # W11：无数据集/新数据集时 AI 状态回到 idle
        if self._report is None:
            self.set_ai_status(self._idle_status_text())

    def get_config(self) -> dict[str, Any]:
        state_col = self.state_combo.currentData()
        states = [self._parse_state_value(it.text()) for it in self.state_list.selectedItems()]
        feats = [it.text() for it in self.feature_list.selectedItems()]
        return {
            "state_col": state_col,
            "target_states": states,
            "feature_cols": feats,
        }

    def set_running(self, is_running: bool) -> None:
        self.analyze_btn.setEnabled(not is_running)
        self.export_btn.setEnabled((not is_running) and self._report is not None)
        if is_running:
            self.analyze_btn.setText("分析中...")
            self.status_label.setText("正在后台分析，请稍候...")
        else:
            self.analyze_btn.setText("开始分析")

    def set_result(self, report: dict[str, Any]) -> None:
        self._report = report
        self._clear_results()
        if not report:
            self.status_label.setText("分析结果为空。")
            return
        if "error" in report:
            self.status_label.setText(f"分析失败：{report['error']}")
            return
        self._fill_summary(report.get("summary", {}))
        self._fill_windows(report.get("univariate", {}))
        self._fill_rules(report.get("rules", {}))
        self._fill_importance(report.get("feature_importance", []))
        self._fill_boxplots(report.get("univariate", {}))
        warnings = report.get("meta", {}).get("warnings", [])
        if warnings:
            self.status_label.setText("⚠ " + "；".join(warnings))
            self.status_label.setStyleSheet("color:#b26a00; padding:4px 6px; background:#fff8e1; border-radius:4px;")
        else:
            self.status_label.setText("✅ 分析完成。")
            self.status_label.setStyleSheet("color:#2e7d32; padding:4px 6px; background:#e8f5e9; border-radius:4px;")
        self.export_btn.setEnabled(True)
        self._refresh_ai_button_state()

    def report(self) -> dict[str, Any] | None:
        return self._report

    # ---------------- 内部填充 ----------------
    def _populate_state_values(self) -> None:
        self.state_list.clear()
        if self._df is None:
            return
        state_col = self.state_combo.currentData()
        if not state_col or state_col not in self._df.columns:
            return
        values = []
        for v in self._df[state_col].dropna().unique().tolist():
            try:
                values.append(v.item() if hasattr(v, "item") else v)
            except Exception:
                values.append(v)
        try:
            values_sorted = sorted(values, key=lambda x: (self._is_zero(x), float(x) if self._is_number(x) else str(x)))
        except Exception:
            values_sorted = values
        for v in values_sorted:
            it = QListWidgetItem(str(v))
            it.setData(Qt.ItemDataRole.UserRole, v)
            self.state_list.addItem(it)
            if not ProcessAnalysisPanel._is_zero(v):
                it.setSelected(True)

    def _populate_features(self, time_col_options: Iterable[str]) -> None:
        self.feature_list.clear()
        time_set = {str(c) for c in time_col_options}
        state_col = self.state_combo.currentData()
        exclude = {"未脱模-s"} | time_set
        if state_col:
            exclude.add(str(state_col))
        for c in self._numeric_cols:
            if c in exclude:
                continue
            it = QListWidgetItem(str(c))
            self.feature_list.addItem(it)
            # 默认全选
            it.setSelected(True)

    def _on_state_col_changed(self, _idx: int) -> None:
        self._populate_state_values()
        self._populate_features(self._datetime_cols)

    def _emit_analyze(self) -> None:
        cfg = self.get_config()
        if not cfg["state_col"]:
            self.status_label.setText("请先选择状态列。")
            return
        if not cfg["feature_cols"]:
            self.status_label.setText("请至少选择一个特征列。")
            return
        if not cfg["target_states"]:
            self.status_label.setText("请至少选择一个目标状态。")
            return
        self.set_running(True)
        self.analysis_requested.emit(cfg)

    def _clear_results(self) -> None:
        self.summary_table.setRowCount(0)
        self.window_table.setRowCount(0)
        self.rules_text.setPlainText("")
        self.imp_table.setRowCount(0)
        self.boxplot_widget.clear()

    # ---- 表格填充 ----
    def _fill_summary(self, summary: dict) -> None:
        self.summary_table.setRowCount(len(summary))
        for row, (state, info) in enumerate(summary.items()):
            cnt = info.get("count", 0)
            pct = info.get("pct", 0.0)
            unrel = info.get("unreliable", False)
            self._set_cell(self.summary_table, row, 0, str(state))
            self._set_cell(self.summary_table, row, 1, str(cnt))
            self._set_cell(self.summary_table, row, 2, f"{pct*100:.2f}%")
            self._set_cell(self.summary_table, row, 3, "⚠ 不可靠" if unrel else "✅ 可靠")

    def _fill_windows(self, univariate: dict) -> None:
        rows: list[tuple[str, str, dict]] = []
        for state, body in univariate.items():
            feats = body.get("features", {}) if isinstance(body, dict) else {}
            for feat, info in feats.items():
                rows.append((str(state), str(feat), info))
        self.window_table.setRowCount(len(rows))
        for i, (state, feat, info) in enumerate(rows):
            n = info.get("count", 0)
            mean = info.get("mean")
            std = info.get("std")
            w1 = info.get("window_1sigma", (None, None))
            w2 = info.get("window_2sigma", (None, None))
            p5, p95 = info.get("p5"), info.get("p95")
            self._set_cell(self.window_table, i, 0, state)
            self._set_cell(self.window_table, i, 1, feat)
            self._set_cell(self.window_table, i, 2, str(n))
            self._set_cell(self.window_table, i, 3, self._fmt(mean))
            self._set_cell(self.window_table, i, 4, self._fmt(std))
            self._set_cell(self.window_table, i, 5, self._fmt_range(w1))
            self._set_cell(self.window_table, i, 6, self._fmt_range(w2))
            self._set_cell(self.window_table, i, 7, self._fmt_range((p5, p95)))
        self.window_table.resizeColumnsToContents()

    def _fill_rules(self, rules: dict) -> None:
        if not rules:
            self.rules_text.setPlainText("未生成规则（可能样本不足或目标状态无法区分）。")
            return
        lines: list[str] = []
        for state, rs in rules.items():
            lines.append(f"=== 目标状态 = {state} ===")
            if not rs:
                lines.append("  （样本不足或未找到有效切分，无规则）")
                continue
            for idx, r in enumerate(rs, start=1):
                conds = []
                for c in r.get("conditions", []):
                    op = "≤" if c["op"] == "<=" else ">"
                    conds.append(f"{c['feature']} {op} {float(c['threshold']):.2f}")
                when = " AND ".join(conds) if conds else "（全体样本）"
                prec = r.get("precision", 0.0) * 100
                rec = r.get("recall", 0.0) * 100
                sup = r.get("support", 0)
                lines.append(
                    f"[{idx}] WHEN {when} THEN 状态={state} "
                    f"(N={sup}, precision={prec:.1f}%, recall={rec:.1f}%)"
                )
            lines.append("")
        self.rules_text.setPlainText("\n".join(lines))

    def _fill_importance(self, importance: list) -> None:
        self.imp_table.setRowCount(len(importance))
        for i, (feat, fval) in enumerate(importance):
            self._set_cell(self.imp_table, i, 0, str(feat))
            if not np.isfinite(fval):
                self._set_cell(self.imp_table, i, 1, "∞")
            else:
                self._set_cell(self.imp_table, i, 1, f"{float(fval):.3f}")
        self.imp_table.resizeColumnsToContents()

    def _fill_boxplots(self, univariate: dict) -> None:
        """用 pyqtgraph 手绘简易箱线图：每个特征一行子图，x 轴是不同 state。"""
        self.boxplot_widget.clear()
        if not univariate:
            return
        # 收集所有特征
        feat_set: list[str] = []
        for _state, body in univariate.items():
            feats = body.get("features", {}) if isinstance(body, dict) else {}
            for f in feats.keys():
                if f not in feat_set:
                    feat_set.append(str(f))
        states = list(univariate.keys())
        if not feat_set or not states:
            return
        n_feat = len(feat_set)
        n_state = len(states)
        # 列数自适应
        ncols = min(3, max(1, n_feat))
        nrows = int(np.ceil(n_feat / ncols))
        for fi, feat in enumerate(feat_set):
            row = fi // ncols
            col = fi % ncols
            p = self.boxplot_widget.addPlot(row=row, col=col, title=feat)
            p.showGrid(y=True, alpha=0.3)
            p.setLabel("bottom", "状态")
            # x 位置
            xs = np.arange(n_state)
            box_w = 0.6
            for si, state in enumerate(states):
                info = univariate[state].get("features", {}).get(feat)
                if not info or info.get("count", 0) == 0:
                    continue
                q1, med, q3 = info.get("p25"), info.get("p50"), info.get("p75")
                lo, hi = info.get("p5"), info.get("p95")
                if any(v is None for v in (q1, med, q3, lo, hi)):
                    continue
                color = QColor(_PALETTE[si % len(_PALETTE)])
                # 须线
                whisker = pg.PlotDataItem(
                    [xs[si], xs[si]], [float(lo), float(hi)], pen=pg.mkPen(color, width=1)
                )
                p.addItem(whisker)
                # IQR 矩形（Q1-Q3）
                rect = QGraphicsRectItem(
                    xs[si] - box_w / 2, float(q1), box_w, float(q3) - float(q1)
                )
                rect.setBrush(pg.mkBrush(color.red(), color.green(), color.blue(), 110))
                rect.setPen(pg.mkPen(color, width=1.2))
                p.addItem(rect)
                # 中位数线
                med_line = pg.PlotDataItem(
                    [xs[si] - box_w / 2, xs[si] + box_w / 2],
                    [float(med), float(med)],
                    pen=pg.mkPen(color.darker(140), width=2),
                )
                p.addItem(med_line)
            ax = p.getAxis("bottom")
            ax.setTicks([[(i, str(s)) for i, s in enumerate(states)]])
            p.getViewBox().autoRange()

    # ---------------- 工具 ----------------
    @staticmethod
    def _set_cell(table: QTableWidget, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, col, item)

    @staticmethod
    def _fmt(v: Any) -> str:
        if v is None:
            return "-"
        try:
            f = float(v)
            if not np.isfinite(f):
                return "-"
            return f"{f:.3f}"
        except Exception:
            return str(v)

    @staticmethod
    def _fmt_range(rng: tuple) -> str:
        if not rng or len(rng) != 2 or rng[0] is None or rng[1] is None:
            return "-"
        try:
            lo, hi = float(rng[0]), float(rng[1])
            if not (np.isfinite(lo) and np.isfinite(hi)):
                return "-"
            return f"[{lo:.2f}, {hi:.2f}]"
        except Exception:
            return "-"

    @staticmethod
    def _parse_state_value(text: str) -> Any:
        """尽量把界面上的 state 文本转成原始类型（int/float/str）。"""
        try:
            if "." in text:
                return float(text)
            return int(text)
        except Exception:
            return text

    @staticmethod
    def _is_zero(v: Any) -> bool:
        try:
            return float(v) == 0.0
        except Exception:
            return False

    @staticmethod
    def _is_number(v: Any) -> bool:
        try:
            float(v)
            return True
        except Exception:
            return False
