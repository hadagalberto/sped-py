from __future__ import annotations

from pathlib import Path

import pytest

from sped.core.encoding import detect_encoding, is_signature_line, iter_lines, split_line


def test_detect_encoding() -> None:
    assert detect_encoding(b"\xef\xbb\xbf|0000|") == "utf-8-sig"
    assert detect_encoding("|0000|João|".encode()) == "utf-8"
    assert detect_encoding("|0000|João|".encode("latin-1")) == "latin-1"


def test_is_signature_line() -> None:
    assert is_signature_line("SBMDSIGABC")
    assert is_signature_line("  sbmdsigabc  ")
    assert is_signature_line("-----BEGIN PKCS7-----")
    assert not is_signature_line("|0000|020|")


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_iter_lines_and_signature(tmp_path: Path, line_ending: str) -> None:
    path = tmp_path / "file.txt"
    path.write_bytes(
        (
            "|0000|020|"
            + line_ending
            + "|0001|0|"
            + line_ending
            + "SBMDSIG"
            + "A" * 20
            + line_ending
            + "lixo"
        ).encode("latin-1")
    )
    assert list(iter_lines(path)) == ["|0000|020|", "|0001|0|"]
    assert list(iter_lines(path, encoding="latin-1")) == ["|0000|020|", "|0001|0|"]


def test_iter_lines_without_final_newline(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_bytes(b"|0000|020|")
    assert list(iter_lines(path)) == ["|0000|020|"]


def test_split_line() -> None:
    assert split_line("|C170|1|PROD|") == ("C170", ("1", "PROD"))
    assert split_line("") is None
    assert split_line("   ") is None
    with pytest.raises(ValueError, match="delimitadores"):
        split_line("C170|1|")
    assert split_line("|C170|1|") == ("C170", ("1",))
    with pytest.raises(ValueError, match="código de registro"):
        split_line("|XX|1|")
