"""Command line interface for sped-py.

Códigos de saída (estáveis, documentados no README):

* ``0`` — sucesso;
* ``1`` — o comando encontrou não conformidades (validação, diff, apuração);
* ``2`` — uso inválido ou dependência opcional ausente;
* ``3`` — falha de E/S ou de leitura do arquivo.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Final

from sped import __version__
from sped.analysis import (
    DEFAULT_DIMENSIONS,
    compute_apuracao,
    diff_files,
    merge_files,
    recompute_apuracao,
    split_file,
    summarize_file,
)
from sped.core.encoding import detect_encoding, iter_lines, split_line
from sped.core.reader import read
from sped.core.writer import write
from sped.exports import MissingOptionalDependencyError, SpedExport
from sped.layouts import available_versions, detect_layout, version_info
from sped.validation import validate
from sped.validation.rules import Severity

EXIT_OK: Final = 0
EXIT_ISSUES: Final = 1
EXIT_USAGE: Final = 2
EXIT_IO: Final = 3


class UsageError(ValueError):
    """Invalid command usage: mapped to ``EXIT_USAGE`` instead of ``EXIT_IO``."""


def _json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _cmd_info(args: argparse.Namespace) -> int:
    layout = detect_layout(args.arquivo)
    cod_ver = layout.cod_ver
    info = version_info(cod_ver, layout.obrigacao)
    registers = list(layout.registers.values())
    field_count = sum(len(register.fields) for register in registers)
    blocks = sorted({register.code[0] for register in registers})
    if args.json:
        _json(
            {
                "arquivo": str(args.arquivo),
                "cod_ver": cod_ver,
                "obrigacao": layout.obrigacao,
                "versoes": list(available_versions(layout.obrigacao)),
                "versao": layout.versao,
                **{key: value for key, value in info.items() if key != "file"},
                "registros": len(registers),
                "campos": field_count,
                "blocos": blocks,
            }
        )
        return EXIT_OK
    print(f"Arquivo:     {args.arquivo}")
    print(f"Obrigação:   {layout.obrigacao}")
    print(f"COD_VER:     {cod_ver} (leiaute {layout.versao})")
    print(f"Vigência:    {layout.valid_from} a {layout.valid_to}")
    print(f"Fonte:       {layout.source_url}")
    print(f"Registros:   {len(registers)}")
    print(f"Campos:      {field_count}")
    print(f"Blocos:      {', '.join(blocks)}")
    print(f"Versões:     {', '.join(available_versions(layout.obrigacao))}")
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    issues = validate(args.arquivo)
    if args.json:
        _json([issue.as_dict() for issue in issues])
    elif issues:
        for issue in issues:
            print(f"{issue.rule} linha {issue.line_no} {issue.code}: {issue.message}")
    else:
        print("OK: nenhum problema encontrado")
    # SPEC: non-zero only on *errors*. Warnings are reported but do not fail
    # the command (they are non-blocking advisories).
    errors = any(issue.severity is Severity.ERROR for issue in issues)
    return EXIT_ISSUES if errors else EXIT_OK


def _cmd_export(args: argparse.Namespace) -> int:
    if args.to not in {"pandas", "polars"} and not args.saida:
        print("informe o diretório/arquivo de saída", file=sys.stderr)
        return EXIT_USAGE
    exporter = SpedExport(args.arquivo)
    if args.to == "csv":
        counts = exporter.csv(args.saida)
        report: object = {"formato": "csv", "arquivos": counts}
    elif args.to == "parquet":
        paths = exporter.parquet(args.saida)
        report = {"formato": "parquet", "arquivos": {k: str(v) for k, v in paths.items()}}
    elif args.to == "excel":
        target = exporter.excel(args.saida)
        report = {"formato": "excel", "arquivo": str(target)}
    elif args.to in {"pandas", "polars"}:
        frames = exporter.frames(library=args.to)
        if args.json:
            report = {"formato": args.to, "registros": sorted(frames)}
        else:
            for code, frame in frames.items():
                print(f"--- {code} ---")
                print(frame)
            return EXIT_OK
    else:
        print(f"Formato de exportação desconhecido: {args.to}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        _json(report)
    elif isinstance(report, dict) and "arquivo" in report:
        print(f"Arquivo gerado: {report['arquivo']}")
    else:
        _json(report)
    return EXIT_OK


def _cmd_diff(args: argparse.Namespace) -> int:
    if args.limit < 0:
        raise UsageError("--limit não pode ser negativo")
    result = diff_files(args.a, args.b, limit=args.limit)
    if args.json:
        _json(result.as_dict())
    else:
        print(f"Somente em A: {result.removed}")
        print(f"Somente em B: {result.added}")
        print(f"Alterados:    {result.changed}")
        for entry in result.entries[:20]:
            if entry.kind == "changed":
                print(f"linha {entry.line_no} {entry.code}: {entry.left} -> {entry.right}")
            elif entry.kind == "removed":
                print(f"somente em A, linha {entry.line_no} {entry.code}: {entry.left}")
            else:
                print(f"somente em B, linha {entry.other_line_no} {entry.code}: {entry.right}")
    return EXIT_ISSUES if result.has_differences else EXIT_OK


def _cmd_fix_totals(args: argparse.Namespace) -> int:
    encoding = args.encoding
    if encoding is None:
        with open(args.arquivo, "rb") as handle:
            encoding = detect_encoding(handle.read(8192))
    source_lines = [
        (split[0], split[1])
        for line in iter_lines(args.arquivo, encoding)
        if (split := split_line(line))
    ]
    try:
        layout = detect_layout(args.arquivo)
    except ValueError:
        layout = None
    count = write(source_lines, args.saida, encoding=encoding, layout=layout)
    if args.json:
        _json({"arquivo": str(args.saida), "linhas": count})
    else:
        print(f"Arquivo corrigido: {args.saida} ({count} linhas)")
    return EXIT_OK


def _cmd_summarize(args: argparse.Namespace) -> int:
    dimensions = tuple(args.dimension) if args.dimension else DEFAULT_DIMENSIONS
    summaries = summarize_file(args.arquivo, dimensions=dimensions)
    if args.json:
        _json([summary.as_dict() for summary in summaries])
    else:
        for summary in summaries:
            print(f"--- {summary.dimension} ({summary.total_count} registros) ---")
            for row in summary.rows:
                item = ", ".join(f"{name}={value}" for name, value in row.totals.items())
                print(f"{row.value or '(vazio)'}  qtd={row.count}  {item}")
    return EXIT_OK


def _cmd_apuracao(args: argparse.Namespace) -> int:
    layout = detect_layout(args.arquivo)
    with read(args.arquivo, layout=layout, strict=False) as arquivo:
        result = compute_apuracao(arquivo.iter_records(), layout=layout)
    if args.json:
        _json(result.as_dict())
    else:
        print(f"Apuração {result.obrigacao}/{result.cod_ver}: {len(result.fields)} campos")
        for field in result.divergences:
            print(
                f"{field.register}.{field.field} linha {field.line_no}: "
                f"informado {field.stated}, apurado {field.computed}"
            )
        if result.ok:
            print("OK: apuração confere")
    return EXIT_ISSUES if not result.ok else EXIT_OK


def _cmd_recompute_apuracao(args: argparse.Namespace) -> int:
    target = recompute_apuracao(args.arquivo, args.saida)
    if args.json:
        _json({"arquivo": str(target)})
    else:
        print(f"Apuração recalculada: {target}")
    return EXIT_OK


def _cmd_merge(args: argparse.Namespace) -> int:
    detected = [detect_layout(path) for path in args.arquivos]
    if len({(item.obrigacao, item.cod_ver) for item in detected}) > 1:
        raise UsageError(
            "leiautes incompatíveis: "
            + ", ".join(f"{item.obrigacao}/{item.cod_ver}" for item in detected)
        )
    target = merge_files(args.arquivos, args.saida)
    if args.json:
        _json({"arquivo": str(target), "entradas": [str(p) for p in args.arquivos]})
    else:
        print(f"Arquivo mesclado: {target}")
    return EXIT_OK


def _cmd_split(args: argparse.Namespace) -> int:
    paths = split_file(args.arquivo, args.saida, by=args.by)
    if args.json:
        _json({"arquivos": [str(path) for path in paths]})
    else:
        for path in paths:
            print(path)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="sped", description="Leitura, validação e análise de arquivos SPED"
    )
    parser.add_argument("--version", action="version", version=f"sped-py {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="mostra metadados do leiaute detectado")
    info.add_argument("arquivo")
    info.add_argument("--json", action="store_true")
    info.set_defaults(func=_cmd_info)

    validate_cmd = sub.add_parser("validate", help="valida estrutura, campos e totais")
    validate_cmd.add_argument("arquivo")
    validate_cmd.add_argument("--json", action="store_true")
    validate_cmd.set_defaults(func=_cmd_validate)

    export = sub.add_parser("export", help="exporta registros para csv/parquet/excel/dataframes")
    export.add_argument("arquivo")
    export.add_argument(
        "--to", choices=("csv", "parquet", "pandas", "polars", "excel"), default="csv"
    )
    export.add_argument("saida", nargs="?")
    export.add_argument("--json", action="store_true")
    export.set_defaults(func=_cmd_export)

    diff = sub.add_parser("diff", help="compara dois arquivos (original x retificadora)")
    diff.add_argument("a")
    diff.add_argument("b")
    diff.add_argument("--limit", type=int, default=20)
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(func=_cmd_diff)

    fix = sub.add_parser("fix-totals", help="recomputa x990/9900/9999")
    fix.add_argument("arquivo")
    fix.add_argument("-o", "--saida", required=True)
    fix.add_argument(
        "--encoding", default=None, help="codificação de entrada/saída (padrão: detectar)"
    )
    fix.add_argument("--json", action="store_true")
    fix.set_defaults(func=_cmd_fix_totals)

    summarize = sub.add_parser("summarize", help="resumos por CFOP/CST/participante")
    summarize.add_argument("arquivo")
    summarize.add_argument("--dimension", action="append", choices=("CFOP", "CST_ICMS", "COD_PART"))
    summarize.add_argument("--json", action="store_true")
    summarize.set_defaults(func=_cmd_summarize)

    apuracao = sub.add_parser("apuracao", help="recalcula e compara os campos de apuração")
    apuracao.add_argument("arquivo")
    apuracao.add_argument("--json", action="store_true")
    apuracao.set_defaults(func=_cmd_apuracao)

    recompute = sub.add_parser("recompute-apuracao", help="grava arquivo com apuração recalculada")
    recompute.add_argument("arquivo")
    recompute.add_argument("-o", "--saida")
    recompute.add_argument("--json", action="store_true")
    recompute.set_defaults(func=_cmd_recompute_apuracao)

    merge = sub.add_parser("merge", help="mescla arquivos do mesmo leiaute")
    merge.add_argument("arquivos", nargs="+")
    merge.add_argument("-o", "--saida", required=True)
    merge.add_argument("--json", action="store_true")
    merge.set_defaults(func=_cmd_merge)

    split_cmd = sub.add_parser("split", help="divide arquivo por período")
    split_cmd.add_argument("arquivo")
    split_cmd.add_argument("-o", "--saida", required=True)
    split_cmd.add_argument("--by", choices=("month", "quarter", "year"), default="month")
    split_cmd.add_argument("--json", action="store_true")
    split_cmd.set_defaults(func=_cmd_split)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    # Python < 3.12 argparse binds the optional positional ``saida`` (empty)
    # together with ``arquivo`` and then rejects a value given after ``--to``
    # (``sped export f.txt --to csv out``). Recover it here.
    if (
        extra
        and getattr(args, "func", None) is _cmd_export
        and args.saida is None
        and len(extra) == 1
        and not extra[0].startswith("-")
    ):
        args.saida = extra[0]
        extra = []
    if extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    try:
        return int(args.func(args))
    except UsageError as exc:
        print(f"uso inválido: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except MissingOptionalDependencyError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    except ImportError as exc:
        print(f"dependência opcional ausente: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (OSError, ValueError, KeyError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    raise SystemExit(main())
