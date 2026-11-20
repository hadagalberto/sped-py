"""sped-py — streaming reader, validator and writer for Brazilian SPED files.

The public API is intentionally small: :func:`read`, :func:`write`,
:func:`load_layout` and the CLI entry point in :mod:`sped.cli`.
"""

from __future__ import annotations

from sped.core.reader import read
from sped.core.writer import write
from sped.layouts import available_versions, load_layout

__all__ = [
    "available_versions",
    "load_layout",
    "read",
    "write",
]

__version__ = "0.1.0"
