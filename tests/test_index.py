from __future__ import annotations

from pathlib import Path

import pytest

from sped.core.encoding import detect_encoding
from sped.core.index import (
    MAGIC,
    IndexedReader,
    SpedIndex,
    build_index,
    default_index_path,
)
from sped.core.reader import SpedReader
from sped.core.types import Layout, Record
from sped.factories.synthetic import BROKEN_KINDS, SyntheticOptions, write_broken, write_synthetic
from sped.layouts import OBRIGACOES, available_versions, detect_layout

PAIRS: tuple[tuple[str, str], ...] = tuple(
    (obrigacao, available_versions(obrigacao)[-1]) for obrigacao in OBRIGACOES
)


def test_index_returns_same_records_as_full_scan(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        records = list(reader)
    layout = reader.layout
    path = build_index(efd_file)
    assert path == default_index_path(efd_file)
    index = SpedIndex.open(path, efd_file)
    assert set(index.codes()) == {record.code for record in records}
    assert all(index.count(code) > 0 for code in index.codes())
    for code in index.codes():
        expected = [record for record in records if record.code == code]
        actual = list(index.records(code, layout))
        assert len(actual) == index.count(code) == len(expected)
        for got, want in zip(actual, expected, strict=True):
            assert (got.line_no, got.code, got.raw, got.values) == (
                want.line_no,
                want.code,
                want.raw,
                want.values,
            )


def test_index_custom_destination_and_unknown_code(tmp_path: Path) -> None:
    source = write_synthetic(tmp_path / "source.txt")
    target = tmp_path / "custom" / "idx.bin"
    build_index(source, target)
    index = SpedIndex.open(target, source)
    layout: Layout = detect_layout(source)
    assert "XXXX" not in index
    assert index.count("XXXX") == 0
    assert list(index.offsets("XXXX")) == []
    assert list(index.records("XXXX", layout)) == []


def test_indexed_reader_builds_on_demand(tmp_path: Path) -> None:
    source = write_synthetic(tmp_path / "auto.txt")
    reader = IndexedReader(source)
    assert not default_index_path(source).exists()
    records = reader.get("C170")
    assert len(records) == 1
    assert records[0].get("COD_ITEM") == "PRODUTO001"
    assert reader.count("C170") == 1
    assert default_index_path(source).exists()
    assert next(iter(IndexedReader(source).by_type("C170"))).raw == records[0].raw


def test_index_stale_source_is_rejected(tmp_path: Path) -> None:
    source = write_synthetic(tmp_path / "stale.txt")
    path = build_index(source)
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="desatualizado"):
        SpedIndex.open(path, source)
    # IndexedReader rebuilds transparently.
    assert IndexedReader(source).count("9999") == 1


def test_index_rejects_foreign_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.idx"
    bad.write_bytes(b"NOTSPED!" + b"\x00" * 16)
    with pytest.raises(ValueError, match="índice SPED"):
        SpedIndex.open(bad)


def test_index_signature_is_ignored(tmp_path: Path) -> None:
    source = write_synthetic(tmp_path / "signed.txt", SyntheticOptions(with_signature=True))
    index = SpedIndex.open(build_index(source), source)
    with SpedReader(source) as reader:
        records: list[Record] = list(reader)
    assert sum(index.count(code) for code in index.codes()) == len(records)


def test_index_utf8_and_lf(tmp_path: Path) -> None:
    source = write_synthetic(
        tmp_path / "utf8.txt",
        SyntheticOptions(encoding="utf-8", line_ending="\n"),
    )
    assert detect_encoding(source.read_bytes()[:8192]) == "utf-8"
    index = SpedIndex.open(build_index(source), source)
    assert index.header["encoding"] == "utf-8"
    with SpedReader(source) as reader:
        expected = [record for record in reader if record.code == "C170"]
        layout = reader.layout
    actual = list(index.records("C170", layout))
    assert [record.raw for record in actual] == [record.raw for record in expected]


@pytest.mark.parametrize("kind", BROKEN_KINDS)
def test_index_does_not_crash_on_broken_files(tmp_path: Path, kind: str) -> None:
    source = write_broken(tmp_path / f"{kind}.txt", kind)
    index = SpedIndex.open(build_index(source), source, validate=False)
    assert isinstance(index.codes(), tuple)
    assert MAGIC == b"SPEDIDX1"


@pytest.mark.parametrize(("obrigacao", "cod_ver"), PAIRS)
def test_index_for_each_obrigacao(tmp_path: Path, obrigacao: str, cod_ver: str) -> None:
    source = write_synthetic(tmp_path / f"{obrigacao}.txt", SyntheticOptions(cod_ver, obrigacao))
    with SpedReader(source) as reader:
        records = list(reader)
        layout = reader.layout
    index = SpedIndex.open(build_index(source), source)
    code = next(record.code for record in records if record.code.endswith("001"))
    got = list(index.records(code, layout))
    want = [record for record in records if record.code == code]
    assert [record.raw for record in got] == [record.raw for record in want]
