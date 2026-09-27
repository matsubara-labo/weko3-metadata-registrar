from __future__ import annotations

import unittest

from generation.metadata_pipeline import MetadataInputError, parse_literal_list


class ParseLiteralListTests(unittest.TestCase):
    def test_plain_strings_are_preserved_verbatim(self) -> None:
        for text in (
            "1.50",
            "1.10",
            "0x1F",
            "1_000",
            "1e3",
            "1, 2",
            "'a' 'b'",
            "'quoted'",
            "None",
            "3.14159265358979323846",
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_literal_list(text), [text])

    def test_plain_string_is_stripped(self) -> None:
        for text, expected in (
            ("  1.50 \n", "1.50"),
            ("  indented", "indented"),
            ("trailing  ", "trailing"),
            ("\u3000全角\u3000", "全角"),
            ("\xa0nbsp\xa0", "nbsp"),
            ("\n line1\n line2 \n", "line1\n line2"),
            ("  [draft] ", "[draft]"),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_literal_list(text), [expected])

    def test_list_elements_are_stripped(self) -> None:
        self.assertEqual(parse_literal_list("[' a ', '\u3000b']"), ["a", "b"])
        self.assertEqual(parse_literal_list("['  ']"), [""])

    def test_quoted_string_list_is_split(self) -> None:
        self.assertEqual(parse_literal_list("['Alice', 'Bob']"), ["Alice", "Bob"])
        self.assertEqual(parse_literal_list("['1.50']"), ["1.50"])

    def test_bracketed_text_that_is_not_a_list_is_kept(self) -> None:
        self.assertEqual(parse_literal_list("[draft] Title"), ["[draft] Title"])
        self.assertEqual(parse_literal_list("[draft]"), ["[draft]"])

    def test_none_elements_become_empty_strings(self) -> None:
        self.assertEqual(parse_literal_list("[None]"), [""])
        self.assertEqual(parse_literal_list("['']"), [""])

    def test_empty_values_yield_no_elements(self) -> None:
        self.assertEqual(parse_literal_list(None), [])
        self.assertEqual(parse_literal_list(""), [])
        self.assertEqual(parse_literal_list("   "), [])

    def test_non_string_list_elements_are_rejected(self) -> None:
        for text, type_name in (
            ("[['a','b']]", "list"),
            ("[1.50]", "float"),
            ("[1]", "int"),
            ("[True]", "bool"),
            ("[('a',)]", "tuple"),
            ("[{'a': 1}]", "dict"),
        ):
            with self.subTest(text=text):
                with self.assertRaisesRegex(MetadataInputError, type_name):
                    parse_literal_list(text)

    def test_list_input_is_stringified(self) -> None:
        self.assertEqual(parse_literal_list(["a", 1]), ["a", "1"])
        self.assertEqual(parse_literal_list([" a ", "\u3000b\n"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
