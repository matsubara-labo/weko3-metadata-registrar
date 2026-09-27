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
    generate_metadata_artifacts,
    load_metadata_schema,
)


def _object_field(name: str, value_key: str) -> dict:
    return {
        "type": "object",
        "title": name,
        "properties": {
            value_key: {"title": name},
            f"{value_key}_language": {"title": "Language"},
        },
    }


def _array_field(name: str, value_key: str) -> dict:
    return {"type": "array", "title": name, "items": _object_field(name, value_key)}


def _write_export(
    export_path: Path,
    properties: dict[str, dict],
    *,
    hidden: frozenset[str] = frozenset(),
    title_keys: tuple[str, ...] = (),
) -> None:
    mapping = {
        key: {
            "jpcoar_mapping": {
                "title": {
                    "@value": "subitem_title",
                    "@attributes": {"xml:lang": "subitem_title_language"},
                }
            }
        }
        for key in title_keys
    }
    with zipfile.ZipFile(export_path, "w") as archive:
        archive.writestr(
            "ItemType.json",
            json.dumps(
                {
                    "id": 1,
                    "schema": {"properties": properties, "required": []},
                    "render": {
                        "table_row": list(properties),
                        "meta_list": {
                            key: {"option": {"hidden": key in hidden}}
                            for key in properties
                        },
                        "meta_fix": {},
                    },
                }
            ),
        )
        archive.writestr("ItemTypeName.json", json.dumps({"id": 1, "name": "T"}))
        archive.writestr("ItemTypeMapping.json", json.dumps({"mapping": mapping}))


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPORT = REPOSITORY_ROOT / "sample" / "config" / "ItemType_export_sample.zip"
TITLE_LANGUAGE = ".metadata.item_30001_title0[0].subitem_title_language"
ALTERNATIVE_LANGUAGE_SUFFIX = ".subitem_alternative_title_language"


class _LanguageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.output_dir = self.root / "output"
        self.source_path = self.root / "source.csv"

    def _settings(self, default_languages: dict[str, str], export: Path) -> Path:
        settings_path = self.root / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "weko_base_url": "https://weko.example.org",
                    "item_type_export": str(export),
                    "indexes": {"Example": "999"},
                    "default_index": "Example",
                    "publish_date": "2026-08-23",
                    "default_languages": default_languages,
                }
            ),
            encoding="utf-8",
        )
        return settings_path

    def _write_source(self, fieldnames: list[str], rows: list[list[str]]) -> None:
        with self.source_path.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(fieldnames)
            writer.writerows(rows)

    def _generate(
        self,
        default_languages: dict[str, str],
        warnings: list[str] | None = None,
        **overrides,
    ):
        config = MetadataGenerationConfig(
            input_path=self.source_path,
            output_dir=self.output_dir,
            registration_config_path=self._settings(default_languages, SAMPLE_EXPORT),
            **overrides,
        )
        on_warning = warnings.append if warnings is not None else None
        return generate_metadata_artifacts(config, on_warning=on_warning)


class RowLanguageTests(_LanguageTestCase):
    def _language_cells(self, artifact) -> list[tuple[str, str]]:
        with artifact.tsv_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            rows = list(csv.reader(file_obj, delimiter="\t"))
        bindings = rows[1]
        title = bindings.index(TITLE_LANGUAGE)
        alternative = next(
            index
            for index, binding in enumerate(bindings)
            if binding.endswith(ALTERNATIVE_LANGUAGE_SUFFIX)
        )
        return [(row[title], row[alternative]) for row in rows[5:]]

    def test_row_language_overrides_default(self) -> None:
        self._write_source(
            ["Title", "Title_lang", "Title_g", "Title_g_lang"],
            [
                ["日本語", "ja", "別名", "ja"],
                ["English", "en", "Alias", ""],
                ["Default", "", "", "ja"],
            ],
        )

        artifacts = self._generate({"Title": "en", "Title_g": "en"})

        self.assertEqual(
            self._language_cells(artifacts[0]),
            [("ja", "ja"), ("en", "en"), ("en", "")],
        )

    def test_list_form_language_cell_drops_empty_elements(self) -> None:
        self._write_source(
            ["Title", "Title_lang"],
            [["['日本語']", "['', 'ja', ' ']"], ["English", "[' en ']"]],
        )

        artifacts = self._generate({"Title": "fr"})

        self.assertEqual(
            [title for title, _ in self._language_cells(artifacts[0])], ["ja", "en"]
        )

    def test_title_without_default_or_column_stops_before_writing(self) -> None:
        self._write_source(["Title"], [["First"]])

        with self.assertRaisesRegex(
            MetadataInputError,
            r"source\.csv:1: no title field \('Title'\) has a language; WEKO "
            r"would reject every record \('Title is required item\.'\); set "
            r"default_languages or add a '<field>_lang' column for one of them$",
        ):
            self._generate({})
        self.assertFalse(self.output_dir.exists())

    def test_title_with_empty_row_language_and_no_default_is_row_error(self) -> None:
        self._write_source(["Title", "Title_lang"], [["First", "ja"], ["Second", " "]])

        with self.assertRaisesRegex(
            MetadataInputError,
            r"source\.csv:3: no title field \('Title'\) has both a value and "
            r"a language",
        ):
            self._generate({})

        artifacts = self._generate({}, skip_invalid_rows=True)

        self.assertEqual(artifacts[0].row_count, 1)
        report = (self.output_dir / "invalid_rows.tsv").read_text(encoding="utf-8-sig")
        self.assertIn("no title field ('Title')", report)

    def test_optional_language_field_without_either_only_warns(self) -> None:
        self._write_source(["Title", "Title_g"], [["First", "Alias"]])
        warnings: list[str] = []

        artifacts = self._generate({"Title": "en"}, warnings)

        self.assertEqual(self._language_cells(artifacts[0]), [("en", "")])
        self.assertEqual(
            [warning for warning in warnings if "language" in warning],
            [
                f"{self.source_path}:1: field 'Title_g' has no language and its "
                "language cells will be empty; set default_languages['Title_g'] "
                "or add a 'Title_g_lang' column"
            ],
        )

    def test_language_columns_are_not_unknown(self) -> None:
        self._write_source(
            ["Title", "Title_lang", "Title_g_lang", "Creator_lang"],
            [["First", "ja", "", ""]],
        )
        warnings: list[str] = []

        self._generate({"Title": "en", "Title_g": "en"}, warnings)

        unknown = [warning for warning in warnings if "unknown column" in warning]
        self.assertEqual(len(unknown), 1)
        self.assertIn("unknown column 'Creator_lang'", unknown[0])

    def test_field_named_like_language_column_is_rejected(self) -> None:
        export_path = self.root / "collision.zip"
        _write_export(
            export_path,
            {
                "item_title": _object_field("Title", "subitem_title"),
                "item_title_lang": {"type": "string", "title": "Title_lang"},
            },
        )
        config = MetadataGenerationConfig(
            input_path=self.source_path,
            output_dir=self.output_dir,
            registration_config_path=self._settings({}, export_path),
        )

        with self.assertRaisesRegex(
            MetadataInputError,
            "ItemType field 'Title_lang' has the name of the language column "
            "for field 'Title'",
        ):
            load_metadata_schema(config)

    def test_sample_schema_marks_title_field(self) -> None:
        config = MetadataGenerationConfig(
            input_path=self.source_path,
            output_dir=self.output_dir,
            registration_config_path=self._settings({}, SAMPLE_EXPORT),
        )

        schema = load_metadata_schema(config)

        self.assertEqual(schema.title_fields, {"Title"})
        self.assertEqual(schema.language_fields, ["Title", "Title_g"])


class MultipleValueTests(_LanguageTestCase):
    def _rows(self, artifact) -> list[list[str]]:
        with artifact.tsv_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            rows = list(csv.reader(file_obj, delimiter="\t"))
        for row in rows[1:]:
            self.assertEqual(len(row), len(rows[1]))
        return rows

    def _cells(self, artifact, prefix: str) -> list[dict[str, str]]:
        rows = self._rows(artifact)
        return [
            {
                name: value
                for name, value in zip(rows[2], row)
                if name.startswith(prefix)
            }
            for row in rows[5:]
        ]

    def test_multiple_titles_expand_with_default_language(self) -> None:
        self._write_source(["Title"], [["['T1', 'T2']"], ["Only"]])

        artifacts = self._generate({"Title": "en"})

        rows = self._rows(artifacts[0])
        self.assertIn(".metadata.item_30001_title0[1].subitem_title", rows[1])
        self.assertIn(".metadata.item_30001_title0[1].subitem_title_language", rows[1])
        self.assertEqual(
            self._cells(artifacts[0], "Title["),
            [
                {
                    "Title[0].タイトル": "T1",
                    "Title[0].言語": "en",
                    "Title[1].タイトル": "T2",
                    "Title[1].言語": "en",
                },
                {
                    "Title[0].タイトル": "Only",
                    "Title[0].言語": "en",
                    "Title[1].タイトル": "",
                    "Title[1].言語": "",
                },
            ],
        )

    def test_row_language_list_is_aligned_with_values(self) -> None:
        self._write_source(
            ["Title", "Title_lang"],
            [["['日本語', 'English']", "['ja', ' en ']"]],
        )

        artifacts = self._generate({"Title": "fr"})

        self.assertEqual(
            self._cells(artifacts[0], "Title["),
            [
                {
                    "Title[0].タイトル": "日本語",
                    "Title[0].言語": "ja",
                    "Title[1].タイトル": "English",
                    "Title[1].言語": "en",
                }
            ],
        )

    def test_single_row_language_applies_to_every_value(self) -> None:
        self._write_source(
            ["Title", "Title_lang"],
            [["['T1', 'T2']", "ja"], ["['T3', 'T4']", "['ja']"]],
        )

        artifacts = self._generate({"Title": "en"})

        self.assertEqual(
            [
                (cells["Title[0].言語"], cells["Title[1].言語"])
                for cells in self._cells(artifacts[0], "Title[")
            ],
            [("ja", "ja"), ("ja", "ja")],
        )

    def test_language_count_mismatch_is_row_error(self) -> None:
        self._write_source(
            ["Title", "Title_lang"],
            [["['T1', 'T2', 'T3']", "['ja', 'en']"], ["Ok", ""]],
        )

        with self.assertRaisesRegex(
            MetadataInputError,
            r"source\.csv:2: 'Title_lang' has 2 languages but 'Title' has 3 "
            r"value\(s\)",
        ):
            self._generate({"Title": "en"})

        artifacts = self._generate({"Title": "en"}, skip_invalid_rows=True)
        self.assertEqual(artifacts[0].row_count, 1)

    def test_single_value_field_rejects_several_values(self) -> None:
        self._write_source(["Title", "Title_g"], [["T", "['A1', 'A2']"]])

        with self.assertRaisesRegex(
            MetadataInputError,
            r"source\.csv:2: 'Title_g' accepts a single value but got 2$",
        ):
            self._generate({"Title": "en", "Title_g": "en"})

    def test_field_without_language_expands_values_only(self) -> None:
        self._write_source(["Title", "Creator"], [["T", "['Alice', 'Bob']"]])

        artifacts = self._generate({"Title": "en"})

        self.assertEqual(
            self._cells(artifacts[0], "Creator"),
            [{"Creator[0].None": "Alice", "Creator[1].None": "Bob"}],
        )

    def test_title_without_language_on_any_value_is_row_error(self) -> None:
        self._write_source(
            ["Title", "Title_lang"], [["['T1', 'T2']", ""], ["['T3', 'T4']", "ja"]]
        )

        with self.assertRaisesRegex(
            MetadataInputError, r"source\.csv:2: no title field \('Title'\) has both"
        ):
            self._generate({})

        artifacts = self._generate({}, skip_invalid_rows=True)
        self.assertEqual(artifacts[0].row_count, 1)


class MultipleTitleFieldTests(_LanguageTestCase):
    def _generate_multi(
        self,
        default_languages: dict[str, str],
        *,
        hidden: frozenset[str] = frozenset(),
        warnings: list[str] | None = None,
        **overrides,
    ):
        export_path = self.root / "multi.zip"
        _write_export(
            export_path,
            {
                "item_a": _object_field("TitleA", "subitem_title"),
                "item_b": _object_field("TitleB", "subitem_title"),
            },
            hidden=hidden,
            title_keys=("item_a", "item_b"),
        )
        config = MetadataGenerationConfig(
            input_path=self.source_path,
            output_dir=self.output_dir,
            registration_config_path=self._settings(default_languages, export_path),
            **overrides,
        )
        on_warning = warnings.append if warnings is not None else None
        return generate_metadata_artifacts(config, on_warning=on_warning)

    def test_one_title_with_language_is_enough(self) -> None:
        self._write_source(
            ["TitleA", "TitleB", "TitleB_lang"],
            [["A1", "B1", "ja"], ["A2", "", "ja"], ["", "B3", "en"]],
        )
        warnings: list[str] = []

        artifacts = self._generate_multi({}, warnings=warnings, skip_invalid_rows=True)

        self.assertEqual(artifacts[0].row_count, 2)
        report = (self.output_dir / "invalid_rows.tsv").read_text(encoding="utf-8-sig")
        self.assertIn("no title field ('TitleA', 'TitleB') has both", report)
        self.assertTrue(
            any("field 'TitleA' has no language" in warning for warning in warnings)
        )

    def test_repeatable_title_index_with_language_is_enough(self) -> None:
        export_path = self.root / "array.zip"
        _write_export(
            export_path,
            {
                "item_a": _array_field("TitleA", "subitem_title"),
                "item_b": _object_field("TitleB", "subitem_title"),
            },
            title_keys=("item_a", "item_b"),
        )
        self._write_source(
            ["TitleA", "TitleA_lang", "TitleB"],
            [["['A1', 'A2']", "['ja', 'en']", ""], ["['A3', 'A4']", "", "B"]],
        )
        config = MetadataGenerationConfig(
            input_path=self.source_path,
            output_dir=self.output_dir,
            registration_config_path=self._settings({}, export_path),
            skip_invalid_rows=True,
        )

        artifacts = generate_metadata_artifacts(config)

        self.assertEqual(artifacts[0].row_count, 1)
        report = (self.output_dir / "invalid_rows.tsv").read_text(encoding="utf-8-sig")
        self.assertIn("no title field ('TitleA', 'TitleB') has both", report)

    def test_no_title_language_source_stops_generation(self) -> None:
        self._write_source(["TitleA", "TitleB"], [["A1", "B1"]])

        with self.assertRaisesRegex(
            MetadataInputError, r"no title field \('TitleA', 'TitleB'\) has a language"
        ):
            self._generate_multi({})

    def test_hidden_title_field_is_ignored(self) -> None:
        self._write_source(["TitleA", "TitleB"], [["A1", "B1"]])

        with self.assertRaisesRegex(
            MetadataInputError, r"no title field \('TitleB'\) has a language"
        ):
            self._generate_multi({"TitleA": "en"}, hidden=frozenset({"item_a"}))

    def test_only_hidden_title_fields_stop_generation(self) -> None:
        self._write_source(["TitleA", "TitleB"], [["A1", "B1"]])

        with self.assertRaisesRegex(
            MetadataInputError,
            r"every title field \('TitleA', 'TitleB'\) is hidden; WEKO ignores "
            r"hidden title fields",
        ):
            self._generate_multi(
                {"TitleA": "en", "TitleB": "en"},
                hidden=frozenset({"item_a", "item_b"}),
            )


if __name__ == "__main__":
    unittest.main()
