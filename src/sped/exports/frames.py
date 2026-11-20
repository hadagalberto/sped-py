"""Exportação para DataFrames, Parquet e Excel (dependências opcionais).

Extras: ``[pandas]`` (DataFrame e Parquet via pyarrow), ``[polars]`` (DataFrame
e Parquet) e ``[excel]`` (openpyxl). Nenhum deles é importado quando o módulo é
carregado: a biblioteca continua com zero dependências obrigatórias.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sped.core.types import Layout
from sped.exports._common import Source, collect, columns, frame_columns


class MissingOptionalDependencyError(ImportError):
    """Dependência opcional ausente, com o extra correto na mensagem."""

    def __init__(self, extra: str, package: str) -> None:
        super().__init__(
            f"Instale o extra [{extra}] para usar {package}: pip install -e '.[{extra}]'"
        )
        self.extra = extra
        self.package = package


def _pandas() -> Any:
    try:
        import pandas as pd  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise MissingOptionalDependencyError("pandas", "pandas") from exc
    return pd


def _polars() -> Any:
    try:
        import polars as pl  # noqa: PLC0415
    except ImportError as exc:
        raise MissingOptionalDependencyError("polars", "polars") from exc
    return pl


def _openpyxl() -> Any:
    try:
        import openpyxl  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise MissingOptionalDependencyError("excel", "openpyxl") from exc
    return openpyxl


def to_dataframes(
    source: Source, layout: Layout | None = None, *, library: str = "pandas"
) -> dict[str, Any]:
    """Devolve um mapa ``código -> DataFrame`` por registro.

    ``library`` aceita ``"pandas"`` ou ``"polars"``. As colunas são os nomes
    publicados no leiaute e as linhas, os valores crus do arquivo.
    """
    chosen, grouped = collect(source, layout)
    if library == "pandas":
        pd = _pandas()
        return {
            code: pd.DataFrame(rows, columns=frame_columns(chosen, code))
            for code, rows in grouped.items()
        }
    if library == "polars":
        pl = _polars()
        return {
            code: pl.DataFrame(rows, schema=frame_columns(chosen, code), orient="row")
            for code, rows in grouped.items()
        }
    raise ValueError(f"biblioteca de DataFrame desconhecida: {library!r}")


def get_dataframe(
    source: Source, code: str, layout: Layout | None = None, *, library: str = "pandas"
) -> Any:
    """DataFrame de um único registro (atalho para aplicações de análise)."""
    frames = to_dataframes(source, layout, library=library)
    try:
        return frames[code]
    except KeyError:
        raise KeyError(f"registro {code!r} não encontrado no arquivo") from None


def to_parquet(
    source: Source,
    destination: str | Path,
    layout: Layout | None = None,
    *,
    library: str = "auto",
) -> dict[str, Path]:
    """Grava ``<REG>.parquet`` por registro e devolve os caminhos."""
    frames = _frames_for_parquet(source, layout, library)
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for code, frame in frames.items():
        path = target / f"{code}.parquet"
        if library == "polars" or not hasattr(frame, "to_parquet"):
            frame.write_parquet(path)
        else:
            frame.to_parquet(path, index=False)
        written[code] = path
    return written


def _frames_for_parquet(source: Source, layout: Layout | None, library: str) -> dict[str, Any]:
    if library == "auto":
        try:
            return to_dataframes(source, layout, library="pandas")
        except MissingOptionalDependencyError:
            return to_dataframes(source, layout, library="polars")
    chosen = to_dataframes(source, layout, library=library)
    return chosen


def to_excel(source: Source, destination: str | Path, layout: Layout | None = None) -> Path:
    """Grava uma planilha por registro em ``destination`` (extra ``[excel]``)."""
    openpyxl = _openpyxl()
    chosen, grouped = collect(source, layout)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for code, rows in grouped.items():
        sheet = workbook.create_sheet(title=code[:31])
        sheet.append(columns(chosen, code))
        for row in rows:
            sheet.append(row)
    workbook.save(target)
    return target


class SpedExport:
    """Fachada com todos os formatos de exportação para um mesmo arquivo."""

    def __init__(self, source: Source, *, layout: Layout | None = None) -> None:
        self.source = source
        self.layout = layout

    def csv(self, destination: str | Path) -> dict[str, int]:
        """Exporta CSVs."""
        from sped.exports.csv_export import export_csv  # noqa: PLC0415

        return export_csv(self.source, destination, layout=self.layout)

    def frames(self, *, library: str = "pandas") -> dict[str, Any]:
        """Exporta DataFrames."""
        return to_dataframes(self.source, self.layout, library=library)

    def parquet(self, destination: str | Path, *, library: str = "auto") -> dict[str, Path]:
        """Exporta Parquet."""
        return to_parquet(self.source, destination, self.layout, library=library)

    def excel(self, destination: str | Path) -> Path:
        """Exporta Excel."""
        return to_excel(self.source, destination, self.layout)
