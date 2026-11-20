from __future__ import annotations

from pathlib import Path

import pytest

from sped.cli import main
from sped.core.writer import write
from sped.factories.synthetic import SyntheticOptions, write_synthetic
from sped.layouts import OBRIGACOES, available_versions, load_layout

PAIRS: tuple[tuple[str, str], ...] = tuple(
    (obrigacao, cod_ver) for obrigacao in OBRIGACOES for cod_ver in available_versions(obrigacao)
)


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_cli_info_and_validate_for_every_version(
    tmp_path: Path,
    obrigacao: str,
    cod_ver: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = write_synthetic(tmp_path / "file.txt", SyntheticOptions(cod_ver, obrigacao))
    assert main(["info", str(path), "--json"]) == 0
    output = capsys.readouterr().out
    assert f'"obrigacao": "{obrigacao}"' in output
    assert f'"cod_ver": "{cod_ver}"' in output
    assert main(["validate", str(path), "--json"]) == 0
    assert capsys.readouterr().out.strip() == "[]"


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_cli_export_csv_for_every_version(tmp_path: Path, obrigacao: str, cod_ver: str) -> None:
    path = write_synthetic(tmp_path / "file.txt", SyntheticOptions(cod_ver, obrigacao))
    output = tmp_path / "csv"
    assert main(["export", str(path), "--to", "csv", str(output)]) == 0
    assert (output / "0000.csv").exists()
    assert (output / "9900.csv").exists()


def test_cli_fix_totals_uses_detected_layout(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "ecf.txt", SyntheticOptions("012", "ecf"))
    lines = path.read_text(encoding="latin-1").splitlines()
    lines[-1] = "|9999|999|"
    broken = tmp_path / "broken.txt"
    broken.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    target = tmp_path / "fixed.txt"
    assert main(["fix-totals", str(broken), "-o", str(target)]) == 0
    assert main(["validate", str(target)]) == 0


def test_writer_does_not_invent_missing_block_closing(tmp_path: Path) -> None:
    layout = load_layout("012", "ecf")
    assert "S990" not in layout.registers
    output = write([("S001", ("0",)), ("S030", ("1",))], tmp_path / "s.txt", layout=layout)
    content = (tmp_path / "s.txt").read_text(encoding="latin-1")
    assert output > 0
    assert "|S990|" not in content
