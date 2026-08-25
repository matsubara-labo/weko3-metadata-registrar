from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from generation.item_type import ItemTypeExportError, load_item_type_export

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPORT = REPOSITORY_ROOT / "sample" / "config" / "ItemType_export_sample.zip"


def write_minimal_export(export_path: Path, item_type: dict) -> None:
    with zipfile.ZipFile(export_path, "w") as archive:
        archive.writestr("ItemType.json", json.dumps(item_type))
        archive.writestr(
            "ItemTypeName.json", json.dumps({"id": item_type["id"], "name": "Test"})
        )


class LoadItemTypeExportTests(unittest.TestCase):
    def test_sample_export_provides_ordered_field_contract(self) -> None:
        item_type = load_item_type_export(SAMPLE_EXPORT)

        self.assertEqual(item_type.id, 40001)
        self.assertEqual(item_type.name, "ResearchArtifact")
        self.assertEqual(len(item_type.fixed_fields), 1)
        pubdate = item_type.fixed_fields[0]
        self.assertEqual(pubdate.name, "PubDate")
        self.assertTrue(pubdate.required)
        self.assertTrue(pubdate.hidden)
        self.assertFalse(pubdate.multiple)
        self.assertEqual(
            [field.name for field in item_type.fields[:5]],
            ["corpusid", "URI", "Title", "Title_g", "Creator"],
        )

        fields = {field.name: field for field in item_type.fields}
        self.assertTrue(fields["corpusid"].hidden)
        self.assertTrue(fields["Title"].required)
        self.assertTrue(fields["Title"].multiple)
        self.assertEqual(
            fields["Title"].binding_templates,
            (
                ".metadata.item_30001_title0[0].subitem_title",
                ".metadata.item_30001_title0[0].subitem_title_language",
            ),
        )
        self.assertTrue(fields["Creator"].dynamically_repeatable)
        self.assertEqual(
            fields["Creator"].binding_templates,
            (".metadata.item_1748316642067[{index}].interim",),
        )
        self.assertTrue(fields["PublicationYear_g"].date_like)

    def test_export_missing_required_member_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            export_path = Path(temporary_directory) / "incomplete.zip"
            with zipfile.ZipFile(export_path, "w") as archive:
                archive.writestr("ItemType.json", json.dumps({"id": 1}))

            with self.assertRaisesRegex(
                ItemTypeExportError, "ItemTypeName.json.*missing"
            ):
                load_item_type_export(export_path)

    def test_duplicate_source_field_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            export_path = Path(temporary_directory) / "duplicate.zip"
            properties = {
                key: {"type": "string", "title": "Duplicate"}
                for key in ("item_a", "item_b")
            }
            write_minimal_export(
                export_path,
                {
                    "id": 1,
                    "schema": {"properties": properties, "required": []},
                    "render": {
                        "table_row": list(properties),
                        "meta_list": {key: {"option": {}} for key in properties},
                        "meta_fix": {},
                    },
                },
            )

            with self.assertRaisesRegex(ItemTypeExportError, "source name"):
                load_item_type_export(export_path)

    def test_invalid_required_definition_raises_export_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            export_path = Path(temporary_directory) / "invalid-required.zip"
            write_minimal_export(
                export_path,
                {
                    "id": 1,
                    "schema": {"properties": {}, "required": None},
                    "render": {"table_row": [], "meta_list": {}, "meta_fix": {}},
                },
            )

            with self.assertRaisesRegex(ItemTypeExportError, "schema.required"):
                load_item_type_export(export_path)


if __name__ == "__main__":
    unittest.main()
