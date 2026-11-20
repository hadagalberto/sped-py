"""Regras de totalização por obrigação, segundo os manuais oficiais.

Cada fórmula aplicada aqui está documentada no campo correspondente do leiaute
oficial (ver ``src/sped/validation/rules.py`` para as fontes e seções).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sped.core.types import Record
from sped.validation.context import ValidationContext, money, number

ZERO: Final = Decimal(0)

#: Códigos de registro que alimentam a apuração do ICMS (ver DEBIT_REGISTERS e
#: CREDIT_REGISTERS abaixo, extraídos do Guia Prático EFD ICMS/IPI v3.2.4).
DEBIT_REGISTERS: Final[tuple[str, ...]] = (
    "C190",
    "C320",
    "C390",
    "C490",
    "C590",
    "C690",
    "C790",
    "C850",
    "C890",
    "D190",
    "D300",
    "D390",
    "D410",
    "D590",
    "D690",
    "D696",
    "D730",
    "D760",
)
CREDIT_REGISTERS: Final[tuple[str, ...]] = ("C190", "C590", "D190", "D590", "D730")
EXCLUDED_COD_SIT: Final = frozenset({"01", "07", "10"})

#: Guia Prático EFD-Contribuições v1.35, M200/M600 campos 02 e 09.
COD_CONT_NC: Final = frozenset({"01", "02", "03", "04", "32", "71"})
COD_CONT_CUM: Final = frozenset({"31", "32", "51", "52", "53", "54", "72"})

#: C190 campo 05 a 11 ← soma dos campos correspondentes dos C170 (exceto
#: VL_RED_BC, que é a soma de VL_ITEM menos VL_BC_ICMS).
C190_SUMS: Final[tuple[tuple[str, str], ...]] = (
    ("VL_BC_ICMS", "VL_BC_ICMS"),
    ("VL_ICMS", "VL_ICMS"),
    ("VL_BC_ICMS_ST", "VL_BC_ICMS_ST"),
    ("VL_ICMS_ST", "VL_ICMS_ST"),
    ("VL_IPI", "VL_IPI"),
)
C190_COMPARE_FIELDS: Final[tuple[str, ...]] = (
    "VL_BC_ICMS",
    "VL_ICMS",
    "VL_BC_ICMS_ST",
    "VL_ICMS_ST",
    "VL_IPI",
    "VL_RED_BC",
)
E110_DEBIT_FIELDS: Final[tuple[str, ...]] = (
    "VL_TOT_DEBITOS",
    "VL_AJ_DEBITOS",
    "VL_TOT_AJ_DEBITOS",
    "VL_ESTORNOS_CRED",
)
E110_CREDIT_FIELDS: Final[tuple[str, ...]] = (
    "VL_TOT_CREDITOS",
    "VL_AJ_CREDITOS",
    "VL_TOT_AJ_CREDITOS",
    "VL_ESTORNOS_DEB",
)


_ICMS_SOURCE_CODES: Final[frozenset[str]] = frozenset(
    dict.fromkeys((*DEBIT_REGISTERS, *CREDIT_REGISTERS))
)


@dataclass(frozen=True, slots=True)
class IcmsTotals:
    """Débitos e créditos de ICMS apurados dos registros de documento."""

    debitos: Decimal
    creditos: Decimal


def compute_icms_totals(records: Iterable[Record]) -> IcmsTotals:
    """Soma VL_ICMS dos registros de débito/crédito, em uma única passada.

    Réplica exata da apuração usada pelo validador: registros com ``COD_SIT``
    em ``EXCLUDED_COD_SIT`` são ignorados; CFOP 5605 (débito) e 1605 (crédito)
    são estornos e não entram na apuração. Fonte: Guia Prático EFD ICMS/IPI
    v3.2.4, campos E110 02 e 06 (URL completa em ``validation.rules.GUIDA_ICMS``).
    """
    debitos = ZERO
    creditos = ZERO
    # One parent per block: a D190 must inherit D100's COD_SIT/IND_OPER, never
    # a stale C100 from the previous block. Using ``last_c100 or last_d100``
    # short-circuits to C forever once any C100 has been seen.
    parents: dict[str, Record | None] = {"C": None, "D": None}
    for record in records:
        if record.code == "C100":
            parents["C"] = record
            continue
        if record.code == "D100":
            parents["D"] = record
            continue
        if record.code not in _ICMS_SOURCE_CODES:
            continue
        parent = parents.get(record.code[0])
        if parent is not None and parent.raw_get("COD_SIT") in EXCLUDED_COD_SIT:
            continue
        operation = parent.raw_get("IND_OPER") if parent is not None else ""
        cfop = record.raw_get("CFOP")
        is_debit = record.code not in CREDIT_REGISTERS or operation == "1"
        if is_debit:
            if cfop != "5605":
                debitos += number(record, "VL_ICMS")
        elif cfop != "1605":
            creditos += number(record, "VL_ICMS")
    return IcmsTotals(debitos, creditos)


def compute_e110_fields(record: Record, totals: IcmsTotals) -> dict[str, Decimal]:
    """Campos apuráveis do E110, segundo o Guia Prático EFD ICMS/IPI v3.2.4."""
    debitos = sum((number(record, name) for name in E110_DEBIT_FIELDS), ZERO)
    creditos = sum((number(record, name) for name in E110_CREDIT_FIELDS), ZERO)
    saldo = debitos - creditos - number(record, "VL_SLD_CREDOR_ANT")
    apurado = max(ZERO, saldo)
    return {
        "VL_TOT_DEBITOS": totals.debitos,
        "VL_TOT_CREDITOS": totals.creditos,
        "VL_SLD_APURADO": apurado,
        "VL_ICMS_RECOLHER": apurado - number(record, "VL_TOT_DED"),
        "VL_SLD_CREDOR_TRANSPORTAR": max(ZERO, -saldo),
    }


def compute_detail_fields(record: Record, acres_bc: str, reduc_bc: str) -> dict[str, Decimal]:
    """VL_BC_CONT_AJUS e VL_CONT_PER de M210/M610 (Guia EFD-Contribuições v1.35)."""
    return {
        "VL_BC_CONT_AJUS": (
            number(record, "VL_BC_CONT") + number(record, acres_bc) - number(record, reduc_bc)
        ),
        "VL_CONT_PER": (
            number(record, "VL_CONT_APUR")
            + number(record, "VL_AJUS_ACRES")
            - number(record, "VL_AJUS_REDUC")
            - number(record, "VL_CONT_DIFER")
            + number(record, "VL_CONT_DIFER_ANT")
        ),
    }


def compute_cont_summary(records: Iterable[Record], code: str, codes: frozenset[str]) -> Decimal:
    """Soma VL_CONT_PER de ``code`` filtrando COD_CONT (M200/M600)."""
    return sum(
        (
            number(record, "VL_CONT_PER")
            for record in records
            if record.code == code and record.raw_get("COD_CONT") in codes
        ),
        ZERO,
    )


def compute_consolidation(record: Record) -> dict[str, Decimal]:
    """Campos 05, 08, 12 e 13 de M200/M600 (Guia EFD-Contribuições v1.35)."""
    due = (
        number(record, "VL_TOT_CONT_NC_PER")
        - number(record, "VL_TOT_CRED_DESC")
        - number(record, "VL_TOT_CRED_DESC_ANT")
    )
    nc_rec = due - number(record, "VL_RET_NC") - number(record, "VL_OUT_DED_NC")
    cum_rec = (
        number(record, "VL_TOT_CONT_CUM_PER")
        - number(record, "VL_RET_CUM")
        - number(record, "VL_OUT_DED_CUM")
    )
    return {
        "VL_TOT_CONT_NC_DEV": due,
        "VL_CONT_NC_REC": nc_rec,
        "VL_CONT_CUM_REC": cum_rec,
        "VL_TOT_CONT_REC": nc_rec + cum_rec,
    }


def compute_saldo_final(
    record: Record, ini_field: str, ind_ini: str, fin_field: str, ind_fin: str
) -> tuple[Decimal, str]:
    """Saldo final contábil: valor absoluto e sinal (D devedor / C credor).

    Fonte: Manual de Orientação da ECD (I155) e da ECF (C155/E155/K155), URLs
    em ``validation.rules.MANUAL_ECD`` e ``validation.rules.MANUAL_ECF``.
    """
    initial = number(record, ini_field)
    if record.raw_get(ind_ini) == "C":
        initial = -initial
    result = initial + number(record, "VL_DEB") - number(record, "VL_CRED")
    return abs(result), ("C" if result < 0 else "D")


def _compare(
    ctx: ValidationContext,
    rule_id: str,
    stated: Decimal,
    computed: Decimal,
    *,
    line: int,
    code: str,
    **extra: object,
) -> None:
    if stated != computed:
        ctx.emit_id(
            rule_id,
            line=line,
            code=code,
            stated=money(stated),
            computed=money(computed),
            **extra,
        )


def check_icms_ipi(ctx: ValidationContext) -> None:
    """C100/C170, C190 e E110 — Guia Prático EFD ICMS/IPI v3.2.4."""
    if ctx.layout.obrigacao != "efd_icmsipi":
        return
    _check_c170_against_c100(ctx)
    _check_c190(ctx)
    _check_e110(ctx)


def _check_c170_against_c100(ctx: ValidationContext) -> None:
    sums: dict[int, Decimal] = {}
    current: int | None = None
    for record in ctx.records:
        if record.code == "C100":
            current = record.line_no
            sums.setdefault(current, ZERO)
        elif record.code == "C170" and current is not None:
            sums[current] += number(record, "VL_ITEM")
    for record in ctx.get("C100"):
        computed = sums.get(record.line_no, ZERO)
        if computed:
            _compare(
                ctx,
                "SPED-TOT-ICMS-C170-001",
                number(record, "VL_MERC"),
                computed,
                line=record.line_no,
                code="C100",
            )


def _group_key(record: Record, parent_line: int) -> tuple[int, str, str, str]:
    return (
        parent_line,
        record.raw_get("CST_ICMS"),
        record.raw_get("CFOP"),
        record.raw_get("ALIQ_ICMS"),
    )


def compute_c190_groups(
    records: Iterable[Record],
) -> dict[tuple[int, str, str, str], dict[str, Decimal]]:
    """Agrupa C170 por C100/CST/CFOP/ALIQ e soma os campos do C190.

    Fonte: Guia Prático EFD ICMS/IPI v3.2.4, registro C190 campos 05 a 11.
    """
    groups: dict[tuple[int, str, str, str], dict[str, Decimal]] = {}
    current: int | None = None
    for record in records:
        if record.code == "C100":
            current = record.line_no
        elif record.code == "C170" and current is not None:
            bucket = groups.setdefault(
                _group_key(record, current),
                {name: ZERO for name, _ in C190_SUMS} | {"VL_RED_BC": ZERO},
            )
            for c190_field, c170_field in C190_SUMS:
                bucket[c190_field] += number(record, c170_field)
            bucket["VL_RED_BC"] += number(record, "VL_ITEM") - number(record, "VL_BC_ICMS")
    return groups


def _check_c190(ctx: ValidationContext) -> None:
    groups = compute_c190_groups(ctx.records)

    seen: set[tuple[int, str, str, str]] = set()
    for record in ctx.get("C190"):
        parent = ctx.parent(record, "C100")
        if parent is None:
            continue
        key = _group_key(record, parent.line_no)
        if key in seen:
            ctx.emit_id(
                "SPED-TOT-ICMS-C190-002",
                line=record.line_no,
                code="C190",
                value="/".join(key[1:]),
            )
        seen.add(key)
        matching_group = groups.get(key)
        if matching_group is None:
            continue
        for field_name in C190_COMPARE_FIELDS:
            _compare(
                ctx,
                "SPED-TOT-ICMS-C190-001",
                number(record, field_name),
                matching_group[field_name],
                line=record.line_no,
                code="C190",
                field=field_name,
            )


def _check_e110(ctx: ValidationContext) -> None:
    totals = compute_icms_totals(ctx.records)
    for record in ctx.get("E110"):
        computed_fields = compute_e110_fields(record, totals)
        for field_name in ("VL_TOT_DEBITOS", "VL_TOT_CREDITOS"):
            _compare(
                ctx,
                "SPED-TOT-ICMS-E110-001",
                number(record, field_name),
                computed_fields[field_name],
                line=record.line_no,
                code="E110",
                field=field_name,
            )
        _compare(
            ctx,
            "SPED-TOT-ICMS-E110-002",
            number(record, "VL_SLD_APURADO"),
            computed_fields["VL_SLD_APURADO"],
            line=record.line_no,
            code="E110",
        )
        _compare(
            ctx,
            "SPED-TOT-ICMS-E110-003",
            number(record, "VL_ICMS_RECOLHER"),
            computed_fields["VL_ICMS_RECOLHER"],
            line=record.line_no,
            code="E110",
        )
        _compare(
            ctx,
            "SPED-TOT-ICMS-E110-004",
            number(record, "VL_SLD_CREDOR_TRANSPORTAR"),
            computed_fields["VL_SLD_CREDOR_TRANSPORTAR"],
            line=record.line_no,
            code="E110",
        )


def check_contribuicoes(ctx: ValidationContext) -> None:
    """M210/M610, M200 e M600 — Guia Prático EFD-Contribuições v1.35."""
    if ctx.layout.obrigacao != "efd_contribuicoes":
        return
    _check_m210(ctx)
    _check_m610(ctx)
    _check_m200(ctx)
    _check_m600(ctx)


def _check_detail(  # noqa: PLR0917
    ctx: ValidationContext,
    code: str,
    acres_bc: str,
    reduc_bc: str,
    step1_rule: str,
    step2_rule: str,
) -> None:
    for record in ctx.get(code):
        expected = compute_detail_fields(record, acres_bc, reduc_bc)
        _compare(
            ctx,
            step1_rule,
            number(record, "VL_BC_CONT_AJUS"),
            expected["VL_BC_CONT_AJUS"],
            line=record.line_no,
            code=code,
        )
        _compare(
            ctx,
            step2_rule,
            number(record, "VL_CONT_PER"),
            expected["VL_CONT_PER"],
            line=record.line_no,
            code=code,
        )


def _check_m210(ctx: ValidationContext) -> None:
    _check_detail(
        ctx,
        "M210",
        "VL_AJUS_ACRES_BC_PIS",
        "VL_AJUS_REDUC_BC_PIS",
        "SPED-TOT-CONTRIB-M210-001",
        "SPED-TOT-CONTRIB-M210-002",
    )


def _check_m610(ctx: ValidationContext) -> None:
    _check_detail(
        ctx,
        "M610",
        "VL_AJUS_ACRES_BC_COFINS",
        "VL_AJUS_REDUC_BC_COFINS",
        "SPED-TOT-CONTRIB-M610-001",
        "SPED-TOT-CONTRIB-M610-002",
    )


def _check_m200(ctx: ValidationContext) -> None:
    for record in ctx.get("M200"):
        for field_name, rule_id, selected in (
            ("VL_TOT_CONT_NC_PER", "SPED-TOT-CONTRIB-M200-001", COD_CONT_NC),
            ("VL_TOT_CONT_CUM_PER", "SPED-TOT-CONTRIB-M200-001", COD_CONT_CUM),
        ):
            _compare(
                ctx,
                rule_id,
                number(record, field_name),
                compute_cont_summary(ctx.records, "M210", selected),
                line=record.line_no,
                code="M200",
                field=field_name,
            )
        _check_consolidation(ctx, record, "SPED-TOT-CONTRIB-M200-002")


def _check_m600(ctx: ValidationContext) -> None:
    for record in ctx.get("M600"):
        for field_name, rule_id, selected in (
            ("VL_TOT_CONT_NC_PER", "SPED-TOT-CONTRIB-M600-001", COD_CONT_NC),
            ("VL_TOT_CONT_CUM_PER", "SPED-TOT-CONTRIB-M600-001", COD_CONT_CUM),
        ):
            _compare(
                ctx,
                rule_id,
                number(record, field_name),
                compute_cont_summary(ctx.records, "M610", selected),
                line=record.line_no,
                code="M600",
                field=field_name,
            )
        _check_consolidation(ctx, record, "SPED-TOT-CONTRIB-M600-002")


def _check_consolidation(ctx: ValidationContext, record: Record, rule_id: str) -> None:
    """Fórmulas dos campos 05, 08, 12 e 13 de M200/M600."""
    for field_name, computed in compute_consolidation(record).items():
        _compare(
            ctx,
            rule_id,
            number(record, field_name),
            computed,
            line=record.line_no,
            code=record.code,
            field=field_name,
        )


def check_ecd(ctx: ValidationContext) -> None:
    """I155 — REGRA_VALIDACAO_DEB_DIF_CRED e REGRA_VALIDACAO_SALDO_FINAL."""
    if ctx.layout.obrigacao != "ecd":
        return
    periods = sorted((ctx.positions[record.line_no], record) for record in ctx.get("I150"))
    debitos: dict[int, Decimal] = {}
    creditos: dict[int, Decimal] = {}
    for record in ctx.get("I155"):
        position = ctx.positions[record.line_no]
        current = max((p for p, _ in periods if p <= position), default=-1)
        debitos[current] = debitos.get(current, ZERO) + number(record, "VL_DEB")
        creditos[current] = creditos.get(current, ZERO) + number(record, "VL_CRED")
        _check_saldo(
            ctx,
            record,
            "SPED-TOT-ECD-002",
            "VL_SLD_INI",
            "IND_DC_INI",
            "VL_SLD_FIN",
            "IND_DC_FIN",
        )
    for position, period in periods:
        if position in debitos and debitos[position] != creditos.get(position, ZERO):
            label = f"{period.raw_get('DT_INI')}-{period.raw_get('DT_FIN')}"
            ctx.emit_id(
                "SPED-TOT-ECD-001",
                code="I155",
                period=label,
                computed=money(debitos[position]),
                stated=money(creditos.get(position, ZERO)),
            )


def _check_saldo(  # noqa: PLR0917
    ctx: ValidationContext,
    record: Record,
    rule_id: str,
    ini_field: str,
    ind_ini: str,
    fin_field: str,
    ind_fin: str,
) -> None:
    """saldo final = saldo inicial (com sinal) + débitos - créditos."""
    expected_abs, expected_signal = compute_saldo_final(
        record, ini_field, ind_ini, fin_field, ind_fin
    )
    stated = f"{money(number(record, fin_field))}/{record.raw_get(ind_fin) or '-'}"
    computed = f"{money(expected_abs)}/{expected_signal}"
    if number(record, fin_field) != expected_abs or (
        record.raw_get(ind_fin) and record.raw_get(ind_fin) != expected_signal
    ):
        ctx.emit_id(
            rule_id,
            line=record.line_no,
            code=record.code,
            stated=stated,
            computed=computed,
        )


def check_ecf(ctx: ValidationContext) -> None:
    """C155/E155/K155 — saldos contábeis do Manual de Orientação da ECF."""
    if ctx.layout.obrigacao != "ecf":
        return
    for code in ("C155", "E155", "K155"):
        for record in ctx.get(code):
            _check_saldo(
                ctx,
                record,
                "SPED-TOT-ECF-001",
                "VL_SLD_INI",
                "IND_VL_SLD_INI",
                "VL_SLD_FIN",
                "IND_VL_SLD_FIN",
            )


def check_all(ctx: ValidationContext) -> None:
    """Run every totalization check in a deterministic order."""
    check_icms_ipi(ctx)
    check_contribuicoes(ctx)
    check_ecd(ctx)
    check_ecf(ctx)
