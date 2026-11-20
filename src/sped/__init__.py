"""sped-py — streaming reader, validator, writer and analyser for Brazilian SPED files.

Public API: :func:`read`, :func:`write`, :func:`load_layout`,
:func:`detect_layout`, :class:`~sped.core.hierarchy.RecordTree`,
:class:`~sped.core.index.IndexedReader`, :func:`validate`,
:func:`summarize_file`, :func:`compute_apuracao`, :func:`diff_files`,
:func:`merge_files`, :func:`split_file` and :class:`~sped.exports.SpedExport`.
"""

from __future__ import annotations

from sped.analysis import (
    ApuracaoResult,
    compute_apuracao,
    diff_files,
    merge_files,
    recompute_apuracao,
    split_file,
    summarize_file,
)
from sped.core.hierarchy import RecordTree
from sped.core.index import IndexedReader
from sped.core.reader import read
from sped.core.writer import write
from sped.exports import SpedExport, export_csv, to_dataframes, to_excel, to_parquet
from sped.layouts import (
    OBRIGACOES,
    available_versions,
    detect_cod_ver,
    detect_layout,
    detect_obrigacao,
    load_layout,
)
from sped.validation import ValidationIssue, validate

__all__ = [
    "OBRIGACOES",
    "ApuracaoResult",
    "IndexedReader",
    "RecordTree",
    "SpedExport",
    "ValidationIssue",
    "available_versions",
    "compute_apuracao",
    "detect_cod_ver",
    "detect_layout",
    "detect_obrigacao",
    "diff_files",
    "export_csv",
    "load_layout",
    "merge_files",
    "read",
    "recompute_apuracao",
    "split_file",
    "summarize_file",
    "to_dataframes",
    "to_excel",
    "to_parquet",
    "validate",
    "write",
]

__version__ = "0.4.0"
