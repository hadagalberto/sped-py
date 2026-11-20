#!/usr/bin/env python3
"""Gera os arquivos JSON de leiaute versionados a partir de fontes oficiais.

Fontes (todas oficiais, buscadas e citadas; nada é inventado):

* **Portal SPED (Receita Federal)** — "Manuais e Guias Práticos" e
  "Histórico Guias Prático": ``http://sped.rfb.gov.br/item/show/1573`` e
  ``http://sped.rfb.gov.br/item/show/3035``.  Cada guia anual é baixado por
  ``http://sped.rfb.gov.br/arquivo/download/<item>``.  É a fonte da lista de
  registros e da vigência de cada COD_VER.
* **CONFAZ** — "Manual de Orientação da EFD ICMS IPI" (Notas Técnicas) em
  ``https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais``.  fonte
  primária das tabelas de campos de cada versão.
* **CONFAZ** — Guia Prático EFD ICMS/IPI v3.2.4 em formato DOCX:
  ``https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais/guia_pratico_efd___versao_3-2-4.docx``.
  Suas tabelas são estruturadas (não dependem de geometria de PDF) e são
  usadas para completar linhas que a extração dos PDFs antigos perde.

A tabela oficial de COD_VER (Ato COTEPE/ICMS 44/18 e alterações), reproduzida
no Apêndice A das Notas Técnicas, é::

    013 = 3.0.0 (01/01/2019)   014 = 3.0.3 (01/01/2020)
    015 = 3.0.6 (01/01/2021)   016 = 3.0.7 (01/01/2022)
    017 = 3.1.1 (01/01/2023)   018 = 3.1.4 (01/01/2024)
    019 = 3.1.7 (01/01/2025)   020 = 3.2.1 (01/01/2026)
    021 = 3.2.3 (01/01/2027)

Uso::

    python scripts/generate_layouts.py              # baixa e gera tudo
    python scripts/generate_layouts.py --offline    # usa tmp/pdf em cache
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent
CACHE: Final = ROOT / "tmp" / "pdf"
OUTPUT: Final = ROOT / "src" / "sped" / "layouts" / "efd_icmsipi"
PORTAL: Final = "http://sped.rfb.gov.br"
CONFAZ: Final = "https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais"
DOCX_URL: Final = f"{CONFAZ}/guia_pratico_efd___versao_3-2-4.docx"
W: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

REG_RE: Final = re.compile(r"^REGISTRO\s+([0-9A-Z]{4})\s*[:\-\u2013\u2014]\s*(.+)", re.I)
NIVEL_RE: Final = re.compile(r"^N[íi]vel\s+hier[áa]rquico\s*[-\u2013\u2014:]*\s*(\d+)", re.I)
OCORR_RE: Final = re.compile(r"^Ocorr[êe]ncia\s*[-\u2013\u2014:]*\s*(.+)", re.I)
HEADER_RE: Final = re.compile(r"^N[ºo]$")
NUM_RE: Final = re.compile(r"^\d{2}$")
FIELD_NAME_RE: Final = re.compile(r"[\w\*\-\.]+", re.UNICODE)
VALUES_RE: Final = re.compile(
    r"Campo\s+(\d{2})\s*\(([A-Z][A-Z0-9_]*)\)\s*[:\-\u2013\u2014]\s*"
    r"Valores?\s+V[áa]lid[oa]s?\s*:?\s*\[([^\]]*)\]",
    re.I,
)


@dataclass(frozen=True, slots=True)
class Source:
    """Official sources and validity metadata for one COD_VER."""

    cod_ver: str
    versao: str
    valid_from: str
    valid_to: str
    guia_item: int
    guia_date: str
    nt_url: str = ""
    nt_date: str = ""

    @property
    def guia_url(self) -> str:
        return f"{PORTAL}/arquivo/download/{self.guia_item}"

    @property
    def page_url(self) -> str:
        return f"{PORTAL}/item/show/{self.guia_item}"

    @property
    def source_url(self) -> str:
        return self.nt_url or self.guia_url

    @property
    def source_date(self) -> str:
        return self.nt_date or self.guia_date


SOURCES: Final[tuple[Source, ...]] = (
    Source("013", "3.0.0", "2019-01-01", "2019-12-31", 4222, "2019-01-17"),
    Source("014", "3.0.3", "2020-01-01", "2020-12-31", 5699, "2019-10-14"),
    Source(
        "015",
        "3.0.6",
        "2021-01-01",
        "2021-12-31",
        7233,
        "2020-11-19",
        nt_url=f"{CONFAZ}/NT_EFD%20ICMS%20IPI%202020.001%20v1.1%20-%20MOC",
        nt_date="2020-08-01",
    ),
    Source("016", "3.0.7", "2022-01-01", "2022-12-31", 7234, "2021-08-26"),
    Source(
        "017",
        "3.1.1",
        "2023-01-01",
        "2023-12-31",
        7238,
        "2022-08-04",
        nt_url=f"{CONFAZ}/nt_efd-icms-ipi-2022-001-v1-0.pdf",
        nt_date="2022-05-01",
    ),
    Source(
        "018",
        "3.1.4",
        "2024-01-01",
        "2024-12-31",
        7277,
        "2023-05-18",
        nt_url=f"{CONFAZ}/nota_tecnica_efd_icms_ipi_2023-001_v1-2.pdf",
        nt_date="2023-08-01",
    ),
    Source(
        "019",
        "3.1.7",
        "2025-01-01",
        "2025-12-31",
        8011,
        "2024-08-14",
        nt_url=f"{PORTAL}/arquivo/download/7545",
        nt_date="2024-09-25",
    ),
    Source(
        "020",
        "3.2.1",
        "2026-01-01",
        "2026-12-31",
        7900,
        "2025-12-01",
        nt_url=f"{CONFAZ}/06___anexo_2.pdf",
        nt_date="2025-05-01",
    ),
    Source(
        "021",
        "3.2.3",
        "2027-01-01",
        "2027-12-31",
        8112,
        "2026-04-02",
        nt_url=f"{CONFAZ}/a05___nt_2026-001_v1-0___anexo_iv.pdf",
        nt_date="2026-05-01",
    ),
)


@dataclass
class ParsedRegister:
    code: str
    title: str = ""
    level: int | None = None
    occurrence: str | None = None
    fields: dict[int, dict[str, Any]] = field(default_factory=dict)


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


def field_name(text: str | None) -> str:
    """Remove artefatos de quebra de linha dentro do mnemônico oficial."""
    return re.sub(r"\s+", "", norm(text))


def _download(url: str, path: Path, offline: bool) -> Path:
    if path.exists() and path.stat().st_size > 1000:
        return path
    if offline:
        raise FileNotFoundError(f"arquivo em cache ausente: {path}")
    print(f"  baixando {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=180) as response:
        path.write_bytes(response.read())
    return path


def _row_to_field(row: Sequence[str | None]) -> dict[str, Any] | None:
    cells = [norm(cell) for cell in row]
    if len(cells) < 6 or not NUM_RE.match(cells[0]):
        return None
    ftype = cells[3]
    if ftype not in {"C", "N"}:
        return None
    tam = cells[4] or "-"
    dec = cells[5] or "-"
    if not re.fullmatch(r"\d{1,5}\*?|-|65536", tam) or not re.fullmatch(r"\d{1,6}|-", dec):
        return None
    obrig = " ".join(cells[6:]) if len(cells) > 6 else ""
    return {
        "num": int(cells[0]),
        "name": field_name(cells[1]),
        "type": ftype,
        "tam": tam,
        "dec": dec,
        "description": cells[2],
        "obrig": obrig,
        "valid_values": [],
    }


def parse_docx(path: Path) -> dict[str, ParsedRegister]:
    """Extrai tabelas estruturadas do Guia Prático DOCX (fonte completa)."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find(W + "body")
    if body is None:
        raise ValueError("DOCX sem corpo")
    registers: dict[str, ParsedRegister] = {}
    current = ""
    for element in body:
        if element.tag == W + "p":
            text = norm("".join(node.text or "" for node in element.iter(W + "t")))
            if match := REG_RE.match(text):
                code = match.group(1).upper()
                current = code
                reg = registers.setdefault(
                    code, ParsedRegister(code=code, title=match.group(2).strip())
                )
                if not reg.title:
                    reg.title = match.group(2).strip()
            elif current and registers[current].level is None:
                if match := NIVEL_RE.match(text):
                    registers[current].level = int(match.group(1))
            elif current and registers[current].occurrence is None:
                if match := OCORR_RE.match(text):
                    registers[current].occurrence = match.group(1).rstrip(".")
        elif element.tag == W + "tbl" and current:
            rows = [
                [
                    " ".join(node.text or "" for node in tc.iter(W + "t"))
                    for tc in tr.findall(W + "tc")
                ]
                for tr in element.findall(W + "tr")
            ]
            if not rows:
                continue
            head = [norm(cell) for cell in rows[0]]
            if (
                len(head) < 6
                or not HEADER_RE.match(field_name(head[0]))
                or head[1].lower() != "campo"
            ):
                continue
            for row in rows[1:]:
                parsed = _row_to_field(row)
                if parsed is not None:
                    registers[current].fields[parsed["num"]] = parsed
    return registers


def parse_pdf(path: Path) -> dict[str, ParsedRegister]:
    """Extrai tabelas de um guia/manual oficial PDF por geometria de células.

    ``pdfplumber`` é dependência opcional (extra ``[tools]``): importá-la aqui
    mantém o módulo importável — e o mypy verificável — sem ela instalada.
    """
    try:
        pdfplumber: Any = importlib.import_module("pdfplumber")
    except ModuleNotFoundError as exc:
        raise RuntimeError("instale o extra [tools] para gerar leiautes") from exc
    registers: dict[str, ParsedRegister] = {}
    current = ""
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            raw_lines = page.extract_text_lines()
            lines = [norm(line["text"]) for line in raw_lines]
            events: list[tuple[float, str, str | None, list[list[str | None]] | None]] = []
            for raw_line in raw_lines:
                text = norm(raw_line["text"])
                if match := REG_RE.match(text):
                    events.append((float(raw_line["top"]), "reg", match.group(1).upper(), None))
            for pdf_table in page.find_tables():
                extracted: Any = pdf_table.extract()
                if extracted:
                    events.append((float(pdf_table.bbox[1]), "table", None, extracted))
            events.sort(key=lambda event: event[0])
            for _top, kind, code, extracted in events:
                if kind == "reg":
                    current = code or ""
                    if current:
                        reg = registers.setdefault(current, ParsedRegister(code=current, title=""))
                        if not reg.title:
                            reg.title = ""
                    continue
                if not current or not extracted:
                    continue
                head = [norm(cell) for cell in extracted[0]]
                is_header = (
                    len(head) >= 6
                    and bool(HEADER_RE.match(field_name(head[0])))
                    and head[1].lower() == "campo"
                    and head[3].lower() == "tipo"
                )
                rows = extracted[1:] if is_header else extracted
                for row in rows:
                    parsed = _row_to_field(row)
                    if parsed is not None:
                        registers.setdefault(current, ParsedRegister(code=current)).fields[
                            parsed["num"]
                        ] = parsed
            for line in lines:
                if not current or current not in registers:
                    continue
                reg = registers[current]
                if reg.level is None:
                    if match := NIVEL_RE.match(line):
                        reg.level = int(match.group(1))
                if reg.occurrence is None:
                    if match := OCORR_RE.match(line):
                        reg.occurrence = match.group(1).rstrip(".")
                if match := VALUES_RE.search(line):
                    num = int(match.group(1))
                    tokens = [
                        token.strip()
                        for token in re.split(r"[,;]", match.group(3))
                        if token.strip() and len(token.strip()) <= 8
                    ]
                    if num in reg.fields:
                        reg.fields[num]["valid_values"] = tokens
    return registers


def merge(
    source: Source,
    authoritative: dict[str, ParsedRegister],
    complete: dict[str, ParsedRegister],
) -> tuple[dict[str, Any], int]:
    """Combina a fonte da versão com a tabela completa, preenchendo lacunas.

    Só são preenchidas lacunas de numeração **dentro** de um registro já
    presente na fonte oficial da versão: se o campo ``nn`` falta entre o 01 e
    o último campo extraído, trata-se de perda da extração (o PDF não desenha
    a linha), não de campo inexistente.  Registros ausentes da versão são
    descartados.
    """
    merged: dict[str, Any] = {}
    gap_count = 0
    for code, reg in authoritative.items():
        base = complete.get(code)
        if base is None:
            continue
        max_num = max(reg.fields, default=0)
        if max_num == 0:
            fields_source = base.fields
            gap_count += len(base.fields)
        else:
            fields_source = {}
            for num in range(1, max_num + 1):
                if num in reg.fields:
                    fields_source[num] = reg.fields[num]
                elif num in base.fields:
                    fields_source[num] = base.fields[num]
                    gap_count += 1
        ordered = [fields_source[num] for num in sorted(fields_source)]
        if ordered and ordered[0]["name"] == "REG":
            # Notas de "Valores Válidos" do PDF podem grudar na linha do REG;
            # o código do registro nunca tem domínio restrito.
            ordered[0]["valid_values"] = []
        if not ordered or ordered[0]["num"] != 1 or ordered[0]["name"] != "REG":
            continue
        merged[code] = {
            "title": base.title or reg.title,
            "level": reg.level if reg.level is not None else base.level,
            "occurrence": reg.occurrence if reg.occurrence is not None else base.occurrence,
            "fields": ordered,
        }
    structural = {
        "0000",
        "0001",
        "0005",
        "0100",
        "0150",
        "0190",
        "0200",
        "0990",
        "C001",
        "C100",
        "C170",
        "C190",
        "C990",
        "E001",
        "E110",
        "E990",
        "9001",
        "9900",
        "9990",
        "9999",
    }
    structural.update(f"{block}990" for block in {code[0] for code in merged})
    for required in structural:
        if required not in merged and required in complete:
            merged[required] = {
                "title": complete[required].title,
                "level": complete[required].level,
                "occurrence": complete[required].occurrence,
                "fields": [complete[required].fields[n] for n in sorted(complete[required].fields)],
            }
    return dict(sorted(merged.items())), gap_count


def validate_layout(document: dict[str, Any], *, enforce_block_closings: bool = True) -> None:
    """Validação rígida antes de gravar: nada inválido é escrito.

    ``enforce_block_closings=False`` é usado apenas quando o próprio manual
    oficial não publica um ``x990`` para determinado bloco (ex.: bloco S do
    leiaute 12 da ECF); o gerador nunca inventa esse registro.
    """
    problems: list[str] = []
    registers = document["registers"]
    for required in ("0000", "0001", "0990", "9001", "9900", "9990", "9999"):
        if required not in registers:
            problems.append(f"registro estrutural ausente: {required}")
    for code, reg in registers.items():
        if not re.fullmatch(r"[0-9A-Z]{4}", code):
            problems.append(f"código inválido: {code}")
        fields = reg["fields"]
        if not fields or fields[0]["name"] != "REG":
            problems.append(f"{code}: campo 01 não é REG")
        for index, field_def in enumerate(fields, start=1):
            if field_def["num"] < index or (
                index > 1 and field_def["num"] <= fields[index - 2]["num"]
            ):
                problems.append(f"{code}: numeração não crescente em {field_def['num']}")
                break
            if field_def["type"] not in {"C", "N"}:
                problems.append(f"{code}.{index}: tipo inválido")
        block = code[0]
        if enforce_block_closings and code.endswith("001") and f"{block}990" not in registers:
            problems.append(f"bloco {block}: sem {block}990")
    if problems:
        raise ValueError("; ".join(problems[:20]))


def generate(offline: bool, only: str | None) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    docx_path = _download(DOCX_URL, CACHE / "guia_3-2-4.docx", offline)
    print("analisando Guia Prático DOCX …", file=sys.stderr)
    complete = parse_docx(docx_path)
    print(
        f"  {len(complete)} registros, {sum(len(r.fields) for r in complete.values())} campos",
        file=sys.stderr,
    )

    entries: list[dict[str, str]] = []
    for source in SOURCES:
        if only and source.cod_ver != only.zfill(3):
            continue
        print(f"COD_VER {source.cod_ver} ({source.versao})", file=sys.stderr)
        primary_pdf = _download(source.source_url, CACHE / f"primary_{source.cod_ver}.pdf", offline)
        authoritative = parse_pdf(primary_pdf)
        registers, gaps = merge(source, authoritative, complete)
        document = {
            "metadata": {
                "obrigacao": "efd_icmsipi",
                "cod_ver": source.cod_ver,
                "versao": source.versao,
                "valid_from": source.valid_from,
                "valid_to": source.valid_to,
                "source_url": source.source_url,
                "source_date": source.source_date,
                "source_page": source.page_url,
                "complete_table_source": DOCX_URL,
                "gap_filled_fields": gaps,
            },
            "registers": registers,
        }
        validate_layout(document)
        target = OUTPUT / f"{source.cod_ver}.json"
        target.write_text(
            json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        entries.append(
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
        print(
            f"  {len(registers)} registros, {gaps} lacunas preenchidas → {target.name}",
            file=sys.stderr,
        )
    registry = {"obrigacao": "efd_icmsipi", "versions": entries}
    (OUTPUT / "registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="usa apenas arquivos em cache")
    parser.add_argument("--only", help="gera apenas um COD_VER")
    args = parser.parse_args(argv)
    generate(args.offline, args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
