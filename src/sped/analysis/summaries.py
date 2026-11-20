"""Resumos por CFOP, CST/CSOSN e participante.

Os resumos são derivados dos registros de detalhe ``C170`` da EFD ICMS/IPI:
``CFOP``, ``CST_ICMS`` e os campos ``VL_*`` vêm do próprio ``C170``;
``COD_PART`` vem do ``C100`` pai (campo 03 do registro C100). Nenhuma regra de
negócio é inventada: as dimensões são nomes de campos publicados no leiaute
oficial, carregado de ``src/sped/layouts``.

Fonte: Guia Prático da EFD ICMS/IPI v3.2.4, registros C100/C170 —
https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@display-file/file
(URL verificada em 2026-11-20; a mesma fonte é citada em ``validation.rules``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from sped.core.reader import SpedReader
from sped.core.types import Layout, Record
from sped.layouts import detect_layout
from sped.validation.context import number

ZERO: Final = Decimal(0)

#: Campos monetários publicados no C170 que compõem o resumo.
TOTAL_FIELDS: Final[tuple[str, ...]] = (
    "VL_ITEM",
    "VL_DESC",
    "VL_BC_ICMS",
    "VL_ICMS",
    "VL_BC_ICMS_ST",
    "VL_ICMS_ST",
    "VL_BC_IPI",
    "VL_IPI",
    "VL_PIS",
    "VL_COFINS",
)

#: Dimensões oferecidas por padrão na CLI e na API.
DEFAULT_DIMENSIONS: Final[tuple[str, ...]] = ("CFOP", "CST_ICMS", "COD_PART")


@dataclass(frozen=True, slots=True)
class SummaryRow:
    """Uma linha de resumo: valor da dimensão, quantidade e somas dos campos."""

    value: str
    count: int
    totals: dict[str, Decimal]

    def as_dict(self) -> dict[str, object]:
        """Representação serializável (Decimals como strings exatas)."""
        return {
            "valor": self.value,
            "quantidade": self.count,
            "totais": {name: str(value) for name, value in self.totals.items()},
        }


@dataclass(frozen=True, slots=True)
class Summary:
    """Resumo completo de uma dimensão."""

    dimension: str
    rows: tuple[SummaryRow, ...]

    @property
    def total_count(self) -> int:
        """Número total de registros detalhe resumidos."""
        return sum(row.count for row in self.rows)

    @property
    def grand_totals(self) -> dict[str, Decimal]:
        """Soma dos campos em todas as linhas."""
        return {
            name: sum((row.totals.get(name, ZERO) for row in self.rows), ZERO)
            for name in TOTAL_FIELDS
        }

    def as_dict(self) -> dict[str, object]:
        """Representação serializável."""
        return {
            "dimensao": self.dimension,
            "linhas": [row.as_dict() for row in self.rows],
            "quantidade_total": self.total_count,
            "totais_gerais": {name: str(value) for name, value in self.grand_totals.items()},
        }


def _validate_dimension(dimension: str, layout: Layout) -> str:
    if dimension == "COD_PART":
        return dimension
    c170 = layout.register("C170")
    if dimension in c170.field_names:
        return dimension
    raise ValueError(f"dimensão {dimension!r} não é um campo publicado de C170")


def summarize(
    records: Iterable[Record],
    dimension: str,
    *,
    layout: Layout,
    fields: tuple[str, ...] = TOTAL_FIELDS,
) -> Summary:
    """Agrupa registros ``C170`` pela dimensão informada.

    ``dimension`` aceita ``COD_PART`` (do ``C100`` pai) ou qualquer campo do
    ``C170`` presente no leiaute. Registros que não sejam ``C170`` são
    ignorados; o ``C100`` mais recente define o participante corrente.
    """
    dimension = _validate_dimension(dimension, layout)
    unknown = sorted(set(fields) - set(layout.register("C170").field_names))
    if unknown:
        raise ValueError(f"campos de resumo inexistentes em C170: {', '.join(unknown)}")

    buckets: dict[str, list[Record]] = defaultdict(list)
    current_part: str = ""
    for record in records:
        if record.code == "C100":
            current_part = record.raw_get("COD_PART")
        elif record.code == "C170":
            key = current_part if dimension == "COD_PART" else record.raw_get(dimension)
            buckets[key].append(record)

    rows = tuple(
        SummaryRow(
            value=key,
            count=len(group),
            totals={name: sum((number(record, name) for record in group), ZERO) for name in fields},
        )
        for key, group in sorted(buckets.items())
    )
    return Summary(dimension=dimension, rows=rows)


def summarize_all(
    records: Iterable[Record],
    *,
    layout: Layout,
    dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
) -> tuple[Summary, ...]:
    """Calcula todas as dimensões em uma única passada sobre ``records``."""
    checked = tuple(_validate_dimension(name, layout) for name in dimensions)
    if not checked:
        raise ValueError("ao menos uma dimensão deve ser informada")
    grouped: dict[tuple[str, str], list[Record]] = defaultdict(list)
    current_part: str = ""
    for record in records:
        if record.code == "C100":
            current_part = record.raw_get("COD_PART")
        elif record.code == "C170":
            for dimension in checked:
                key = current_part if dimension == "COD_PART" else record.raw_get(dimension)
                grouped[(dimension, key)].append(record)

    summaries: list[Summary] = []
    for dimension in checked:
        rows = tuple(
            SummaryRow(
                value=key,
                count=len(group),
                totals={
                    name: sum((number(record, name) for record in group), ZERO)
                    for name in TOTAL_FIELDS
                },
            )
            for (selected, key), group in sorted(grouped.items())
            if selected == dimension
        )
        summaries.append(Summary(dimension=dimension, rows=rows))
    return tuple(summaries)


def summarize_file(
    path: str | Path,
    *,
    layout: Layout | None = None,
    dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
) -> tuple[Summary, ...]:
    """Lê ``path`` e devolve os resumos das dimensões solicitadas."""
    chosen = layout or detect_layout(path)
    with SpedReader(path, layout=chosen, strict=False) as reader:
        return summarize_all(reader.iter_records(), layout=chosen, dimensions=dimensions)
