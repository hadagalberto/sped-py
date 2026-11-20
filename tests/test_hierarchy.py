from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

from sped.core.hierarchy import RecordTree, TreeNode, build_tree, level_of
from sped.core.reader import SpedReader
from sped.core.types import Field, FieldDef, Layout, Record
from sped.factories.synthetic import SyntheticOptions, write_synthetic
from sped.layouts import load_layout


def test_levels_come_from_official_layout() -> None:
    layout = load_layout("020")
    record = Record(1, "0000", (), "")
    assert level_of(record, layout) == layout.register("0000").level == 0
    assert level_of(Record(2, "C170", (), ""), layout) == 3
    assert level_of(Record(3, "C100", (), ""), layout) == 2


def test_level_fallback_without_official_level() -> None:
    layout = Layout(
        obrigacao="teste",
        cod_ver="000",
        versao="0",
        valid_from="2019-01-01",
        valid_to="2019-12-31",
        source_url="http://example.test",
        source_date="2019-01-01",
        registers={},
    )
    assert level_of(Record(1, "0000", (), ""), layout) == 0
    assert level_of(Record(2, "0001", (), ""), layout) == 1
    assert level_of(Record(3, "0990", (), ""), layout) == 1
    assert level_of(Record(4, "9900", (), ""), layout) == 2
    assert level_of(Record(5, "C170", (), ""), layout) == 2


def test_iter_entries_builds_parent_links_without_materialising(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        tree = build_tree(reader, reader.layout)
        entries = tree.iter_entries()
        first = next(entries)
        assert first.code == "0000"
        assert first.level == 0
        assert first.parent is None
        assert first.block == "0"
        second = next(entries)
        assert second.code == "0001"
        assert second.parent == "0000"
        assert second.level == 1
        rest = list(entries)
        assert rest
        assert all(entry.parent is not None for entry in rest if entry.level > 0)


def test_iter_nodes_links_children_and_descendants(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        records = list(reader)
    nodes = list(RecordTree(records, reader.layout).iter_nodes())
    root = nodes[0]
    assert isinstance(root, TreeNode)
    assert root.code == "0000"
    assert all(child.parent is root for child in root.children)
    opening = next(node for node in nodes if node.code == "C001")
    children = [node for node in nodes if node.parent is opening]
    assert children and all(child.code.startswith("C") for child in children)
    assert any(descendant.code in {"C100", "C170", "C190"} for descendant in opening.descendants())


def test_by_type_and_blocks(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        records = list(reader)
    tree = RecordTree(records, reader.layout)
    assert [record.code for record in tree.by_type("C100")] == ["C100"]
    assert list(tree.blocks()) == ["0", "C", "E", "9"]


def test_hierarchy_is_lazy_over_a_generator(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        records = list(reader)
    consumed = 0

    def generator() -> Iterator[Record]:
        nonlocal consumed
        for record in records:
            consumed += 1
            yield record

    entries = RecordTree(generator(), reader.layout).iter_entries()
    assert consumed == 0
    next(entries)
    assert consumed == 1
    assert len(list(entries)) == len(records) - 1
    assert consumed == len(records)


def test_hierarchy_works_for_all_obrigacoes(tmp_path: Path) -> None:
    for obrigacao, cod in (("efd_contribuicoes", "006"), ("ecd", "009"), ("ecf", "012")):
        path = write_synthetic(tmp_path / f"{obrigacao}.txt", SyntheticOptions(cod, obrigacao))
        with SpedReader(path) as reader:
            entries = list(RecordTree(reader, reader.layout).iter_entries())
        assert entries[0].code == "0000"
        assert entries[0].parent is None
        assert any(entry.code.endswith("001") and entry.parent == "0000" for entry in entries)
        assert any(entry.parent is not None for entry in entries)


def test_typed_values_available_in_nodes(efd_file: Path) -> None:
    with SpedReader(efd_file) as reader:
        node = next(node for node in RecordTree(reader, reader.layout) if node.code == "C170")
    assert node.record.get("COD_ITEM") == "PRODUTO001"
    assert node.record.get("QTD") == Decimal("0.00001")
    assert isinstance(node.record.fields[0], Field)
    assert isinstance(node.record.fields[0].definition, FieldDef)
