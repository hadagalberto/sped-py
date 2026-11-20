from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sped.core.reader import read
from sped.core.writer import write
from sped.factories.synthetic import SyntheticOptions, build_records, write_synthetic


@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(cnpj=st.text(alphabet="0123456789", min_size=14, max_size=14))
def test_write_read_roundtrip_is_byte_identical(tmp_path: Path, cnpj: str) -> None:
    options = SyntheticOptions(cod_ver="020", cnpj=cnpj)
    original = write_synthetic(tmp_path / "original.txt", options)
    copy = tmp_path / "copy.txt"
    with read(original) as source:
        write(source, copy)
    assert original.read_bytes() == copy.read_bytes()


@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(quantity=st.integers(min_value=1, max_value=3))
def test_totals_recomputation_idempotent(tmp_path: Path, quantity: int) -> None:
    records = build_records()
    expanded: list[tuple[str, tuple[str, ...]]] = []
    for record in records:
        expanded.append(record)
        if record[0] == "C170":
            expanded.extend([record] * (quantity - 1))
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    write(expanded, first)
    write(first.read_bytes().decode("latin-1").splitlines(), second)
    assert first.read_bytes() == second.read_bytes()
