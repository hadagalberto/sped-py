"""Funções internas de manipulação de registros para merge/split."""

from __future__ import annotations

from datetime import date
from typing import Final

from sped.analysis.periods import parse_date
from sped.core.types import Layout, Record
from sped.core.writer import OutputRecord

#: Campos de data publicados nos leiautes, em ordem de preferência.
DATE_FIELDS: Final[tuple[str, ...]] = (
    "DT_E_S",
    "DT_DOC",
    "DT_INI",
    "DT_APUR",
    "DT_REF",
    "DT_FIN",
)

#: Registros de controle que o escritor recalcula e não devem ser copiados.
#: 9001 é preservado: em alguns leiautes (ex.: ECD) ele traz campos obrigatórios.
CONTROL_CODES: Final[frozenset[str]] = frozenset({"0000", "9900", "9990", "9999"})


def is_closing(code: str) -> bool:
    """True para x990 (exceto 9990, que é controle)."""
    return len(code) == 4 and code.endswith("990") and code != "9990"


def is_opener(code: str) -> bool:
    """True para x001, incluindo 0001 e 9001."""
    return len(code) == 4 and code.endswith("001")


def raw_without_register(record: Record) -> list[str]:
    """Valores crus de um registro sem o campo REG implícito."""
    values = list(record.raw_values)
    if values and values[0] == record.code:
        values = values[1:]
    return values


def _field_index(record: OutputRecord, layout: Layout, field_name: str) -> int:
    code, _ = record
    names = [definition.name for definition in layout.register(code).fields]
    if names and names[0] == "REG":
        names = names[1:]
    try:
        return names.index(field_name)
    except ValueError:
        raise ValueError(f"campo {code}.{field_name} não existe no leiaute") from None


def get_field(record: OutputRecord, layout: Layout, field_name: str) -> str:
    """Valor cru de um campo, usando a posição publicada no leiaute."""
    _, values = record
    index = _field_index(record, layout, field_name)
    return values[index] if index < len(values) else ""


def set_field(record: OutputRecord, layout: Layout, field_name: str, value: str) -> OutputRecord:
    """Troca o valor cru de um campo, usando a posição publicada no leiaute."""
    code, values = record
    index = _field_index(record, layout, field_name)
    updated = list(values)
    if index >= len(updated):
        updated.extend([""] * (index + 1 - len(updated)))
    updated[index] = value
    return code, tuple(updated)


def record_date(record: Record, layout: Layout) -> date | None:
    """Primeira data válida informada em um registro, ou ``None``."""
    available = (
        set(layout.register(record.code).field_names) if record.code in layout.registers else set()
    )
    for name in DATE_FIELDS:
        if name not in available:
            continue
        raw = record.raw_get(name)
        if raw:
            try:
                return parse_date(raw)
            except ValueError:
                continue
    return None
