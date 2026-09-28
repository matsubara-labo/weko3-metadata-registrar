from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from generation.metadata_pipeline import (
    MetadataGenerationConfig,
    MetadataInputError,
    MetadataSchema,
    build_title_fallback,
    generate_metadata_artifacts,
    load_metadata_schema,
)
from scripts import generate_metadata_imports

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPORT = (
    REPOSITORY_ROOT / "sample" / "AXIES2025" / "config" / "ItemType_export_sample.zip"
)
TITLE_BINDING = ".metadata.item_30001_title0[0].subitem_title"
TITLE_LANGUAGE = ".metadata.item_30001_title0[0].subitem_title_language"
FALLBACKS = (("R", "Title_r"), ("G", "Title_g"))


class TitleFallbackGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.output_dir = self.root / "output"
        self.source_path = self.root / "source.csv"
        self.settings_path = self.root / "settings.json"
        self.settings_path.write_text(
            json.dumps(
                {
                    "weko_base_url": "https://weko.example.org",
                    "item_type_export": str(SAMPLE_EXPORT),
                    "indexes": {"Example": "999"},
                    "default_index": "Example",
                    "publish_date": "2026-08-23",
                    "default_languages": {"Title": "en", "Title_g": "en"},
                }
            ),
            encoding="utf-8",
        )

    def _write_source(self, fieldnames: list[str], rows: list[list[str]]) -> None:
        with self.source_path.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(fieldnames)
            writer.writerows(rows)

    def _generate(self, filled: list[tuple[int, str]] | None = None, **overrides):
        config = MetadataGenerationConfig(
            input_path=self.source_path,
            output_dir=self.output_dir,
            registration_config_path=self.settings_path,
            **overrides,
        )
        on_title_filled = (
            (lambda row, title: filled.append((row, title)))
            if filled is not None
            else None
        )
        return generate_metadata_artifacts(config, on_title_filled=on_title_filled)

    def _titles(self, artifact) -> list[tuple[str, str]]:
        with artifact.tsv_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            rows = list(csv.reader(file_obj, delimiter="\t"))
        title = rows[1].index(TITLE_BINDING)
        language = rows[1].index(TITLE_LANGUAGE)
        return [(row[title], row[language]) for row in rows[5:]]

    def test_empty_title_uses_first_fallback_with_a_value(self) -> None:
        self._write_source(
            ["Title", "Title_g", "Title_r"],
            [
                ["[]", "repo-g", "['DNAxiS']"],
                ["", "repo-only", "[]"],
                ["['Generated']", "repo", "['Readme']"],
            ],
        )
        filled: list[tuple[int, str]] = []

        artifacts = self._generate(filled, title_fallbacks=FALLBACKS)

        self.assertEqual(
            self._titles(artifacts[0]),
            [
                ("NoTitle (R: DNAxiS)", "en"),
                ("NoTitle (G: repo-only)", "en"),
                ("Generated", "en"),
            ],
        )
        self.assertEqual(
            filled, [(2, "NoTitle (R: DNAxiS)"), (3, "NoTitle (G: repo-only)")]
        )

    def test_prefix_can_be_changed(self) -> None:
        self._write_source(["Title", "Title_g"], [["[]", "repo"]])

        artifacts = self._generate(
            title_fallbacks=(("G", "Title_g"),), title_fallback_prefix="Untitled"
        )

        self.assertEqual(self._titles(artifacts[0]), [("Untitled (G: repo)", "en")])

    def test_blank_list_elements_do_not_count_as_a_title(self) -> None:
        self._write_source(["Title", "Title_g"], [["['', ' ']", "repo"]])

        artifacts = self._generate(title_fallbacks=(("G", "Title_g"),))

        self.assertEqual(self._titles(artifacts[0]), [("NoTitle (G: repo)", "en")])

    def test_row_stays_invalid_when_every_fallback_is_empty(self) -> None:
        self._write_source(["Title", "Title_g", "Title_r"], [["[]", "", "[]"]])

        with self.assertRaisesRegex(
            MetadataInputError, r"source\.csv:2: Required metadata field 'Title'"
        ):
            self._generate(title_fallbacks=FALLBACKS)

    def test_without_option_empty_title_is_still_an_error(self) -> None:
        self._write_source(["Title", "Title_g"], [["[]", "repo"]])

        with self.assertRaisesRegex(
            MetadataInputError, r"Required metadata field 'Title' is empty"
        ):
            self._generate()

    def test_missing_fallback_column_stops_before_writing(self) -> None:
        self._write_source(["Title", "Title_g"], [["[]", "repo"]])

        with self.assertRaisesRegex(
            MetadataInputError,
            r"source\.csv:1: --title-fallback column\(s\) not in the input: "
            r"'Title_r'$",
        ):
            self._generate(title_fallbacks=FALLBACKS)
        self.assertFalse(self.output_dir.exists())

    def test_non_itemtype_fallback_column_is_not_unknown(self) -> None:
        self._write_source(["Title", "llm_title"], [["[]", "Guess"]])
        filled: list[tuple[int, str]] = []

        artifacts = self._generate(
            filled, title_fallbacks=(("L", "llm_title"),), strict_columns=True
        )

        self.assertEqual(self._titles(artifacts[0]), [("NoTitle (L: Guess)", "en")])

    def test_fills_are_not_reported_when_generation_stops(self) -> None:
        self._write_source(
            ["Title", "Title_g", "PublicationYear_g"],
            [["[]", "repo", "2020-01-02"], ["Kept", "", "2020/01/02"]],
        )
        filled: list[tuple[int, str]] = []

        with self.assertRaises(MetadataInputError):
            self._generate(filled, title_fallbacks=(("G", "Title_g"),))

        self.assertEqual(filled, [])

    def test_invalid_rows_report_keeps_the_original_title(self) -> None:
        self._write_source(
            ["Title", "Title_g", "PublicationYear_g"],
            [["[]", "repo", "2020/01/02"], ["Kept", "", "2020-01-02"]],
        )
        filled: list[tuple[int, str]] = []

        artifacts = self._generate(
            filled, title_fallbacks=(("G", "Title_g"),), skip_invalid_rows=True
        )

        self.assertEqual(artifacts[0].row_count, 1)
        self.assertEqual(filled, [])
        with (self.output_dir / "invalid_rows.tsv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as file_obj:
            report = list(csv.DictReader(file_obj, delimiter="\t"))
        self.assertEqual(report[0]["Title"], "[]")
        self.assertIn("is not a WEKO date", report[0]["_invalid_reason"])


class BuildTitleFallbackTests(unittest.TestCase):
    def _schema(self, title_fields: frozenset[str]) -> MetadataSchema:
        return MetadataSchema(
            item_type_name="T(1)",
            item_schema_url="https://weko.example.org/items/jsonschema/1",
            base_metadata_bindings=[],
            base_display_columns=[],
            base_column_values=[],
            base_column_attributes=[],
            column_bindings={"Alt": [".a"], "Title": [".t"], "Other": [".o"]},
            default_languages={},
            field_attributes={"Alt": "", "Title": "", "Other": ""},
            display_columns={"Alt": ["Alt"], "Title": ["Title"], "Other": ["O"]},
            repeatable_fields=frozenset(),
            title_fields=title_fields,
        )

    def test_no_sources_disables_the_fallback(self) -> None:
        self.assertIsNone(build_title_fallback(self._schema(frozenset()), ()))

    def test_first_title_field_in_itemtype_order_is_targeted(self) -> None:
        fallback = build_title_fallback(
            self._schema(frozenset({"Other", "Title"})), (("G", "Other"),)
        )

        self.assertEqual(fallback.field_name, "Title")

    def test_itemtype_without_title_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(MetadataInputError, r"has none$"):
            build_title_fallback(self._schema(frozenset()), (("G", "Other"),))

    def test_duplicate_labels_are_rejected(self) -> None:
        with self.assertRaisesRegex(MetadataInputError, r"must be unique"):
            build_title_fallback(
                self._schema(frozenset({"Title"})), (("G", "Alt"), ("G", "Other"))
            )

    def test_sample_schema_targets_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "weko_base_url": "https://weko.example.org",
                        "item_type_export": str(SAMPLE_EXPORT),
                        "indexes": {"Example": "999"},
                        "default_index": "Example",
                        "publish_date": "2026-08-23",
                        "default_languages": {"Title": "en"},
                    }
                ),
                encoding="utf-8",
            )
            schema = load_metadata_schema(
                MetadataGenerationConfig(
                    input_path=Path("unused.csv"),
                    output_dir=Path("unused"),
                    registration_config_path=settings,
                )
            )

        fallback = build_title_fallback(schema, FALLBACKS)

        self.assertEqual(fallback.field_name, "Title")


class TitleFallbackCliTests(unittest.TestCase):
    def _run_main(self, *extra_args: str, side_effect=None):
        argv = ["generate", "--input", "in.txt", "--output-dir", "out", *extra_args]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(
                generate_metadata_imports,
                "generate_metadata_artifacts",
                return_value=[],
                side_effect=side_effect,
            ) as generate,
            mock.patch("builtins.print") as print_mock,
        ):
            self.assertEqual(generate_metadata_imports.main(), 0)
        return generate.call_args.args[0], print_mock

    def test_defaults_disable_the_fallback(self) -> None:
        config, _ = self._run_main()

        self.assertEqual(config.title_fallbacks, ())
        self.assertEqual(config.title_fallback_prefix, "NoTitle")

    def test_options_are_passed_in_order(self) -> None:
        config, _ = self._run_main(
            "--title-fallback",
            "R=Title_r",
            "--title-fallback",
            " G = Title_g ",
            "--title-fallback-prefix",
            "Untitled",
        )

        self.assertEqual(config.title_fallbacks, FALLBACKS)
        self.assertEqual(config.title_fallback_prefix, "Untitled")

    def test_malformed_fallback_is_rejected(self) -> None:
        for value in ("Title_r", "=Title_r", "R="):
            with self.subTest(value=value):
                argv = ["generate", "--input", "i", "--output-dir", "o"]
                with (
                    mock.patch.object(sys, "argv", [*argv, "--title-fallback", value]),
                    mock.patch("sys.stderr"),
                    self.assertRaises(SystemExit),
                ):
                    generate_metadata_imports.main()

    def test_filled_titles_are_printed(self) -> None:
        def fake_generate(config, *, on_title_filled, **kwargs):
            on_title_filled(7, "NoTitle (G: repo)")
            return []

        _, print_mock = self._run_main(
            "--title-fallback", "G=Title_g", side_effect=fake_generate
        )

        print_mock.assert_any_call("filled title: in.txt:7: NoTitle (G: repo)")
        print_mock.assert_any_call("filled 1 empty title(s) with --title-fallback")


if __name__ == "__main__":
    unittest.main()
