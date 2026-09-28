from __future__ import annotations

import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from generation.metadata_pipeline import (
    MetadataGenerationConfig,
    MetadataInputError,
    OutputExistsError,
    find_generated_artifacts,
    generate_metadata_artifacts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPORT = (
    REPOSITORY_ROOT / "sample" / "AXIES2025" / "config" / "ItemType_export_sample.zip"
)
FIELDNAMES = ["corpusid", "Title", "Creator"]


class InvalidRowsGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.output_dir = self.root / "output"
        self.report_path = self.output_dir / "invalid_rows.tsv"
        self.source_path = self.root / "source.csv"
        self.settings_path = self.root / "settings.json"
        self.settings_path.write_text(
            json.dumps(
                {
                    "weko_base_url": "https://weko.example.org",
                    "item_type_export": str(SAMPLE_EXPORT),
                    "indexes": {"Example": "999"},
                    "default_index": "Example",
                    "publish_date": "2026-08-23",
                    "default_languages": {"Title": "en"},
                }
            ),
            encoding="utf-8",
        )
        self._write_source(
            [
                ("1", "First", "['Alice']"),
                ("2", "[None]", "['Bob']"),
                ("3", "Third", "['Carol', '', 'Dave']"),
                ("4", "['', ' ']", "x\ty"),
                ("5", "Fifth", "[1]"),
            ]
        )

    def _write_source(self, rows: list[tuple[str, str, str]]) -> None:
        with self.source_path.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(FIELDNAMES)
            writer.writerows(rows)

    def _config(self, **overrides) -> MetadataGenerationConfig:
        values = {
            "input_path": self.source_path,
            "output_dir": self.output_dir,
            "registration_config_path": self.settings_path,
        }
        values.update(overrides)
        return MetadataGenerationConfig(**values)

    def _read_tsv(self, path: Path) -> list[list[str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            return list(csv.reader(file_obj, delimiter="\t"))

    def test_strict_mode_lists_all_invalid_rows_and_writes_nothing(self) -> None:
        with self.assertRaises(MetadataInputError) as context:
            generate_metadata_artifacts(self._config())

        lines = str(context.exception).splitlines()
        self.assertEqual(len(lines), 3)
        self.assertRegex(lines[0], r"source\.csv:3: .*'Title' is empty$")
        self.assertRegex(lines[1], r"source\.csv:5: .*'Title' is empty$")
        self.assertRegex(lines[2], r"source\.csv:6: 'Creator': .*int")
        self.assertFalse(self.output_dir.exists())

    def test_strict_mode_keeps_previous_outputs_with_overwrite(self) -> None:
        self.output_dir.mkdir()
        (self.output_dir / "import.zip").write_text("old", encoding="utf-8")

        with self.assertRaises(MetadataInputError):
            generate_metadata_artifacts(self._config(overwrite=True, zip_outputs=True))

        self.assertEqual(
            [path.name for path in self.output_dir.iterdir()], ["import.zip"]
        )

    def test_skip_invalid_rows_writes_valid_rows_and_report(self) -> None:
        reported: list[tuple[Path, int]] = []

        artifacts = generate_metadata_artifacts(
            self._config(skip_invalid_rows=True),
            on_invalid_rows=lambda path, count: reported.append((path, count)),
        )

        self.assertEqual(reported, [(self.report_path, 3)])
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].row_count, 2)
        written = self._read_tsv(artifacts[0].tsv_path)
        data_rows = written[5:]
        self.assertEqual(
            [
                row[written[1].index(".metadata.item_1748316538548")]
                for row in data_rows
            ],
            ["1", "3"],
        )
        self.assertIn("Carol", data_rows[1])
        self.assertIn("Dave", data_rows[1])
        self.assertIn("Creator[1].None", written[2])
        self.assertNotIn("Creator[2].None", written[2])

        report = self._read_tsv(self.report_path)
        self.assertEqual(report[0], ["_invalid_row", "_invalid_reason", *FIELDNAMES])
        self.assertEqual([row[0] for row in report[1:]], ["3", "5", "6"])
        self.assertIn("'Title' is empty", report[1][1])
        self.assertEqual(report[1][2:], ["2", "[None]", "['Bob']"])
        self.assertEqual(report[2][2:], ["4", "['', ' ']", "x\ty"])
        self.assertEqual(report[3][2:], ["5", "Fifth", "[1]"])
        self.assertTrue(self.report_path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_report_is_not_written_without_invalid_rows(self) -> None:
        self._write_source([("1", "First", "['Alice']")])
        reported: list[tuple[Path, int]] = []

        artifacts = generate_metadata_artifacts(
            self._config(skip_invalid_rows=True),
            on_invalid_rows=lambda path, count: reported.append((path, count)),
        )

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(reported, [])
        self.assertFalse(self.report_path.exists())

    def test_report_is_protected_and_removed_like_other_outputs(self) -> None:
        generate_metadata_artifacts(self._config(skip_invalid_rows=True))
        self.assertIn(self.report_path, find_generated_artifacts(self.output_dir))

        with self.assertRaisesRegex(OutputExistsError, r"invalid_rows\.tsv"):
            generate_metadata_artifacts(self._config(skip_invalid_rows=True))

        self._write_source([("1", "First", "['Alice']")])
        removed: list[Path] = []
        generate_metadata_artifacts(
            self._config(overwrite=True, skip_invalid_rows=True),
            on_remove=removed.append,
        )
        self.assertIn(self.report_path, removed)
        self.assertFalse(self.report_path.exists())

    def test_all_invalid_rows_replace_only_the_report(self) -> None:
        self._write_source([("1", "[None]", ""), ("2", "['']", "")])
        self.output_dir.mkdir()
        (self.output_dir / "import.zip").write_text("old", encoding="utf-8")
        (self.output_dir / "output_write.tsv").write_text("old", encoding="utf-8")
        self.report_path.write_text("old", encoding="utf-8")
        reported: list[tuple[Path, int]] = []

        artifacts = generate_metadata_artifacts(
            self._config(skip_invalid_rows=True, overwrite=True, zip_outputs=True),
            on_invalid_rows=lambda path, count: reported.append((path, count)),
        )

        self.assertEqual(artifacts, [])
        self.assertEqual(reported, [(self.report_path, 2)])
        self.assertEqual(
            sorted(path.name for path in self.output_dir.iterdir()),
            ["import.zip", "invalid_rows.tsv", "output_write.tsv"],
        )
        self.assertEqual(
            (self.output_dir / "import.zip").read_text(encoding="utf-8"), "old"
        )
        self.assertEqual(
            [row[0] for row in self._read_tsv(self.report_path)[1:]], ["2", "3"]
        )

    def _rerun_from_report(self, fixed_titles: dict[str, str]) -> list[object]:
        generate_metadata_artifacts(self._config(skip_invalid_rows=True))
        report = self._read_tsv(self.report_path)
        title_column = report[0].index("Title")
        for row in report[1:]:
            row[title_column] = fixed_titles.get(row[2], row[title_column])
        with self.report_path.open("w", encoding="utf-8-sig", newline="") as file_obj:
            csv.writer(file_obj, delimiter="\t", lineterminator="\n").writerows(report)
        return generate_metadata_artifacts(
            self._config(
                input_path=self.report_path, overwrite=True, skip_invalid_rows=True
            )
        )

    def test_report_can_be_used_as_input_for_fixed_rows(self) -> None:
        artifacts = self._rerun_from_report({"2": "Second"})

        self.assertEqual([artifact.row_count for artifact in artifacts], [1])
        written = self._read_tsv(artifacts[0].tsv_path)
        self.assertIn("Second", written[5])
        report = self._read_tsv(self.report_path)
        self.assertEqual(report[0], ["_invalid_row", "_invalid_reason", *FIELDNAMES])
        self.assertEqual([row[2] for row in report[1:]], ["4", "5"])
        self.assertEqual([row[0] for row in report[1:]], ["3", "4"])

    def test_report_input_is_kept_when_all_rows_are_fixed(self) -> None:
        self._write_source([("1", "First", ""), ("2", "[None]", "")])

        artifacts = self._rerun_from_report({"2": "Second"})

        self.assertEqual([artifact.row_count for artifact in artifacts], [1])
        self.assertTrue(self.report_path.exists())
        self.assertEqual(
            [row[3] for row in self._read_tsv(self.report_path)[1:]], ["Second"]
        )

    def test_zip_output_contains_only_valid_rows(self) -> None:
        artifacts = generate_metadata_artifacts(
            self._config(skip_invalid_rows=True, zip_outputs=True, keep_tsv=False)
        )

        with zipfile.ZipFile(artifacts[0].zip_path) as archive:
            text = archive.read("data/output_write.tsv").decode("utf-8-sig")
        self.assertEqual(len(text.splitlines()), 7)


if __name__ == "__main__":
    unittest.main()
