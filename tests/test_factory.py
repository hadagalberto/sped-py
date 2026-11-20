from __future__ import annotations

from pathlib import Path

import pytest

from sped.core.encoding import iter_lines
from sped.factories.synthetic import (
    BROKEN_KINDS,
    SyntheticOptions,
    build_records,
    format_example_record,
    write_broken,
    write_synthetic,
)


def test_build_records_shape() -> None:
    records = build_records()
    assert records[0][0] == "0000"
    assert records[0][1][0] == "020"
    assert any(code == "C170" for code, _ in records)


@pytest.mark.parametrize("kind", BROKEN_KINDS)
def test_broken_variants(kind: str, tmp_path: Path) -> None:
    path = write_broken(tmp_path / "broken.txt", kind)
    assert path.exists()


def test_unknown_broken_variant(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="desconhecida"):
        write_broken(tmp_path / "x.txt", "inexistente")


def test_signature_stripped(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "signed.txt", SyntheticOptions(with_signature=True))
    assert all(not line.startswith("SBMDSIG") for line in iter_lines(path))


def test_custom_line_endings(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "lf.txt", SyntheticOptions(line_ending="\n"))
    assert b"\r\n" not in path.read_bytes()


def test_format_example() -> None:
    assert format_example_record("X001", ("1",)) == "|X001|1|"
