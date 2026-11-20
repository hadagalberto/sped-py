"""Exportadores: CSV (sem dependências), DataFrames, Parquet e Excel."""

from __future__ import annotations

from sped.exports._common import collect
from sped.exports.csv_export import export_csv
from sped.exports.frames import (
    MissingOptionalDependencyError,
    SpedExport,
    get_dataframe,
    to_dataframes,
    to_excel,
    to_parquet,
)

__all__ = [
    "MissingOptionalDependencyError",
    "SpedExport",
    "collect",
    "export_csv",
    "get_dataframe",
    "to_dataframes",
    "to_excel",
    "to_parquet",
]
