from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import InvalidSessionIdException
from test_import_result import EN_HEADER, en_row, write_import_zip, write_result

from importers import selenium_auto_register
from importers.import_ledger import ImportLedger, file_sha256
from importers.selenium_auto_register import (
    ImportOutcomeUnknownError,
    WekoImportConfig,
    build_parser,
    run_import,
)


def read_ledger(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class LedgerTests(unittest.TestCase):
    def test_append_keeps_existing_lines_and_tolerates_corrupt_ones(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "ledger.jsonl"
            ledger = ImportLedger(path)
            ledger.append("a.zip", "aaa", "started")
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n{not json\n[1, 2]\n")
            ledger.append("a.zip", "aaa", "succeeded", result_path=Path("r.tsv"))
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"truncated": ')
            ledger.append("b.zip", "bbb", "started")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                records = ledger.read_records()
        self.assertEqual(
            [(r.zip_name, r.status) for r in records],
            [("a.zip", "started"), ("a.zip", "succeeded"), ("b.zip", "started")],
        )
        self.assertEqual(records[1].result_path, "r.tsv")
        self.assertEqual(output.getvalue().count("corrupt import ledger line"), 3)

    def test_ledger_with_bom_still_blocks_first_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            ledger = ImportLedger(path)
            ledger.append("a.zip", "aaa", "succeeded")
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
            ledger.append("b.zip", "bbb", "started")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                blocking = ledger.blocking_record("aaa")
                records = ledger.read_records()
        self.assertIsNotNone(blocking)
        self.assertEqual(blocking.status, "succeeded")
        self.assertEqual([r.zip_name for r in records], ["a.zip", "b.zip"])
        self.assertNotIn("corrupt", output.getvalue())

    def test_record_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            ImportLedger(path).append("a.zip", "aaa", "unknown", detail="boom")
            (record,) = read_ledger(path)
        self.assertEqual(
            set(record), {"timestamp", "zip_name", "sha256", "status", "detail"}
        )
        self.assertRegex(record["timestamp"], r"[+-]\d{2}:\d{2}$")

    def test_ledger_options(self) -> None:
        args = build_parser().parse_args(
            ["--ledger-path", "l.jsonl", "--allow-reimport"]
        )
        self.assertEqual(args.ledger_path, Path("l.jsonl"))
        self.assertTrue(args.allow_reimport)
        config = WekoImportConfig(base_dir=Path("/base"))
        self.assertEqual(
            config.resolved_ledger_path(), Path("/base/output/import_ledger.jsonl")
        )
        self.assertFalse(config.allow_reimport)


class RunImportLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base_dir = Path(self.directory.name)
        self.zip_dir = self.base_dir / "output" / "zip_data"
        self.zip_dir.mkdir(parents=True)
        self.download_dir = self.base_dir / "output" / "import_results"
        self.download_dir.mkdir(parents=True)
        self.downloads = 0
        self.ledger_path = self.base_dir / "output" / "import_ledger.jsonl"

    def download_result(self, *args, **kwargs) -> Path:
        # Each WEKO download creates a new file, which run_import renames.
        self.downloads += 1
        return write_result(
            self.download_dir / f"List_Download_{self.downloads}.tsv",
            EN_HEADER,
            [en_row(1), en_row(2)],
        )

    def config(self, **overrides) -> WekoImportConfig:
        return WekoImportConfig(
            base_dir=self.base_dir, weko_base_url="https://weko.example", **overrides
        )

    def statuses(self) -> list[str]:
        return [record["status"] for record in read_ledger(self.ledger_path)]

    def run_browser_flow(
        self,
        config: WekoImportConfig,
        click_effects: list,
        load_effects: list | None = None,
    ):
        output = io.StringIO()
        with (
            patch.object(
                selenium_auto_register, "create_driver", return_value=MagicMock()
            ) as create_driver,
            patch.object(selenium_auto_register, "login"),
            patch.object(selenium_auto_register, "wait_for_present"),
            patch.object(selenium_auto_register, "prepare_file_input"),
            patch.object(
                selenium_auto_register, "click_when_ready", side_effect=click_effects
            ) as click_when_ready,
            patch.object(
                selenium_auto_register,
                "wait_for_step_ready_or_page_error",
                side_effect=load_effects,
            ),
            patch.object(selenium_auto_register, "click_element"),
            patch.object(
                selenium_auto_register,
                "wait_for_download",
                side_effect=self.download_result,
            ),
            patch.object(selenium_auto_register, "DRIVER_RETRY_DELAY_SECONDS", 0),
            contextlib.redirect_stdout(output),
        ):
            try:
                outcome: object = run_import(config)
            except Exception as exc:
                outcome = exc
        import_clicks = [
            call
            for call in click_when_ready.call_args_list
            if call.args[3] == "import button"
        ]
        return outcome, create_driver.call_count, len(import_clicks), output.getvalue()

    def test_session_lost_after_import_click_is_not_retried(self) -> None:
        zip_path = write_import_zip(self.zip_dir / "import.zip", 2)
        lost = InvalidSessionIdException("invalid session id")
        outcome, drivers, import_clicks, output = self.run_browser_flow(
            self.config(), [None, lost]
        )
        self.assertIsInstance(outcome, ImportOutcomeUnknownError)
        self.assertEqual(drivers, 1)
        self.assertEqual(import_clicks, 1)
        self.assertFalse(zip_path.exists())
        self.assertTrue(
            (self.base_dir / "output" / "failed_zip_data" / "import.zip").exists()
        )
        self.assertEqual(self.statuses(), ["started", "unknown"])
        self.assertIn("check manually in WEKO", output)

    def test_download_timeout_after_import_is_outcome_unknown(self) -> None:
        write_import_zip(self.zip_dir / "import.zip", 2)
        outcome, drivers, _, _ = self.run_browser_flow(
            self.config(),
            [None, None],
            load_effects=[MagicMock(), TimeoutError("import timed out")],
        )
        self.assertIsInstance(outcome, ImportOutcomeUnknownError)
        self.assertEqual(drivers, 1)
        self.assertEqual(self.statuses(), ["started", "unknown"])

    def test_session_lost_before_import_click_is_retried(self) -> None:
        zip_path = write_import_zip(self.zip_dir / "import.zip", 2)
        lost = InvalidSessionIdException("invalid session id")
        outcome, drivers, import_clicks, output = self.run_browser_flow(
            self.config(),
            [None, None, None],
            load_effects=[lost, MagicMock(), MagicMock()],
        )
        self.assertEqual(len(outcome.imported), 1)
        self.assertEqual(drivers, 2)
        self.assertEqual(import_clicks, 1)
        self.assertIn("retrying after driver disconnect", output)
        self.assertFalse(zip_path.exists())
        self.assertEqual(self.statuses(), ["started", "succeeded"])
        record = read_ledger(self.ledger_path)[-1]
        self.assertEqual(record["zip_name"], "import.zip")
        self.assertEqual(
            record["result_path"], str(self.download_dir / "import_result.tsv")
        )

    def test_rerun_with_same_content_is_skipped_unless_allowed(self) -> None:
        zip_path = write_import_zip(self.zip_dir / "import.zip", 2)
        original = zip_path.read_bytes()
        outcome, _, _, _ = self.run_browser_flow(self.config(), [None, None])
        self.assertEqual(len(outcome.imported), 1)

        renamed = self.zip_dir / "renamed.zip"
        renamed.write_bytes(original)
        outcome, drivers, _, output = self.run_browser_flow(self.config(), [])
        self.assertEqual(outcome.imported, [])
        self.assertEqual([path for path, _ in outcome.skipped], [renamed])
        self.assertEqual(drivers, 0)
        self.assertTrue(renamed.exists())
        self.assertIn("'succeeded'", output)
        self.assertIn("Skipped 1 zip file(s)", output)

        outcome, drivers, _, _ = self.run_browser_flow(
            self.config(allow_reimport=True), [None, None]
        )
        self.assertEqual(len(outcome.imported), 1)
        self.assertEqual(drivers, 1)
        self.assertEqual(
            self.statuses(), ["started", "succeeded", "started", "succeeded"]
        )

    def test_started_only_entry_blocks_import(self) -> None:
        zip_path = write_import_zip(self.zip_dir / "import.zip", 2)
        ImportLedger(self.ledger_path).append(
            "import.zip", file_sha256(zip_path), "started"
        )
        outcome, drivers, _, output = self.run_browser_flow(self.config(), [])
        self.assertEqual(outcome.imported, [])
        self.assertEqual(len(outcome.skipped), 1)
        self.assertEqual(drivers, 0)
        self.assertTrue(zip_path.exists())
        self.assertIn("'started'", output)

    def test_main_reports_skipped_zips(self) -> None:
        zip_path = write_import_zip(self.zip_dir / "import.zip", 2)
        ImportLedger(self.ledger_path).append(
            "import.zip", file_sha256(zip_path), "unknown"
        )
        output = io.StringIO()
        argv = [
            "selenium_auto_register",
            "--base-dir",
            str(self.base_dir),
            "--weko-base-url",
            "https://weko.example",
        ]
        with (
            patch("sys.argv", argv),
            patch.object(selenium_auto_register, "create_driver") as create_driver,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(selenium_auto_register.main(), 0)
        create_driver.assert_not_called()
        self.assertIn("No zip files were imported; 1 zip file(s)", output.getvalue())
        self.assertNotIn("No zip files were found to import.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
