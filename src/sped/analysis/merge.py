"""Mescla arquivos SPED do mesmo leiaute em um único arquivo por período.

Os arquivos de entrada devem pertencer à mesma obrigação e ao mesmo ``COD_VER``.
O ``0000`` do resultado cobre o menor ``DT_INI`` e o maior ``DT_FIN``; registros
de abertura/encerramento de bloco e os registros de controle (9001, 9900, 9990,
9999) são gerados uma única vez pelo escritor. Por padrão os campos de apuração
são recalculados a partir dos detalhes mesclados (ver ``analysis.apuracao``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from sped.analysis._records import (
    CONTROL_CODES,
    get_field,
    is_closing,
    is_opener,
    raw_without_register,
    set_field,
)
from sped.analysis.apuracao import recompute_apuracao
from sped.analysis.periods import parse_date
from sped.core.reader import SpedReader
from sped.core.types import Layout
from sped.core.writer import OutputRecord, write
from sped.layouts import detect_layout

#: Registros únicos ou cadastros: ``()`` mantém só o primeiro; campos nomeados
#: formam a chave de deduplicação (nomes publicados no leiaute oficial).
_DEDUP_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "0005": (),
    "0100": (),
    "0110": (),
    "0150": ("COD_PART",),
    "0190": ("UNID",),
    "0200": ("COD_ITEM",),
    "E100": (),
    "E110": (),
    "M200": (),
    "M600": (),
    "I010": (),
    "I050": (),
}


def _header(path: Path, layout: Layout) -> OutputRecord:
    with SpedReader(path, layout=layout, strict=False) as reader:
        record = next(iter(reader.iter_records()), None)
    if record is None or record.code != "0000":
        raise ValueError(f"{path}: arquivo sem registro 0000")
    return record.code, tuple(raw_without_register(record))


def merge_files(
    paths: Sequence[str | Path],
    destination: str | Path,
    *,
    layout: Layout | None = None,
    refresh: bool = True,
) -> Path:
    """Mescla ``paths`` em ``destination`` e devolve o caminho gravado."""
    sources = [Path(path) for path in paths]
    if not sources:
        raise ValueError("ao menos um arquivo deve ser informado")
    chosen = layout or detect_layout(sources[0])
    for source in sources[1:]:
        other = detect_layout(source)
        if (other.obrigacao, other.cod_ver) != (chosen.obrigacao, chosen.cod_ver):
            raise ValueError(
                f"leiautes incompatíveis: {source} é {other.obrigacao}/{other.cod_ver}"
            )

    headers = [_header(source, chosen) for source in sources]
    starts = [get_field(header, chosen, "DT_INI") for header in headers]
    ends = [get_field(header, chosen, "DT_FIN") for header in headers]
    if not all(starts) or not all(ends):
        raise ValueError("todo arquivo deve informar DT_INI e DT_FIN no registro 0000")
    first_header = headers[0]
    start = min(starts, key=parse_date)
    end = max(ends, key=parse_date)
    header = set_field(set_field(first_header, chosen, "DT_INI", start), chosen, "DT_FIN", end)

    def records() -> Iterable[OutputRecord]:
        yield header
        seen_openers: set[str] = set()
        seen_dedup: dict[str, set[str]] = {}
        for source in sources:
            with SpedReader(source, layout=chosen, strict=False) as reader:
                for record in reader.iter_records():
                    code = record.code
                    if code in CONTROL_CODES or is_closing(code):
                        continue
                    if is_opener(code):
                        if code in seen_openers:
                            continue
                        seen_openers.add(code)
                    output: OutputRecord = (code, tuple(raw_without_register(record)))
                    keys = _DEDUP_KEYS.get(code)
                    if keys is not None:
                        identity = "|".join(get_field(output, chosen, name) for name in keys)
                        bucket = seen_dedup.setdefault(code, set())
                        if identity in bucket:
                            continue
                        bucket.add(identity)
                    yield output

    target = Path(destination)
    write(records(), target, layout=chosen)
    if refresh and chosen.obrigacao in {"efd_icmsipi", "efd_contribuicoes"}:
        recompute_apuracao(target, target, layout=chosen)
    return target
