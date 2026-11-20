"""Testes positivos/negativos de cada regra do validador PVA-like.

Toda regra registrada em ``sped.validation.RULES`` possui aqui um caso com
fixture válida (sem a regra) e uma variante quebrada (com a regra), conforme
exigido pela SPEC. Todas as fixtures são sintéticas.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from sped.core.reader import SpedParseError
from sped.core.types import Field, FieldDef, Record
from sped.factories.synthetic import (
    BROKEN_SPECS,
    Mutation,
    SyntheticOptions,
    _apply_mutation,
    _field_index,
    write_broken,
    write_synthetic,
)
from sped.validation import RULES, Severity, ValidationIssue, validate
from sped.validation.context import money, number

EFD = SyntheticOptions()
CONTRIB = SyntheticOptions(cod_ver="006", obrigacao="efd_contribuicoes")
ECD = SyntheticOptions(cod_ver="009", obrigacao="ecd")
ECF = SyntheticOptions(cod_ver="012", obrigacao="ecf")


@dataclass(frozen=True, slots=True)
class Case:
    rule_id: str
    kind: str
    options: SyntheticOptions


CASES: tuple[Case, ...] = (
    Case("SPED-FRAME", "missing_0000", EFD),
    Case("SPED-FIELD", "bad_field_size", EFD),
    Case("SPED-STRUCT", "missing_block_closing", EFD),
    Case("SPED-9900", "bad_9900_count", EFD),
    Case("SPED-9999", "wrong_file_total", EFD),
    Case("SPED-9990", "wrong_9990_count", EFD),
    Case("SPED-STRUCT-X990-001", "wrong_x990_count", EFD),
    Case("SPED-STRUCT-HIER-001", "orphan_c170", EFD),
    Case("SPED-TAB-CNPJ-001", "invalid_cnpj", EFD),
    Case("SPED-TAB-CFOP-002", "cfop_oper_mismatch", EFD),
    Case("SPED-PERFIL-001", "invalid_perfil", EFD),
    Case("SPED-PERFIL-002", "missing_perfil_record", EFD),
    Case("SPED-PERFIL-003", "forbidden_perfil_record", EFD),
    Case("SPED-TAB-CFOP-001", "invalid_cfop", EFD),
    Case("SPED-TAB-CST-001", "invalid_cst", EFD),
    Case("SPED-TAB-NCM-001", "invalid_ncm", EFD),
    Case("SPED-XREF-0150-001", "unknown_participant", EFD),
    Case("SPED-XREF-0200-001", "unknown_item", EFD),
    Case("SPED-XREF-0190-001", "unknown_unit", EFD),
    Case("SPED-XREF-ORDER-001", "late_participant", EFD),
    Case("SPED-XREF-DUP-001", "duplicate_participant", EFD),
    Case("SPED-TOT-ICMS-C170-001", "bad_c170_total", EFD),
    Case("SPED-TOT-ICMS-C190-001", "bad_c190_total", EFD),
    Case("SPED-TOT-ICMS-C190-002", "duplicate_c190", EFD),
    Case("SPED-TOT-ICMS-E110-001", "bad_e110_apuracao", EFD),
    Case("SPED-TOT-ICMS-E110-002", "bad_e110_saldo", EFD),
    Case("SPED-TOT-ICMS-E110-003", "bad_e110_recolher", EFD),
    Case("SPED-TOT-ICMS-E110-004", "bad_e110_transportar", EFD),
    Case("SPED-TOT-CONTRIB-M210-001", "bad_m210_bc", CONTRIB),
    Case("SPED-TOT-CONTRIB-M210-002", "bad_m210_per", CONTRIB),
    Case("SPED-TOT-CONTRIB-M610-001", "bad_m610_bc", CONTRIB),
    Case("SPED-TOT-CONTRIB-M610-002", "bad_m610_per", CONTRIB),
    Case("SPED-TOT-CONTRIB-M200-001", "bad_m200_detail", CONTRIB),
    Case("SPED-TOT-CONTRIB-M200-002", "bad_m200_total", CONTRIB),
    Case("SPED-TOT-CONTRIB-M600-001", "bad_m600_detail", CONTRIB),
    Case("SPED-TOT-CONTRIB-M600-002", "bad_m600_total", CONTRIB),
    Case("SPED-TOT-ECD-001", "bad_ecd_balance", ECD),
    Case("SPED-TOT-ECD-002", "bad_ecd_saldo", ECD),
    Case("SPED-TOT-ECF-001", "bad_ecf_saldo", ECF),
)

CASE_IDS = [case.rule_id for case in CASES]


def test_every_rule_has_a_broken_fixture_case() -> None:
    assert set(CASE_IDS) == set(RULES)
    assert len(CASE_IDS) == len(set(CASE_IDS))
    for case in CASES:
        assert case.kind in BROKEN_SPECS


@pytest.mark.parametrize("rule_id", list(RULES))
def test_rule_definition_is_complete(rule_id: str) -> None:
    rule = RULES[rule_id]
    assert rule.id == rule_id
    assert rule.title.strip()
    assert rule.message.strip()
    assert rule.severity in {Severity.ERROR, Severity.WARNING}
    assert "http" in rule.source


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_broken_variant_reports_its_rule(case: Case, tmp_path: Path) -> None:
    path = write_broken(tmp_path / "broken.txt", case.kind, case.options)
    matching = [issue for issue in validate(path) if issue.rule == case.rule_id]
    assert matching, f"{case.kind} não disparou {case.rule_id}"
    for issue in matching:
        assert issue.message
        assert "{" not in issue.message
        assert issue.severity == RULES[case.rule_id].severity


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_valid_fixture_does_not_report_the_rule(case: Case, tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "valid.txt", case.options)
    assert validate(path) == []
    assert not any(issue.rule == case.rule_id for issue in validate(path))


@pytest.mark.parametrize(
    "options",
    [
        SyntheticOptions(cod_ver=ver, obrigacao="efd_icmsipi", perfil=perfil)
        for ver in ("013", "017", "020")
        for perfil in ("A", "B")
    ],
)
def test_icmsipi_profiles_a_and_b_are_valid(options: SyntheticOptions, tmp_path: Path) -> None:
    assert validate(write_synthetic(tmp_path / "file.txt", options)) == []


@pytest.mark.parametrize(
    "options",
    [
        SyntheticOptions(obrigacao=obrigacao, cod_ver=ver, dc_ini=sign, dc_fin=sign)
        for obrigacao, ver in (("ecd", "009"), ("ecf", "012"))
        for sign in ("C", "D")
    ],
)
def test_credit_and_debit_balances_are_valid(options: SyntheticOptions, tmp_path: Path) -> None:
    assert validate(write_synthetic(tmp_path / "file.txt", options)) == []


def test_number_and_money_helpers() -> None:
    definition = FieldDef(1, "VL_ITEM", "N", 10, False, 2)
    rec = Record(1, "C170", (Field(definition, "100,50", Decimal("100.50")),))
    assert number(rec, "VL_ITEM") == Decimal("100.50")
    assert money(Decimal("100.5")) == "100.50"
    assert number(rec, "MISSING") == Decimal(0)
    empty = Record(2, "C170", (Field(definition, "", None),))
    assert number(empty, "VL_ITEM") == Decimal(0)
    text = Record(3, "C170", (Field(definition, "abc", "abc"),))
    assert number(text, "VL_ITEM") == Decimal(0)
    bool_field = FieldDef(2, "FLAG", "N", 1, False, 0)
    assert number(Record(4, "X", (Field(bool_field, "1", True),)), "FLAG") == Decimal(1)


def test_factory_rejects_unknown_mutation(tmp_path: Path) -> None:
    path = write_synthetic(tmp_path / "valid.txt")
    lines = path.read_text(encoding="latin-1").splitlines()
    with pytest.raises(AssertionError, match="ação desconhecida"):
        _apply_mutation(lines, Mutation("nope", "0000"), EFD)
    with pytest.raises(AssertionError, match="não existe"):
        _field_index("0000", "CAMPO_INEXISTENTE", EFD)


def test_parse_error_is_reported_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_synthetic(tmp_path / "valid.txt")

    class BrokenReader:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def iter_records(self) -> object:
            raise SpedParseError(7, "falha simulada")

    from sped.validation import engine  # noqa: PLC0415

    monkeypatch.setattr(engine, "SpedReader", BrokenReader)
    issues = engine.validate(path)
    assert any(issue.rule == "SPED-FRAME" and issue.line_no == 7 for issue in issues)


def test_validation_issue_serialization() -> None:
    issue = ValidationIssue("R", 3, "C170", "mensagem", Severity.WARNING)
    assert issue.as_dict()["severity"] == "warning"
