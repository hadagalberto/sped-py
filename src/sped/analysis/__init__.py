"""Auxiliares de análise: resumos, apuração, diff e mesclagem/divisão.

Todas as fórmulas de apuração são reutilizadas de ``sped.validation.totals``,
que cita os manuais oficiais. Nenhuma regra é inventada neste pacote.
"""

from __future__ import annotations

from sped.analysis.apuracao import (
    ApuracaoField,
    ApuracaoResult,
    compute_apuracao,
    recompute_apuracao,
)
from sped.analysis.diff import DiffEntry, FileDiff, diff_files
from sped.analysis.merge import merge_files
from sped.analysis.periods import Period, format_date, parse_date, split_periods
from sped.analysis.split import split_file
from sped.analysis.summaries import (
    DEFAULT_DIMENSIONS,
    TOTAL_FIELDS,
    Summary,
    SummaryRow,
    summarize,
    summarize_all,
    summarize_file,
)

__all__ = [
    "DEFAULT_DIMENSIONS",
    "TOTAL_FIELDS",
    "ApuracaoField",
    "ApuracaoResult",
    "DiffEntry",
    "FileDiff",
    "Period",
    "Summary",
    "SummaryRow",
    "compute_apuracao",
    "diff_files",
    "format_date",
    "merge_files",
    "parse_date",
    "recompute_apuracao",
    "split_file",
    "split_periods",
    "summarize",
    "summarize_all",
    "summarize_file",
]
