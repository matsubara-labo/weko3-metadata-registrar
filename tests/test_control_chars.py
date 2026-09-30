from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from generation.control_chars import (
    count_rules,
    repair_cell,
    repair_file,
    repair_value,
    write_repair_report,
)
from generation.metadata_pipeline import parse_literal_list
from scripts import repair_control_chars


class RepairValueTests(unittest.TestCase):
    def test_r1_restores_broken_unicode_escapes(self) -> None:
        cases = {
            "Moro-Vel\x00e1zquez": "Moro-Velázquez",
            "Universit\x00E4t": "Universität",
            "Paulavi\x010dius": "Paulavičius",
            "Age_j^{\x03b3_{k}}": "Age_j^{γ_{k}}",
        }
        for broken, repaired in cases.items():
            with self.subTest(broken=broken):
                self.assertEqual(repair_value(broken), (repaired, ("R1",)))

    def test_r1_keeps_the_encoded_code_point_even_if_the_llm_was_wrong(self) -> None:
        # README says Yi\u{g}it; the value encodes U+0110 and is kept as is.
        self.assertEqual(repair_value("Yi\x0110it")[0], "YiĐit")

    def test_r1_skips_code_points_that_are_not_text(self) -> None:
        # U+00BF is punctuation, so the character is only made visible.
        self.assertEqual(
            repair_value("Universit\x00bft"), ("Universit\\x00bft", ("R4",))
        )

    def test_r1_never_merges_tab_lf_or_cr_with_hex_digits(self) -> None:
        for value in ("col\tab", "line\nbe", "x\r\nad"):
            with self.subTest(value=value):
                self.assertEqual(repair_value(value), (value, ()))

    def test_r2_restores_latex_commands_eaten_by_escapes(self) -> None:
        self.assertEqual(
            repair_value("$\x08eta$-VAE and $\x0crak{O}$"),
            ("$\\beta$-VAE and $\\frak{O}$", ("R2",)),
        )

    def test_r3_restores_tab_only_before_known_commands(self) -> None:
        self.assertEqual(
            repair_value("Mu\tilde{n}oz, S{\text{o}}ren, $\textalpha$"),
            ("Mu\\tilde{n}oz, S{\\text{o}}ren, $\\textalpha$", ("R3",)),
        )
        table = "CP\t10571\tAT\t11\n\tFile::Slurp"
        self.assertEqual(repair_value(table), (table, ()))

    def test_r3_restores_cr_before_a_letter_but_not_before_lf(self) -> None:
        self.assertEqual(
            repair_value("(r_s, \rho_s) in '\result'"),
            ("(r_s, \\rho_s) in '\\result'", ("R3",)),
        )
        self.assertEqual(repair_value("a\r\nb"), ("a\r\nb", ()))

    def test_r2_characters_are_never_read_as_unicode_escapes(self) -> None:
        cases = {
            "\x0bec{x}": "\\vec{x}",
            "\x08ackslash": "\\backslash",
            "\x0cace": "\\face",
            "{\x07a}": "{\\aa}",
        }
        for broken, repaired in cases.items():
            with self.subTest(broken=broken):
                self.assertEqual(repair_value(broken), (repaired, ("R2",)))

    def test_r4_also_covers_edges_the_generator_would_strip(self) -> None:
        # "\infty-Diff" decoded to "\x1diff"; stripping would leave "iff".
        self.assertEqual(
            repair_value("\x1diff: Infinite"), ("\\x1diff: Infinite", ("R4",))
        )

    def test_r4_makes_other_control_characters_visible(self) -> None:
        self.assertEqual(
            repair_value("the $\x12$ ECE \x7fn\x00"),
            ("the $\\x12$ ECE \\x7fn\\x00", ("R4",)),
        )

    def test_rules_are_reported_in_order_once(self) -> None:
        self.assertEqual(repair_value("the \x1e\x00b0P\x00b0 regime")[1], ("R1", "R4"))


class RepairCellTests(unittest.TestCase):
    def test_list_cell_is_rewritten_and_parses_to_the_repaired_values(self) -> None:
        cell = "['L. Moro-Vel\\x00e1zquez', None, 'kept']"

        new, changes = repair_cell(cell)

        self.assertEqual(parse_literal_list(new), ["L. Moro-Velázquez", "", "kept"])
        self.assertEqual(
            changes, [(0, ("R1",), "L. Moro-Vel\x00e1zquez", "L. Moro-Velázquez")]
        )

    def test_cells_without_changes_keep_their_exact_text(self) -> None:
        for cell in ('["a",  "b"]', "plain \\x00 text", "[1, 2]", "[broken", ""):
            with self.subTest(cell=cell):
                self.assertEqual(repair_cell(cell), (cell, []))


class RepairFileTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.input = self.root / "input.tsv"
        with self.input.open("w", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj, delimiter="\t", lineterminator="\n")
            writer.writerow(["corpusid", "Title", "Creator_r"])
            writer.writerow(["11", "['Plain']", "['Ada']"])
            writer.writerow(
                ["22", "['$\\x08eta$']", "['Vel\\x00e1zquez', 'P. \\x7fz']"]
            )
        os.utime(self.input, ns=(1_000_000_000_000_000_000, 1_700_000_000_123_456_789))
        self.output = self.root / "out" / "repaired.tsv"

    def rows(self, path: Path) -> list[list[str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            return list(csv.reader(file_obj, delimiter="\t"))

    def test_repairs_are_listed_with_record_number_and_id(self) -> None:
        repairs = repair_file(self.input, self.output)

        self.assertEqual(
            [
                (r.record_number, r.record_id, r.column, r.index, r.rules)
                for r in repairs
            ],
            [
                (3, "22", "Title", 0, ("R2",)),
                (3, "22", "Creator_r", 0, ("R1",)),
                (3, "22", "Creator_r", 1, ("R4",)),
            ],
        )
        self.assertEqual(count_rules(repairs), {"R1": 1, "R2": 1, "R4": 1})
        rows = self.rows(self.output)
        self.assertEqual(rows[:2], self.rows(self.input)[:2])
        self.assertEqual(parse_literal_list(rows[2][2]), ["Velázquez", "P. \\x7fz"])

    def test_modification_time_is_copied_unless_disabled(self) -> None:
        repair_file(self.input, self.output)
        self.assertEqual(self.output.stat().st_mtime_ns, self.input.stat().st_mtime_ns)

        other = self.root / "other.tsv"
        repair_file(self.input, other, keep_mtime=False)
        self.assertNotEqual(other.stat().st_mtime_ns, self.input.stat().st_mtime_ns)

    def test_output_must_differ_from_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "must differ"):
            repair_file(self.input, self.input)
        link = self.root / "link.tsv"
        os.link(self.input, link)
        with self.assertRaisesRegex(ValueError, "must differ"):
            repair_file(self.input, link)

    def test_blank_lines_are_not_numbered_like_the_generator(self) -> None:
        text = self.input.read_text(encoding="utf-8").replace("\n11", "\n\n11")
        self.input.write_text(text, encoding="utf-8")

        repairs = repair_file(self.input, self.output)

        self.assertEqual({repair.record_number for repair in repairs}, {3})
        self.assertEqual(self.output.read_text(encoding="utf-8").count("\n\n"), 1)

    def test_failure_leaves_no_partial_output(self) -> None:
        with (
            mock.patch(
                "generation.control_chars._repair_row", side_effect=RuntimeError("x")
            ),
            self.assertRaises(RuntimeError),
        ):
            repair_file(self.input, self.output)

        self.assertEqual(list(self.output.parent.iterdir()), [])

    def test_report_makes_control_characters_visible(self) -> None:
        report = self.root / "report.tsv"
        write_repair_report(repair_file(self.input, self.output), report)

        rows = self.rows(report)
        self.assertEqual(
            rows[0],
            ["record_no", "id", "column", "list_index", "rules", "before", "after"],
        )
        self.assertEqual(
            rows[2],
            ["3", "22", "Creator_r", "0", "R1", "'Vel\\x00e1zquez'", "Velázquez"],
        )


class ReportWriteTests(unittest.TestCase):
    def test_failed_report_write_keeps_the_previous_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.tsv"
            report.write_text("previous", encoding="utf-8")
            with (
                mock.patch("csv.writer", side_effect=OSError("disk full")),
                self.assertRaises(OSError),
            ):
                write_repair_report([], report)

            self.assertEqual(report.read_text(encoding="utf-8"), "previous")
            self.assertEqual(
                sorted(path.name for path in Path(directory).iterdir()), ["report.tsv"]
            )


class RepairCliTests(unittest.TestCase):
    def run_main(self, *args: str) -> tuple[int, str]:
        with (
            mock.patch.object(sys, "argv", ["repair", *args]),
            mock.patch("builtins.print") as print_mock,
        ):
            code = repair_control_chars.main()
        output = "\n".join(
            " ".join(str(arg) for arg in call.args)
            for call in print_mock.call_args_list
        )
        return code, output

    def test_writes_output_and_default_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "in.tsv"
            source.write_text("corpusid\tTitle\n1\t['a\\x00e9']\n", encoding="utf-8")
            output = root / "fixed.tsv"

            code, printed = self.run_main(
                "--input", str(source), "--output", str(output)
            )

            self.assertEqual(code, 0)
            self.assertTrue((root / "fixed_repairs.tsv").exists())
            self.assertIn(
                "repaired 1 list element(s) in 1 record(s) (rules: R1=1)", printed
            )

            code, _ = self.run_main("--input", str(source), "--output", str(output))
            self.assertEqual(code, 1)
            code, _ = self.run_main(
                "--input", str(source), "--output", str(output), "--overwrite"
            )
            self.assertEqual(code, 0)

    def test_report_and_output_never_replace_the_input_or_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "foo_repairs.tsv"
            source.write_text("corpusid\tTitle\n1\t['a']\n", encoding="utf-8")
            original = source.read_bytes()
            cases = [
                ("--output", str(source)),
                ("--output", str(root / "foo.tsv"), "--overwrite"),
                ("--output", str(root / "x.tsv"), "--report", str(root / "x.tsv")),
            ]
            for extra in cases:
                with self.subTest(extra=extra):
                    code, _ = self.run_main("--input", str(source), *extra)
                    self.assertEqual(code, 1)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse((root / "x.tsv").exists())


if __name__ == "__main__":
    unittest.main()
