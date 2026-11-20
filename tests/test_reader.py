from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from sped.core.reader import SpedParseError, SpedReader, read, validate_field
from sped.core.types import FieldDef
from sped.layouts import load_layout


def test_read_all_records(efd_file: Path) -> None:
    with read(efd_file) as reader:
        records = list(reader)
    assert records[0].code == "0000"
    assert records[-1].code == "9999"
    assert {record.code for record in records} >= {"0000", "C100", "C170", "C190", "E110", "9999"}
    assert all(not record.errors for record in records)


def test_typed_values(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        c170 = next(record for record in reader if record.code == "C170")
    assert c170.get("COD_ITEM") == "PRODUTO001"
    assert c170.get("QTD") == Decimal("0.00001")
    assert c170.raw_get("COD_ITEM") == "PRODUTO001"


def test_by_type(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        assert [record.code for record in reader.by_type("C100")] == ["C100"]


def test_strict_mode_errors(broken_file_factory: Callable[[str], Path]) -> None:
    for kind in (
        "bad_field_size",
        "invalid_date",
        "unknown_register",
        "broken_framing",
    ):
        with SpedReader(broken_file_factory(kind)) as reader, pytest.raises(SpedParseError):
            list(reader)


def test_non_strict_mode_collects_errors(broken_file_factory: Callable[[str], Path]) -> None:
    issues: list[tuple[int, str, str]] = []
    path = broken_file_factory("invalid_date")
    reader = SpedReader(
        path, strict=False, on_issue=lambda line, code, msg: issues.append((line, code, msg))
    )
    list(reader)
    assert issues and "data" in issues[0][2]


def test_field_count_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "short.txt"
    path.write_bytes(b"|0000|020|\n|9999|3|\n")
    reader = SpedReader(path, layout=load_layout("020"), strict=False)
    issues: list[str] = []
    reader.on_issue = lambda line, code, msg: issues.append(msg)
    list(reader)
    assert any("esperados" in message for message in issues)


def test_validate_field_rules() -> None:
    assert validate_field(FieldDef(1, "REG", "C", 4, True, 0), "0000") is None
    assert "obrigatório" in str(
        validate_field(FieldDef(1, "REG", "C", 4, True, 0, required=True), "")
    )
    assert "tamanho" in str(validate_field(FieldDef(1, "REG", "C", 4, True, 0), "00000"))
    assert "tamanho" in str(validate_field(FieldDef(1, "REG", "C", 4, False, 0), "00000"))
    assert "numérico" in str(validate_field(FieldDef(1, "VL", "N", 5, False, 2), "abc"))
    assert validate_field(FieldDef(1, "VL", "N", 6, False, 2), "123,45") is None
    assert "domínio" in str(
        validate_field(FieldDef(1, "UF", "C", 2, True, 0, valid_values=("SP", "RJ")), "MG")
    )


def test_explicit_layout_bypasses_detection(efd_file: Path) -> None:
    path = efd_file.parent / "explicit.txt"
    path.write_bytes(efd_file.read_bytes())
    reader = SpedReader(path, layout=load_layout("020"))
    assert next(iter(reader)).code == "0000"


def test_context_manager_exit(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        assert reader.layout.cod_ver == "020"
