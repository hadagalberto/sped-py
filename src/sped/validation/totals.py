"""Regras de totalização por obrigação, segundo os manuais oficiais.

Cada fórmula aplicada aqui está documentada no campo correspondente do leiaute
oficial (ver ``src/sped/validation/rules.py`` para as fontes e seções). As
verificações consomem registros um a um e guardam apenas agregados, mantendo
memória constante mesmo em arquivos de vários GB.
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


def _icms_contribution(record: Record, parent: Record | None) -> tuple[Decimal, Decimal]:
    """Débito/crédito de um registro, já aplicadas as exclusões oficiais."""
    if parent is not None and parent.raw_get("COD_SIT") in EXCLUDED_COD_SIT:
        return ZERO, ZERO
    operation = parent.raw_get("IND_OPER") if parent is not None else ""
    cfop = record.raw_get("CFOP")
    is_debit = record.code not in CREDIT_REGISTERS or operation == "1"
    if is_debit:
        return (ZERO if cfop == "5605" else number(record, "VL_ICMS")), ZERO
    return ZERO, (ZERO if cfop == "1605" else number(record, "VL_ICMS"))


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
        debito, credito = _icms_contribution(record, parents.get(record.code[0]))
        debitos += debito
        creditos += credito
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


def _group_key_local(record: Record) -> tuple[str, str, str]:
    return (
        record.raw_get("CST_ICMS"),
        record.raw_get("CFOP"),
        record.raw_get("ALIQ_ICMS"),
    )


def _group_key(record: Record, parent_line: int) -> tuple[int, str, str, str]:
    return (parent_line, *_group_key_local(record))


def _empty_c190_bucket() -> dict[str, Decimal]:
    return {name: ZERO for name, _ in C190_SUMS} | {"VL_RED_BC": ZERO}


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
            bucket = groups.setdefault(_group_key(record, current), _empty_c190_bucket())
            for c190_field, c170_field in C190_SUMS:
                bucket[c190_field] += number(record, c170_field)
            bucket["VL_RED_BC"] += number(record, "VL_ITEM") - number(record, "VL_BC_ICMS")
    return groups


class TotalsChecks:
    """Verificações de totalização em uma única passada e memória limitada."""

    def __init__(self, obrigacao: str) -> None:
        self.obrigacao = obrigacao
        self.parents: dict[str, Record | None] = {"C": None, "D": None}
        self.debitos = ZERO
        self.creditos = ZERO
        self.current_c100: Record | None = None
        self.c170_sum = ZERO
        self.c190_groups: dict[tuple[str, str, str], dict[str, Decimal]] = {}
        self.c190_seen: set[tuple[str, str, str]] = set()
        #: E110 resume documentos que podem vir depois dele (ex.: arquivos
        #: mesclados), por isso a comparação usa os totais finais.
        self.e110_records: list[Record] = []
        self.m210_by_cod: dict[str, Decimal] = {}
        self.m610_by_cod: dict[str, Decimal] = {}
        #: M200/M600 resumem registros que podem vir depois deles no arquivo;
        #: a comparação é feita ao final (um registro por período).
        self.summary_records: list[Record] = []
        self.period: Record | None = None
        self.period_debitos = ZERO
        self.period_creditos = ZERO

    def feed(self, record: Record, ctx: ValidationContext) -> None:
        code = record.code
        if code in {"C100", "D100"}:
            self.parents[code[0]] = record
        if self.obrigacao == "efd_icmsipi":
            self._icms_ipi(record, ctx)
        elif self.obrigacao == "efd_contribuicoes":
            self._contribuicoes(record, ctx)
        elif self.obrigacao == "ecd":
            self._ecd(record, ctx)
        elif self.obrigacao == "ecf":
            self._ecf(record, ctx)

    def finish(self, ctx: ValidationContext) -> None:
        if self.obrigacao == "efd_icmsipi":
            self._close_c100(ctx)
            self._finish_e110(ctx)
        elif self.obrigacao == "efd_contribuicoes":
            self._finish_contribuicoes(ctx)
        elif self.obrigacao == "ecd":
            self._close_period(ctx)

    def _finish_contribuicoes(self, ctx: ValidationContext) -> None:
        for record in self.summary_records:
            code = record.code
            bucket = self.m210_by_cod if code == "M200" else self.m610_by_cod
            rule_id = "SPED-TOT-CONTRIB-M200-001" if code == "M200" else "SPED-TOT-CONTRIB-M600-001"
            for field_name, selected in (
                ("VL_TOT_CONT_NC_PER", COD_CONT_NC),
                ("VL_TOT_CONT_CUM_PER", COD_CONT_CUM),
            ):
                _compare(
                    ctx,
                    rule_id,
                    number(record, field_name),
                    sum((value for cod, value in bucket.items() if cod in selected), ZERO),
                    line=record.line_no,
                    code=code,
                    field=field_name,
                )

    # --- EFD ICMS/IPI -------------------------------------------------------

    def _icms_ipi(self, record: Record, ctx: ValidationContext) -> None:
        code = record.code
        if code == "C100":
            self._close_c100(ctx)
            self.current_c100 = record
            self.c170_sum = ZERO
            self.c190_groups = {}
            self.c190_seen = set()
        elif code == "C170":
            if self.current_c100 is not None:
                self.c170_sum += number(record, "VL_ITEM")
                bucket = self.c190_groups.setdefault(_group_key_local(record), _empty_c190_bucket())
                for c190_field, c170_field in C190_SUMS:
                    bucket[c190_field] += number(record, c170_field)
                bucket["VL_RED_BC"] += number(record, "VL_ITEM") - number(record, "VL_BC_ICMS")
        elif code == "C190":
            self._check_c190(record, ctx)
        elif code == "E110":
            self.e110_records.append(record)
        if code in _ICMS_SOURCE_CODES:
            debito, credito = _icms_contribution(record, self.parents.get(code[0]))
            self.debitos += debito
            self.creditos += credito

    def _close_c100(self, ctx: ValidationContext) -> None:
        if self.current_c100 is None or not self.c170_sum:
            return
        _compare(
            ctx,
            "SPED-TOT-ICMS-C170-001",
            number(self.current_c100, "VL_MERC"),
            self.c170_sum,
            line=self.current_c100.line_no,
            code="C100",
        )

    def _finish_e110(self, ctx: ValidationContext) -> None:
        for record in self.e110_records:
            computed = compute_e110_fields(record, IcmsTotals(self.debitos, self.creditos))
            for field_name in ("VL_TOT_DEBITOS", "VL_TOT_CREDITOS"):
                _compare(
                    ctx,
                    "SPED-TOT-ICMS-E110-001",
                    number(record, field_name),
                    computed[field_name],
                    line=record.line_no,
                    code="E110",
                    field=field_name,
                )
            for rule_id, field_name in (
                ("SPED-TOT-ICMS-E110-002", "VL_SLD_APURADO"),
                ("SPED-TOT-ICMS-E110-003", "VL_ICMS_RECOLHER"),
                ("SPED-TOT-ICMS-E110-004", "VL_SLD_CREDOR_TRANSPORTAR"),
            ):
                _compare(
                    ctx,
                    rule_id,
                    number(record, field_name),
                    computed[field_name],
                    line=record.line_no,
                    code="E110",
                )

    def _check_c190(self, record: Record, ctx: ValidationContext) -> None:
        parent = ctx.parent(record, "C100")
        if parent is None:
            return
        key = _group_key_local(record)
        if key in self.c190_seen:
            ctx.emit_id(
                "SPED-TOT-ICMS-C190-002",
                line=record.line_no,
                code="C190",
                value="/".join(key),
            )
        self.c190_seen.add(key)
        matching = self.c190_groups.get(key)
        if matching is None:
            return
        for field_name in C190_COMPARE_FIELDS:
            _compare(
                ctx,
                "SPED-TOT-ICMS-C190-001",
                number(record, field_name),
                matching[field_name],
                line=record.line_no,
                code="C190",
                field=field_name,
            )

    # --- EFD-Contribuições --------------------------------------------------

    def _contribuicoes(self, record: Record, ctx: ValidationContext) -> None:
        code = record.code
        if code in {"M210", "M610"}:
            acres = "VL_AJUS_ACRES_BC_PIS" if code == "M210" else "VL_AJUS_ACRES_BC_COFINS"
            reduc = "VL_AJUS_REDUC_BC_PIS" if code == "M210" else "VL_AJUS_REDUC_BC_COFINS"
            step1 = "SPED-TOT-CONTRIB-M210-001" if code == "M210" else "SPED-TOT-CONTRIB-M610-001"
            step2 = "SPED-TOT-CONTRIB-M210-002" if code == "M210" else "SPED-TOT-CONTRIB-M610-002"
            expected = compute_detail_fields(record, acres, reduc)
            _compare(
                ctx,
                step1,
                number(record, "VL_BC_CONT_AJUS"),
                expected["VL_BC_CONT_AJUS"],
                line=record.line_no,
                code=code,
            )
            _compare(
                ctx,
                step2,
                number(record, "VL_CONT_PER"),
                expected["VL_CONT_PER"],
                line=record.line_no,
                code=code,
            )
            bucket = self.m210_by_cod if code == "M210" else self.m610_by_cod
            cod = record.raw_get("COD_CONT")
            bucket[cod] = bucket.get(cod, ZERO) + number(record, "VL_CONT_PER")
        elif code in {"M200", "M600"}:
            self.summary_records.append(record)
            consolidation_rule = (
                "SPED-TOT-CONTRIB-M200-002" if code == "M200" else "SPED-TOT-CONTRIB-M600-002"
            )
            for field_name, computed in compute_consolidation(record).items():
                _compare(
                    ctx,
                    consolidation_rule,
                    number(record, field_name),
                    computed,
                    line=record.line_no,
                    code=code,
                    field=field_name,
                )

    # --- ECD / ECF ----------------------------------------------------------

    def _ecd(self, record: Record, ctx: ValidationContext) -> None:
        code = record.code
        if code == "I150":
            self._close_period(ctx)
            self.period = record
            self.period_debitos = ZERO
            self.period_creditos = ZERO
        elif code == "I155":
            self.period_debitos += number(record, "VL_DEB")
            self.period_creditos += number(record, "VL_CRED")
            _check_saldo(
                ctx,
                record,
                "SPED-TOT-ECD-002",
                "VL_SLD_INI",
                "IND_DC_INI",
                "VL_SLD_FIN",
                "IND_DC_FIN",
            )

    def _close_period(self, ctx: ValidationContext) -> None:
        if self.period is None or self.period_debitos == self.period_creditos:
            return
        label = f"{self.period.raw_get('DT_INI')}-{self.period.raw_get('DT_FIN')}"
        ctx.emit_id(
            "SPED-TOT-ECD-001",
            code="I155",
            period=label,
            computed=money(self.period_debitos),
            stated=money(self.period_creditos),
        )

    def _ecf(self, record: Record, ctx: ValidationContext) -> None:
        if record.code in {"C155", "E155", "K155"}:
            _check_saldo(
                ctx,
                record,
                "SPED-TOT-ECF-001",
                "VL_SLD_INI",
                "IND_VL_SLD_INI",
                "VL_SLD_FIN",
                "IND_VL_SLD_FIN",
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
