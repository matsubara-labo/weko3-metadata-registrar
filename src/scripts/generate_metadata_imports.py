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
    MetadataGenerationConfig,
    generate_metadata_artifacts,
    summarize_artifacts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate WEKO metadata import TSV/ZIP files."
    )
    parser.add_argument(
        "--input", type=Path, required=True, help="Source CSV or TSV file."
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Directory for generated files."
    )
    parser.add_argument("--schema-config", type=Path, help="Metadata schema json file.")
    parser.add_argument(
        "--index-id", help="WEKO index id. If omitted, use the value in schema config."
    )
    parser.add_argument(
        "--index-name",
        help="WEKO index name. If omitted, use the value in schema config.",
    )
    parser.add_argument(
        "--publish-date",
        help="Publish date in YYYY-MM-DD format. If omitted, use the value in schema config.",
    )
    parser.add_argument(
        "--publish-status",
        help="WEKO publish status. If omitted, use the value in schema config.",
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = MetadataGenerationConfig(
        input_path=args.input,
        output_dir=args.output_dir,
        schema_config_path=args.schema_config,
        index_id=args.index_id,
        index_name=args.index_name,
        publish_date=args.publish_date,
        publish_status=args.publish_status,
        chunk_size=args.chunk_size or None,
        zip_outputs=args.zip,
        keep_tsv=args.keep_tsv or not args.zip,
    )
    artifacts = generate_metadata_artifacts(config)
    print(summarize_artifacts(artifacts))
    for artifact in artifacts:
        print(
            f"chunk={artifact.chunk_index} rows={artifact.row_count} tsv={artifact.tsv_path}"
        )
        if artifact.zip_path:
            print(f"chunk={artifact.chunk_index} zip={artifact.zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
