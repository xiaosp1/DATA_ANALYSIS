"""S5 Tab 布局 vertical QSplitter 测试 (C037-C #4 反馈)。

约束(与现有 S5 测试一致):
- PySide6 offscreen 模式启动 QApplication;
- 不启动主窗口、不读真实文件;
- 只验证 ``_build_multi_attr_tab`` 之后多变量归因 Tab 内部的布局结构:

  1) ``self._multi_splitter`` 是 ``QSplitter``,orientation = Vertical;
  2) splitter 恰好有 3 个 child(top / middle / bottom);
  3) 3 个 stretch factor 是 3:3:2(top:middle:bottom);
  4) chart1/chart2/chart3 + m1/m2 表格 widget 引用仍然存在且未被改类型
     (确保 ``_fill_multi_attr`` 渲染逻辑不受影响);
  5) tab 仍然能 ``indexOf`` 到 ``multi_attr_widget``(回归保护)。
"""
from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QSplitter  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    yield _app


def _build_panel(app):
    """构造 ProcessAnalysisPanel 实例(会自动调用 _build_multi_attr_tab)。"""
    from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel

    return ProcessAnalysisPanel()


# --------------------------------------------------------------------------
# 1. _multi_splitter 存在且方向是 Vertical
# --------------------------------------------------------------------------

def test_multi_splitter_exists_and_vertical(app):
    """_build_multi_attr_tab 调用后应创建 _multi_splitter (QSplitter, Qt.Vertical)。"""
    p = _build_panel(app)
    sp = getattr(p, "_multi_splitter", None)
    assert sp is not None, "ProcessAnalysisPanel 应在 _build_multi_attr_tab 里创建 _multi_splitter"
    assert isinstance(sp, QSplitter), f"_multi_splitter 必须是 QSplitter,实际 {type(sp).__name__}"
    assert sp.orientation() == Qt.Vertical, (
        f"_multi_splitter 必须是 Qt.Vertical,实际 {sp.orientation()}"
    )


# --------------------------------------------------------------------------
# 2. splitter 含 3 个 child widget (top / middle / bottom)
# --------------------------------------------------------------------------

def test_multi_splitter_has_three_children(app):
    """splitter 必须有 3 个 child(top=chart1+chart2, middle=chart3, bottom=M1/M2 表)。"""
    p = _build_panel(app)
    sp = p._multi_splitter
    assert sp.count() == 3, f"splitter 必须有 3 个 child,实际 {sp.count()}"

    top = sp.widget(0)
    middle = sp.widget(1)
    bottom = sp.widget(2)
    assert top is not None and middle is not None and bottom is not None

    # 引用一致性
    assert top is p._multi_chart_widget_top
    assert middle is p._multi_chart_widget_middle
    assert bottom is p._multi_tables_widget


# --------------------------------------------------------------------------
# 3. 3 个 stretch factor 是 3:3:2
# --------------------------------------------------------------------------

def test_multi_splitter_stretch_factors_3_3_2(app):
    """top:middle:bottom stretch = 3:3:2 (图占大头,表占 2 份)。"""
    p = _build_panel(app)
    sp = p._multi_splitter

    def _stretch(widget) -> int:
        return widget.sizePolicy().verticalStretch()

    assert _stretch(sp.widget(0)) == 3, "top (chart1+chart2) stretch 应为 3"
    assert _stretch(sp.widget(1)) == 3, "middle (chart3) stretch 应为 3"
    assert _stretch(sp.widget(2)) == 2, "bottom (M1/M2) stretch 应为 2"


# --------------------------------------------------------------------------
# 4. chart1/2/3 widget 引用未被破坏 (回归保护: _fill_multi_attr 不能崩)
# --------------------------------------------------------------------------

def test_chart_and_table_widget_refs_preserved(app):
    """chart1/2/3 + m1/m2 表 widget 引用仍然存在且类型未变。"""
    from app.ui.widgets.process_analysis_panel import _MultiChartWidget

    p = _build_panel(app)

    # 3 张图 widget 仍是 _MultiChartWidget
    assert isinstance(p.multi_chart1, _MultiChartWidget)
    assert isinstance(p.multi_chart2, _MultiChartWidget)
    assert isinstance(p.multi_chart3, _MultiChartWidget)

    # chart3 必须在 splitter middle 内(而非 top,确保它是独立的 middle 段)
    sp = p._multi_splitter
    middle = sp.widget(1)
    assert p.multi_chart3.parent() is not None
    # chart3 应该嵌在 middle_widget 内部(中间包了一个 GroupBox)
    # GroupBox -> middle_widget, 故 chart3.parent() 应在 middle_widget 的子树里
    cur = p.multi_chart3.parent()
    while cur is not None:
        if cur is middle:
            break
        cur = cur.parent()
    assert cur is middle, "chart3 必须放在 splitter 的 middle 段(独立 tab 内不再等宽)"

    # M1/M2 表仍在(0 行,因为还没跑归因)
    assert p.multi_m1_table.rowCount() == 0
    assert p.multi_m2_table.rowCount() == 0
    assert p.multi_m1_table.columnCount() == 4
    assert p.multi_m2_table.columnCount() == 5


# --------------------------------------------------------------------------
# 5. 回归保护: S5 Tab 仍然在 result_tabs 里
# --------------------------------------------------------------------------

def test_multi_attr_tab_still_in_result_tabs(app):
    """_build_multi_attr_tab 仍应把 multi_attr_widget 加到 result_tabs。"""
    p = _build_panel(app)
    idx = p.result_tabs.indexOf(p.multi_attr_widget)
    assert idx >= 0, "multi_attr_widget 必须在 result_tabs 里(回归保护)"
    assert p.result_tabs.tabText(idx) == "多变量归因 (S5)"
