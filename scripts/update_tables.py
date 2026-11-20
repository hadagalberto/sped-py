#!/usr/bin/env python3
"""Atualiza as tabelas oficiais agrupadas em ``src/sped/tables``.

Nenhum código é inventado: CFOP e NCM são extraídos das fontes oficiais
abaixo; CST/CSOSN são o conjunto finito publicado nas tabelas oficiais
citadas (conferência manual, com as URLs gravadas no metadata de cada JSON).
Use --retrieved-at para registrar uma data diferente da verificação atual.

Fontes (verificadas em 2026-11-20):

* **CFOP** — CONFAZ, ``Ajuste SINIEF 07/01`` (anexo com a tabela completa de
  códigos e notas explicativas),
  https://www.confaz.fazenda.gov.br/legislacao/ajustes/2001/AJ_007_01
  Os códigos de grupo (descrição toda em maiúsculas, p. ex. ``1.000``,
  ``1.100``) são mantidos no JSON mas separados em ``title_codes``: o Guia
  Prático EFD ICMS/IPI (Cap. IV, subseção 1.2) determina que esses códigos
  "não devem ser utilizados" em operações.
* **NCM** — Receita Federal, download público da Nomenclatura Comum do Mercosul,
  https://www.gov.br/receitafederal/pt-br/assuntos/aduana-e-comercio-exterior/classificacao-fiscal-de-mercadorias/download-ncm-nomenclatura-comum-do-mercosul
  JSON direto (sem captcha):
  https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json
  Apenas os códigos de 8 dígitos (nível NCM) são agrupados.
* **CST/CSOSN** — Guia Prático EFD ICMS/IPI v3.2.4 (Cap. IV, subseção 1.1):
  https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@display-file/file
  e CONFAZ, ``Ajuste SINIEF 03/10`` (Anexo Único, Tabela B — CSOSN):
  https://www.confaz.fazenda.gov.br/legislacao/ajustes/2010/AJ_003_10

Uso::

    python scripts/update_tables.py                 # baixa e gera tudo
    python scripts/update_tables.py --offline       # usa tmp/tables_cache
    python scripts/update_tables.py --check         # só confere se está atualizado
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent
CACHE: Final = ROOT / "tmp" / "tables_cache"
OUTPUT: Final = ROOT / "src" / "sped" / "tables"

CFOP_URL: Final = "https://www.confaz.fazenda.gov.br/legislacao/ajustes/2001/AJ_007_01"
NCM_URL: Final = (
    "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json"
)
CST_GUIDE_URL: Final = (
    "https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/"
    "manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@display-file/file"
)
CSOSN_URL: Final = "https://www.confaz.fazenda.gov.br/legislacao/ajustes/2010/AJ_003_10"
RETRIEVED_AT: Final = "2026-11-20"

#: Guia Prático EFD ICMS/IPI v3.2.4, Cap. IV subseção 1.1, Tabelas A e B.
CST_ORIGEM: Final = ("0", "1", "2", "3", "4", "5", "6", "7", "8")
CST_TRIBUTACAO: Final = (
    "00",
    "02",
    "10",
    "15",
    "20",
    "30",
    "40",
    "41",
    "50",
    "51",
    "53",
    "60",
    "61",
    "70",
    "90",
)
#: Ajuste SINIEF 03/10, Anexo Único, Tabela B (a Tabela C foi revogada pelo
#: Ajuste SINIEF 17/2015).
CSOSN: Final = ("101", "102", "103", "201", "202", "203", "300", "400", "500", "900")

CFOP_LINE: Final = re.compile(r"^([1-7])[\.\s]?(\d{3})\s*[-\u2013\u2014]\s*(.+)$")


@dataclass(frozen=True, slots=True)
class CfopTable:
    codes: dict[str, str]
    title_codes: tuple[str, ...]


def fetch(url: str, name: str, *, offline: bool) -> bytes:
    """Return raw bytes from the official URL or from the local cache."""
    cached = CACHE / name
    if offline:
        return cached.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": "sped-py/table-updater"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = bytes(response.read())
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def parse_cfop(raw_html: bytes) -> CfopTable:
    """Extract CFOP codes and descriptions from the CONFAZ HTML page."""
    text = raw_html.decode("utf-8", errors="replace")
    text = re.sub(r"<p[^>]*>", "\n", text)
    text = re.sub(r"</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    codes: dict[str, str] = {}
    for line in text.splitlines():
        match = CFOP_LINE.match(" ".join(line.split()))
        if match is not None:
            codes.setdefault(match.group(1) + match.group(2), match.group(3).strip())
    if len(codes) < 400:
        raise ValueError(f"tabela CFOP incompleta: apenas {len(codes)} códigos extraídos")
    titles = tuple(sorted(code for code, desc in codes.items() if desc.isupper()))
    return CfopTable(codes, titles)


def parse_ncm(payload: bytes) -> tuple[list[str], str, str]:
    """Return sorted 8-digit NCM codes, the update date and the tome act."""
    document = json.loads(payload.decode("utf-8"))
    codes = sorted(
        {
            str(node["Codigo"]).replace(".", "")
            for node in document["Nomenclaturas"]
            if re.fullmatch(r"\d{8}", str(node["Codigo"]).replace(".", ""))
        }
    )
    if len(codes) < 9000:
        raise ValueError(f"tabela NCM incompleta: apenas {len(codes)} códigos extraídos")
    return codes, str(document["Data_Ultima_Atualizacao_NCM"]), str(document["Ato"])


def document(
    name: str, url: str, extra: dict[str, Any], retrieved_at: str = RETRIEVED_AT
) -> dict[str, Any]:
    return {
        "metadata": {
            "name": name,
            "source_url": url,
            "retrieved_at": retrieved_at,
            **extra,
        }
    }


def build_documents(
    cfop: CfopTable, ncm: tuple[list[str], str, str], retrieved_at: str = RETRIEVED_AT
) -> dict[str, dict[str, Any]]:
    """Build the JSON documents written by this script."""
    ncm_codes, ncm_date, ncm_act = ncm
    cfop_doc = document(
        "cfop",
        CFOP_URL,
        {
            "law": "Ajuste SINIEF 07/01 (CONFAZ)",
            "title_code_rule": (
                "Códigos de grupo (title_codes) não devem ser usados em operações — "
                "Guia Prático EFD ICMS/IPI v3.2.4, Cap. IV subseção 1.2"
            ),
            "count": len(cfop.codes),
        },
        retrieved_at,
    )
    cfop_doc["codes"] = dict(sorted(cfop.codes.items()))
    cfop_doc["title_codes"] = list(cfop.title_codes)

    ncm_doc = document(
        "ncm",
        NCM_URL,
        {
            "law": ncm_act,
            "official_update": ncm_date,
            "landing_page": (
                "https://www.gov.br/receitafederal/pt-br/assuntos/aduana-e-comercio-exterior/"
                "classificacao-fiscal-de-mercadorias/download-ncm-nomenclatura-comum-do-mercosul"
            ),
            "count": len(ncm_codes),
        },
        retrieved_at,
    )
    ncm_doc["codes"] = ncm_codes

    cst_doc = document(
        "cst",
        CST_GUIDE_URL,
        {
            "law": "Guia Prático EFD ICMS/IPI v3.2.4 Cap. IV subseção 1.1; Ajuste SINIEF 03/10",
            "csosn_source_url": CSOSN_URL,
        },
        retrieved_at,
    )
    cst_doc["tables"] = {
        "origem": list(CST_ORIGEM),
        "tributacao": list(CST_TRIBUTACAO),
        "csosn": list(CSOSN),
    }
    return {"cfop": cfop_doc, "ncm": ncm_doc, "cst": cst_doc}


def write_documents(documents: dict[str, dict[str, Any]], output: Path) -> None:
    """Write all documents as UTF-8 JSON with LF line endings."""
    output.mkdir(parents=True, exist_ok=True)
    for name, doc in documents.items():
        target = output / f"{name}.json"
        text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        target.write_bytes(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="usa arquivos em tmp/tables_cache")
    parser.add_argument("--check", action="store_true", help="apenas confere se está atualizado")
    parser.add_argument(
        "--retrieved-at",
        default=RETRIEVED_AT,
        help="data de verificação a gravar no metadata (ISO-8601)",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    cfop = parse_cfop(fetch(CFOP_URL, "cfop.html", offline=args.offline))
    ncm = parse_ncm(fetch(NCM_URL, "ncm.json", offline=args.offline))
    docs = build_documents(cfop, ncm, args.retrieved_at)
    if args.check:
        stale = []
        for name, doc in docs.items():
            target = args.output / f"{name}.json"
            expected = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if not target.exists() or target.read_bytes() != expected:
                stale.append(name)
        if stale:
            print("Tabelas desatualizadas: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("Tabelas atualizadas.")
        return 0
    write_documents(docs, args.output)
    for name, doc in docs.items():
        count = doc["metadata"].get("count") or sum(
            len(values) for values in doc["tables"].values()
        )
        print(f"{name}: {count} entradas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
