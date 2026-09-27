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
    generate_metadata_artifacts,
    is_weko_date,
    load_rows,
    load_rows_with_errors,
    normalize_row,
)
from generation.registration_config import (
    RegistrationConfigError,
    load_registration_settings,
)
from scripts import generate_metadata_imports

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EXPORT = REPOSITORY_ROOT / "sample" / "config" / "ItemType_export_sample.zip"


def _schema() -> MetadataSchema:
    return MetadataSchema(
        item_type_name="Test(1)",
        item_schema_url="https://weko.example.org/items/jsonschema/1",
        base_metadata_bindings=[],
        template_column_values={},
        template_column_attributes={},
        column_bindings={
            "Title": [".metadata.item_title"],
            "Issued": [".metadata.item_issued"],
            "Dates": ".metadata.item_dates[{index}].interim",
            "Note": [".metadata.item_note"],
        },
        default_languages={},
        field_attributes={
            "Title": "Required",
            "Issued": "",
            "Dates": "Allow Multiple",
            "Note": "",
        },
        display_columns={
            "Title": ["Title"],
            "Issued": ["Issued"],
            "Dates": "Dates[{index}].None",
            "Note": ["Note"],
        },
    )


DATE_FIELDS = frozenset({"Issued", "Dates"})


class WekoDateTests(unittest.TestCase):
    def test_weko_date_formats(self) -> None:
        for value in ("2020-01-02", "2020-01", "2020", "2020-02-29"):
            with self.subTest(value=value):
                self.assertTrue(is_weko_date(value))
        for value in (
            "2020-1-2",
            "2020/01/02",
            "2020-02-30",
            "2021-02-29",
            "2020-13",
            "2020-1",
            " 2020-01-02 ",
            "not-a-date",
            "",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_weko_date(value))

    def test_dates_are_trimmed_and_time_part_dropped(self) -> None:
        row = normalize_row(
            {
                "Title": "t",
                "Issued": " 2020-01-02 ",
                "Dates": "['2020-01-02T10:00:00', ' 2021 ']",
            },
            _schema(),
            DATE_FIELDS,
        )

        self.assertEqual(row["Issued"], "2020-01-02")
        self.assertEqual(row["Dates"], ["2020-01-02", "2021"])

    def test_invalid_dates_are_row_errors(self) -> None:
        for field_name, value in (
            ("Issued", "2020-1-2"),
            ("Issued", "2020/01/02"),
            ("Issued", "2020-02-30"),
            ("Dates", "['2020-01', '2020-13']"),
        ):
            with self.subTest(field_name=field_name, value=value):
                with self.assertRaisesRegex(
                    MetadataInputError,
                    rf"'{field_name}' value .* is not a WEKO date "
                    r"\(YYYY-MM-DD, YYYY-MM or YYYY\)",
                ):
                    normalize_row(
                        {"Title": "t", field_name: value}, _schema(), DATE_FIELDS
                    )

    def test_empty_date_is_allowed(self) -> None:
        row = normalize_row({"Title": "t", "Issued": " "}, _schema(), DATE_FIELDS)

        self.assertEqual(row["Issued"], "")

    def test_non_date_fields_are_not_checked(self) -> None:
        row = normalize_row({"Title": "t", "Note": "2020/01/02"}, _schema())

        self.assertEqual(row["Note"], "2020/01/02")


class ColumnCheckTests(unittest.TestCase):
    def _load(self, header: str, **kwargs) -> tuple[list[str], list[object]]:
        warnings: list[str] = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "input.csv"
            input_path.write_text(
                header + "\n" + ",".join(["x"] * len(header.split(","))) + "\n",
                encoding="utf-8",
            )
            rows, errors = load_rows_with_errors(
                input_path, _schema(), on_warning=warnings.append, **kwargs
            )
        return warnings, errors

    def test_unknown_column_is_warned_with_hint(self) -> None:
        warnings, _ = self._load("Title,Issued,Dates,Nots,id")

        self.assertEqual(len(warnings), 3)
        self.assertTrue(
            warnings[0].endswith(
                "input.csv:1: unknown column 'Nots' (did you mean 'Note'?) "
                "will be ignored"
            )
        )
        self.assertTrue(
            warnings[1].endswith("input.csv:1: unknown column 'id' will be ignored")
        )

    def test_fields_present_in_header_are_not_suggested(self) -> None:
        warnings, _ = self._load("Title,Issued,Dates,Note,Nots,title")

        self.assertEqual(len(warnings), 2)
        self.assertTrue(warnings[0].endswith("unknown column 'Nots' will be ignored"))
        self.assertTrue(warnings[1].endswith("unknown column 'title' will be ignored"))

    def test_case_and_space_differences_are_hinted(self) -> None:
        warnings, _ = self._load("title,Title ,Issued,Dates,Note")

        self.assertRegex(
            warnings[0], r"unknown column 'title' \(did you mean 'Title'\?\)"
        )
        self.assertRegex(
            warnings[1], r"unknown column 'Title ' \(did you mean 'Title'\?\)"
        )
        self.assertRegex(warnings[2], r"missing column 'Title' \(Required\)$")

    def test_missing_columns_are_warned(self) -> None:
        warnings, errors = self._load("Title,Issued")

        self.assertEqual(len(warnings), 2)
        self.assertRegex(warnings[0], r"input\.csv:1: missing column 'Dates'$")
        self.assertRegex(warnings[1], r"input\.csv:1: missing column 'Note'$")
        self.assertEqual(errors, [])

    def test_missing_required_column_warns_and_rows_fail(self) -> None:
        warnings, errors = self._load("Issued,Dates,Note")

        self.assertEqual(len(warnings), 1)
        self.assertRegex(warnings[0], r"missing column 'Title' \(Required\)$")
        self.assertEqual(len(errors), 1)

    def test_unnamed_column_is_not_unknown(self) -> None:
        warnings, _ = self._load(",Title,Issued,Dates,Note", strict_columns=True)

        self.assertEqual(warnings, [])

    def test_invalid_rows_report_columns_are_not_unknown(self) -> None:
        warnings, _ = self._load("_invalid_row,_invalid_reason,Title,Issued,Dates,Note")

        self.assertEqual(warnings, [])

    def test_strict_columns_rejects_all_unknown_columns(self) -> None:
        with self.assertRaisesRegex(
            MetadataInputError,
            r"input\.csv:1: unknown column\(s\) not in the ItemType: "
            r"'Titel' \(did you mean 'Title'\?\), 'id'",
        ):
            self._load("Titel,Issued,id", strict_columns=True)

    def test_strict_columns_keeps_missing_columns_as_warnings(self) -> None:
        warnings, _ = self._load("Title", strict_columns=True)

        self.assertEqual(len(warnings), 3)

    def test_load_rows_is_backward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "input.csv"
            input_path.write_text("Title,extra\nt,x\n", encoding="utf-8")
            rows = load_rows(input_path, _schema())

        self.assertEqual(rows[0]["Title"], "t")


class PublishDateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.source_path = self.root / "source.csv"
        with self.source_path.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(["corpusid", "Title", "Titel", "PublicationYear_g"])
            writer.writerow(["1", "First", "x", "2020-01-02T00:00:00"])
            writer.writerow(["2", "Second", "y", "2020/01/02"])

    def _settings(self, publish_date: str) -> Path:
        settings_path = self.root / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "weko_base_url": "https://weko.example.org",
                    "item_type_export": str(SAMPLE_EXPORT),
                    "indexes": {"Example": "999"},
                    "default_index": "Example",
                    "publish_date": publish_date,
                    "default_languages": {"Title": "en"},
                }
            ),
            encoding="utf-8",
        )
        return settings_path

    def _config(self, **overrides) -> MetadataGenerationConfig:
        values = {
            "input_path": self.source_path,
            "output_dir": self.root / "output",
            "registration_config_path": self._settings("2026-08-23"),
        }
        values.update(overrides)
        return MetadataGenerationConfig(**values)

    def test_invalid_publish_date_in_config_is_rejected(self) -> None:
        for value in ("27/05/2025", "2025-5-27", "2025-02-30", "2025-05"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    RegistrationConfigError, "publish_date .* YYYY-MM-DD"
                ):
                    load_registration_settings(self._settings(value))

    def test_valid_publish_date_in_config_is_accepted(self) -> None:
        settings = load_registration_settings(self._settings("2025-05-27"))

        self.assertEqual(settings.publish_date, "2025-05-27")

    def test_invalid_publish_date_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            RegistrationConfigError, "--publish-date '27/05/2025'"
        ):
            generate_metadata_artifacts(self._config(publish_date="27/05/2025"))
        self.assertFalse((self.root / "output").exists())

    def test_generation_reports_warnings_and_date_row_errors(self) -> None:
        warnings: list[str] = []

        artifacts = generate_metadata_artifacts(
            self._config(skip_invalid_rows=True), on_warning=warnings.append
        )

        self.assertEqual(artifacts[0].row_count, 1)
        self.assertTrue(
            any(
                "unknown column 'Titel' (did you mean 'Title_g'?)" in w
                for w in warnings
            )
        )
        report = (self.root / "output" / "invalid_rows.tsv").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn(
            "'PublicationYear_g' value '2020/01/02' is not a WEKO date", report
        )

    def test_strict_columns_stops_generation(self) -> None:
        with self.assertRaisesRegex(MetadataInputError, "unknown column\\(s\\)"):
            generate_metadata_artifacts(self._config(strict_columns=True))


class CliValidationTests(unittest.TestCase):
    def _parse(self, *extra_args: str):
        return generate_metadata_imports.build_parser().parse_args(
            ["--input", "a", "--output-dir", "b", *extra_args]
        )

    def test_invalid_publish_date_is_rejected_by_parser(self) -> None:
        for value in ("27/05/2025", "2025-5-27", "2025-02-30"):
            with self.subTest(value=value):
                with (
                    mock.patch("sys.stderr"),
                    self.assertRaises(SystemExit),
                ):
                    self._parse("--publish-date", value)

    def test_valid_publish_date_is_accepted_by_parser(self) -> None:
        self.assertEqual(
            self._parse("--publish-date", "2025-05-27").publish_date, "2025-05-27"
        )

    def test_strict_columns_option(self) -> None:
        self.assertFalse(self._parse().strict_columns)
        self.assertTrue(self._parse("--strict-columns").strict_columns)

    def test_warnings_are_printed(self) -> None:
        def fake_generate(config, *, on_warning, **kwargs):
            self.assertTrue(config.strict_columns)
            on_warning("in.txt:1: missing column 'Note'")
            return []

        argv = [
            "generate",
            "--input",
            "in.txt",
            "--output-dir",
            "out",
            "--strict-columns",
        ]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(
                generate_metadata_imports,
                "generate_metadata_artifacts",
                side_effect=fake_generate,
            ),
            mock.patch("builtins.print") as print_mock,
        ):
            self.assertEqual(generate_metadata_imports.main(), 0)

        print_mock.assert_any_call("warning: in.txt:1: missing column 'Note'")


if __name__ == "__main__":
    unittest.main()
