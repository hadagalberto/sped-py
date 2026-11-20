from __future__ import annotations

import sys
import time
import tracemalloc
from pathlib import Path

import pytest

from sped.core.reader import read
from sped.core.writer import OutputRecord, write
from sped.factories.synthetic import build_records
from sped.layouts import load_layout

#: Limite generoso: qualquer máquina moderna supera isso em streaming sequencial.
#: Serve para detectar regressões graves (ex.: carregar o arquivo inteiro na RAM).
MIN_THROUGHPUT_MB_S = 1.0
_TRACER_SLOWDOWN = 5


def _write_template(path: Path, repetitions: int) -> int:
    template: OutputRecord = next(record for record in build_records() if record[0] == "C170")
    line = ("|" + "|".join(("C170", *template[1])) + "|\r\n").encode("latin-1")
    with path.open("wb") as handle:
        for _ in range(repetitions):
            handle.write(line)
    return repetitions * len(line)


def _traced_peak(path: Path, stop_after: int | None = None) -> tuple[int, int]:
    """Conta registros e mede pico de memória com tracemalloc."""
    peak = 0
    count = 0
    tracemalloc.start()
    try:
        with read(path, layout=load_layout("020"), strict=False) as reader:
            for _record in reader:
                count += 1
                if stop_after is not None and count == stop_after:
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    stop_after = None
        if tracemalloc.is_tracing():
            _, peak = tracemalloc.get_traced_memory()
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
    return count, peak


def _throughput(path: Path, size: int) -> tuple[int, float]:
    """Segunda passada sem tracemalloc: tempo de leitura representativo."""
    started = time.perf_counter()
    with read(path, layout=load_layout("020"), strict=False) as reader:
        count = sum(1 for _ in reader)
    elapsed = time.perf_counter() - started
    return count, size / elapsed / 1024 / 1024


def test_flat_memory_small_stream(tmp_path: Path) -> None:
    """Constant-memory guarantee at a scale that runs on every CI job."""
    template: OutputRecord = next(record for record in build_records() if record[0] == "C170")
    path = tmp_path / "large.txt"
    with path.open("ab") as handle:
        write([template] * 20_000, handle, recompute=False)

    count, peak = _traced_peak(path)
    assert count == 20_000
    assert peak < 32 * 1024 * 1024


def test_throughput_bound(tmp_path: Path) -> None:
    """Throughput generoso em volume que cabe na suíte padrão (~9 MB)."""
    path = tmp_path / "throughput.txt"
    size = _write_template(path, 50_000)
    count, throughput = _throughput(path, size)
    assert count == 50_000
    minimum = MIN_THROUGHPUT_MB_S
    # The default suite runs under pytest-cov, whose line tracer slows pure
    # Python several-fold (0.6 MB/s seen on a shared CI runner). Scale the
    # bound when a tracer is active so this catches regressions, not noise.
    if sys.gettrace() is not None:
        minimum /= _TRACER_SLOWDOWN
    assert throughput > minimum, f"throughput {throughput:.1f} MB/s (min {minimum})"


@pytest.mark.slow
def test_one_gigabyte_stream(tmp_path: Path) -> None:
    """Opt-in 1 GB: memória plana sob tracemalloc e vazão generosa (`-m slow`)."""
    path = tmp_path / "one_gb.txt"
    target_bytes = 1_000_000_000
    template: OutputRecord = next(record for record in build_records() if record[0] == "C170")
    line = "|" + "|".join(("C170", *template[1])) + "|\r\n"
    repetitions = target_bytes // len(line.encode("latin-1")) + 1
    with path.open("wb") as handle:
        for _ in range(repetitions):
            handle.write(line.encode("latin-1"))
            if handle.tell() >= target_bytes:
                break
    size = path.stat().st_size

    # tracemalloc torna a leitura uma ordem de grandeza mais lenta; mede o pico
    # numa amostra representativa e a vazão numa passada íntegra sem tracing.
    traced_count, peak = _traced_peak(path, stop_after=200_000)
    assert traced_count > 100_000
    assert peak < 64 * 1024 * 1024
    count, throughput = _throughput(path, size)
    assert count > 100_000
    assert throughput > MIN_THROUGHPUT_MB_S, f"throughput {throughput:.1f} MB/s"
