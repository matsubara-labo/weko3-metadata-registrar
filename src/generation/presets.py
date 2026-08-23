from __future__ import annotations

from pathlib import Path

from .metadata_pipeline import MetadataGenerationConfig


def build_single_file_export_config(base_dir: Path) -> MetadataGenerationConfig:
    return MetadataGenerationConfig(
        input_path=base_dir / "source_data" / "chunk25_single-url_safe_utf-8.tsv",
        output_dir=base_dir / "output",
        index_id=None,
        index_name=None,
        publish_date=None,
        publish_status=None,
        chunk_size=None,
        zip_outputs=False,
        keep_tsv=True,
    )


def build_chunked_zip_export_config(base_dir: Path) -> MetadataGenerationConfig:
    return MetadataGenerationConfig(
        input_path=base_dir / "source_data" / "sample.csv",
        output_dir=base_dir / "output" / "zip_data",
        index_id=None,
        index_name=None,
        publish_date=None,
        publish_status=None,
        chunk_size=50,
        zip_outputs=True,
        keep_tsv=False,
    )
