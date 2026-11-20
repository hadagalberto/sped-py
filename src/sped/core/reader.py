"""Streaming, typed reader for pipe-delimited SPED files."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import TypeAlias

from sped.core.encoding import iter_lines, split_line
from sped.core.types import Field, FieldDef, Layout, Record, RegisterDef
from sped.layouts import detect_layout


def _issue(
    line_no: int,
    code: str,
    message: str,
    *,
    strict: bool,
    on_issue: IssueHandler | None,
) -> None:
    """Report an issue through ``on_issue`` and/or raise in strict mode."""
    if on_issue is not None:
        on_issue(line_no, code, message)
    if strict:
        raise SpedParseError(line_no, message)


def parse_record(
    line_no: int,
    code: str,
    values: tuple[str, ...],
    raw: str,
    layout: Layout,
    *,
    strict: bool = True,
    on_issue: IssueHandler | None = None,
) -> Record | None:
    """Parse one already-split line against ``layout``.

    Shared by the streaming reader and the on-disk index so that random
    access returns exactly the same :class:`Record` objects as a full scan.
    """
    try:
        definition: RegisterDef = layout.register(code)
    except KeyError:
        _issue(
            line_no,
            code,
            f"registro {code!r} não existe no leiaute {layout.cod_ver}",
            strict=strict,
            on_issue=on_issue,
        )
        return None
    fields: list[Field] = []
    # O REG é implícito: a linha começa com |REG| e não repete o código
    # como primeiro valor. As tabelas oficiais, porém, o descrevem como
    # campo 01 — por isso ele é incluído no record e removido da contagem.
    value_defs = definition.fields
    if value_defs and value_defs[0].name == "REG":
        reg_def = value_defs[0]
        fields.append(Field(definition=reg_def, raw=code, value=code))
        value_defs = value_defs[1:]
    if len(values) != len(value_defs):
        _issue(
            line_no,
            code,
            f"{code}: esperados {len(value_defs)} campos, encontrados {len(values)}",
            strict=strict,
            on_issue=on_issue,
        )
    for field_def, raw_value in zip(value_defs, values, strict=False):
        error = validate_field(field_def, raw_value, line_no=line_no, code=code)
        if error is not None:
            _issue(line_no, code, error, strict=strict, on_issue=on_issue)
        value = field_def.coerce(raw_value)
        if field_def.ftype == "N" and raw_value and isinstance(value, str):
            message = f"{code}.{field_def.num:02d} ({field_def.name}): conversão numérica falhou"
            if error is None:
                _issue(line_no, code, message, strict=strict, on_issue=on_issue)
                error = message
        fields.append(Field(definition=field_def, raw=raw_value, value=value, error=error))
    return Record(line_no=line_no, code=code, fields=tuple(fields), raw=raw)


IssueHandler: TypeAlias = Callable[[int, str, str], None]


class SpedParseError(ValueError):
    """Raised in strict mode when a line violates the layout."""

    def __init__(self, line_no: int, message: str) -> None:
        super().__init__(f"linha {line_no}: {message}")
        self.line_no = line_no
        self.message = message


def validate_field(  # noqa: PLR0911
    definition: FieldDef,
    raw: str,
    *,
    line_no: int = 0,
    code: str = "",
) -> str | None:
    """Return a pt-BR error message for an invalid field, or ``None``.

    Checks the official size/type rules: required, exact/max length, numeric
    grammar, date grammar and published value domains.
    """
    label = f"{code}.{definition.num:02d} ({definition.name})"
    if raw == "":
        return f"{label}: campo obrigatório vazio" if definition.required else None
    if definition.exact and len(raw) != definition.size:
        return f"{label}: tamanho {len(raw)} diferente de {definition.size}"
    if not definition.exact and definition.size and len(raw) > definition.size:
        return f"{label}: tamanho {len(raw)} excede {definition.size}"
    if definition.ftype == "N":
        body = raw[1:] if raw.startswith("-") else raw
        # The official separator is the comma. A dot is never valid in a
        # SPED numeric field, and an integer field cannot carry a comma.
        if "." in body or body.count(",") > 1 or (definition.dec == 0 and "," in body):
            return f"{label}: número inválido {raw!r}"
        candidate = body.replace(",", ".")
        if definition.dec > 0 and "," in body:
            integral, _, fractional = candidate.partition(".")
            valid = (
                integral.isdigit() and fractional.isdigit() and len(fractional) <= definition.dec
            )
        else:
            valid = bool(candidate) and candidate.isdigit()
        if not valid:
            return f"{label}: valor numérico inválido {raw!r}"
    if definition.is_date:
        if len(raw) != 8 or not raw.isdigit():
            return f"{label}: data deve estar no formato DDMMAAAA"
        try:
            date(int(raw[4:8]), int(raw[2:4]), int(raw[0:2]))
        except ValueError:
            return f"{label}: data inválida {raw!r}"
    if definition.valid_values and raw not in definition.valid_values:
        return f"{label}: valor {raw!r} fora do domínio publicado"
    return None


class SpedReader:
    """Iterate records of a SPED file with constant memory.

    Example::

        with SpedReader("efd.txt") as reader:
            for record in reader:
                print(record.code, record.values)
    """

    def __init__(
        self,
        path: str | Path,
        layout: Layout | None = None,
        *,
        encoding: str | None = None,
        strict: bool = True,
        on_issue: IssueHandler | None = None,
    ) -> None:
        self.path = Path(path)
        self.encoding = encoding
        self.strict = strict
        self.on_issue = on_issue
        self.layout = layout or detect_layout(self.path)
        self.line_no = 0

    def __enter__(self) -> SpedReader:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def _issue(self, line_no: int, code: str, message: str) -> None:
        _issue(
            line_no,
            code,
            message,
            strict=self.strict,
            on_issue=self.on_issue,
        )

    def _parse(self, line_no: int, code: str, values: tuple[str, ...], raw: str) -> Record | None:
        return parse_record(
            line_no,
            code,
            values,
            raw,
            self.layout,
            strict=self.strict,
            on_issue=self.on_issue,
        )

    def iter_records(self) -> Iterator[Record]:
        """Yield parsed records one at a time."""
        lines = iter(iter_lines(self.path, self.encoding))
        for raw in lines:
            self.line_no += 1
            try:
                split = split_line(raw)
            except ValueError as exc:
                self._issue(self.line_no, "", str(exc))
                continue
            if split is None:
                continue
            code, values = split
            record = self._parse(self.line_no, code, values, raw)
            if record is not None:
                yield record

    def __iter__(self) -> Iterator[Record]:
        return self.iter_records()

    def by_type(self, code: str) -> Iterator[Record]:
        """Yield only records of the given register type (single pass)."""
        return (record for record in self.iter_records() if record.code == code)


def read(path: str | Path, **kwargs: object) -> SpedReader:
    """Return a streaming :class:`SpedReader` for ``path``."""
    return SpedReader(path, **kwargs)  # type: ignore[arg-type]
