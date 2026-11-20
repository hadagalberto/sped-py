"""Resolução de fonte compartilhada pelos exportadores."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sped.core.reader import SpedReader
from sped.core.types import Layout, Record
from sped.layouts import detect_layout

Source = str | Path | Iterable[Record]


def resolve_source(source: Source, layout: Layout | None = None) -> tuple[Layout, Iterable[Record]]:
    """Devolve ``(layout, registros)`` para um caminho ou um iterável de registros."""
    if isinstance(source, (str, Path)):
        chosen = layout or detect_layout(source)
        return chosen, SpedReader(source, layout=chosen, strict=False).iter_records()
    if layout is None:
        raise ValueError("layout é obrigatório quando a fonte é um iterável de registros")
    return layout, source


def collect(
    source: Source, layout: Layout | None = None
) -> tuple[Layout, dict[str, list[tuple[str, ...]]]]:
    """Agrupa valores crus por código de registro (uma passada)."""
    chosen, records = resolve_source(source, layout)
    grouped: dict[str, list[tuple[str, ...]]] = {}
    for record in records:
        grouped.setdefault(record.code, []).append(record.raw_values)
    return chosen, grouped


def columns(layout: Layout, code: str) -> list[str]:
    """Nomes das colunas publicados para ``code``."""
    return list(layout.register(code).field_names)


def frame_columns(layout: Layout, code: str) -> list[str]:
    """Nomes de coluna únicos para tabelas que não aceitam duplicatas.

    Alguns registros oficiais (ex.: C170) repetem mnemônicos como ``ALIQ_PIS``
    em campos distintos. CSV e Excel mantêm os nomes publicados; formatos
    tabulares tipados (pandas/Polars/Parquet) recebem sufixo ``_2``, ``_3``...
    na segunda ocorrência em diante. Nenhuma posição de campo é alterada.
    """
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in columns(layout, code):
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result
