"""Validação PVA-like de arquivos SPED.

Cada regra tem id estável, severidade, mensagem pt-BR e fonte oficial citada
em :mod:`sped.validation.rules`. As tabelas oficiais usadas pelas regras vivem
em :mod:`sped.tables` e são atualizadas por ``scripts/update_tables.py``.
"""

from __future__ import annotations

from sped.validation.context import ValidationContext, ValidationIssue
from sped.validation.engine import validate
from sped.validation.rules import RULES, Rule, Severity

__all__ = [
    "RULES",
    "Rule",
    "Severity",
    "ValidationContext",
    "ValidationIssue",
    "validate",
]
