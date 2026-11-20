"""Divide um arquivo SPED em arquivos válidos por período.

Cada parte recebe um ``0000`` com ``DT_INI``/``DT_FIN`` do recorte, os registros
de cadastro que não possuem data (replicados em todas as partes), os documentos
cuja data pertence ao recorte e os registros de apuração (blocos E e M), que são
replicados e recalculados para que cada parte seja autoconsistente.
Os totais estruturais são recalculados pelo escritor.

Fonte dos campos de data: tabelas oficiais de leiaute (``sped.layouts``);
a convenção ``DDMMAAAA`` está documentada em ``sped.core.types.FieldDef``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path

from sped.analysis._records import (
    CONTROL_CODES,
    get_field,
    is_closing,
    is_opener,
    raw_without_register,
    record_date,
    set_field,
)
from sped.analysis.apuracao import recompute_apuracao
from sped.analysis.periods import Period, format_date, split_periods
from sped.core.reader import SpedReader
from sped.core.types import Layout, Record
from sped.core.writer import OutputRecord, write
from sped.layouts import detect_layout

#: Blocos cujos registros resumem a apuração inteira; replicados nas partes.
_APPRAISAL_BLOCKS: dict[str, str] = {
    "efd_icmsipi": "E",
    "efd_contribuicoes": "M",
}


def _header(layout: Layout, source: Path) -> OutputRecord:
    with SpedReader(source, layout=layout, strict=False) as reader:
        record = next(iter(reader.iter_records()), None)
    if record is None or record.code != "0000":
        raise ValueError(f"{source}: arquivo sem registro 0000")
    return record.code, tuple(raw_without_register(record))


def _openers(layout: Layout, source: Path) -> dict[str, OutputRecord]:
    """Primeiro registro x001 de cada bloco, na ordem do arquivo."""
    result: dict[str, OutputRecord] = {}
    with SpedReader(source, layout=layout, strict=False) as reader:
        for record in reader.iter_records():
            if is_opener(record.code) and record.code != "9001" and record.code not in result:
                result[record.code] = (record.code, tuple(raw_without_register(record)))
    return result


def _period_index(periods: tuple[Period, ...], value: date) -> int:
    for index, period in enumerate(periods):
        if period.contains(value):
            return index
    return 0 if value < periods[0].start else len(periods) - 1


def _in_period(  # noqa: PLR0917
    record: Record,
    layout: Layout,
    periods: tuple[Period, ...],
    index: int,
    current: date | None,
    appraisal_block: str | None,
) -> bool:
    if appraisal_block is not None and record.code.startswith(appraisal_block):
        return True
    own_date = record_date(record, layout)
    effective = own_date or current
    if effective is None:
        return True
    return _period_index(periods, effective) == index


def _part_records(  # noqa: PLR0917
    source: Path,
    chosen: Layout,
    part_header: OutputRecord,
    periods: tuple[Period, ...],
    index: int,
    openers: dict[str, OutputRecord],
    appraisal_block: str | None,
) -> Iterable[OutputRecord]:
    """Registros de uma parte, em streaming, com aberturas de bloco reconstruídas."""
    yield part_header
    emitted_blocks: set[str] = set()
    current: date | None = None
    with SpedReader(source, layout=chosen, strict=False) as reader:
        for record in reader.iter_records():
            code = record.code
            if code == "9001":
                # Preserva campos obrigatórios que o escritor não pode inferir.
                yield code, tuple(raw_without_register(record))
                continue
            if is_opener(code) or is_closing(code):
                # Fim/abertura de bloco encerra o documento corrente.
                current = None
                continue
            if code in CONTROL_CODES:
                continue
            if code in {"C100", "D100", "I150"}:
                own = record_date(record, chosen)
                if own is not None:
                    current = own
            if not _in_period(record, chosen, periods, index, current, appraisal_block):
                continue
            block = code[0]
            if block not in emitted_blocks and f"{block}001" in openers:
                emitted_blocks.add(block)
                yield openers[f"{block}001"]
            yield code, tuple(raw_without_register(record))
    # Blocos sem dokumentos nesta parte ainda existem no arquivo original;
    # o escritor gera o x990 correspondente a partir da abertura.
    for opener_code, opener in openers.items():
        if opener_code[0] not in emitted_blocks:
            emitted_blocks.add(opener_code[0])
            yield opener


def split_file(
    path: str | Path,
    destination_dir: str | Path,
    *,
    by: str = "month",
    layout: Layout | None = None,
    refresh: bool = True,
) -> tuple[Path, ...]:
    """Divide ``path`` em um arquivo por período e devolve os caminhos gravados."""
    source = Path(path)
    chosen = layout or detect_layout(source)
    header = _header(chosen, source)
    periods = split_periods(
        get_field(header, chosen, "DT_INI"), get_field(header, chosen, "DT_FIN"), by
    )
    if not periods:
        raise ValueError("nenhum período resultante da divisão")
    openers = _openers(chosen, source)
    appraisal_block = _APPRAISAL_BLOCKS.get(chosen.obrigacao)
    output_dir = Path(destination_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for index, period in enumerate(periods):
        target = output_dir / f"{source.stem}_{period.code}.txt"
        part_header = set_field(
            set_field(header, chosen, "DT_INI", format_date(period.start)),
            chosen,
            "DT_FIN",
            format_date(period.end),
        )
        write(
            _part_records(source, chosen, part_header, periods, index, openers, appraisal_block),
            target,
            layout=chosen,
        )
        if refresh and chosen.obrigacao in {"efd_icmsipi", "efd_contribuicoes"}:
            recompute_apuracao(target, target, layout=chosen)
        written.append(target)
    return tuple(written)
