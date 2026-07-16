"""W8a 工艺分析 Tab UI 面板。

包含参数区(状态列/目标状态/特征列/分析按钮/导出按钮)+ 结果区(Tab 多页)+ 状态标签。
信号:analysis_requested(config)、export_requested()。
"""
from __future__ import annotations

import sys
import time
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from app.services.ai_config import load_ai_config_file, load_default_ai_config

try:  # pingouin 可选;UI 层在 venv 缺失时禁用精化 checkbox
    import pingouin  # type: ignore  # noqa: F401
    _HAS_PINGOOUIN = True
except Exception:  # pragma: no cover
    _HAS_PINGOOUIN = False

_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


# ===== C047 UI 心跳日志(仅日志，不影响 UI 行为) =====
_UI_HB_T0 = time.time()  # UI 进程级 t0;与 head_tail_attribution 独立锚点


def _hb_ui(msg: str, pct: int = -1) -> None:
    """UI 层 5Hz 心跳,走 stderr。"""
    try:
        line = "[ATTR] t+%.3fs pct=%d %s" % (time.time() - _UI_HB_T0, int(pct), str(msg))
        print(line, file=sys.stderr)
    except Exception:
        pass


class _MultiChartWidget(pg.GraphicsLayoutWidget):
    """S5-#3 多变量归因图表包装。

    覆盖 sizeHint / minimumSizeHint 避免默认 600px 在狭窄 Dock 中撐破右面板布局。
    行为与父类一致(仍是 GraphicsLayoutWidget,可继续 addPlot)。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(0)

    def sizeHint(self):  # type: ignore[override]
        from PySide6.QtCore import QSize
        return QSize(180, 220)

    def minimumSizeHint(self):  # type: ignore[override]
        from PySide6.QtCore import QSize
        return QSize(120, 180)


class _MultiAttrWidget(QWidget):
    """S5-#3 多变量归因 Tab 根容器。

    sizeHint / minimumSizeHint 明确限制在 360-400px 范围内,避免多个
    _MultiChartWidget 默认 sizeHint 叠加后撐破右 Dock(400px 最小宽度)。
    """

    def sizeHint(self):  # type: ignore[override]
        from PySide6.QtCore import QSize
        return QSize(380, 480)

    def minimumSizeHint(self):  # type: ignore[override]
        from PySide6.QtCore import QSize
        return QSize(360, 360)


# =============================================================================
# S5-#3 模块级纯函数(无 Qt 依赖,可在 tests 里直接 import)
# =============================================================================


# C048 P0A 降采样 (C046 root cause: LOESS fallback O(n²/10) 主线程冻结)
MAX_RENDER_POINTS: int = 5000
"""chart3 单子图最大渲染点数(散点 + LOESS 共用)。

C046 根因报告实测：n=1M 时 np.convolve LOESS fallback 单子图 100-180s,p=10 多变量
模式卡死 20+ 分钟。在 _render_chart3_subplot 入口加 n 阈值判断, n>5000 时降采样到
5000 点, 单子图 LOESS 耗时从 O(n × n/10) 降到 O(5000 × 500) ≈ 2.5e6 ops,
n=1M → 5k 点 ≈ 200x 加速(实测 n=100000 → 5k: 329ms → <10ms, ≥30x)。
"""


def _downsample_for_render(
    x: "np.ndarray",
    resid: "np.ndarray",
    max_points: int = MAX_RENDER_POINTS,
    seed: int = 42,
) -> "tuple[np.ndarray, np.ndarray, int]":
    """chart3 渲染用降采样: 返回 (x_ds, resid_ds, n_orig)。

    C048 P0A 修复入口函数(纯函数,无 Qt 依赖,可在 tests 直接 import)。
    设计要点:
      - n <= max_points 时**不**降采样, 输入严格透传 (DoD 硬约束)
      - n > max_points 时用 np.random.default_rng(seed=42) 采样 max_points 个索引,
        排序回原顺序 (np.sort), 保证散点和 LOESS 用**同一组**采样点且 x 升序
      - 返回 n_orig 让调用方按需报告原样本量(标题/日志)

    注意: 不要用 replace=True (会让 x/resid 出现重复索引, 散点重叠);
          不要把 x 和 resid 分开采样 (否则散点和趋势线对不上, 图会"飞");
          np.sort(idx) 是排序"索引值", 不是排序 x 值; LOESS 内部会再 np.argsort(x)
          对 x 做升序排列以适配 lowess / np.convolve 的有序输入要求。
    """
    x_arr = np.asarray(x, dtype=float).ravel()
    r_arr = np.asarray(resid, dtype=float).ravel()
    n = int(x_arr.size)
    if n <= int(max_points):
        return x_arr, r_arr, n
    rng = np.random.default_rng(int(seed))
    idx = rng.choice(n, int(max_points), replace=False)
    idx_sorted = np.sort(idx)  # 升序 → x[idx_sorted] 自然升序, 利于 LOESS 排序
    return x_arr[idx_sorted], r_arr[idx_sorted], n


def _pearson_ui(x: "np.ndarray", y: "np.ndarray") -> float:
    """UI 层用最小 Pearson(仅用于 Top10 预勾预排序)。

    与 engine 的 _pearson 等价但不做 scipy 探测(UI 层只关心大小排序)。
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 2:
        return 0.0
    xd = x - x.mean()
    yd = y - y.mean()
    denom = float(np.sqrt((xd * xd).sum() * (yd * yd).sum()))
    if denom <= 1e-12:
        return 0.0
    return float((xd * yd).sum() / denom)


def compute_top_n_pearson(
    df: "pd.DataFrame",
    target_col: str,
    candidates: "list[str]",
    n: int = 10,
) -> "list[tuple[str, float]]":
    """对 candidates 列表计算与 target 的 |Pearson|,返回按 |r| 降序的前 n 个 (col, r)。

    容错:
      - df/列缺失 → 返回 []
      - 候选非数值或全 nan → 跳过
      - n<=0 → 返回空
      - 单值常量列(std=0)→ 跳过(Pearson=0 也会被排到末尾)
    """
    if df is None or target_col not in df.columns or not candidates:
        return []
    if int(n) <= 0:
        return []
    try:
        y = pd.to_numeric(df[target_col], errors="coerce")
    except Exception:
        return []
    out: list[tuple[str, float]] = []
    for c in candidates:
        if c == target_col or c not in df.columns:
            continue
        try:
            x = pd.to_numeric(df[c], errors="coerce")
        except Exception:
            continue
        sub = pd.DataFrame({"y": y, "x": x}).dropna()
        if len(sub) < 3:
            continue
        x_arr = sub["x"].to_numpy(dtype=float)
        y_arr = sub["y"].to_numpy(dtype=float)
        if float(x_arr.std(ddof=1)) <= 1e-12 or float(y_arr.std(ddof=1)) <= 1e-12:
            continue
        r = _pearson_ui(x_arr, y_arr)
        out.append((str(c), float(r)))
    out.sort(key=lambda t: abs(t[1]), reverse=True)
    return out[: int(n)]


def preselect_top_n_indices(
    feature_names: "list[str]",
    top_features: "list[str]",
) -> "set[int]":
    """根据 Top-N 特征名集合,返回在 feature_names 中需要预勾选的下标集合。

    用于子工具条「仅 Top10」点击时复用同一份排序。
    """
    top_set = {str(c) for c in top_features}
    return {i for i, name in enumerate(feature_names) if str(name) in top_set}


def build_multi_params(
    multi_enabled: bool,
    multi_top_n: int = 10,
    multi_compute_partial: bool = True,
    multi_compute_ols: bool = True,
    use_pingouin: bool = False,
) -> dict:
    """构造 panel → main_window → engine 的 multi 参数 dict(纯函数,便于测试)。

    语义:
      - multi_enabled=False 时,partial/ols/use_pingouin 一律 False(取消多变量连带 M1+M2 全跳)。
      - multi_enabled=True 时,partial/ols/use_pingouin 采用参数传入值(但 use_pingouin 需调用方先判断环境)。
      - multi_top_n<=1 规范化为 10(避免用户输入 0/1/负数导致 OLS 退化)。
    """
    enabled = bool(multi_enabled)
    top_n = int(multi_top_n) if multi_top_n and int(multi_top_n) >= 2 else 10
    return {
        "multi": enabled,
        "multi_top_n": top_n,
        "multi_compute_partial": enabled and bool(multi_compute_partial),
        "multi_compute_ols": enabled and bool(multi_compute_ols),
        "use_pingouin": enabled and bool(use_pingouin),
    }


class ProcessAnalysisPanel(QWidget):
    analysis_requested = Signal(dict)
    export_requested = Signal()
    ai_insight_requested = Signal(str, str, str, str, int)  # provider, base_url, model, api_key, timeout_sec

    # 轻量 XOR 混淆固定 key(不是强加密,仅防同事随手翻 QSettings 注册表看到明文)
    _OBFUSCATE_KEY = "DateAnalysis-AI-Key-Obf-v1!"

    # S5-#3 重写 minimumSizeHint 避免多变量 Tab + 子工具条额外控件撐破右 Dock(400px)
    def minimumSizeHint(self):  # type: ignore[override]
        from PySide6.QtCore import QSize
        # 保留原列宽 336 + 一些浮动;不使用 Qt 默认布局合计,避免多变量 Tab 撐过 400
        return QSize(360, 360)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._df: pd.DataFrame | None = None
        self._numeric_cols: list[str] = []
        self._datetime_cols: list[str] = []
        self._report: dict[str, Any] | None = None
        self._mode: str = "state_classify"  # W12: state_classify | head_tail_attr
        self._api_keys: dict[str, str] = {}
        # W12.3: 标记哪些 provider 的 key 来自 ai_config.json 配置文件(用于状态栏文案)
        self._api_key_from_config: set[str] = set()
        # W9:每个 provider 记忆用户自定义过的 base_url / model(None 表示尚未手动改过)
        self._user_base_url: dict[str, str] = {}
        self._user_model: dict[str, str] = {}
        self._ai_cancel_callback = None  # W12.1: fn() -> None
        self._ai_running = False
        # ===== S5-#3 多变量归因(默认开启) =====
        self._multi_enabled: bool = True  # Owner 决策 6:默认开启
        self._multi_top_n: int = 10  # 子工具条「仅 Top10」/ 多变量 OLS 默认取 Top N
        self._use_pingouin: bool = bool(_HAS_PINGOOUIN)  # pingouin 缺失时强制 False
        # 子工具条当前模式:'all' | 'invert' | 'top10' | 'custom'
        self._feat_select_mode: str = "all"
        # C037-B: 默认目标列兑底值(set_dataset 后被填充)
        self._default_target_col: str = "[机尾]指数-s"
        self._analysis_cancel_callback = None  # fn() -> None, 与 ai_cancel 同款
        self._settings = QSettings("DateAnalysis", "DateAnalysis")
        self._load_user_ai_settings()
        # W11:从 ~/.codex/config.toml / env 加载默认 base_url/model/api_key
        self._ai_defaults = load_default_ai_config()
        _def_key = (self._ai_defaults.get("api_key") or "").strip()
        if _def_key:
            self._api_keys["openai"] = _def_key
        # W12.3:从启动目录 ai_config.json 读取各 provider 默认配置(优先级:QSettings > ai_config.json > _ai_defaults/env > PRESET)
        self._ai_config_file = self._find_ai_config_file()
        self._ai_config_from_file: dict[str, dict[str, str]] = {}
        if self._ai_config_file is not None:
            self._ai_config_from_file = load_ai_config_file(self._ai_config_file)
            for provider, info in self._ai_config_from_file.items():
                k = (info.get("api_key") or "").strip()
                if k and not self._api_keys.get(provider):
                    self._api_keys[provider] = k
                    self._api_key_from_config.add(provider)
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

        # W12: 分析模式切换
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("状态分类(原工艺窗口)", "state_classify")
        self.mode_combo.addItem("归因分析", "head_tail_attr")
        form.addRow("分析模式:", self.mode_combo)

        self.mode_hint_label = QLabel("")
        self.mode_hint_label.setWordWrap(True)
        self.mode_hint_label.setStyleSheet("color:#1565c0; padding:2px 4px;")
        form.addRow("", self.mode_hint_label)

        self.state_combo = QComboBox()
        form.addRow("状态列:", self.state_combo)

        # ===== C037-B: 归因分析「目标列」下拉(替代硬编码 [机尾]指数-s)=====
        # 默认填 [机尾]指数-s（如果存在），否则填第一个数值列；归因模式启用,状态分类模式禁用
        self.target_combo = QComboBox()
        form.addRow("目标列:", self.target_combo)

        self.state_list = QListWidget()
        self.state_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.state_list.setMaximumHeight(90)
        form.addRow("目标状态(多选):", self.state_list)

        self.feature_list = QListWidget()
        self.feature_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.feature_list.setMaximumHeight(180)

        # ===== S5-#3 特征列子工具条(全选/反选/仅 Top10/自定义)=====
        self.feat_toolbar = QWidget()
        tb_layout = QHBoxLayout(self.feat_toolbar)
        tb_layout.setContentsMargins(0, 0, 0, 0)
        tb_layout.setSpacing(4)
        self.feat_btn_all = QPushButton("☑ 全选")
        self.feat_btn_invert = QPushButton("☐ 反选")
        self.feat_btn_top10 = QPushButton("☐ 仅 Top10")
        self.feat_btn_custom = QPushButton("☐ 自定义")
        for _b in (self.feat_btn_all, self.feat_btn_invert, self.feat_btn_top10, self.feat_btn_custom):
            _b.setMinimumWidth(0)
            _b.setStyleSheet("padding:2px 8px;")
            tb_layout.addWidget(_b)
        tb_layout.addStretch(1)
        # 把子工具条 + feature_list 放进一个竖向容器,form.addRow 接收一个 widget
        feat_container = QWidget()
        feat_v = QVBoxLayout(feat_container)
        feat_v.setContentsMargins(0, 0, 0, 0)
        feat_v.setSpacing(2)
        feat_v.addWidget(self.feat_toolbar)
        feat_v.addWidget(self.feature_list)
        form.addRow("特征列(多选):", feat_container)

        # ===== S5-#3 多变量归因使能开关 + pingouin 精化(行 2,位于特征列下方)=====
        multi_row = QHBoxLayout()
        multi_row.setContentsMargins(0, 0, 0, 0)
        multi_row.setSpacing(6)
        self.multi_checkbox = QCheckBox("多变量归因 (S5)")
        self.multi_checkbox.setChecked(True)
        self.multi_checkbox.setMinimumWidth(0)
        self.multi_checkbox.setToolTip(
            "默认开启:除 W12 单变量外,追加 M1 偏相关 + M2 OLS β*/R2/VIF;关闭则跳过 M1+M2。"
        )
        self.use_pingouin_checkbox = QCheckBox("pingouin 精化")
        self.use_pingouin_checkbox.setChecked(bool(_HAS_PINGOOUIN))
        self.use_pingouin_checkbox.setMinimumWidth(0)
        if not _HAS_PINGOOUIN:
            self.use_pingouin_checkbox.setEnabled(False)
            self.use_pingouin_checkbox.setToolTip(
                "pingouin>=0.5.3 未安装,请先 `pip install pingouin>=0.5.3` 后重启启用。"
            )
        else:
            self.use_pingouin_checkbox.setToolTip(
                "启用 pingouin.partial_corr(更稳定的偏相关估计);未启用时降级到 numpy 残差法。"
            )
        multi_row.addWidget(self.multi_checkbox)
        multi_row.addWidget(self.use_pingouin_checkbox)
        multi_row.addStretch(1)
        form.addRow("多变量归因:", self._wrap(multi_row))

        btn_row = QHBoxLayout()
        self.analyze_btn = QPushButton("开始分析")
        self.analyze_btn.setDefault(True)
        self.analyze_btn.setMinimumWidth(80)
        self.analyze_btn.setStyleSheet("font-weight:bold; padding:5px 10px;")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setMinimumWidth(60)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setToolTip("取消当前分析(仅 head_tail_attr 模式生效)")
        self.cancel_btn.setStyleSheet("padding:5px 10px;")
        self.export_btn = QPushButton("导出报告")
        self.export_btn.setMinimumWidth(80)
        self.export_btn.setToolTip("导出报告(CSV + PNG)")
        self.export_btn.setEnabled(False)
        btn_row.addWidget(self.analyze_btn)
        btn_row.addWidget(self.cancel_btn)
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
        self.imp_table.setHorizontalHeaderLabels(["特征", "F 值(ANOVA)"])
        self.imp_table.horizontalHeader().setStretchLastSection(True)
        self.imp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_tabs.addTab(self.imp_table, "特征重要性")

        # 5. 箱线图
        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        self.boxplot_widget = pg.GraphicsLayoutWidget()
        self.result_tabs.addTab(self.boxplot_widget, "箱线图")

        # W12: 6. 机尾指数-s 归因视图(表格 + 文字)
        self.attrib_widget = QWidget()
        attrib_root = QVBoxLayout(self.attrib_widget)
        attrib_root.setContentsMargins(4, 4, 4, 4)
        self.attrib_summary_label = QLabel("")
        self.attrib_summary_label.setWordWrap(True)
        attrib_root.addWidget(self.attrib_summary_label)
        self.attrib_table = QTableWidget(0, 7)
        self.attrib_table.setHorizontalHeaderLabels(
            ["特征", "N", "Pearson", "Spearman", "方向", "理想时μ±σ", "推荐窗口"]
        )
        self.attrib_table.horizontalHeader().setStretchLastSection(True)
        self.attrib_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        attrib_root.addWidget(self.attrib_table)
        self.attrib_rules_text = QPlainTextEdit()
        self.attrib_rules_text.setReadOnly(True)
        self.attrib_rules_text.setMaximumHeight(140)
        attrib_root.addWidget(self.attrib_rules_text)
        self.result_tabs.addTab(self.attrib_widget, "归因结果")

        # ===== S5-#3 7. 多变量归因 Tab (M1 偏相关 + M2 OLS + VIF) =====
        self._build_multi_attr_tab()
        # 多变量 Tab 明确限制最小/推荐宽度,避免撐破右 Dock(400px)
        self.multi_attr_widget.setMinimumWidth(0)
        self.multi_attr_widget.setMaximumWidth(16777215)
        # 默认隐藏(enable 多变量时显示)
        idx_multi = self.result_tabs.indexOf(self.multi_attr_widget)
        if idx_multi >= 0:
            self.result_tabs.setTabVisible(idx_multi, self._multi_enabled)

        # 7. AI 解读
        self._build_ai_tab()

        # W10: 各子内容设最小宽度 0,避免表格/文本撑破 Dock
        _sp_exp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for tbl in (
            self.summary_table,
            self.window_table,
            self.imp_table,
            self.multi_m1_table,
            self.multi_m2_table,
        ):
            tbl.setMinimumWidth(0)
            tbl.setSizePolicy(_sp_exp)
            tbl.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.rules_text.setMinimumWidth(0)
        self.rules_text.setSizePolicy(_sp_exp)
        # S5-#3 多变量 Tab 内部图表容器需保持 0 最小宽度,不擑破 Dock
        self.multi_attr_widget.setMinimumWidth(0)
        # Panel 本身设最小宽 0,布局由主窗口控制
        self.setMinimumWidth(0)

        root.addWidget(self.result_tabs, stretch=1)

        # 警告/状态
        self.status_label = QLabel("请先导入数据并选择特征列,点击「开始分析」。")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#b26a00; padding:4px 6px; background:#fff8e1; border-radius:4px;")
        root.addWidget(self.status_label)

        # 信号
        self.state_combo.currentIndexChanged.connect(self._on_state_col_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        # C037-B: target 切换时重算 feature_list(目标不能进入特征列)
        self.target_combo.currentIndexChanged.connect(self._on_target_col_changed)
        self.analyze_btn.clicked.connect(self._emit_analyze)
        self.export_btn.clicked.connect(self.export_requested.emit)
        # S5-#3 新增信号
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.multi_checkbox.toggled.connect(self._on_multi_checkbox_toggled)
        self.use_pingouin_checkbox.toggled.connect(self._on_use_pingouin_toggled)
        self.feat_btn_all.clicked.connect(lambda: self._apply_feat_select_mode("all"))
        self.feat_btn_invert.clicked.connect(lambda: self._apply_feat_select_mode("invert"))
        self.feat_btn_top10.clicked.connect(lambda: self._apply_feat_select_mode("top10"))
        self.feat_btn_custom.clicked.connect(lambda: self._apply_feat_select_mode("custom"))
        self.feature_list.itemSelectionChanged.connect(self._on_feat_selection_changed)

    # ---------------- AI 解读 Tab ----------------
    def _build_ai_tab(self) -> None:
        self.ai_tab = QWidget()
        ai_root = QVBoxLayout(self.ai_tab)
        ai_root.setContentsMargins(6, 6, 6, 6)
        ai_root.setSpacing(6)

        # W10: AI 工具栏两行布局--第一行 提供商+模型;第二行 Base URL;第三行按钮靠右
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

        # W12.2: AI 请求超时时间(用户可配置,QSettings 持久化)
        self.ai_timeout_spin = QSpinBox()
        self.ai_timeout_spin.setRange(5, 300)
        self.ai_timeout_spin.setSingleStep(5)
        self.ai_timeout_spin.setSuffix(" s")
        self.ai_timeout_spin.setToolTip(
            "AI 请求最长等待时间(秒),超时后提示失败。网络慢/内网代理可适当调大。"
        )
        self.ai_timeout_spin.setMinimumWidth(0)
        _saved_to = self._settings.value("ai_timeout_sec", 30, type=int)
        try:
            _saved_to = int(_saved_to)
        except Exception:
            _saved_to = 30
        if _saved_to < 5 or _saved_to > 300:
            _saved_to = 30
        self.ai_timeout_spin.setValue(_saved_to)
        self.ai_timeout_spin.valueChanged.connect(self._on_ai_timeout_changed)

        tool_grid.addWidget(QLabel("提供商:"), 0, 0)
        tool_grid.addWidget(self.ai_provider_combo, 0, 1)
        tool_grid.addWidget(QLabel("模型:"), 0, 2)
        tool_grid.addWidget(self.ai_model_edit, 0, 3)
        tool_grid.addWidget(QLabel("Base URL:"), 1, 0)
        tool_grid.addWidget(self.ai_base_url_edit, 1, 1, 1, 3)
        tool_grid.addWidget(QLabel("超时(s):"), 2, 0)
        tool_grid.addWidget(self.ai_timeout_spin, 2, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.ai_set_key_btn = QPushButton("配置 Key")
        self.ai_set_key_btn.setMinimumWidth(70)
        self.ai_generate_btn = QPushButton("生成解读")
        self.ai_generate_btn.setMinimumWidth(80)
        self.ai_regenerate_btn = QPushButton("重新生成")
        self.ai_regenerate_btn.setMinimumWidth(80)
        self.ai_cancel_btn = QPushButton("停止")
        self.ai_cancel_btn.setMinimumWidth(60)
        self.ai_cancel_btn.setEnabled(False)
        self.ai_cancel_btn.setToolTip("停止当前 AI 请求(软取消:UI 立即恢复,后台请求跑到超时后丢弃)")
        self.ai_generate_btn.setEnabled(False)
        self.ai_regenerate_btn.setEnabled(False)
        btn_row.addWidget(self.ai_set_key_btn)
        btn_row.addWidget(self.ai_generate_btn)
        btn_row.addWidget(self.ai_regenerate_btn)
        btn_row.addWidget(self.ai_cancel_btn)

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
        self.ai_result_browser.setPlainText("请先完成工艺分析并配置 API Key,再点击『生成解读』。")
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
        self.ai_cancel_btn.clicked.connect(self._on_ai_cancel_clicked)
        # W9:所有 provider 下均可编辑 base_url / model;输入变化时持久化
        self.ai_base_url_edit.textEdited.connect(self._on_ai_base_url_edited)
        self.ai_model_edit.textEdited.connect(self._on_ai_model_edited)

        # 默认 openai,同步默认 base_url/model
        self._on_ai_provider_changed(0)
        # 尝试从 QSettings 加载 openai key(若有)
        self._load_api_key_from_settings("openai")
        # W11:初始显示当前 endpoint/model
        self.set_ai_status(self._idle_status_text())

    # ---------------- S5-#3 多变量归因 Tab ----------------
    def _build_multi_attr_tab(self) -> None:
        # 使用 _MultiAttrWidget 子类,sizeHint/minsizehint 限制为不撐破 400px Dock
        self.multi_attr_widget = _MultiAttrWidget()
        root = QVBoxLayout(self.multi_attr_widget)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # VIF 警告 banner(黄色,默认隐藏)
        self.multi_vif_banner = QLabel("")
        self.multi_vif_banner.setWordWrap(True)
        self.multi_vif_banner.setVisible(False)
        self.multi_vif_banner.setStyleSheet(
            "color:#8a6d00; background:#fff3cd; padding:6px 8px; border-radius:4px;"
        )
        root.addWidget(self.multi_vif_banner)

        # 顶部摘要
        self.multi_summary_label = QLabel("多变量归因未执行。")
        self.multi_summary_label.setWordWrap(True)
        self.multi_summary_label.setStyleSheet(
            "color:#0b5a8a; padding:4px 6px; background:#e8f4fa; border-radius:4px;"
        )
        root.addWidget(self.multi_summary_label)

        # C034: 内嵌进度条 + 阶段文字(取代完全依赖全局 QProgressDialog 的旧体验)
        self.attrib_progress_bar = QProgressBar()
        self.attrib_progress_bar.setRange(0, 100)
        self.attrib_progress_bar.setValue(0)
        self.attrib_progress_bar.setTextVisible(True)
        self.attrib_progress_bar.setFormat("归因进度: %p%")
        self.attrib_progress_bar.setVisible(False)  # 默认隐藏,running 时再显
        root.addWidget(self.attrib_progress_bar)
        self.attrib_status_label = QLabel("就绪")
        self.attrib_status_label.setStyleSheet("color:#555; padding:2px 4px;")
        self.attrib_status_label.setVisible(False)
        root.addWidget(self.attrib_status_label)

        # C037-C: 3 张图表 + 2 张表 用 vertical QSplitter 布局(top:middle:bottom = 3:3:2)
        #   top:    HBox(chart1, chart2)
        #   middle: chart3 (独立,不再等宽)
        #   bottom: VBox(M1 表, M2 表)
        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        # pyqtgraph GraphicsLayoutWidget 默认 sizeHint 较宽,需指定最小宽度 + 伸缩策略
        # 使其在 400px 窄 Dock 中仍能画出来(高低比例保留)
        # 使用 _MultiChartWidget 子类覆盖 sizeHint = (180, 220),避免撐破右 Dock
        self.multi_chart1 = _MultiChartWidget()
        self.multi_chart1.setMinimumHeight(220)
        self.multi_chart1.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))
        self.multi_chart2 = _MultiChartWidget()
        self.multi_chart2.setMinimumHeight(220)
        self.multi_chart2.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))
        self.multi_chart3 = _MultiChartWidget()
        self.multi_chart3.setMinimumHeight(220)
        self.multi_chart3.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))
        # 包裹容器以便加标题
        def _wrap_chart(widget: "pg.GraphicsLayoutWidget", title: str) -> "QWidget":
            box = QGroupBox(title)
            box.setMinimumWidth(0)
            bl = QVBoxLayout(box)
            bl.setContentsMargins(4, 6, 4, 4)
            bl.addWidget(widget)
            return box

        # splitter top: chart1 + chart2
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)
        top_layout.addWidget(
            _wrap_chart(self.multi_chart1, "图1:|β*| 贡献排名"), 1
        )
        top_layout.addWidget(
            _wrap_chart(self.multi_chart2, "图2:单偏相关 vs 全偏相关"), 1
        )

        # splitter middle: chart3 独立(不再等宽)
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)
        middle_layout.addWidget(
            _wrap_chart(self.multi_chart3, "图3:OLS 残差散点图")
        )

        # splitter bottom: M1 表 + M2 表
        m1_box = QGroupBox("M1 偏相关表(控制其它头部列)")
        m1_lay = QVBoxLayout(m1_box)
        m1_lay.setContentsMargins(4, 6, 4, 4)
        self.multi_m1_table = QTableWidget(0, 4)
        self.multi_m1_table.setHorizontalHeaderLabels(["特征", "N", "single_r", "partial_r"])
        self.multi_m1_table.horizontalHeader().setStretchLastSection(True)
        self.multi_m1_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        m1_lay.addWidget(self.multi_m1_table)

        m2_box = QGroupBox("M2 OLS β* / VIF 表")
        m2_lay = QVBoxLayout(m2_box)
        m2_lay.setContentsMargins(4, 6, 4, 4)
        self.multi_m2_table = QTableWidget(0, 5)
        self.multi_m2_table.setHorizontalHeaderLabels(
            ["特征", "β*", "|β*|", "VIF", "VIF 警告"]
        )
        self.multi_m2_table.horizontalHeader().setStretchLastSection(True)
        self.multi_m2_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        m2_lay.addWidget(self.multi_m2_table)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)
        bottom_layout.addWidget(m1_box)
        bottom_layout.addWidget(m2_box)

        # vertical QSplitter — 初始 3:3:2,三个 handle 都可拖
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top_widget)
        splitter.addWidget(middle_widget)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 3)  # chart1+chart2
        splitter.setStretchFactor(1, 3)  # chart3
        splitter.setStretchFactor(2, 2)  # M1+M2 表
        splitter.setSizes([300, 300, 200])
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # 保存引用以便 _fill_multi_attr / 测试访问
        self._multi_splitter = splitter
        self._multi_chart_widget_top = top_widget
        self._multi_chart_widget_middle = middle_widget
        self._multi_tables_widget = bottom_widget

        self.result_tabs.addTab(self.multi_attr_widget, "多变量归因 (S5)")

    # W9: per-provider base_url/model 持久化
    def _load_user_ai_settings(self) -> None:
        for provider in ("openai", "deepseek", "custom"):
            bu = self._settings.value(f"ai_base_url_{provider}", "", type=str) or ""
            md = self._settings.value(f"ai_model_{provider}", "", type=str) or ""
            if bu.strip():
                self._user_base_url[provider] = bu.strip()
            if md.strip():
                self._user_model[provider] = md.strip()

    @staticmethod
    def _find_ai_config_file() -> str | None:
        """查找 ai_config.json 的位置。

        优先级:
          1) 进程启动工作目录(cwd,即 bat 同级,最符合用户预期)
          2) 应用可执行文件目录(QCoreApplication.applicationDirPath)
        找到返回绝对路径字符串,找不到返回 None。
        """
        from pathlib import Path
        candidates: list[Path] = []
        try:
            candidates.append(Path.cwd() / "ai_config.json")
        except Exception:
            pass
        try:
            from PySide6.QtCore import QCoreApplication
            app_dir = QCoreApplication.applicationDirPath()
            if app_dir:
                candidates.append(Path(app_dir) / "ai_config.json")
        except Exception:
            pass
        for c in candidates:
            try:
                if c.is_file():
                    return str(c.resolve())
            except Exception:
                continue
        return None

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

    def _on_ai_timeout_changed(self, v: int) -> None:
        try:
            iv = int(v)
        except Exception:
            iv = 30
        if iv < 5 or iv > 300:
            iv = 30
        self._settings.setValue("ai_timeout_sec", iv)

    def ai_timeout_sec(self) -> int:
        try:
            v = int(self.ai_timeout_spin.value())
        except Exception:
            v = 30
        if v < 5 or v > 300:
            return 30
        return v

    def _on_ai_provider_changed(self, _idx: int) -> None:
        from app.services.ai_client import AIClient
        provider = self.ai_provider_combo.currentData() or "openai"
        preset = AIClient.PRESETS.get(provider)
        # W11:所有 provider 均可编辑 base_url/model(W10 保留非只读)
        self.ai_base_url_edit.setReadOnly(False)
        self.ai_model_edit.setReadOnly(False)
        # W11:默认值优先级--QSettings 用户值 > ai_config(codex/env)> PRESETS > 空串
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
        # block signals to avoid spurious textEdited writes(避免把默认值当成用户值保存)
        self.ai_base_url_edit.blockSignals(True)
        self.ai_model_edit.blockSignals(True)
        self.ai_base_url_edit.setText(default_url)
        self.ai_model_edit.setText(default_model)
        self.ai_base_url_edit.blockSignals(False)
        self.ai_model_edit.blockSignals(False)
        # 同步 _user_base_url/_user_model 内存缓存(仅当 QSettings 中确实有用户值)
        if settings_url:
            self._user_base_url[provider] = settings_url
        else:
            self._user_base_url.pop(provider, None)
        if settings_model:
            self._user_model[provider] = settings_model
        else:
            self._user_model.pop(provider, None)
        self._load_api_key_from_settings(provider)
        # W11:若 _ai_defaults 为 openai 提供了 api_key 且 settings 里没有覆盖,使用默认 key
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
            "输入 API Key(仅保存在本机 QSettings)",
            f"请输入 {provider} 的 API Key:",
            echo=QLineEdit.EchoMode.Password,
            text="",
        )
        if not ok:
            return
        key = text.strip()
        self.set_api_key(key)
        if key:
            self._save_api_key_to_settings(provider, key)
            self.set_ai_status(f"API Key 已保存(provider: {provider})")
        else:
            self._clear_api_key_from_settings(provider)
            self.set_ai_status("API Key 已清除")
        self._refresh_ai_button_state()

    def _emit_ai_insight(self) -> None:
        _hb_ui("ENTER _emit_ai_insight", 100)
        if self._ai_running:
            self.set_ai_status("已有 AI 请求在执行,请先点『停止』或等其完成。")
            return
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
        self._ai_running = True
        self.ai_generate_btn.setEnabled(False)
        self.ai_regenerate_btn.setEnabled(False)
        self.ai_cancel_btn.setEnabled(True)
        # W12.2: 请求期间禁用 AI 相关输入,与其他控件一致
        self.ai_timeout_spin.setEnabled(False)
        self.ai_provider_combo.setEnabled(False)
        self.ai_base_url_edit.setEnabled(False)
        self.ai_model_edit.setEnabled(False)
        self.ai_set_key_btn.setEnabled(False)
        self.ai_result_browser.setPlainText("AI 分析中,请稍候...")
        endpoint = url
        model = (cfg.get("model") or "").strip()
        timeout_sec = self.ai_timeout_sec()
        self.set_ai_status(
            f"请求中...(endpoint:{endpoint} 模型:{model},最多等{timeout_sec}s,可点『停止』)"
        )
        self.ai_insight_requested.emit(cfg["provider"], cfg["base_url"], cfg["model"], key, timeout_sec)

    def _on_ai_cancel_clicked(self) -> None:
        cb = self._ai_cancel_callback
        self.set_ai_status("已请求停止...")
        self.ai_cancel_btn.setEnabled(False)
        if callable(cb):
            try:
                cb()
            except Exception:
                pass

    def set_ai_cancel_callback(self, fn) -> None:
        self._ai_cancel_callback = fn

    def set_ai_finished(self) -> None:
        """Called by main_window after AI success/error/cancel to restore buttons."""
        _hb_ui("EXIT _emit_ai_insight (via set_ai_finished)", 100)
        self._ai_running = False
        self.ai_cancel_btn.setEnabled(False)
        # W12.2: 恢复输入控件
        self.ai_timeout_spin.setEnabled(True)
        self.ai_provider_combo.setEnabled(True)
        self.ai_base_url_edit.setEnabled(True)
        self.ai_model_edit.setEnabled(True)
        self.ai_set_key_btn.setEnabled(True)
        self._refresh_ai_button_state()

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

    # ---- API Key 存取(轻量 XOR 混淆,不是加密) ----
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
        # W9:所有 provider 可编辑
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
        self.set_ai_finished()

    def _idle_status_text(self) -> str:
        # W11:展示当前 endpoint / model,便于用户确认是否走代理
        return (
            f"就绪(endpoint: {self.ai_base_url_edit.text()},"
            f"模型: {self.ai_model_edit.text()})"
        )

    def set_ai_status(self, msg: str) -> None:
        self.ai_status_label.setText(str(msg) if msg else "就绪")

    # ---------------- 模式切换 ----------------
    def _on_mode_changed(self, _idx: int) -> None:
        mode = self.mode_combo.currentData() or "state_classify"
        self._mode = str(mode)
        self._apply_mode_ui()
        # 根据模式刷新特征列
        self._populate_features(self._datetime_cols)
        self._refresh_status_by_mode()

    def _apply_mode_ui(self) -> None:
        is_attr = self._mode == "head_tail_attr"
        # 状态列/目标状态区在 head_tail 模式下禁用
        self.state_combo.setEnabled(not is_attr)
        self.state_list.setEnabled(not is_attr)
        # C037-B: 目标列(target_combo)只在归因模式下可用;
        # 状态分类模式下不分析数值列对目标的影响,目标列无意义,禁用
        if hasattr(self, "target_combo"):
            self.target_combo.setEnabled(bool(is_attr))
        # 多变量归因参数区只对 head_tail_attr 模式有意义
        for w in (
            self.feat_toolbar,
            self.multi_checkbox,
            self.use_pingouin_checkbox,
        ):
            try:
                w.setVisible(is_attr)
            except Exception:
                pass
        # 控制是否显示归因 Tab
        idx_attrib = self.result_tabs.indexOf(self.attrib_widget)
        idx_multi = self.result_tabs.indexOf(self.multi_attr_widget)
        idx_box = self.result_tabs.indexOf(self.boxplot_widget)
        idx_window = self.result_tabs.indexOf(self.window_table)
        idx_imp = self.result_tabs.indexOf(self.imp_table)
        idx_summary = self.result_tabs.indexOf(self.summary_table)
        idx_rules = self.result_tabs.indexOf(self.rules_text)
        if is_attr:
            default_t = (
                getattr(self, "_default_target_col", None) or "[机尾]指数-s"
            )
            self.mode_hint_label.setText(
                f"将自动以 {default_t}=4 为理想目标,分析全部数值列对其影响。"
            )
            # 切到归因 tab
            for i in (idx_box, idx_window, idx_imp, idx_summary, idx_rules):
                if i >= 0:
                    self.result_tabs.setTabEnabled(i, False)
            if idx_attrib >= 0:
                self.result_tabs.setTabEnabled(idx_attrib, True)
            if idx_multi >= 0:
                self.result_tabs.setTabVisible(idx_multi, bool(self._multi_enabled))
                self.result_tabs.setTabEnabled(idx_multi, bool(self._multi_enabled))
        else:
            self.mode_hint_label.setText("原工艺窗口模式:按选定状态列对特征做单变量窗口与规则挖掘。")
            for i in (idx_box, idx_window, idx_imp, idx_summary, idx_rules):
                if i >= 0:
                    self.result_tabs.setTabEnabled(i, True)
            if idx_attrib >= 0:
                self.result_tabs.setTabEnabled(idx_attrib, False)
            if idx_multi >= 0:
                self.result_tabs.setTabVisible(idx_multi, False)
                self.result_tabs.setTabEnabled(idx_multi, False)

    def _has_head_tail_columns(self) -> bool:
        """C037-B: 软化不再要求必须有 [机头]* 或 [机尾]指数-s,
        只要求至少有 2 个数值列(允许归因分析任意数值列)。"""
        if self._df is None:
            return False
        n_numeric = 0
        for c in self._df.columns:
            try:
                if pd.api.types.is_numeric_dtype(self._df[c]):
                    n_numeric += 1
                    if n_numeric >= 2:
                        return True
            except Exception:
                continue
        return False

    def _refresh_status_by_mode(self) -> None:
        if self._mode == "head_tail_attr":
            if not self._has_head_tail_columns():
                self.mode_hint_label.setText(
                    "⚠ 未检测到足够数值列（≥2 列）。请确认已加载含数值型参数的数据集。"
                )
                self.mode_hint_label.setStyleSheet("color:#c62828; padding:2px 4px;")
                self.analyze_btn.setEnabled(False)
            else:
                default_t = (
                    getattr(self, "_default_target_col", None) or "[机尾]指数-s"
                )
                self.mode_hint_label.setText(
                    f"将自动以 {default_t}=4 为理想目标,分析全部数值列对其影响。"
                )
                self.mode_hint_label.setStyleSheet("color:#1565c0; padding:2px 4px;")
                self.analyze_btn.setEnabled(True)
        else:
            self.mode_hint_label.setStyleSheet("color:#1565c0; padding:2px 4px;")

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
        """由 MainWindow 在切换/导入/清空时调用,填充下拉与列表。"""
        self._df = df
        self._numeric_cols = [str(c) for c in numeric_cols]
        self._datetime_cols = [str(c) for c in datetime_cols]

        self.state_combo.blockSignals(True)
        self.state_combo.clear()
        state_opts = [str(c) for c in state_col_options]
        for c in state_opts:
            self.state_combo.addItem(c, c)
        # 默认选第一个(外部已经按关键词排好序)
        self.state_combo.blockSignals(False)

        # ===== C037-B: 填充目标列(target_combo)=====
        # 归因模式 = 全部数值列(排除时间列),默认 [机尾]指数-s(如存在)
        self._populate_target_combo()

        self._populate_state_values()
        self._populate_features(time_col_options)

        # 清空结果
        self._report = None
        self._ai_running = False
        self._clear_results()
        self.export_btn.setEnabled(False)
        self._apply_mode_ui()
        if df is None or len(df) == 0:
            self.status_label.setText("当前无数据集。")
        else:
            self.status_label.setText(f"已加载 {len(df)} 行 × {len(df.columns)} 列,请选择参数后点「开始分析」。")
        self._refresh_status_by_mode()
        self._refresh_ai_button_state()
        # W11:无数据集/新数据集时 AI 状态回到 idle
        if self._report is None:
            self.set_ai_status(self._idle_status_text())

    def get_config(self) -> dict[str, Any]:
        mode = self._mode
        feats = [it.text() for it in self.feature_list.selectedItems()]
        cfg: dict[str, Any] = {"mode": mode, "feature_cols": feats}
        if mode == "state_classify":
            state_col = self.state_combo.currentData()
            states = [self._parse_state_value(it.text()) for it in self.state_list.selectedItems()]
            cfg["state_col"] = state_col
            cfg["target_states"] = states
            # S5-#3 state_classify 模式不启用多变量,但保持字段存在以便 main_window 走兼容分支
            cfg["multi"] = False
            cfg["multi_top_n"] = 10
            cfg["multi_compute_partial"] = False
            cfg["multi_compute_ols"] = False
            cfg["use_pingouin"] = False
        else:
            cfg["target_col"] = self.target_combo.currentData() or "[机尾]指数-s"
            cfg["ideal_value"] = 4.0
            # S5-#3 透传多变量归因参数(关闭时不写 multi 节点;开启时 main_window 调 build_head_tail_report)
            cfg["multi"] = bool(self._multi_enabled)
            cfg["multi_top_n"] = int(self._multi_top_n)
            cfg["multi_compute_partial"] = bool(self._multi_enabled)  # enable 时偏相关 = on
            cfg["multi_compute_ols"] = bool(self._multi_enabled)  # enable 时 OLS = on
            cfg["use_pingouin"] = bool(
                self._multi_enabled
                and bool(_HAS_PINGOOUIN)
                and bool(self.use_pingouin_checkbox.isChecked())
            )
        return cfg

    def current_mode(self) -> str:
        return self._mode

    def set_running(self, is_running: bool) -> None:
        self.analyze_btn.setEnabled(not is_running)
        self.export_btn.setEnabled((not is_running) and self._report is not None)
        # S5-#3 cancel 按钮只在 head_tail_attr 模式 + running 时可用
        in_attr = self._mode == "head_tail_attr"
        self.cancel_btn.setEnabled(bool(is_running and in_attr))
        # C034: multi 模式时点亮/隐藏内嵌进度条(单变量模式仍用旧 status_label)
        show_progress = bool(is_running and in_attr and bool(getattr(self, "_multi_enabled", False)))
        if hasattr(self, "attrib_progress_bar"):
            self.attrib_progress_bar.setVisible(show_progress)
            if show_progress:
                self.attrib_progress_bar.setRange(0, 100)
                self.attrib_progress_bar.setValue(0)
        if hasattr(self, "attrib_status_label"):
            self.attrib_status_label.setVisible(show_progress)
        # C034:running 启动时自动切到多变量 Tab,让用户看到进度条
        if show_progress and hasattr(self, "multi_attr_widget"):
            idx_multi = self.result_tabs.indexOf(self.multi_attr_widget)
            if idx_multi >= 0:
                self.result_tabs.setCurrentIndex(idx_multi)
        if is_running:
            self.analyze_btn.setText("分析中...")
            self.status_label.setText("正在后台分析,请稍候...")
        else:
            self.analyze_btn.setText("开始分析")
            self.cancel_btn.setEnabled(False)

    def set_progress(self, pct: int, msg: str = "") -> None:
        """C034:MainWindow._progress_cb 调过来,更新内嵌进度条 + 阶段文字。"""
        if hasattr(self, "attrib_progress_bar") and self.attrib_progress_bar is not None:
            self.attrib_progress_bar.setValue(max(0, min(100, int(pct))))
        if msg and hasattr(self, "attrib_status_label") and self.attrib_status_label is not None:
            self.attrib_status_label.setText(str(msg))

    def set_result(self, report: dict[str, Any], mode: str | None = None) -> None:
        if mode is not None:
            self._mode = mode
        self._report = report
        self._clear_results()
        if not report:
            self.status_label.setText("分析结果为空。")
            return
        if "error" in report:
            self.status_label.setText(f"分析失败:{report['error']}")
            return
        if self._mode == "head_tail_attr" or report.get("meta", {}).get("mode") == "head_tail_attribution":
            self._fill_head_tail(report)
        else:
            self._fill_state_classify(report)
        self.export_btn.setEnabled(True)
        self._refresh_ai_button_state()

    def _fill_state_classify(self, report: dict[str, Any]) -> None:
        self._fill_summary(report.get("summary", {}))
        self._fill_windows(report.get("univariate", {}))
        self._fill_rules(report.get("rules", {}))
        self._fill_importance(report.get("feature_importance", []))
        self._fill_boxplots(report.get("univariate", {}))
        warnings = report.get("meta", {}).get("warnings", [])
        if warnings:
            self.status_label.setText("⚠ " + ";".join(warnings))
            self.status_label.setStyleSheet("color:#b26a00; padding:4px 6px; background:#fff8e1; border-radius:4px;")
        else:
            self.status_label.setText("✅ 分析完成。")
            self.status_label.setStyleSheet("color:#2e7d32; padding:4px 6px; background:#e8f5e9; border-radius:4px;")
        # 默认跳到摘要 tab
        self.result_tabs.setCurrentWidget(self.summary_table)

    def report(self) -> dict[str, Any] | None:
        return self._report

    # ---------------- 内部填充 ----------------
    def _populate_target_combo(self) -> None:
        """C037-B: 填充归因目标列下拉(target_combo)。

        语义:归因模式 = 全部数值列(排除时间列、ID 列);默认选 [机尾]指数-s(如存在),
        否则选第一个数值列。Owner #3:「归因模式纳入全部数值列」。
        """
        if not hasattr(self, "target_combo"):
            return
        self.target_combo.blockSignals(True)
        try:
            self.target_combo.clear()
            if self._df is None or len(self._df.columns) == 0:
                return
            time_set = {str(c) for c in self._datetime_cols}
            numeric_cols: list[str] = []
            for c in self._df.columns:
                cname = str(c)
                if cname in time_set:
                    continue
                if not pd.api.types.is_numeric_dtype(self._df[c]):
                    continue
                numeric_cols.append(cname)
            # 优先 [机尾]指数-s 作为默认项
            preferred = "[机尾]指数-s"
            ordered: list[str] = []
            if preferred in numeric_cols:
                ordered.append(preferred)
                ordered.extend([c for c in numeric_cols if c != preferred])
            else:
                ordered = numeric_cols
            for c in ordered:
                self.target_combo.addItem(c, c)
            # 记住默认 target(用于 _populate_features 预选 Top10)
            self._default_target_col = preferred if preferred in numeric_cols else (
                ordered[0] if ordered else preferred
            )
        finally:
            self.target_combo.blockSignals(False)

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
        # C037-B: 归因模式下也排除当前 target_col(target 不是自己的 feature)
        if self._mode == "head_tail_attr" and hasattr(self, "target_combo"):
            tcol = self.target_combo.currentData()
            if tcol:
                exclude.add(str(tcol))
        is_attr = (self._mode == "head_tail_attr")
        visible_cols: list[str] = []
        for c in self._numeric_cols:
            if c in exclude:
                continue
            # C037-B Owner #3: 归因模式纳入全部数值列(不再只限 [机头]*)
            it = QListWidgetItem(str(c))
            self.feature_list.addItem(it)
            visible_cols.append(str(c))
        # ===== S5-#3 预勾选策略 =====
        # head_tail_attr 模式默认仍保持全选(W12 习惯);多变量启用时重置为「仅 Top10」。
        # state_classify 模式不进入多变量逻辑,保持默认全选。
        if is_attr:
            # C037-B: 从 target_combo 取(默认 [机尾]指数-s),不再硬编码
            target = self.target_combo.currentData() or self._default_target_col or "[机尾]指数-s"
            if (
                self._multi_enabled
                and self._df is not None
                and target in self._df.columns
            ):
                top = compute_top_n_pearson(
                    self._df, target, visible_cols, n=int(self._multi_top_n)
                )
                top_set = {c for c, _ in top}
                for i in range(self.feature_list.count()):
                    it = self.feature_list.item(i)
                    it.setSelected(it.text() in top_set)
                self._feat_select_mode = "top10"
            else:
                for i in range(self.feature_list.count()):
                    self.feature_list.item(i).setSelected(True)
                self._feat_select_mode = "all"
        else:
            for i in range(self.feature_list.count()):
                self.feature_list.item(i).setSelected(True)
            self._feat_select_mode = "all"
        self._refresh_feat_toolbar_state()

    def _on_state_col_changed(self, _idx: int) -> None:
        self._populate_state_values()
        self._populate_features(self._datetime_cols)

    def _on_target_col_changed(self, _idx: int) -> None:
        """C037-B: target 切换后重算 feature_list,避免 target 出现在 feature_cols 里。"""
        self._populate_features(self._datetime_cols)

    # ---------------- S5-#3 多变量归因信号处理 ----------------
    def _on_multi_checkbox_toggled(self, checked: bool) -> None:
        self._multi_enabled = bool(checked)
        # 多变量开关关闭:pingouin 精化 checkbox 禁用、Tab 隐藏、报告不含 multi
        self.use_pingouin_checkbox.setEnabled(bool(checked) and bool(_HAS_PINGOOUIN))
        if not checked:
            self.use_pingouin_checkbox.setChecked(False)
        idx_multi = self.result_tabs.indexOf(self.multi_attr_widget)
        if idx_multi >= 0:
            # 仅在 head_tail_attr 模式下才可见
            show = bool(checked) and (self._mode == "head_tail_attr")
            self.result_tabs.setTabVisible(idx_multi, show)
            self.result_tabs.setTabEnabled(idx_multi, show)
        # 同步模式提示
        if self._mode == "head_tail_attr":
            if checked:
                self.mode_hint_label.setText(
                    "将自动跨类合并机头+机尾数据,以[机尾]指数-s=4为理想目标,"
                    "默认勾选 Top10 头部列 + M1 偏相关 + M2 OLS β*/R2/VIF。"
                )
            else:
                self.mode_hint_label.setText(
                    "将自动跨类合并机头+机尾数据,以[机尾]指数-s=4为理想目标,"
                    "仅 W12 单变量归因(多变量归因已关闭)。"
                )

    def _on_use_pingouin_toggled(self, checked: bool) -> None:
        # pingouin 不可用时强制 false;主路径不依赖 pingouin
        if not _HAS_PINGOOUIN and checked:
            self.use_pingouin_checkbox.blockSignals(True)
            self.use_pingouin_checkbox.setChecked(False)
            self.use_pingouin_checkbox.blockSignals(False)

    def _refresh_feat_toolbar_state(self) -> None:
        """根据当前 _feat_select_mode 更新子工具条按钮视觉。"""
        for btn, mode in (
            (self.feat_btn_all, "all"),
            (self.feat_btn_invert, "invert"),
            (self.feat_btn_top10, "top10"),
            (self.feat_btn_custom, "custom"),
        ):
            active = mode == self._feat_select_mode
            label = btn.text().lstrip("☑☐ ").strip()
            prefix = "☑" if active else "☐"
            btn.setText(f"{prefix} {label}")

    def _apply_feat_select_mode(self, mode: str) -> None:
        """全选/反选/仅 Top10/自定义子工具条逻辑。"""
        if self.feature_list.count() == 0:
            self._feat_select_mode = mode
            self._refresh_feat_toolbar_state()
            return
        n = self.feature_list.count()
        if mode == "all":
            for i in range(n):
                self.feature_list.item(i).setSelected(True)
        elif mode == "invert":
            for i in range(n):
                it = self.feature_list.item(i)
                it.setSelected(not it.isSelected())
        elif mode == "top10":
            if self._df is None or "[机尾]指数-s" not in self._df.columns:
                # 数据缺失时退化为全选
                for i in range(n):
                    self.feature_list.item(i).setSelected(True)
            else:
                names = [self.feature_list.item(i).text() for i in range(n)]
                top = compute_top_n_pearson(
                    self._df, "[机尾]指数-s", names, n=int(self._multi_top_n)
                )
                top_set = {c for c, _ in top}
                for i in range(n):
                    self.feature_list.item(i).setSelected(
                        self.feature_list.item(i).text() in top_set
                    )
        elif mode == "custom":
            # 自定义:不动用户当前勾选
            pass
        self._feat_select_mode = mode
        self._refresh_feat_toolbar_state()

    def _on_feat_selection_changed(self) -> None:
        # 用户手动改勾选 → 切到「自定义」模式
        if self._feat_select_mode == "custom":
            return
        self._feat_select_mode = "custom"
        self._refresh_feat_toolbar_state()

    def _on_cancel_clicked(self) -> None:
        cb = self._analysis_cancel_callback
        self.status_label.setText("已请求取消...")
        self.cancel_btn.setEnabled(False)
        if callable(cb):
            try:
                cb()
            except Exception:
                pass

    def set_analysis_cancel_callback(self, fn) -> None:
        self._analysis_cancel_callback = fn

    def _emit_analyze(self) -> None:
        cfg = self.get_config()
        if self._mode == "head_tail_attr":
            if not self._has_head_tail_columns():
                self.status_label.setText("未检测到足够数值列（≥2 列），请先加载含数值型参数的数据集。")
                return
            if not cfg["feature_cols"]:
                self.status_label.setText("请至少选择一个数值特征列。")
                return
        else:
            if not cfg.get("state_col"):
                self.status_label.setText("请先选择状态列。")
                return
            if not cfg["feature_cols"]:
                self.status_label.setText("请至少选择一个特征列。")
                return
            if not cfg.get("target_states"):
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
        # W12
        self.attrib_table.setRowCount(0)
        self.attrib_rules_text.setPlainText("")
        self.attrib_summary_label.setText("")
        # S5-#3 多变量归因
        self.multi_m1_table.setRowCount(0)
        self.multi_m2_table.setRowCount(0)
        self.multi_chart1.clear()
        self.multi_chart2.clear()
        self.multi_chart3.clear()
        self.multi_summary_label.setText("多变量归因未执行。")
        self.multi_vif_banner.setVisible(False)
        self.multi_vif_banner.setText("")

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
            self.rules_text.setPlainText("未生成规则(可能样本不足或目标状态无法区分)。")
            return
        lines: list[str] = []
        for state, rs in rules.items():
            lines.append(f"=== 目标状态 = {state} ===")
            if not rs:
                lines.append("  (样本不足或未找到有效切分,无规则)")
                continue
            for idx, r in enumerate(rs, start=1):
                conds = []
                for c in r.get("conditions", []):
                    op = "≤" if c["op"] == "<=" else ">"
                    conds.append(f"{c['feature']} {op} {float(c['threshold']):.2f}")
                when = " AND ".join(conds) if conds else "(全体样本)"
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

    # ---- W12 机尾指数-s 归因渲染 ----
    def _fill_head_tail(self, rep: dict[str, Any]) -> None:
        meta = rep.get("meta", {}) or {}
        tdist = rep.get("target_dist", {}) or {}
        attr = list(rep.get("attribution", []) or [])
        rules = list(rep.get("top_rules", []) or [])
        win = rep.get("overall_suggested_window", {}) or {}

        n = int(meta.get("n_rows", 0) or 0)
        tcol = str(meta.get("target_col", "[机尾]指数-s"))
        pct_ideal = float(tdist.get("pct_ideal", 0.0) or 0.0) * 100
        pct_near = float(tdist.get("pct_near_ideal", 0.0) or 0.0) * 100
        mean = tdist.get("mean")
        parts = [
            f"目标列 {tcol},有效配对 N={n};均值={self._fmt(mean)},"
            f"精确=4 占比 {pct_ideal:.1f}%,近理想(|Δ|≤0.5)占比 {pct_near:.1f}%。"
        ]
        if win:
            win_parts = []
            for f, info in win.items():
                win_parts.append(f"{f}=[{self._fmt(info.get('lo'))}, {self._fmt(info.get('hi'))}]")
            parts.append("综合建议窗口:" + "; ".join(win_parts) + "。")
        warns = meta.get("warnings", []) or []
        if warns:
            parts.append("⚠ " + ";".join(list(warns)[:3]))
        self.attrib_summary_label.setText(" ".join(parts))
        self.attrib_summary_label.setWordWrap(True)

        self.attrib_table.setRowCount(len(attr))
        for i, a in enumerate(attr):
            feat = str(a.get("feature", ""))
            n_i = int(a.get("n", 0) or 0)
            pr = a.get("pearson_r")
            sr = a.get("spearman_r")
            direction = a.get("direction", "")
            mi = a.get("mean_when_ideal")
            si = a.get("std_when_ideal")
            wi = a.get("window_ideal") or (None, None)
            ideal_str = (
                f"{self._fmt(mi)}±{self._fmt(si)}" if mi is not None and si is not None else "-"
            )
            win_str = f"[{self._fmt(wi[0])}, {self._fmt(wi[1])}]" if wi[0] is not None else "-"
            self._set_cell(self.attrib_table, i, 0, feat)
            self._set_cell(self.attrib_table, i, 1, str(n_i))
            self._set_cell(self.attrib_table, i, 2, self._fmt(pr))
            self._set_cell(self.attrib_table, i, 3, self._fmt(sr))
            self._set_cell(self.attrib_table, i, 4, str(direction))
            self._set_cell(self.attrib_table, i, 5, ideal_str)
            self._set_cell(self.attrib_table, i, 6, win_str)
        self.attrib_table.resizeColumnsToContents()

        lines: list[str] = []
        lines.append("Top 单特征阈值规则(按近理想率降序):")
        if rules:
            for i, r in enumerate(rules, start=1):
                feat = str(r.get("feature", ""))
                op = "≤" if r.get("op") == "<=" else ">"
                thr = r.get("threshold")
                n_r = int(r.get("n", 0) or 0)
                pct = float(r.get("pct_near_ideal", 0.0) or 0.0) * 100
                tm = r.get("target_mean")
                lines.append(
                    f"  {i}) WHEN {feat} {op} {self._fmt(thr)} "
                    f"THEN 近理想率={pct:.1f}% (N={n_r}, 目标均值={self._fmt(tm)})"
                )
        else:
            lines.append("  (未挖掘到显著规则)")
        self.attrib_rules_text.setPlainText("\n".join(lines))

        # S5-#3 多变量归因渲染(如果引擎输出了 multi 节点)
        self._fill_multi_attr(rep)
        # 仅在多变量实际有结果时跳到多变量 Tab;否则保持归因结果 Tab
        if self._multi_enabled and rep.get("multi"):
            idx_multi = self.result_tabs.indexOf(self.multi_attr_widget)
            if idx_multi >= 0 and self.result_tabs.isTabVisible(idx_multi):
                self.result_tabs.setCurrentWidget(self.multi_attr_widget)
            else:
                self.result_tabs.setCurrentWidget(self.attrib_widget)
        else:
            self.result_tabs.setCurrentWidget(self.attrib_widget)

        if warns:
            self.status_label.setText("⚠ " + ";".join(list(warns)[:5]))
            self.status_label.setStyleSheet("color:#b26a00; padding:4px 6px; background:#fff8e1; border-radius:4px;")
        else:
            self.status_label.setText("✅ 归因完成。")
            self.status_label.setStyleSheet("color:#2e7d32; padding:4px 6px; background:#e8f5e9; border-radius:4px;")

    # ---- S5-#3 多变量归因渲染 ----
    def _fill_multi_attr(self, rep: dict[str, Any]) -> None:
        """渲染 multi 节点:3 张图表 + 2 张表 + VIF banner + 顶部摘要。

        若 rep 不含 'multi'(引擎跳过了多变量),整组保持空,不报错。
        """
        multi = rep.get("multi") if isinstance(rep, dict) else None
        if not multi:
            self.multi_summary_label.setText("多变量归因未执行(M1/M2 已禁用或报告不含 multi 节点)。")
            self.multi_m1_table.setRowCount(0)
            self.multi_m2_table.setRowCount(0)
            self.multi_chart1.clear()
            self.multi_chart2.clear()
            self.multi_chart3.clear()
            self.multi_vif_banner.setVisible(False)
            self.multi_vif_banner.setText("")
            return

        partial = list(multi.get("partial_corr") or [])
        ols = multi.get("ols") or None
        top_contrib = list(multi.get("top_contributors") or [])
        ols_skip = multi.get("ols_skipped_reason")
        warnings = list(multi.get("warnings") or [])
        vif_thr = float(multi.get("vif_warn_threshold") or 10.0)

        # 顶部摘要
        summary_parts: list[str] = []
        if ols and isinstance(ols, dict):
            r2 = ols.get("r2")
            r2_adj = ols.get("r2_adj")
            n_m2 = ols.get("n")
            k_m2 = ols.get("k")
            cond = ols.get("condition_number")
            r2_str = f"{r2:.3f}" if isinstance(r2, (int, float)) and np.isfinite(float(r2)) else "-"
            r2a_str = f"{r2_adj:.3f}" if isinstance(r2_adj, (int, float)) and np.isfinite(float(r2_adj)) else "-"
            summary_parts.append(f"M2 OLS:N={n_m2}, k={k_m2}, R2={r2_str}, R2_adj={r2a_str}")
            if isinstance(cond, (int, float)) and np.isfinite(float(cond)):
                summary_parts.append(f"条件数 κ={float(cond):.1f}")
        else:
            summary_parts.append(f"M2 OLS 跳过:{ols_skip or '未启用'}")
        if top_contrib:
            summary_parts.append("主因子:" + " / ".join(top_contrib[:5]))
        self.multi_summary_label.setText(";".join(summary_parts) + "。")

        # VIF banner(仅警告,不剔除)
        vif_warns = [w for w in warnings if "VIF" in w and "建议剔除" in w]
        if vif_warns:
            banner = "⚠ VIF 警告(仅提示,未自动剔除):" + ";".join(vif_warns[:5])
            if len(vif_warns) > 5:
                banner += f";等 {len(vif_warns)} 项"
            self.multi_vif_banner.setText(banner)
            self.multi_vif_banner.setVisible(True)
        else:
            self.multi_vif_banner.setText("")
            self.multi_vif_banner.setVisible(False)

        # M1 表
        self.multi_m1_table.setRowCount(len(partial))
        for i, row in enumerate(partial):
            feat = str(row.get("feature", ""))
            n_i = int(row.get("n", 0) or 0)
            sr = row.get("single_r")
            pr = row.get("partial_r")
            self._set_cell(self.multi_m1_table, i, 0, feat)
            self._set_cell(self.multi_m1_table, i, 1, str(n_i))
            self._set_cell(self.multi_m1_table, i, 2, self._fmt(sr))
            self._set_cell(self.multi_m1_table, i, 3, self._fmt(pr))
        self.multi_m1_table.resizeColumnsToContents()

        # M2 表
        coef = list((ols or {}).get("coef_std") or []) if ols else []
        # 排序:|β*| 降序
        coef_sorted = sorted(coef, key=lambda d: abs(float(d.get("beta_std", 0.0) or 0.0)), reverse=True)
        self.multi_m2_table.setRowCount(len(coef_sorted))
        for i, row in enumerate(coef_sorted):
            feat = str(row.get("feature", ""))
            bs = float(row.get("beta_std", 0.0) or 0.0)
            absb = float(row.get("abs_beta_std", abs(bs)) or 0.0)
            vif = float(row.get("vif", 1.0) or 1.0)
            vif_warn_flag = bool(row.get("vif_warn", False)) or vif > vif_thr
            self._set_cell(self.multi_m2_table, i, 0, feat)
            self._set_cell(self.multi_m2_table, i, 1, f"{bs:.3f}")
            self._set_cell(self.multi_m2_table, i, 2, f"{absb:.3f}")
            self._set_cell(self.multi_m2_table, i, 3, f"{vif:.2f}")
            self._set_cell(
                self.multi_m2_table,
                i,
                4,
                "⚠ VIF>" + f"{vif_thr:.1f}" if vif_warn_flag else "-",
            )
        self.multi_m2_table.resizeColumnsToContents()

        # 图 1:|β*| 贡献排名(pyqtgraph BarGraphItem)
        self.multi_chart1.clear()
        if coef_sorted:
            p1 = self.multi_chart1.addPlot(row=0, col=0)
            p1.showGrid(y=True, alpha=0.3)
            names = [str(c.get("feature", "")) for c in coef_sorted]
            ys = [abs(float(c.get("beta_std", 0.0) or 0.0)) for c in coef_sorted]
            xs = np.arange(len(ys))
            colors = []
            for c in coef_sorted:
                vif_v = float(c.get("vif", 1.0) or 1.0)
                kept = bool(c.get("kept", True))
                bs = float(c.get("beta_std", 0.0) or 0.0)
                if not kept:
                    colors.append("#9e9e9e")  # 灰 = 被剔除
                elif bs >= 0:
                    colors.append("#1f77b4")  # 蓝 = 正
                else:
                    colors.append("#d62728")  # 红 = 负
            brushes = [pg.mkBrush(QColor(c)) for c in colors]
            bg = pg.BarGraphItem(x=xs, height=ys, width=0.6, brushes=brushes)  # type: ignore[arg-type]
            p1.addItem(bg)
            # 柱顶标签
            for x, y_, n_ in zip(xs, ys, names):
                t = pg.TextItem(f"{y_:.2f}", color="#333", anchor=(0.5, 1.0))
                t.setPos(float(x), float(y_) + 0.02)
                p1.addItem(t)
            ax = p1.getAxis("bottom")
            short = [n_.replace("[机头]", "")[:8] for n_ in names]
            ax.setTicks([[(i, s) for i, s in enumerate(short)]])
            p1.setLabel("left", "|β*|")
            p1.setLabel("bottom", "特征")
            p1.getViewBox().setMouseEnabled(x=True, y=True)
            p1.getViewBox().autoRange()

        # 图 2:单偏相关 vs 全偏相关对比(双 BarGraphItem)
        self.multi_chart2.clear()
        if partial:
            p2 = self.multi_chart2.addPlot(row=0, col=0)
            p2.showGrid(y=True, alpha=0.3)
            sorted_pc = sorted(
                partial,
                key=lambda d: abs(float(d.get("partial_r", 0.0) or 0.0)),
                reverse=True,
            )
            names = [str(d.get("feature", "")) for d in sorted_pc]
            single_rs = [float(d.get("single_r", 0.0) or 0.0) for d in sorted_pc]
            partial_rs = [float(d.get("partial_r", 0.0) or 0.0) for d in sorted_pc]
            xs = np.arange(len(names))
            w = 0.4
            bg1 = pg.BarGraphItem(x=xs - w / 2, height=single_rs, width=w,
                                  brush=pg.mkBrush("#1f77b4"))
            bg2 = pg.BarGraphItem(x=xs + w / 2, height=partial_rs, width=w,
                                  brush=pg.mkBrush("#ff7f0e"))
            p2.addItem(bg1)
            p2.addItem(bg2)
            # 图例(手写两个 TextItem)
            legend = pg.LegendItem(offset=(-10, 10))
            legend.setParentItem(p2)
            legend.addItem(bg1, "single_r (Pearson)")
            legend.addItem(bg2, "partial_r")
            ax = p2.getAxis("bottom")
            short = [n_.replace("[机头]", "")[:8] for n_ in names]
            ax.setTicks([[(i, s) for i, s in enumerate(short)]])
            p2.setLabel("left", "相关系数")
            p2.setLabel("bottom", "特征")
            p2.getViewBox().autoRange()

        # 图 3:OLS 残差散点图 + 水平线 0 + ±2σ 填色区域 + LOESS 趋势线
        # 规范(docs/proposals/2026-07-15-s5-attribution-multi-proposal.md §2.3):
        #   grid 2 × ⌈p/2⌉;每个子图 e vs x_j;
        #   残差水平线 y=0 虚线;±2σ 区域填浅色;带 LOESS 趋势线。
        self.multi_chart3.clear()
        # 多变量归因开关关闭时整组隐藏(防御性,正常流程由 result_tabs Tab 可见性控制)
        if not bool(getattr(self, "_multi_enabled", True)):
            self.multi_chart3.addPlot(row=0, col=0, title="(多变量归因已关闭)")
        else:
            try:
                ols_dict = ols if isinstance(ols, dict) else None
                if not ols_dict:
                    self.multi_chart3.addPlot(row=0, col=0, title="(无 OLS 结果)")
                elif self._df is None or "[机尾]指数-s" not in self._df.columns:
                    self.multi_chart3.addPlot(row=0, col=0, title="(需数据可用)")
                else:
                    self._render_chart3_grid(coef_sorted=coef_sorted, ols_dict=ols_dict)
            except Exception as e:  # 图表失败不阻塞其它渲染
                try:
                    self.multi_chart3.clear()
                    self.multi_chart3.addPlot(row=0, col=0, title=f"图3 渲染失败: {e}")
                except Exception:
                    pass

    def _render_chart3_grid(self, coef_sorted: list[dict], ols_dict: dict) -> None:
        """图 3 主入口:算标准化残差 → 拆 grid → 渲染每张子图(拆分自 _fill_multi_attr,
        单函数不超过 50 行,便于失败定位与单元验证)。"""
        _hb_ui("ENTER _render_chart3_grid n_feats=%d" % len(coef_sorted or []), 100)
        from app.services.head_tail_attribution import _zscore_array

        # C037-B: target_col 从 target_combo 取(保留 [机尾]指数-s 兑底),不再硬编码
        target_col = (
            (self.target_combo.currentData() if hasattr(self, "target_combo") else None)
            or self._default_target_col
            or "[机尾]指数-s"
        )
        feats = [str(c.get("feature", "")) for c in coef_sorted]
        cols = [target_col] + feats
        sub = self._df[cols].apply(pd.to_numeric, errors="coerce").dropna()
        if len(sub) < 5 or len(feats) == 0:
            self.multi_chart3.addPlot(row=0, col=0, title="(样本不足 / 无特征)")
            return

        y = sub[target_col].to_numpy(dtype=float)
        X = sub[feats].to_numpy(dtype=float)
        Xs = _zscore_array(X)
        ys = (y - y.mean()) / max(y.std(ddof=1), 1e-12)
        try:
            beta, *_ = np.linalg.lstsq(Xs, ys, rcond=None)
            resid = ys - Xs @ beta
        except Exception:
            resid = np.zeros_like(ys)

        n_feat = len(feats)
        # 规范:2 行 × ⌈p/2⌉ 列;p=1 时仍 1×1
        nrows = 2 if n_feat > 1 else 1
        ncols = int(np.ceil(n_feat / nrows)) if n_feat > 0 else 1
        for fi, feat in enumerate(feats):
            r = fi // ncols
            c = fi % ncols
            self._render_chart3_subplot(
                x=Xs[:, fi],
                resid=resid,
                feat=feat,
                row=r,
                col=c,
            )
        _hb_ui("EXIT _render_chart3_grid", 100)

    def _render_chart3_subplot(self, x: np.ndarray, resid: np.ndarray,
                               feat: str, row: int, col: int) -> None:
        """单张子图:散点 + y=0 虚线 + ±2σ 填色区域 + LOESS 趋势线 + 标题含 resid mean±std。

        C048 P0A 降采样 (C046 root cause: LOESS fallback O(n²/10) 主线程冻结):
        入口加 MAX_RENDER_POINTS=5000 阈值, n>5000 时降采样到 5000 点 (散点 + LOESS 共用
        同一组采样点以保持视觉对应), LOESS kernel w 按降采样后的 n 重算 (max(5, n_ds//10))。
        n=1M → 5k 点 ≈ 200x 加速 (np.convolve O(n_ds × w_ds) = O(2.5e6) vs 原 O(1e11))。
        标题/±2σ 带的 mean/std 仍用原始数据 (避免随机采样造成的统计量抖动)。
        """
        n_orig = int(len(x))
        _hb_ui("ENTER _render_chart3_subplot feat=%s row=%d col=%d n=%d" % (feat, row, col, n_orig), 100)
        short_feat = feat.replace("[机头]", "")
        # 残差摘要(子图标题尾部)——用原始数据, 不受降采样影响
        resid_mean = float(np.mean(resid)) if len(resid) else 0.0
        resid_std = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0
        title = f"{short_feat}  mean={resid_mean:+.2f} std={resid_std:.2f}"

        # C048 P0A 降采样: n>MAX_RENDER_POINTS 时降采样到 5000 点, 散点+LOESS 共用
        # x/r 同一组索引 (np.sort 回原顺序), 保证散点和趋势线对得上
        if n_orig > MAX_RENDER_POINTS:
            x, resid, _n_back = _downsample_for_render(x, resid, max_points=MAX_RENDER_POINTS)
            _hb_ui("C048 P0A downsample feat=%s n_orig=%d -> n_ds=%d" % (feat, n_orig, len(x)), 100)

        sp = self.multi_chart3.addPlot(row=row, col=col, title=title)
        sp.showGrid(x=True, y=True, alpha=0.3)
        sp.setLabel("bottom", "x (z)")
        sp.setLabel("left", "e")

        # 散点(降采样后, 与 LOESS 共用同一组点)
        scatter = pg.ScatterPlotItem(
            x=x, y=resid,
            size=4, pen=pg.mkPen("#1f77b4", width=1),
            brush=pg.mkBrush("#1f77b488"),
        )
        sp.addItem(scatter)

        # y=0 水平虚线
        sp.addLine(y=0, pen=pg.mkPen("#666", style=Qt.PenStyle.DashLine))

        # ±2σ 填色区域(LightOrange #ff7f0e33)——sd 用原始 std (稳定, 不随采样抖)
        # x_lo/x_hi 用降采样后的 x 范围 (否则 band 会延伸出可见散点区域)
        sd = resid_std
        if sd > 0 and np.isfinite(sd):
            x_lo = float(np.min(x))
            x_hi = float(np.max(x))
            upper = pg.PlotDataItem([x_lo, x_hi], [2 * sd, 2 * sd])
            lower = pg.PlotDataItem([x_lo, x_hi], [-2 * sd, -2 * sd])
            band = pg.FillBetweenItem(
                curve1=upper,
                curve2=lower,
                brush=pg.mkBrush("#ff7f0e33"),  # alpha≈0.2 浅橙
                pen=pg.mkPen(None),
            )
            sp.addItem(band)

        # LOESS 趋势线(statsmodels 不可用则滑窗均值兜底)
        # C048 P0A: x/resid 已是降采样后数据, kernel w 按 max(5, len(xs_sorted)//10) 重算
        _hb_ui("LOESS enter feat=%s n=%d" % (feat, len(x)), 100)
        try:
            from statsmodels.nonparametric.smoothers_lowess import lowess
            frac = 0.3 if len(x) >= 30 else max(0.2, 5.0 / max(len(x), 1))
            sm = lowess(resid, x, frac=frac, it=1, return_sorted=True)
            trend = pg.PlotDataItem(
                sm[:, 0], sm[:, 1],
                pen=pg.mkPen("#d62728", width=2),
            )
            sp.addItem(trend)
            _hb_ui("LOESS exit statsmodels feat=%s" % feat, 100)
        except Exception:
            # numpy 滑窗均值兜底(window = max(5, n//10))
            try:
                order = np.argsort(x)
                xs_sorted = x[order]
                rs_sorted = resid[order]
                w = max(5, len(xs_sorted) // 10)
                kernel = np.ones(w) / w
                smooth = np.convolve(rs_sorted, kernel, mode="same")
                sp.addItem(pg.PlotDataItem(
                    xs_sorted, smooth,
                    pen=pg.mkPen("#d62728", width=2),
                ))
                _hb_ui("LOESS exit numpy-fallback feat=%s" % feat, 100)
            except Exception:
                _hb_ui("LOESS exit FAILED feat=%s" % feat, 100)
                pass
        _hb_ui("EXIT _render_chart3_subplot feat=%s" % feat, 100)

    def _fill_boxplots(self, univariate: dict) -> None:
        """用 pyqtgraph 手绘简易箱线图:每个特征一行子图,x 轴是不同 state。"""
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
                # IQR 矩形(Q1-Q3)
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
        """尽量把界面上的 state 文本转成原始类型(int/float/str)。"""
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
