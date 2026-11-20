"""Structural and totalisation checks used by ``sped validate``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sped.core.encoding import iter_lines, split_line
from sped.core.reader import SpedParseError, SpedReader
from sped.core.types import Layout, Record

REQUIRED_RECORDS: Final[tuple[str, ...]] = ("0000", "0001", "0990", "9001", "9900", "9990", "9999")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One problem found while validating a file."""

    rule: str
    line_no: int
    code: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "line": self.line_no,
            "register": self.code,
            "message": self.message,
        }


def validate(path: str | Path) -> list[ValidationIssue]:  # noqa: PLR0912
    """Collect all structural/field/total issues in a SPED file.

    Reading is non-strict so that every problem is reported in one pass.
    """
    issues: list[ValidationIssue] = []

    def on_issue(line_no: int, code: str, message: str) -> None:
        issues.append(ValidationIssue("SPED-FIELD", line_no, code, message))

    records: list[Record] = []
    codes: list[str] = []
    layout: Layout | None = None
    try:
        reader = SpedReader(path, strict=False, on_issue=on_issue)
        layout = reader.layout
    except ValueError as exc:
        # Sem COD_VER detectável não há leiaute: ainda assim inspecionamos o
        # arquivo cru para relatar os registros estruturais ausentes.
        issues.append(ValidationIssue("SPED-FRAME", 0, "", str(exc)))
        for line in iter_lines(path):
            try:
                split = split_line(line)
            except ValueError:
                continue
            if split is not None:
                codes.append(split[0])
    else:
        try:
            records = list(reader.iter_records())
        except SpedParseError as exc:
            issues.append(ValidationIssue("SPED-FRAME", exc.line_no, "", exc.message))
        codes = [record.code for record in records]
    seen = set(codes)
    for required in REQUIRED_RECORDS:
        if layout is not None and required not in layout.registers:
            continue
        if required not in seen:
            issues.append(
                ValidationIssue(
                    "SPED-STRUCT", 0, required, f"registro obrigatório {required} ausente"
                )
            )
    if codes and codes[0] != "0000":
        issues.append(ValidationIssue("SPED-STRUCT", 1, codes[0], "arquivo deve começar com 0000"))
    if codes and codes[-1] != "9999":
        issues.append(
            ValidationIssue("SPED-STRUCT", 0, codes[-1], "arquivo deve terminar com 9999")
        )

    for block in sorted({code[0] for code in codes if code[0] not in {"9"}}):
        closing = f"{block}990"
        if layout is not None and closing not in layout.registers:
            continue
        if f"{block}001" in seen and closing not in seen:
            issues.append(
                ValidationIssue(
                    "SPED-STRUCT", 0, f"{block}990", f"bloco {block} sem registro de encerramento"
                )
            )

    counts: dict[str, int] = {}
    for record in records:
        counts[record.code] = counts.get(record.code, 0) + 1

    for record in records:
        if record.code == "9900" and len(record.fields) >= 3:
            expected_code = record.raw_get("REG_BLC")
            stated = record.raw_get("QTD_REG_BLC")
            actual = counts.get(expected_code, 0)
            if stated != str(actual):
                issues.append(
                    ValidationIssue(
                        "SPED-9900",
                        record.line_no,
                        "9900",
                        f"{expected_code}: informado {stated}, encontrado {actual}",
                    )
                )
        if record.code == "9999" and len(record.fields) >= 2:
            stated_total = record.raw_get("QTD_LIN")
            if stated_total != str(len(records)):
                issues.append(
                    ValidationIssue(
                        "SPED-9999",
                        record.line_no,
                        "9999",
                        f"total informado {stated_total}, encontrado {len(records)}",
                    )
                )
    return issues
