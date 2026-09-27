from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from generation.metadata_pipeline import (
    WEKO_TSV_FIELD_SIZE_LIMIT,
    MetadataGenerationConfig,
    MetadataInputError,
    MetadataSchema,
    generate_metadata_artifacts,
    load_metadata_schema,
    load_rows,
    load_rows_with_errors,
    normalize_row,
    write_tsv,
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
        self.assertEqual(
            schema.column_bindings["Title"],
            [
                ".metadata.item_30001_title0[{index}].subitem_title",
                ".metadata.item_30001_title0[{index}].subitem_title_language",
            ],
        )
        self.assertEqual(
            schema.display_columns["Title"],
            ["Title[{index}].タイトル", "Title[{index}].言語"],
        )
        self.assertIn("Title", schema.repeatable_fields)
        self.assertIn("Creator", schema.repeatable_fields)
        self.assertNotIn("Title_g", schema.repeatable_fields)
        self.assertEqual(
            schema.column_bindings["Title_g"],
            [
                ".metadata.item_30001_alternative_title1.subitem_alternative_title",
                ".metadata.item_30001_alternative_title1"
                ".subitem_alternative_title_language",
            ],
        )
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
                "RequiredField": [".metadata.item_required[{index}].interim"]
            },
            default_languages={},
            field_attributes={"RequiredField": "Required, Allow Multiple"},
            display_columns={"RequiredField": ["RequiredField[{index}].None"]},
            repeatable_fields=frozenset({"RequiredField"}),
        )

        with self.assertRaisesRegex(MetadataInputError, "RequiredField.*empty"):
            normalize_row({}, schema)

    def _schema(
        self, field_name: str, attribute: str, *, repeatable: bool
    ) -> MetadataSchema:
        binding = ".metadata.item_x[{index}].interim" if repeatable else ".x"
        display = f"{field_name}[{{index}}].None" if repeatable else field_name
        return MetadataSchema(
            item_type_name="Test(1)",
            item_schema_url="https://weko.example.org/items/jsonschema/1",
            base_metadata_bindings=[],
            template_column_values={},
            template_column_attributes={},
            column_bindings={field_name: [binding]},
            default_languages={},
            field_attributes={field_name: attribute},
            display_columns={field_name: [display]},
            repeatable_fields=frozenset({field_name} if repeatable else ()),
        )

    def test_empty_list_elements_do_not_satisfy_required_field(self) -> None:
        for repeatable in (True, False):
            schema = self._schema(
                "Field", "Required, Allow Multiple", repeatable=repeatable
            )
            for text in ("[None]", "['']", "[' ', None]", "[]"):
                with self.subTest(repeatable=repeatable, text=text):
                    with self.assertRaisesRegex(MetadataInputError, "'Field' is empty"):
                        normalize_row({"Field": text}, schema)

    def test_empty_list_elements_are_dropped(self) -> None:
        schema = self._schema("Field", "Allow Multiple", repeatable=True)

        row = normalize_row({"Field": "['a', '', ' ', None, 'b']"}, schema)

        self.assertEqual(row["Field"], ["a", "b"])

    def test_scalar_field_uses_single_non_empty_element(self) -> None:
        schema = self._schema("Field", "Required", repeatable=False)

        self.assertEqual(
            normalize_row({"Field": "['', ' ', 'x']"}, schema), {"Field": "x"}
        )
        with self.assertRaisesRegex(
            MetadataInputError, r"^'Field' accepts a single value but got 2$"
        ):
            normalize_row({"Field": "['', 'x', 'y']"}, schema)
        self.assertEqual(
            normalize_row({"Field": "  plain  "}, schema), {"Field": "plain"}
        )

    def test_all_row_errors_are_listed(self) -> None:
        with self.assertRaises(MetadataInputError) as context:
            self._load_text("input.csv", "Title\nok\n[1]\nfine\n[2]\n")

        lines = str(context.exception).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"input\.csv:3: 'Title': .*int")
        self.assertRegex(lines[1], r"input\.csv:5: 'Title': .*int")

    def test_row_error_list_is_capped(self) -> None:
        with self.assertRaises(MetadataInputError) as context:
            self._load_text("input.csv", "Title\n" + "[1]\n" * 53)

        lines = str(context.exception).splitlines()
        self.assertEqual(len(lines), 51)
        self.assertIn("input.csv:51:", lines[49])
        self.assertEqual(lines[50], "... and 3 more")

    def test_load_rows_with_errors_keeps_valid_rows_and_raw_cells(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "input.csv"
            input_path.write_text("id,Title\n1,ok\n2,[1]\n3\n", encoding="utf-8")
            rows, errors = load_rows_with_errors(input_path, self._title_schema())

        self.assertEqual([row["Title"] for row in rows], [["ok"], []])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].row_number, 3)
        self.assertEqual(errors[0].cells, {"id": "2", "Title": "[1]"})

    def test_non_string_list_element_error_names_column(self) -> None:
        schema = MetadataSchema(
            item_type_name="Test(1)",
            item_schema_url="https://weko.example.org/items/jsonschema/1",
            base_metadata_bindings=[],
            template_column_values={},
            template_column_attributes={},
            column_bindings={"Version": [".metadata.item_version[{index}].interim"]},
            default_languages={},
            field_attributes={"Version": "Allow Multiple"},
            display_columns={"Version": ["Version[{index}].None"]},
            repeatable_fields=frozenset({"Version"}),
        )

        with self.assertRaisesRegex(MetadataInputError, "'Version'.*float"):
            normalize_row({"Version": "[1.50]"}, schema)

    def _title_schema(self) -> MetadataSchema:
        return MetadataSchema(
            item_type_name="Test(1)",
            item_schema_url="https://weko.example.org/items/jsonschema/1",
            base_metadata_bindings=[],
            template_column_values={},
            template_column_attributes={},
            column_bindings={"Title": [".metadata.item_title[{index}].interim"]},
            default_languages={},
            field_attributes={"Title": "Allow Multiple"},
            display_columns={"Title": ["Title[{index}].None"]},
            repeatable_fields=frozenset({"Title"}),
        )

    def _load_text(
        self, file_name: str, text: str, delimiter: str | None = None
    ) -> list[dict[str, object]]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / file_name
            input_path.write_text(text, encoding="utf-8")
            return load_rows(input_path, self._title_schema(), delimiter=delimiter)

    def test_txt_with_tabs_is_detected_as_tab(self) -> None:
        rows = self._load_text("input.txt", "id\tTitle\n1\tfirst\n2\tsecond\n")

        self.assertEqual([row["Title"] for row in rows], [["first"], ["second"]])

    def test_txt_with_commas_is_detected_as_comma(self) -> None:
        rows = self._load_text("input.txt", "id,Title\n1,first\n2,second\n")

        self.assertEqual([row["Title"] for row in rows], [["first"], ["second"]])

    def test_txt_tsv_with_list_cells_is_detected_as_tab(self) -> None:
        rows = self._load_text(
            "input.txt",
            "id\tTitle\tDescription\n"
            "1\t['Alice', 'Bob']\tA, B, and C\n"
            "2\t['Carol', 'Dave']\tx, y\n",
        )

        self.assertEqual(
            [row["Title"] for row in rows], [["Alice", "Bob"], ["Carol", "Dave"]]
        )

    def test_txt_csv_with_list_cells_is_detected_as_comma(self) -> None:
        rows = self._load_text(
            "input.txt",
            "id,Title\n1,\"['Alice', 'Bob']\"\n2,\"['Carol']\"\n",
        )

        self.assertEqual([row["Title"] for row in rows], [["Alice", "Bob"], ["Carol"]])

    def test_csv_extension_with_tabs_is_rejected_as_wrong_delimiter(self) -> None:
        with self.assertRaisesRegex(
            MetadataInputError,
            r"input\.csv:1: no column matches the ItemType fields; .*"
            r"\(used 'comma'\); specify --delimiter comma or --delimiter tab$",
        ):
            self._load_text("input.csv", "id\tTitle\n1\tfirst\n")

    def test_explicit_tab_delimiter_overrides_csv_extension(self) -> None:
        rows = self._load_text("input.csv", "id\tTitle\n1\tfirst\n", delimiter="\t")

        self.assertEqual(rows[0]["Title"], ["first"])

    def test_duplicate_column_name_is_rejected_with_positions(self) -> None:
        with self.assertRaisesRegex(
            MetadataInputError,
            r":1: duplicate column name\(s\): 'Title' \(columns 2, 5\)$",
        ):
            self._load_text("input.csv", "id,Title,a,b,Title\n1,first,x,y,second\n")

    def test_all_duplicate_column_names_are_listed_in_order(self) -> None:
        with self.assertRaisesRegex(
            MetadataInputError,
            r"'Title' \(columns 1, 3\), 'Creator' \(columns 2, 4, 5\)$",
        ):
            self._load_text(
                "input.tsv",
                "Title\tCreator\tTitle\tCreator\tCreator\na\tb\tc\td\te\n",
            )

    def test_repeated_empty_column_names_are_rejected(self) -> None:
        with self.assertRaisesRegex(MetadataInputError, r"'' \(columns 3, 4\)$"):
            self._load_text("input.csv", "Title,x,,\na,b,c,d\n")

    def test_unique_header_loads_rows(self) -> None:
        rows = self._load_text("input.csv", "id,Title\n1,first\n")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Title"], ["first"])

    def test_empty_file_returns_no_rows(self) -> None:
        self.assertEqual(self._load_text("input.csv", ""), [])

    def test_cell_over_weko_limit_is_rejected_with_column(self) -> None:
        previous_limit = csv.field_size_limit()
        with self.assertRaisesRegex(
            MetadataInputError,
            r"input\.tsv:2: 'Title' value is 200000 characters; "
            r"WEKO cannot read TSV cells longer than 131072 characters$",
        ):
            self._load_text("input.tsv", "Title\n" + "a" * 200_000 + "\n")
        self.assertEqual(csv.field_size_limit(), previous_limit)

    def test_cell_at_weko_limit_is_loaded_and_written(self) -> None:
        previous_limit = csv.field_size_limit()
        value = "a" * WEKO_TSV_FIELD_SIZE_LIMIT
        rows = self._load_text("input.tsv", f"Title\n{value}\n")
        self.assertEqual(csv.field_size_limit(), previous_limit)
        self.assertEqual(rows[0]["Title"], [value])

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "output.tsv"
            write_tsv(rows, output_path, self._title_schema())
            with output_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
                written = list(csv.reader(file_obj, delimiter="\t"))
        self.assertEqual(written[5], [value])

    def test_csv_error_is_reported_with_line_number(self) -> None:
        previous_limit = csv.field_size_limit()
        with (
            mock.patch("generation.metadata_pipeline.INPUT_FIELD_SIZE_LIMIT", 10),
            self.assertRaisesRegex(
                MetadataInputError,
                r"input\.csv: line 3: malformed input: field larger than",
            ),
        ):
            self._load_text("input.csv", "Title\nshort\n" + "a" * 20 + "\n")
        self.assertEqual(csv.field_size_limit(), previous_limit)

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
