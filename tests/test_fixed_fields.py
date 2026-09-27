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
    MetadataSchema,
    generate_metadata_artifacts,
)

CONTROL_COLUMN_COUNT = 11


def _object_field(name: str, value_key: str) -> dict:
    return {
        "type": "object",
        "title": name,
        "properties": {
            value_key: {"title": "Value"},
            f"{value_key}_language": {"title": "Language"},
        },
    }


def _write_export(export_path: Path, *, fixed_required: bool = False) -> None:
    fixed = {
        "pubdate": {"type": "string", "title": "PubDate", "format": "datetime"},
        "item_fixed_object": _object_field("FixedObject", "fixed_value"),
        "item_fixed_array": {
            "type": "array",
            "title": "FixedArray",
            "items": _object_field("FixedArray", "fixed_item"),
        },
    }
    regular = {
        "item_title": {"type": "string", "title": "Title"},
        "item_note": _object_field("Note", "note"),
        "item_tags": {
            "type": "array",
            "title": "Tags",
            "items": _object_field("Tags", "tag"),
        },
    }
    meta_fix = {key: {"option": {}} for key in fixed}
    meta_fix["pubdate"] = {"option": {"required": True, "hidden": True}}
    meta_fix["item_fixed_object"] = {"option": {"required": fixed_required}}
    with zipfile.ZipFile(export_path, "w") as archive:
        archive.writestr(
            "ItemType.json",
            json.dumps(
                {
                    "id": 7,
                    "schema": {
                        "properties": {**fixed, **regular},
                        "required": [],
                    },
                    "render": {
                        "table_row": list(regular),
                        "meta_list": {key: {"option": {}} for key in regular},
                        "meta_fix": meta_fix,
                    },
                }
            ),
        )
        archive.writestr("ItemTypeName.json", json.dumps({"id": 7, "name": "T"}))


class FixedFieldColumnTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)

    def _generate(
        self,
        *,
        fixed_required: bool = False,
        configured_publish_status: str | None = None,
        publish_status: str | None = None,
    ) -> list[list[str]]:
        export_path = self.root / "export.zip"
        _write_export(export_path, fixed_required=fixed_required)
        settings = {
            "weko_base_url": "https://weko.example.org",
            "item_type_export": str(export_path),
            "indexes": {"Example": "999"},
            "default_index": "Example",
            "publish_date": "2026-08-23",
            "default_languages": {"Note": "en", "Tags": "ja"},
        }
        if configured_publish_status is not None:
            settings["publish_status"] = configured_publish_status
        settings_path = self.root / "settings.json"
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        source_path = self.root / "source.csv"
        with source_path.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(["Title", "Note", "Tags"])
            writer.writerow(["First", "A note", "['x', 'y']"])
            writer.writerow(["Second", "", "['z']"])

        artifacts = generate_metadata_artifacts(
            MetadataGenerationConfig(
                input_path=source_path,
                output_dir=Path(tempfile.mkdtemp(dir=self.root)),
                registration_config_path=settings_path,
                publish_status=publish_status,
            )
        )
        with artifacts[0].tsv_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file_obj:
            return list(csv.reader(file_obj, delimiter="\t"))

    def test_multi_binding_fixed_fields_keep_columns_aligned(self) -> None:
        rows = self._generate()

        lengths = {len(row) for row in rows[1:]}
        self.assertEqual(len(lengths), 1, [len(row) for row in rows])
        fixed = slice(CONTROL_COLUMN_COUNT, CONTROL_COLUMN_COUNT + 5)
        self.assertEqual(
            rows[1][fixed],
            [
                ".metadata.pubdate",
                ".metadata.item_fixed_object.fixed_value",
                ".metadata.item_fixed_object.fixed_value_language",
                ".metadata.item_fixed_array[0].fixed_item",
                ".metadata.item_fixed_array[0].fixed_item_language",
            ],
        )
        self.assertEqual(
            rows[2][fixed],
            [
                "PubDate",
                "FixedObject.Value",
                "FixedObject.Language",
                "FixedArray[0].Value",
                "FixedArray[0].Language",
            ],
        )
        self.assertEqual(
            rows[4][fixed],
            ["Hide, Required", "", "", "Allow Multiple", "Allow Multiple"],
        )
        for row in rows[5:]:
            self.assertEqual(row[fixed], ["2026-08-23", "", "", "", ""])
        self.assertFalse(any("{index}" in cell for cell in rows[1] + rows[2]))

        column = {binding: index for index, binding in enumerate(rows[1])}
        values = [
            {binding: row[index] for binding, index in column.items()}
            for row in rows[5:]
        ]
        self.assertEqual(values[0][".metadata.item_title"], "First")
        self.assertEqual(values[0][".metadata.item_note.note"], "A note")
        self.assertEqual(values[0][".metadata.item_note.note_language"], "en")
        self.assertEqual(values[0][".metadata.item_tags[1].tag"], "y")
        self.assertEqual(values[1][".metadata.item_title"], "Second")
        self.assertEqual(values[1][".metadata.item_note.note"], "")
        self.assertEqual(values[1][".metadata.item_tags[0].tag"], "z")
        self.assertEqual(values[1][".metadata.item_tags[1].tag"], "")

    def test_publish_status_stays_aligned_with_control_and_fixed_columns(
        self,
    ) -> None:
        cases = (
            (None, None, "public"),
            ("private", None, "private"),
            ("private", "public", "public"),
        )
        for configured, override, expected in cases:
            with self.subTest(configured=configured, override=override):
                rows = self._generate(
                    configured_publish_status=configured, publish_status=override
                )
                base = slice(0, CONTROL_COLUMN_COUNT + 5)
                self.assertEqual(
                    rows[1][base],
                    [
                        "#.id",
                        ".uri",
                        ".metadata.path[0]",
                        ".pos_index[0]",
                        ".publish_status",
                        ".feedback_mail[0]",
                        ".researchmap_linkage",
                        ".cnri",
                        ".doi_ra",
                        ".doi",
                        ".edit_mode",
                        ".metadata.pubdate",
                        ".metadata.item_fixed_object.fixed_value",
                        ".metadata.item_fixed_object.fixed_value_language",
                        ".metadata.item_fixed_array[0].fixed_item",
                        ".metadata.item_fixed_array[0].fixed_item_language",
                    ],
                )
                self.assertEqual(rows[2][4], ".PUBLISH_STATUS")
                self.assertEqual(rows[4][4], "Required")
                for row in rows[5:]:
                    self.assertEqual(
                        row[base],
                        [
                            "",
                            "",
                            "999",
                            "Example",
                            expected,
                            "",
                            "",
                            "",
                            "",
                            "",
                            "keep",
                            "2026-08-23",
                            "",
                            "",
                            "",
                            "",
                        ],
                    )
                self.assertEqual(
                    rows[5][rows[1].index(".metadata.item_title")], "First"
                )

    def test_required_fixed_field_without_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(MetadataInputError, "FixedObject"):
            self._generate(fixed_required=True)

    def test_mismatched_base_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mismatched lengths"):
            MetadataSchema(
                item_type_name="Test(1)",
                item_schema_url="https://weko.example.org/items/jsonschema/1",
                base_metadata_bindings=[".a", ".b"],
                base_display_columns=["A"],
                base_column_values=["", ""],
                base_column_attributes=["", ""],
                column_bindings={},
                default_languages={},
                field_attributes={},
                display_columns={},
                repeatable_fields=frozenset(),
            )


if __name__ == "__main__":
    unittest.main()
