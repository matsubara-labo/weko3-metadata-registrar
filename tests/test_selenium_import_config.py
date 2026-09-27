from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from importers import selenium_auto_register
from importers.selenium_auto_register import (
    DEFAULT_REGISTRATION_CONFIG_PATH,
    DEFAULT_SELECTOR_CONFIG_PATH,
    REPOSITORY_ROOT,
    WekoImportConfig,
    build_chrome_options,
    build_parser,
    resolve_selectors,
    resolve_weko_base_url,
    run_import,
)


class SeleniumImportConfigTests(unittest.TestCase):
    def write_registration_config(self, directory: Path, base_url: str) -> Path:
        config_path = directory / "metadata_registration.json"
        config_path.write_text(
            json.dumps(
                {
                    "weko_base_url": base_url,
                    "item_type_export": "ItemType.zip",
                    "indexes": {"S2ORC": "1"},
                    "default_index": "S2ORC",
                    "publish_date": "2025-05-27",
                    "default_languages": {},
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def test_parser_defaults_use_repository_configuration(self) -> None:
        args = build_parser().parse_args([])

        self.assertEqual(args.base_dir, REPOSITORY_ROOT)
        self.assertEqual(args.registration_config, DEFAULT_REGISTRATION_CONFIG_PATH)
        self.assertIsNone(args.weko_base_url)

    def test_default_directories_share_repository_output_root(self) -> None:
        config = WekoImportConfig(base_dir=REPOSITORY_ROOT)

        self.assertEqual(
            config.resolved_zip_dir(), REPOSITORY_ROOT / "output" / "zip_data"
        )
        self.assertEqual(
            config.resolved_download_dir(),
            REPOSITORY_ROOT / "output" / "import_results",
        )
        self.assertEqual(
            config.resolved_processed_zip_dir(),
            REPOSITORY_ROOT / "output" / "uploaded_zip_data",
        )

    def test_base_url_resolution_uses_cli_then_config_and_ignores_weko_url(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            registration_config = self.write_registration_config(
                base_dir, "https://config.example"
            )
            (base_dir / ".env").write_text(
                "WEKO_URL=https://dotenv.example\n", encoding="utf-8"
            )

            cases = (
                ("https://cli.example/", "https://cli.example"),
                (None, "https://config.example"),
            )
            for cli_url, expected in cases:
                with self.subTest(cli_url=cli_url):
                    with patch.dict(
                        os.environ, {"WEKO_URL": "https://env.example"}, clear=True
                    ):
                        config = WekoImportConfig(
                            base_dir=base_dir,
                            weko_base_url=cli_url,
                            registration_config_path=registration_config,
                        )
                        self.assertEqual(resolve_weko_base_url(config), expected)

    def test_resolved_base_url_builds_fixed_weko_paths(self) -> None:
        config = WekoImportConfig(
            base_dir=REPOSITORY_ROOT,
            weko_base_url="https://weko.example",
        )

        self.assertEqual(config.login_url, "https://weko.example/login/?next=%2F")
        self.assertEqual(config.import_url, "https://weko.example/admin/items/import/")

    def test_empty_cli_base_url_is_rejected(self) -> None:
        config = WekoImportConfig(weko_base_url="")

        with self.assertRaisesRegex(RuntimeError, "CLI"):
            resolve_weko_base_url(config)

    def test_default_selector_configuration_is_loadable(self) -> None:
        self.assertEqual(
            DEFAULT_SELECTOR_CONFIG_PATH,
            REPOSITORY_ROOT / "config" / "weko_ui_selectors.json",
        )
        selectors = resolve_selectors(WekoImportConfig(base_dir=REPOSITORY_ROOT))
        self.assertTrue(selectors.email_input)

    def assert_parser_rejects(self, argv: list[str]) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(argv)

    def test_parser_rejects_both_zip_handling_flags(self) -> None:
        self.assert_parser_rejects(
            ["--keep-zip-after-import", "--delete-zip-after-import"]
        )
        self.assertTrue(
            build_parser().parse_args(["--keep-zip-after-import"]).keep_zip_after_import
        )

    def test_parser_rejects_negative_limit(self) -> None:
        self.assert_parser_rejects(["--limit", "-1"])
        self.assert_parser_rejects(["--limit", "abc"])
        self.assertEqual(build_parser().parse_args(["--limit", "0"]).limit, 0)
        self.assertIsNone(build_parser().parse_args([]).limit)

    def test_run_import_rejects_both_zip_handling_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            zip_dir = Path(directory) / "zip_data"
            zip_dir.mkdir()
            zip_path = zip_dir / "import.zip"
            zip_path.write_bytes(b"zip")
            config = WekoImportConfig(
                base_dir=Path(directory),
                weko_base_url="https://weko.example",
                zip_dir=zip_dir,
                delete_zip_after_import=True,
                keep_zip_after_import=True,
            )
            with patch.object(selenium_auto_register, "create_driver") as create:
                with self.assertRaisesRegex(ValueError, "cannot both"):
                    run_import(config)
            create.assert_not_called()
            self.assertTrue(zip_path.exists())

    def test_certificate_errors_are_ignored_only_when_enabled(self) -> None:
        insecure_args = {"--ignore-certificate-errors", "--allow-insecure-localhost"}
        with tempfile.TemporaryDirectory() as directory:
            default_options = build_chrome_options(Path(directory), headless=False)
            enabled_options = build_chrome_options(
                Path(directory), headless=False, ignore_certificate_errors=True
            )
        self.assertFalse(insecure_args & set(default_options.arguments))
        self.assertTrue(insecure_args <= set(enabled_options.arguments))
        self.assertFalse(build_parser().parse_args([]).ignore_certificate_errors)
        self.assertTrue(
            build_parser()
            .parse_args(["--ignore-certificate-errors"])
            .ignore_certificate_errors
        )

    def run_main(self, base_dir: Path, *extra: str) -> str:
        output = io.StringIO()
        argv = [
            "selenium_auto_register",
            "--base-dir",
            str(base_dir),
            "--weko-base-url",
            "https://weko.example",
            *extra,
        ]
        with (
            patch("sys.argv", argv),
            patch.object(selenium_auto_register, "create_driver") as create_driver,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(selenium_auto_register.main(), 0)
        create_driver.assert_not_called()
        return output.getvalue()

    def test_main_reports_limit_zero_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            zip_dir = base_dir / "output" / "zip_data"
            zip_dir.mkdir(parents=True)
            self.assertIn("No zip files were found to import.", self.run_main(base_dir))
            (zip_dir / "import.zip").write_bytes(b"zip")
            output = self.run_main(base_dir, "--limit", "0")
            self.assertTrue((zip_dir / "import.zip").exists())
        self.assertIn("No zip files were imported because --limit 0 was given.", output)
        self.assertNotIn("No zip files were found to import.", output)


if __name__ == "__main__":
    unittest.main()
