"""Testes dos auxiliares de análise, com vetores válidos e inválidos conhecidos."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import sped
from sped.analysis import (
    compute_apuracao,
    diff_files,
    format_date,
    merge_files,
    parse_date,
    recompute_apuracao,
    split_file,
    split_periods,
    summarize,
    summarize_all,
    summarize_file,
)
from sped.core.reader import read
from sped.core.types import Record
from sped.factories.synthetic import SyntheticOptions, write_broken, write_synthetic
from sped.layouts import detect_layout


def _records(path: Path) -> list[Record]:
    with read(path, strict=False) as arquivo:
        return list(arquivo.iter_records())


# ---------------------------------------------------------------------------
# Resumos
# ---------------------------------------------------------------------------


def test_summarize_cfop(efd_file: Path) -> None:
    summaries = summarize_file(efd_file, dimensions=("CFOP",))
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.dimension == "CFOP"
    assert summary.total_count == 1
    assert len(summary.rows) == 1
    row = summary.rows[0]
    assert row.value == "1101"
    assert row.count == 1
    # C2: SPED não tem decimais implícitos — "10000" em N(15,2) é 10000,00.
    assert row.totals["VL_ITEM"] == Decimal("10000.00")
    assert summary.grand_totals["VL_ICMS"] == Decimal("10000")
    assert summary.as_dict()["dimensao"] == "CFOP"


def test_summarize_all_dimensions(efd_file: Path) -> None:
    summaries = summarize_file(efd_file)
    assert tuple(item.dimension for item in summaries) == ("CFOP", "CST_ICMS", "COD_PART")
    assert summaries[1].rows[0].value == "000"
    assert summaries[2].rows[0].value == "CLIENTE001"
    assert all(item.total_count == 1 for item in summaries)


def test_summarize_single_pass_and_serialization(efd_file: Path) -> None:
    layout = detect_layout(efd_file)
    records = _records(efd_file)
    result = summarize(records, "CFOP", layout=layout, fields=("VL_ITEM",))
    assert set(result.rows[0].totals) == {"VL_ITEM"}
    assert result.as_dict()["quantidade_total"] == 1
    multi = summarize_all(records, layout=layout, dimensions=("CFOP", "COD_PART"))
    assert len(multi) == 2


def test_summarize_empty_and_invalid_dimension(efd_file: Path) -> None:
    layout = detect_layout(efd_file)
    empty = summarize([], "CFOP", layout=layout)
    assert empty.rows == ()
    assert empty.total_count == 0
    assert empty.grand_totals["VL_ITEM"] == 0
    with pytest.raises(ValueError, match="dimensão"):
        summarize([], "NAO_EXISTE", layout=layout)
    with pytest.raises(ValueError, match="campos de resumo"):
        summarize([], "CFOP", layout=layout, fields=("CAMPO_FALSO",))
    with pytest.raises(ValueError, match="uma dimensão"):
        summarize_all([], layout=layout, dimensions=())


# ---------------------------------------------------------------------------
# Apuração
# ---------------------------------------------------------------------------


def test_apuracao_valid_file(efd_file: Path) -> None:
    layout = detect_layout(efd_file)
    result = compute_apuracao(_records(efd_file), layout=layout)
    assert result.ok
    assert result.obrigacao == "efd_icmsipi"
    assert result.period == ("01012024", "31122024")
    assert result.divergences == ()
    assert any(field.register == "E110" for field in result.fields)
    assert any(field.register == "C190" for field in result.fields)
    assert all(field.ok for field in result.fields)
    assert result.as_dict()["divergencias"] == 0


@pytest.mark.parametrize(
    ("kind", "register", "field"),
    [
        ("bad_e110_apuracao", "E110", "VL_TOT_CREDITOS"),
        ("bad_e110_saldo", "E110", "VL_SLD_APURADO"),
        ("bad_e110_transportar", "E110", "VL_SLD_CREDOR_TRANSPORTAR"),
        ("bad_c190_total", "C190", "VL_BC_ICMS"),
    ],
)
def test_apuracao_invalid_vectors(
    kind: str,
    register: str,
    field: str,
    broken_file_factory: Callable[[str], Path],
) -> None:
    path = broken_file_factory(kind)
    layout = detect_layout(path)
    result = compute_apuracao(_records(path), layout=layout)
    assert not result.ok
    assert any(item.register == register and item.field == field for item in result.divergences)
    divergent = next(item for item in result.divergences if item.field == field)
    assert divergent.difference is not None
    assert divergent.difference != 0
    assert divergent.as_dict()["ok"] is False


def test_apuracao_contribuicoes_and_accounting(tmp_path: Path) -> None:
    for obrigacao, cod_ver, kind, field in (
        ("efd_contribuicoes", "006", "bad_m210_bc", "VL_BC_CONT_AJUS"),
        ("ecd", "009", "bad_ecd_saldo", "IND_DC_FIN"),
        ("ecf", "012", "bad_ecf_saldo", "IND_VL_SLD_FIN"),
    ):
        options = SyntheticOptions(obrigacao=obrigacao, cod_ver=cod_ver)
        broken = write_broken(tmp_path / f"{obrigacao}.txt", kind, options)
        result = compute_apuracao(_records(broken), layout=detect_layout(broken))
        assert not result.ok, obrigacao
        assert any(item.field == field for item in result.divergences), obrigacao


def test_recompute_apuracao_fixes_file(
    broken_file_factory: Callable[[str], Path], tmp_path: Path
) -> None:
    broken = broken_file_factory("bad_e110_apuracao")
    target = recompute_apuracao(broken, tmp_path / "fixed.txt")
    assert sped.validate(target) == []
    layout = detect_layout(target)
    assert compute_apuracao(_records(target), layout=layout).ok


def test_recompute_apuracao_default_destination(
    broken_file_factory: Callable[[str], Path],
) -> None:
    broken = broken_file_factory("bad_c190_total")
    target = recompute_apuracao(broken)
    assert target.name == f"{broken.stem}-apurado{broken.suffix}"
    assert sped.validate(target) == []


def test_apuracao_field_string_comparison(tmp_path: Path) -> None:
    path = write_broken(
        tmp_path / "ecd-bad.txt",
        "bad_ecd_saldo",
        SyntheticOptions(obrigacao="ecd", cod_ver="009"),
    )
    layout = detect_layout(path)
    result = compute_apuracao(_records(path), layout=layout)
    divergent = next(item for item in result.divergences if item.field == "IND_DC_FIN")
    assert divergent.difference is None
    assert divergent.stated != divergent.computed


# ---------------------------------------------------------------------------
# Períodos
# ---------------------------------------------------------------------------


def test_period_helpers() -> None:
    assert format_date(date(2024, 1, 31)) == "31012024"
    assert parse_date("01012024") == date(2024, 1, 1)
    with pytest.raises(ValueError, match="data SPED inválida"):
        parse_date("2024-01-01")
    assert split_periods("01012024", "31122024", "month")[0].contains(date(2024, 1, 15))
    assert len(split_periods("01012024", "31122024", "quarter")) == 4
    assert len(split_periods("01012024", "31122024", "year")) == 1
    periods = split_periods("15012024", "15032024", "month")
    assert len(periods) == 3
    assert format_date(periods[0].start) == "15012024"
    assert format_date(periods[0].end) == "31012024"
    assert format_date(periods[1].end) == "29022024"
    assert periods[0].code == "202401"
    assert periods[0].label == "202401-202401"
    with pytest.raises(ValueError, match="DT_INI posterior"):
        split_periods("31122024", "01012024")
    with pytest.raises(ValueError, match="granularidade"):
        split_periods("01012024", "31122024", "week")


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def test_diff_identical(efd_file: Path) -> None:
    result = diff_files(efd_file, efd_file)
    assert not result.has_differences
    assert (result.added, result.removed, result.changed) == (0, 0, 0)
    assert result.as_dict()["diferencas"] is False


def test_diff_changed_value(efd_file: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.txt"
    other.write_bytes(efd_file.read_bytes().replace(b"CLIENTE001", b"CLIENTE002"))
    result = diff_files(efd_file, other)
    # O participante aparece em 0150 (cadastro) e C100 (documento).
    assert result.changed == 2
    assert result.added == result.removed == 0
    assert {entry.code for entry in result.entries} == {"0150", "C100"}
    assert all(entry.kind == "changed" for entry in result.entries)
    assert "CLIENTE001" in str(result.entries[0].left)
    assert "CLIENTE002" in str(result.entries[0].right)


def test_diff_inserted_and_removed_lines(efd_file: Path, tmp_path: Path) -> None:
    lines = efd_file.read_bytes().splitlines(keepends=True)
    inserted = tmp_path / "inserted.txt"
    extra = b"|0190|UN|UNIDADE TESTE|\r\n"
    inserted.write_bytes(b"".join(lines[:5]) + extra + b"".join(lines[5:]))
    result = diff_files(efd_file, inserted)
    assert result.added == 1
    assert result.changed == result.removed == 0
    assert result.entries[0].kind == "added"

    removed = tmp_path / "removed.txt"
    removed.write_bytes(b"".join(lines[:5] + lines[6:]))
    reverse = diff_files(efd_file, removed)
    assert reverse.removed == 1
    assert reverse.entries[0].kind == "removed"


def test_diff_replaced_register_code(efd_file: Path, tmp_path: Path) -> None:
    lines = efd_file.read_bytes().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith(b"|0190|"):
            lines[index] = b"|0191|OUTRO|TESTE|\r\n|0192|MAIS|UM|\r\n"
            break
    other = tmp_path / "replaced.txt"
    other.write_bytes(b"".join(lines))
    result = diff_files(efd_file, other, limit=10)
    assert result.added >= 1
    assert result.removed >= 1
    assert any(entry.kind == "added" for entry in result.entries)
    assert any(entry.kind == "removed" for entry in result.entries)


def test_diff_limit(efd_file: Path, tmp_path: Path) -> None:
    other = tmp_path / "other.txt"
    other.write_bytes(efd_file.read_bytes().replace(b"CLIENTE001", b"CLIENTE002"))
    result = diff_files(efd_file, other, limit=0)
    assert result.changed == 2
    assert result.entries == ()
    with pytest.raises(ValueError, match="limit"):
        diff_files(efd_file, other, limit=-1)


# ---------------------------------------------------------------------------
# Merge / split
# ---------------------------------------------------------------------------


def test_record_helpers_invalid_values(broken_file_factory: Callable[[str], Path]) -> None:
    from sped.analysis._records import get_field, record_date, set_field  # noqa: PLC0415

    path = broken_file_factory("invalid_date")
    with read(path, strict=False) as arquivo:
        opening = next(record for record in arquivo.iter_records() if record.code == "0000")
    layout = detect_layout(path)
    # DT_INI inválido é ignorado; a função usa a próxima data válida (DT_FIN).
    assert record_date(opening, layout) == date(2024, 12, 31)
    output = ("0000", tuple(raw for raw in opening.raw_values if raw != "0000"))
    with pytest.raises(ValueError, match="não existe"):
        get_field(output, layout, "CAMPO_INEXISTENTE")
    with pytest.raises(ValueError, match="não existe"):
        set_field(output, layout, "CAMPO_INEXISTENTE", "x")


def test_merge_two_files(efd_file: Path, tmp_path: Path) -> None:
    other = write_synthetic(
        tmp_path / "feb.txt",
        SyntheticOptions(dt_ini="01022024", dt_fin="29022024", participant="CLIENTE002"),
    )
    merged = merge_files([efd_file, other], tmp_path / "merged.txt")
    assert sped.validate(merged) == []
    with read(merged) as arquivo:
        records = list(arquivo.iter_records())
    header = next(record for record in records if record.code == "0000")
    assert header.raw_get("DT_INI") == "01012024"
    assert header.raw_get("DT_FIN") == "31122024"
    assert sum(record.code == "C100" for record in records) == 2
    assert sum(record.code == "E110" for record in records) == 1
    assert sum(record.code == "0150" for record in records) == 2


def test_merge_rejects_incompatible_layouts(efd_file: Path, tmp_path: Path) -> None:
    other = write_synthetic(
        tmp_path / "contrib.txt",
        SyntheticOptions(obrigacao="efd_contribuicoes", cod_ver="006"),
    )
    with pytest.raises(ValueError, match="leiautes incompatíveis"):
        merge_files([efd_file, other], tmp_path / "bad.txt")
    with pytest.raises(ValueError, match="ao menos um"):
        merge_files([], tmp_path / "bad.txt")


def test_split_by_month(efd_file: Path, tmp_path: Path) -> None:
    parts = split_file(efd_file, tmp_path / "parts")
    assert len(parts) == 12
    assert [part.name for part in parts[:2]] == ["efd_202401.txt", "efd_202402.txt"]
    for part in parts:
        assert sped.validate(part) == []
    with read(parts[0]) as arquivo:
        january = next(record for record in arquivo.iter_records() if record.code == "0000")
    assert january.raw_get("DT_INI") == "01012024"
    assert january.raw_get("DT_FIN") == "31012024"
    with read(parts[-1]) as arquivo:
        december = next(record for record in arquivo.iter_records() if record.code == "0000")
    assert december.raw_get("DT_FIN") == "31122024"


@pytest.mark.parametrize(("by", "expected"), [("quarter", 4), ("year", 1)])
def test_split_other_granularities(by: str, expected: int, efd_file: Path, tmp_path: Path) -> None:
    parts = split_file(efd_file, tmp_path / by, by=by)
    assert len(parts) == expected
    assert all(sped.validate(part) == [] for part in parts)


def test_split_invalid_granularity(efd_file: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="granularidade"):
        split_file(efd_file, tmp_path / "bad", by="week")


def test_merge_and_split_all_obligations(tmp_path: Path) -> None:
    for obrigacao, cod_ver in (
        ("efd_contribuicoes", "006"),
        ("ecd", "009"),
        ("ecf", "012"),
    ):
        options = SyntheticOptions(obrigacao=obrigacao, cod_ver=cod_ver)
        first = write_synthetic(tmp_path / f"{obrigacao}-1.txt", options)
        second = write_synthetic(tmp_path / f"{obrigacao}-2.txt", options)
        merged = merge_files([first, second], tmp_path / f"{obrigacao}-merged.txt")
        parts = split_file(first, tmp_path / f"{obrigacao}-parts", by="year")
        assert sped.validate(merged) == [], obrigacao
        assert all(sped.validate(part) == [] for part in parts), obrigacao
