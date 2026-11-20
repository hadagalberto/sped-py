"""Leitura das tabelas oficiais agrupadas em :mod:`sped.tables`.

O módulo expõe conjuntos imutáveis (cacheados) e predicates usados pelas
regras de validação. A proveniência de cada tabela está no metadata do JSON,
gerado por ``scripts/update_tables.py`` a partir de fontes oficiais.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any, Final

_TABLES_PACKAGE: Final = "sped.tables"


def _load(name: str) -> dict[str, Any]:
    path = resources.files(_TABLES_PACKAGE).joinpath(f"{name}.json")
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"tabela {name!r} inválida")
    return document


@lru_cache(maxsize=8)
def metadata(name: str) -> dict[str, str]:
    """Return the provenance metadata bundled with table ``name``."""
    raw = _load(name)["metadata"]
    return {str(key): str(value) for key, value in raw.items()}


@lru_cache(maxsize=8)
def cfop_codes() -> frozenset[str]:
    """Every CFOP code published in Ajuste SINIEF 07/01."""
    return frozenset(str(code) for code in _load("cfop")["codes"])


@lru_cache(maxsize=8)
def cfop_title_codes() -> frozenset[str]:
    """Group/heading CFOP codes that must not be used in operations."""
    return frozenset(str(code) for code in _load("cfop")["title_codes"])


@lru_cache(maxsize=8)
def ncm_codes() -> frozenset[str]:
    """Every 8-digit NCM code of the current official table."""
    return frozenset(str(code) for code in _load("ncm")["codes"])


@lru_cache(maxsize=8)
def _cst_table(name: str) -> frozenset[str]:
    return frozenset(str(code) for code in _load("cst")["tables"][name])


def cst_origem() -> frozenset[str]:
    """Official first digit of CST-ICMS (origem da mercadoria)."""
    return _cst_table("origem")


def cst_tributacao() -> frozenset[str]:
    """Official last two digits of CST-ICMS (Tabela B do Guia Prático)."""
    return _cst_table("tributacao")


def csosn_codes() -> frozenset[str]:
    """Official CSOSN codes (Ajuste SINIEF 03/10, Tabela B)."""
    return _cst_table("csosn")


def valid_cst_icms(value: str) -> bool:
    """Return True for an official CST-ICMS or CSOSN code."""
    if value in csosn_codes():
        return True
    return len(value) == 3 and value[0] in cst_origem() and value[1:] in cst_tributacao()


def valid_cfop(value: str) -> bool:
    """Return True for an operational (non-heading) official CFOP code."""
    return value in cfop_codes() and value not in cfop_title_codes()


def table_sources() -> dict[str, str]:
    """Return the official source URL of each bundled table."""
    return {name: metadata(name)["source_url"] for name in ("cfop", "ncm", "cst")}
