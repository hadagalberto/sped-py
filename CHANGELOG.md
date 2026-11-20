# Changelog

Todas as mudanças notáveis são documentadas aqui. Formato baseado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

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
