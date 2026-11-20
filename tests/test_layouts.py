from __future__ import annotations

from pathlib import Path

import pytest

from sped.layouts import available_versions, detect_cod_ver, load_layout, version_info


def test_all_versions_available() -> None:
    assert available_versions() == tuple(f"{n:03d}" for n in range(13, 22))


@pytest.mark.parametrize("cod_ver", available_versions())
def test_layout_metadata_and_structural_registers(cod_ver: str) -> None:
    layout = load_layout(cod_ver)
    assert layout.cod_ver == cod_ver
    assert layout.source_url.startswith("http")
    assert layout.source_date
    assert layout.valid_from < layout.valid_to
    for required in ("0000", "0001", "0990", "9001", "9900", "9990", "9999"):
        assert required in layout.registers
    assert layout.register("0000").field("COD_VER").name == "COD_VER"


def test_versions_are_official_and_distinct() -> None:
    versions = [version_info(cod) for cod in available_versions()]
    assert len({entry["source_url"] for entry in versions}) >= 8
    assert versions[0]["valid_from"] == "2019-01-01"
    assert versions[-1]["valid_from"] == "2027-01-01"


def test_load_layout_normalizes_cod_ver() -> None:
    assert load_layout("20").versao == load_layout("020").versao


def test_unknown_version() -> None:
    with pytest.raises(KeyError):
        load_layout("999")


def test_detect_cod_ver(efd_file: Path) -> None:
    assert detect_cod_ver(efd_file) == "020"


def test_detect_cod_ver_invalid(tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    path.write_bytes(b"nao e sped\n")
    with pytest.raises(ValueError, match="COD_VER"):
        detect_cod_ver(path)
