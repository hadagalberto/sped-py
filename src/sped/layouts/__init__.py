"""Access to the versioned, officially sourced layout data files.

Four obrigações are bundled: EFD ICMS/IPI, EFD-Contribuições, ECD and ECF.
Every JSON file records the official source URL and date; see
``scripts/generate_layouts.py`` and ``scripts/generate_layouts_accounting.py``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Final

from sped.core.encoding import is_signature_line
from sped.core.types import FieldDef, Layout, RegisterDef

_REGISTRY_NAME: Final = "registry.json"
_LAYOUTS_PACKAGE: Final = "sped.layouts"

#: Obrigações bundled with the library, in the order used by the docs.
OBRIGACOES: Final[tuple[str, ...]] = (
    "efd_icmsipi",
    "efd_contribuicoes",
    "ecd",
    "ecf",
)

#: The 0000 field 02 of ECD/ECF is the fixed marker LECD/LECF, not a COD_VER.
#: Source: Manual de Orientação do Leiaute 9 da ECD (item 7989) and Manual de
#: Orientação do Leiaute 12 da ECF (item 8004), both on Portal SPED.
_MARKERS: Final[dict[str, str]] = {"LECD": "ecd", "LECF": "ecf"}

#: Official ECD I010.COD_VER_LC values ("8.00" / "9.00") map to our 3-digit
#: keys. The manual states "A partir do ano-calendário 2020: Versão 9.00".
_ECD_VERSOES: Final[dict[str, str]] = {"8.00": "008", "9.00": "009"}


def _resource(obrigacao: str, name: str) -> Path:
    """Return a path inside the bundled layout package."""
    return resources.files(_LAYOUTS_PACKAGE).joinpath(obrigacao).joinpath(name)  # type: ignore[return-value]


@lru_cache(maxsize=8)
def _registry(obrigacao: str) -> dict[str, Any]:
    path = _resource(obrigacao, _REGISTRY_NAME)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)  # type: ignore[no-any-return]


def available_versions(obrigacao: str = "efd_icmsipi") -> tuple[str, ...]:
    """Return every bundled COD_VER for ``obrigacao``, oldest first."""
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
    # EFD ICMS/IPI uses O/OC/O*; ECD, ECF and EFD-Contribuições use
    # "Sim"/"Não" in the official "Obrigatório" column.
    required = bool(re.match(r"^O(?:\*|$)", obrig)) or ("Sim" in obrig and "Não" not in obrig)
    return FieldDef(
        num=int(raw["num"]),
        name=str(raw["name"]),
        ftype=str(raw["type"]),
        size=size,
        exact=exact,
        dec=dec,
        description=str(raw.get("description", "")),
        required=required,
        conditional=obrig.startswith("OC") or "condicion" in obrig.lower(),
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


@lru_cache(maxsize=32)
def load_layout(cod_ver: str, obrigacao: str = "efd_icmsipi") -> Layout:
    """Load a bundled layout by its three-digit ``COD_VER``.

    ``cod_ver`` may be given as ``"020"``, ``"20"`` or (for ECF) ``"0012"``;
    all are normalised to three digits.
    """
    normalized = cod_ver.lstrip("0").zfill(3)
    info = version_info(normalized, obrigacao)
    path = _resource(obrigacao, info["file"])
    with path.open(encoding="utf-8") as handle:
        return _parse_document(json.load(handle))


def _records_from_sample(sample: str) -> list[tuple[str, ...]]:
    result: list[tuple[str, ...]] = []
    for line in sample.splitlines():
        if is_signature_line(line):
            break
        if not line.startswith("|"):
            continue
        # Tolerate broken trailing framing here: the reader must still be able
        # to detect the layout and then report the framing error itself.
        body = line[1:-1] if line.endswith("|") else line[1:]
        parts = body.split("|")
        if len(parts) < 2 or len(parts[0]) != 4 or not parts[0].isalnum():
            continue
        result.append((parts[0], *parts[1:]))
    return result


def _sample(path: str | Path) -> str:
    with Path(path).open("rb") as handle:
        raw = handle.read(131072)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _detect(path: str | Path) -> tuple[str, str]:
    """Return ``(obrigacao, cod_ver)`` detected from the beginning of a file."""
    records = _records_from_sample(_sample(path))
    if not records:
        raise ValueError("arquivo não contém registros delimitados por '|' com COD_VER válido")
    first = records[0]
    if first[0] != "0000":
        raise ValueError("primeira linha não contém um registro 0000 com COD_VER válido")
    if len(first) > 1 and first[1] in _MARKERS:
        obrigacao = _MARKERS[first[1]]
    else:
        codigo = first[1] if len(first) > 1 else ""
        if codigo.lstrip("0").zfill(3) in available_versions("efd_icmsipi"):
            obrigacao = "efd_icmsipi"
        elif codigo.lstrip("0").zfill(3) in available_versions("efd_contribuicoes"):
            obrigacao = "efd_contribuicoes"
        else:
            raise ValueError(f"COD_VER {codigo!r} não corresponde a nenhuma obrigação conhecida")
    if obrigacao == "ecd":
        # 0000 da ECD não tem COD_VER; a versão está em I010.COD_VER_LC.
        i010 = next((record for record in records if record[0] == "I010"), None)
        if i010 is not None and len(i010) > 2 and i010[2] in _ECD_VERSOES:
            return obrigacao, _ECD_VERSOES[i010[2]]
        # Sem I010, a vigência oficial do leiaute 9 começa em 2020.
        dt_ini = first[2] if len(first) > 2 else ""
        year = int(dt_ini[4:8]) if len(dt_ini) == 8 and dt_ini.isdigit() else 2020
        return obrigacao, "008" if year < 2020 else "009"
    # Na ECF o COD_VER é o campo 03 (o campo 02 é o marcador LECF).
    cod_index = 2 if obrigacao == "ecf" else 1
    cod_ver = first[cod_index].lstrip("0").zfill(3)
    version_info(cod_ver, obrigacao)  # fail early with a helpful message
    return obrigacao, cod_ver


def detect_obrigacao(path: str | Path) -> str:
    """Detect the obrigação of a SPED file."""
    return _detect(path)[0]


def detect_cod_ver(path: str | Path, obrigacao: str | None = None) -> str:
    """Detect the layout version of a SPED file.

    When ``obrigacao`` is omitted it is detected from the same sample. ECD is
    detected from ``I010.COD_VER_LC`` because its 0000 has no COD_VER field.
    """
    detected_obrigacao, cod_ver = _detect(path)
    if obrigacao is not None and obrigacao != detected_obrigacao:
        raise ValueError(f"arquivo é da obrigação {detected_obrigacao!r}, não {obrigacao!r}")
    return cod_ver


def detect_layout(path: str | Path) -> Layout:
    """Detect both obrigação and COD_VER and return the matching layout."""
    obrigacao, cod_ver = _detect(path)
    return load_layout(cod_ver, obrigacao)
