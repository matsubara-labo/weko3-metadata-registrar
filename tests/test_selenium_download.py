from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from selenium.common.exceptions import TimeoutException

from importers.selenium_auto_register import (
    DEFAULT_SELECTOR_CONFIG_PATH,
    RESULT_FILE_PREFIX,
    load_selector_config,
    wait_for_download,
)


class WaitForDownloadTests(unittest.TestCase):
    def test_returns_result_file_and_ignores_check_and_partial_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            download_dir = Path(directory)
            (download_dir / "existing.tsv").write_text("", encoding="utf-8")
            previous_files = {"existing.tsv"}
            (download_dir / "check_2026-09-27.tsv").write_text("", encoding="utf-8")
            (download_dir / "List_Download_2026-09-27.tsv.crdownload").write_text(
                "", encoding="utf-8"
            )
            (download_dir / "List_Download_2026-09-27.tsv").write_text(
                "", encoding="utf-8"
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = wait_for_download(download_dir, previous_files, 1_000)

        self.assertEqual(result.name, "List_Download_2026-09-27.tsv")

    def test_times_out_when_only_check_file_appears(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            download_dir = Path(directory)
            (download_dir / "check_2026-09-27.tsv").write_text("", encoding="utf-8")
            (download_dir / "List_Download_2026-09-27.tsv.crdownload").write_text(
                "", encoding="utf-8"
            )
            output = io.StringIO()

            with (
                patch("importers.selenium_auto_register.POLL_INTERVAL_SECONDS", 0.01),
                contextlib.redirect_stdout(output),
                self.assertRaises(TimeoutException) as raised,
            ):
                wait_for_download(download_dir, set(), 50)

        self.assertIn(RESULT_FILE_PREFIX, str(raised.exception))
        self.assertEqual(output.getvalue().count("check_2026-09-27.tsv"), 1)


class DownloadButtonSelectorTests(unittest.TestCase):
    def test_default_download_button_candidates_are_scoped_to_result(self) -> None:
        selectors = load_selector_config(DEFAULT_SELECTOR_CONFIG_PATH)

        candidates = selectors.download_button
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertNotIn("'Download'", candidate.value)
        scoped = [c for c in candidates if "result_container" in c.value]
        self.assertGreaterEqual(len(scoped), 2)
        self.assertIn("result_container", candidates[0].value)


if __name__ == "__main__":
    unittest.main()
