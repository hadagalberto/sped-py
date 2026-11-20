"""Byte-identical round trips and real invalid vectors for every obrigação."""

from __future__ import annotations

from pathlib import Path

import pytest

from sped.core.encoding import detect_encoding
from sped.core.reader import SpedParseError, SpedReader, read
from sped.core.validation import validate
from sped.core.writer import write
from sped.factories.synthetic import SyntheticOptions, build_records, write_synthetic
from sped.layouts import OBRIGACOES, available_versions, detect_layout, load_layout

PAIRS: tuple[tuple[str, str], ...] = tuple(
    (obrigacao, cod_ver) for obrigacao in OBRIGACOES for cod_ver in available_versions(obrigacao)
)


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_write_read_roundtrip_is_byte_identical(
    tmp_path: Path, obrigacao: str, cod_ver: str
) -> None:
    options = SyntheticOptions(cod_ver=cod_ver, obrigacao=obrigacao)
    original = write_synthetic(tmp_path / "original.txt", options)
    layout = detect_layout(original)
    with read(original) as source:
        records = list(source)
        assert records
        assert all(not record.errors for record in records)
    copy = tmp_path / "copy.txt"
    with read(original) as source:
        write(source, copy, layout=layout)
    assert original.read_bytes() == copy.read_bytes()


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_totals_recomputation_idempotent(tmp_path: Path, obrigacao: str, cod_ver: str) -> None:
    options = SyntheticOptions(cod_ver=cod_ver, obrigacao=obrigacao)
    layout = load_layout(cod_ver, obrigacao)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    write(build_records(options), first, layout=layout)
    encoding = detect_encoding(first.read_bytes()[:8192])
    write(first.read_bytes().decode(encoding).splitlines(), second, layout=layout)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_valid_fixture_passes_validation(tmp_path: Path, obrigacao: str, cod_ver: str) -> None:
    path = write_synthetic(
        tmp_path / "valid.txt", SyntheticOptions(cod_ver=cod_ver, obrigacao=obrigacao)
    )
    assert validate(path) == []


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_known_invalid_total(tmp_path: Path, obrigacao: str, cod_ver: str) -> None:
    path = write_synthetic(
        tmp_path / "bad_total.txt", SyntheticOptions(cod_ver=cod_ver, obrigacao=obrigacao)
    )
    lines = path.read_text(encoding="latin-1").splitlines()
    lines[-1] = "|9999|999|"
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    assert any(issue.rule == "SPED-9999" for issue in validate(path))


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_known_invalid_unknown_register(tmp_path: Path, obrigacao: str, cod_ver: str) -> None:
    path = write_synthetic(
        tmp_path / "unknown.txt", SyntheticOptions(cod_ver=cod_ver, obrigacao=obrigacao)
    )
    lines = path.read_text(encoding="latin-1").splitlines()
    lines.insert(2, "|XXXX|valor|")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    with SpedReader(path) as reader, pytest.raises(SpedParseError, match="XXXX"):
        list(reader)


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_known_invalid_framing(tmp_path: Path, obrigacao: str, cod_ver: str) -> None:
    path = write_synthetic(
        tmp_path / "framing.txt", SyntheticOptions(cod_ver=cod_ver, obrigacao=obrigacao)
    )
    lines = path.read_text(encoding="latin-1").splitlines()
    lines[0] = lines[0][:-1]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    with SpedReader(path) as reader, pytest.raises(SpedParseError):
        list(reader)
