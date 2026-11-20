from __future__ import annotations

from pathlib import Path

import pytest

from sped.factories.synthetic import SyntheticOptions, write_synthetic
from sped.layouts import (
    OBRIGACOES,
    available_versions,
    detect_cod_ver,
    detect_layout,
    detect_obrigacao,
    load_layout,
    version_info,
)

EXPECTED: dict[str, tuple[str, ...]] = {
    "efd_icmsipi": tuple(f"{cod:03d}" for cod in range(13, 22)),
    "efd_contribuicoes": ("005", "006"),
    "ecd": ("008", "009"),
    "ecf": tuple(f"{cod:03d}" for cod in range(6, 13)),
}
PAIRS: tuple[tuple[str, str], ...] = tuple(
    (obrigacao, cod_ver) for obrigacao in OBRIGACOES for cod_ver in EXPECTED[obrigacao]
)


def test_all_obrigacoes_and_versions_are_bundled() -> None:
    assert set(OBRIGACOES) == set(EXPECTED)
    for obrigacao in OBRIGACOES:
        assert available_versions(obrigacao) == EXPECTED[obrigacao]


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_layout_has_official_provenance_and_levels(obrigacao: str, cod_ver: str) -> None:
    layout = load_layout(cod_ver, obrigacao)
    assert layout.obrigacao == obrigacao
    assert layout.cod_ver == cod_ver
    assert layout.source_url.startswith("http")
    assert layout.source_date
    assert layout.valid_from < "2099-01-01"
    for required in ("0000", "0001", "0990", "9001", "9900", "9990", "9999"):
        assert required in layout.registers
    assert layout.register("0000").field("REG").name == "REG"
    assert layout.register("0000").field("DT_INI").is_date
    if obrigacao != "efd_icmsipi":
        assert layout.gap_filled_fields == 0
        assert layout.register("0000").level == 0
    versions = [version_info(cod, obrigacao) for cod in available_versions(obrigacao)]
    assert len({item["source_url"] for item in versions}) == len(versions)


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_detect_layout_from_generated_file(tmp_path: Path, obrigacao: str, cod_ver: str) -> None:
    path = write_synthetic(tmp_path / "file.txt", SyntheticOptions(cod_ver, obrigacao))
    assert detect_obrigacao(path) == obrigacao
    assert detect_cod_ver(path) == cod_ver
    assert detect_cod_ver(path, obrigacao) == cod_ver
    layout = detect_layout(path)
    assert (layout.obrigacao, layout.cod_ver) == (obrigacao, cod_ver)


def test_ecd_version_comes_from_i010(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "ecd.txt", SyntheticOptions("009", "ecd"))
    assert detect_cod_ver(path) == "009"
    data = path.read_bytes()
    data = data.replace(b"|I010|G|9.00|", b"|I010|G|8.00|")
    path.write_bytes(data)
    assert detect_cod_ver(path) == "008"  # COD_VER_LC explícito vence o ano


def test_ecd_version_fallback_from_year(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "ecd.txt", SyntheticOptions("008", "ecd"))
    lines = [line for line in path.read_text().splitlines() if not line.startswith("|I010|")]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    assert detect_cod_ver(path) == "008"


def test_ecf_four_digit_cod_ver(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "ecf.txt", SyntheticOptions("012", "ecf"))
    assert b"|0000|LECF|0012|" in path.read_bytes()
    assert detect_cod_ver(path) == "012"


def test_detect_rejects_wrong_obrigacao(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "efd.txt")
    with pytest.raises(ValueError, match="obrigação"):
        detect_cod_ver(path, "ecf")


def test_load_layout_accepts_four_digits() -> None:
    assert load_layout("0012", "ecf").cod_ver == "012"


def test_unknown_obrigacao_version() -> None:
    with pytest.raises(KeyError):
        load_layout("001", "ecf")
