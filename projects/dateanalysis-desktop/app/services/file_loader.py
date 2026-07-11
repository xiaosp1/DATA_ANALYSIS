from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from app.models.dataset import ColumnMeta, DataSet


class FileLoadError(Exception):
    pass


def _read_csv_fallback(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "gbk", "gb18030"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
        except Exception as exc:
            raise FileLoadError(f"读取 CSV 失败：{exc}") from exc
    raise FileLoadError(f"CSV 编码无法识别：{last_error}")


def _read_excel(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".xlsx":
            return pd.read_excel(path, engine="openpyxl")
        if suffix == ".xls":
            return pd.read_excel(path)
        raise FileLoadError(f"不支持的 Excel 扩展名：{suffix}")
    except ImportError as exc:
        raise FileLoadError(f"缺少 Excel 读取依赖：{exc}") from exc
    except Exception as exc:
        raise FileLoadError(f"读取 Excel 失败：{exc}") from exc


def _looks_like_datetime(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    non_null = series.dropna()
    if non_null.empty:
        return False
    if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
        return False
    sample_count = min(20, len(non_null))
    sample = non_null.head(sample_count)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        converted = pd.to_datetime(sample, errors="coerce")
    if converted.isna().all():
        return False
    valid_ratio = converted.notna().sum() / max(1, len(sample))
    name_hint = any(key in str(series.name).lower() for key in ["date", "time", "日期", "时间"])
    return valid_ratio >= 0.8 or (name_hint and valid_ratio >= 0.6)


def _build_column_meta(df: pd.DataFrame) -> dict[str, ColumnMeta]:
    metas: dict[str, ColumnMeta] = {}
    for col in df.columns:
        series = df[col]
        is_numeric = pd.api.types.is_numeric_dtype(series)
        is_datetime = pd.api.types.is_datetime64_any_dtype(series) or _looks_like_datetime(series)
        sample = [v for v in series.dropna().head(3).tolist()]
        metas[str(col)] = ColumnMeta(
            name=str(col),
            dtype=str(series.dtype),
            is_numeric=bool(is_numeric),
            is_datetime=bool(is_datetime),
            missing_count=int(series.isna().sum()),
            sample_values=sample,
        )
    return metas


def load_file(path: str | Path, has_header: bool = True) -> DataSet:
    file_path = Path(path)
    if not file_path.exists():
        raise FileLoadError("文件不存在")
    suffix = file_path.suffix.lower()

    try:
        if suffix == ".csv":
            if has_header:
                df = _read_csv_fallback(file_path)
            else:
                df = _read_csv_fallback_no_header(file_path)
        elif suffix in {".xlsx", ".xls"}:
            if has_header:
                df = _read_excel(file_path)
            else:
                df = _read_excel_no_header(file_path)
        else:
            raise FileLoadError(f"暂不支持的文件格式：{suffix}")
    except FileLoadError:
        raise
    except Exception as exc:
        raise FileLoadError(f"读取文件失败：{exc}") from exc

    df.columns = [str(c) for c in df.columns]
    return DataSet(
        file_name=file_path.name,
        file_path=str(file_path),
        df=df,
        column_metas=_build_column_meta(df),
    )


def _read_csv_fallback_no_header(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "gbk", "gb18030"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding, header=None)
        except UnicodeDecodeError as exc:
            last_error = exc
        except Exception as exc:
            raise FileLoadError(f"读取 CSV 失败：{exc}") from exc
    raise FileLoadError(f"CSV 编码无法识别：{last_error}")


def _read_excel_no_header(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".xlsx":
            return pd.read_excel(path, engine="openpyxl", header=None)
        if suffix == ".xls":
            return pd.read_excel(path, header=None)
        raise FileLoadError(f"不支持的 Excel 扩展名：{suffix}")
    except ImportError as exc:
        raise FileLoadError(f"缺少 Excel 读取依赖：{exc}") from exc
    except Exception as exc:
        raise FileLoadError(f"读取 Excel 失败：{exc}") from exc
