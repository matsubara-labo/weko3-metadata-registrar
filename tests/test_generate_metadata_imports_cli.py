from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from scripts import generate_metadata_imports


class GenerateMetadataImportsCliTests(unittest.TestCase):
    def _run_main(self, *extra_args: str):
        argv = ["generate", "--input", "in.txt", "--output-dir", "out", *extra_args]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(
                generate_metadata_imports,
                "generate_metadata_artifacts",
                return_value=[],
            ) as generate,
            mock.patch("builtins.print"),
        ):
            self.assertEqual(generate_metadata_imports.main(), 0)
        return generate.call_args.args[0]

    def test_delimiter_defaults_to_auto(self) -> None:
        config = self._run_main()

        self.assertEqual(config.input_path, Path("in.txt"))
        self.assertEqual(config.delimiter, "auto")

    def test_delimiter_option_is_passed_to_config(self) -> None:
        self.assertEqual(self._run_main("--delimiter", "tab").delimiter, "tab")
        self.assertEqual(self._run_main("--delimiter", "comma").delimiter, "comma")

    def test_overwrite_defaults_to_false(self) -> None:
        self.assertFalse(self._run_main().overwrite)

    def test_overwrite_option_is_passed_to_config(self) -> None:
        self.assertTrue(self._run_main("--overwrite").overwrite)

    def test_removed_paths_are_printed(self) -> None:
        def fake_generate(config, *, on_remove):
            on_remove(Path("out") / "import_001.zip")
            return []

        argv = ["generate", "--input", "in.txt", "--output-dir", "out", "--overwrite"]
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

        print_mock.assert_any_call(f"removed {Path('out') / 'import_001.zip'}")

    def test_unrelated_zip_files_are_warned_about(self) -> None:
        argv = ["generate", "--input", "in.txt", "--output-dir", "out"]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(
                generate_metadata_imports,
                "generate_metadata_artifacts",
                return_value=[],
            ),
            mock.patch.object(
                generate_metadata_imports,
                "find_unrelated_zip_files",
                return_value=[Path("out") / "manual.zip"],
            ) as find_unrelated,
            mock.patch("builtins.print") as print_mock,
        ):
            self.assertEqual(generate_metadata_imports.main(), 0)

        find_unrelated.assert_called_once_with(Path("out"))
        print_mock.assert_any_call(
            f"warning: {Path('out') / 'manual.zip'} is not a generated file "
            "but will be imported if this directory is used as --zip-dir"
        )

    def test_unknown_delimiter_is_rejected(self) -> None:
        with (
            mock.patch("sys.stderr"),
            self.assertRaises(SystemExit),
        ):
            generate_metadata_imports.build_parser().parse_args(
                ["--input", "a", "--output-dir", "b", "--delimiter", ";"]
            )


if __name__ == "__main__":
    unittest.main()
