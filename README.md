# sped-py

Leitura, validação, escrita e análise de arquivos SPED (EFD ICMS/IPI,
EFD-Contribuições, ECD e ECF) em Python puro, com leitura **streaming** de
arquivos de vários GB em memória constante.

- Python ≥ 3.10, **zero dependências obrigatórias**.
- Leiautes versionados gerados a partir das tabelas oficiais do Portal SPED e
  da CONFAZ (CODs 013 a 021, exercícios de 2019 a 2027).
- `Decimal` para valores monetários, datas `DDMMAAAA` convertidas para `date`.
- CLI `sped` com `info`, `validate`, `export`, `diff` e `fix-totals`.

> **Atenção:** os campos de totais (`x990`, `9900`, `9999`) são recalculados
> pelo escritor. Nunca confie em totais de um arquivo recebido sem validar.

## Instalação

```bash
pip install -e .            # biblioteca + CLI
pip install -e '.[pandas]'  # exportação para DataFrame/parquet
pip install -e '.[polars]'
pip install -e '.[excel]'
```

## Uso rápido

```python
from sped import read, write, load_layout

with read("efd.txt") as arquivo:
    for registro in arquivo:
        print(registro.line_no, registro.code, registro.values)

layout = load_layout("020")
print(layout.versao, layout.source_url)

with read("efd.txt") as entrada:
    write(entrada, "corrigido.txt")
```

A conversão tipada usa `Decimal` (nunca `float`) para campos `N` com decimais:

```python
with read("efd.txt") as arquivo:
    registro = next(registro for registro in arquivo if registro.code == "C170")
    print(registro.get("VL_ITEM"))  # Decimal('100.00')
```

## CLI

```bash
sped info efd.txt
sped validate efd.txt --json          # exit 1 quando há erros
sped export efd.txt --to csv saida/
sped export efd.txt --to parquet saida/
sped diff original.txt retificadora.txt
sped fix-totals efd.txt -o corrigido.txt
```

## Leiautes e fonte oficial

`src/sped/layouts/efd_icmsipi/<COD_VER>.json` contém todos os registros e
campos extraídos das tabelas publicadas pelo
[Portal SPED](http://sped.rfb.gov.br/item/show/1573) e pela
[CONFAZ](https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais).
Cada JSON registra `source_url`, `source_date`, vigência e o número de campos
preenchidos a partir do guia estruturado quando o PDF oficial não desenhava a
linha da célula. O script gerador é `scripts/generate_layouts.py`:

```bash
python scripts/generate_layouts.py          # busca fontes oficiais e gera tudo
python scripts/generate_layouts.py --offline
```

## Desenvolvimento

```bash
python -m pip install -e . pytest pytest-cov hypothesis ruff mypy
ruff check . && ruff format --check .
mypy
python -m pytest
```

A suíte inclui testes de propriedade (`write(read(x))` byte-identical,
idempotência dos totais) e um teste lento de streaming de 1 GB (`-m slow`).

## Licença

MIT — Hadagalberto Junior. Ver [LICENSE](LICENSE).
