from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from generation.registration_config import (
    RegistrationConfigError,
    load_registration_settings,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RegistrationConfigTests(unittest.TestCase):
    def test_named_index_resolves_its_configured_id(self) -> None:
        settings = load_registration_settings(
            REPOSITORY_ROOT / "sample" / "AXIES2025" / "metadata_registration.json"
        )

        self.assertEqual(settings.resolve_index("PWCD"), ("1776751280302", "PWCD"))
        self.assertEqual(
            settings.item_type_export_path.resolve(),
            (
                REPOSITORY_ROOT
                / "sample"
                / "AXIES2025"
                / "config"
                / "ItemType_export_sample.zip"
            ).resolve(),
        )

    def load_with(self, **extra: object):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "metadata_registration.json"
            config_path.write_text(
                json.dumps(
                    {
                        "weko_base_url": "https://weko.example",
                        "item_type_export": "ItemType.zip",
                        "indexes": {"Example": "1"},
                        "default_index": "Example",
                        "publish_date": "2025-05-27",
                        "default_languages": {},
                        **extra,
                    }
                ),
                encoding="utf-8",
            )
            return load_registration_settings(config_path)

    def test_publish_status_defaults_to_public(self) -> None:
        self.assertEqual(self.load_with().publish_status, "public")

    def test_publish_status_accepts_public_and_private(self) -> None:
        for status in ("public", "private"):
            with self.subTest(status=status):
                self.assertEqual(
                    self.load_with(publish_status=status).publish_status, status
                )

    def test_invalid_publish_status_is_rejected(self) -> None:
        for status in ("Private", "draft", "", 1):
            with self.subTest(status=status):
                with self.assertRaisesRegex(RegistrationConfigError, "publish_status"):
                    self.load_with(publish_status=status)

    def test_date_timezone_defaults_to_japan(self) -> None:
        self.assertEqual(self.load_with().date_timezone, ZoneInfo("Asia/Tokyo"))

    def test_date_timezone_accepts_iana_names(self) -> None:
        self.assertEqual(
            self.load_with(date_timezone="UTC").date_timezone, ZoneInfo("UTC")
        )

    def test_invalid_date_timezone_is_rejected(self) -> None:
        for value in ("JST", "Asia/Nowhere", "", 9):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RegistrationConfigError, "date_timezone"):
                    self.load_with(date_timezone=value)


if __name__ == "__main__":
    unittest.main()
