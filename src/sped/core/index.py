"""Optional on-disk index for random access by register.

The index is a sidecar binary file (``<arquivo>.spedidx`` by default). It is
built in one streaming pass and stores, for every register code, the line
numbers and byte offsets of its lines. A lookup then seeks directly to the
relevant lines instead of rescanning a multi-gigabyte file.

Format (all integers big-endian)::

    b"SPEDIDX1"            magic
    uint32                 length of JSON header
    JSON header            UTF-8: source fingerprint, encoding, layout and a
                           ``sections`` map ``code -> [data offset, count]``
    per section, ``count`` x (uint64 line_no, uint64 byte_offset)

The source fingerprint (size and mtime) makes stale indexes fail loudly rather
than return wrong records.
"""

from __future__ import annotations

import json
import struct
from collections import defaultdict
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from sped.core.encoding import detect_encoding, is_signature_line, split_line
from sped.core.reader import parse_record
from sped.core.types import Layout, Record
from sped.layouts import detect_layout

MAGIC: bytes = b"SPEDIDX1"
FORMAT_VERSION: int = 1
_ENTRY = struct.Struct(">QQ")
_U32 = struct.Struct(">I")


def default_index_path(path: str | Path) -> Path:
    """Return the default sidecar path for a SPED file."""
    source = Path(path)
    return source.with_name(source.name + ".spedidx")


def _validate_header(header: dict[str, Any]) -> None:
    if header.get("format_version") != FORMAT_VERSION:
        raise ValueError("versão de índice incompatível")
    if not isinstance(header.get("sections"), dict):
        raise ValueError("índice sem seções de registros")


def build_index(
    path: str | Path,
    destination: str | Path | None = None,
    *,
    layout: Layout | None = None,
    encoding: str | None = None,
) -> Path:
    """Scan ``path`` once and write an index; return the index path.

    ``layout`` is stored in the header so lookups can parse records without
    guessing a version. When omitted the layout is detected from the file.
    """
    source = Path(path)
    target = Path(destination) if destination is not None else default_index_path(source)
    chosen_layout = layout or detect_layout(source)
    stat = source.stat()
    with source.open("rb") as handle:
        chosen_encoding = encoding or detect_encoding(handle.read(8192))

    positions: dict[str, list[tuple[int, int]]] = defaultdict(list)
    line_no = 0
    with source.open("rb") as handle:
        while True:
            offset = handle.tell()
            raw = handle.readline()
            if not raw:
                break
            text = raw.decode(chosen_encoding).rstrip("\r\n")
            if is_signature_line(text):
                break
            line_no += 1
            if not text.strip():
                continue
            try:
                split = split_line(text)
            except ValueError:
                continue
            if split is None:
                continue
            positions[split[0]].append((line_no, offset))

    header: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "source": str(source.resolve()),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "encoding": chosen_encoding,
        "obrigacao": chosen_layout.obrigacao,
        "cod_ver": chosen_layout.cod_ver,
        "sections": {},
    }
    sections: dict[str, list[int]] = {}
    payload = bytearray()
    for code in sorted(positions):
        entries = positions[code]
        sections[code] = [len(payload), len(entries)]
        for number, entry_offset in entries:
            payload.extend(_ENTRY.pack(number, entry_offset))
    header["sections"] = sections
    header_bytes = json.dumps(header, ensure_ascii=False, sort_keys=True).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("wb") as sink:
        sink.write(MAGIC)
        sink.write(_U32.pack(len(header_bytes)))
        sink.write(header_bytes)
        sink.write(payload)
    temporary.replace(target)
    return target


class SpedIndex:
    """Open index; use :meth:`records` for direct access to one register type."""

    def __init__(
        self, path: str | Path, header: dict[str, Any], source: Path, data_base: int
    ) -> None:
        self.path = Path(path)
        self.header = header
        self.source = source
        self._data_base = data_base

    @classmethod
    def open(
        cls,
        path: str | Path,
        source: str | Path | None = None,
        *,
        validate: bool = True,
    ) -> SpedIndex:
        """Open and validate an existing index."""
        index_path = Path(path)
        with index_path.open("rb") as handle:
            if handle.read(len(MAGIC)) != MAGIC:
                raise ValueError("arquivo não é um índice SPED")
            length = _U32.unpack(handle.read(_U32.size))[0]
            header_bytes = handle.read(length)
            header = json.loads(header_bytes.decode("utf-8"))
        _validate_header(header)
        data_base = len(MAGIC) + _U32.size + len(header_bytes)
        source_path = Path(source) if source is not None else Path(header["source"])
        if validate and source_path.exists():
            stat = source_path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (
                header["source_size"],
                header["source_mtime_ns"],
            ):
                raise ValueError("índice desatualizado: o arquivo SPED mudou desde a geração")
        return cls(index_path, header, source_path, data_base)

    def codes(self) -> tuple[str, ...]:
        """Return every register code present in the index."""
        return tuple(sorted(self.header["sections"]))

    def count(self, code: str) -> int:
        """Return the number of indexed lines of ``code`` (0 when absent)."""
        section = self.header["sections"].get(code)
        return int(section[1]) if section else 0

    def __contains__(self, code: object) -> bool:
        return code in self.header["sections"]

    def offsets(self, code: str) -> Iterator[tuple[int, int]]:
        """Yield ``(line_no, byte_offset)`` pairs for ``code``."""
        section = self.header["sections"].get(code)
        if not section:
            return
        start, count = self._data_base + int(section[0]), int(section[1])
        with self.path.open("rb") as handle:
            handle.seek(start)
            for _ in range(count):
                yield _ENTRY.unpack(handle.read(_ENTRY.size))

    def records(
        self,
        code: str,
        layout: Layout,
        *,
        strict: bool = True,
    ) -> Iterator[Record]:
        """Yield parsed records of ``code`` by seeking directly to their lines."""
        encoding = str(self.header["encoding"])
        with ExitStack() as stack:
            handle = stack.enter_context(self.source.open("rb"))
            for line_no, offset in self.offsets(code):
                handle.seek(offset)
                raw_bytes = handle.readline()
                text = raw_bytes.decode(encoding).rstrip("\r\n")
                split = split_line(text)
                if split is None:
                    continue
                record = parse_record(
                    line_no,
                    code,
                    split[1],
                    text,
                    layout,
                    strict=strict,
                )
                if record is not None:
                    yield record


class IndexedReader:
    """Convenience reader with random access backed by :class:`SpedIndex`.

    The index is created on first use when no valid sidecar exists.
    """

    def __init__(
        self,
        path: str | Path,
        layout: Layout | None = None,
        *,
        index_path: str | Path | None = None,
        encoding: str | None = None,
        strict: bool = True,
    ) -> None:
        self.path = Path(path)
        self.layout = layout or detect_layout(self.path)
        self.index_path = (
            Path(index_path) if index_path is not None else default_index_path(self.path)
        )
        self.strict = strict
        self.index: SpedIndex | None = None
        self._encoding = encoding

    def _open(self) -> SpedIndex:
        if self.index is None:
            try:
                self.index = SpedIndex.open(self.index_path, self.path)
            except (OSError, ValueError, KeyError):
                build_index(
                    self.path,
                    self.index_path,
                    layout=self.layout,
                    encoding=self._encoding,
                )
                self.index = SpedIndex.open(self.index_path, self.path)
        return self.index

    def by_type(self, code: str) -> Iterator[Record]:
        """Yield records of ``code`` using the on-disk index."""
        return self._open().records(code, self.layout, strict=self.strict)

    def get(self, code: str) -> tuple[Record, ...]:
        """Return all records of ``code`` as a tuple."""
        return tuple(self.by_type(code))

    def count(self, code: str) -> int:
        """Return the indexed number of lines of ``code``."""
        return self._open().count(code)
