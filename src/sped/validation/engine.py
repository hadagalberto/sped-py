"""Orquestração da validação PVA-like de um arquivo SPED.

O arquivo é percorrido uma única vez. Cada verificador consome um registro por
vez e guarda apenas estado limitado, portanto a memória não cresce com o
tamanho do arquivo.
"""

from __future__ import annotations

from pathlib import Path

from sped.core.encoding import iter_lines, split_line
from sped.core.reader import SpedParseError, SpedReader
from sped.core.types import Layout, Record
from sped.layouts import detect_layout
from sped.validation import checks
from sped.validation.checks import (
    CrossrefChecks,
    HierarchyChecks,
    StructureChecks,
    TableChecks,
)
from sped.validation.context import ValidationContext, ValidationIssue
from sped.validation.rules import Severity
from sped.validation.totals import TotalsChecks

IssueList = list[ValidationIssue]


def _raw_codes(path: str | Path) -> list[str]:
    """Best-effort register codes of a file whose layout cannot be detected."""
    codes: list[str] = []
    for line in iter_lines(path):
        try:
            split = split_line(line)
        except ValueError:
            continue
        if split is not None:
            codes.append(split[0])
    return codes


def _structure_without_layout(codes: list[str], issues: IssueList) -> None:
    """Report the structural registers missing when no COD_VER can be read."""
    from sped.validation.checks import REQUIRED_RECORDS  # noqa: PLC0415

    present = set(codes)
    for required in REQUIRED_RECORDS:
        if required not in present:
            issues.append(
                ValidationIssue(
                    "SPED-STRUCT",
                    0,
                    required,
                    f"Estrutura inválida: registro obrigatório {required} ausente",
                    Severity.ERROR,
                )
            )
    if codes and codes[0] != "0000":
        issues.append(
            ValidationIssue(
                "SPED-STRUCT",
                1,
                codes[0],
                f"Estrutura inválida: arquivo deve começar com 0000 (encontrado {codes[0]})",
                Severity.ERROR,
            )
        )
    if codes and codes[-1] != "9999":
        issues.append(
            ValidationIssue(
                "SPED-STRUCT",
                0,
                codes[-1],
                f"Estrutura inválida: arquivo deve terminar com 9999 (encontrado {codes[-1]})",
                Severity.ERROR,
            )
        )


def validate(path: str | Path) -> IssueList:
    """Collect every structural, field, table, cross-reference and total issue.

    Reading is non-strict so that all problems are reported in a single pass.
    The result is ordered by check group; each issue carries a stable rule id,
    severity and pt-BR message. Memory is bounded: no record list is built.
    """
    issues: IssueList = []

    def on_issue(line_no: int, code: str, message: str) -> None:
        issues.append(
            ValidationIssue(
                "SPED-FIELD", line_no, code, f"Campo inválido: {message}", Severity.ERROR
            )
        )

    try:
        layout: Layout = detect_layout(path)
    except ValueError as exc:
        issues.append(
            ValidationIssue("SPED-FRAME", 0, "", f"Falha ao ler o arquivo: {exc}", Severity.ERROR)
        )
        _structure_without_layout(_raw_codes(path), issues)
        return issues

    ctx = ValidationContext(layout)
    ctx.issues = issues
    structure = StructureChecks()
    tables = TableChecks()
    hierarchy = HierarchyChecks()
    crossrefs = CrossrefChecks(layout)
    totals_checks = TotalsChecks(layout.obrigacao)

    def consume(record: Record) -> None:
        ctx.feed(record)
        structure.feed(record, ctx)
        tables.feed(record, ctx)
        hierarchy.feed(record, ctx)
        crossrefs.feed(record, ctx)
        totals_checks.feed(record, ctx)

    try:
        reader = SpedReader(path, layout=layout, strict=False, on_issue=on_issue)
        for record in reader.iter_records():
            consume(record)
    except SpedParseError as exc:
        issues.append(
            ValidationIssue(
                "SPED-FRAME",
                exc.line_no,
                "",
                f"Falha ao ler o arquivo: {exc.message}",
                Severity.ERROR,
            )
        )

    structure.finish(ctx)
    checks.check_perfil(ctx)
    crossrefs.finish(ctx)
    totals_checks.finish(ctx)
    return ctx.issues
