from __future__ import annotations

import tracemalloc
from pathlib import Path

import pytest

from sped.core.reader import read
from sped.core.writer import OutputRecord, write
from sped.factories.synthetic import build_records
from sped.layouts import load_layout


def test_flat_memory_small_stream(tmp_path: Path) -> None:
    """Constant-memory guarantee at a scale that runs on every CI job."""
    template: OutputRecord = next(record for record in build_records() if record[0] == "C170")
    path = tmp_path / "large.txt"
    path.write_bytes(b"")
    with path.open("ab") as handle:
        write([template] * 20_000, handle, recompute=False)

    tracemalloc.start()
    try:
        count = 0
        with read(path, layout=load_layout("020")) as reader:
            for record in reader:
                count += record.code == "C170"
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == 20_000
    assert peak < 32 * 1024 * 1024


@pytest.mark.slow
def test_one_gigabyte_stream(tmp_path: Path) -> None:
    """Opt-in 1 GB streaming test: `pytest -m slow`."""
    template: OutputRecord = next(record for record in build_records() if record[0] == "C170")
    path = tmp_path / "one_gb.txt"
    target_bytes = 1_000_000_000
    line = "|" + "|".join(("C170", *template[1])) + "|\r\n"
    repetitions = target_bytes // len(line.encode("latin-1")) + 1
    with path.open("wb") as handle:
        for _ in range(repetitions):
            handle.write(line.encode("latin-1"))
            if handle.tell() >= target_bytes:
                break

    tracemalloc.start()
    try:
        with read(path, layout=load_layout("020"), strict=False) as reader:
            count = sum(1 for _ in reader)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count > 100_000
    assert peak < 64 * 1024 * 1024
