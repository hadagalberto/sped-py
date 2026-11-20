from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sped.cli import build_parser, main


def test_parser_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "sped-py" in capsys.readouterr().out


def test_info(efd_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", str(efd_file)]) == 0
    output = capsys.readouterr().out
    assert "COD_VER" in output
    assert "Portal" not in output or "Fonte" in output
    assert main(["info", str(efd_file), "--json"]) == 0
    assert '"cod_ver": "020"' in capsys.readouterr().out


def test_validate_ok_and_json(efd_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(efd_file)]) == 0
    assert "OK" in capsys.readouterr().out
    assert main(["validate", str(efd_file), "--json"]) == 0
    assert capsys.readouterr().out.strip() == "[]"


def test_validate_error_exit(
    broken_file_factory: Callable[[str], Path], capsys: pytest.CaptureFixture[str]
) -> None:
    path = broken_file_factory("wrong_file_total")
    assert main(["validate", str(path)]) == 1
    assert "SPED-9999" in capsys.readouterr().out
    assert main(["validate", str(path), "--json"]) == 1
    assert '"rule"' in capsys.readouterr().out


def test_export_csv(efd_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "csv"
    assert main(["export", str(efd_file), "--to", "csv", str(output)]) == 0
    assert (output / "C170.csv").exists()
    assert (output / "0000.csv").read_text(encoding="utf-8").startswith("REG,COD_VER")


def test_export_pandas_missing(
    efd_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # pandas é extra opcional; o comando deve falhar com mensagem clara se ausente.
    code = main(["export", str(efd_file), "--to", "pandas", str(tmp_path)])
    if code == 2:
        assert "pandas" in capsys.readouterr().err
    else:
        assert code == 0


def test_export_unknown_format(
    efd_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["export", str(efd_file), "--to", "xml", str(tmp_path)])


def test_diff(efd_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["diff", str(efd_file), str(efd_file)]) == 0
    assert "Alterados:    0" in capsys.readouterr().out
    other = tmp_path / "other.txt"
    other.write_bytes(efd_file.read_bytes().replace(b"CLIENTE001", b"CLIENTE002"))
    assert main(["diff", str(efd_file), str(other)]) == 1
    assert "Alterados:" in capsys.readouterr().out


def test_fix_totals(
    broken_file_factory: Callable[[str], Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = broken_file_factory("wrong_file_total")
    target = tmp_path / "fixed.txt"
    assert main(["fix-totals", str(broken), "-o", str(target)]) == 0
    assert "corrigido" in capsys.readouterr().out
    assert main(["validate", str(target)]) == 0
    capsys.readouterr()
