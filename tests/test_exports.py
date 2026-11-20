"""Testes de exportação, inclusive caminhos de dependência opcional ausente."""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest

from sped.core.reader import read
from sped.exports import (
    MissingOptionalDependencyError,
    SpedExport,
    collect,
    export_csv,
    get_dataframe,
    to_dataframes,
    to_excel,
    to_parquet,
)
from sped.layouts import detect_layout


def _without(module: str, monkeypatch: pytest.MonkeyPatch) -> None:
    real_import: Any = builtins.__import__

    def fake(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == module or name.startswith(f"{module}."):
            raise ImportError(f"módulo {module} indisponível no teste")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake)


def test_export_csv(efd_file: Path, tmp_path: Path) -> None:
    target = tmp_path / "csv"
    counts = export_csv(efd_file, target)
    assert counts["C170"] == 1
    assert counts["0000"] == 1
    assert (target / "C170.csv").exists()
    header = (target / "0000.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("REG,COD_VER,COD_FIN,DT_INI")
    row = (target / "C170.csv").read_text(encoding="utf-8").splitlines()[1]
    assert row.startswith("C170,1,PRODUTO001")


def test_export_csv_from_iterable(efd_file: Path, tmp_path: Path) -> None:
    with read(efd_file) as arquivo:
        records = list(arquivo.iter_records())
    with pytest.raises(ValueError, match="layout"):
        export_csv(records, tmp_path / "sem-layout")
    counts = export_csv(records, tmp_path / "com-layout", layout=detect_layout(efd_file))
    assert counts == export_csv(efd_file, tmp_path / "por-caminho")


def test_collect(efd_file: Path) -> None:
    layout, grouped = collect(efd_file)
    assert layout.obrigacao == "efd_icmsipi"
    assert set(grouped) >= {"0000", "C100", "C170", "E110"}
    assert grouped["C170"][0][0] == "C170"


def test_to_dataframes_pandas(efd_file: Path) -> None:
    frames = to_dataframes(efd_file, library="pandas")
    assert frames["C170"].shape == (1, 38)
    assert list(frames["C170"].columns).count("ALIQ_PIS") == 1
    assert "ALIQ_PIS_2" in frames["C170"].columns
    assert list(frames["C100"].columns)[:4] == ["REG", "IND_OPER", "IND_EMIT", "COD_PART"]
    assert frames["E110"].iloc[0]["VL_TOT_CREDITOS"] == "10000"
    assert get_dataframe(efd_file, "C170").shape == (1, 38)
    with pytest.raises(KeyError, match="não encontrado"):
        get_dataframe(efd_file, "ZZZZ")


def test_to_dataframes_polars(efd_file: Path) -> None:
    frames = to_dataframes(efd_file, library="polars")
    assert frames["C170"].shape == (1, 38)
    assert frames["C170"].columns[0] == "REG"
    assert frames["C170"].columns.count("ALIQ_PIS") == 1
    assert "ALIQ_PIS_2" in frames["C170"].columns
    assert frames["E110"]["VL_TOT_CREDITOS"][0] == "10000"
    assert get_dataframe(efd_file, "C170", library="polars").height == 1


def test_invalid_library(efd_file: Path) -> None:
    with pytest.raises(ValueError, match="biblioteca"):
        to_dataframes(efd_file, library="duckdb")


def test_to_parquet_pandas(efd_file: Path, tmp_path: Path) -> None:
    import pandas as pd  # type: ignore[import-untyped]  # noqa: PLC0415

    paths = to_parquet(efd_file, tmp_path / "pq", library="pandas")
    assert paths["C170"].exists()
    frame = pd.read_parquet(paths["C170"])
    assert frame.shape == (1, 38)
    assert frame.iloc[0]["COD_ITEM"] == "PRODUTO001"


def test_to_parquet_polars(efd_file: Path, tmp_path: Path) -> None:
    import polars as pl  # noqa: PLC0415

    paths = to_parquet(efd_file, tmp_path / "pq", library="polars")
    assert paths["C170"].exists()
    frame = pl.read_parquet(paths["C170"])
    assert frame.shape == (1, 38)


def test_to_parquet_auto(efd_file: Path, tmp_path: Path) -> None:
    paths = to_parquet(efd_file, tmp_path / "pq")
    assert paths["E110"].exists()


def test_to_excel(efd_file: Path, tmp_path: Path) -> None:
    from openpyxl import load_workbook  # type: ignore[import-untyped]  # noqa: PLC0415

    target = to_excel(efd_file, tmp_path / "sped.xlsx")
    workbook = load_workbook(target)
    assert "C170" in workbook.sheetnames
    sheet = workbook["C170"]
    assert sheet.max_row == 2
    assert sheet.cell(row=1, column=1).value == "REG"
    assert sheet.cell(row=2, column=1).value == "C170"
    workbook.close()


def test_missing_optional_dependencies(
    efd_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without("pandas", monkeypatch)
    with pytest.raises(MissingOptionalDependencyError) as exc:
        to_dataframes(efd_file)
    assert exc.value.extra == "pandas"
    assert "pip install" in str(exc.value)
    with pytest.raises(MissingOptionalDependencyError):
        get_dataframe(efd_file, "C170")
    # Parquet com library=auto deve cair para polars quando pandas falta.
    paths = to_parquet(efd_file, tmp_path / "pq-auto")
    assert paths["C170"].exists()

    monkeypatch.undo()
    _without("polars", monkeypatch)
    with pytest.raises(MissingOptionalDependencyError) as exc:
        to_dataframes(efd_file, library="polars")
    assert exc.value.extra == "polars"

    monkeypatch.undo()
    _without("openpyxl", monkeypatch)
    with pytest.raises(MissingOptionalDependencyError) as exc:
        to_excel(efd_file, tmp_path / "no.xlsx")
    assert exc.value.extra == "excel"


def test_sped_export_facade(efd_file: Path, tmp_path: Path) -> None:
    exporter = SpedExport(efd_file)
    assert exporter.csv(tmp_path / "csv")["C170"] == 1
    assert exporter.frames(library="pandas")["C170"].shape[0] == 1
    assert exporter.parquet(tmp_path / "pq", library="polars")["C170"].exists()
    assert exporter.excel(tmp_path / "sped.xlsx").exists()
