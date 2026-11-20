# sped-py

Leitura, validação, escrita e análise de arquivos SPED (EFD ICMS/IPI,
EFD-Contribuições, ECD e ECF) em Python puro, com leitura **streaming** de
arquivos de vários GB em memória constante.

- Python ≥ 3.10, **zero dependências obrigatórias**.
- Leiautes versionados gerados a partir das tabelas oficiais do Portal SPED e
  da CONFAZ, para **todas as obrigações e versões de 2019 em diante**:
  EFD ICMS/IPI (013–021), EFD-Contribuições (005–006), ECD (008–009) e ECF
  (006–012).
- Hierarquia de registros com níveis publicados nos manuais e iteração lazy;
  índice opcional em disco para acesso aleatório por registro.
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

A obrigação e a versão são detectadas automaticamente (para a ECD a versão vem
de `I010.COD_VER_LC` ou, na ausência desse registro, do ano de `0000.DT_INI`):

```python
from sped.layouts import detect_layout, available_versions

layout = detect_layout("arquivo.txt")
print(layout.obrigacao, layout.cod_ver, available_versions(layout.obrigacao))
```

### Hierarquia e índice

```python
from sped.core.hierarchy import RecordTree
from sped.core.index import IndexedReader, build_index
from sped.core.reader import read

with read("arquivo.txt") as arquivo:
    for entrada in RecordTree(arquivo, arquivo.layout).iter_entries():
        print(entrada.line_no, entrada.code, entrada.level, entrada.parent)

indice = build_index("arquivo.txt")  # grava arquivo.txt.spedidx
leitor = IndexedReader("arquivo.txt")  # reaproveita/cria o índice
for registro in leitor.by_type("C170"):  # só busca as linhas C170
    print(registro.get("VL_ITEM"))
```

## Validação PVA-like

```python
from sped.validation import RULES, validate

for issue in validate("efd.txt"):
    print(issue.rule, issue.severity.value, issue.message)

print(len(RULES))  # catálogo completo de regras
```

Cada regra possui id estável, severidade (`error` ou `warning`), mensagem em
pt-BR e a fonte oficial citada. O motor verifica estrutura, registros
obrigatórios por perfil (A/B/C da EFD ICMS/IPI), totalizações de todas as
obrigações, tabelas oficiais e referências cruzadas (`0150`/`0200`/`0190`).
A saída JSON do CLI inclui a severidade:

```bash
sped validate efd.txt --json    # exit 1 quando há erros
```

### Tabelas oficiais

`src/sped/tables` agrupa CFOP (Ajuste SINIEF 07/01), NCM (Receita
Federal/Siscomex) e CST/CSOSN (Guia Prático EFD ICMS/IPI e Ajuste SINIEF 03/10).
Cada JSON registra `source_url` e `retrieved_at`; a atualização é feita por
`python scripts/update_tables.py` (use `--offline` para o cache em
`tmp/tables_cache` e `--check` para conferir se está atualizado).

```python
from sped.validation.tables import valid_cfop, valid_cst_icms, ncm_codes

valid_cfop("1101")  # True (operacional)
valid_cfop("1100")  # False (código de grupo)
valid_cst_icms("000")  # True
"84713011" in ncm_codes()  # True
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

Os JSON em `src/sped/layouts/<obrigacao>/<COD_VER>.json` contêm todos os
registros e campos extraídos das tabelas publicadas pelo
[Portal SPED](http://sped.rfb.gov.br/item/show/1573) e pela
[CONFAZ](https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais).
Cada JSON registra `source_url`, `source_date` e vigência. Fontes utilizadas
(todas oficiais, verificadas em 2026-11-20):

- EFD ICMS/IPI — [Guias Práticos e Notas Técnicas do Portal SPED](http://sped.rfb.gov.br/item/show/1573).
- EFD-Contribuições — [Guia Prático v1.32 (item 4175, COD_VER 005)](http://sped.rfb.gov.br/item/show/4175)
  e [v1.35 (item 5837, COD_VER 006)](http://sped.rfb.gov.br/item/show/5837);
  tabela oficial 3.1.1 "Versão do Leiaute".
- ECD — [Manual do Leiaute 8 (item 4217)](http://sped.rfb.gov.br/item/show/4217)
  e [Leiaute 9 (item 7989)](http://sped.rfb.gov.br/item/show/7989);
  `I010.COD_VER_LC` = 8.00 / 9.00.
- ECF — [Manuais dos Leiautes 6 a 12 (item 1644)](http://sped.rfb.gov.br/item/show/1644);
  `0000.COD_VER` = 0006 a 0012.

Scripts geradores (com `--offline` para usar o cache em `tmp/pdf`):

```bash
python scripts/generate_layouts.py
python scripts/generate_layouts_accounting.py
```

Nenhuma posição de campo é inventada: as tabelas estruturadas dos manuais
oficiais são extraídas diretamente pelos scripts. Pesquisas posteriores que
alteram campos sem criar novo COD_VER são refletidas no último guia/manual
publicado daquela versão.

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
