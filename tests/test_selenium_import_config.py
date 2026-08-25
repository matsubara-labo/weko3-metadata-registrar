from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from importers.selenium_auto_register import (
    DEFAULT_REGISTRATION_CONFIG_PATH,
    DEFAULT_SELECTOR_CONFIG_PATH,
    REPOSITORY_ROOT,
    WekoImportConfig,
    build_parser,
    resolve_selectors,
    resolve_weko_base_url,
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

    def test_base_url_resolution_uses_cli_then_environment_then_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            registration_config = self.write_registration_config(
                base_dir, "https://config.example"
            )

            cases = (
                ("https://cli.example/", "https://env.example", "https://cli.example"),
                (None, "https://env.example/", "https://env.example"),
                (None, None, "https://config.example"),
            )
            for cli_url, env_url, expected in cases:
                with self.subTest(cli_url=cli_url, env_url=env_url):
                    environment = {"WEKO_URL": env_url} if env_url else {}
                    with patch.dict(os.environ, environment, clear=True):
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


if __name__ == "__main__":
    unittest.main()
