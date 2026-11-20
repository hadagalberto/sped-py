#!/usr/bin/env python3
"""Gera os leiautes EFD-Contribuições, ECD e ECF a partir de fontes oficiais.

Todas as tabelas vêm dos manuais/guias publicados no Portal SPED (Receita
Federal) e são citadas abaixo. Nenhuma posição de campo ou regra é inventada:
o script apenas extrai as tabelas estruturadas dos documentos oficiais.

Fontes (verificadas em 2026-11-20):

* **EFD-Contribuições** — índice de manuais
  ``http://sped.rfb.gov.br/item/show/1989``:
  Guia Prático v1.32 (``/item/show/4175``, atualizado em 07/10/2019, COD_VER
  005 — exercício de 2019) e Guia Prático v1.35
  (``/item/show/5837``, atualizado em 18/06/2021, COD_VER 006 — a partir de
  2020). A tabela oficial 3.1.1 "Versão do Leiaute" dos guias fixa
  ``005 = 3.1.0 (01/01/2019)`` e ``006 = 3.2.0 (01/01/2020)``. As notas
  técnicas posteriores (``/item/show/7593``, ``/item/show/7667``,
  ``/item/show/8126``) alteram campos sem criar novo COD_VER; por isso o
  leiaute 006 usa o último guia publicado.
* **ECD** — índice de manuais ``http://sped.rfb.gov.br/item/show/1569``:
  Manual de Orientação do Leiaute 8 (``/item/show/4217``, ADE Cofis 64/2019,
  atualizado em novembro de 2019) e Manual de Orientação do Leiaute 9
  (``/item/show/7989``, ADE Cofis 01/2026, atualizado em maio de 2026).
  O campo ``I010.COD_VER_LC`` é ``8.00``/``9.00`` respectivamente; o 0000 da
  ECD não contém COD_VER (o campo 02 é o texto fixo ``LECD``).
* **ECF** — índice de manuais ``http://sped.rfb.gov.br/item/show/1644``:
  Manuais dos Leiautes 6 a 12 (itens 4271, 5716, 5971, 7145, 7306, 7626 e
  8004). O campo ``0000.COD_VER`` é ``0006`` a ``0012``, um para cada
  ano-calendário de 2019 a 2025, conforme a observação oficial no campo 03.

Uso::

    python scripts/generate_layouts_accounting.py           # busca fontes oficiais
    python scripts/generate_layouts_accounting.py --offline # usa tmp/pdf em cache
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from xml.etree import ElementTree as ET

from generate_layouts import (
    HEADER_RE,
    NIVEL_RE,
    OCORR_RE,
    REG_RE,
    ParsedRegister,
    W,
    _row_to_field,
    norm,
    validate_layout,
)

ROOT: Final = Path(__file__).resolve().parent.parent
CACHE: Final = ROOT / "tmp" / "pdf"
LAYOUTS: Final = ROOT / "src" / "sped" / "layouts"
PORTAL: Final = "http://sped.rfb.gov.br"
REQUIRED: Final[tuple[str, ...]] = (
    "0000",
    "0001",
    "0990",
    "9001",
    "9900",
    "9990",
    "9999",
)


@dataclass(frozen=True, slots=True)
class Source:
    """Uma versão oficial, com proveniência completa."""

    obrigacao: str
    cod_ver: str
    versao: str
    valid_from: str
    valid_to: str
    item: int
    source_date: str
    cache_name: str
    parser: Callable[[Path], dict[str, ParsedRegister]]

    @property
    def source_url(self) -> str:
        return f"{PORTAL}/arquivo/download/{self.item}"

    @property
    def source_page(self) -> str:
        return f"{PORTAL}/item/show/{self.item}"


def _accounting_docx(path: Path) -> dict[str, ParsedRegister]:
    """Extrai tabelas dos manuais Word de ECD e EFD-Contribuições.

    Além dos cabeçalhos ``REGISTRO xxxx: ...``, os manuais contêm a instrução
    oficial ``Campos a serem informados no registro xxxx`` seguida de uma
    tabela de campos. Sem esse reconhecimento, os campos dessa tabela seriam
    atribuídos ao registro anterior (o que corromperia, por exemplo, o 9999
    da ECD com campos do I510).
    """
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find(W + "body")
    if body is None:
        raise ValueError("DOCX sem corpo")
    explicit_re = re.compile(r"[Cc]ampos a serem informados no registro\s+([0-9A-Z]{4})")
    registers: dict[str, ParsedRegister] = {}
    current = ""
    for element in body:
        if element.tag == W + "p":
            text = norm("".join(node.text or "" for node in element.iter(W + "t")))
            if match := REG_RE.match(text):
                current = match.group(1).upper()
                reg = registers.setdefault(
                    current, ParsedRegister(code=current, title=match.group(2))
                )
                if not reg.title:
                    reg.title = match.group(2)
            elif match := explicit_re.search(text):
                current = match.group(1).upper()
                registers.setdefault(current, ParsedRegister(code=current))
            elif current and registers[current].level is None:
                if match := NIVEL_RE.match(text):
                    registers[current].level = int(match.group(1))
            elif current and registers[current].occurrence is None:
                if match := OCORR_RE.match(text):
                    registers[current].occurrence = match.group(1).rstrip(".")
            continue
        if element.tag != W + "tbl" or not current:
            continue
        rows = [
            [" ".join(node.text or "" for node in tc.iter(W + "t")) for tc in tr.findall(W + "tc")]
            for tr in element.findall(W + "tr")
        ]
        if not rows:
            continue
        head = [norm(cell) for cell in rows[0]]
        if (
            len(head) < 6
            or not HEADER_RE.match("".join(head[0]).replace(" ", ""))
            or head[1].lower() != "campo"
        ):
            continue
        for row in rows[1:]:
            parsed = _row_to_field(row)
            if parsed is not None:
                registers[current].fields[parsed["num"]] = parsed
    return registers


def _ecf_docx(path: Path) -> dict[str, ParsedRegister]:
    """Extrai tabelas do manual Word da ECF (coluna 'Valores Válidos').

    As tabelas oficiais da ECF têm o cabeçalho
    ``Nº | Campo | Descrição | Tipo | Tamanho | Decimal | Valores Válidos |
    Obrigatório``; os níveis hierárquicos aparecem em linhas separadas do
    mesmo registro.
    """
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find(W + "body")
    if body is None:
        raise ValueError("DOCX sem corpo")
    registers: dict[str, ParsedRegister] = {}
    current = ""
    level_occ = re.compile(r"N[ií]vel\s+Hier[aá]rquico\s*[\-\u2013\u2014:]?\s*(\d+)", re.I)
    occ_re = re.compile(r"Ocorr[êe]ncia\s*[\-\u2013\u2014:]?\s*(.+)", re.I)
    for element in body:
        if element.tag not in {W + "p", W + "tbl"}:
            continue
        rows = [
            [" ".join(node.text or "" for node in tc.iter(W + "t")) for tc in tr.findall(W + "tc")]
            for tr in element.findall(W + "tr")
        ]
        if not rows:
            continue
        head = [norm(cell) for cell in rows[0]]
        if len(head) == 1 and (
            match := re.match(r"REGISTRO\s+([0-9A-Z][0-9A-Z\s]{2,8})\s*:\s*(.+)", head[0], re.I)
        ):
            # O Word oficial quebra às vezes o código ("REGISTRO M5 1 0");
            # o mnemônico publicado é M510.
            code = re.sub(r"\s+", "", match.group(1)).upper()
            if len(code) != 4 or not code.isalnum():
                continue
            current = code
            reg = registers.setdefault(current, ParsedRegister(code=current))
            if not reg.title:
                reg.title = norm(match.group(2))
            for row in rows[1:]:
                for cell in row:
                    text = norm(cell)
                    if level_match := level_occ.search(text):
                        reg.level = int(level_match.group(1))
                    if occ_match := occ_re.search(text):
                        reg.occurrence = occ_match.group(1).rstrip(".") or None
            continue
        if len(head) < 7 or norm(head[0]).lower() not in {"nº", "n", "no"}:
            continue
        if "campo" not in head[1].lower() or "tipo" not in head[3].lower():
            continue
        for row in rows[1:]:
            if len(row) < 7 or not norm(row[0]).isdigit():
                continue
            num = int(norm(row[0]))
            name = "".join(norm(row[1]).split())
            ftype = norm(row[3])
            if ftype not in {"C", "N"} or not name:
                continue
            tam = norm(row[4]) or "-"
            dec = norm(row[5]) or "-"
            valid_raw = norm(row[6])
            valid = [
                value.strip()
                for value in valid_raw.strip("[]").split(";")
                if value.strip() != "-"
                # Domain tokens are short codes; prose such as "Código da
                # Natureza Jurídica" is a reference, not a valid value.
                and re.fullmatch(r"[0-9A-Za-z_./:-]{1,8}", value.strip())
            ]
            registers.setdefault(current, ParsedRegister(code=current)).fields[num] = {
                "num": num,
                "name": name,
                "type": ftype,
                "tam": tam,
                "dec": dec,
                "description": norm(row[2]),
                "obrig": norm(row[7]) if len(row) > 7 else "",
                "valid_values": valid,
            }
    return registers


SOURCES: Final[tuple[Source, ...]] = (
    Source(
        "efd_contribuicoes",
        "005",
        "3.1.0",
        "2019-01-01",
        "2019-12-31",
        4175,
        "2019-10-07",
        "contrib_1_32_word.docx",
        _accounting_docx,
    ),
    Source(
        "efd_contribuicoes",
        "006",
        "3.2.0",
        "2020-01-01",
        "2099-12-31",
        5837,
        "2021-06-18",
        "contrib_1_35_word.docx",
        _accounting_docx,
    ),
    Source(
        "ecd",
        "008",
        "8.00",
        "2019-01-01",
        "2019-12-31",
        4217,
        "2019-11-01",
        "ecd_leiaute8_word.docx",
        _accounting_docx,
    ),
    Source(
        "ecd",
        "009",
        "9.00",
        "2020-01-01",
        "2099-12-31",
        7989,
        "2026-05-01",
        "ecd_leiaute9_word.docx",
        _accounting_docx,
    ),
    Source(
        "ecf",
        "006",
        "6.0",
        "2019-01-01",
        "2019-12-31",
        4271,
        "2019-12-01",
        "ecf_leiaute6_word.docx",
        _ecf_docx,
    ),
    Source(
        "ecf",
        "007",
        "7.0",
        "2020-01-01",
        "2020-12-31",
        5716,
        "2020-12-01",
        "ecf_leiaute7_word.docx",
        _ecf_docx,
    ),
    Source(
        "ecf",
        "008",
        "8.0",
        "2021-01-01",
        "2021-12-31",
        5971,
        "2022-01-01",
        "ecf_leiaute8_word.docx",
        _ecf_docx,
    ),
    Source(
        "ecf",
        "009",
        "9.0",
        "2022-01-01",
        "2022-12-31",
        7145,
        "2022-12-01",
        "ecf_leiaute9_word.docx",
        _ecf_docx,
    ),
    Source(
        "ecf",
        "010",
        "10.0",
        "2023-01-01",
        "2023-12-31",
        7306,
        "2024-04-01",
        "ecf_leiaute10_word.docx",
        _ecf_docx,
    ),
    Source(
        "ecf",
        "011",
        "11.0",
        "2024-01-01",
        "2024-12-31",
        7626,
        "2025-09-29",
        "ecf_leiaute11_word.docx",
        _ecf_docx,
    ),
    Source(
        "ecf",
        "012",
        "12.0",
        "2025-01-01",
        "2099-12-31",
        8004,
        "2026-05-20",
        "ecf_leiaute12_word.docx",
        _ecf_docx,
    ),
)


def _download(source: Source, offline: bool) -> Path:
    path = CACHE / source.cache_name
    if path.exists() and path.stat().st_size > 1000:
        return path
    if offline:
        raise FileNotFoundError(f"arquivo oficial em cache ausente: {path}")
    print(f"  baixando {source.source_page}", file=sys.stderr)
    with urllib.request.urlopen(source.source_url, timeout=180) as response:
        path.write_bytes(response.read())
    return path


def _document(source: Source, registers: dict[str, ParsedRegister]) -> dict[str, object]:
    for required in REQUIRED:
        if required not in registers:
            raise ValueError(
                f"{source.obrigacao}/{source.cod_ver}: registro oficial {required} ausente"
            )
    cleaned: dict[str, object] = {}
    for code, reg in sorted(registers.items()):
        if not re.fullmatch(r"[0-9A-Z]{4}", code):
            continue
        fields = [reg.fields[num] for num in sorted(reg.fields)]
        if not fields or fields[0]["name"] != "REG":
            continue
        if fields[0].get("valid_values"):
            # O código do registro nunca tem domínio restrito; notas de
            # "Valores Válidos" podem grudar na linha do REG no documento.
            fields[0]["valid_values"] = []
        cleaned[code] = {
            "title": reg.title,
            "level": reg.level,
            "occurrence": reg.occurrence,
            "fields": fields,
        }
    document: dict[str, object] = {
        "metadata": {
            "obrigacao": source.obrigacao,
            "cod_ver": source.cod_ver,
            "versao": source.versao,
            "valid_from": source.valid_from,
            "valid_to": source.valid_to,
            "source_url": source.source_url,
            "source_date": source.source_date,
            "source_page": source.source_page,
            "gap_filled_fields": 0,
        },
        "registers": cleaned,
    }
    # A ECF 12 (manual oficial, item 8004) não publica S990 para o bloco S;
    # o gerador não inventa registros ausentes da fonte oficial.
    validate_layout(document, enforce_block_closings=source.obrigacao != "ecf")
    return document


def generate(offline: bool, only: str | None) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, str]]] = {}
    for source in SOURCES:
        if only and not (source.obrigacao == only or source.cod_ver == only.zfill(3)):
            continue
        print(f"{source.obrigacao}/{source.cod_ver} ({source.versao})", file=sys.stderr)
        path = _download(source, offline)
        registers = source.parser(path)
        document = _document(source, registers)
        output = LAYOUTS / source.obrigacao
        output.mkdir(parents=True, exist_ok=True)
        target = output / f"{source.cod_ver}.json"
        target.write_text(
            json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        grouped.setdefault(source.obrigacao, []).append(
            {
                "cod_ver": source.cod_ver,
                "versao": source.versao,
                "valid_from": source.valid_from,
                "valid_to": source.valid_to,
                "source_url": source.source_url,
                "source_date": source.source_date,
                "file": f"{source.cod_ver}.json",
            }
        )
        print(f"  {len(registers)} registros → {target.relative_to(ROOT)}", file=sys.stderr)
    for obrigacao, entries in grouped.items():
        registry = {"obrigacao": obrigacao, "versions": entries}
        target = LAYOUTS / obrigacao / "registry.json"
        target.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="usa apenas arquivos em cache")
    parser.add_argument("--only", help="gera apenas uma obrigação ou COD_VER")
    args = parser.parse_args(argv)
    generate(args.offline, args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
