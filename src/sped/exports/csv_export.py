"""Exportação streaming para CSV, um arquivo por registro."""

from __future__ import annotations

import csv
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from sped.core.types import Layout
from sped.exports._common import Source, columns, resolve_source


def export_csv(
    source: Source, destination: str | Path, *, layout: Layout | None = None
) -> dict[str, int]:
    """Grava ``<REG>.csv`` para cada registro encontrado e devolve as contagens.

    O cabeçalho usa os nomes de campo publicados no leiaute oficial; os valores
    são exatamente os do arquivo de entrada (sem conversão de tipos).
    """
    chosen, records = resolve_source(source, layout)
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    with ExitStack() as stack:
        writers: dict[str, Any] = {}
        for record in records:
            code = record.code
            if code not in writers:
                handle = stack.enter_context(
                    (target / f"{code}.csv").open("w", encoding="utf-8", newline="")
                )
                writer = csv.writer(handle)
                writer.writerow(columns(chosen, code))
                writers[code] = writer
            writers[code].writerow(record.raw_values)
            counts[code] += 1
    return dict(counts)
