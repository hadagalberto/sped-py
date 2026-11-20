"""Regras de estrutura, perfil, tabelas oficiais e referências cruzadas."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from sped.core.types import Layout
from sped.validation.context import ValidationContext, by_fields
from sped.validation.tables import ncm_codes, valid_cfop, valid_cst_icms

REQUIRED_RECORDS: Final[tuple[str, ...]] = (
    "0000",
    "0001",
    "0005",
    "0990",
    "9001",
    "9900",
    "9990",
    "9999",
)

#: Guia Prático EFD ICMS/IPI v3.2.4, tabelas 2.6.1.1/.1A/.4-.8 (todos os perfis).
PERFIL_COMMON: Final[tuple[str, ...]] = (
    "0000",
    "0001",
    "0005",
    "0990",
    "B001",
    "B990",
    "C001",
    "C990",
    "D001",
    "D990",
    "E001",
    "E100",
    "E110",
    "E990",
    "G001",
    "G990",
    "H001",
    "H990",
    "K001",
    "K990",
    "1001",
    "1010",
    "9001",
    "9900",
    "9990",
    "9999",
)

#: 0100 só é exigido dos perfis A e B (tabela 2.6.1.1 do Guia Prático).
PERFIL_AB: Final[tuple[str, ...]] = ("0100",)

_PERFIS: Final = frozenset({"A", "B", "C"})


def check_structure(ctx: ValidationContext) -> None:  # noqa: PLR0912
    """Structural registers, block closings, 9900 counts and 9999 total."""
    present = set(ctx.counts)
    for required in REQUIRED_RECORDS:
        if required in ctx.layout.registers and required not in present:
            ctx.emit_id(
                "SPED-STRUCT", detail=f"registro obrigatório {required} ausente", code=required
            )
    if ctx.records:
        if ctx.records[0].code != "0000":
            ctx.emit_id(
                "SPED-STRUCT",
                detail=f"arquivo deve começar com 0000 (encontrado {ctx.records[0].code})",
                line=ctx.records[0].line_no,
                code=ctx.records[0].code,
            )
        if ctx.records[-1].code != "9999":
            ctx.emit_id(
                "SPED-STRUCT",
                detail=f"arquivo deve terminar com 9999 (encontrado {ctx.records[-1].code})",
                code=ctx.records[-1].code,
            )
    for block in sorted({code[0] for code in present if code[0] != "9"}):
        opener, closing = f"{block}001", f"{block}990"
        if opener in present and closing in ctx.layout.registers and closing not in present:
            ctx.emit_id(
                "SPED-STRUCT", detail=f"bloco {block} sem registro de encerramento", code=closing
            )
    for record in ctx.get("9900"):
        if len(record.fields) >= 3:
            expected = record.raw_get("REG_BLC")
            stated = record.raw_get("QTD_REG_BLC")
            actual = ctx.counts.get(expected, 0)
            if stated != str(actual):
                ctx.emit_id(
                    "SPED-9900",
                    detail=f"{expected}: informado {stated}, encontrado {actual}",
                    line=record.line_no,
                )
    for record in ctx.get("9999"):
        if len(record.fields) >= 2:
            stated = record.raw_get("QTD_LIN")
            if stated != str(len(ctx.records)):
                ctx.emit_id(
                    "SPED-9999",
                    detail=f"total informado {stated}, encontrado {len(ctx.records)}",
                    line=record.line_no,
                )


def check_perfil(ctx: ValidationContext) -> None:
    """Required/forbidden records for EFD ICMS/IPI profiles A, B and C."""
    if ctx.layout.obrigacao != "efd_icmsipi":
        return
    opening = ctx.first("0000")
    if opening is None:
        return
    perfil = opening.raw_get("IND_PERFIL").strip().upper()
    if perfil not in _PERFIS:
        ctx.emit_id("SPED-PERFIL-001", line=opening.line_no, code="0000", value=perfil or "(vazio)")
        return

    def require(code: str) -> None:
        if code in ctx.layout.registers and code not in ctx.counts:
            ctx.emit_id("SPED-PERFIL-002", code=code, register=code, perfil=perfil)

    for code in PERFIL_COMMON:
        require(code)
    if perfil in {"A", "B"}:
        for code in PERFIL_AB:
            require(code)
    if ctx.get("C100"):
        require("C190")
        if perfil in {"A", "B"}:
            require("C170")
        elif perfil == "C" and ctx.get("C170"):
            ctx.emit_id("SPED-PERFIL-003", code="C170", register="C170", perfil=perfil)
    if ctx.get("D100"):
        require("D190")


def _check_code_field(
    ctx: ValidationContext,
    codes: tuple[str, ...],
    field_name: str,
    rule_id: str,
    predicate: Callable[[str], bool],
) -> None:
    for code in codes:
        for record in ctx.get(code):
            value = record.raw_get(field_name)
            if value and not predicate(value):
                ctx.emit_id(rule_id, line=record.line_no, code=code, register=code, value=value)


def check_tables(ctx: ValidationContext) -> None:
    """CFOP, CST-ICMS and NCM values against the bundled official tables."""
    _check_code_field(ctx, ("C170", "C190", "D190"), "CFOP", "SPED-TAB-CFOP-001", valid_cfop)
    for code in ("C170", "C190", "D190"):
        for record in ctx.get(code):
            value = record.raw_get("CST_ICMS")
            if value and not valid_cst_icms(value):
                detail = "origem ou tributação fora das tabelas oficiais"
                ctx.emit_id(
                    "SPED-TAB-CST-001",
                    line=record.line_no,
                    code=code,
                    register=code,
                    value=value,
                    detail=detail,
                )
    ncms = ncm_codes()
    for record in ctx.get("0200"):
        value = record.raw_get("COD_NCM")
        if value and value not in ncms:
            ctx.emit_id("SPED-TAB-NCM-001", line=record.line_no, code="0200", value=value)


#: (campo, registro declarante, regra, descrição do campo na mensagem).
_REFERENCES: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("COD_PART", "0150", "SPED-XREF-0150-001", "COD_PART"),
    ("COD_ITEM", "0200", "SPED-XREF-0200-001", "COD_ITEM"),
    ("UNID", "0190", "SPED-XREF-0190-001", "UNID"),
)

#: Campos de cadastro cujos valores devem existir em 0150/0200/0190.
_DECLARED: Final[dict[str, str]] = {
    "COD_PART": "0150",
    "COD_ITEM": "0200",
    "UNID": "0190",
}


def _users(layout: Layout) -> dict[str, dict[str, str]]:
    """Derive every referencing register from the official layout fields.

    Hardcoding a short list would miss dozens of registers that also carry
    ``COD_PART``/``COD_ITEM``/``UNID`` (e.g. C110, D160, 0205). The layout is
    the source of truth; no register is guessed.
    """
    result: dict[str, dict[str, str]] = {name: {} for name in _DECLARED}
    for code, register in layout.registers.items():
        names = register.field_names
        # A cadastro's own key is not a reference to itself, but 0200.UNID_INV
        # still references the unit declared in 0190.
        if code != "0150" and "COD_PART" in names:
            result["COD_PART"][code] = "COD_PART"
        if code != "0200" and "COD_ITEM" in names:
            result["COD_ITEM"][code] = "COD_ITEM"
        if code != "0190":
            if "UNID_INV" in names:
                result["UNID"][code] = "UNID_INV"
            elif "UNID" in names:
                result["UNID"][code] = "UNID"
    return result


def check_crossrefs(ctx: ValidationContext) -> None:
    """0150/0200/0190 references used by documents and items."""
    users = _users(ctx.layout)
    for field_name, declared_code, rule_id, _label in _REFERENCES:
        declared_field = "UNID" if declared_code == "0190" else field_name
        declared = by_fields(ctx.by_code, declared_code, declared_field)
        _check_declared_field(ctx, users[field_name], declared, declared_code, rule_id)

    for code, field_name in (("0150", "COD_PART"), ("0200", "COD_ITEM"), ("0190", "UNID")):
        seen: set[str] = set()
        for record in ctx.get(code):
            value = record.raw_get(field_name)
            if not value:
                continue
            if value in seen:
                ctx.emit_id(
                    "SPED-XREF-DUP-001",
                    line=record.line_no,
                    code=code,
                    register=code,
                    field=field_name,
                    value=value,
                )
            seen.add(value)


def _check_declared_field(
    ctx: ValidationContext,
    users: dict[str, str],
    declared: dict[str, int],
    declared_code: str,
    rule_id: str,
) -> None:
    for code, field_name in users.items():
        for record in ctx.get(code):
            value = record.raw_get(field_name)
            if not value:
                continue
            if value in declared:
                if declared[value] > record.line_no:
                    ctx.emit_id(
                        "SPED-XREF-ORDER-001",
                        line=record.line_no,
                        code=code,
                        register=code,
                        field=field_name,
                        value=value,
                        declared=declared[value],
                    )
                continue
            ctx.emit_id(
                rule_id,
                line=record.line_no,
                code=code,
                register=code,
                value=value,
                field=field_name,
                declared_register=declared_code,
            )


def check_all(ctx: ValidationContext) -> None:
    """Run every non-totalization check in a deterministic order."""
    check_structure(ctx)
    check_perfil(ctx)
    check_tables(ctx)
    check_crossrefs(ctx)
