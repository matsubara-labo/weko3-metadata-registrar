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
    ReviewItem,
    count_rules,
    repair_file,
    same_file,
    write_repair_report,
    write_review_report,
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
        "--review",
        type=Path,
        help="TSV listing list elements with LF before a LaTeX \\n... command "
        "(e.g. \\nu), which may be a decoded \\n but are not changed. Default: "
        "<output stem>_review.tsv next to --output.",
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
        help="Replace --output, --report and --review if they exist.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = args.report or args.output.with_name(f"{args.output.stem}_repairs.tsv")
    review = args.review or args.output.with_name(f"{args.output.stem}_review.tsv")
    paths = [("--output", args.output), ("--report", report), ("--review", review)]
    for index, (name, path) in enumerate(paths):
        for other_name, other in [("--input", args.input), *paths[:index]]:
            if same_file(path, other):
                print(f"error: {name} {path} is the {other_name} file", file=sys.stderr)
                return 1
    existing = [path for _, path in paths if path.exists()]
    if existing and not args.overwrite:
        names = ", ".join(str(path) for path in existing)
        print(f"error: {names} already exists; pass --overwrite", file=sys.stderr)
        return 1
    reviews: list[ReviewItem] = []
    repairs = repair_file(
        args.input,
        args.output,
        delimiter=args.delimiter,
        id_column=args.id_column or None,
        keep_mtime=not args.no_keep_mtime,
        reviews=reviews,
    )
    write_repair_report(repairs, report)
    write_review_report(reviews, review)
    rules = count_rules(repairs)
    summary = ", ".join(f"{rule}={rules[rule]}" for rule in sorted(rules)) or "none"
    records = len({repair.record_number for repair in repairs})
    print(
        f"repaired {len(repairs)} list element(s) in {records} record(s) "
        f"(rules: {summary})"
    )
    print(f"output={args.output}")
    print(f"report={report}")
    print(
        f"review={review} ({len(reviews)} LF before a LaTeX \\n... command to check "
        "by hand; not changed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
