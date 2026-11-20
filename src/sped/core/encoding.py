"""Byte-level handling: encoding detection, line endings and signature stripping.

SPED files are normally ``latin-1`` with CRLF line endings; UTF-8 (with or
without BOM) and bare LF are accepted as required by the SPEC.
"""

from __future__ import annotations

import codecs
from collections.abc import Iterator
from pathlib import Path

#: The marker that starts the appended digital-signature block (SPEC).
SIGNATURE_MARKER: str = "SBMDSIG"

#: Additional markers emitted by some SPED signers.
SIGNATURE_MARKERS: tuple[str, ...] = (
    SIGNATURE_MARKER,
    "-----BEGIN PKCS7-----",
    "-----BEGIN SIGNATURE-----",
    "-----BEGIN CERTIFICATE-----",
)


def detect_encoding(sample: bytes) -> str:
    """Detect the encoding of a SPED file from an initial byte sample.

    UTF-8 BOM wins; otherwise strict UTF-8 is attempted and ``latin-1`` is
    used as the fallback (latin-1 maps every byte, so it never fails).
    """
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # An incremental decoder buffers an incomplete trailing multi-byte sequence
    # instead of rejecting it. A plain ``sample.decode("utf-8")`` misdetects a
    # UTF-8 file as latin-1 whenever the 8192-byte sample happens to cut a
    # character in half (see tests/test_hardening.py).
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(sample)
    except UnicodeDecodeError:
        return "latin-1"
    return "utf-8"


def is_signature_line(line: str) -> bool:
    """True if ``line`` belongs to the appended signature block."""
    stripped = line.strip().lstrip("\ufeff").upper()
    # Some signers frame the marker as ``|SBMDSIG|...|`` instead of writing it
    # bare. Both forms belong to the appended signature block and must be
    # stripped (a 7-character token is never a valid SPED register code).
    if stripped.startswith("|"):
        stripped = stripped[1:]
    return any(stripped.startswith(marker) for marker in SIGNATURE_MARKERS)


def iter_lines(path: str | Path, encoding: str | None = None) -> Iterator[str]:
    """Yield physical lines of a SPED file without signature or line endings.

    Handles CRLF, LF and (defensively) lone CR.  The signature block, once
    started, consumes the remainder of the file and is not yielded.
    """
    with Path(path).open("rb") as handle:
        first_chunk = handle.read(8192)
        handle.seek(0)
        chosen = encoding or detect_encoding(first_chunk)
        decoder = codecs.getincrementaldecoder(chosen)()
        buffer = ""
        in_signature = False
        while chunk := handle.read(65536):
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                raw, buffer = buffer.split("\n", 1)
                line = raw[:-1] if raw.endswith("\r") else raw
                if in_signature or is_signature_line(line):
                    in_signature = True
                    continue
                yield line
        buffer += decoder.decode(b"", final=True)
        if buffer and not in_signature and not is_signature_line(buffer):
            yield buffer[:-1] if buffer.endswith("\r") else buffer


def split_line(line: str) -> tuple[str, tuple[str, ...]] | None:
    """Split a ``|REG|v1|v2|`` line into its register code and raw values.

    Returns ``None`` for blank lines and raises :class:`ValueError` when the
    pipe framing is broken.
    """
    if not line.strip():
        return None
    if not line.startswith("|") or not line.endswith("|"):
        raise ValueError(f"linha sem delimitadores '|' nas extremidades: {line[:60]!r}")
    parts = line.split("|")
    code = parts[1]
    if len(code) != 4 or not code.isalnum():
        raise ValueError(f"código de registro inválido: {code!r}")
    return code, tuple(parts[2:-1])
