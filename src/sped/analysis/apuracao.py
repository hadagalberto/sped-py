"""Recálculo da apuração de ICMS/IPI, PIS/COFINS e saldos contábeis.

Todas as fórmulas vêm dos mesmos documentos oficiais já citados pelo validador
(``sped.validation.rules``) e são implementadas uma única vez, em
``sped.validation.totals``. Este módulo apenas as aplica e compara com os valores
informados pelo contribuinte, permitindo recomputar um arquivo corrigido.

Fontes (verificadas em 2026-11-20):

* Guia Prático da EFD ICMS/IPI v3.2.4, E110 —
  https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@display-file/file
* Guia Prático da EFD-Contribuições v1.35, M200/M210/M600/M610 —
  http://sped.rfb.gov.br/estatico/AD/06A0F5C4E4CC8CA16035EB891A3AE31EA79708/Guia_Pratico_EFD_Contribuicoes_Versao_1_35%20-%2018_06_2021.pdf
* Manual de Orientação da ECD (I155) e da ECF (C155/E155/K155) — URLs em
  ``sped.validation.rules.MANUAL_ECD`` / ``MANUAL_ECF``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Final

from sped.core.reader import SpedReader
from sped.core.types import Layout, Record
from sped.core.writer import OutputRecord, write
from sped.layouts import detect_layout
from sped.validation.context import number
from sped.validation.totals import (
    C190_COMPARE_FIELDS,
    COD_CONT_CUM,
    COD_CONT_NC,
    compute_c190_groups,
    compute_consolidation,
    compute_cont_summary,
    compute_detail_fields,
    compute_e110_fields,
    compute_icms_totals,
    compute_saldo_final,
)

#: (campo de acréscimo, campo de redução) da base de cálculo ajustada.
_DETAIL_ADJUSTMENTS: Final[dict[str, tuple[str, str]]] = {
    "M210": ("VL_AJUS_ACRES_BC_PIS", "VL_AJUS_REDUC_BC_PIS"),
    "M610": ("VL_AJUS_ACRES_BC_COFINS", "VL_AJUS_REDUC_BC_COFINS"),
}

#: (saldo inicial, indicador inicial, saldo final, indicador final) dos saldos.
_SALDO_REGISTERS: Final[dict[str, tuple[str, str, str, str]]] = {
    "I155": ("VL_SLD_INI", "IND_DC_INI", "VL_SLD_FIN", "IND_DC_FIN"),
    "C155": ("VL_SLD_INI", "IND_VL_SLD_INI", "VL_SLD_FIN", "IND_VL_SLD_FIN"),
    "E155": ("VL_SLD_INI", "IND_VL_SLD_INI", "VL_SLD_FIN", "IND_VL_SLD_FIN"),
    "K155": ("VL_SLD_INI", "IND_VL_SLD_INI", "VL_SLD_FIN", "IND_VL_SLD_FIN"),
}

_Computed = dict[tuple[str, int], dict[str, Decimal | str]]


def _group_key(record: Record, parent_line: int) -> tuple[int, str, str, str]:
    return (
        parent_line,
        record.raw_get("CST_ICMS"),
        record.raw_get("CFOP"),
        record.raw_get("ALIQ_ICMS"),
    )


def _computed_fields(  # noqa: PLR0912
    records: tuple[Record, ...], layout: Layout
) -> _Computed:
    """Mapa ``(registro, linha) -> {campo: valor apurado}`` por obrigação."""
    result: _Computed = {}
    if layout.obrigacao == "efd_icmsipi":
        totals = compute_icms_totals(records)
        for record in records:
            if record.code == "E110":
                result[(record.code, record.line_no)] = dict(compute_e110_fields(record, totals))
        groups = compute_c190_groups(records)
        current_c100 = 0
        for record in records:
            if record.code == "C100":
                current_c100 = record.line_no
            elif record.code == "C190":
                group = groups.get(_group_key(record, current_c100))
                if group is not None:
                    result[(record.code, record.line_no)] = {
                        name: group[name] for name in C190_COMPARE_FIELDS
                    }
    elif layout.obrigacao == "efd_contribuicoes":
        for record in records:
            if record.code in _DETAIL_ADJUSTMENTS:
                acres, reduc = _DETAIL_ADJUSTMENTS[record.code]
                result[(record.code, record.line_no)] = dict(
                    compute_detail_fields(record, acres, reduc)
                )
            elif record.code in {"M200", "M600"}:
                detail_code = "M210" if record.code == "M200" else "M610"
                computed: dict[str, Decimal | str] = {
                    "VL_TOT_CONT_NC_PER": compute_cont_summary(records, detail_code, COD_CONT_NC),
                    "VL_TOT_CONT_CUM_PER": compute_cont_summary(records, detail_code, COD_CONT_CUM),
                }
                computed.update(compute_consolidation(record))
                result[(record.code, record.line_no)] = computed
    elif layout.obrigacao in {"ecd", "ecf"}:
        for record in records:
            spec = _SALDO_REGISTERS.get(record.code)
            if spec is None:
                continue
            value, signal = compute_saldo_final(record, *spec)
            result[(record.code, record.line_no)] = {
                spec[2]: value,
                spec[3]: signal,
            }
    return result


@dataclass(frozen=True, slots=True)
class ApuracaoField:
    """Comparação entre o valor informado e o valor apurado de um campo."""

    register: str
    field: str
    line_no: int
    stated: Decimal | str
    computed: Decimal | str

    @property
    def difference(self) -> Decimal | None:
        """Diferença apurado - informado, quando ambos são numéricos."""
        if isinstance(self.computed, Decimal) and isinstance(self.stated, Decimal):
            return self.computed - self.stated
        return None

    @property
    def ok(self) -> bool:
        """True quando informado e apurado coincidem."""
        return self.stated == self.computed

    def as_dict(self) -> dict[str, object]:
        """Representação serializável."""
        difference = self.difference
        return {
            "registro": self.register,
            "campo": self.field,
            "linha": self.line_no,
            "informado": str(self.stated),
            "apurado": str(self.computed),
            "diferenca": None if difference is None else str(difference),
            "ok": self.ok,
        }


@dataclass(frozen=True, slots=True)
class ApuracaoResult:
    """Resultado do recálculo de apuração de um arquivo."""

    obrigacao: str
    cod_ver: str
    period: tuple[str, str]
    fields: tuple[ApuracaoField, ...]

    @property
    def divergences(self) -> tuple[ApuracaoField, ...]:
        """Campos cujo valor informado difere do apurado."""
        return tuple(field for field in self.fields if not field.ok)

    @property
    def ok(self) -> bool:
        """True quando todos os campos conferem."""
        return not self.divergences

    def as_dict(self) -> dict[str, object]:
        """Representação serializável (JSON/CLI)."""
        return {
            "obrigacao": self.obrigacao,
            "cod_ver": self.cod_ver,
            "periodo": {"inicio": self.period[0], "fim": self.period[1]},
            "ok": self.ok,
            "divergencias": len(self.divergences),
            "campos": [field.as_dict() for field in self.fields],
        }


def compute_apuracao(records: Iterable[Record], *, layout: Layout) -> ApuracaoResult:
    """Recalcula e compara todos os campos de apuração de um arquivo."""
    materialized = tuple(records)
    computed = _computed_fields(materialized, layout)
    opening = next((record for record in materialized if record.code == "0000"), None)
    period = (
        (opening.raw_get("DT_INI"), opening.raw_get("DT_FIN")) if opening is not None else ("", "")
    )
    comparisons: list[ApuracaoField] = []
    for record in materialized:
        values = computed.get((record.code, record.line_no))
        if values is None:
            continue
        for field_name, expected in values.items():
            stated: Decimal | str = (
                record.raw_get(field_name)
                if isinstance(expected, str)
                else number(record, field_name)
            )
            comparisons.append(
                ApuracaoField(
                    register=record.code,
                    field=field_name,
                    line_no=record.line_no,
                    stated=stated,
                    computed=expected,
                )
            )
    return ApuracaoResult(
        obrigacao=layout.obrigacao,
        cod_ver=layout.cod_ver,
        period=period,
        fields=tuple(comparisons),
    )


def _format_raw(value: Decimal | str, dec: int) -> str:
    """Formato numérico SPED: vírgula decimal, sem casas implícitas."""
    if isinstance(value, str):
        return value
    if dec == 0:
        return str(int(value.to_integral_value()))
    text = f"{value:.{dec}f}"
    integral, _, fractional = text.partition(".")
    return f"{integral},{fractional}"


def _replace_field(record: Record, layout: Layout, field_name: str, raw: str) -> Record:
    """Devolve ``record`` com um campo alterado (valor cru e convertido)."""
    definition = layout.register(record.code).field(field_name)
    fields = tuple(
        replace(field, raw=raw, value=definition.coerce(raw))
        if field.definition.name == field_name
        else field
        for field in record.fields
    )
    return replace(record, fields=fields)


def recompute_apuracao(
    path: str | Path,
    destination: str | Path | None = None,
    *,
    layout: Layout | None = None,
) -> Path:
    """Grava ``path`` com os campos de apuração recalculados a partir dos detalhes.

    Os totais estruturais (x990/9900/9999) também são recalculados pelo escritor.
    O arquivo de entrada não é modificado; ``destination`` usa o mesmo nome com
    o sufixo ``-apurado`` quando omitido.
    """
    source = Path(path)
    chosen = layout or detect_layout(source)
    if destination is None:
        destination = source.with_name(f"{source.stem}-apurado{source.suffix}")
    target = Path(destination)

    with SpedReader(source, layout=chosen, strict=False) as reader:
        records = tuple(reader.iter_records())
    computed = _computed_fields(records, chosen)
    totals = compute_icms_totals(records) if chosen.obrigacao == "efd_icmsipi" else None

    output: list[OutputRecord] = []
    for record in records:
        updates = dict(computed.get((record.code, record.line_no), {}))
        if record.code == "E110" and totals is not None:
            # Os campos derivados dependem dos totais informados; aplica primeiro
            # VL_TOT_DEBITOS/CREDITOS e só depois recalcula o saldo.
            staged = record
            for name in ("VL_TOT_DEBITOS", "VL_TOT_CREDITOS"):
                if name in updates:
                    dec = chosen.register(record.code).field(name).dec
                    staged = _replace_field(staged, chosen, name, _format_raw(updates[name], dec))
            updates.update(compute_e110_fields(staged, totals))
        elif record.code in {"M200", "M600"}:
            # A consolidação de M200/M600 depende dos totais de M210/M610.
            staged = record
            for name in ("VL_TOT_CONT_NC_PER", "VL_TOT_CONT_CUM_PER"):
                if name in updates:
                    dec = chosen.register(record.code).field(name).dec
                    staged = _replace_field(staged, chosen, name, _format_raw(updates[name], dec))
            updates.update(compute_consolidation(staged))
        updated = record
        for field_name, expected in updates.items():
            dec = chosen.register(record.code).field(field_name).dec
            updated = _replace_field(updated, chosen, field_name, _format_raw(expected, dec))
        raw_values = list(updated.raw_values)
        if raw_values and raw_values[0] == updated.code:
            raw_values = raw_values[1:]
        output.append((updated.code, tuple(raw_values)))

    write(output, target, layout=chosen)
    return target
