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
        "C001",
        "C100",
        "C170",
        "C190",
        "C990",
        "E001",
        "E110",
        "E990",
        "9001",
    ),
    "efd_contribuicoes": (
        "0000",
        "0001",
        "0110",
        "0150",
        "0200",
        "C001",
        "C100",
        "C170",
        "M001",
        "M210",
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
        if definition.name in overrides:
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


def write_broken(path: str | Path, kind: str, options: SyntheticOptions | None = None) -> Path:
    """Write a synthetic file with a known defect for negative tests."""
    if kind not in BROKEN_KINDS:
        raise ValueError(f"variante desconhecida: {kind!r}")
    opts = options or SyntheticOptions()
    destination = write_synthetic(path, opts)
    lines = destination.read_text(encoding=opts.encoding).splitlines()

    def replace_code(code: str, field_index: int, value: str) -> None:
        for index, line in enumerate(lines):
            if line.startswith(f"|{code}|"):
                parts = line.split("|")
                parts[field_index] = value
                lines[index] = "|".join(parts)
                return
        raise AssertionError(f"registro {code} não encontrado")

    if kind == "bad_field_size":
        replace_code("0000", 7, "X" * 30)
    elif kind == "invalid_date":
        replace_code("0000", 4, "31132024")
    elif kind == "unknown_register":
        lines.insert(8, "|XXXX|valor|")
    elif kind == "missing_block_closing":
        lines = [line for line in lines if not line.startswith("|C990|")]
    elif kind == "wrong_file_total":
        replace_code("9999", 2, "999")
    elif kind == "broken_framing":
        lines[0] = lines[0][:-1]

    destination.write_bytes((opts.line_ending.join(lines) + opts.line_ending).encode(opts.encoding))
    return destination


def format_example_record(code: str, values: tuple[str, ...]) -> str:
    """Format one example record (helper for docs and interactive tests)."""
    return format_line(code, values)
