"""sped-py — streaming reader, validator and writer for Brazilian SPED files.

Public API: :func:`read`, :func:`write`, :func:`load_layout`,
:func:`detect_layout`, :class:`~sped.core.hierarchy.RecordTree` and
:class:`~sped.core.index.IndexedReader`.
"""

from __future__ import annotations

from sped.core.hierarchy import RecordTree
from sped.core.index import IndexedReader
from sped.core.reader import read
from sped.core.writer import write
from sped.layouts import (
    OBRIGACOES,
    available_versions,
    detect_cod_ver,
    detect_layout,
    detect_obrigacao,
    load_layout,
)

__all__ = [
    "OBRIGACOES",
    "IndexedReader",
    "RecordTree",
    "available_versions",
    "detect_cod_ver",
    "detect_layout",
    "detect_obrigacao",
    "load_layout",
    "read",
    "write",
]

__version__ = "0.2.0"
