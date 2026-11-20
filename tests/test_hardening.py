"""Regression tests for the milestone-5 audit and hostile-input sweep."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from sped.analysis import diff_files
from sped.cli import main
from sped.core.encoding import detect_encoding, is_signature_line, iter_lines
from sped.core.index import SpedIndex, build_index
from sped.core.reader import read
from sped.core.writer import format_line
from sped.exports import MissingOptionalDependencyError, to_parquet
from sped.factories.synthetic import (
    SyntheticOptions,
    _overrides,
    _values,
    write_synthetic,
)
from sped.layouts import _parse_field, load_layout
from sped.validation import validate
from sped.validation.totals import compute_icms_totals


def test_utf8_multibyte_at_sample_boundary(tmp_path: Path) -> None:
    """An 8192-byte sample may cut a character: encoding must still be UTF-8."""
    line = "|0000|020|" + "A" * (8191 - 10) + "ç|" + "B" * 10 + "|\r\n"
    data = line.encode("utf-8")
    assert data[8191:8192] == b"\xc3"  # second byte falls outside the sample
    assert detect_encoding(data[:8192]) == "utf-8"
    path = tmp_path / "boundary.txt"
    path.write_bytes(data)
    assert "ç" in next(iter(iter_lines(path)))  # decoded as UTF-8, not mojibake
    with read(path, layout=load_layout("020"), strict=False) as reader:
        assert next(iter(reader)).code == "0000"  # no decode failure


def test_framed_signature_is_stripped(tmp_path: Path) -> None:
    """Signers may frame the SBMDSIG marker with pipes."""
    assert is_signature_line("|SBMDSIG|ABC|")
    assert is_signature_line("|-----BEGIN PKCS7-----|")
    assert not is_signature_line("|0000|020|")
    base = write_synthetic(tmp_path / "base.txt")
    path = tmp_path / "signed.txt"
    path.write_bytes(base.read_bytes() + b"|SBMDSIG|ABCD|\r\n|-----BEGIN PKCS7-----|\r\n")
    assert list(iter_lines(path))[-1].startswith("|9999|")
    with read(path) as reader:
        assert [record.code for record in reader][-1] == "9999"
    assert validate(path) == []


def test_top_level_get_dataframe_export(efd_file: Path) -> None:
    """The import used by both READMEs must be part of the public API."""
    from sped import get_dataframe  # noqa: PLC0415

    frame = get_dataframe(efd_file, "C170")
    assert len(frame) == 1
    assert "VL_ITEM" in frame.columns


def test_icms_totals_use_the_parent_of_their_own_block(tmp_path: Path) -> None:
    """D190 inherits D100 (cancelado), never a stale C100 from block C."""
    layout = load_layout("020")
    opts = SyntheticOptions()
    lines = write_synthetic(tmp_path / "base.txt").read_text("latin-1").splitlines()

    def set_field(prefix: str, field: str, value: str) -> None:
        for index, line in enumerate(lines):
            if line.startswith(f"|{prefix}|"):
                names = [definition.name for definition in layout.register(prefix).fields][1:]
                parts = line.split("|")
                parts[2 + names.index(field)] = value
                lines[index] = "|".join(parts)
                return
        raise AssertionError(prefix)

    set_field("C100", "COD_SIT", "00")
    set_field("C100", "IND_OPER", "0")
    overrides = _overrides(layout, opts)
    d100 = format_line("D100", _values(layout, "D100", {**overrides, "COD_SIT": "01"}))
    d190 = format_line("D190", _values(layout, "D190", {**overrides, "VL_ICMS": "5000"}))
    index = next(i for i, line in enumerate(lines) if line.startswith("|D990|"))
    lines[index:index] = [d100, d190]
    path = tmp_path / "both_blocks.txt"
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))

    with read(path, layout=layout, strict=False) as reader:
        totals = compute_icms_totals(reader.iter_records())
    assert totals.debitos == Decimal(0)
    # C2: VL_ICMS "10000" em N(15,2) vale 10000,00 (sem escalamento).
    assert totals.creditos == Decimal("10000")


def test_validate_exit_code_only_for_errors(
    broken_file_factory: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """SPEC: non-zero exit on errors; warnings are advisory only."""
    assert main(["validate", str(broken_file_factory("late_participant"))]) == 0
    assert "SPED-XREF-ORDER-001" in capsys.readouterr().out
    assert main(["validate", str(broken_file_factory("wrong_file_total"))]) == 1


def test_cli_usage_exit_codes(efd_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Documented exit code 2 is for invalid usage, not I/O failures."""
    assert main(["diff", str(efd_file), str(efd_file), "--limit", "-1"]) == 2
    assert "uso inválido" in capsys.readouterr().err
    other = write_synthetic(
        efd_file.parent / "contrib.txt", SyntheticOptions("006", "efd_contribuicoes")
    )
    assert main(["merge", str(efd_file), str(other), "-o", str(efd_file.parent / "m.txt")]) == 2
    assert "leiautes incompatíveis" in capsys.readouterr().err


def test_fix_totals_auto_detects_input_encoding(tmp_path: Path) -> None:
    """UTF-8 input keeps its characters without an explicit --encoding."""
    source = write_synthetic(
        tmp_path / "utf8.txt",
        SyntheticOptions(cod_ver="020", participant="CLIENTEÇÃO", encoding="utf-8"),
    )
    target = tmp_path / "fixed.txt"
    assert main(["fix-totals", str(source), "-o", str(target)]) == 0
    data = target.read_bytes()
    assert "CLIENTEÇÃO".encode() in data
    assert detect_encoding(data[:8192]) == "utf-8"
    assert validate(target) == []


def test_diff_survives_broken_framing(efd_file: Path, tmp_path: Path) -> None:
    """Malformed lines are skipped, not fatal, in an offline comparison."""
    other = tmp_path / "broken.txt"
    data = efd_file.read_bytes().splitlines(keepends=True)
    data.insert(1, b"linha sem delimitadores\r\n")
    other.write_bytes(b"".join(data))
    result = diff_files(efd_file, other)
    assert not result.has_differences


def test_cross_references_are_derived_from_the_layout(tmp_path: Path) -> None:
    """Registers other than C100/D100 that carry COD_PART are checked."""
    layout = load_layout("020")
    overrides = _overrides(layout, SyntheticOptions())
    lines = write_synthetic(tmp_path / "base.txt").read_text("latin-1").splitlines()
    b020 = format_line("B020", _values(layout, "B020", {**overrides, "COD_PART": "NAOEXISTE"}))
    index = next(i for i, line in enumerate(lines) if line.startswith("|B001|")) + 1
    lines.insert(index, b020)
    path = tmp_path / "xref.txt"
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    assert any(
        issue.rule == "SPED-XREF-0150-001" and issue.code == "B020" for issue in validate(path)
    )


def test_item_unit_reference_is_still_checked(tmp_path: Path) -> None:
    """0200.UNID_INV references 0190 — do not lose it when deriving users."""
    layout = load_layout("020")
    lines = write_synthetic(tmp_path / "base.txt").read_text("latin-1").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("|0200|"):
            parts = line.split("|")
            names = [definition.name for definition in layout.register("0200").fields][1:]
            parts[2 + names.index("UNID_INV")] = "XXX"
            lines[index] = "|".join(parts)
            break
    path = tmp_path / "unit.txt"
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    assert any(
        issue.rule == "SPED-XREF-0190-001" and issue.code == "0200" for issue in validate(path)
    )


def test_required_flag_accepts_repeated_tokens() -> None:
    """Extracted tables sometimes repeat the token: 'O O', 'OC OC'."""
    base = {"num": 1, "name": "CAMPO", "type": "C", "tam": "4*", "dec": "-"}
    assert _parse_field({**base, "obrig": "O O"}).required
    assert not _parse_field({**base, "obrig": "OC OC"}).required
    assert _parse_field({**base, "obrig": "OC OC"}).conditional
    assert _parse_field({**base, "obrig": "Sim"}).required
    assert not _parse_field({**base, "obrig": "Não"}).required


def test_index_fails_closed_when_source_is_missing(efd_file: Path, tmp_path: Path) -> None:
    """A stale/missing source must not silently pair with an old index."""
    index = build_index(efd_file, tmp_path / "file.idx")
    moved = tmp_path / "moved.txt"
    efd_file.replace(moved)
    with pytest.raises(ValueError, match="origem"):
        SpedIndex.open(index, efd_file)


def test_paths_with_spaces_and_accents(efd_file: Path) -> None:
    """Windows-style paths with spaces and non-ASCII names work end to end."""
    target = efd_file.parent / "pasta com espaço çã o" / "arquivo çã o.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(efd_file.read_bytes())
    assert validate(target) == []
    assert main(["info", str(target)]) == 0


def test_oversized_field_is_reported_without_crash(tmp_path: Path) -> None:
    """A 1 MB field is a validation error, never an exception."""
    path = tmp_path / "huge.txt"
    line = "|0000|020|" + "X" * 1_000_000 + "|\r\n"
    path.write_bytes(line.encode("latin-1"))
    issues = validate(path)
    assert any(issue.rule == "SPED-FIELD" for issue in issues)


def test_parquet_missing_engine_is_actionable(
    efd_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pandas.to_parquet without pyarrow must name the extra, not leak ImportError."""

    def broken(self: object, *_args: object, **_kwargs: object) -> None:
        raise ImportError("pyarrow missing")

    import pandas as pd  # type: ignore[import-untyped]  # noqa: PLC0415

    monkeypatch.setattr(pd.DataFrame, "to_parquet", broken, raising=False)
    with pytest.raises(MissingOptionalDependencyError, match=r"\[pandas\].*pyarrow"):
        to_parquet(efd_file, tmp_path / "pq", library="pandas")
