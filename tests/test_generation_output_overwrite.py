from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from generation.metadata_pipeline import (
    MetadataGenerationConfig,
    MetadataInputError,
    OutputExistsError,
    find_generated_artifacts,
    find_unrelated_zip_files,
    generate_metadata_artifacts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPORT = (
    REPOSITORY_ROOT / "sample" / "AXIES2025" / "config" / "ItemType_export_sample.zip"
)
FIELDNAMES = ["corpusid", "Title", "Title_g", "Creator", "PublicationYear_g"]


class GenerationOutputOverwriteTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.output_dir = self.root / "output"
        self.source_path = self.root / "source.csv"
        self._write_source(1)
        self.settings_path = self.root / "settings.json"
        self.settings_path.write_text(
            json.dumps(
                {
                    "weko_base_url": "https://weko.example.org",
                    "item_type_export": str(SAMPLE_EXPORT),
                    "indexes": {"Example": "999"},
                    "default_index": "Example",
                    "publish_date": "2026-08-23",
                    "default_languages": {"Title": "en", "Title_g": "en"},
                }
            ),
            encoding="utf-8",
        )

    def _write_source(self, row_count: int) -> None:
        with self.source_path.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=FIELDNAMES)
            writer.writeheader()
            for index in range(row_count):
                writer.writerow(
                    {
                        "corpusid": str(index),
                        "Title": f"Title {index}",
                        "Title_g": "Alternative title",
                        "Creator": "['Alice']",
                        "PublicationYear_g": "2026-08-23",
                    }
                )

    def _config(self, **overrides) -> MetadataGenerationConfig:
        values = {
            "input_path": self.source_path,
            "output_dir": self.output_dir,
            "registration_config_path": self.settings_path,
            "zip_outputs": True,
            "keep_tsv": False,
        }
        values.update(overrides)
        return MetadataGenerationConfig(**values)

    def _seed(self, *names: str) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            (self.output_dir / name).write_text("old", encoding="utf-8")

    def _names(self) -> set[str]:
        return {path.name for path in self.output_dir.iterdir()}

    def test_only_generated_artifact_names_are_detected(self) -> None:
        self._seed(
            "output_write.tsv",
            "output_write_12.tsv",
            "import.zip",
            "import_001.zip",
            "import_abc.zip",
            "import_001.zip.bak",
            "notes.txt",
        )
        (self.output_dir / "import_002.zip").mkdir()
        (self.output_dir / "sub").mkdir()
        (self.output_dir / "sub" / "import_003.zip").write_text("x")

        self.assertEqual(
            [path.name for path in find_generated_artifacts(self.output_dir)],
            ["import.zip", "import_001.zip", "output_write.tsv", "output_write_12.tsv"],
        )

    def test_upper_case_generated_names_are_detected(self) -> None:
        self._seed("IMPORT.ZIP", "Output_Write_002.TSV")

        self.assertEqual(
            [path.name for path in find_generated_artifacts(self.output_dir)],
            ["IMPORT.ZIP", "Output_Write_002.TSV"],
        )
        with self.assertRaisesRegex(OutputExistsError, r"IMPORT\.ZIP"):
            generate_metadata_artifacts(self._config())

    def test_unrelated_zip_files_are_listed_but_kept(self) -> None:
        self._seed("import_001.zip", "manual.zip", "OTHER.ZIP", "notes.txt")
        (self.output_dir / "dir.zip").mkdir()

        self.assertEqual(
            [path.name for path in find_unrelated_zip_files(self.output_dir)],
            ["OTHER.ZIP", "manual.zip"],
        )
        generate_metadata_artifacts(self._config(overwrite=True))
        self.assertEqual(
            self._names(),
            {"import.zip", "manual.zip", "OTHER.ZIP", "notes.txt", "dir.zip"},
        )

    def test_empty_output_dir_generates_as_before(self) -> None:
        artifacts = generate_metadata_artifacts(self._config())

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(self._names(), {"import.zip"})

    def test_existing_artifact_is_rejected_without_writing(self) -> None:
        self._seed("import_001.zip")

        with self.assertRaisesRegex(
            OutputExistsError, r"import_001\.zip.*--overwrite"
        ) as context:
            generate_metadata_artifacts(self._config())

        self.assertIsInstance(context.exception, FileExistsError)
        self.assertEqual(self._names(), {"import_001.zip"})
        self.assertEqual(
            (self.output_dir / "import_001.zip").read_text(encoding="utf-8"), "old"
        )

    def test_error_lists_at_most_ten_names(self) -> None:
        self._seed(*(f"import_{index:03d}.zip" for index in range(1, 13)))

        with self.assertRaises(OutputExistsError) as context:
            generate_metadata_artifacts(self._config())

        message = str(context.exception)
        self.assertIn("import_010.zip", message)
        self.assertNotIn("import_011.zip", message)
        self.assertIn("... and 2 more", message)

    def test_overwrite_removes_stale_chunks_and_keeps_unrelated_files(self) -> None:
        self._seed(
            "import_001.zip",
            "import_002.zip",
            "import_003.zip",
            "output_write_001.tsv",
            "notes.txt",
        )
        removed: list[Path] = []

        artifacts = generate_metadata_artifacts(
            self._config(overwrite=True), on_remove=removed.append
        )

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(self._names(), {"import.zip", "notes.txt"})
        self.assertEqual(
            sorted(path.name for path in removed),
            [
                "import_001.zip",
                "import_002.zip",
                "import_003.zip",
                "output_write_001.tsv",
            ],
        )

    def test_load_error_with_overwrite_keeps_previous_outputs(self) -> None:
        self._seed("import_001.zip", "import_002.zip")
        self.source_path.write_text(
            "corpusid,Unknown\n1,x\n", encoding="utf-8", newline=""
        )

        with self.assertRaises(MetadataInputError):
            generate_metadata_artifacts(self._config(overwrite=True))

        self.assertEqual(self._names(), {"import_001.zip", "import_002.zip"})

    def test_empty_input_with_overwrite_removes_nothing(self) -> None:
        self._seed("import_001.zip")
        self.source_path.write_text(
            ",".join(FIELDNAMES) + "\n", encoding="utf-8", newline=""
        )

        self.assertEqual(generate_metadata_artifacts(self._config(overwrite=True)), [])
        self.assertEqual(self._names(), {"import_001.zip"})


if __name__ == "__main__":
    unittest.main()
