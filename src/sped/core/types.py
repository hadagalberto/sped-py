"""Immutable data model for SPED layouts and records.

All sizes and rules stored here come from the official layout tables; nothing
is guessed.  See ``scripts/generate_layouts.py`` for provenance.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

#: Official field types (section 2.7.1 of the EFD ICMS/IPI layout manual).
FIELD_TYPES: Final[frozenset[str]] = frozenset({"C", "N"})

#: Obrigatoriedade codes found in the official tables.
OBRIG_CODES: Final[frozenset[str]] = frozenset({"O", "OC", "O*", "N", "NA", "NI"})


@dataclass(frozen=True, slots=True)
class FieldDef:
    """One field of a register, as published in the official table."""

    num: int
    name: str
    ftype: str
    size: int
    exact: bool
    dec: int
    description: str = ""
    required: bool = False
    conditional: bool = False
    valid_values: tuple[str, ...] = ()

    @property
    def is_date(self) -> bool:
        """True for the N(008) date fields named ``DT_*`` in the official layout."""
        return (
            self.ftype == "N" and self.size == 8 and self.dec == 0 and self.name.startswith("DT_")
        )

    def coerce(self, raw: str) -> str | Decimal | int | date | None:  # noqa: PLR0911
        """Convert a raw field value to its Python type.

        Numeric fields with decimals are returned as :class:`~decimal.Decimal`
        (never ``float``), integer numerics as ``int``, dates as
        :class:`~datetime.date`, and alphanumeric fields as ``str``.  Empty
        optional values become ``None``.
        """
        if raw == "":
            return None
        if self.ftype == "C":
            return raw
        if self.is_date:
            if len(raw) != 8 or not raw.isdigit():
                return raw
            try:
                return date(int(raw[4:8]), int(raw[2:4]), int(raw[0:2]))
            except ValueError:
                return raw
        negative = raw.startswith("-")
        body = raw[1:] if negative else raw
        # SPED has no implied decimals: the decimal separator is a comma and
        # ``10000`` means ten thousand, never ``100,00``. A dot is not a
        # separator in the official format and is left raw so the reader flags
        # it (Guia Prático EFD ICMS/IPI, campo 2.7.1).
        if "," in body:
            try:
                value = Decimal(body.replace(",", "."))
            except Exception:
                return raw
            return -value if negative else value
        if "." in body or not body.isdigit():
            return raw
        if self.dec == 0:
            return int(body) * (-1 if negative else 1)
        value = Decimal(int(body))
        return -value if negative else value


@dataclass(frozen=True, slots=True)
class RegisterDef:
    """Definition of one register (``REGISTRO ...``) of a layout."""

    code: str
    title: str
    level: int | None
    occurrence: str | None
    fields: tuple[FieldDef, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def field(self, name_or_num: str | int) -> FieldDef:
        """Look up a field by mnemonic or 1-based number."""
        for field in self.fields:
            if name_or_num in (field.name, field.num):
                return field
        raise KeyError(f"campo {name_or_num!r} não existe no registro {self.code}")


@dataclass(frozen=True, slots=True)
class Layout:
    """A versioned SPED layout and its official provenance."""

    obrigacao: str
    cod_ver: str
    versao: str
    valid_from: str
    valid_to: str
    source_url: str
    source_date: str
    registers: Mapping[str, RegisterDef]
    gap_filled_fields: int = 0

    def register(self, code: str) -> RegisterDef:
        try:
            return self.registers[code]
        except KeyError:
            raise KeyError(f"registro {code!r} não existe no leiaute {self.cod_ver}") from None


@dataclass(frozen=True, slots=True)
class Field:
    """A converted field plus its raw source text and any validation error."""

    definition: FieldDef
    raw: str
    value: str | Decimal | int | date | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Record:
    """One ``|REG|...|`` line, parsed and validated against a layout."""

    line_no: int
    code: str
    fields: tuple[Field, ...]
    raw: str = ""

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(field.error for field in self.fields if field.error is not None)

    @property
    def values(self) -> tuple[str | Decimal | int | date | None, ...]:
        return tuple(field.value for field in self.fields)

    @property
    def raw_values(self) -> tuple[str, ...]:
        return tuple(field.raw for field in self.fields)

    def get(self, name: str, default: object = None) -> object:
        """Return the converted value of a field by mnemonic."""
        for field in self.fields:
            if field.definition.name == name:
                return field.value
        return default

    def raw_get(self, name: str, default: str = "") -> str:
        """Return the raw value of a field by mnemonic."""
        for field in self.fields:
            if field.definition.name == name:
                return field.raw
        return default
