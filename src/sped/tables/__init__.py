"""Tabelas oficiais agrupadas (CFOP, CST/CSOSN e NCM).

Os JSON são gerados por ``scripts/update_tables.py`` a partir das fontes
oficiais (CONFAZ e Receita Federal); cada arquivo registra ``source_url`` e
``retrieved_at``. Nenhum código é inventado. A API de leitura está em
:mod:`sped.validation.tables`.
"""

from __future__ import annotations
