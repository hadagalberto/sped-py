"""Comparação estrutural entre dois arquivos SPED (original x retificadora).

A comparação usa ``difflib.SequenceMatcher`` sobre a sequência de registros
``(código, valores brutos)``. Isso alinha inserções e remoções de linhas em vez
de tratá-las como alterações em cascata — essencial para retificadoras. O
resultado distingue registros ``added``, ``removed`` e ``changed`` e carrega os
números de linha de ambos os arquivos.

Este é um utilitário de análise offline: ao contrário do reader, materializa os
registros dos dois arquivos para poder alinhá-los. Para arquivos de vários GB,
compare recortes por período (``sped split``) antes de usar ``diff``.

Fonte das regras de estrutura/retificação: Guia Prático da EFD ICMS/IPI v3.2.4,
registro 0000 (campo RETIFICADORA quando aplicável) — URL em
``sped.validation.rules.GUIDA_ICMS``.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from sped.core.encoding import iter_lines, split_line

Line = tuple[str, tuple[str, ...]]
_Fingerprint = tuple[str, tuple[str, ...]]


def _records(path: str | Path) -> list[Line]:
    """Lê os registros de ``path`` ignorando linhas vazias e assinaturas."""
    result: list[Line] = []
    for line_no, raw in enumerate(iter_lines(path), start=1):
        split = split_line(raw)
        if split is not None:
            result.append((f"{line_no}:{split[0]}", split[1]))
    return result


@dataclass(frozen=True, slots=True)
class DiffEntry:
    """Uma diferença alinhada entre os dois arquivos."""

    kind: str
    line_no: int
    other_line_no: int
    code: str
    left: tuple[str, ...] | None
    right: tuple[str, ...] | None

    def as_dict(self) -> dict[str, object]:
        """Representação serializável."""
        return {
            "tipo": self.kind,
            "linha_a": self.line_no,
            "linha_b": self.other_line_no,
            "registro": self.code,
            "a": list(self.left) if self.left is not None else None,
            "b": list(self.right) if self.right is not None else None,
        }


@dataclass(frozen=True, slots=True)
class FileDiff:
    """Resumo das diferenças entre dois arquivos."""

    a: str
    b: str
    added: int
    removed: int
    changed: int
    entries: tuple[DiffEntry, ...]

    @property
    def has_differences(self) -> bool:
        """True quando há qualquer diferença."""
        return bool(self.added or self.removed or self.changed)

    def as_dict(self) -> dict[str, object]:
        """Representação serializável (JSON/CLI)."""
        return {
            "a": self.a,
            "b": self.b,
            "adicionados": self.added,
            "removidos": self.removed,
            "alterados": self.changed,
            "diferencas": self.has_differences,
            "detalhes": [entry.as_dict() for entry in self.entries],
        }


def _location(label: str) -> tuple[int, str]:
    number_text, _, code = label.partition(":")
    return int(number_text), code


def diff_files(a: str | Path, b: str | Path, *, limit: int = 20) -> FileDiff:  # noqa: PLR0912
    """Alinha e compara dois arquivos SPED.

    ``limit`` restringe quantas entradas individuais são mantidas no resultado;
    as contagens sempre refletem o arquivo inteiro. Use ``limit=0`` para não
    manter detalhes.
    """
    if limit < 0:
        raise ValueError("limit não pode ser negativo")
    left = _records(a)
    right = _records(b)
    left_fingerprints: list[_Fingerprint] = [
        (label.split(":", 1)[1], values) for label, values in left
    ]
    right_fingerprints: list[_Fingerprint] = [
        (label.split(":", 1)[1], values) for label, values in right
    ]
    matcher = difflib.SequenceMatcher(None, left_fingerprints, right_fingerprints, autojunk=False)
    entries: list[DiffEntry] = []

    def add(kind: str, left_index: int | None, right_index: int | None) -> None:
        if limit == 0 or len(entries) >= limit:
            return
        left_label = left[left_index][0] if left_index is not None else ""
        right_label = right[right_index][0] if right_index is not None else ""
        left_line, left_code = _location(left_label) if left_label else (0, "")
        right_line, right_code = _location(right_label) if right_label else (0, "")
        code = right_code or left_code
        entries.append(
            DiffEntry(
                kind=kind,
                line_no=left_line,
                other_line_no=right_line,
                code=code,
                left=left[left_index][1] if left_index is not None else None,
                right=right[right_index][1] if right_index is not None else None,
            )
        )

    added = removed = changed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            pairs = min(i2 - i1, j2 - j1)
            for offset in range(pairs):
                li, ri = i1 + offset, j1 + offset
                if left[li][0].split(":", 1)[1] == right[ri][0].split(":", 1)[1]:
                    changed += 1
                    add("changed", li, ri)
                else:
                    removed += 1
                    added += 1
                    add("removed", li, None)
                    add("added", None, ri)
            for index in range(i1 + pairs, i2):
                removed += 1
                add("removed", index, None)
            for index in range(j1 + pairs, j2):
                added += 1
                add("added", None, index)
        elif tag == "delete":
            removed += i2 - i1
            for index in range(i1, i2):
                add("removed", index, None)
        elif tag == "insert":
            added += j2 - j1
            for index in range(j1, j2):
                add("added", None, index)

    return FileDiff(
        a=str(a),
        b=str(b),
        added=added,
        removed=removed,
        changed=changed,
        entries=tuple(entries),
    )
