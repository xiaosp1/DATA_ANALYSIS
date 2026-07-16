# -*- coding: utf-8 -*-
"""UI smoke test v7 (V1.7): single-category baseline + cross-category contract chart.

- Sets QT_QPA_PLATFORM=offscreen before any PySide6 import.
- sys.path / CSV_PATH / OUT use Path(__file__).parents[1] (no E:\\ hardcoding).
- Smoke principle: no exception == pass.
"""
import os
import sys
import time
import traceback
import uuid
import warnings
from datetime import datetime
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # MUST precede PySide6 import

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest

from app.models.dataset_item import DatasetItem
from app.services.data_processing import scale_datasets_by_category
from app.services.export_service import export_stats_to_csv, export_stats_to_excel, export_plot_widget_to_png
from app.ui.main_window import MainWindow

CSV = PROJECT_ROOT / "tests" / "D3_7#_B1_85_0.csv"
OUT = PROJECT_ROOT / "tests" / "ui_smoke_out"
if OUT.exists():
    for p in OUT.rglob("*"):
        if p.is_file():
            try:
                p.unlink()
            except Exception:
                pass
OUT.mkdir(parents=True, exist_ok=True)

Y = ["虎口距", "拇指距", "中指距"]
GRANULARITIES = ["原始", "分钟", "小时", "班次", "天", "周"]


def _safe_disconnect_changed(combo):
    """Silence PySide6 RuntimeWarning on no-op disconnect.

    PySide6 prints a C-level RuntimeWarning ("Failed to disconnect (None)")
    when disconnect() is called with no remaining receivers; a plain try/except
    cannot catch it because it is emitted directly from Qt. We wrap the call in
    `warnings.catch_warnings` + a generous try/except so the smoke-test log
    stays clean. Functionality is unchanged: we only want to drop the auto-
    refresh lambda that MainWindow wires once at startup before our script
    drives the combo programmatically.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            combo.currentIndexChanged.disconnect()
    except Exception:
        pass


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def wait_idle(w, timeout=60000, step=50):
    end = time.time() + timeout / 1000
    while time.time() < end:
        QTest.qWait(step)
        for tl in QApplication.topLevelWidgets():
            if isinstance(tl, QMessageBox) and tl.isVisible():
                log(f"(auto-close dialog: {tl.windowTitle()} - {tl.text()[:60]})")
                tl.accept()
        if not w._dataset_busy and not w._analysis_busy:
            return True
    return False


def sel_text(combo, text):
    i = combo.findText(text)
    assert i >= 0, f"combo item not found: {text}"
    combo.setCurrentIndex(i)


def sel_data(combo, data):
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            combo.setCurrentIndex(i)
            return True
    return False


def grab_to(widget, path, min_size=5000):
    QTest.qWait(300)
    widget.repaint()
    QTest.qWait(100)
    pix = widget.grab()
    ok = pix.save(str(path), "PNG")
    sz = path.stat().st_size if path.exists() else 0
    assert ok and sz > min_size, f"grab failed {path} size={sz}"


def curve_count(w):
    return len(w.chart_panel.plot_widget.plotItem.listDataItems())


def run_and_wait(w, trigger):
    trigger()
    assert wait_idle(w, timeout=60000), "background task did not finish"


def activate_item_by_name(w, name_substr):
    """Activate dataset programmatically (synchronous UI refresh, no background)."""
    target = None
    for it in w._manager.items():
        if name_substr in it.name:
            target = it
    assert target is not None, f"dataset containing {name_substr!r} not found"
    w._manager.set_active(target.dataset_id)
    w._cache_columns_for(target)
    w.data_panel.set_dataframe(target.df)
    w.chart_panel.clear()
    w.desc_charts_panel.clear()
    w._desc_tables = {}
    w._stats_df = None
    w.stats_panel.clear_tables()
    w.stats_panel.set_table(
        "综合统计",
        pd.DataFrame(columns=["列名", "有效计数", "缺失值", "最大值", "最小值",
                               "平均值", "中位数", "求和", "方差", "标准差", "极差"]),
    )
    w._refresh_dataset_ui()
    QTest.qWait(50)
    return target


# ---------------------------------------------------------------------------
# Single-category path (V1.6.1 baseline, kept intact)
# ---------------------------------------------------------------------------
def run_single_category_path(w):
    log("===== [1/2] single-category path =====")
    r = w._worker_import([str(CSV)])
    assert not r["errors"], r["errors"]
    w._on_import_done(r)
    QTest.qWait(100)
    assert w._manager.active_item().df.shape == (13575, 6)
    log("import OK")

    w.mode_desc_button.setChecked(True)
    w._on_mode_changed(1)
    QTest.qWait(100)
    dp = w.descriptive_panel
    dp._clear_selection()
    for i in range(dp.col_list.count()):
        it = dp.col_list.item(i)
        if it.text() in Y:
            it.setSelected(True)
    dp.bins_spin.setValue(30)
    dp.kde_check.setChecked(True)
    dp.mean_check.setChecked(True)
    dp.median_check.setChecked(True)
    dp.qq_check.setChecked(True)
    dp.scatter_check.setChecked(False)
    sel_data(dp.corr_combo, "pearson")
    dp.iqr_k_spin.setValue(1.5)
    cfg = dp.config()
    assert set(cfg["columns"]) == set(Y)
    log("running descriptive stats ...")
    t0 = time.time()
    run_and_wait(w, lambda: w._run_descriptive_analysis(cfg))
    assert "综合统计" in w._desc_tables and not w._desc_tables["综合统计"].empty
    log(f"descriptive OK in {(time.time()-t0)*1000:.0f} ms")

    for idx, name in {0: "0_desc_hist", 1: "1_desc_box", 2: "2_desc_qq", 3: "3_desc_corr"}.items():
        w.desc_charts_panel.tabs.setCurrentIndex(idx)
        w.chart_tabs.setCurrentIndex(1)
        QTest.qWait(500)
        grab_to(w, OUT / f"{name}.png", min_size=10000)
    log("descriptive screenshots OK")

    csv_out = OUT / "desc_stats.csv"
    xlsx_out = OUT / "desc_stats.xlsx"
    export_stats_to_csv(w._desc_tables["综合统计"], csv_out)
    export_stats_to_excel(w._desc_tables["综合统计"], xlsx_out)
    assert csv_out.exists() and xlsx_out.exists()
    log("descriptive export OK")

    w.mode_trend_button.setChecked(True)
    w._on_mode_changed(0)
    QTest.qWait(100)
    _safe_disconnect_changed(w.chart_options_panel.granularity_combo)
    cp = w.chart_config_panel
    cop = w.chart_options_panel
    sel_text(cp.x_combo, "时间")
    for n, wg in cp._y_widgets.items():
        wg.checkbox.setChecked(n in Y)
        wg.mean_checkbox.setChecked(n in Y)
    cp.show_points_check.setChecked(True)
    cp.show_mean_check.setChecked(True)

    for gran in ["原始", "分钟", "班次"]:
        # disconnect auto-refresh to avoid double-start / busy-lock conflict
        try:
            w.chart_options_panel.granularity_combo.currentIndexChanged.disconnect()
        except Exception:
            pass
        sel_text(cop.granularity_combo, gran)
        QTest.qWait(50)
        log(f"plot[{gran}] ...")
        run_and_wait(w, lambda gran=gran: w._run_chart_only())
        assert curve_count(w) >= 1, f"plot[{gran}] has no curves"
        QTest.qWait(500)
        grab_to(w, OUT / f"trend_{gran}.png", min_size=10000)
        log(f"plot[{gran}] OK curves={curve_count(w)}")

    pp = w.processing_panel
    pp._clear_rules()
    QTest.qWait(50)
    sel_text(pp.column_combo, "虎口距")
    sel_data(pp.operator_combo, "gt")
    pp.threshold_spin.setValue(500.0)
    sel_data(pp.action_combo, "delete_row")
    pp.add_rule_button.click()
    QTest.qWait(50)
    assert len(pp._rules) == 1
    before = w._manager.active_item().df.shape[0]
    log("applying processing ...")
    run_and_wait(w, lambda: w._apply_processing(list(pp._rules)))
    assert w._manager.active_item() is not None and w._manager.active_item().kind == "processed"
    after = w._manager.active_item().df.shape[0]
    assert after < before
    log(f"processing OK rows {before}->{after}")
    QTest.qWait(200)

    w.mode_desc_button.setChecked(True)
    w._on_mode_changed(1)
    QTest.qWait(100)
    cfg2 = w.descriptive_panel.config()
    assert cfg2["columns"]
    run_and_wait(w, lambda: w._run_descriptive_analysis(cfg2))
    assert "综合统计" in w._desc_tables and not w._desc_tables["综合统计"].empty
    log("post-processing descriptive OK")

    w._clear_all()
    QTest.qWait(200)
    assert w._manager.active_item() is None and curve_count(w) == 0
    log("single-category cleared OK")


# ---------------------------------------------------------------------------
# Cross-category path (V1.7 new)
# ---------------------------------------------------------------------------
def _make_head_df(n=60, seed=1):
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2026-07-10 08:00:00")
    times = pd.date_range(t0, periods=n, freq="min")
    return pd.DataFrame({
        "时间": times,
        "脱模力": 100 + np.cumsum(rng.normal(0, 1, n)),
        "主缸压力": 200 + np.cumsum(rng.normal(0, 2, n)),
    })


def _make_tail_df(n=70, seed=2):
    rng = np.random.default_rng(seed)
    # tail starts 10min earlier and ends 20min later than head => overlap + lead/lag
    t0 = pd.Timestamp("2026-07-10 07:50:00")
    times = pd.date_range(t0, periods=n, freq="min")
    return pd.DataFrame({
        "时间": times,
        "振动加速度": 1.0 + rng.normal(0, 0.1, n).cumsum() * 0.05,
        "尾温": 60 + rng.normal(0, 0.3, n).cumsum(),
    })


def _add_category_direct(w, df, name, category, factor):
    """Bypass file dialog / file IO; add an original-like dataset directly."""
    item = DatasetItem(
        dataset_id=str(uuid.uuid4()),
        name=name,
        kind="original",
        df=df.copy(),
        source_files=["<ui-smoke-memory>"],
        created_at=datetime.now(),
        can_delete=False,
        metadata={},
        category=category,
        pixel_factor=float(factor),
        scaled=False,
    )
    w._manager._items[item.dataset_id] = item
    if w._manager._active_id is None:
        w._manager._active_id = item.dataset_id
    w._manager._notify()
    return item


def run_cross_category_path(w):
    log("===== [2/2] cross-category path =====")
    head_df = _make_head_df()
    tail_df = _make_tail_df()
    log(f"synthesized head={head_df.shape}, tail={tail_df.shape}")

    h = _add_category_direct(w, head_df, "smoke_head.csv", "head", factor=0.5)
    t = _add_category_direct(w, tail_df, "smoke_tail.csv", "tail", factor=0.25)
    log(f"programmatic add head={h.dataset_id[:8]} tail={t.dataset_id[:8]}")
    QTest.qWait(50)

    w._merge_by_category("head")
    w._merge_by_category("tail")
    w._merge_cross_category()
    QTest.qWait(100)

    cross = activate_item_by_name(w, "跨类合并")
    log(f"activated cross-merged dataset: {cross.name} shape={cross.df.shape}")
    assert "时间" in cross.df.columns
    head_cols = [c for c in cross.df.columns if str(c).startswith("[机头]")]
    tail_cols = [c for c in cross.df.columns if str(c).startswith("[机尾]")]
    assert head_cols and tail_cols, f"prefix columns missing: head={head_cols}, tail={tail_cols}"
    log(f"cross columns: head={head_cols}, tail={tail_cols}")

    w.mode_trend_button.setChecked(True)
    w._on_mode_changed(0)
    QTest.qWait(100)
    _safe_disconnect_changed(w.chart_options_panel.granularity_combo)
    cp = w.chart_config_panel
    cop = w.chart_options_panel
    sel_text(cp.x_combo, "时间")
    pick_head = head_cols[0]
    pick_tail = tail_cols[0]
    for n, wg in cp._y_widgets.items():
        wg.checkbox.setChecked(n in (pick_head, pick_tail))
        wg.mean_checkbox.setChecked(False)
    cp.show_points_check.setChecked(False)
    cp.show_mean_check.setChecked(False)
    log(f"selected Y: {pick_head} + {pick_tail}")

    for gran in GRANULARITIES:
        try:
            w.chart_options_panel.granularity_combo.currentIndexChanged.disconnect()
        except Exception:
            pass
        sel_text(cop.granularity_combo, gran)
        QTest.qWait(30)
        log(f"cross-plot[{gran}] ...")
        run_and_wait(w, lambda gran=gran: w._run_chart_only())
        log(f"cross-plot[{gran}] OK curves={curve_count(w)}")
    log("cross 6 granularities all passed (no exception)")

    w.mode_desc_button.setChecked(True)
    w._on_mode_changed(1)
    QTest.qWait(100)
    dp = w.descriptive_panel
    dp._clear_selection()
    want = [str(pick_head), str(pick_tail)]
    for i in range(dp.col_list.count()):
        it = dp.col_list.item(i)
        if it.text() in want:
            it.setSelected(True)
    cfg = dp.config()
    assert set(want).issubset(set(cfg["columns"])), f"desc column selection wrong: {cfg['columns']}"
    log(f"cross-descriptive columns={cfg['columns']}")
    run_and_wait(w, lambda: w._run_descriptive_analysis(cfg))
    assert "综合统计" in w._desc_tables and not w._desc_tables["综合统计"].empty
    log("cross descriptive OK")

    ncols_before = len(h.df.columns)
    logs = scale_datasets_by_category(
        w._manager, "head", factor=0.5,
        exclude_mode="auto", exclude_columns=["时间"],
    )
    for msg in logs:
        log(f"[scale] {msg}")
    ncols_after = len(h.df.columns)
    assert ncols_after == ncols_before, f"column count changed after batch scale: {ncols_before}->{ncols_after}"
    mm_cols = [c for c in h.df.columns if "(mm)" in str(c)]
    assert mm_cols, f"no (mm) column after batch scale: {list(h.df.columns)}"
    log(f"head batch scale OK (mm) cols: {mm_cols}")

    # --- V1.8 P1-W4③：跨类导出冒烟 ---
    # 跨类合并可能在 head 缩放后重新生成（会带 [机头]xxx(mm) 前缀+后缀），所以重新 merge 一次确保最新状态
    w._merge_cross_category()
    QTest.qWait(100)
    cross = activate_item_by_name(w, "跨类合并")
    log(f"re-activated cross for export: {cross.name} shape={cross.df.shape}")

    # 1) 趋势图：X=时间，Y 选一个 [机头] 列 + 一个 [机尾] 列，粒度=原始
    w.mode_trend_button.setChecked(True)
    w._on_mode_changed(0)
    QTest.qWait(100)
    _safe_disconnect_changed(w.chart_options_panel.granularity_combo)
    cp = w.chart_config_panel
    cop = w.chart_options_panel
    sel_text(cp.x_combo, "时间")
    cross_head_cols = [c for c in cross.df.columns if str(c).startswith("[机头]")]
    cross_tail_cols = [c for c in cross.df.columns if str(c).startswith("[机尾]")]
    assert cross_head_cols and cross_tail_cols, f"missing prefix cols in cross: head={cross_head_cols} tail={cross_tail_cols}"
    pick_h = cross_head_cols[0]
    pick_t = cross_tail_cols[0]
    for n, wg in cp._y_widgets.items():
        wg.checkbox.setChecked(n in (pick_h, pick_t))
        wg.mean_checkbox.setChecked(False)
    cp.show_points_check.setChecked(False)
    cp.show_mean_check.setChecked(False)
    sel_text(cop.granularity_combo, "原始")
    QTest.qWait(30)
    run_and_wait(w, lambda: w._run_chart_only())
    assert curve_count(w) >= 2, f"cross chart expected >=2 curves, got {curve_count(w)}"
    QTest.qWait(300)

    # 导出当前图表 PNG
    cross_png = OUT / "cross_trend.png"
    export_plot_widget_to_png(w.chart_panel.plot_widget, str(cross_png))
    assert cross_png.exists() and cross_png.stat().st_size > 5000, f"cross PNG missing or too small: {cross_png}"
    log(f"cross chart PNG OK: {cross_png.name} size={cross_png.stat().st_size}")

    # 2) 描述统计导出 CSV / XLSX
    w.mode_desc_button.setChecked(True)
    w._on_mode_changed(1)
    QTest.qWait(100)
    dp = w.descriptive_panel
    dp._clear_selection()
    cross_desc_cols = [str(pick_h), str(pick_t)]
    for i in range(dp.col_list.count()):
        it = dp.col_list.item(i)
        if it.text() in cross_desc_cols:
            it.setSelected(True)
    cfg_cross = dp.config()
    assert set(cross_desc_cols).issubset(set(cfg_cross["columns"]))
    run_and_wait(w, lambda: w._run_descriptive_analysis(cfg_cross))
    assert "综合统计" in w._desc_tables and not w._desc_tables["综合统计"].empty
    cross_desc_csv = OUT / "cross_desc_stats.csv"
    cross_desc_xlsx = OUT / "cross_desc_stats.xlsx"
    export_stats_to_csv(w._desc_tables["综合统计"], str(cross_desc_csv))
    export_stats_to_excel(w._desc_tables["综合统计"], str(cross_desc_xlsx))
    assert cross_desc_csv.exists() and cross_desc_csv.stat().st_size > 20
    assert cross_desc_xlsx.exists() and cross_desc_xlsx.stat().st_size > 20
    log(f"cross descriptive export OK: csv={cross_desc_csv.stat().st_size} xlsx={cross_desc_xlsx.stat().st_size}")

    # 3) 跨类合并数据集 CSV / XLSX
    cross_csv = OUT / "cross_dataset.csv"
    cross_xlsx = OUT / "cross_dataset.xlsx"
    export_stats_to_csv(cross.df, str(cross_csv))
    export_stats_to_excel(cross.df, str(cross_xlsx))
    assert cross_csv.exists() and cross_csv.stat().st_size > 20
    assert cross_xlsx.exists() and cross_xlsx.stat().st_size > 20
    log(f"cross dataset export OK: csv={cross_csv.stat().st_size} xlsx={cross_xlsx.stat().st_size}")

    w._clear_all()
    QTest.qWait(200)
    assert w._manager.active_item() is None and curve_count(w) == 0
    log("cross-category cleared OK")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    QTest.qWait(300)
    log("window created")
    try:
        run_single_category_path(w)
        run_cross_category_path(w)
    except Exception:
        traceback.print_exc()
        return 1
    log("===== UI smoke (single+cross) ALL PASSED =====")
    return 0


def test_ui_smoke_offscreen():
    """Pytest entry point (offscreen): single-category + cross-category paths.

    Builds its own QApplication (QT_QPA_PLATFORM=offscreen is set at module top)
    so we don't require pytest-qt.
    """
    rc = main()
    assert rc == 0, f"ui_smoke exited with code {rc}"


if __name__ == "__main__":
    sys.exit(main())
