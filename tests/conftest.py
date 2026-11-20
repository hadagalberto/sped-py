"""Fixtures compartilhadas: todos os arquivos são sintéticos."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sped.factories.synthetic import SyntheticOptions, write_broken, write_synthetic


@pytest.fixture
def options() -> SyntheticOptions:
    return SyntheticOptions(cod_ver="020")


@pytest.fixture
def efd_file(tmp_path: Path, options: SyntheticOptions) -> Path:
    return write_synthetic(tmp_path / "efd.txt", options)


@pytest.fixture
def broken_file_factory(tmp_path: Path, options: SyntheticOptions) -> Callable[[str], Path]:
    def factory(kind: str) -> Path:
        return write_broken(tmp_path / f"{kind}.txt", kind, options)

    return factory
