"""Command line interface for sped-py."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from sped import __version__
from sped.core.encoding import iter_lines, split_line
from sped.core.reader import SpedReader
from sped.core.validation import validate
from sped.core.writer import write
from sped.layouts import available_versions, detect_layout, version_info


def _cmd_info(args: argparse.Namespace) -> int:
    layout = detect_layout(args.arquivo)
    cod_ver = layout.cod_ver
    info = version_info(cod_ver, layout.obrigacao)
    registers = list(layout.registers.values())
    field_count = sum(len(register.fields) for register in registers)
    blocks = sorted({register.code[0] for register in registers})
    print(f"Arquivo:     {args.arquivo}")
    print(f"Obrigação:   {layout.obrigacao}")
    print(f"COD_VER:     {cod_ver} (leiaute {layout.versao})")
    print(f"Vigência:    {layout.valid_from} a {layout.valid_to}")
    print(f"Fonte:       {layout.source_url}")
    print(f"Registros:   {len(registers)}")
    print(f"Campos:      {field_count}")
    print(f"Blocos:      {', '.join(blocks)}")
    print(f"Versões:     {', '.join(available_versions(layout.obrigacao))}")
    if args.json:
        print(
            json.dumps(
                {
                    "arquivo": str(args.arquivo),
                    "cod_ver": cod_ver,
                    "obrigacao": layout.obrigacao,
                    "versoes": list(available_versions(layout.obrigacao)),
                    "versao": layout.versao,
                    **{key: value for key, value in info.items() if key != "file"},
                    "registros": len(registers),
                    "campos": field_count,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    issues = validate(args.arquivo)
    if args.json:
        print(json.dumps([issue.as_dict() for issue in issues], ensure_ascii=False, indent=2))
    elif issues:
        for issue in issues:
            print(f"{issue.rule} linha {issue.line_no} {issue.code}: {issue.message}")
    else:
        print("OK: nenhum problema encontrado")
    return 1 if issues else 0


def _cmd_export(args: argparse.Namespace) -> int:
    layout = detect_layout(args.arquivo)
    output = Path(args.saida)
    output.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[tuple[str, ...]]] = {}
    reader = SpedReader(args.arquivo, layout=layout, strict=False)
    for record in reader:
        grouped.setdefault(record.code, []).append(record.raw_values)

    if args.to == "csv":
        for code, rows in grouped.items():
            with (output / f"{code}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(layout.register(code).field_names)
                writer.writerows(rows)
    elif args.to in {"parquet", "pandas", "excel"}:
        try:
            import pandas as pd  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError:
            print("Instale o extra [pandas] para exportar para DataFrame/parquet", file=sys.stderr)
            return 2
        frame_by_code = {
            code: pd.DataFrame(rows, columns=layout.register(code).field_names)
            for code, rows in grouped.items()
        }
        if args.to == "parquet":
            for code, frame in frame_by_code.items():
                frame.to_parquet(output / f"{code}.parquet", index=False)
        elif args.to == "excel":
            with pd.ExcelWriter(output / "sped.xlsx") as excel_writer:
                for code, frame in frame_by_code.items():
                    frame.to_excel(excel_writer, sheet_name=code[:31], index=False)
        else:
            print(frame_by_code)
    else:
        print(f"Formato de exportação desconhecido: {args.to}", file=sys.stderr)
        return 2
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    def snapshot(path: str) -> dict[tuple[int, str], tuple[str, ...]]:
        result: dict[tuple[int, str], tuple[str, ...]] = {}
        line_no = 0
        for line in iter_lines(path):
            line_no += 1
            split = split_line(line)
            if split is None:
                continue
            code, values = split
            result[(line_no, code)] = values
        return result

    left, right = snapshot(args.a), snapshot(args.b)
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    changed = sorted(key for key in set(left) & set(right) if left[key] != right[key])
    print(f"Somente em A: {len(only_left)}")
    print(f"Somente em B: {len(only_right)}")
    print(f"Alterados:    {len(changed)}")
    for key in changed[:20]:
        print(f"linha {key[0]} {key[1]}: {left[key]} -> {right[key]}")
    return 1 if (only_left or only_right or changed) else 0


def _cmd_fix_totals(args: argparse.Namespace) -> int:
    lines = []
    for line in iter_lines(args.arquivo):
        split = split_line(line)
        if split is not None:
            lines.append(split)
    try:
        layout = detect_layout(args.arquivo)
    except ValueError:
        layout = None
    count = write(lines, args.saida, encoding=args.encoding, layout=layout)
    print(f"Arquivo corrigido: {args.saida} ({count} linhas)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="sped", description="Leitura e validação de arquivos SPED"
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

    export = sub.add_parser("export", help="exporta registros para csv/parquet/excel")
    export.add_argument("arquivo")
    export.add_argument("--to", choices=("csv", "parquet", "pandas", "excel"), default="csv")
    export.add_argument("saida")
    export.set_defaults(func=_cmd_export)

    diff = sub.add_parser("diff", help="compara dois arquivos linha a linha")
    diff.add_argument("a")
    diff.add_argument("b")
    diff.set_defaults(func=_cmd_diff)

    fix = sub.add_parser("fix-totals", help="recomputa x990/9900/9999")
    fix.add_argument("arquivo")
    fix.add_argument("-o", "--saida", required=True)
    fix.add_argument("--encoding", default="latin-1")
    fix.set_defaults(func=_cmd_fix_totals)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
