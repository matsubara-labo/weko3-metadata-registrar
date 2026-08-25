from __future__ import annotations

import unittest
from pathlib import Path

from generation.registration_config import load_registration_settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RegistrationConfigTests(unittest.TestCase):
    def test_named_index_resolves_its_configured_id(self) -> None:
        settings = load_registration_settings(
            REPOSITORY_ROOT / "config" / "metadata_registration.json"
        )

        self.assertEqual(settings.resolve_index("PWCD"), ("1776751280302", "PWCD"))
        self.assertEqual(
            settings.item_type_export_path.resolve(),
            (
                REPOSITORY_ROOT / "sample" / "config" / "ItemType_export_sample.zip"
            ).resolve(),
        )


if __name__ == "__main__":
    unittest.main()
