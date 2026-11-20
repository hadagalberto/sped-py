from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sped.cli import build_parser, main
from sped.factories.synthetic import SyntheticOptions, write_synthetic


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


def test_info_json_is_pure(efd_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", str(efd_file), "--json"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("{")
    assert '"obrigacao": "efd_icmsipi"' in output
    assert "Arquivo:" not in output


def test_fix_totals_json(
    broken_file_factory: Callable[[str], Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = broken_file_factory("wrong_file_total")
    target = tmp_path / "fixed.json.txt"
    assert main(["fix-totals", str(broken), "-o", str(target), "--json"]) == 0
    assert '"linhas"' in capsys.readouterr().out


def test_export_requires_destination(efd_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["export", str(efd_file), "--to", "csv"]) == 2
    assert "saída" in capsys.readouterr().err


def test_export_parquet_excel_and_polars(
    efd_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["export", str(efd_file), "--to", "parquet", str(tmp_path / "pq"), "--json"]) == 0
    assert (tmp_path / "pq" / "C170.parquet").exists()
    assert '"formato": "parquet"' in capsys.readouterr().out
    assert main(["export", str(efd_file), "--to", "excel", str(tmp_path / "x.xlsx")]) == 0
    assert (tmp_path / "x.xlsx").exists()
    assert main(["export", str(efd_file), "--to", "polars", "--json"]) == 0
    assert '"registros"' in capsys.readouterr().out
    assert main(["export", str(efd_file), "--to", "pandas"]) == 0
    assert "C170" in capsys.readouterr().out


def test_diff_json(efd_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    other = tmp_path / "other.txt"
    other.write_bytes(efd_file.read_bytes().replace(b"CLIENTE001", b"CLIENTE002"))
    assert main(["diff", str(efd_file), str(other), "--json"]) == 1
    payload = capsys.readouterr().out
    assert '"alterados": 2' in payload
    assert '"tipo": "changed"' in payload


def test_summarize_cli(efd_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["summarize", str(efd_file), "--dimension", "CFOP"]) == 0
    assert "1101" in capsys.readouterr().out
    assert main(["summarize", str(efd_file), "--json"]) == 0
    assert '"dimensao": "CFOP"' in capsys.readouterr().out


def test_apuracao_cli(
    broken_file_factory: Callable[[str], Path],
    efd_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["apuracao", str(efd_file)]) == 0
    assert "OK" in capsys.readouterr().out
    broken = broken_file_factory("bad_e110_apuracao")
    assert main(["apuracao", str(broken), "--json"]) == 1
    assert '"divergencias": 2' in capsys.readouterr().out
    assert main(["apuracao", str(broken)]) == 1
    assert "VL_TOT_CREDITOS" in capsys.readouterr().out


def test_recompute_apuracao_cli(
    broken_file_factory: Callable[[str], Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = broken_file_factory("bad_e110_apuracao")
    target = tmp_path / "recuperado.txt"
    assert main(["recompute-apuracao", str(broken), "-o", str(target), "--json"]) == 0
    assert '"arquivo"' in capsys.readouterr().out
    assert main(["validate", str(target)]) == 0
    capsys.readouterr()


def test_merge_and_split_cli(
    efd_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = write_synthetic(
        tmp_path / "feb.txt",
        SyntheticOptions(dt_ini="01022024", dt_fin="29022024", participant="CLIENTE002"),
    )
    merged = tmp_path / "merged.txt"
    assert main(["merge", str(efd_file), str(other), "-o", str(merged), "--json"]) == 0
    assert '"entradas"' in capsys.readouterr().out
    assert main(["validate", str(merged)]) == 0
    capsys.readouterr()
    parts_dir = tmp_path / "parts"
    assert main(["split", str(efd_file), "-o", str(parts_dir), "--by", "quarter", "--json"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) >= 1
    assert len(list(parts_dir.glob("*.txt"))) == 4


def test_cli_error_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", "arquivo-inexistente.txt"]) == 3
    assert "erro" in capsys.readouterr().err
