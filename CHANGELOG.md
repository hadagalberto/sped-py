# Changelog

Todas as mudanças notáveis são documentadas aqui. Formato baseado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [Unreleased] — auditoria e endurecimento (milestone 5)

### Fixed

- Detecção de UTF-8 quando um caractere multibyte cruza o limite da amostra de
  8192 bytes; blocos de assinatura com o marcador enquadrado (`|SBMDSIG|…|`)
  agora são removidos; CR final não é mais removido em excesso.
- Apuração de ICMS: `C190` e `D190` usam o pai do seu próprio bloco — um `D100`
  cancelado não herda mais o `C100` anterior.
- `obrig` repetido nas tabelas oficiais (`"O O"`, `"OC OC"`) não desativa mais
  a obrigatoriedade do campo.
- Referências cruzadas 0150/0200/0190 derivadas de todos os registros do
  leiaute, não apenas de uma lista fixa de três registros.
- CLI: avisos não causam mais exit 1; erros de uso retornam 2 (não 3);
  `fix-totals` detecta a codificação de entrada por padrão e a aplica na saída;
  `diff` tolera linhas com framing quebrado.
- `get_dataframe` exportado no pacote raiz; erro acionável quando o pyarrow
  falta na exportação Parquet; índice em disco falha se o arquivo de origem
  estiver ausente.
- CI: job lento usa `--no-cov` (o gate de 95% tornava o job impossível) e novo
  job de build com wheel + sdist.

### Added

- `docs/SPEC-CHECKLIST.md` com verificação de cada requisito da SPEC.
- Extra `[tools]` com `pdfplumber` para os scripts geradores de leiautes.
- `tests/test_hardening.py` com 15 regressões de entradas maliciosas/edge cases.

## [0.4.0] - 2026-11-20

### Added

- Auxiliares de análise (`sped.analysis`): resumos por CFOP/CST/COD_PART em uma
  única passada; recálculo e comparação da apuração de ICMS/IPI (E110 e C190),
  PIS/COFINS (M200/M210/M600/M610) e saldos contábeis (I155, C155/E155/K155),
  com `recompute_apuracao()` para gravar um arquivo corrigido; diff alinhado
  entre original e retificadora; mesclagem e divisão por período
  (`merge_files`, `split_file`) gerando arquivos que passam em `sped validate`.
- Fórmulas de apuração extraídas para funções puras em `sped.validation.totals`,
  compartilhadas pelo validador e pela análise (fonte única dos manuais oficiais).
- Exportadores (`sped.exports`): CSV streaming, DataFrames pandas/Polars,
  Parquet e Excel, com `SpedExport`, `get_dataframe()` e erro claro quando uma
  extra opcional falta. Mnemônicos repetidos ganham sufixo `_2`/`_3` em formatos
  tabulares, sem alterar posições de campo.
- CLI completa com `summarize`, `apuracao`, `recompute-apuracao`, `merge`,
  `split`, `--json` em todos os comandos e códigos de saída documentados
  (`0` sucesso, `1` não conformidades, `2` uso/extra ausente, `3` E/S).
- Extras `[test]` e atualização da CI para instalar todas as dependências
  opcionais nos testes.
- Testes de vazão com limite generoso e streaming de 1 GB com pico de memória
  medido por `tracemalloc`.

### Fixed

- Escrita de campos de apuração corrigida (o REG implícito causava deslocamento
  de uma posição nos valores recalculados).
- Mesclagem/divisão preservam registros de controle obrigatórios (ex.: 9001 da
  ECD) e blocos sem documentos, evitando inconsistências no resultado.

## [0.3.0] - 2026-11-20

### Added

- Motor de validação PVA-like (`sped.validation`) com catálogo de regras
  imutáveis: cada regra tem id estável, severidade (`error`/`warning`), mensagem
  em pt-BR e fonte oficial citada. Cobertura de estrutura, registros obrigatórios
  por perfil A/B/C da EFD ICMS/IPI, totalizações de todas as obrigações
  (C100/C170, C190, E110, M200/M210, M600/M610, I155 e C155/E155/K155),
  tabelas oficiais e referências cruzadas 0150/0200/0190.
- Tabelas oficiais agrupadas em `src/sped/tables`: CFOP (Ajuste SINIEF 07/01),
  NCM (Receita Federal/Siscomex) e CST/CSOSN (Guia Prático EFD ICMS/IPI e
  Ajuste SINIEF 03/10), com `scripts/update_tables.py` (`--offline`, `--check`)
  registrando URL e data de cada fonte.
- `ValidationIssue.severity` e `severity` na saída JSON de `sped validate`.
- Fábrica sintética com variante quebrada por regra e testes positivo/negativo
  para cada uma delas.

## [0.2.0] - 2026-11-20

### Added

- Leiautes oficiais de EFD-Contribuições (COD_VER 005/006), ECD (008/009) e
  ECF (006–012), extraídos dos guias/manuais do Portal SPED e citados nos
  scripts geradores e no README. Detecção automática da obrigação e da versão
  (ECD via `I010.COD_VER_LC`).
- Hierarquia lazy de registros (`sped.core.hierarchy`) com níveis publicados,
  links pai/filho e iteração de stream com memória proporcional à profundidade.
- Índice opcional em disco (`sped.core.index`, `sped.core.index.IndexedReader`)
  para acesso aleatório por registro, com validação de fingerprint do arquivo.
- Fábrica sintética e testes de round trip byte-idêntico para as 20 combinações
  obrigação/versão, além de vetores inválidos conhecidos para cada uma.
- Escritor e validador cientes do leiaute: nenhum registro estrutural ausente
  da tabela oficial é inventado (ex.: ECF leiaute 12 não define S990).

## [0.1.0] - 2026-11-20

### Added

- Estrutura do projeto com hatchling, `src` layout, `py.typed`, ruff,
  mypy `--strict`, pytest + hypothesis + cobertura ≥ 95% e CI Linux/Windows/macOS
  para Python 3.10–3.13.
- Script `scripts/generate_layouts.py` que busca guias oficiais do Portal SPED e
  da CONFAZ, extrai as tabelas de campos e gera leiautes versionados com
  proveniência (URL e data).
- Leiautes EFD ICMS/IPI para COD_VER 013 a 021.
- Leitor streaming com detecção de encoding, CRLF/LF, remoção do bloco de
  assinatura, conversão tipada com `Decimal` e validação por campo.
- Escritor com recomputação automática de `x990`, `9900` e `9999`.
- Fábrica de arquivos sintéticos realistas e variantes quebradas para testes.
- CLI `sped` com `info`, `validate`, `export`, `diff` e `fix-totals`.
