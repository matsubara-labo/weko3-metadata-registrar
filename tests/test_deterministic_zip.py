from __future__ import annotations

import calendar
import csv
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from generation import metadata_pipeline
from generation.metadata_pipeline import (
    MetadataGenerationConfig,
    generate_metadata_artifacts,
    zip_date_time_from_timestamp,
    zip_tsv,
)
from importers.import_ledger import STATUS_SUCCEEDED, ImportLedger, file_sha256

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPORT = (
    REPOSITORY_ROOT / "sample" / "AXIES2025" / "config" / "ItemType_export_sample.zip"
)
# 2026-08-23 12:34:57 UTC; ZIP stores it rounded down to 12:34:56.
INPUT_MTIME = calendar.timegm((2026, 8, 23, 12, 34, 57))
FIELDNAMES = ["corpusid", "Title", "Title_g", "Creator", "PublicationYear_g"]


class DeterministicZipTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
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
                    "default_languages": {"Title": "en", "Title_g": "en"},
                }
            ),
            encoding="utf-8",
        )
        self._write_source(["Title 0", "Title 1"])

    def _write_source(self, titles: list[str]) -> None:
        with self.source_path.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=FIELDNAMES)
            writer.writeheader()
            for index, title in enumerate(titles):
                writer.writerow(
                    {
                        "corpusid": str(index),
                        "Title": title,
                        "Title_g": "Alternative title",
                        "Creator": "['Alice']",
                        "PublicationYear_g": "2026-08-23",
                    }
                )

    def _generate(
        self, output_name: str, tsv_mtime: int, input_mtime: int = INPUT_MTIME
    ) -> Path:
        real_zip_tsv = metadata_pipeline.zip_tsv

        def zip_with_tsv_mtime(tsv_path: Path, zip_path: Path, date_time) -> None:
            os.utime(tsv_path, (tsv_mtime, tsv_mtime))
            real_zip_tsv(tsv_path, zip_path, date_time)

        os.utime(self.source_path, (input_mtime, input_mtime))
        config = MetadataGenerationConfig(
            input_path=self.source_path,
            output_dir=self.root / output_name,
            registration_config_path=self.settings_path,
            zip_outputs=True,
            keep_tsv=True,
        )
        with patch.object(metadata_pipeline, "zip_tsv", zip_with_tsv_mtime):
            artifacts = generate_metadata_artifacts(config)
        self.assertEqual(len(artifacts), 1)
        zip_path = artifacts[0].zip_path
        assert zip_path is not None
        return zip_path

    def _member_date_time(self, zip_path: Path) -> tuple[int, ...]:
        with zipfile.ZipFile(zip_path) as archive:
            return archive.infolist()[0].date_time

    def test_regenerated_zip_is_byte_identical(self) -> None:
        first = self._generate("first", 1_000_000_000)
        second = self._generate("second", 1_700_000_000)

        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(file_sha256(first), file_sha256(second))

    def test_zip_member_metadata_is_fixed_and_content_unchanged(self) -> None:
        zip_path = self._generate("output", 1_700_000_000)
        tsv_path = zip_path.parent / "output_write.tsv"

        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            self.assertEqual(
                [info.filename for info in infos], ["data/output_write.tsv"]
            )
            info = infos[0]
            self.assertEqual(info.date_time, (2026, 8, 23, 12, 34, 56))
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(info.external_attr, 0o644 << 16)
            self.assertEqual(archive.read(info), tsv_path.read_bytes())

    def test_changed_row_changes_hash(self) -> None:
        first = self._generate("first", 1_700_000_000)
        self._write_source(["Title 0", "Changed title"])
        second = self._generate("second", 1_700_000_000)

        self.assertNotEqual(file_sha256(first), file_sha256(second))

    def test_changed_input_mtime_changes_hash(self) -> None:
        first = self._generate("first", 1_700_000_000)
        second = self._generate("second", 1_700_000_000, INPUT_MTIME + 2)

        self.assertNotEqual(file_sha256(first), file_sha256(second))

    def test_pre_1980_input_mtime_is_clamped(self) -> None:
        zip_path = self._generate("output", 1_700_000_000, 0)

        self.assertEqual(self._member_date_time(zip_path), (1980, 1, 1, 0, 0, 0))

    def test_sub_second_input_mtime_is_truncated_exactly(self) -> None:
        os.utime(self.source_path, ns=(1_700_000_001_999_999_900,) * 2)
        config = MetadataGenerationConfig(
            input_path=self.source_path,
            output_dir=self.root / "exact",
            registration_config_path=self.settings_path,
            zip_outputs=True,
        )
        artifacts = generate_metadata_artifacts(config)
        zip_path = artifacts[0].zip_path
        assert zip_path is not None

        # 1700000001 is 2023-11-14 22:13:21 UTC; float st_mtime rounds to ...002.
        self.assertEqual(self._member_date_time(zip_path), (2023, 11, 14, 22, 13, 20))

    def test_zip_date_time_rounds_down_and_clamps(self) -> None:
        self.assertEqual(
            zip_date_time_from_timestamp(INPUT_MTIME), (2026, 8, 23, 12, 34, 56)
        )
        self.assertEqual(zip_date_time_from_timestamp(-1), (1980, 1, 1, 0, 0, 0))
        self.assertEqual(
            zip_date_time_from_timestamp(2**40), (2107, 12, 31, 23, 59, 58)
        )

    def test_zip_tsv_ignores_tsv_mtime(self) -> None:
        tsv_path = self.root / "output_write.tsv"
        tsv_path.write_bytes(b"\xef\xbb\xbf#header\nrow\n")
        date_time = (2026, 8, 23, 12, 34, 56)
        os.utime(tsv_path, (1_000_000_000, 1_000_000_000))
        zip_tsv(tsv_path, self.root / "a" / "import.zip", date_time)
        os.utime(tsv_path, (1_700_000_000, 1_700_000_000))
        zip_tsv(tsv_path, self.root / "b" / "import.zip", date_time)

        first = hashlib.sha256((self.root / "a" / "import.zip").read_bytes())
        second = hashlib.sha256((self.root / "b" / "import.zip").read_bytes())
        self.assertEqual(first.hexdigest(), second.hexdigest())

    def test_ledger_blocks_regenerated_zip(self) -> None:
        first = self._generate("first", 1_000_000_000)
        ledger = ImportLedger(self.root / "import_ledger.jsonl")
        ledger.append(first.name, file_sha256(first), STATUS_SUCCEEDED)

        second = self._generate("second", 1_700_000_000)
        record = ledger.blocking_record(file_sha256(second))

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, STATUS_SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
