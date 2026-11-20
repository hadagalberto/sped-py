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
- Full CLI `sped`: `info`, `validate`, `export`, `diff`, `fix-totals`,
  `summarize`, `apuracao`, `recompute-apuracao`, `merge` and `split` — all with
  `--json` and stable exit codes.
- Analysis helpers: CFOP/CST/participant summaries, apuração recomputation
  (ICMS/IPI, PIS/COFINS and accounting balances), amended-file diff and
  merge/split by period.
- Exports: CSV (dependency-free), pandas, Polars, Parquet and Excel.

> Totals (`x990`, `9900`, `9999`) are recomputed by the writer. Never trust
> totals from an incoming file without validating it.

## Install

```bash
pip install -e .
pip install -e '.[pandas]'  # DataFrame + Parquet (pyarrow)
pip install -e '.[polars]'  # DataFrame + Parquet (Polars)
pip install -e '.[excel]'   # Excel (openpyxl)
pip install -e '.[test]'    # all extras, for the test suite
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

## PVA-like validation

```python
from sped.validation import RULES, validate

for issue in validate("efd.txt"):
    print(issue.rule, issue.severity.value, issue.message)
```

Every rule has a stable id, severity (`error`/`warning`), a pt-BR message and a
cited official source. Checks cover structure, required records per EFD
ICMS/IPI profile (A/B/C), totalizations for all four obligations, official
CFOP/CST/NCM tables and 0150/0200/0190 cross-references. Bundled tables are
refreshed with `python scripts/update_tables.py`; provenance is recorded in
each JSON file.

## Analysis

```python
from sped import (
    compute_apuracao,
    diff_files,
    merge_files,
    recompute_apuracao,
    split_file,
    summarize_file,
)
from sped.core.reader import read
from sped.layouts import detect_layout

for summary in summarize_file("efd.txt"):  # CFOP, CST, COD_PART
    print(summary.dimension, summary.as_dict())

with read("efd.txt", strict=False) as source:
    ap = compute_apuracao(source.iter_records(), layout=detect_layout("efd.txt"))
print(ap.ok, [field.as_dict() for field in ap.divergences])
fixed = recompute_apuracao("efd.txt")  # writes efd-apurado.txt

result = diff_files("original.txt", "amended.txt")
print(result.added, result.removed, result.changed)
merge_files(["jan.txt", "feb.txt"], "accumulated.txt")
parts = split_file("accumulated.txt", "parts/", by="month")
```

Apuração formulas are not reimplemented: analysis calls the same pure functions
used by the validator (`sped.validation.totals`), which cite the official
manuals. `merge_files`/`split_file` recompute structural totals and apuração, so
their output passes `sped validate`.

## Exports

```python
from sped import SpedExport, get_dataframe

exporter = SpedExport("efd.txt")
exporter.csv("out/")
exporter.frames(library="pandas")
exporter.frames(library="polars")
exporter.parquet("out/")
exporter.excel("out/sped.xlsx")
c170 = get_dataframe("efd.txt", "C170")
```

CSV and Excel keep the published field names. Typed tabular formats append
`_2`, `_3`… to duplicated mnemonics from the official layout (e.g. `ALIQ_PIS`
in C170) so columns are unique; field positions never change.

## CLI

```bash
sped info efd.txt
sped validate efd.txt --json
sped export efd.txt --to csv out/
sped export efd.txt --to parquet out/
sped export efd.txt --to excel out/sped.xlsx
sped diff original.txt amended.txt --json
sped fix-totals efd.txt -o fixed.txt
sped summarize efd.txt --dimension CFOP --json
sped apuracao efd.txt --json
sped recompute-apuracao efd.txt -o fixed.txt
sped merge jan.txt feb.txt -o accumulated.txt
sped split accumulated.txt -o parts/ --by month
```

Every command accepts `--json`. Exit codes: `0` success; `1` command found
non-conformities (validation, diff or apuração); `2` invalid usage or missing
optional dependency; `3` read/I/O failure.

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
python -m pip install -e '.[test]' pytest pytest-cov hypothesis ruff mypy
ruff check . && ruff format --check .
mypy
python -m pytest -m "not slow"   # default suite
python -m pytest -m slow         # opt-in 1 GB streaming test
```

## License

MIT — Hadagalberto Junior. See [LICENSE](LICENSE).
