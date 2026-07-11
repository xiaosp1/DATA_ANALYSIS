# -*- coding: utf-8 -*-
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from app.services.descriptive_service import (
    batch_descriptive_stats,
    boxplot_stats,
    calculate_descriptive_stats,
    correlation_matrix,
    distribution_data,
    missing_summary,
    quantile_table,
)


def test_basic_stats():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
    r = calculate_descriptive_stats(df, "x")
    assert r.count == 5
    assert r.missing_count == 0
    assert r.max == 5.0
    assert r.min == 1.0
    assert math.isclose(r.mean, 3.0)
    assert math.isclose(r.median, 3.0)
    assert math.isclose(r.q1, 2.0)
    assert math.isclose(r.q3, 4.0)
    assert math.isclose(r.iqr, 2.0)
    assert r.skewness == 0.0
    # 样本方差 = 2.5, 样本标准差 = sqrt(2.5)
    assert math.isclose(r.variance, 2.5)
    assert math.isclose(r.std_dev, math.sqrt(2.5))


def test_missing_and_invalid():
    df = pd.DataFrame({"x": [1.0, None, "a", 4.0]})
    r = calculate_descriptive_stats(df, "x")
    assert r.count == 2
    # missing_count counts NaN + non-numeric
    assert r.missing_count == 2
    assert r.missing_rate == 0.5


def test_constant_column_cv_is_none():
    df = pd.DataFrame({"x": [2.0, 2.0, 2.0, 2.0]})
    r = calculate_descriptive_stats(df, "x")
    assert r.mean == 2.0
    assert r.cv is None or r.cv == 0.0  # avoid div-by-zero; our impl returns None


def test_empty_column_returns_empty_result():
    df = pd.DataFrame({"x": [None, None]})
    r = calculate_descriptive_stats(df, "x")
    assert r.count == 0
    assert r.mean is None
    assert r.max is None


def test_quantile_table_shape():
    df = pd.DataFrame({"x": list(range(101))})
    qt = quantile_table(df, ["x"])
    assert "列名" in qt.columns
    assert qt.iloc[0]["P0"] != "-"
    assert qt.iloc[0]["P100"] != "-"


def test_correlation_identity_and_sign():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [2, 4, 6, 8, 10]})
    corr = correlation_matrix(df, ["a", "b"], method="pearson")
    assert corr.shape == (2, 2)
    assert abs(corr.loc["a", "b"] - 1.0) < 1e-9


def test_distribution_data_outliers():
    # b has a single outlier 200 over values 9-15
    df = pd.DataFrame({"b": [10, 12, 11, 13, 15, 9, 200]})
    d = distribution_data(df, "b", bins=8)
    assert d.outliers.size >= 1
    assert d.q1 is not None and d.q3 is not None
    assert d.median is not None
    assert d.counts.sum() == 7
    if d.kde_x is not None:
        assert d.kde_x.size == d.kde_y.size


def test_missing_summary_counters():
    df = pd.DataFrame({"x": [1, None, "bad", 4], "y": [1, 2, 3, 4]})
    ms = missing_summary(df, ["x", "y"])
    row_x = ms[ms["列名"] == "x"].iloc[0]
    assert row_x["缺失值(空)"] == 1
    assert row_x["非数值无效数"] == 1
    assert row_x["总无效数"] == 2
    row_y = ms[ms["列名"] == "y"].iloc[0]
    assert row_y["总无效数"] == 0


def test_boxplot_stats_has_outlier_flag():
    df = pd.DataFrame({"b": [10, 12, 11, 13, 15, 9, 200]})
    bs = boxplot_stats(df, ["b"])
    assert int(bs.iloc[0]["离群点数"]) >= 1


if __name__ == "__main__":
    test_basic_stats()
    test_missing_and_invalid()
    test_constant_column_cv_is_none()
    test_empty_column_returns_empty_result()
    test_quantile_table_shape()
    test_correlation_identity_and_sign()
    test_distribution_data_outliers()
    test_missing_summary_counters()
    test_boxplot_stats_has_outlier_flag()
    print("all tests passed")

