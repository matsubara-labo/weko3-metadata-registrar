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

from generation.metadata_pipeline import (
    DEFAULT_REGISTRATION_CONFIG_PATH,
    MetadataGenerationConfig,
    find_unrelated_zip_files,
    generate_metadata_artifacts,
    summarize_artifacts,
)
from generation.registration_config import is_publish_date


def publish_date_argument(value: str) -> str:
    if not is_publish_date(value):
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a valid YYYY-MM-DD date, e.g. 2025-05-27"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate WEKO metadata import TSV/ZIP files."
    )
    parser.add_argument(
        "--input", type=Path, required=True, help="Source CSV or TSV file."
    )
    parser.add_argument(
        "--delimiter",
        choices=("auto", "comma", "tab"),
        default="auto",
        help="Input delimiter. auto uses .tsv/.csv extensions, otherwise compares tabs and commas in the header line.",
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Directory for generated files."
    )
    parser.add_argument(
        "--registration-config",
        type=Path,
        default=DEFAULT_REGISTRATION_CONFIG_PATH,
        help="Registration config JSON file. Uses config/metadata_registration.json by default.",
    )
    parser.add_argument(
        "--index-name",
        help="WEKO index name. If omitted, use default_index from registration config.",
    )
    parser.add_argument(
        "--publish-date",
        type=publish_date_argument,
        help="Publish date in YYYY-MM-DD format. If omitted, use registration config.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help="Rows per output file. 0 means no chunking.",
    )
    parser.add_argument(
        "--zip", action="store_true", help="Also create import zip files."
    )
    parser.add_argument(
        "--keep-tsv",
        action="store_true",
        help="Keep TSV files when zip files are created.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Remove all existing output_write*.tsv/import*.zip/invalid_rows.tsv files in the output directory before generating. Without it, generation stops if any exist.",
    )
    parser.add_argument(
        "--skip-invalid-rows",
        action="store_true",
        help="Generate from valid rows only and write invalid rows to invalid_rows.tsv in the output directory. Without it, generation stops if any row is invalid.",
    )
    parser.add_argument(
        "--strict-columns",
        action="store_true",
        help="Stop if the input has columns that are not ItemType fields. Without it, such columns are ignored with a warning.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = MetadataGenerationConfig(
        input_path=args.input,
        output_dir=args.output_dir,
        index_name=args.index_name,
        publish_date=args.publish_date,
        chunk_size=args.chunk_size or None,
        zip_outputs=args.zip,
        keep_tsv=args.keep_tsv or not args.zip,
        registration_config_path=args.registration_config,
        delimiter=args.delimiter,
        overwrite=args.overwrite,
        skip_invalid_rows=args.skip_invalid_rows,
        strict_columns=args.strict_columns,
    )
    skipped: list[int] = []

    def report_invalid_rows(path: Path, count: int) -> None:
        skipped.append(count)
        print(f"skipped {count} invalid row(s); see {path}")

    artifacts = generate_metadata_artifacts(
        config,
        on_remove=lambda path: print(f"removed {path}"),
        on_invalid_rows=report_invalid_rows,
        on_warning=lambda message: print(f"warning: {message}"),
    )
    if skipped and not artifacts:
        print("No valid rows were found; no import files were generated.")
        return 1
    print(summarize_artifacts(artifacts))
    for artifact in artifacts:
        print(
            f"chunk={artifact.chunk_index} rows={artifact.row_count} tsv={artifact.tsv_path}"
        )
        if artifact.zip_path:
            print(f"chunk={artifact.chunk_index} zip={artifact.zip_path}")
    for path in find_unrelated_zip_files(config.output_dir):
        print(
            f"warning: {path} is not a generated file but will be imported "
            "if this directory is used as --zip-dir"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
