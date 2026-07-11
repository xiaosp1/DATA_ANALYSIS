# -*- coding: utf-8 -*-
"""针对 tests/D3_7#_B1_85_0.csv 的服务层综合测试（修正版）"""
import sys
import math
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np

from app.services.file_loader import load_file
from app.services import stats_service, descriptive_service, time_aggregation, data_processing, export_service
from app.models.processing_rule import ProcessingRule
from app.services.data_processor import prepare_multi_y_chart_data, infer_numeric_series, infer_datetime_series

CSV_PATH = PROJECT_ROOT / "tests" / "D3_7#_B1_85_0.csv"

passed = 0
failed = 0
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name} -- {detail}")

# 1. 文件加载
ds = load_file(CSV_PATH)
check("load_file 成功加载 shape=(13575,6)", ds.df.shape == (13575, 6), f"shape={ds.df.shape}")
check("列名识别正确", list(ds.df.columns) == ["时间","虎口距","拇指距","中指距","中点x","中点y"])
numeric_cols = sorted([c for c,m in ds.column_metas.items() if m.is_numeric])
dt_cols = [c for c,m in ds.column_metas.items() if m.is_datetime]
check("数值列识别正确", numeric_cols == sorted(["虎口距","拇指距","中指距","中点x","中点y"]), f"numeric={numeric_cols}")
check("时间列识别为日期时间", "时间" in dt_cols, f"datetime={dt_cols}")
check("所有列缺失计数=0（原文件）", all(m.missing_count == 0 for m in ds.column_metas.values()))

df = ds.df
y_cols = ["虎口距","拇指距","中指距"]

# 2. 基础统计（stats_service）
base_stats = stats_service.calculate_batch_stats(df, y_cols)
check("基础统计条数=3", len(base_stats) == 3)
for r in base_stats:
    check(f"基础统计[{r.column_name}]有效计数=13575", r.count == 13575)
    check(f"基础统计[{r.column_name}]min<max", r.min is not None and r.max is not None and r.max > r.min)
    check(f"基础统计[{r.column_name}]均值在[min,max]", r.min <= r.mean <= r.max)
    check(f"基础统计[{r.column_name}]标准差>0", r.std_dev is not None and r.std_dev > 0)
stats_df = stats_service.stats_to_dataframe(base_stats)
check("stats_to_dataframe 输出 shape=(3,11)", stats_df.shape == (3, 11), f"shape={stats_df.shape}")

# 3. 描述统计（descriptive_service）
desc_results = descriptive_service.batch_descriptive_stats(df, y_cols + ["中点x","中点y"])
check("描述统计条数=5", len(desc_results) == 5)
for r in desc_results:
    check(f"描述统计[{r.column_name}]扩展字段齐全",
          r.count == 13575 and abs(r.missing_rate) < 1e-9 and r.q1 is not None and r.q3 is not None
          and r.iqr is not None and r.cv is not None and r.skewness is not None and r.kurtosis is not None
          and r.p01 is not None and r.p99 is not None)
desc_df = descriptive_service.descriptive_to_dataframe(desc_results)
check("descriptive_to_dataframe 行数=5", desc_df.shape[0] == 5)

qt = descriptive_service.quantile_table(df, y_cols)
check("quantile_table 行数=3", qt.shape[0] == 3)
expected_qcols = ["列名","P0","P1","P5","P25","P50","P75","P95","P99","P100"]
check("quantile_table 列齐全", all(c in qt.columns for c in expected_qcols), f"cols={list(qt.columns)}")
# P0/P100 应等于 min/max
hk = qt[qt["列名"]=="虎口距"].iloc[0]
check("quantile_table 虎口距 P0==min/P100==max",
      abs(float(hk["P0"]) - df["虎口距"].min()) < 1e-4 and abs(float(hk["P100"]) - df["虎口距"].max()) < 1e-4,
      f"P0={hk['P0']}, min={df['虎口距'].min()}; P100={hk['P100']}, max={df['虎口距'].max()}")

# missing_summary 针对数值列应无无效；对非数值列（时间）应报告非数值无效
ms = descriptive_service.missing_summary(df, y_cols)
check("missing_summary(数值列) 总无效数=0", (ms["总无效数"] == 0).all(), ms.to_string())
ms_time = descriptive_service.missing_summary(df, ["时间"])
check("missing_summary(时间列) 非数值=13575", int(ms_time.iloc[0]["非数值无效数"]) == 13575)

corr_p = descriptive_service.correlation_matrix(df, y_cols, method="pearson")
check("Pearson 相关矩阵 3x3 对角线=1", corr_p.shape == (3,3) and abs(corr_p.loc["虎口距","虎口距"] - 1.0) < 1e-9)
check("拇指距-虎口距正相关 r>0.5", corr_p.loc["虎口距","拇指距"] > 0.5, f"r={corr_p.loc['虎口距','拇指距']}")
corr_s = descriptive_service.correlation_matrix(df, y_cols, method="spearman")
check("Spearman 相关矩阵 3x3", corr_s.shape == (3,3))

for col in y_cols:
    d = descriptive_service.distribution_data(df, col, bins=30, iqr_k=1.5)
    check(f"distribution_data[{col}]counts.sum()==13575", int(d.counts.sum()) == 13575)
    check(f"distribution_data[{col}]KDE 长度一致", d.kde_x is None or d.kde_x.size == d.kde_y.size)
    check(f"distribution_data[{col}]IQR 边界包含中位数", d.iqr_lower < d.median < d.iqr_upper,
          f"lo={d.iqr_lower}, med={d.median}, hi={d.iqr_upper}")
    # 离群点：虎口距存在极端值(1230)
    if col == "虎口距":
        check(f"distribution_data[{col}]存在离群点", d.outliers.size > 0, f"outliers={d.outliers.size}")

bs = descriptive_service.boxplot_stats(df, y_cols)
check("boxplot_stats 行数=3 含离群点列", bs.shape[0] == 3 and "离群点数" in bs.columns)
check("boxplot_stats 虎口距有离群点", int(bs[bs["列名"]=="虎口距"].iloc[0]["离群点数"]) > 0)

# 4. prepare_multi_y_chart_data
work, mean_map, is_dt, messages = prepare_multi_y_chart_data(df, "时间", y_cols)
check("prepare_multi_y_chart_data 时间轴=True", is_dt is True)
check("prepare_multi_y_chart_data mean_map 覆盖 3 列", set(mean_map.keys()) == set(y_cols))
check("prepare_multi_y_chart_data 按时间排序", work["时间"].is_monotonic_increasing)
check("prepare_multi_y_chart_data 行数=13575", work.shape[0] == 13575)

# 5. 时间聚合
for gran in ["原始","分钟","小时","班次","天","周"]:
    agg, logs, is_dt2, xname = time_aggregation.aggregate_by_time(df, "时间", y_cols, gran)
    check(f"aggregate_by_time[{gran}] 非空且为时间轴", (not agg.empty) and is_dt2, f"rows={agg.shape[0]}")
    check(f"aggregate_by_time[{gran}] Y列保留", all(c in agg.columns for c in y_cols))
agg_min, _, _, _ = time_aggregation.aggregate_by_time(df, "时间", y_cols, "分钟")
check("分钟聚合行数 <= 原始", agg_min.shape[0] <= 13575, f"agg_min={agg_min.shape[0]}")
agg_shift, _, _, _ = time_aggregation.aggregate_by_time(df, "时间", y_cols, "班次")
check("班次聚合行数显著减少(< 50)", agg_shift.shape[0] < 50, f"shift_rows={agg_shift.shape[0]}")
agg_day, _, _, _ = time_aggregation.aggregate_by_time(df, "时间", y_cols, "天")
check("天聚合行数在 1-5 之间（数据覆盖约 3 天）", 1 <= agg_day.shape[0] <= 5, f"day_rows={agg_day.shape[0]}")
agg_hour, _, _, _ = time_aggregation.aggregate_by_time(df, "时间", y_cols, "小时")
check("小时聚合行数小于等于 24*天数", agg_hour.shape[0] <= 24*5, f"hour_rows={agg_hour.shape[0]}")
# 非法粒度应抛异常
try:
    time_aggregation.aggregate_by_time(df, "时间", y_cols, "不存在的粒度")
    raised = False
except ValueError:
    raised = True
check("非法粒度抛 ValueError", raised)
# 不存在时间列应抛 KeyError
try:
    time_aggregation.aggregate_by_time(df, "不存在列", y_cols, "分钟")
    raised2 = False
except KeyError:
    raised2 = True
check("不存在时间列抛 KeyError", raised2)

# 6. 数据处理规则
# delete_row：虎口距 > 500 应删除（最大值 1230）
rules_del = [ProcessingRule(column="虎口距", operator="gt", threshold="500", action="delete_row")]
pdf1, logs1 = data_processing.apply_rules(df, rules_del)
del_count = 13575 - pdf1.shape[0]
check("apply_rules delete_row：虎口距>500 删除行数>0", del_count > 0, f"del={del_count}")
# replace_mean：中指距 > 1050 替换为均值
m_before = float(pd.to_numeric(df["中指距"], errors="coerce").mean())
n_gt = int((pd.to_numeric(df["中指距"], errors="coerce") > 1050).sum())
rules_rep = [ProcessingRule(column="中指距", operator="gt", threshold="1050", action="replace_mean")]
pdf2, logs2 = data_processing.apply_rules(df, rules_rep)
max_after = float(pd.to_numeric(pdf2["中指距"], errors="coerce").max())
check("apply_rules replace_mean：中指距>1050 替换触发", n_gt > 0, f"n_gt={n_gt}")
check("apply_rules replace_mean：替换后最大值<=1050", max_after <= 1050 + 1e-6, f"max_after={max_after}")
check("apply_rules replace_mean：行数不变", pdf2.shape[0] == 13575)
# 规则不存在的列
pdf3, logs3 = data_processing.apply_rules(df, [ProcessingRule(column="不存在列", operator="gt", threshold="1", action="delete_row")])
check("apply_rules 缺列跳过，行数不变", pdf3.shape[0] == 13575 and any("不存在" in l for l in logs3))
# is_null/not_null 规则
pdf4, logs4 = data_processing.apply_rules(df, [ProcessingRule(column="中指距", operator="is_null", threshold="", action="delete_row")])
check("is_null 规则：无缺失不删行", pdf4.shape[0] == 13575)

# 7. 导出
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    csv_out = td / "desc_stats.csv"
    xlsx_out = td / "desc_stats.xlsx"
    export_service.export_stats_to_csv(desc_df, csv_out)
    export_service.export_stats_to_excel(desc_df, xlsx_out)
    check("export_stats_to_csv 非空", csv_out.exists() and csv_out.stat().st_size > 0)
    check("export_stats_to_excel 非空", xlsx_out.exists() and xlsx_out.stat().st_size > 0)
    back = pd.read_csv(csv_out, encoding="utf-8-sig")
    check("CSV 回读列名一致", list(back.columns) == list(desc_df.columns))
    back_x = pd.read_excel(xlsx_out)
    check("Excel 回读行数一致", back_x.shape[0] == desc_df.shape[0])

# 8. 类型推断
num, inv = infer_numeric_series(df["虎口距"])
check("infer_numeric_series 虎口距 无无效值", inv == 0)
dt_s = infer_datetime_series(df["时间"])
check("infer_datetime_series 时间列全部解析", dt_s.notna().all() and dt_s.shape[0] == 13575)

print("----")
print(f"PASSED: {passed}  FAILED: {failed}")
sys.exit(0 if failed == 0 else 1)
