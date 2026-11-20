"""Regras de estrutura, perfil, tabelas oficiais e referências cruzadas.

Todas as verificações consomem registros um a um (:meth:`feed`) e mantêm
apenas estado limitado; a memória não cresce com o tamanho do arquivo.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from sped.core.hierarchy import level_of
from sped.core.types import Layout, Record
from sped.validation.context import ValidationContext
from sped.validation.tables import (
    ncm_codes,
    valid_cfop,
    valid_cnpj,
    valid_cpf,
    valid_cst_icms,
)

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

#: Guia Prático: 1xxx/2xxx/3xxx são entradas; 5xxx/6xxx/7xxx são saídas.
_CFOP_ENTRADA: Final = frozenset({"1", "2", "3"})
_CFOP_SAIDA: Final = frozenset({"5", "6", "7"})


class StructureChecks:
    """Estrutura do arquivo, fechamentos de bloco, 9900, 9990 e 9999."""

    def __init__(self) -> None:
        self.block = ""
        self.block_count = 0

    def feed(self, record: Record, ctx: ValidationContext) -> None:
        code = record.code
        if code[0] == "9":
            # Bloco 9 é validado ao final, quando todos os 9900 são conhecidos.
            return
        if code.endswith("990"):
            computed = self.block_count + 1
            declared = record.raw_get(f"QTD_LIN_{code[0]}")
            # Alguns leiautes (ECD/ECF) não publicam o campo de contagem no
            # registro de encerramento; não hávalor informado a confrontar.
            if declared and declared != str(computed):
                ctx.emit_id(
                    "SPED-STRUCT-X990-001",
                    line=record.line_no,
                    code=code,
                    register=code,
                    stated=declared or "(vazio)",
                    computed=computed,
                )
            self.block = ""
            self.block_count = 0
            return
        if code[0] != self.block:
            self.block = code[0]
            self.block_count = 0
        self.block_count += 1

    def finish(self, ctx: ValidationContext) -> None:  # noqa: PLR0912
        present = set(ctx.counts)
        for required in REQUIRED_RECORDS:
            if required in ctx.layout.registers and required not in present:
                ctx.emit_id(
                    "SPED-STRUCT", detail=f"registro obrigatório {required} ausente", code=required
                )
        if ctx.first_code and ctx.first_code != "0000":
            ctx.emit_id(
                "SPED-STRUCT",
                detail=f"arquivo deve começar com 0000 (encontrado {ctx.first_code})",
                code=ctx.first_code,
            )
        if ctx.last_code and ctx.last_code != "9999":
            ctx.emit_id(
                "SPED-STRUCT",
                detail=f"arquivo deve terminar com 9999 (encontrado {ctx.last_code})",
                code=ctx.last_code,
            )
        for block in sorted({code[0] for code in present if code[0] != "9"}):
            opener, closing = f"{block}001", f"{block}990"
            if opener in present and closing in ctx.layout.registers and closing not in present:
                ctx.emit_id(
                    "SPED-STRUCT",
                    detail=f"bloco {block} sem registro de encerramento",
                    code=closing,
                )

        listed: set[str] = set()
        for record in ctx.get("9900"):
            expected = record.raw_get("REG_BLC")
            stated = record.raw_get("QTD_REG_BLC")
            actual = ctx.counts.get(expected, 0)
            if stated != str(actual):
                ctx.emit_id(
                    "SPED-9900",
                    detail=f"{expected}: informado {stated}, encontrado {actual}",
                    line=record.line_no,
                )
            if expected in listed:
                ctx.emit_id("SPED-9900", detail=f"{expected}: linha duplicada", line=record.line_no)
            listed.add(expected)
        for code, actual in ctx.counts.items():
            if code not in listed:
                ctx.emit_id("SPED-9900", detail=f"{code}: sem linha totalizadora ({actual})")

        block9_lines = sum(count for code, count in ctx.counts.items() if code[0] == "9")
        for record in ctx.get("9990"):
            stated = record.raw_get("QTD_LIN_9")
            if stated and stated != str(block9_lines):
                ctx.emit_id(
                    "SPED-9990",
                    detail=(
                        f"total informado {stated}, encontrado {block9_lines} "
                        "(inclui 9001, 9900, 9990 e 9999)"
                    ),
                    line=record.line_no,
                )

        file_lines = sum(ctx.counts.values())
        for record in ctx.get("9999"):
            stated = record.raw_get("QTD_LIN")
            if stated != str(file_lines):
                ctx.emit_id(
                    "SPED-9999",
                    detail=f"total informado {stated}, encontrado {file_lines}",
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
    if ctx.counts.get("C100"):
        require("C190")
        if perfil in {"A", "B"}:
            require("C170")
        elif perfil == "C" and ctx.counts.get("C170"):
            ctx.emit_id("SPED-PERFIL-003", code="C170", register="C170", perfil=perfil)
    if ctx.counts.get("D100"):
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


class TableChecks:
    """Tabelas oficiais, documentos e coerência CFOP x IND_OPER."""

    def __init__(self) -> None:
        self.ncms = ncm_codes()

    def feed(self, record: Record, ctx: ValidationContext) -> None:
        code = record.code
        if code in {"C170", "C190", "D190"}:
            cfop = record.raw_get("CFOP")
            if cfop and not valid_cfop(cfop):
                ctx.emit_id(
                    "SPED-TAB-CFOP-001",
                    line=record.line_no,
                    code=code,
                    register=code,
                    value=cfop,
                )
            cst = record.raw_get("CST_ICMS")
            if cst and not valid_cst_icms(cst):
                ctx.emit_id(
                    "SPED-TAB-CST-001",
                    line=record.line_no,
                    code=code,
                    register=code,
                    value=cst,
                    detail="origem ou tributação fora das tabelas oficiais",
                )
            self._check_direction(record, cfop, ctx)
        if code == "0200":
            value = record.raw_get("COD_NCM")
            if value and value not in self.ncms:
                ctx.emit_id("SPED-TAB-NCM-001", line=record.line_no, code="0200", value=value)
        self._check_documents(record, ctx)

    def _check_direction(self, record: Record, cfop: str, ctx: ValidationContext) -> None:
        if len(cfop) != 4 or not cfop.isdigit():
            return
        if cfop[0] in _CFOP_ENTRADA:
            kind, expected = "entrada", "0"
        elif cfop[0] in _CFOP_SAIDA:
            kind, expected = "saída", "1"
        else:
            return
        parent_code = "D100" if record.code.startswith("D") else "C100"
        parent = ctx.parent(record, parent_code)
        if parent is None:
            return
        operation = parent.raw_get("IND_OPER")
        if operation and operation != expected:
            ctx.emit_id(
                "SPED-TAB-CFOP-002",
                line=record.line_no,
                code=record.code,
                register=record.code,
                value=cfop,
                kind=kind,
                operation=operation,
            )

    def _check_documents(self, record: Record, ctx: ValidationContext) -> None:
        """CNPJ/CPF: dígitos verificadores (Receita Federal, módulo 11)."""
        for field in record.fields:
            name = field.definition.name.upper()
            raw = field.raw
            if not raw:
                continue
            is_cnpj = field.definition.size == 14 and "CNPJ" in name
            is_cpf = field.definition.size == 11 and "CPF" in name and "CNPJ" not in name
            invalid = (is_cnpj and not valid_cnpj(raw)) or (is_cpf and not valid_cpf(raw))
            if invalid:
                ctx.emit_id(
                    "SPED-TAB-CNPJ-001",
                    line=record.line_no,
                    code=record.code,
                    register=record.code,
                    field=field.definition.name,
                    value=raw,
                )


#: Relações de filiação inequívocas dos registros de documento (Guia
#: Prático EFD ICMS/IPI, "Nível hierárquico" de cada registro).
_CHILD_PARENTS: Final[dict[str, tuple[str, ...]]] = {
    "C170": ("C100", "C300", "C350", "C400", "C500", "C600", "C700", "C800"),
    "C190": ("C100", "C300", "C390", "C490", "C590", "C690", "C790", "C890"),
    "D190": ("D100", "D300", "D390", "D410", "D590", "D690", "D730"),
    "E110": ("E100",),
    "I155": ("I150",),
    "I150": ("I010", "I050"),
    "M210": ("M200",),
    "M610": ("M600",),
}


def _is_data_register(code: str) -> bool:
    """Aberturas/encerramentos de bloco não são pais de registros de dado."""
    return not (code.endswith(("001", "990")) or code in {"9001", "9900", "9990", "9999"})


class HierarchyChecks:
    """Exige o pai dos registros de detalhe conforme o nível publicado.

    As tabelas publicadas têm numeração inconscistente para alguns registros
    de controle (por exemplo 1010 aparece como nível 3 em EFD ICMS/IPI), por
    isso a regra só exige ancestral de nível superior para detalhes (nível >=
    3) e usa as relações inequívocas de filiação quando disponíveis.
    """

    def __init__(self) -> None:
        self.stack: list[tuple[int, str]] = []

    def feed(self, record: Record, ctx: ValidationContext) -> None:
        level = level_of(record, ctx.layout)
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        ancestor = next(
            (code for ancestor_level, code in reversed(self.stack) if ancestor_level < level), None
        )
        numeric = record.code[1:]
        is_detail = (
            level >= 3
            and numeric.isdigit()
            and int(numeric) >= 100
            and not record.code.endswith("00")
        )
        required = _CHILD_PARENTS.get(record.code, ())
        if required:
            # A pilha só retém ancestrais de nível estritamente menor; em
            # versões antigas E100 e E110 compartilham o mesmo nível.
            violated = not any(ctx.parent(record, code) for code in required)
        elif is_detail:
            # Um detalhe precisa de um registro de dado (não apenas da abertura
            # do bloco) como ancestral. Registros de nível baixo como 1010
            # ficam diretamente sob a abertura do bloco.
            violated = ancestor is None or not _is_data_register(ancestor)
        else:
            violated = False
        if violated:
            ctx.emit_id(
                "SPED-STRUCT-HIER-001",
                line=record.line_no,
                code=record.code,
                register=record.code,
                level=level,
                parent_level=level - 1,
            )
        self.stack.append((level, record.code))


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
    """Derive every referencing register from the official layout fields."""
    result: dict[str, dict[str, str]] = {name: {} for name in _DECLARED}
    for code, register in layout.registers.items():
        names = register.field_names
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


class CrossrefChecks:
    """0150/0200/0190 references used by documents and items."""

    def __init__(self, layout: Layout) -> None:
        self.users = _users(layout)
        codes = set(_DECLARED.values())
        self.declared: dict[str, dict[str, int]] = {code: {} for code in codes}
        self.seen: dict[str, set[str]] = {code: set() for code in codes}
        self.uses: dict[tuple[str, str, str], int] = {}

    def feed(self, record: Record, ctx: ValidationContext) -> None:
        code = record.code
        if code in _DECLARED.values():
            field_name = code_field(code)
            value = record.raw_get(field_name)
            if value:
                self.declared[code].setdefault(value, record.line_no)
                if value in self.seen[code]:
                    ctx.emit_id(
                        "SPED-XREF-DUP-001",
                        line=record.line_no,
                        code=code,
                        register=code,
                        field=field_name,
                        value=value,
                    )
                self.seen[code].add(value)
        for field_name, users in self.users.items():
            local_field = users.get(code)
            if local_field is None:
                continue
            value = record.raw_get(local_field)
            if value:
                self.uses.setdefault((field_name, value, code), record.line_no)

    def finish(self, ctx: ValidationContext) -> None:
        rules = {field_name: rule_id for field_name, _decl, rule_id, _label in _REFERENCES}
        for (field_name, value, code), line in self.uses.items():
            declared = self.declared[_DECLARED[field_name]]
            if value in declared:
                if declared[value] > line:
                    ctx.emit_id(
                        "SPED-XREF-ORDER-001",
                        line=line,
                        code=code,
                        register=code,
                        field=field_name,
                        value=value,
                        declared=declared[value],
                    )
                continue
            declared_code = _DECLARED[field_name]
            ctx.emit_id(
                rules[field_name],
                line=line,
                code=code,
                register=code,
                value=value,
                field=field_name,
                declared_register=declared_code,
            )


def code_field(code: str) -> str:
    """Campo chave do registro de cadastro ``code``."""
    return "UNID" if code == "0190" else ("COD_ITEM" if code == "0200" else "COD_PART")
