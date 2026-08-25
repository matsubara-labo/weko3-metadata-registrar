from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from generation.metadata_pipeline import (
    MetadataGenerationConfig,
    MetadataInputError,
    MetadataSchema,
    generate_metadata_artifacts,
    load_metadata_schema,
    normalize_row,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPORT = REPOSITORY_ROOT / "sample" / "config" / "ItemType_export_sample.zip"


class MetadataGenerationFromExportTests(unittest.TestCase):
    def test_loaded_schema_preserves_original_registration_types(self) -> None:
        schema = load_metadata_schema(
            MetadataGenerationConfig(
                input_path=Path("unused.csv"),
                output_dir=Path("unused-output"),
                registration_config_path=(
                    REPOSITORY_ROOT / "config" / "metadata_registration.json"
                ),
            )
        )

        self.assertIsInstance(schema.item_type_name, str)
        self.assertIsInstance(schema.item_schema_url, str)
        self.assertIsInstance(schema.base_metadata_bindings, list)
        self.assertIsInstance(schema.template_column_values, dict)
        self.assertIsInstance(schema.template_column_attributes, dict)
        self.assertIsInstance(schema.column_bindings, dict)
        self.assertIsInstance(schema.default_languages, dict)
        self.assertIsInstance(schema.field_attributes, dict)
        self.assertIsInstance(schema.display_columns, dict)
        self.assertIsInstance(schema.column_bindings["Title"], list)
        self.assertIsInstance(schema.column_bindings["Creator"], str)
        self.assertIsInstance(schema.display_columns["Title"], list)
        self.assertIsInstance(schema.display_columns["Creator"], str)
        self.assertTrue(
            all(isinstance(value, str) for value in schema.base_metadata_bindings)
        )
        self.assertTrue(
            all(
                isinstance(value, str)
                for value in schema.template_column_values.values()
            )
        )
        self.assertTrue(
            all(
                isinstance(value, str)
                for value in schema.template_column_attributes.values()
            )
        )
        self.assertTrue(
            all(isinstance(value, str) for value in schema.field_attributes.values())
        )
        self.assertEqual(
            schema.default_languages,
            {"Title": "en", "Title_g": "en"},
        )

    def test_empty_required_repeatable_field_is_rejected(self) -> None:
        schema = MetadataSchema(
            item_type_name="Test(1)",
            item_schema_url="https://weko.example.org/items/jsonschema/1",
            base_metadata_bindings=[],
            template_column_values={},
            template_column_attributes={},
            column_bindings={
                "RequiredField": ".metadata.item_required[{index}].interim"
            },
            default_languages={},
            field_attributes={"RequiredField": "Required, Allow Multiple"},
            display_columns={"RequiredField": "RequiredField[{index}].None"},
        )

        with self.assertRaisesRegex(MetadataInputError, "RequiredField.*empty"):
            normalize_row({}, schema)

    def test_generation_uses_config_and_exported_item_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source.csv"
            with source_path.open("w", encoding="utf-8", newline="") as file_obj:
                writer = csv.DictWriter(
                    file_obj,
                    fieldnames=[
                        "corpusid",
                        "Title",
                        "Title_g",
                        "Creator",
                        "PublicationYear_g",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "corpusid": "123",
                        "Title": "Main title",
                        "Title_g": "Alternative title",
                        "Creator": "['Alice', 'Bob']",
                        "PublicationYear_g": "2026-08-23T12:34:56",
                    }
                )

            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "weko_base_url": "https://weko.example.org",
                        "item_type_export": str(SAMPLE_EXPORT),
                        "indexes": {"Example": "999"},
                        "default_index": "Example",
                        "publish_date": "2026-08-23",
                        "default_languages": {
                            "Title": "en",
                            "Title_g": "en",
                        },
                    }
                ),
                encoding="utf-8",
            )

            artifacts = generate_metadata_artifacts(
                MetadataGenerationConfig(
                    input_path=source_path,
                    output_dir=root / "output",
                    registration_config_path=settings_path,
                )
            )

            output_path = artifacts[0].tsv_path
            self.assertIsNotNone(output_path)
            with output_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
                rows = list(csv.reader(file_obj, delimiter="\t"))

        self.assertEqual(
            rows[0],
            [
                "#ItemType",
                "ResearchArtifact(40001)",
                "https://weko.example.org/items/jsonschema/40001",
            ],
        )
        self.assertEqual(
            rows[2][:12],
            [
                "#ID",
                "URI",
                ".IndexID[0]",
                ".POS_INDEX[0]",
                ".PUBLISH_STATUS",
                ".FEEDBACK_MAIL[0]",
                ".RESEAECHMAP_LINKAGE",
                ".CNRI",
                ".DOI_RA",
                ".DOI",
                "Keep/Upgrade Version",
                "PubDate",
            ],
        )
        self.assertEqual(
            rows[4][:12],
            [
                "#",
                "",
                "Allow Multiple",
                "Allow Multiple",
                "Required",
                "Allow Multiple",
                "",
                "",
                "",
                "",
                "Required",
                "Hide, Required",
            ],
        )
        self.assertEqual(
            rows[5][:12],
            [
                "",
                "",
                "999",
                "Example",
                "public",
                "",
                "",
                "",
                "",
                "",
                "keep",
                "2026-08-23",
            ],
        )
        display_to_index = {name: index for index, name in enumerate(rows[2])}
        self.assertEqual(rows[5][display_to_index[".IndexID[0]"]], "999")
        self.assertEqual(rows[5][display_to_index[".POS_INDEX[0]"]], "Example")
        self.assertEqual(
            rows[1][display_to_index["corpusid"]], ".metadata.item_1748316538548"
        )
        self.assertEqual(rows[5][display_to_index["corpusid"]], "123")
        self.assertEqual(
            rows[1][display_to_index["Title_g.その他のタイトル"]],
            ".metadata.item_30001_alternative_title1.subitem_alternative_title",
        )
        self.assertEqual(rows[5][display_to_index["Title_g.言語"]], "en")
        self.assertEqual(rows[5][display_to_index["Creator[0].None"]], "Alice")
        self.assertEqual(rows[5][display_to_index["Creator[1].None"]], "Bob")
        self.assertEqual(rows[5][display_to_index["PublicationYear_g"]], "2026-08-23")


if __name__ == "__main__":
    unittest.main()
