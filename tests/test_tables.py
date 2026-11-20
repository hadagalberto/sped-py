"""Tabelas oficiais agrupadas e script de atualização."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from sped.validation.tables import (
    cfop_codes,
    cfop_title_codes,
    csosn_codes,
    cst_origem,
    cst_tributacao,
    metadata,
    ncm_codes,
    table_sources,
    valid_cfop,
    valid_cst_icms,
)

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "src" / "sped" / "tables"


@pytest.fixture(scope="module")
def updater() -> ModuleType:
    path = ROOT / "scripts" / "update_tables.py"
    spec = importlib.util.spec_from_file_location("sped_update_tables", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cfop_table_has_official_codes_and_titles() -> None:
    codes = cfop_codes()
    assert len(codes) >= 500
    assert {"1101", "5102", "5949"} <= codes
    assert {"1000", "1100", "5900"} <= cfop_title_codes()
    assert valid_cfop("1101")
    assert not valid_cfop("1100")  # código de grupo
    assert not valid_cfop("9999")
    assert not valid_cfop("")


def test_ncm_table_has_official_codes() -> None:
    codes = ncm_codes()
    assert len(codes) >= 10000
    assert "84713011" in codes
    assert all(len(code) == 8 and code.isdigit() for code in codes)
    assert "99999999" not in codes


def test_cst_and_csosn_tables() -> None:
    assert cst_origem() == frozenset("012345678")
    assert {"00", "02", "53", "61", "90"} <= cst_tributacao()
    assert {"101", "202", "900"} <= csosn_codes()
    for valid in ("000", "102", "510", "090", "161"):
        assert valid_cst_icms(valid), valid
    for invalid in ("999", "00", "", "1", "0A0"):
        assert not valid_cst_icms(invalid), invalid


def test_metadata_has_official_sources() -> None:
    for name in ("cfop", "ncm", "cst"):
        info = metadata(name)
        assert info["source_url"].startswith("https://")
        assert info["retrieved_at"] == "2026-11-20"
    assert set(table_sources()) == {"cfop", "ncm", "cst"}
    assert "confaz" in table_sources()["cfop"]
    assert "siscomex" in table_sources()["ncm"]


def test_update_script_parses_cfop_html(updater: ModuleType) -> None:
    with pytest.raises(ValueError, match="CFOP incompleta"):
        updater.parse_cfop(b"<p>1.101 - curto</p>")
    bundled = json.loads((TABLES / "cfop.json").read_text(encoding="utf-8"))
    lines = [
        f'<p class="A5-1TextoAcordo">{code[:1]}.{code[1:]} - {desc}</p>'
        for code, desc in bundled["codes"].items()
    ]
    table = updater.parse_cfop(("<html>" + "".join(lines) + "</html>").encode("utf-8"))
    assert table.codes["1101"] == bundled["codes"]["1101"]
    assert set(table.title_codes) == set(bundled["title_codes"])


def test_update_script_parses_ncm_json(updater: ModuleType) -> None:
    with pytest.raises(ValueError, match="NCM incompleta"):
        updater.parse_ncm(json.dumps({"Nomenclaturas": []}).encode())
    bundled = json.loads((TABLES / "ncm.json").read_text(encoding="utf-8"))
    payload = {
        "Data_Ultima_Atualizacao_NCM": "20/11/2026",
        "Ato": "Res Gecex nº 926/2026",
        "Nomenclaturas": [
            {"Codigo": f"{code[:4]}.{code[4:6]}.{code[6:]}"} for code in bundled["codes"]
        ],
    }
    codes, date, act = updater.parse_ncm(json.dumps(payload).encode("utf-8"))
    assert codes == bundled["codes"]
    assert date == "20/11/2026"
    assert "926/2026" in act


def test_update_script_builds_documents(updater: ModuleType) -> None:
    cfop = updater.CfopTable({"1101": "Compra"}, ("1100",))
    docs = updater.build_documents(cfop, (["84713011"], "20/11/2026", "Res Gecex 926/2026"))
    assert set(docs) == {"cfop", "ncm", "cst"}
    assert docs["cfop"]["codes"] == {"1101": "Compra"}
    assert docs["cfop"]["title_codes"] == ["1100"]
    assert docs["ncm"]["metadata"]["official_update"] == "20/11/2026"
    assert docs["cst"]["tables"]["csosn"][0] == "101"
