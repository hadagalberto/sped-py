"""Structural and totalisation checks used by ``sped validate``.

Compatibility façade: the PVA-like engine lives in :mod:`sped.validation`.
"""

from __future__ import annotations

from sped.validation import RULES, Rule, Severity, ValidationIssue, validate
from sped.validation.checks import REQUIRED_RECORDS

__all__ = [
    "REQUIRED_RECORDS",
    "RULES",
    "Rule",
    "Severity",
    "ValidationIssue",
    "validate",
]
