"""Contexto imutável de uma validação e coleta de não conformidades."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final

from sped.core.types import Layout, Record
from sped.validation.rules import RULES, Rule, Severity

_MISSING: Final = object()


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Uma não conformidade encontrada em um arquivo."""

    rule: str
    line_no: int
    code: str
    message: str
    severity: Severity = Severity.ERROR

    def as_dict(self) -> dict[str, object]:
        """Serializable representation used by ``sped validate --json``."""
        return {
            "rule": self.rule,
            "line": self.line_no,
            "register": self.code,
            "message": self.message,
            "severity": self.severity.value,
        }


def number(record: Record, field_name: str) -> Decimal:
    """Return a numeric field as ``Decimal``, or zero when absent/empty."""
    value = record.get(field_name, _MISSING)
    if value is _MISSING or value is None or value == "":
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return Decimal(0)


def money(value: Decimal) -> str:
    """Format a Decimal for pt-BR diagnostic messages."""
    return f"{value:.2f}"


@dataclass(slots=True)
class ValidationContext:
    """Records, layout and issue sink shared by all checks of one file."""

    layout: Layout
    records: list[Record]
    issues: list[ValidationIssue] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    by_code: dict[str, list[Record]] = field(default_factory=dict)
    positions: dict[int, int] = field(default_factory=dict)

    @classmethod
    def build(cls, records: list[Record], layout: Layout) -> ValidationContext:
        """Index ``records`` by register type and line number."""
        counts: Counter[str] = Counter()
        by_code: dict[str, list[Record]] = {}
        positions: dict[int, int] = {}
        for index, record in enumerate(records):
            counts[record.code] += 1
            by_code.setdefault(record.code, []).append(record)
            positions[record.line_no] = index
        return cls(layout, records, counts=counts, by_code=by_code, positions=positions)

    def get(self, code: str) -> tuple[Record, ...]:
        """Return all records of register type ``code``."""
        return tuple(self.by_code.get(code, ()))

    def first(self, code: str) -> Record | None:
        """Return the first record of register type ``code``, if any."""
        records = self.by_code.get(code)
        return records[0] if records else None

    def emit(self, rule: Rule, **values: object) -> None:
        """Append an issue built from ``rule`` with interpolated ``values``.

        ``line`` and ``code`` are reserved keys describing the location; all
        other keys feed the pt-BR message template.
        """
        line = int(str(values.pop("line", 0)))
        code = str(values.pop("code", ""))
        self.issues.append(
            ValidationIssue(
                rule.id, line, code, rule.format(line=line, code=code, **values), rule.severity
            )
        )

    def emit_id(self, rule_id: str, **values: object) -> None:
        """Append an issue for a rule looked up by id."""
        self.emit(RULES[rule_id], **values)

    def parent(self, record: Record, code: str) -> Record | None:
        """Return the closest preceding record of type ``code``."""
        position = self.positions.get(record.line_no, 0) - 1
        while position >= 0:
            candidate = self.records[position]
            if candidate.code == code:
                return candidate
            position -= 1
        return None


def by_fields(records: Mapping[str, list[Record]], code: str, field_name: str) -> dict[str, int]:
    """Map each declared value of ``code.field_name`` to its first line number."""
    result: dict[str, int] = {}
    for record in records.get(code, ()):
        value = record.raw_get(field_name)
        if value:
            result.setdefault(value, record.line_no)
    return result
