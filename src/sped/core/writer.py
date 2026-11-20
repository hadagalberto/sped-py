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
from sped.core.types import Layout, Record

OutputRecord: TypeAlias = tuple[str, tuple[str, ...]]


def format_line(code: str, values: Iterable[str]) -> str:
    """Format a register code and its raw values as ``|REG|...|``.

    ``|`` is the field delimiter defined by the SPED layout, so it cannot be
    part of a register code or of a value: accepting it would silently emit a
    file whose fields are shifted by one.
    """
    fields = (code, *values)
    if any("|" in field for field in fields):
        raise ValueError("caractere '|' não pode aparecer dentro de registro ou valor")
    return "|" + "|".join(fields) + "|"


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

    def __init__(
        self,
        sink: BinaryIO,
        encoding: str,
        line_ending: str,
        recompute: bool,
        layout: Layout | None,
    ) -> None:
        self.sink = sink
        self.encoding = encoding
        self.line_ending = line_ending
        self.recompute = recompute
        #: When a layout is known, never emit a structural register that the
        #: official table does not define (e.g. ECF leiaute 12 has no S990).
        self.available = frozenset(layout.registers) if layout is not None else None
        self.layout = layout
        self.counts: Counter[str] = Counter()
        #: Register codes in order of first appearance (dict insertion order).
        self.order: list[str] = []
        self.total_lines = 0
        self.block = ""
        self.block_count = 0
        self.has_9001 = False

    def _exists(self, code: str) -> bool:
        return self.available is None or code in self.available

    def _count(self, code: str) -> None:
        """Count one occurrence, remembering where the code first appeared."""
        if code not in self.counts:
            self.order.append(code)
        self.counts[code] += 1

    def emit_struct(self, code: str, values: tuple[str, ...]) -> None:
        """Emit a generated structural record, padding optional trailing fields.

        ECF's 9900, for instance, officially defines five fields (the last two
        are filled only for dynamic tables); static counts leave them empty.
        """
        if self.layout is not None and code in self.layout.registers:
            expected = len(self.layout.register(code).fields) - 1
            values = values + ("",) * max(0, expected - len(values))
        self.emit(code, values)

    def emit(self, code: str, values: Iterable[str]) -> None:
        line = format_line(code, values)
        self.sink.write(line.encode(self.encoding) + self.line_ending.encode(self.encoding))
        self.total_lines += 1

    def close_block(self) -> None:
        if not self.block or self.block_count == 0:
            self.block = ""
            return
        closing = f"{self.block}990"
        if self._exists(closing):
            self.emit_struct(closing, (str(self.block_count + 1),))
            self._count(closing)
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
            self._count(code)
            return
        if is_block_closing(code) and self._exists(code):
            self.emit_struct(code, (str(self.block_count + 1),))
            self._count(code)
            self.block = ""
            self.block_count = 0
            return
        current = _block_of(code)
        if self.block and current != self.block:
            self.close_block()
        self.block = current
        self.block_count += 1
        self._count(code)
        self.emit(code, values)

    def finish(self) -> None:
        if not self.recompute:
            return
        self.close_block()
        if not self.has_9001 and self._exists("9001"):
            self.emit_struct("9001", ())
            self._count("9001")
        # Guia Prático EFD ICMS/IPI v3.2.4, registro 9900: "Todos os registros
        # referenciados neste arquivo, inclusive os posteriores a este
        # registro, devem ter uma linha totalizadora". Isso inclui o próprio
        # 9900, o 9990 e o 9999. Manual da ECF (bloco 9) é explícito quanto a
        # 9900/9990/9999.
        for code in ("9900", "9990", "9999"):
            if self._exists(code):
                self._count(code)
        if self._exists("9900"):
            # Cada tipo de registro (inclusive 9900) tem exatamente uma linha.
            self.counts["9900"] = len(self.order)
            for code in self.order:
                self.emit_struct("9900", (code, str(self.counts[code])))
        if self._exists("9990"):
            # 9990.QTD_LIN_9 = linhas 9900 + abertura 9001 + o próprio 9990 +
            # o 9999 (o Guia determina que o 9999 entra na soma embora não
            # pertença ao bloco 9).
            block9_count = (
                len(self.order)
                + self.counts.get("9001", 0)
                + self.counts.get("9990", 0)
                + self.counts.get("9999", 0)
            )
            self.emit_struct("9990", (str(block9_count),))
        if self._exists("9999"):
            self.emit_struct("9999", (str(self.total_lines + 1),))


def write(
    records: Iterable[Record | OutputRecord | str],
    destination: str | Path | BinaryIO,
    *,
    encoding: str = "latin-1",
    line_ending: str = "\r\n",
    recompute: bool = True,
    layout: Layout | None = None,
) -> int:
    """Write SPED records to ``destination`` and return the line count.

    When ``recompute`` is true (default), x990 closings, the 9900 register
    list and the 9999 total are recalculated from the records themselves.
    Existing closing/total records in ``records`` are ignored and replaced.

    When ``layout`` is supplied, no structural register outside the official
    table is emitted (needed for layouts such as ECF where some blocks have
    no ``x990`` closing).
    """
    with ExitStack() as stack:
        sink: BinaryIO
        if not hasattr(destination, "write"):
            sink = stack.enter_context(Path(str(destination)).open("wb"))
        else:
            sink = destination  # type: ignore[assignment]
        state = _TotalsWriter(sink, encoding, line_ending, recompute, layout)
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
    layout: Layout | None = None,
) -> Iterator[str]:
    """Yield the formatted lines that :func:`write` would emit (useful in tests)."""
    buffer = BytesIO()
    write(records, buffer, encoding=encoding, line_ending=line_ending, layout=layout)
    yield from buffer.getvalue().decode(encoding).splitlines()
