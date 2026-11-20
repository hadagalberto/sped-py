from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from sped.core.reader import read
from sped.core.writer import (
    as_output,
    format_line,
    is_block_closing,
    write,
    write_iter,
)
from sped.factories.synthetic import build_records


def test_format_line_and_helpers() -> None:
    assert format_line("C170", ("1", "PROD")) == "|C170|1|PROD|"
    assert is_block_closing("0990") is True
    assert is_block_closing("C990") is True
    assert is_block_closing("9990") is False
    assert as_output("|X001|1|") == ("X001", ("1",))
    with pytest.raises(ValueError, match="vazia"):
        as_output("")


def test_writer_recomputes_totals(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    lines = write(build_records(), target, line_ending="\n")
    content = target.read_text(encoding="latin-1")
    assert lines == len(content.splitlines())
    assert content.startswith("|0000|")
    assert "|9900|0000|1|" in content
    assert content.splitlines()[-2].startswith("|9990|")
    assert content.splitlines()[-1] == f"|9999|{lines}|"


def test_writer_inserts_missing_block_closing(tmp_path: Path) -> None:
    records = [record for record in build_records() if record[0] != "C990"]
    target = tmp_path / "out.txt"
    write(records, target, line_ending="\n")
    content = target.read_text(encoding="latin-1")
    assert "|C990|" in content


def test_writer_idempotent(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    write(build_records(), first)
    write(first.read_bytes().decode("latin-1").splitlines(), second)
    assert first.read_bytes() == second.read_bytes()


def test_recompute_disabled(tmp_path: Path) -> None:
    target = tmp_path / "raw.txt"
    write([("X001", ("a",))], target, recompute=False, line_ending="\n")
    assert target.read_text(encoding="latin-1") == "|X001|a|\n"


def test_write_to_stream_and_iter() -> None:
    buffer = BytesIO()
    assert write([("X001", ("a",))], buffer, line_ending="\n", recompute=False) == 1
    assert buffer.getvalue() == b"|X001|a|\n"
    assert next(iter(write_iter([("X001", ("a",))], line_ending="\n"))) == "|X001|a|"


def test_writer_accepts_record_objects(efd_file: Path, tmp_path: Path) -> None:
    with read(efd_file) as source:
        target = tmp_path / "copy.txt"
        write(source, target)
    assert target.read_bytes() == efd_file.read_bytes()


def test_writer_utf8(tmp_path: Path) -> None:
    target = tmp_path / "utf8.txt"
    write([("X001", ("João",))], target, encoding="utf-8", line_ending="\n", recompute=False)
    assert target.read_bytes() == "|X001|João|\n".encode()
