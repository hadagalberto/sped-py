"""Utilitários de período (DDMMAAAA) para mesclar e dividir arquivos SPED.

As datas ``DT_INI``/``DT_FIN`` e as datas de documentos seguem o formato
``DDMMAAAA`` publicado nos leiautes oficiais (vide ``sped.core.types.FieldDef``).
Nenhuma regra de apuração é criada aqui: apenas recortes temporais.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final

DATE_FORMAT: Final = "%d%m%Y"
GRANULARITIES: Final[tuple[str, ...]] = ("month", "quarter", "year")


def parse_date(raw: str) -> date:
    """Converte ``DDMMAAAA`` em :class:`datetime.date`."""
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"data SPED inválida: {raw!r} (esperado DDMMAAAA)")
    return date(int(raw[4:8]), int(raw[2:4]), int(raw[0:2]))


def format_date(value: date) -> str:
    """Converte :class:`datetime.date` em ``DDMMAAAA``."""
    return value.strftime(DATE_FORMAT)


@dataclass(frozen=True, slots=True)
class Period:
    """Um intervalo [início, fim] dentro do arquivo."""

    start: date
    end: date

    @property
    def label(self) -> str:
        """Rótulo ``AAAAMM-AAAAMM`` usado em relatórios."""
        return f"{Period._yyyymm(self.start)}-{Period._yyyymm(self.end)}"

    @staticmethod
    def _yyyymm(value: date) -> str:
        raw = format_date(value)
        return f"{raw[4:8]}{raw[2:4]}"

    @property
    def code(self) -> str:
        """Código ``AAAAMM`` do início do período (usado em nomes de arquivo)."""
        return Period._yyyymm(self.start)

    def contains(self, value: date) -> bool:
        """True quando ``value`` pertence ao intervalo."""
        return self.start <= value <= self.end


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, count: int) -> date:
    index = value.month - 1 + count
    year = value.year + index // 12
    return date(year, index % 12 + 1, 1)


def split_periods(start_raw: str, end_raw: str, granularity: str = "month") -> tuple[Period, ...]:
    """Divide o intervalo informado em períodos contíguos.

    ``granularity`` aceita ``month``, ``quarter`` ou ``year``. O fim de cada
    período é o dia anterior ao início do seguinte (ou ``end_raw`` no último),
    de modo que os intervalos não se sobreponham.
    """
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularidade desconhecida: {granularity!r}")
    start = parse_date(start_raw)
    end = parse_date(end_raw)
    if start > end:
        raise ValueError("DT_INI posterior a DT_FIN")
    step = {"month": 1, "quarter": 3, "year": 12}[granularity]
    first = _month_start(start)
    result: list[Period] = []
    cursor = first
    while cursor <= end:
        following = _add_months(cursor, step)
        period_end = min(date.fromordinal(following.toordinal() - 1), end)
        result.append(Period(max(cursor, start), period_end))
        cursor = following
    return tuple(result)
