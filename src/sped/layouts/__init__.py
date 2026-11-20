"""Access to the versioned, officially sourced layout data files."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Final

from sped.core.types import FieldDef, Layout, RegisterDef

_REGISTRY_NAME: Final = "registry.json"
_LAYOUTS_PACKAGE: Final = "sped.layouts"
_COD_VER_RE: Final = re.compile(r"^\|0000\|(\d{3})\|")


def _resource(obrigacao: str, name: str) -> Path:
    """Return a path inside the bundled layout package."""
    return resources.files(_LAYOUTS_PACKAGE).joinpath(obrigacao).joinpath(name)  # type: ignore[return-value]


@lru_cache(maxsize=1)
def _registry(obrigacao: str) -> dict[str, Any]:
    path = _resource(obrigacao, _REGISTRY_NAME)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)  # type: ignore[no-any-return]


def available_versions(obrigacao: str = "efd_icmsipi") -> tuple[str, ...]:
    """Return every bundled COD_VER, oldest first."""
    return tuple(entry["cod_ver"] for entry in _registry(obrigacao)["versions"])


def version_info(cod_ver: str, obrigacao: str = "efd_icmsipi") -> dict[str, str]:
    """Return metadata (official source, validity, dates) for one COD_VER."""
    for entry in _registry(obrigacao)["versions"]:
        if entry["cod_ver"] == cod_ver:
            return dict(entry)
    raise KeyError(f"COD_VER {cod_ver!r} não disponível para {obrigacao!r}")


def _parse_field(raw: dict[str, Any]) -> FieldDef:
    tam = str(raw["tam"])
    exact = tam.endswith("*")
    digits = tam.rstrip("*")
    size = int(digits) if digits.isdigit() else 0
    dec_raw = str(raw.get("dec", "-"))
    dec = int(dec_raw) if dec_raw.isdigit() else 0
    obrig = str(raw.get("obrig", ""))
    valid = raw.get("valid_values", ())
    return FieldDef(
        num=int(raw["num"]),
        name=str(raw["name"]),
        ftype=str(raw["type"]),
        size=size,
        exact=exact,
        dec=dec,
        description=str(raw.get("description", "")),
        required=bool(re.match(r"^O(?:\*|$)", obrig)),
        conditional=obrig.startswith("OC"),
        valid_values=tuple(str(value) for value in valid),
    )


def _parse_document(document: dict[str, Any]) -> Layout:
    meta = document["metadata"]
    registers: dict[str, RegisterDef] = {}
    for code, raw in document["registers"].items():
        fields = tuple(_parse_field(field) for field in raw["fields"])
        registers[code] = RegisterDef(
            code=code,
            title=str(raw.get("title", "")),
            level=raw.get("level"),
            occurrence=raw.get("occurrence"),
            fields=fields,
        )
    return Layout(
        obrigacao=str(meta["obrigacao"]),
        cod_ver=str(meta["cod_ver"]),
        versao=str(meta["versao"]),
        valid_from=str(meta["valid_from"]),
        valid_to=str(meta["valid_to"]),
        source_url=str(meta["source_url"]),
        source_date=str(meta["source_date"]),
        registers=registers,
        gap_filled_fields=int(meta.get("gap_filled_fields", 0)),
    )


@lru_cache(maxsize=16)
def load_layout(cod_ver: str, obrigacao: str = "efd_icmsipi") -> Layout:
    """Load a bundled layout by its three-digit ``COD_VER``.

    ``cod_ver`` may be given as ``"020"`` or ``"20"``; both are normalised.
    """
    normalized = cod_ver.zfill(3)
    info = version_info(normalized, obrigacao)
    path = _resource(obrigacao, info["file"])
    with path.open(encoding="utf-8") as handle:
        return _parse_document(json.load(handle))


def detect_cod_ver(path: str | Path, obrigacao: str = "efd_icmsipi") -> str:
    """Detect the COD_VER from the first record of a SPED file."""
    with Path(path).open("rb") as handle:
        sample = handle.read(4096)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        first = text.splitlines()[0] if text.splitlines() else ""
        match = _COD_VER_RE.match(first.strip())
        if match:
            cod_ver = match.group(1)
            # Fail early with a helpful message when the version is unsupported.
            version_info(cod_ver, obrigacao)
            return cod_ver
    raise ValueError("primeira linha não contém um registro 0000 com COD_VER válido")
