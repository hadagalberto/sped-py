"""Regression tests for the independent review findings (milestone 6).

Every expected value below is derived by hand from the official SPED rules,
the SPEC, or simple arithmetic on the test vector itself — never from the
library under test.
"""

from __future__ import annotations

import tracemalloc
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sped.cli import main
from sped.core.types import FieldDef
from sped.core.writer import OutputRecord, format_line, write, write_iter
from sped.factories.synthetic import SyntheticOptions, build_records, write_synthetic
from sped.layouts import load_layout
from sped.validation import validate

if TYPE_CHECKING:
    from collections.abc import Iterator

RULE_X990 = "SPED-STRUCT-X990-001"
RULE_9990 = "SPED-9990"
RULE_9900 = "SPED-9900"
RULE_CNPJ = "SPED-TAB-CNPJ-001"
RULE_CFOP_OPER = "SPED-TAB-CFOP-002"
RULE_HIER = "SPED-STRUCT-HIER-001"


def _set_field(path: Path, code: str, field: str, value: str) -> None:
    """Replace ``field`` on the first ``|code|`` line using the official layout."""
    layout = load_layout("020")
    names = [definition.name for definition in layout.register(code).fields]
    if names and names[0] == "REG":
        names = names[1:]
    lines = path.read_text("latin-1").splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"|{code}|"):
            parts = line.split("|")
            parts[2 + names.index(field)] = value
            lines[index] = "|".join(parts)
            break
    else:
        raise AssertionError(f"linha {code} não encontrada")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))


# --- C1: the 9900 register must totalise *every* register type --------------


def test_writer_9900_includes_9900_9990_9999_and_correct_9990(tmp_path: Path) -> None:
    """Guia Prático EFD ICMS/IPI v3.2.4, Bloco 9 (págs. 325-326).

    ``9900``: "Todos os registros referenciados neste arquivo, inclusive os
    posteriores a este registro, devem ter uma linha totalizadora". ``9990``:
    a contagem inclui abertura/encerramento do bloco **e** o registro 9999.

    Hand-derived vector: two data lines (0000, 0001) -> 0990 says 3; 9001 is
    generated -> distinct codes = {0000, 0001, 0990, 9001, 9900, 9990, 9999}
    = 7, so there are 7 lines 9900; bloco 9 = 1 + 7 + 1 + 1 = 10; file = 13.
    """
    target = tmp_path / "out.txt"
    write([("0000", ("020",)), ("0001", ("0",))], target, line_ending="\n")
    lines = target.read_text("latin-1").splitlines()

    assert lines[:3] == ["|0000|020|", "|0001|0|", "|0990|3|"]
    assert lines[3] == "|9001|"
    assert lines[4:11] == [
        "|9900|0000|1|",
        "|9900|0001|1|",
        "|9900|0990|1|",
        "|9900|9001|1|",
        "|9900|9900|7|",
        "|9900|9990|1|",
        "|9900|9999|1|",
    ]
    assert lines[11] == "|9990|10|"
    assert lines[12] == "|9999|13|"
    assert len(lines) == 13


def test_fix_totals_cli_writes_complete_block_9(efd_file: Path, tmp_path: Path) -> None:
    """``sped fix-totals`` goes through the same writer and must fix bloco 9."""
    target = tmp_path / "fixed.txt"
    assert main(["fix-totals", str(efd_file), "-o", str(target)]) == 0
    content = target.read_text("latin-1")
    assert "|9900|9900|" in content
    assert "|9900|9999|1|" in content
    assert validate(target) == []


def test_9900_count_for_9900_is_the_number_of_9900_lines() -> None:
    """QTD_REG_BLC of REG_BLC=9900 equals the count of emitted 9900 lines."""
    lines = list(write_iter([("0000", ("020",)), ("0001", ("0",))], line_ending="\n"))
    totals = [line for line in lines if line.startswith("|9900|")]
    declared = next(int(line.split("|")[3]) for line in totals if line.split("|")[2] == "9900")
    assert declared == len(totals) == 7


# --- C2: SPED has no implied decimal places --------------------------------


def test_integer_body_has_no_implied_decimals() -> None:
    """Guia Prático, campo 2.7.1: N(15,2) with body ``10000`` means 10000,00.

    The old ``scaleb(-dec)`` silently turned it into 100,00.
    """
    money = FieldDef(1, "VL_ITEM", "N", 15, False, 2)
    assert money.coerce("10000") == Decimal("10000.00")
    assert money.coerce("-10000") == Decimal("-10000.00")
    assert money.coerce("123,45") == Decimal("123.45")


def test_no_false_c190_error_for_integer_and_comma_spellings(tmp_path: Path) -> None:
    """``10000`` and ``10000,00`` are the same value in a SPED numeric field."""
    path = write_synthetic(tmp_path / "efd.txt")
    _set_field(path, "C190", "VL_BC_ICMS", "10000,00")
    issues = [issue for issue in validate(path) if issue.rule == "SPED-TOT-ICMS-C190-001"]
    assert issues == []


# --- H1: declared x990 / 9900 / 9990 counts are actually checked ----------


def test_wrong_x990_and_9990_counts_are_reported(tmp_path: Path) -> None:
    """Guia Prático: x990.QTD_LIN_n and 9990.QTD_LIN_9 are validated fields."""
    path = write_synthetic(tmp_path / "efd.txt")
    original = path.read_text("latin-1").splitlines()
    block0_lines = sum(1 for line in original if line[1] == "0")  # hand count
    block9_lines = sum(1 for line in original if line[1] == "9")  # inclui 9999
    _set_field(path, "0990", "QTD_LIN_0", "999")
    _set_field(path, "9990", "QTD_LIN_9", "888")

    issues = validate(path)
    assert any(
        issue.rule == RULE_X990 and issue.code == "0990" and str(block0_lines) in issue.message
        for issue in issues
    )
    assert any(
        issue.rule == RULE_9990 and "888" in issue.message and str(block9_lines) in issue.message
        for issue in issues
    )


def test_missing_9900_line_for_a_present_register_is_reported(tmp_path: Path) -> None:
    """Guia Prático: every register in the file needs its own 9900 line."""
    path = write_synthetic(tmp_path / "efd.txt")
    lines = path.read_text("latin-1").splitlines()
    lines = [line for line in lines if not line.startswith("|9900|C170|")]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    issues = validate(path)
    assert any(issue.rule == RULE_9900 and "C170" in issue.message for issue in issues)


# --- H2: CNPJ / CPF check digits -------------------------------------------


def test_cnpj_cpf_check_digits_hand_table() -> None:
    """Receita Federal, algoritmo de verificação de CNPJ/CPF (módulo 11).

    Hand-computed examples:
    * CNPJ 12345678/0001-95: dv1 = 5, dv2 = 5 (valid).
    * CNPJ 11444777/0001-61: dv1 = 6, dv2 = 1 (valid).
    * CPF 123.456.789-09: dv1 = 0, dv2 = 9 (valid).
    * CPF 529.982.247-25: dv1 = 2, dv2 = 5 (valid).
    Repeated-digit documents are rejected by the official algorithm.
    """
    from sped.validation.tables import valid_cnpj, valid_cpf  # noqa: PLC0415

    for value in ("12345678000195", "11444777000161", "11222333000181"):
        assert valid_cnpj(value), value
    for value in ("12345678000196", "11444777000162", "11111111111111", "123"):
        assert not valid_cnpj(value), value
    for value in ("12345678909", "52998224725"):
        assert valid_cpf(value), value
    for value in ("12345678910", "52998224726", "11111111111", "123"):
        assert not valid_cpf(value), value


def test_invalid_cnpj_in_0000_is_reported(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "efd.txt")
    _set_field(path, "0000", "CNPJ", "12345678000196")  # DV errado
    assert any(issue.rule == RULE_CNPJ for issue in validate(path))


# --- H3: CFOP direction vs IND_OPER ----------------------------------------


def test_cfop_entrada_with_saida_operation_is_reported(tmp_path: Path) -> None:
    """CFOP 1101 begins with 1 (entrada); IND_OPER=1 means saída."""
    path = write_synthetic(tmp_path / "efd.txt")
    _set_field(path, "C100", "IND_OPER", "1")
    assert any(issue.rule == RULE_CFOP_OPER for issue in validate(path))
    assert validate(write_synthetic(tmp_path / "ok.txt")) == []


# --- H4: parent/child hierarchy is enforced --------------------------------


def test_c170_without_c100_parent_is_reported(tmp_path: Path) -> None:
    """Nível hierárquico: C170 (3) requires a C100 (2) ancestor."""
    path = write_synthetic(tmp_path / "efd.txt")
    lines = path.read_text("latin-1").splitlines()
    c170 = next(line for line in lines if line.startswith("|C170|"))
    lines.remove(c170)
    insert_at = next(i for i, line in enumerate(lines) if line.startswith("|C100|"))
    lines.insert(insert_at, c170)
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    issues = validate(path)
    assert any(issue.rule == RULE_HIER and issue.code == "C170" for issue in issues)
    assert validate(write_synthetic(tmp_path / "ok.txt")) == []


# --- H5: validation streams with bounded memory ----------------------------


def test_validation_memory_is_flat_on_a_100k_line_file(tmp_path: Path) -> None:
    """100000 detail records must not be materialised by the validator."""

    def expanded() -> Iterator[OutputRecord]:
        yield from build_records()
        template = next(record for record in build_records() if record[0] == "C170")
        for _ in range(100_000):
            yield template

    path = tmp_path / "big.txt"
    write(expanded(), path)

    tracemalloc.start()
    try:
        validate(path)
        _peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    # Constant memory: a bounded counter/aggregate state, never 100k Records.
    assert _peak < 32 * 1024 * 1024, f"pico {_peak / 1024 / 1024:.1f} MB"


# --- M1: the decimal separator is a comma, never a dot --------------------


def test_dot_decimal_separator_is_rejected() -> None:
    """Guia Prático: o separador decimal oficial do SPED é a vírgula."""
    from sped.core.reader import validate_field  # noqa: PLC0415

    money = FieldDef(1, "VL_ITEM", "N", 15, False, 2)
    assert money.coerce("123.45") == "123.45"  # left raw -> field error
    assert money.coerce("123,45") == Decimal("123.45")
    assert "inválido" in (validate_field(money, "123.45") or "")
    assert validate_field(money, "123,45") is None


# --- M2: a pipe cannot appear inside a value -------------------------------


def test_writer_rejects_pipe_inside_value() -> None:
    """``|`` is the field delimiter and can never be part of a value."""
    with pytest.raises(ValueError, match=r"\|"):
        format_line("C170", ("AB|CD",))
    with pytest.raises(ValueError, match=r"\|"):
        write([("C170", ("AB|CD",))], "unused.txt")


# --- M3: 9900 lines follow first appearance, not alphabetical order --------


def test_9900_follows_first_appearance_order() -> None:
    """9900 lists each register type in the order it first appears."""
    lines = list(
        write_iter(
            [
                ("C100", ("x",)),
                ("0000", ("020",)),
                ("C100", ("y",)),
                ("0150", ("z",)),
            ],
            line_ending="\n",
        )
    )
    listed = [line.split("|")[2] for line in lines if line.startswith("|9900|")]
    # First appearance in the emitted file: C100, then the C990 closing that
    # the writer inserts before block 0 starts, then 0000, its 0990, 0150...
    assert listed == [
        "C100",
        "C990",
        "0000",
        "0990",
        "0150",
        "9001",
        "9900",
        "9990",
        "9999",
    ]


# --- optional-registration sanity: the fixture must stay valid -------------


def test_factory_cnpj_cpf_fixtures_are_officially_valid() -> None:
    """The synthetic fixture uses documents that pass the official check."""
    from sped.validation.tables import valid_cnpj, valid_cpf  # noqa: PLC0415

    options = SyntheticOptions()
    assert valid_cnpj(options.cnpj)
    assert valid_cpf("12345678909")
