from __future__ import annotations

import contextlib
import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from importers import selenium_auto_register
from importers.import_result import (
    ImportResultError,
    count_expected_records,
    parse_import_result,
    summarize_import_result,
)
from importers.selenium_auto_register import (
    MAX_IMPORT_ATTEMPTS,
    ImportRunResults,
    WekoImportConfig,
    build_parser,
    driver_connection_lost,
    driver_session_lost,
    run_import,
    store_result_file,
)

EN_HEADER = ["No.", "Start Date", "End Date", "Item ID", "Status", "Import Result"]
JA_HEADER = [
    "No.",
    "開始日時",
    "終了日時",
    "アイテムID",
    "ステータス",
    "インポート結果",
]


def write_result(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    delimiter = "," if path.suffix == ".csv" else "\t"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def en_row(no: int, status: str = "Done", result: str = "Success") -> list[str]:
    return [str(no), "2026-09-27 10:00:00", "2026-09-27 10:00:05", "", status, result]


def write_import_zip(path: Path, record_count: int) -> Path:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(
        ["#ItemType", "Sample(1)", "https://weko.example/items/jsonschema/1"]
    )
    writer.writerow(["#.id", ".uri", ".metadata.path[0]", ".metadata.title"])
    writer.writerow(["#ID", "URI", ".IndexID[0]", "Title"])
    writer.writerow(["#", "", "Allow Multiple", "Required"])
    writer.writerow(["#", "", "", ""])
    for index in range(record_count):
        title = "multi\nline title" if index == 0 else f"title {index}"
        writer.writerow(["", "", "1", title])
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/output_write.tsv", "﻿" + buffer.getvalue())
    return path


class ParseImportResultTests(unittest.TestCase):
    def test_parses_english_tsv_and_japanese_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            en_path = write_result(
                Path(directory) / "List_Download_en.tsv",
                EN_HEADER,
                [en_row(1), ["", "", "", "", "", ""], en_row(2)],
            )
            ja_path = write_result(
                Path(directory) / "List_Download_ja.csv",
                JA_HEADER,
                [["1", "", "", "10", "完了", "成功"]],
            )
            en_rows = parse_import_result(en_path)
            ja_rows = parse_import_result(ja_path)

        self.assertEqual([row.no for row in en_rows], ["1", "2"])
        self.assertTrue(all(row.succeeded for row in en_rows))
        self.assertEqual(len(ja_rows), 1)
        self.assertEqual(ja_rows[0].item_id, "10")
        self.assertTrue(ja_rows[0].succeeded)

    def test_rejects_result_with_too_few_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_result(Path(directory) / "r.tsv", ["No.", "Status"], [])
            with self.assertRaisesRegex(ImportResultError, "columns"):
                parse_import_result(path)


class ExpectedRecordCountTests(unittest.TestCase):
    def test_counts_data_rows_in_generated_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            zip_path = write_import_zip(Path(directory) / "import.zip", 2)
            self.assertEqual(count_expected_records(zip_path), 2)


class SummaryTests(unittest.TestCase):
    def summarize(self, rows: list[list[str]], record_count: int, header=EN_HEADER):
        with tempfile.TemporaryDirectory() as directory:
            result = write_result(Path(directory) / "r.tsv", header, rows)
            zip_path = write_import_zip(Path(directory) / "i.zip", record_count)
            return summarize_import_result(result, zip_path)

    def test_all_success_rows_matching_count_succeed(self) -> None:
        self.assertTrue(self.summarize([en_row(1), en_row(2)], 2).succeeded)
        ja_rows = [["1", "", "", "", "完了", "成功"], ["2", "", "", "", "完了", "成功"]]
        self.assertTrue(self.summarize(ja_rows, 2, JA_HEADER).succeeded)

    def test_count_mismatch_fails(self) -> None:
        self.assertFalse(self.summarize([en_row(1)], 2).succeeded)

    def test_error_row_fails(self) -> None:
        summary = self.summarize(
            [en_row(1), en_row(2, "FAILURE", "Error: DOI duplicated")], 2
        )
        self.assertFalse(summary.succeeded)
        self.assertEqual(summary.success_count, 1)
        self.assertEqual([row.no for row in summary.failed_rows], ["2"])
        self.assertIn("Error: DOI duplicated", "\n".join(summary.describe()))

    def test_empty_result_fails(self) -> None:
        self.assertFalse(self.summarize([], 0).succeeded)


class StoreResultFileTests(unittest.TestCase):
    def test_failed_rename_keeps_the_downloaded_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            downloaded = write_result(
                Path(directory) / "List_Download_x.tsv", EN_HEADER, []
            )
            with (
                patch.object(Path, "rename", side_effect=PermissionError("busy")),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                stored = store_result_file(downloaded, Path("import_001.zip"))

            self.assertEqual(stored, downloaded)
            self.assertTrue(downloaded.exists())
        self.assertIn("could not rename", output.getvalue())

    def test_result_is_renamed_after_the_zip_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = store_result_file(
                write_result(root / "List_Download_x.tsv", EN_HEADER, []),
                Path("zips/import_001.zip"),
            )
            second = store_result_file(
                write_result(root / "List_Download_y.csv", EN_HEADER, []),
                Path("zips/import_001.zip"),
            )
            third = store_result_file(
                write_result(root / "List_Download_z.tsv", EN_HEADER, []),
                Path("zips/import_001.zip"),
            )

            self.assertEqual(first, root / "import_001_result.tsv")
            self.assertEqual(second, root / "import_001_result.csv")
            self.assertEqual(third, root / "import_001_result_001.tsv")
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                [
                    "import_001_result.csv",
                    "import_001_result.tsv",
                    "import_001_result_001.tsv",
                ],
            )


class RunImportResultTests(unittest.TestCase):
    def run_with_result(
        self, base_dir: Path, rows: list[list[str]], **config_overrides
    ) -> tuple[Path, object, str]:
        zip_dir = base_dir / "output" / "zip_data"
        zip_dir.mkdir(parents=True)
        zip_path = write_import_zip(zip_dir / "import.zip", 2)
        download_dir = base_dir / "output" / "import_results"
        download_dir.mkdir(parents=True)
        result_path = write_result(
            download_dir / "List_Download_1.tsv", EN_HEADER, rows
        )
        config = WekoImportConfig(
            base_dir=base_dir, weko_base_url="https://weko.example", **config_overrides
        )
        output = io.StringIO()
        with (
            patch.object(selenium_auto_register, "create_driver") as create_driver,
            patch.object(selenium_auto_register, "login"),
            patch.object(
                selenium_auto_register, "import_one_zip", return_value=result_path
            ) as import_one_zip,
            contextlib.redirect_stdout(output),
        ):
            try:
                outcome: object = run_import(config)
            except ImportResultError as exc:
                outcome = exc
        self.assertEqual(import_one_zip.call_count, 1)
        self.assertEqual(create_driver.call_count, 1)
        return zip_path, outcome, output.getvalue()

    def test_success_moves_zip_to_processed_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            zip_path, outcome, output = self.run_with_result(
                base_dir, [en_row(1), en_row(2)]
            )
            self.assertIsInstance(outcome, ImportRunResults)
            self.assertEqual(len(outcome.imported), 1)
            self.assertFalse(zip_path.exists())
            self.assertTrue(
                (base_dir / "output" / "uploaded_zip_data" / "import.zip").exists()
            )
            self.assertEqual(
                outcome.imported[0][1],
                base_dir / "output" / "import_results" / "import_result.tsv",
            )
            self.assertTrue(outcome.imported[0][1].exists())
        self.assertIn("result: success=2/2", output)

    def test_failure_moves_zip_to_failed_dir_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            zip_path, outcome, output = self.run_with_result(
                base_dir, [en_row(1), en_row(2, "FAILURE", "Error: failed")]
            )
            self.assertIsInstance(outcome, ImportResultError)
            self.assertFalse(driver_session_lost(outcome))
            self.assertFalse(driver_connection_lost(outcome))
            self.assertFalse(zip_path.exists())
            self.assertTrue(
                (base_dir / "output" / "failed_zip_data" / "import.zip").exists()
            )
            self.assertFalse((base_dir / "output" / "uploaded_zip_data").exists())
            self.assertTrue(
                (base_dir / "output" / "import_results" / "import_result.tsv").exists()
            )
        self.assertIn("success=1/2 failure=1 expected=2", output)
        self.assertIn("Error: failed", output)
        self.assertGreater(MAX_IMPORT_ATTEMPTS, 1)

    def test_failure_does_not_delete_zip_when_delete_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            failed_dir = base_dir / "custom_failed"
            _, outcome, _ = self.run_with_result(
                base_dir,
                [en_row(1)],
                delete_zip_after_import=True,
                failed_zip_dir=failed_dir,
            )
            self.assertIsInstance(outcome, ImportResultError)
            self.assertTrue((failed_dir / "import.zip").exists())

    def test_unparsable_result_moves_zip_to_failed_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            zip_path, outcome, output = self.run_with_result(
                base_dir, [["1", "broken"]], keep_zip_after_import=True
            )
            self.assertIsInstance(outcome, ImportResultError)
            self.assertFalse(zip_path.exists())
            self.assertTrue(
                (base_dir / "output" / "failed_zip_data" / "import.zip").exists()
            )
        self.assertIn("result: unparsable", output)

    def test_failed_zip_dir_option_and_default(self) -> None:
        args = build_parser().parse_args(["--failed-zip-dir", "failed"])
        self.assertEqual(args.failed_zip_dir, Path("failed"))
        config = WekoImportConfig(base_dir=Path("/base"))
        self.assertEqual(
            config.resolved_failed_zip_dir(), Path("/base/output/failed_zip_data")
        )


if __name__ == "__main__":
    unittest.main()
