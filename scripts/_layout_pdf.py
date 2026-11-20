"""Parser das tabelas de leiaute dos documentos oficiais do SPED (PDF).

Lê o **Guia Prático da EFD ICMS/IPI** e as **Notas Técnicas** publicados pela
Receita Federal (Portal SPED) e extrai, para cada registro, a tabela de campos:

    Nº | Campo | Descrição | Tipo | Tam | Dec | Obrig (ou Entr | Saída)

As Notas Técnicas usam a mesma tabela sem as colunas de obrigatoriedade
(``Nº | Campo | Descrição | Tipo | Tam | Dec``).

Estratégia de extração
----------------------
A extração baseada em células do pdfplumber é frágil nestes PDFs: linhas
verticais duplicadas dividem colunas estreitas em duas células idênticas,
células mescladas verticalmente (ex.: "Não apresentar" na coluna Entr do
registro C176) exibem o texto uma única vez para várias linhas, e tabelas sem
linhas horizontais em parte das linhas são ignoradas. Por isso este módulo
trabalha com **geometria de palavras**:

1. A linha de cabeçalho (``Nº Campo Descrição Tipo Tam Dec ...``) define as
   faixas horizontais (bandas x) de cada coluna a partir das posições das
   palavras do próprio cabeçalho;
2. As palavras ``NN`` (dois dígitos) na coluna "Nº" definem as linhas
   (bandas y) de cada campo, inclusive quando a descrição quebra em várias
   linhas;
3. Cada palavra da página é atribuída a uma coluna pelo centro x e a uma
   linha pelo centro y — sem depender de células desenhadas;
4. Nas colunas pequenas (Tipo/Tam/Dec/obrigatoriedade), as arestas
   horizontais desenhadas que atravessam a banda definem "faixas verticais":
   quando uma faixa cobre várias linhas e seu texto é um único valor válido,
   ele se aplica a todas as linhas cobertas (célula mesclada).

O parser é tolerante a artefatos, porém **estrito na validação**: cada
registro precisa ter campos numerados sequencialmente a partir de 01, o campo
01 (REG) precisa existir, e os valores de Tipo/Tam/Dec/Obrig precisam
pertencer aos domínios oficiais descritos na seção 2.7.1 da Nota Técnica.

Nada aqui inventa posições ou regras: tudo vem do texto extraído dos PDFs
oficiais; o resultado é verificado em ``scripts/generate_layouts.py``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

import pdfplumber
from pdfplumber.page import Page

#: Registro para o qual imprimir detalhes de extração (variável de ambiente).
_DEBUG_REG: Final = os.environ.get("SPED_LAYOUT_DEBUG", "")


def _debug(reg_code: str, msg: str) -> None:
    if _DEBUG_REG and reg_code == _DEBUG_REG:
        print(f"[debug {reg_code}] {msg}")

# ---------------------------------------------------------------------------
# Expressões regulares dos elementos textuais do documento
# ---------------------------------------------------------------------------

#: Cabeçalho de registro: "REGISTRO C170: ITENS DO DOCUMENTO (CÓDIGO 01, ...)".
REG_HEADER_RE: Final = re.compile(r"^REGISTRO ([0-9A-Z]{4})\s*[:\u2013\u2014-]\s*(.+)$")

#: "Nível hierárquico - 3" / "Nível hierárquico: 2" (aceito em qualquer ponto da linha).
NIVEL_RE: Final = re.compile(r"N[íi]vel\s+hier[áa]rquico\s*[-\u2013\u2014:]*\s*(\d+)")

#: "Ocorrência – 1:N" / "Ocorrência: um por arquivo".
OCORR_RE: Final = re.compile(r"Ocorr[êe]ncia\s*[-\u2013\u2014:]*\s*(.+?)\s*$")

#: Linha "Observações:" que encerra a tabela de campos de um registro.
OBS_LINE_RE: Final = re.compile(r"^Observa[çc][õo]es\b.*$")

#: Nota de campo com lista de valores válidos entre colchetes.
VALORES_VALIDOS_RE: Final = re.compile(
    r"Campo\s+(\d{2})\s*\(([A-Z][A-Z0-9_]*)\)\s*[-\u2013\u2014]\s*"
    r"Valores?\s+V[áa]lid[oa]s?\s*:?\s*\[([^\]]*)\]"
)

#: Linha de cabeçalho da tabela de campos (com ou sem colunas de obrigatoriedade).
TABLE_HEADER_LINE_RE: Final = re.compile(
    r"^N[ºo]\s+Campo\s+Descri[çc][ãa]o\s+Tipo\s+Tam\s+Dec\b.*$"
)

#: Rótulos das colunas do cabeçalho, na ordem esquerda→direita.
_HEADER_LABELS: Final = ("Nº", "Campo", "Descrição", "Tipo", "Tam", "Dec")

#: Rodapés/cabeçalhos de página e linhas "Observação:" (palavras destas faixas
#: y são descartadas na extração de células).
JUNK_LINE_RE: Final = re.compile(
    r"^(?:Guia\s+Pr[áa]tico\s+EFD|NT\s+\d{4}\.\d+|Atualiza[çc][ãa]o:|"
    r"P[áa]gina\s+\d+\s+de\s+\d+|Observa[çc][ãa]o)\b",
    re.IGNORECASE,
)

#: Célula "Nº" — exatamente dois dígitos (os anexos usam códigos de 4 dígitos).
NUM_CELL_RE: Final = re.compile(r"^\d{2}$")

#: Nome de campo — mnemônico em maiúsculas, com acentos (0500 tem "NÍVEL").
NAME_CELL_RE: Final = re.compile(r"^[A-ZÀ-ÖØ-Þ][A-Z0-9_À-ÖØ-Þ]{0,59}$")

#: Tipo oficial: N numérico, C alfanumérico (seção 2.7.1 da NT).
TIPO_CELL_RE: Final = re.compile(r"^[CN]$")

#: Tamanho oficial: dígitos com "*" opcional (exato), "-", ou "65536".
TAM_CELL_RE: Final = re.compile(r"^(?:\d{1,5}\*?|-|65536)$")

#: Decimais oficiais: dígitos ou "-" (célula vazia conta como ausente).
DEC_CELL_RE: Final = re.compile(r"^(?:\d{1,2}|-)?$")

#: Obrigatoriedade: "O", "OC", "O*", "Não apresentar", "Não se aplica",
#: "Não informar". Células com texto adicional (ex.: "N (informar no 0205)"
#: no registro 0200 do Guia 3.2.2) são mantidas cruas — sem inventar leitura.
OBRIG_CELL_RE: Final = re.compile(
    r"^(?:O|OC|O\*|N[ãa]o\s+(?:apresentar(?:\s+este\s+campo)?|se\s+aplica|informar))$",
    re.IGNORECASE,
)

#: Frases completas de obrigatoriedade em várias palavras.
_OBRIG_PHRASES: Final = (
    "Não apresentar este campo",
    "Não apresentar",
    "Não se aplica",
    "Não informar",
)

#: Palavras de fragmento de frases quebradas entre linhas/células.
_FRAGMENT_WORDS: Final = frozenset(
    {"apresentar", "este", "campo", "se", "aplica", "Não", "NÃO", "informar"}
)

# ---------------------------------------------------------------------------
# Modelo de dados intermediário
# ---------------------------------------------------------------------------


@dataclass
class ParsedField:
    """Um campo do registro, com os valores crus extraídos do PDF."""

    num: int
    name: str
    description: str = ""
    ftype: str = ""  # "C" ou "N"
    tam: str = ""  # cru: "004", "004*", "-", "65536" (vazio = ausente)
    dec: str = ""  # cru: "02", "-" (vazio = ausente)
    obrig: tuple[str, ...] = ()  # 1 ou 2 valores crus ("O", "OC", "Não apresentar")
    valid_values: tuple[str, ...] = ()  # de "Valores Válidos: [...]" quando presentes


@dataclass
class ParsedRegister:
    """Um registro com sua tabela de campos e observações hierárquicas."""

    code: str
    title: str
    fields: list[ParsedField] = field(default_factory=list)
    level: int | None = None
    occurrence: str | None = None
    page_first: int | None = None
    page_last: int | None = None

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def field_types(self) -> dict[str, tuple[str, str, str]]:
        """Mapeia nome do campo -> (tipo, tam, dec), para comparações entre documentos."""
        return {f.name: (f.ftype, f.tam, f.dec) for f in self.fields}


@dataclass
class LayoutParse:
    """Resultado completo do parse de um documento."""

    registers: dict[str, ParsedRegister]
    diagnostics: list[str]
    duplicates: list[str]


# ---------------------------------------------------------------------------
# Bandas de colunas derivadas do cabeçalho
# ---------------------------------------------------------------------------


@dataclass
class _ColumnBands:
    """Faixas x das colunas de uma tabela de campos."""

    num: tuple[float, float]
    campo: tuple[float, float]
    descr: tuple[float, float]
    tipo: tuple[float, float]
    tam: tuple[float, float]
    dec: tuple[float, float]
    obrig: list[tuple[float, float]]  # 0, 1 ou 2 colunas (NT=0, Guia=1 ou 2)

    def all_bands(self) -> list[tuple[str, tuple[float, float]]]:
        cols: list[tuple[str, tuple[float, float]]] = [
            ("num", self.num),
            ("campo", self.campo),
            ("descr", self.descr),
            ("tipo", self.tipo),
            ("tam", self.tam),
            ("dec", self.dec),
        ]
        cols.extend(("obrig", band) for band in self.obrig)
        return cols


def _header_bands(
    page: Page, header_line: dict[str, object], n_obrig: int
) -> _ColumnBands | None:
    """Calcula as bandas x de cada coluna a partir das palavras do cabeçalho."""
    top = float(header_line["top"])  # type: ignore[arg-type]
    bottom = float(header_line["bottom"])  # type: ignore[arg-type]
    words = [
        w
        for w in page.extract_words()
        if w["top"] >= top - 1 and w["bottom"] <= bottom + 1
    ]
    words.sort(key=lambda w: w["x0"])
    labels = [w["text"] for w in words]
    if labels[:6] != list(_HEADER_LABELS):
        return None

    # Fronteiras: borda esquerda da 1ª coluna, midpoints entre palavras
    # vizinhas e borda direita da última.
    bounds = [words[0]["x0"] - 14]
    for i in range(len(words) - 1):
        bounds.append((words[i]["x1"] + words[i + 1]["x0"]) / 2)
    bounds.append(words[-1]["x1"] + 40)
    cols = [(bounds[i], bounds[i + 1]) for i in range(len(words))]

    return _ColumnBands(
        num=cols[0],
        campo=cols[1],
        descr=cols[2],
        tipo=cols[3],
        tam=cols[4],
        dec=cols[5],
        obrig=cols[6 : 6 + n_obrig],
    )


def _n_obrig_from_header(text: str) -> int:
    """Número de colunas de obrigatoriedade no cabeçalho (0=NT, 1=Obrig, 2=Entr/Saída)."""
    if re.search(r"Entr", text) and re.search(r"Sa[íi]da", text):
        return 2
    if "Obrig" in text:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Extração de linhas de uma região da página
# ---------------------------------------------------------------------------


@dataclass
class _RowBand:
    """Linha de campo: banda y + número do campo."""

    num: int
    top: float
    bottom: float


def _junk_y_ranges(page: Page) -> list[tuple[float, float]]:
    """Faixas y de cabeçalhos/rodapés de página, para excluir suas palavras."""
    ranges: list[tuple[float, float]] = []
    for line in page.extract_text_lines():
        if JUNK_LINE_RE.match(line["text"].strip()):
            ranges.append((float(line["top"]) - 1, float(line["bottom"]) + 1))
    return ranges


def _words_in_region(
    page: Page, x0: float, x1: float, top: float, bottom: float
) -> list[dict[str, float]]:
    """Palavras cujo centro x está na banda e cujo centro y está na região."""
    out = []
    for w in page.extract_words():
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        if x0 <= cx <= x1 and top <= cy <= bottom:
            out.append(w)
    return out


def _row_bands(
    page: Page,
    bands: _ColumnBands,
    top: float,
    bottom: float,
    junk: Sequence[tuple[float, float]],
) -> list[_RowBand]:
    """Linhas de campo da região, pelas palavras NN da coluna Nº."""
    anchors = []
    for w in _words_in_region(page, bands.num[0], bands.num[1], top, bottom):
        text = w["text"]
        if NUM_CELL_RE.match(text):
            if any(j0 <= (w["top"] + w["bottom"]) / 2 <= j1 for j0, j1 in junk):
                continue
            anchors.append((int(text), float(w["top"]), float(w["bottom"])))
    anchors.sort(key=lambda a: a[1])
    rows: list[_RowBand] = []
    for i, (num, a_top, a_bottom) in enumerate(anchors):
        if i + 1 < len(anchors):
            next_top = anchors[i + 1][1] - 1.5
        else:
            # Última linha da região: fecha na borda inferior desenhada da
            # tabela, se houver, para não engolir prosa logo após a tabela.
            next_top = _table_bottom_edge(page, bands.num, a_bottom, bottom) or bottom
        rows.append(_RowBand(num=num, top=a_top - 1.5, bottom=next_top))
    return rows


def _table_bottom_edge(
    page: Page,
    band: tuple[float, float],
    below: float,
    limit: float,
) -> float | None:
    """Topo da primeira aresta horizontal que atravessa a banda abaixo de ``below``."""
    width = band[1] - band[0]
    best: float | None = None
    for e in page.edges:
        if e.get("orientation") != "h":
            continue
        etop = float(e["top"])
        ex0, ex1 = float(e["x0"]), float(e["x1"])
        if etop < below or etop > limit:
            continue
        if ex1 - ex0 < max(0.5 * width, 10):
            continue
        if ex0 <= band[0] + 1 and ex1 >= band[1] - 1:
            if best is None or etop < best:
                best = etop
    return best


def _cell_words(
    page: Page,
    band: tuple[float, float],
    row: _RowBand,
    junk: Sequence[tuple[float, float]],
) -> list[dict[str, float]]:
    """Palavras de uma célula, ordenadas por linha e coluna."""
    words = _words_in_region(page, band[0], band[1], row.top, row.bottom)
    words = [
        w
        for w in words
        if not any(j0 <= (w["top"] + w["bottom"]) / 2 <= j1 for j0, j1 in junk)
    ]
    words.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
    return words


def _strip_assignments(
    page: Page,
    band: tuple[float, float],
    rows: Sequence[_RowBand],
    top: float,
    bottom: float,
    junk: Sequence[tuple[float, float]],
    is_value: "Callable[[str], bool]",
) -> dict[int, str]:
    """Células por faixas verticais (arestas horizontais) de uma coluna.

    Cada faixa entre duas arestas horizontais que atravessam a banda contém o
    texto de uma célula. Uma faixa que cobre várias linhas com um único valor
    válido é uma célula mesclada (ex.: "Não apresentar" na coluna Entr do
    C176) e o valor vale para todas as linhas cobertas.
    """
    width = band[1] - band[0]
    edges: list[float] = []
    for e in page.edges:
        if e.get("orientation") != "h":
            continue
        ex0, ex1 = float(e["x0"]), float(e["x1"])
        etop = float(e["top"])
        # A aresta pode ser mais estreita que a banda derivada do cabeçalho
        # (as fronteiras desenhadas ficam dentro da coluna); exige 70%.
        overlap = min(ex1, band[1]) - max(ex0, band[0])
        if overlap < 0.7 * width:
            continue
        if top - 2 <= etop <= bottom + 2:
            edges.append(round(etop, 1))
    edges = sorted(set(edges))
    if not edges:
        return {}

    out: dict[int, str] = {}
    for k in range(len(edges) - 1):
        y0, y1 = edges[k], edges[k + 1]
        if y1 - y0 < 6:  # aresta dupla, não faixa real
            continue
        covered = [
            r
            for r in rows
            if y0 <= (r.top + r.bottom) / 2 < y1  # âncoras dentro da faixa
        ]
        if len(covered) < 2:
            continue
        words = _words_in_region(page, band[0], band[1], y0, y1)
        words = [
            w
            for w in words
            if not any(j0 <= (w["top"] + w["bottom"]) / 2 <= j1 for j0, j1 in junk)
        ]
        words.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
        text = re.sub(r"\s+", " ", " ".join(w["text"] for w in words)).strip()
        if text and is_value(text):
            for r in covered:
                out[r.num] = text  # célula mesclada: valor para todas
    return out


def _is_obrig_value(text: str) -> bool:
    values = _normalize_obrig_cell(text)
    return len(values) == 1 and bool(OBRIG_CELL_RE.match(values[0]))


def _strip_token(tok: str) -> str:
    """Remove apóstrofos/aspas tipográficos de rótulos (ex.: "N’" no C179)."""
    return tok.strip("\u2019\u2018'\"").strip()


def _join_description(words: Sequence[dict[str, float]]) -> str:
    """Junta as palavras da descrição em texto corrido."""
    return re.sub(r"\s+", " ", " ".join(w["text"] for w in words)).strip()


def _normalize_obrig_cell(text: str) -> tuple[str, ...]:
    """Divide o texto de uma célula de obrigatoriedade em valores (1 ou 2)."""
    t = re.sub(r"\s+", " ", text).strip()
    for phrase in _OBRIG_PHRASES:
        t = t.replace(phrase, f"\x00{phrase}\x00")
    parts = [p.strip(" \x00") for p in t.split("\x00")]
    values = [p for p in parts if p]
    if all(OBRIG_CELL_RE.match(v) for v in values):
        return tuple(values)
    return (t,) if t else ()


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------


@dataclass
class _ParserState:
    """Estado do parser entre páginas/linhas."""

    current: ParsedRegister | None = None
    bands: _ColumnBands | None = None
    seen_occ: bool = False
    registers: dict[str, ParsedRegister] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


@dataclass
class _StreamEvent:
    """Evento ordenado por posição vertical na página."""

    top: float
    kind: str  # "reg" | "header" | "nivel" | "ocorr" | "valores"
    line: dict[str, object]
    code: str = ""
    title: str = ""
    level: int = 0
    occurrence: str = ""
    n_obrig: int = 0
    field_num: int = 0
    field_name: str = ""
    raw_values: str = ""


def _page_events(lines: Sequence[dict[str, object]]) -> list[_StreamEvent]:
    """Classifica as linhas de texto da página em eventos ordenados."""
    events: list[_StreamEvent] = []
    for line in lines:
        raw: str = str(line["text"])
        text = re.sub(r"\s+", " ", raw).strip()
        if not text:
            continue
        m = REG_HEADER_RE.match(text)
        if m:
            events.append(
                _StreamEvent(
                    top=float(line["top"]), kind="reg", line=dict(line),
                    code=m.group(1), title=m.group(2),
                )
            )
            continue
        if TABLE_HEADER_LINE_RE.match(text):
            events.append(
                _StreamEvent(
                    top=float(line["top"]), kind="header", line=dict(line),
                    n_obrig=_n_obrig_from_header(text),
                )
            )
            continue
        m = NIVEL_RE.search(text)
        if m:
            events.append(
                _StreamEvent(
                    top=float(line["top"]), kind="nivel", line=dict(line),
                    level=int(m.group(1)),
                )
            )
            continue
        m = OCORR_RE.search(text)
        if m:
            events.append(
                _StreamEvent(
                    top=float(line["top"]), kind="ocorr", line=dict(line),
                    occurrence=m.group(1).rstrip("."),
                )
            )
            continue
        if OBS_LINE_RE.match(text):
            events.append(
                _StreamEvent(top=float(line["top"]), kind="obs", line=dict(line))
            )
            continue
        m = VALORES_VALIDOS_RE.search(raw)
        if m:
            events.append(
                _StreamEvent(
                    top=float(line["top"]), kind="valores", line=dict(line),
                    field_num=int(m.group(1)), field_name=m.group(2),
                    raw_values=m.group(3),
                )
            )
    events.sort(key=lambda e: e.top)
    return events


def _process_page(page: Page, page_no: int, state: _ParserState) -> None:
    """Processa uma página do documento."""
    lines = page.extract_text_lines()
    events = _page_events(lines)
    junk = _junk_y_ranges(page)
    page_words = page.extract_words()
    page_top = min((w["top"] for w in page_words), default=0.0)
    page_bottom = max((w["bottom"] for w in page_words), default=1000.0)

    # Tabela continuada da página anterior, sem cabeçalho nesta página:
    # a região vai do topo da página até o primeiro evento.
    if (
        state.current is not None
        and not state.seen_occ
        and state.bands is not None
        and (not events or events[0].kind != "header")
    ):
        first_top = events[0].top if events else page_bottom
        if first_top > page_top:
            _collect_rows(
                page, page_no, state, state.current, page_top, first_top, junk
            )

    for idx, ev in enumerate(events):
        if ev.kind == "reg":
            prev = state.registers.get(ev.code)
            if prev is not None and prev.fields:
                state.duplicates.append(ev.code)
                state.current = prev
            elif prev is None:
                state.current = ParsedRegister(
                    code=ev.code, title=ev.title, page_first=page_no
                )
                state.registers[ev.code] = state.current
            else:
                state.current = prev
                state.current.title = state.current.title or ev.title
            state.current.page_last = page_no
            state.bands = None
            state.seen_occ = False

        elif ev.kind == "header":
            reg = state.current
            if reg is None or state.seen_occ:
                continue
            bands = _header_bands(page, ev.line, ev.n_obrig)
            if bands is None:
                state.diagnostics.append(
                    f"p{page_no}: {reg.code} cabeçalho de tabela ilegível"
                )
                continue
            state.bands = bands
            next_top = events[idx + 1].top if idx + 1 < len(events) else page_bottom
            _collect_rows(page, page_no, state, reg, ev.top + 4, next_top, junk)

        elif ev.kind == "nivel" and state.current is not None:
            if state.current.level is None:
                state.current.level = ev.level
            state.current.page_last = page_no

        elif ev.kind == "ocorr" and state.current is not None:
            if state.current.occurrence is None:
                state.current.occurrence = ev.occurrence
                state.seen_occ = True
            state.current.page_last = page_no

        elif ev.kind == "valores" and state.current is not None:
            tokens = [
                t.strip()
                for t in re.split(r"[;,\n]", ev.raw_values)
                if t.strip() and len(t.strip()) <= 6
                and re.fullmatch(r"[0-9A-Za-z-]+", t.strip())
            ]
            if not tokens:
                continue
            for fld in state.current.fields:
                if fld.num == ev.field_num and fld.name == ev.field_name:
                    fld.valid_values = tuple(tokens)
                    break
            else:
                state.diagnostics.append(
                    f"p{page_no}: {state.current.code} nota de campo "
                    f"{ev.field_num:02d} ({ev.field_name}) sem campo correspondente"
                )


@dataclass
class _TailValues:
    """Valores das colunas finais extraídos do fim da primeira linha do campo."""

    tipo: str = ""
    tipo_x: float = 0.0
    tam: str = ""
    dec: str = ""
    units: list[str] = field(default_factory=list)  # unidades de obrigatoriedade


def _is_obrig_token(tok: str) -> bool:
    return bool(re.fullmatch(r"O|OC|O\*", tok))


def _is_valueish(tok: str) -> bool:
    """Token que pode pertencer às colunas finais (Tipo/Tam/Dec/Obrig)."""
    if _is_obrig_token(tok) or tok == "-" or tok in _FRAGMENT_WORDS:
        return True
    t = _strip_token(tok)
    return bool(TIPO_CELL_RE.match(t) or TAM_CELL_RE.match(t) or DEC_CELL_RE.match(t))


def _is_obrig_phrase_tail(tokens: Sequence[str], upto: int) -> int:
    """Comprimento (em tokens) de frase de obrigatoriedade terminando em ``upto``."""
    n = upto
    if (
        n >= 4
        and tokens[n - 4] == "Não"
        and tokens[n - 3] == "apresentar"
        and tokens[n - 2] == "este"
        and tokens[n - 1] == "campo"
    ):
        return 4
    if n >= 2 and tokens[n - 2] == "Não" and tokens[n - 1] == "apresentar":
        return 2
    if n >= 3 and tokens[n - 3] == "Não" and tokens[n - 2] == "se" and tokens[n - 1] == "aplica":
        return 3
    return 0


def _group_units(tokens: Sequence[str]) -> list[str]:
    """Agrupa tokens de obrigatoriedade em unidades (frases viram uma só)."""
    units: list[str] = []
    i = 0
    while i < len(tokens):
        rest = len(tokens) - i
        phrase = _is_obrig_phrase_tail(tokens[i:], rest)
        if phrase:
            units.append(re.sub(r"\s+", " ", " ".join(tokens[i : i + phrase])))
            i += phrase
            continue
        tok = tokens[i]
        if _is_obrig_token(tok) or tok == "-":
            units.append(tok)
            i += 1
            continue
        # texto livre (ex.: "N (informar no 0205)"): junta tudo como uma unidade
        j = i
        while j < len(tokens) and not _is_obrig_token(tokens[j]) and tokens[j] != "-":
            j += 1
        units.append(re.sub(r"\s+", " ", " ".join(tokens[i:j])))
        i = j
    return [u for u in units if u]


def _parse_value_run(
    words: Sequence[dict[str, float]], n_obrig: int
) -> _TailValues | None:
    """Extrai Tipo/Tam/Dec/unidades de obrigatoriedade do fim da primeira linha.

    A descrição nos PDFs oficiais ultrapassa a largura da célula desenhada e
    invade visualmente as colunas finais; os valores verdadeiros são os
    últimos tokens da linha. O consumo vai da direita para a esquerda até o
    primeiro token que não parece valor, e a cadeia [Tipo, Tam, Dec?] é
    localizada dentro do trecho consumido — o que torna o método imune a
    deslocamentos de coluna entre páginas (ex.: 0000 do Guia 3.2.2, pág. 28).
    """
    tokens = [w["text"] for w in words]
    i = len(tokens)
    while i > 0:
        phrase = _is_obrig_phrase_tail(tokens, i)
        if phrase:
            i -= phrase
            continue
        if _is_valueish(tokens[i - 1]):
            i -= 1
            continue
        break
    run = tokens[i:]
    if not run:
        return None

    out = _TailValues()
    # Localiza o primeiro token Tipo (C/N) do trecho consumido.
    k = 0
    while k < len(run) and not TIPO_CELL_RE.match(_strip_token(run[k])):
        k += 1
    if k >= len(run):
        return None
    out.tipo = _strip_token(run[k])
    if k + 1 >= len(run) or not TAM_CELL_RE.match(run[k + 1]):
        return None
    out.tam = run[k + 1]
    nxt = k + 2
    if nxt < len(run) and DEC_CELL_RE.match(run[nxt]):
        out.dec = run[nxt]
        nxt += 1
    out.units = _group_units(run[nxt:])
    out.tipo_x = float(words[i + k]["x0"])
    return out


def _at_or_below_rows(
    words: Sequence[dict[str, float]],
    rows: Sequence[_RowBand],
    junk: Sequence[tuple[float, float]],
) -> dict[int, list[dict[str, float]]]:
    """Atribui cada palavra à linha cuja âncora está no seu nível ou abaixo.

    Nas tabelas com células deslocadas (ex.: C179 do Guia 3.2.2), os valores
    ficam até uma linha acima da âncora; a primeira âncora no nível da
    palavra (ou abaixo dela) identifica a linha correta. Em tabelas normais a
    palavra está na própria linha da âncora.
    """
    out: dict[int, list[dict[str, float]]] = {}
    clean = [
        w
        for w in words
        if not any(j0 <= (w["top"] + w["bottom"]) / 2 <= j1 for j0, j1 in junk)
    ]
    for w in clean:
        center = (w["top"] + w["bottom"]) / 2
        target = rows[-1]
        for r in rows:
            if r.top + 1.5 >= center - 6.0:  # âncora no nível da palavra
                target = r
                break
        out.setdefault(target.num, []).append(w)
    for words_list in out.values():
        words_list.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
    return out


def _shift_bands(bands: _ColumnBands, dx: float) -> _ColumnBands:
    """Desloca as colunas de valor (as colunas de texto não se deslocam)."""
    return _ColumnBands(
        num=bands.num,
        campo=bands.campo,
        descr=bands.descr,
        tipo=(bands.tipo[0] + dx, bands.tipo[1] + dx),
        tam=(bands.tam[0] + dx, bands.tam[1] + dx),
        dec=(bands.dec[0] + dx, bands.dec[1] + dx),
        obrig=[(b[0] + dx, b[1] + dx) for b in bands.obrig],
    )


def _snake_continuation(name: str, extra: str) -> bool:
    """Um fragmento de nome quebrado entre linhas continua o mnemônico."""
    if not extra:
        return False
    if not re.fullmatch(r"[A-Z0-9_]+", extra):
        return False
    return name.endswith("_") or extra.startswith("_")


def _collect_rows(
    page: Page,
    page_no: int,
    state: _ParserState,
    reg: ParsedRegister,
    region_top: float,
    region_bottom: float,
    junk: Sequence[tuple[float, float]],
) -> None:
    """Extrai as linhas de campo de uma região da página."""
    bands = state.bands
    if bands is None or region_bottom <= region_top:
        return
    rows = _row_bands(page, bands, region_top, region_bottom, junk)
    if not rows:
        return

    # Tabelas continuadas podem vir com as colunas de valor deslocadas em
    # relação ao cabeçalho da página anterior (ex.: 0000, pág. 28 do Guia
    # 3.2.2). Detecta pela coluna Tipo da primeira linha legível: só há
    # deslocamento quando o valor cai FORA da banda derivada do cabeçalho.
    page_bands = bands
    for probe in rows[:2]:
        probe_words = _words_in_region(
            page, bands.campo[0] - 10.0, 2000.0, probe.top - 0.5, probe.top + 10.5
        )
        probe_words.sort(key=lambda w: w["x0"])
        probe_tail = _parse_value_run(probe_words, len(bands.obrig))
        if probe_tail is not None:
            t0, t1 = bands.tipo
            if not (t0 + 2 <= probe_tail.tipo_x <= t1 - 2):
                dx = probe_tail.tipo_x - (t0 + t1) / 2
                page_bands = _shift_bands(bands, dx)
            break

    # Células mescladas das colunas de obrigação ("Não apresentar" desenhado
    # uma única vez cobrindo toda a tabela, ex.: C130 e C176).
    strips: dict[str, dict[int, str]] = {}
    obrig_specs: list[tuple[str, tuple[float, float]]] = []
    if page_bands.obrig:
        obrig_specs.append(("obrig", page_bands.obrig[0]))
    if len(page_bands.obrig) == 2:
        obrig_specs.append(("obrig2", page_bands.obrig[1]))
    for col_name, band in obrig_specs:
        strips[col_name] = _strip_assignments(
            page, band, rows, region_top, region_bottom, junk, _is_obrig_value
        )

    # Palavras das colunas de obrigação por linha (âncora no nível ou abaixo).
    # A região começa na primeira linha da tabela: o cabeçalho e o texto de
    # introdução ficam acima dela.
    words_top = rows[0].top if rows else region_top
    oblig_words: dict[str, dict[int, list[dict[str, float]]]] = {}
    for col_name, band in obrig_specs:
        words = _words_in_region(page, band[0], band[1], words_top, region_bottom)
        oblig_words[col_name] = _at_or_below_rows(words, rows, junk)
        _debug(
            reg.code,
            f"obrig '{col_name}' palavras por linha: "
            + ", ".join(
                f"{num}:{_join_words(ws)!r}"
                for num, ws in sorted(oblig_words[col_name].items())
            ),
        )
    for col_name in strips:
        _debug(
            reg.code,
            f"faixas mescladas '{col_name}': "
            + ", ".join(f"{num}:{val!r}" for num, val in sorted(strips[col_name].items())),
        )

    for row in rows:
        expected = reg.fields[-1].num + 1 if reg.fields else 1
        if reg.fields and row.num <= reg.fields[-1].num:
            state.diagnostics.append(
                f"p{page_no}: {reg.code} campo {row.num:02d} repetido (ignorado)"
            )
            continue
        if row.num != expected:
            state.diagnostics.append(
                f"p{page_no}: {reg.code} campo {row.num:02d} fora de sequência "
                f"(esperado {expected:02d})"
            )
            continue

        # Primeira linha visual do campo: mesma faixa y da palavra NN.
        first_line_words = _words_in_region(
            page, bands.campo[0] - 10.0, 2000.0, row.top - 0.5, row.top + 10.5
        )
        first_line_words = [
            w
            for w in first_line_words
            if not any(j0 <= (w["top"] + w["bottom"]) / 2 <= j1 for j0, j1 in junk)
        ]
        first_line_words.sort(key=lambda w: w["x0"])

        tail = _parse_value_run(first_line_words, len(bands.obrig))

        # Nome: palavras da coluna Campo na primeira linha.
        name_words = [
            w
            for w in first_line_words
            if bands.campo[0] <= (w["x0"] + w["x1"]) / 2 <= bands.campo[1]
        ]
        name = re.sub(r"\s+", " ", "".join(w["text"] for w in name_words)).strip()
        # Nome quebrado em duas linhas (ex.: VL_UNIT_LIMITE_B / C_ICMS_ULT_E).
        next_line = _words_in_region(
            page, bands.campo[0], bands.campo[1], row.top + 10.5, row.top + 23.0
        )
        next_line = [
            w
            for w in next_line
            if not any(j0 <= (w["top"] + w["bottom"]) / 2 <= j1 for j0, j1 in junk)
        ]
        next_line.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
        fragment = "".join(w["text"] for w in next_line).strip()
        if _snake_continuation(name, fragment):
            name += fragment

        # Descrição: palavras da banda da linha à esquerda da coluna Tipo,
        # na ordem de leitura (a descrição pode invadir as colunas finais).
        if tail is not None:
            descr_words = _words_in_region(
                page, bands.descr[0], tail.tipo_x - 1.0, row.top, row.bottom
            )
            descr_words = [
                w
                for w in descr_words
                if not any(j0 <= (w["top"] + w["bottom"]) / 2 <= j1 for j0, j1 in junk)
            ]
            descr_words.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
            descr = _join_description(descr_words)
            ftype, tam, dec = tail.tipo, tail.tam, tail.dec
            units = list(tail.units)
        else:
            # Sem trecho legível: usa as bandas (ajustadas ao deslocamento).
            ftype = _strip_token(_cell_text(page, page_bands.tipo, row, junk))
            tam = _cell_text(page, page_bands.tam, row, junk)
            dec = _cell_text(page, page_bands.dec, row, junk)
            descr = _join_description(_cell_words(page, bands.descr, row, junk))
            units = []
            if not (TIPO_CELL_RE.match(ftype) and TAM_CELL_RE.match(tam)):
                state.diagnostics.append(
                    f"p{page_no}: {reg.code} campo {row.num:02d} sem colunas finais legíveis"
                )
                continue

        # Obrigatoriedade: valor por linha (âncora no nível ou abaixo da
        # palavra), célula mesclada quando houver, e por fim as unidades do
        # fim da primeira linha.
        obrig_values: list[str] = []
        if len(bands.obrig) == 2:
            entr = _join_words(oblig_words["obrig"].get(row.num, []))
            if not OBRIG_CELL_RE.match(entr):
                entr = strips["obrig"].get(row.num, entr if entr else "")
            saida = _join_words(oblig_words["obrig2"].get(row.num, []))
            if not OBRIG_CELL_RE.match(saida):
                saida = strips["obrig2"].get(row.num, saida if saida else "")
            if not entr and units:
                entr = units[0] if len(units) > 1 else ""
            if not saida and units:
                saida = units[-1]
            obrig_values = [entr, saida]
        elif len(bands.obrig) == 1:
            value = _join_words(oblig_words["obrig"].get(row.num, []))
            if not OBRIG_CELL_RE.match(value):
                value = strips["obrig"].get(row.num, value if value else "")
            if not value and units:
                value = units[-1]
            obrig_values = [value]

        reg.fields.append(
            ParsedField(
                num=row.num,
                name=name,
                description=descr,
                ftype=ftype,
                tam=tam,
                dec=dec or "-",
                obrig=_normalize_obrig_list(obrig_values),
            )
        )


def _join_words(words: Sequence[dict[str, float]]) -> str:
    """Junta palavras já ordenadas de uma célula."""
    return re.sub(r"\s+", " ", " ".join(w["text"] for w in words)).strip()


def _cell_text(
    page: Page, band: tuple[float, float], row: _RowBand, junk: Sequence[tuple[float, float]]
) -> str:
    """Texto das palavras de uma coluna na banda y da linha."""
    words = _cell_words(page, band, row, junk)
    return re.sub(r"\s+", " ", " ".join(w["text"] for w in words)).strip()


def _normalize_obrig_list(values: Sequence[str]) -> tuple[str, ...]:
    """Normaliza a lista de valores de obrigatoriedade de uma linha."""
    out: list[str] = []
    for v in values:
        if not v:
            continue
        out.extend(_normalize_obrig_cell(v))
    return tuple(out)


def parse_leiaute_pdf(path: str) -> LayoutParse:
    """Extrai todos os registros do capítulo de blocos de um documento oficial."""
    state = _ParserState()
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages):
            _process_page(page, page_no, state)
    return LayoutParse(
        registers=state.registers,
        diagnostics=state.diagnostics,
        duplicates=state.duplicates,
    )


# ---------------------------------------------------------------------------
# Validação do parse
# ---------------------------------------------------------------------------


def validate_parse(parse: LayoutParse, expected_min_registers: int = 100) -> list[str]:
    """Regras de sanidade sobre o parse; devolve a lista de problemas."""
    problems: list[str] = []
    regs = parse.registers

    if len(regs) < expected_min_registers:
        problems.append(f"poucos registros: {len(regs)}")

    for code, reg in regs.items():
        if not re.fullmatch(r"[0-9A-Z]{4}", code):
            problems.append(f"{code}: código de registro inválido")
        if not reg.fields:
            problems.append(f"{code}: sem campos")
            continue
        if reg.fields[0].num != 1 or reg.fields[0].name != "REG":
            problems.append(f"{code}: campo 01 não é REG")
        for i, fld in enumerate(reg.fields, start=1):
            if fld.num != i:
                problems.append(f"{code}: numeração de campos salta em {fld.num}")
                break
            if not fld.name:
                problems.append(f"{code}.{fld.num}: sem nome")
            elif not NAME_CELL_RE.match(fld.name):
                problems.append(f"{code}.{fld.num}: nome inválido {fld.name!r}")
            if not TIPO_CELL_RE.match(fld.ftype):
                problems.append(f"{code}.{fld.num} ({fld.name}): tipo inválido {fld.ftype!r}")
            if not TAM_CELL_RE.match(fld.tam):
                problems.append(f"{code}.{fld.num} ({fld.name}): tam inválido {fld.tam!r}")
            if not DEC_CELL_RE.match(fld.dec):
                problems.append(f"{code}.{fld.num} ({fld.name}): dec inválido {fld.dec!r}")
            for v in fld.obrig:
                if not OBRIG_CELL_RE.match(v):
                    problems.append(
                        f"{code}.{fld.num} ({fld.name}): obrig inválido {v!r}"
                    )
        if reg.level is None:
            problems.append(f"{code}: sem nível hierárquico")
        if reg.occurrence is None:
            problems.append(f"{code}: sem ocorrência")

    # Registros estruturais obrigatórios em qualquer leiaute da EFD ICMS/IPI.
    for structural in ("0000", "0001", "9990", "9999"):
        if structural not in regs:
            problems.append(f"falta registro estrutural {structural}")
    # Fechamentos de bloco: todo bloco aberto precisa do x990 correspondente.
    blocks = sorted({c[0] for c in regs})
    for b in blocks:
        if f"{b}001" in regs and f"{b}990" not in regs:
            problems.append(f"bloco {b}: sem registro de encerramento {b}990")

    return problems


def compare_registers(
    a: dict[str, ParsedRegister], b: dict[str, ParsedRegister]
) -> dict[str, object]:
    """Compara dois parses (Registro→campos) para verificação entre documentos."""
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    field_diffs: list[str] = []
    value_diffs: list[str] = []
    for code in sorted(set(a) & set(b)):
        fa, fb = a[code].field_types(), b[code].field_types()
        if list(fa) != list(fb):
            field_diffs.append(code)
            continue
        for name in fa:
            if fa[name] != fb[name]:
                value_diffs.append(f"{code}.{name}: {fa[name]} != {fb[name]}")
    return {
        "only_in_first": only_a,
        "only_in_second": only_b,
        "field_list_diff": field_diffs,
        "value_diff": value_diffs,
    }
