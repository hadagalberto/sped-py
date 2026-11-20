"""Fábrica de arquivos SPED sintéticos, porém realistas.

Nenhum dado de contribuinte real é usado: CNPJ, inscrição estadual, nomes e
valores são fixtures determinísticos.  Os arquivos respeitam o leiaute oficial
carregado pelo ``COD_VER`` e passam nas validações do leitor.

Todas as quatro obrigações são cobertas (EFD ICMS/IPI, EFD-Contribuições, ECD
e ECF).  A fábrica escolhe registros presentes em **todas** as versões de cada
obrigação, de modo que um único gerador produza fixtures válidas para cada
``COD_VER`` publicado.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sped.core.types import Layout
from sped.core.writer import OutputRecord, format_line, write
from sped.layouts import load_layout

#: Variantes genéricas (quaisquer obrigações) usadas pelos testes legados.
BROKEN_KINDS: Final[tuple[str, ...]] = (
    "bad_field_size",
    "invalid_date",
    "unknown_register",
    "missing_block_closing",
    "wrong_file_total",
    "broken_framing",
)

#: Registros representativos comuns a todas as versões de cada obrigação.
SEQUENCES: Final[dict[str, tuple[str, ...]]] = {
    "efd_icmsipi": (
        "0000",
        "0001",
        "0005",
        "0100",
        "0150",
        "0190",
        "0200",
        "0990",
        "B001",
        "B990",
        "C001",
        "C100",
        "C170",
        "C190",
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
        "1990",
        "9001",
    ),
    "efd_contribuicoes": (
        "0000",
        "0001",
        "0110",
        "0150",
        "0190",
        "0200",
        "C001",
        "C100",
        "C170",
        "M001",
        "M200",
        "M210",
        "M600",
        "M610",
        "9001",
    ),
    "ecd": (
        "0000",
        "0001",
        "0007",
        "0150",
        "C001",
        "I001",
        "I010",
        "I050",
        "I150",
        "I155",
        "J001",
        "9001",
    ),
    "ecf": (
        "0000",
        "0001",
        "0010",
        "0930",
        "C001",
        "C040",
        "C155",
        "E001",
        "E010",
        "J001",
        "J050",
        "9001",
    ),
}


@dataclass(frozen=True, slots=True)
class SyntheticOptions:
    """Parâmetros determinísticos da fábrica."""

    cod_ver: str = "020"
    obrigacao: str = "efd_icmsipi"
    cnpj: str = "12345678000195"
    ie: str = "123456789012"
    uf: str = "SP"
    dt_ini: str = "01012024"
    dt_fin: str = "31122024"
    participant: str = "CLIENTE001"
    item: str = "PRODUTO001"
    perfil: str = "A"
    dc_ini: str = "D"
    dc_fin: str = "D"
    encoding: str = "latin-1"
    line_ending: str = "\r\n"
    with_signature: bool = False


def _values(  # noqa: PLR0912
    layout: Layout, code: str, overrides: dict[str, str]
) -> tuple[str, ...]:
    """Build values for every field of ``code`` from official definitions."""
    result: list[str] = []
    for definition in layout.register(code).fields:
        if definition.name == "REG":
            # O código do registro é escrito pelo writer, não faz parte dos valores.
            continue
        if f"{code}.{definition.name}" in overrides:
            result.append(overrides[f"{code}.{definition.name}"])
        elif definition.name in overrides:
            result.append(overrides[definition.name])
        elif definition.valid_values:
            result.append(definition.valid_values[0])
        elif definition.is_date or definition.name.startswith("DT_"):
            result.append(overrides.get("DT_INI", "01012024"))
        elif definition.name in {"CNPJ", "CNPJ_CPF_EMIT"}:
            result.append(overrides.get("CNPJ", "12345678000195"))
        elif definition.ftype == "N":
            if definition.dec:
                result.append("10000" if definition.dec == 2 else "1" + "0" * definition.dec)
            elif definition.exact and definition.size:
                result.append("1" * definition.size)
            else:
                result.append("1")
        elif definition.exact and definition.size:
            result.append("T" * definition.size)
        elif definition.size:
            result.append("T" * min(5, definition.size))
        else:
            result.append("TESTE")
    return tuple(result)


def _period(layout: Layout, options: SyntheticOptions) -> tuple[str, str]:
    """Período coerente com a vigência oficial do leiaute."""
    if options.obrigacao == "efd_icmsipi":
        return options.dt_ini, options.dt_fin
    year = layout.valid_from[:4]
    if not year.isdigit():
        year = "2024"
    return f"0101{year}", f"3112{year}"


def _overrides(layout: Layout, options: SyntheticOptions) -> dict[str, str]:
    dt_ini, dt_fin = _period(layout, options)
    values: dict[str, str] = {
        # A ECF publica COD_VER com 4 dígitos (0012); as demais, com 3.
        "COD_VER": layout.cod_ver.zfill(4) if options.obrigacao == "ecf" else layout.cod_ver,
        "COD_VER_LC": layout.versao,
        "DT_INI": dt_ini,
        "DT_FIN": dt_fin,
        "CNPJ": options.cnpj,
        "CNPJ_CPF_EMIT": options.cnpj,
        "CPF": "12345678909",
        "UF": options.uf,
        "IE": options.ie,
        "LECD": "LECD",
        "NOME_ESC": "LECF",
        "IND_MOV": "0",
        "IND_DAD": "0",
        "IND_ESC": "G",
        "TIPO_ESCRIT": "0",
        "RETIFICADORA": "N",
        "TIP_ECF": "0",
        "COD_PART": options.participant,
        "COD_ITEM": options.item,
        "UNID": "UN",
        "UNID_INV": "UN",
        "COD_MOD": "55",
        "COD_SIT": "00",
        "IND_OPER": "0",
        "IND_EMIT": "1",
        "CST_ICMS": "000",
        "CFOP": "1101",
        "CHV_NFE": "0" * 44,
        "DT_DOC": dt_ini,
        "DT_E_S": dt_ini,
        "NUM_ITEM": "1",
        "QTD": "1",
        "IND_PERFIL": options.perfil,
        # NCM real da tabela oficial (Receita Federal/Siscomex).
        "0200.COD_NCM": "84713011",
        # C170/C190: VL_RED_BC = soma(VL_ITEM - VL_BC_ICMS) = 0 no fixture.
        "C170.VL_DESC": "0",
        "C190.VL_RED_BC": "0",
        # E110: o único documento é de entrada (CFOP 1101), logo o ICMS de
        # 100,00 apurado em C190 vai para crédito e transporta como saldo.
        "E110.VL_TOT_DEBITOS": "0",
        "E110.VL_AJ_DEBITOS": "0",
        "E110.VL_TOT_AJ_DEBITOS": "0",
        "E110.VL_ESTORNOS_CRED": "0",
        "E110.VL_TOT_CREDITOS": "10000",
        "E110.VL_AJ_CREDITOS": "0",
        "E110.VL_TOT_AJ_CREDITOS": "0",
        "E110.VL_ESTORNOS_DEB": "0",
        "E110.VL_SLD_CREDOR_ANT": "0",
        "E110.VL_SLD_APURADO": "0",
        "E110.VL_TOT_DED": "0",
        "E110.VL_ICMS_RECOLHER": "0",
        "E110.VL_SLD_CREDOR_TRANSPORTAR": "10000",
        "E110.DEB_ESP": "0",
        # ECD I155: saldo inicial devedor 100 + débitos 100 - créditos 100
        # resulta em saldo final devedor 100 (D = devedor, C = credor).
        "IND_DC_INI": options.dc_ini,
        "IND_DC_FIN": options.dc_fin,
        # ECF C155: mesma convenção de sinais dos saldos contábeis.
        "C155.IND_VL_SLD_INI": options.dc_ini,
        "C155.IND_VL_SLD_FIN": options.dc_fin,
        # Contribuições: M210 (PIS) não cumulativo, M610 (COFINS) cumulativo.
        "M210.COD_CONT": "01",
        "M610.COD_CONT": "51",
        "M200.VL_TOT_CONT_NC_PER": "10000",
        "M200.VL_TOT_CRED_DESC": "0",
        "M200.VL_TOT_CRED_DESC_ANT": "0",
        "M200.VL_TOT_CONT_NC_DEV": "10000",
        "M200.VL_RET_NC": "0",
        "M200.VL_OUT_DED_NC": "0",
        "M200.VL_CONT_NC_REC": "10000",
        "M200.VL_TOT_CONT_CUM_PER": "0",
        "M200.VL_RET_CUM": "0",
        "M200.VL_OUT_DED_CUM": "0",
        "M200.VL_CONT_CUM_REC": "0",
        "M200.VL_TOT_CONT_REC": "10000",
        "M600.VL_TOT_CONT_NC_PER": "0",
        "M600.VL_TOT_CRED_DESC": "0",
        "M600.VL_TOT_CRED_DESC_ANT": "0",
        "M600.VL_TOT_CONT_NC_DEV": "0",
        "M600.VL_RET_NC": "0",
        "M600.VL_OUT_DED_NC": "0",
        "M600.VL_CONT_NC_REC": "0",
        "M600.VL_TOT_CONT_CUM_PER": "10000",
        "M600.VL_RET_CUM": "0",
        "M600.VL_OUT_DED_CUM": "0",
        "M600.VL_CONT_CUM_REC": "10000",
        "M600.VL_TOT_CONT_REC": "10000",
    }
    return values


def build_records(options: SyntheticOptions | None = None) -> list[OutputRecord]:
    """Return a realistic, complete record sequence for the given version."""
    opts = options or SyntheticOptions()
    layout = load_layout(opts.cod_ver, opts.obrigacao)
    sequence = SEQUENCES[opts.obrigacao]
    overrides = _overrides(layout, opts)
    for code in sequence:
        if code not in layout.registers:
            raise ValueError(f"{opts.obrigacao}/{opts.cod_ver}: registro {code} fora do leiaute")
    return [(code, _values(layout, code, overrides)) for code in sequence]


def write_synthetic(path: str | Path, options: SyntheticOptions | None = None) -> Path:
    """Write a valid synthetic SPED file and return its path."""
    opts = options or SyntheticOptions()
    destination = Path(path)
    layout = load_layout(opts.cod_ver, opts.obrigacao)
    buffer = io.BytesIO()
    write(
        build_records(opts),
        buffer,
        encoding=opts.encoding,
        line_ending=opts.line_ending,
        layout=layout,
    )
    data = buffer.getvalue()
    if opts.with_signature:
        data += ("SBMDSIG" + "A" * 64 + opts.line_ending).encode(opts.encoding)
    destination.write_bytes(data)
    return destination


@dataclass(frozen=True, slots=True)
class Mutation:
    """One deterministic defect applied to a valid synthetic file."""

    action: str
    code: str
    field: str = ""
    value: str = ""
    anchor: str = ""


#: Uma ou mais mutações por variante; cada regra do validador tem sua variante.
BROKEN_SPECS: Final[dict[str, tuple[Mutation, ...]]] = {
    "bad_field_size": (Mutation("set", "0000", "CNPJ", "X" * 30),),
    "invalid_date": (Mutation("set", "0000", "DT_INI", "31132024"),),
    "unknown_register": (Mutation("insert", "0000", value="|XXXX|valor|"),),
    "missing_block_closing": (Mutation("drop", "C990"),),
    "wrong_file_total": (Mutation("set", "9999", "QTD_LIN", "999"),),
    "broken_framing": (Mutation("unframe", ""),),
    "missing_0000": (Mutation("drop", "0000"),),
    "missing_perfil_record": (Mutation("drop", "0100"),),
    "invalid_perfil": (Mutation("set", "0000", "IND_PERFIL", "Z"),),
    "forbidden_perfil_record": (Mutation("set", "0000", "IND_PERFIL", "C"),),
    "invalid_cfop": (Mutation("set", "C170", "CFOP", "9999"),),
    "invalid_cst": (Mutation("set", "C170", "CST_ICMS", "999"),),
    "invalid_ncm": (Mutation("set", "0200", "COD_NCM", "99999999"),),
    "unknown_participant": (Mutation("set", "C100", "COD_PART", "NAOEXISTE"),),
    "unknown_item": (Mutation("set", "C170", "COD_ITEM", "NAOEXISTE"),),
    "unknown_unit": (Mutation("set", "C170", "UNID", "XXX"),),
    "late_participant": (Mutation("move", "0150", anchor="C170"),),
    "duplicate_participant": (Mutation("duplicate", "0150"),),
    "bad_c190_total": (Mutation("set", "C190", "VL_BC_ICMS", "20000"),),
    "duplicate_c190": (Mutation("duplicate", "C190"),),
    "bad_c170_total": (Mutation("set", "C170", "VL_ITEM", "20000"),),
    "bad_e110_apuracao": (Mutation("set", "E110", "VL_TOT_CREDITOS", "20000"),),
    "bad_e110_saldo": (Mutation("set", "E110", "VL_SLD_APURADO", "50000"),),
    "bad_e110_recolher": (Mutation("set", "E110", "VL_ICMS_RECOLHER", "50000"),),
    "bad_e110_transportar": (Mutation("set", "E110", "VL_SLD_CREDOR_TRANSPORTAR", "50000"),),
    "bad_9900_count": (Mutation("set", "9900", "QTD_REG_BLC", "999"),),
    "wrong_x990_count": (Mutation("set", "0990", "QTD_LIN_0", "999"),),
    "wrong_9990_count": (Mutation("set", "9990", "QTD_LIN_9", "888"),),
    "invalid_cnpj": (Mutation("set", "0000", "CNPJ", "12345678000196"),),
    "cfop_oper_mismatch": (Mutation("set", "C100", "IND_OPER", "1"),),
    "orphan_c170": (Mutation("before", "C170", anchor="C100"),),
    "bad_m210_bc": (Mutation("set", "M210", "VL_BC_CONT_AJUS", "20000"),),
    "bad_m210_per": (Mutation("set", "M210", "VL_CONT_PER", "20000"),),
    "bad_m610_bc": (Mutation("set", "M610", "VL_BC_CONT_AJUS", "20000"),),
    "bad_m610_per": (Mutation("set", "M610", "VL_CONT_PER", "20000"),),
    "bad_m200_detail": (Mutation("set", "M200", "VL_TOT_CONT_NC_PER", "20000"),),
    "bad_m200_total": (Mutation("set", "M200", "VL_TOT_CONT_NC_DEV", "20000"),),
    "bad_m600_detail": (Mutation("set", "M600", "VL_TOT_CONT_CUM_PER", "20000"),),
    "bad_m600_total": (Mutation("set", "M600", "VL_CONT_CUM_REC", "20000"),),
    "bad_ecd_balance": (Mutation("set", "I155", "VL_CRED", "20000"),),
    "bad_ecd_saldo": (Mutation("set", "I155", "IND_DC_FIN", "C"),),
    "bad_ecf_saldo": (Mutation("set", "C155", "IND_VL_SLD_FIN", "C"),),
}

#: Todas as variantes, inclusive as específicas por obrigação.
ALL_BROKEN_KINDS: Final[tuple[str, ...]] = tuple(BROKEN_SPECS)


def _field_index(layout_code: str, field: str, options: SyntheticOptions) -> int:
    """Position of ``field`` in a raw line (the implicit REG is not written)."""
    layout = load_layout(options.cod_ver, options.obrigacao)
    names = [definition.name for definition in layout.register(layout_code).fields]
    if names and names[0] == "REG":
        names = names[1:]
    try:
        return 2 + names.index(field)
    except ValueError:
        raise AssertionError(f"campo {field} não existe em {layout_code}") from None


def _fix_block_counts(lines: list[str], options: SyntheticOptions) -> list[str]:
    """Regenerate structural records after a mutation that moves lines.

    Only the ordering defect under test is kept; x990/9900/9999 stay correct so
    the variant does not accidentally trigger unrelated structural rules.
    """
    from sped.core.encoding import split_line  # noqa: PLC0415

    layout = load_layout(options.cod_ver, options.obrigacao)
    buffer = io.BytesIO()
    records = [split for line in lines if (split := split_line(line))]
    write(
        records,
        buffer,
        encoding=options.encoding,
        line_ending=options.line_ending,
        layout=layout,
    )
    return buffer.getvalue().decode(options.encoding).splitlines()


def _apply_mutation(  # noqa: PLR0911
    lines: list[str], mutation: Mutation, options: SyntheticOptions
) -> list[str]:
    action, code = mutation.action, mutation.code
    if action == "unframe":
        lines[0] = lines[0][:-1]
        return lines
    if action == "drop":
        return [line for line in lines if not line.startswith(f"|{code}|")]
    if action == "insert":
        index = next(i for i, line in enumerate(lines) if line.startswith(f"|{code}|"))
        lines.insert(index + 1, mutation.value)
        return lines
    if action == "duplicate":
        line = next(line for line in lines if line.startswith(f"|{code}|"))
        index = lines.index(line)
        lines.insert(index + 1, line)
        return lines
    if action == "move":
        line = next(line for line in lines if line.startswith(f"|{code}|"))
        lines.remove(line)
        anchor = next(i for i, item in enumerate(lines) if item.startswith(f"|{mutation.anchor}|"))
        lines.insert(anchor + 1, line)
        # Moving a cadastro across blocks changes the block line counts; keep
        # them correct so the variant isolates the "declared after use" defect.
        return _fix_block_counts(lines, options)
    if action == "before":
        line = next(line for line in lines if line.startswith(f"|{code}|"))
        lines.remove(line)
        anchor = next(i for i, item in enumerate(lines) if item.startswith(f"|{mutation.anchor}|"))
        lines.insert(anchor, line)
        return _fix_block_counts(lines, options)
    if action == "set":
        index = next(i for i, line in enumerate(lines) if line.startswith(f"|{code}|"))
        parts = lines[index].split("|")
        parts[_field_index(code, mutation.field, options)] = mutation.value
        lines[index] = "|".join(parts)
        return lines
    raise AssertionError(f"ação desconhecida: {action!r}")


def write_broken(path: str | Path, kind: str, options: SyntheticOptions | None = None) -> Path:
    """Write a synthetic file with a known defect for negative tests."""
    if kind not in BROKEN_SPECS:
        raise ValueError(f"variante desconhecida: {kind!r}")
    opts = options or SyntheticOptions()
    destination = write_synthetic(path, opts)
    lines = destination.read_text(encoding=opts.encoding).splitlines()
    for mutation in BROKEN_SPECS[kind]:
        lines = _apply_mutation(lines, mutation, opts)
    destination.write_bytes((opts.line_ending.join(lines) + opts.line_ending).encode(opts.encoding))
    return destination


def format_example_record(code: str, values: tuple[str, ...]) -> str:
    """Format one example record (helper for docs and interactive tests)."""
    return format_line(code, values)
