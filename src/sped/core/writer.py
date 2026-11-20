"""SPED writer with automatic recomputation of x990/9900/9999 totals.

The writer streams: data records are emitted as they arrive, only one pending
closing record and the (bounded) per-register counter are held in memory.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, TypeAlias

from sped.core.encoding import split_line
from sped.core.types import Record

OutputRecord: TypeAlias = tuple[str, tuple[str, ...]]


def format_line(code: str, values: Iterable[str]) -> str:
    """Format a register code and its raw values as ``|REG|...|``."""
    return "|" + "|".join((code, *values)) + "|"


def as_output(record: Record | OutputRecord | str) -> OutputRecord:
    """Normalise a record, ``(code, values)`` pair or raw line to an output pair."""
    if isinstance(record, str):
        split = split_line(record)
        if split is None:
            raise ValueError("linha vazia não pode ser escrita")
        return split
    if isinstance(record, Record):
        values = record.raw_values
        if values and values[0] == record.code:
            values = values[1:]
        return record.code, values
    return record[0], tuple(record[1])


def is_block_closing(code: str) -> bool:
    """True for ``0990``, ``B990`` … ``K990``, ``1990`` (not ``9990``)."""
    return len(code) == 4 and code.endswith("990") and code != "9990"


def _block_of(code: str) -> str:
    return code[0]


class _TotalsWriter:
    """Internal streaming state machine used by :func:`write`."""

    def __init__(self, sink: BinaryIO, encoding: str, line_ending: str, recompute: bool) -> None:
        self.sink = sink
        self.encoding = encoding
        self.line_ending = line_ending
        self.recompute = recompute
        self.counts: Counter[str] = Counter()
        self.total_lines = 0
        self.block = ""
        self.block_count = 0
        self.has_9001 = False

    def emit(self, code: str, values: Iterable[str]) -> None:
        line = format_line(code, values)
        self.sink.write(line.encode(self.encoding) + self.line_ending.encode(self.encoding))
        self.total_lines += 1

    def close_block(self) -> None:
        if not self.block or self.block_count == 0:
            self.block = ""
            return
        closing = f"{self.block}990"
        self.emit(closing, (str(self.block_count + 1),))
        self.counts[closing] += 1
        self.block = ""
        self.block_count = 0

    def feed(self, code: str, values: tuple[str, ...]) -> None:
        if not self.recompute:
            self.emit(code, values)
            return
        if code in {"9900", "9990", "9999"}:
            return
        if code == "9001":
            self.has_9001 = True
            self.emit(code, values)
            self.counts[code] += 1
            return
        if is_block_closing(code):
            self.emit(code, (str(self.block_count + 1),))
            self.counts[code] += 1
            self.block = ""
            self.block_count = 0
            return
        current = _block_of(code)
        if self.block and current != self.block:
            self.close_block()
        self.block = current
        self.block_count += 1
        self.counts[code] += 1
        self.emit(code, values)

    def finish(self) -> None:
        if not self.recompute:
            return
        self.close_block()
        if not self.has_9001:
            self.emit("9001", ())
            self.counts["9001"] += 1
        self.counts["9990"] = 1
        for code in sorted(self.counts):
            if code in {"9900", "9999"}:
                continue
            self.emit("9900", (code, str(self.counts[code])))
        block9_count = 1 + len([c for c in self.counts if c not in {"9900", "9999"}]) + 1
        self.emit("9990", (str(block9_count),))
        self.emit("9999", (str(self.total_lines + 1),))


def write(
    records: Iterable[Record | OutputRecord | str],
    destination: str | Path | BinaryIO,
    *,
    encoding: str = "latin-1",
    line_ending: str = "\r\n",
    recompute: bool = True,
) -> int:
    """Write SPED records to ``destination`` and return the line count.

    When ``recompute`` is true (default), x990 closings, the 9900 register
    list and the 9999 total are recalculated from the records themselves.
    Existing closing/total records in ``records`` are ignored and replaced.
    """
    with ExitStack() as stack:
        sink: BinaryIO
        if not hasattr(destination, "write"):
            sink = stack.enter_context(Path(str(destination)).open("wb"))
        else:
            sink = destination  # type: ignore[assignment]
        state = _TotalsWriter(sink, encoding, line_ending, recompute)
        for record in records:
            code, values = as_output(record)
            state.feed(code, values)
        state.finish()
        return state.total_lines


def write_iter(
    records: Iterable[Record | OutputRecord | str],
    *,
    encoding: str = "latin-1",
    line_ending: str = "\r\n",
) -> Iterator[str]:
    """Yield the formatted lines that :func:`write` would emit (useful in tests)."""
    buffer = BytesIO()
    write(records, buffer, encoding=encoding, line_ending=line_ending)
    yield from buffer.getvalue().decode(encoding).splitlines()
