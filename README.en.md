# sped-py

Pure-Python streaming reader, validator and writer for Brazilian SPED digital
bookkeeping files (EFD ICMS/IPI, EFD-Contribuições, ECD and ECF).

- Python ≥ 3.10, **zero required dependencies**.
- Versioned layouts generated from official Portal SPED / CONFAZ tables
  (COD_VER 013–021, tax years 2019–2027).
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
```

## CLI

```bash
sped info efd.txt
sped validate efd.txt --json
sped export efd.txt --to csv out/
sped diff original.txt amended.txt
sped fix-totals efd.txt -o fixed.txt
```

## Layouts

Versioned JSON layouts live in `src/sped/layouts/efd_icmsipi/` and record the
official source URL, publication date and validity period. Regenerate with
`python scripts/generate_layouts.py` (network required) or `--offline`.

## Development

```bash
ruff check . && ruff format --check .
mypy
python -m pytest
```

## License

MIT — Hadagalberto Junior. See [LICENSE](LICENSE).
