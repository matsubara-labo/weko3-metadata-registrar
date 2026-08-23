# /// script
# requires-python = ">=3.13"
# ///
#
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generation.metadata_pipeline import (
    generate_metadata_artifacts,
    summarize_artifacts,
)
from generation.presets import build_chunked_zip_export_config


def main() -> int:
    base_dir = Path(__file__).resolve().parents[2]
    config = build_chunked_zip_export_config(base_dir)
    artifacts = generate_metadata_artifacts(config)
    print(summarize_artifacts(artifacts))
    for artifact in artifacts:
        if artifact.zip_path:
            print(artifact.zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
