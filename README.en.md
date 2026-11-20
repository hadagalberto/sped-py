# sped-py

Pure-Python streaming reader, validator and writer for Brazilian SPED digital
bookkeeping files (EFD ICMS/IPI, EFD-Contribuições, ECD and ECF).

- Python ≥ 3.10, **zero required dependencies**.
- Versioned layouts generated from official Portal SPED / CONFAZ tables for
  every obligation and version from 2019 on: EFD ICMS/IPI (013–021),
  EFD-Contribuições (005–006), ECD (008–009) and ECF (006–012).
- Lazy record hierarchy with published levels and an optional on-disk index
  for random access by register.
- `Decimal` for monetary values, `DDMMAAAA` dates converted to `date`.
- CLI `sped` with `info`, `validate`, `export`, `diff` and `fix-totals`.

> Totals (`x990`, `9900`, `9999`) are recomputed by the writer. Never trust
> totals from an incoming file without validating it.

## Install

```bash
pip install -e .
pip install -e '.[pandas]'  # DataFrame/parquet export
```

## Quick start

```python
from sped import read, write, load_layout

with read("efd.txt") as f:
    for record in f:
        print(record.line_no, record.code, record.values)

layout = load_layout("020")
print(layout.versao, layout.source_url)

with read("efd.txt") as source:
    write(source, "fixed.txt")

# Obligation and COD_VER are auto-detected (ECD uses I010.COD_VER_LC).
from sped.layouts import detect_layout

print(detect_layout("efd.txt").obrigacao)
```

## CLI

```bash
sped info efd.txt
sped validate efd.txt --json
sped export efd.txt --to csv out/
sped diff original.txt amended.txt
sped fix-totals efd.txt -o fixed.txt
```

## Hierarchy and index

```python
from sped.core.hierarchy import RecordTree
from sped.core.index import IndexedReader, build_index
from sped.core.reader import read

with read("arquivo.txt") as source:
    for entry in RecordTree(source, source.layout).iter_entries():
        print(entry.line_no, entry.code, entry.level, entry.parent)

build_index("arquivo.txt")  # writes arquivo.txt.spedidx
for record in IndexedReader("arquivo.txt").by_type("C170"):
    print(record.get("VL_ITEM"))
```

## Layouts

Versioned JSON layouts live in `src/sped/layouts/<obrigacao>/` and record the
official source URL, publication date and validity period. The official
sources are the Portal SPED manuals: EFD ICMS/IPI
([item 1573](http://sped.rfb.gov.br/item/show/1573)), EFD-Contribuições guides
v1.32/v1.35 ([items 4175](http://sped.rfb.gov.br/item/show/4175) and
[5837](http://sped.rfb.gov.br/item/show/5837)), ECD manuals
([items 4217/7989](http://sped.rfb.gov.br/item/show/1569)) and ECF manuals
[leiautes 6–12 (item 1644)](http://sped.rfb.gov.br/item/show/1644). Regenerate
with `python scripts/generate_layouts.py` and
`python scripts/generate_layouts_accounting.py` (network required, or
`--offline` to use `tmp/pdf`).

## Development

```bash
ruff check . && ruff format --check .
mypy
python -m pytest
```

## License

MIT — Hadagalberto Junior. See [LICENSE](LICENSE).
