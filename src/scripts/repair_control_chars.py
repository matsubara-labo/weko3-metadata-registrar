# /// script
# requires-python = ">=3.13"
# ///
#
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generation.control_chars import (
    count_rules,
    repair_file,
    same_file,
    write_repair_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair control characters that broken escape handling left "
        "in list cells of a source CSV/TSV, before generating import files."
    )
    parser.add_argument(
        "--input", type=Path, required=True, help="Source CSV or TSV file."
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Repaired CSV or TSV file."
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="TSV listing every changed list element. Default: <output stem>"
        "_repairs.tsv next to --output.",
    )
    parser.add_argument(
        "--delimiter",
        choices=("auto", "comma", "tab"),
        default="auto",
        help="Input delimiter, as in generate_metadata_imports.py.",
    )
    parser.add_argument(
        "--id-column",
        default="corpusid",
        help="Column copied into the report to identify records "
        "(default: corpusid; ignored if the input lacks it).",
    )
    parser.add_argument(
        "--no-keep-mtime",
        action="store_true",
        help="Do not copy the input's modification time to --output. By default "
        "it is copied so ZIPs generated from unchanged rows keep their SHA-256 "
        "in the import ledger.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace --output and --report if they exist.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = args.report or args.output.with_name(f"{args.output.stem}_repairs.tsv")
    for path, name in ((args.output, "--output"), (report, "--report")):
        if same_file(path, args.input):
            print(f"error: {name} {path} is the --input file", file=sys.stderr)
            return 1
    if same_file(report, args.output):
        print(f"error: --report {report} is the --output file", file=sys.stderr)
        return 1
    existing = [path for path in (args.output, report) if path.exists()]
    if existing and not args.overwrite:
        names = ", ".join(str(path) for path in existing)
        print(f"error: {names} already exists; pass --overwrite", file=sys.stderr)
        return 1
    repairs = repair_file(
        args.input,
        args.output,
        delimiter=args.delimiter,
        id_column=args.id_column or None,
        keep_mtime=not args.no_keep_mtime,
    )
    write_repair_report(repairs, report)
    rules = count_rules(repairs)
    summary = ", ".join(f"{rule}={rules[rule]}" for rule in sorted(rules)) or "none"
    records = len({repair.record_number for repair in repairs})
    print(
        f"repaired {len(repairs)} list element(s) in {records} record(s) "
        f"(rules: {summary})"
    )
    print(f"output={args.output}")
    print(f"report={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
