"""Contexto de validação com estado limitado (streaming).

O validador nunca materializa o arquivo inteiro: o contexto guarda apenas
contadores, o último registro de cada tipo e os registros de controle
(0000/x990/9001/9900/9990/9999). Isso mantém a memória constante mesmo para
arquivos de vários GB.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final

from sped.core.types import Layout, Record
from sped.validation.rules import RULES, Rule, Severity

_MISSING: Final = object()

#: Registros de controle necessários para as regras de estrutura.
_CONTROL_CODES: Final[frozenset[str]] = frozenset({"0000", "9001", "9900", "9990", "9999"})


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
    """Estado compartilhado pelas verificações de um único arquivo."""

    layout: Layout
    issues: list[ValidationIssue] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)
    by_code: dict[str, list[Record]] = field(default_factory=dict)
    last_by_code: dict[str, Record] = field(default_factory=dict)
    first_code: str = ""
    last_code: str = ""

    @classmethod
    def build(cls, records: Iterable[Record], layout: Layout) -> ValidationContext:
        """Build a context from any iterable of records (including a reader)."""
        ctx = cls(layout)
        for record in records:
            ctx.feed(record)
        return ctx

    def feed(self, record: Record) -> None:
        """Absorb one record, keeping only bounded state."""
        if not self.first_code:
            self.first_code = record.code
        self.last_code = record.code
        self.counts[record.code] += 1
        self.last_by_code[record.code] = record
        if record.code in _CONTROL_CODES or record.code.endswith("990"):
            self.by_code.setdefault(record.code, []).append(record)

    def get(self, code: str) -> tuple[Record, ...]:
        """Return the control records of register type ``code``."""
        return tuple(self.by_code.get(code, ()))

    def first(self, code: str) -> Record | None:
        """Return the first control record of ``code``, if any."""
        records = self.by_code.get(code)
        return records[0] if records else None

    def emit(self, rule: Rule, **values: object) -> None:
        """Append an issue built from ``rule`` with interpolated ``values``."""
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
        """Return the closest preceding record of ``code`` in O(1)."""
        candidate = self.last_by_code.get(code)
        if candidate is not None and candidate.line_no < record.line_no:
            return candidate
        return None
