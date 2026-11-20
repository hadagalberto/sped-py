"""Fábrica de arquivos EFD ICMS/IPI sintéticos, porém realistas.

Nenhum dado de contribuinte real é usado: CNPJ, inscrição estadual, nomes e
valores são fixtures determinísticos.  Os arquivos respeitam o leiaute oficial
carregado pelo ``COD_VER`` e passam nas validações do leitor.
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


@dataclass(frozen=True, slots=True)
class SyntheticOptions:
    """Parâmetros determinísticos da fábrica."""

    cod_ver: str = "020"
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
        elif definition.name.startswith("DT_"):
            result.append("01012024")
        elif definition.name in {"CNPJ", "CNPJ_CPF_EMIT"}:
            result.append("12345678000195")
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


def build_records(options: SyntheticOptions | None = None) -> list[OutputRecord]:
    """Return a realistic, complete record sequence for the given version."""
    opts = options or SyntheticOptions()
    layout = load_layout(opts.cod_ver)
    records: list[OutputRecord] = [
        (
            "0000",
            _values(
                layout,
                "0000",
                {
                    "COD_VER": opts.cod_ver,
                    "COD_FIN": "0",
                    "DT_INI": opts.dt_ini,
                    "DT_FIN": opts.dt_fin,
                    "CNPJ": opts.cnpj,
                    "UF": opts.uf,
                    "IE": opts.ie,
                },
            ),
        ),
        ("0001", _values(layout, "0001", {"IND_MOV": "0"})),
        ("0005", _values(layout, "0005", {})),
        ("0100", _values(layout, "0100", {"CPF": "12345678909"})),
        ("0150", _values(layout, "0150", {"COD_PART": opts.participant, "COD_PAIS": "1058"})),
        ("0190", _values(layout, "0190", {"UNID": "UN", "DESCR": "Unidade"})),
        ("0200", _values(layout, "0200", {"COD_ITEM": opts.item, "UNID_INV": "UN"})),
        ("0990", _values(layout, "0990", {})),
        (
            "C001",
            _values(
                layout,
                "C001",
                {"IND_MOV": "0"} if "IND_MOV" in layout.register("C001").field_names else {},
            ),
        ),
        (
            "C100",
            _values(
                layout,
                "C100",
                {
                    "IND_OPER": "0",
                    "IND_EMIT": "1",
                    "COD_PART": opts.participant,
                    "COD_MOD": "55",
                    "COD_SIT": "00",
                    "SER": "1",
                    "NUM_DOC": "1",
                    "CHV_NFE": "0" * 44,
                    "DT_DOC": opts.dt_ini,
                    "DT_E_S": opts.dt_ini,
                },
            ),
        ),
        (
            "C170",
            _values(
                layout,
                "C170",
                {
                    "NUM_ITEM": "1",
                    "COD_ITEM": opts.item,
                    "QTD": "1",
                    "UNID": "UN",
                    "CST_ICMS": "000",
                    "CFOP": "1101",
                },
            ),
        ),
        (
            "C190",
            _values(
                layout,
                "C190",
                {
                    "CST_ICMS": "000",
                    "CFOP": "1101",
                    "ALIQ_ICMS": "0",
                    "VL_OPR": "10000",
                    "VL_BC_ICMS": "10000",
                    "VL_ICMS": "0",
                },
            ),
        ),
        ("C990", _values(layout, "C990", {})),
        ("E001", _values(layout, "E001", {"IND_MOV": "0"})),
        ("E110", _values(layout, "E110", {})),
        ("E990", _values(layout, "E990", {})),
        ("9001", _values(layout, "9001", {"IND_MOV": "0"})),
    ]
    return records


def write_synthetic(path: str | Path, options: SyntheticOptions | None = None) -> Path:
    """Write a valid synthetic EFD file and return its path."""
    opts = options or SyntheticOptions()
    destination = Path(path)
    buffer = io.BytesIO()
    write(
        build_records(opts),
        buffer,
        encoding=opts.encoding,
        line_ending=opts.line_ending,
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
