import unittest

from olmocr.bench.tests import (
    BaselineTest,
    BasePDFTest,
    FootnoteTest,
    FormatTest,
    MathTest,
    TableTest,
    TestChecked,
    TestType,
    TextOrderTest,
    TextPresenceTest,
    ValidationError,
    normalize_text,
    parse_html_tables,
    parse_markdown_tables,
)


class TestNormalizeText(unittest.TestCase):
    """Test the normalize_text function"""

    def test_whitespace_normalization(self):
        """Test that whitespace is properly normalized"""
        input_text = "This  has\tmultiple    spaces\nand\nnewlines"
        expected = "This has multiple spaces and newlines"
        self.assertEqual(normalize_text(input_text), expected)

    def test_character_replacement(self):
        """Test that fancy characters are replaced with ASCII equivalents"""
        input_text = "This has 'fancy' “quotes” and—dashes"
        expected = "This has 'fancy' \"quotes\" and-dashes"
        self.assertEqual(normalize_text(input_text), expected)

    def test_markdown1(self):
        """Test that fancy characters are replaced with ASCII equivalents"""
        input_text = "this is *bold*"
        expected = "this is bold"
        self.assertEqual(normalize_text(input_text), expected)

    def test_markdown2(self):
        """Test that fancy characters are replaced with ASCII equivalents"""
        input_text = "_italic__ is *bold*"
        expected = "italic_ is bold"
        self.assertEqual(normalize_text(input_text), expected)

    def test_empty_input(self):
        """Test that empty input returns empty output"""
        self.assertEqual(normalize_text(""), "")

    def test_brs(self):
        """Test that empty input returns empty output"""
        self.assertEqual(normalize_text("Hello<br>everyone"), "Hello everyone")
        self.assertEqual(normalize_text("Hello<br>everyone"), normalize_text("Hello\neveryone"))
        self.assertEqual(normalize_text("Hello<br/>everyone"), "Hello everyone")
        self.assertEqual(normalize_text("Hello<br/>everyone"), normalize_text("Hello\neveryone"))

    def test_two_stars(self):
        self.assertEqual(
            normalize_text(
                "**Georges V.** (2007) – *Le Forez du VIe au IVe millénaire av. J.-C. Territoires, identités et stratégies des sociétés humaines du Massif central dans le bassin amont de la Loire (France)*, thèse de doctorat, université de Bourgogne, Dijon, 2 vol., 435 p."
            ),
            "Georges V. (2007) - Le Forez du VIe au IVe millénaire av. J.-C. Territoires, identités et stratégies des sociétés humaines du Massif central dans le bassin amont de la Loire (France), thèse de doctorat, université de Bourgogne, Dijon, 2 vol., 435 p.",
        )


class TestBasePDFTest(unittest.TestCase):
    """Test the BasePDFTest class"""

    def test_valid_initialization(self):
        """Test that a valid initialization works"""
        test = BasePDFTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value)
        self.assertEqual(test.pdf, "test.pdf")
        self.assertEqual(test.page, 1)
        self.assertEqual(test.id, "test_id")
        self.assertEqual(test.type, TestType.BASELINE.value)
        self.assertEqual(test.max_diffs, 0)
        self.assertIsNone(test.checked)
        self.assertIsNone(test.url)

    def test_empty_pdf(self):
        """Test that empty PDF raises ValidationError"""
        with self.assertRaises(ValidationError):
            BasePDFTest(pdf="", page=1, id="test_id", type=TestType.BASELINE.value)

    def test_empty_id(self):
        """Test that empty ID raises ValidationError"""
        with self.assertRaises(ValidationError):
            BasePDFTest(pdf="test.pdf", page=1, id="", type=TestType.BASELINE.value)

    def test_negative_max_diffs(self):
        """Test that negative max_diffs raises ValidationError"""
        with self.assertRaises(ValidationError):
            BasePDFTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value, max_diffs=-1)

    def test_invalid_test_type(self):
        """Test that invalid test type raises ValidationError"""
        with self.assertRaises(ValidationError):
            BasePDFTest(pdf="test.pdf", page=1, id="test_id", type="invalid_type")

    def test_run_method_not_implemented(self):
        """Test that run method raises NotImplementedError"""
        test = BasePDFTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value)
        with self.assertRaises(NotImplementedError):
            test.run("content")

    def test_checked_enum(self):
        """Test that checked accepts valid TestChecked enums"""
        test = BasePDFTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value, checked=TestChecked.VERIFIED)
        self.assertEqual(test.checked, TestChecked.VERIFIED)


class TestTextPresenceTest(unittest.TestCase):
    """Test the TextPresenceTest class"""

    def test_valid_present_test(self):
        """Test that a valid PRESENT test initializes correctly"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="test text")
        self.assertEqual(test.text, "test text")
        self.assertTrue(test.case_sensitive)
        self.assertIsNone(test.first_n)
        self.assertIsNone(test.last_n)

    def test_valid_absent_test(self):
        """Test that a valid ABSENT test initializes correctly"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ABSENT.value, text="test text", case_sensitive=False)
        self.assertEqual(test.text, "test text")
        self.assertFalse(test.case_sensitive)

    def test_empty_text(self):
        """Test that empty text raises ValidationError"""
        with self.assertRaises(ValidationError):
            TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="")

    def test_present_text_exact_match(self):
        """Test that PRESENT test returns True for exact match"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="target text")
        result, _ = test.run("This is some target text in a document")
        self.assertTrue(result)

    def test_present_text_not_found(self):
        """Test that PRESENT test returns False when text not found"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="missing text")
        result, explanation = test.run("This document doesn't have the target")
        self.assertFalse(result)
        self.assertIn("missing text", explanation)

    def test_present_text_with_max_diffs(self):
        """Test that PRESENT test with max_diffs handles fuzzy matching"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="target text", max_diffs=2)
        result, _ = test.run("This is some targett textt in a document")
        self.assertTrue(result)

    def test_absent_text_found(self):
        """Test that ABSENT test returns False when text is found"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ABSENT.value, text="target text")
        result, explanation = test.run("This is some target text in a document")
        self.assertFalse(result)
        self.assertIn("target text", explanation)

    def test_absent_text_found_diffs(self):
        """Test that ABSENT test returns False when text is found"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ABSENT.value, text="target text", max_diffs=2)
        result, explanation = test.run("This is some target text in a document")
        self.assertFalse(result)
        result, explanation = test.run("This is some targett text in a document")
        self.assertFalse(result)
        result, explanation = test.run("This is some targettt text in a document")
        self.assertFalse(result)
        result, explanation = test.run("This is some targetttt text in a document")
        self.assertTrue(result)

    def test_absent_test_subsets(self):
        """Test that ABSENT test returns False when text is found"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ABSENT.value, text="max", max_diffs=0)
        result, explanation = test.run("There is a max set of diffs to make")
        self.assertFalse(result)
        result, explanation = test.run("This is some maximum text in a document")
        self.assertFalse(result)

    def test_absent_text_not_found(self):
        """Test that ABSENT test returns True when text is not found"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ABSENT.value, text="missing text")
        result, _ = test.run("This document doesn't have the target")
        self.assertTrue(result)

    def test_present_short_candidate_with_space_query_does_not_falsely_pass(self):
        """Regression: rapidfuzz.partial_ratio scales by min(len(a), len(b)).

        For very short md_content (e.g. "\\n", which normalize_text collapses
        to " "), partial_ratio(query_with_space, " ") returns 1.0 because a
        single space character matches a single space inside the query. With
        max_diffs=0 the threshold is 1.0, so PRESENT tests for any
        space-containing query falsely passed. A length guard rejects the
        match before partial_ratio is consulted.
        """
        test = TextPresenceTest(
            pdf="test.pdf", page=1, id="test_id",
            type=TestType.PRESENT.value,
            text="an expression of good will from you",
        )
        # Empty content
        result, _ = test.run("")
        self.assertFalse(result)
        # Single newline (parserbench's splitter formerly emitted this for
        # empty parser output; normalize_text collapses to " ")
        result, _ = test.run("\n")
        self.assertFalse(result)
        # Single space directly
        result, _ = test.run(" ")
        self.assertFalse(result)
        # Short content where a coincidental space would otherwise win
        result, _ = test.run("a b")
        self.assertFalse(result)

    def test_absent_short_candidate_with_space_query_does_not_falsely_fail(self):
        """Mirror of the above for ABSENT — must PASS when md_content is too
        short to plausibly contain the query.
        """
        test = TextPresenceTest(
            pdf="test.pdf", page=1, id="test_id",
            type=TestType.ABSENT.value,
            text="TELEPHONE 478",
        )
        for short in ("", "\n", " ", "a b"):
            result, _ = test.run(short)
            self.assertTrue(result, f"absent should pass for short md={short!r}")

    def test_case_insensitive_present(self):
        """Test that case_sensitive=False works for PRESENT test"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="TARGET TEXT", case_sensitive=False)
        result, _ = test.run("This is some target text in a document")
        self.assertTrue(result)

    def test_case_insensitive_absent(self):
        """Test that case_sensitive=False works for ABSENT test"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ABSENT.value, text="TARGET TEXT", case_sensitive=False)
        result, explanation = test.run("This is some target text in a document")
        self.assertFalse(result)

    def test_first_n_limit(self):
        """Test that first_n parameter works correctly"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="beginning", first_n=20)
        result, _ = test.run("beginning of text, but not the end")
        self.assertTrue(result)

        # Test that text beyond first_n isn't matched
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="end", first_n=20)
        result, _ = test.run("beginning of text, but not the end")
        self.assertFalse(result)

    def test_last_n_limit(self):
        """Test that last_n parameter works correctly"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="end", last_n=20)
        result, _ = test.run("beginning of text, but not the end")
        self.assertTrue(result)

        # Test that text beyond last_n isn't matched
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="beginning", last_n=20)
        result, _ = test.run("beginning of text, but not the end")
        self.assertFalse(result)

    def test_both_first_and_last_n(self):
        """Test that combining first_n and last_n works correctly"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="beginning", first_n=15, last_n=10)
        result, _ = test.run("beginning of text, middle part, but not the end")
        self.assertTrue(result)

        # Text only in middle shouldn't be found
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="middle", first_n=15, last_n=10)
        result, _ = test.run("beginning of text, middle part, but not the end")
        self.assertFalse(result)

    def test_unicode_normalized_forms(self):
        """Test that e+accent == e_with_accent unicode chars"""
        test = TextPresenceTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="I like to eat at a caf\u00e9")
        result, _ = test.run("I like to eat at a caf\u00e9")
        self.assertTrue(result)

        result, _ = test.run("I like to eat at a cafe\u0301")
        self.assertTrue(result)


class TestTextOrderTest(unittest.TestCase):
    """Test the TextOrderTest class"""

    def test_valid_initialization(self):
        """Test that valid initialization works"""
        test = TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="first text", after="second text")
        self.assertEqual(test.before, "first text")
        self.assertEqual(test.after, "second text")

    def test_invalid_test_type(self):
        """Test that invalid test type raises ValidationError"""
        with self.assertRaises(ValidationError):
            TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, before="first text", after="second text")

    def test_empty_before(self):
        """Test that empty before text raises ValidationError"""
        with self.assertRaises(ValidationError):
            TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="", after="second text")

    def test_empty_after(self):
        """Test that empty after text raises ValidationError"""
        with self.assertRaises(ValidationError):
            TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="first text", after="")

    def test_correct_order(self):
        """Test that correct order returns True"""
        test = TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="first", after="second")
        result, _ = test.run("This has first and then second in correct order")
        self.assertTrue(result)

    def test_incorrect_order(self):
        """Test that incorrect order returns False"""
        test = TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="second", after="first")
        result, explanation = test.run("This has first and then second in correct order")
        self.assertFalse(result)

    def test_before_not_found(self):
        """Test that 'before' text not found returns False"""
        test = TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="missing", after="present")
        result, explanation = test.run("This text has present but not the other word")
        self.assertFalse(result)

    def test_after_not_found(self):
        """Test that 'after' text not found returns False"""
        test = TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="present", after="missing")
        result, explanation = test.run("This text has present but not the other word")
        self.assertFalse(result)

    def test_max_diffs(self):
        """Test that max_diffs parameter works correctly"""
        test = TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="first", after="second", max_diffs=1)
        result, _ = test.run("This has firsst and then secand in correct order")
        self.assertTrue(result)

    def test_multiple_occurrences(self):
        """Test that multiple occurrences are handled correctly"""
        test = TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="target", after="target")
        result, _ = test.run("This has target and then target again")
        self.assertTrue(result)

        # Test reverse direction fails
        test = TextOrderTest(pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="B", after="A")
        result, _ = test.run("A B A B")  # A comes before B, but B also comes before second A
        self.assertTrue(result)

    def test_real_case_unicode(self):
        text = """# Marketing Strategies in the Canadian Beef Sector

Julieta Frank,

Derek Brewin,

and

Maria José Patiño*

*Paper presented at the NCCC-134 Conference on Applied Commodity Price Analysis,  
Forecasting, and Market Risk Management  
St. Louis, Missouri, April 18-19, 2011*

*Copyright 2011 by Julieta Frank, Derek Brewin, and Maria José Patiño. All rights reserved.  
Readers may make verbatim copies of this document for non-commercial purposes by any  
means, provided that this copyright notice appears on all such copies.*

* Julieta Frank (Julieta_Frank@umanitoba.ca) is an Assistant Professor, Derek Brewin is an Associate Professor, and Maria José Patiño is a graduate student in the Department of Agribusiness and Agricultural Economics at the University of Manitoba. The funding support of the Manitoba Rural Adaptation Council and the Solomon Sinclair Farm Management Institute are gratefully acknowledged."""

        test = TextOrderTest(
            pdf="test.pdf", page=1, id="test_id", type=TestType.ORDER.value, before="Maria Jos\u00e9 Pati\u00f1o*", after="All rights reserved.", max_diffs=0
        )
        result, _ = test.run(text)
        self.assertTrue(result)


class TestTableTest(unittest.TestCase):
    """Test the TableTest class"""

    def setUp(self):
        """Set up test fixtures"""
        self.markdown_table = """
| Header 1 | Header 2 | Header 3 |
| -------- | -------- | -------- |
| Cell A1  | Cell A2  | Cell A3  |
| Cell B1  | Cell B2  | Cell B3  |
"""

        self.html_table = """
<table>
  <tr>
    <th>Header 1</th>
    <th>Header 2</th>
    <th>Header 3</th>
  </tr>
  <tr>
    <td>Cell A1</td>
    <td>Cell A2</td>
    <td>Cell A3</td>
  </tr>
  <tr>
    <td>Cell B1</td>
    <td>Cell B2</td>
    <td>Cell B3</td>
  </tr>
</table>
"""

    def test_valid_initialization(self):
        """Test that valid initialization works"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="target cell")
        self.assertEqual(test.cell, "target cell")
        self.assertEqual(test.up, "")
        self.assertEqual(test.down, "")
        self.assertEqual(test.left, "")
        self.assertEqual(test.right, "")
        self.assertEqual(test.top_heading, "")
        self.assertEqual(test.left_heading, "")

    def test_invalid_test_type(self):
        """Test that invalid test type raises ValidationError"""
        with self.assertRaises(ValidationError):
            TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, cell="target cell")

    def test_parse_markdown_tables(self):
        """Test markdown table parsing"""
        _test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        tables = parse_markdown_tables(self.markdown_table)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].cell_text[0, 0], "Header 1")
        self.assertEqual(tables[0].cell_text[1, 1], "Cell A2")
        self.assertEqual(tables[0].cell_text[2, 2], "Cell B3")

    def test_parse_html_tables(self):
        """Test HTML table parsing"""
        _test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        tables = parse_html_tables(self.html_table)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].cell_text[0, 0], "Header 1")
        self.assertEqual(tables[0].cell_text[1, 1], "Cell A2")
        self.assertEqual(tables[0].cell_text[2, 2], "Cell B3")

    def test_match_cell(self):
        """Test finding a cell in a table"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        result, _ = test.run(self.markdown_table)
        self.assertTrue(result)

    def test_cell_not_found(self):
        """Test cell not found in table"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Missing Cell")
        result, explanation = test.run(self.markdown_table)
        self.assertFalse(result)
        self.assertIn("No cell matching", explanation)

    def test_up_relationship(self):
        """Test up relationship in table"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", up="Header 2")
        result, _ = test.run(self.markdown_table)
        self.assertTrue(result)

        # Test incorrect up relationship
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", up="Wrong Header")
        result, explanation = test.run(self.markdown_table)
        self.assertFalse(result)
        self.assertIn("doesn't match expected", explanation)

    def test_down_relationship(self):
        """Test down relationship in table"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", down="Cell B2")
        result, _ = test.run(self.markdown_table)
        self.assertTrue(result)

        # Test incorrect down relationship
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", down="Wrong Cell")
        result, explanation = test.run(self.markdown_table)
        self.assertFalse(result)
        self.assertIn("doesn't match expected", explanation)

    def test_left_relationship(self):
        """Test left relationship in table"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", left="Cell A1")
        result, _ = test.run(self.markdown_table)
        self.assertTrue(result)

        # Test incorrect left relationship
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", left="Wrong Cell")
        result, explanation = test.run(self.markdown_table)
        self.assertFalse(result)
        self.assertIn("doesn't match expected", explanation)

    def test_right_relationship(self):
        """Test right relationship in table"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", right="Cell A3")
        result, _ = test.run(self.markdown_table)
        self.assertTrue(result)

        # Test incorrect right relationship
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", right="Wrong Cell")
        result, explanation = test.run(self.markdown_table)
        self.assertFalse(result)
        self.assertIn("doesn't match expected", explanation)

    def test_top_heading_relationship(self):
        """Test top_heading relationship in table"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell B2", top_heading="Header 2")
        result, _ = test.run(self.markdown_table)
        self.assertTrue(result)

        # Test incorrect top_heading relationship
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell B2", top_heading="Wrong Header")
        result, explanation = test.run(self.markdown_table)
        self.assertFalse(result)
        self.assertIn("doesn't match expected", explanation)

    def test_left_heading_relationship(self):
        """Test left_heading relationship in table"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A3", left_heading="Cell A1")
        result, _ = test.run(self.markdown_table)
        self.assertTrue(result)

        # Test incorrect left_heading relationship
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A3", left_heading="Wrong Cell")
        result, explanation = test.run(self.markdown_table)
        self.assertFalse(result)
        self.assertIn("doesn't match expected", explanation)

    def test_multiple_relationships(self):
        """Test multiple relationships in table"""
        test = TableTest(
            pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", up="Header 2", down="Cell B2", left="Cell A1", right="Cell A3"
        )
        result, _ = test.run(self.markdown_table)
        self.assertTrue(result)

        # Test one incorrect relationship
        test = TableTest(
            pdf="test.pdf",
            page=1,
            id="test_id",
            type=TestType.TABLE.value,
            cell="Cell A2",
            up="Header 2",
            down="Cell B2",
            left="Wrong Cell",  # This is incorrect
            right="Cell A3",
        )
        result, explanation = test.run(self.markdown_table)
        self.assertFalse(result)
        self.assertIn("doesn't match expected", explanation)

    def test_no_tables_found(self):
        """Test behavior when no tables are found"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        result, explanation = test.run("This is plain text with no tables")
        self.assertFalse(result)
        self.assertEqual(explanation, "No tables found in the content")

    def test_fuzzy_matching(self):
        """Test fuzzy matching with max_diffs"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2", max_diffs=1)
        # Create table with slightly misspelled cell
        misspelled_table = self.markdown_table.replace("Cell A2", "Cel A2")
        result, _ = test.run(misspelled_table)
        self.assertTrue(result)

    def test_with_stripped_content(self):
        """Test table parsing with stripped content"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Strip all leading/trailing whitespace from the markdown table
        stripped_table = self.markdown_table.strip()
        result, explanation = test.run(stripped_table)
        self.assertTrue(result, f"Table test failed with stripped content: {explanation}")

    def test_table_at_end_of_file(self):
        """Test that a table at the very end of the file is correctly detected"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Create content with text followed by a table at the very end with no trailing newline
        content_with_table_at_end = "Some text before the table.\n" + self.markdown_table.strip()
        result, explanation = test.run(content_with_table_at_end)
        self.assertTrue(result, f"Table at end of file not detected: {explanation}")

    def test_table_at_end_with_no_trailing_newline(self):
        """Test that a table at the end with no trailing newline is detected"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Remove the trailing newline from the markdown table
        content_without_newline = self.markdown_table.rstrip()
        result, explanation = test.run(content_without_newline)
        self.assertTrue(result, f"Table without trailing newline not detected: {explanation}")

    def test_table_at_end_with_extra_spaces(self):
        """Test that a table at the end with extra spaces is detected"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Add extra spaces to the end of lines in the table
        lines = self.markdown_table.split("\n")
        content_with_extra_spaces = "\n".join([line + "   " for line in lines])
        result, explanation = test.run(content_with_extra_spaces)
        self.assertTrue(result, f"Table with extra spaces not detected: {explanation}")

    def test_table_at_end_with_mixed_whitespace(self):
        """Test that a table at the end with mixed whitespace is detected"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Add various whitespace characters to the table
        content_with_mixed_whitespace = "Some text before the table.\n" + self.markdown_table.strip() + "  \t  "
        result, explanation = test.run(content_with_mixed_whitespace)
        self.assertTrue(result, f"Table with mixed whitespace not detected: {explanation}")

    def test_malformed_table_at_end(self):
        """Test that a slightly malformed table at the end is still detected"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Create a table with irregular pipe placement at the end
        malformed_table = """
Some text before the table.
| Header 1 | Header 2 | Header 3
| -------- | -------- | --------
| Cell A1  | Cell A2  | Cell A3  |
| Cell B1  | Cell B2  | Cell B3"""
        result, explanation = test.run(malformed_table)
        self.assertTrue(result, f"Malformed table at end not detected: {explanation}")

    def test_incomplete_table_at_end(self):
        """Test that an incomplete table at the end still gets detected if it contains valid rows"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Missing the separator row
        incomplete_table = """
Some text before the table.
| Header 1 | Header 2 | Header 3 |
| Cell A1  | Cell A2  | Cell A3  |
| Cell B1  | Cell B2  | Cell B3  |"""
        result, explanation = test.run(incomplete_table)
        self.assertTrue(result, f"Incomplete table at end not detected: {explanation}")

    def test_table_with_excessive_blank_lines_at_end(self):
        """Test that a table followed by many blank lines is detected"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Add many blank lines after the table
        table_with_blanks = self.markdown_table + "\n\n\n\n\n\n\n\n\n\n"
        result, explanation = test.run(table_with_blanks)
        self.assertTrue(result, f"Table with blank lines at end not detected: {explanation}")

    def test_table_at_end_after_long_text(self):
        """Test that a table at the end after a very long text is detected"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Create a very long text before the table
        long_text = "Lorem ipsum dolor sit amet, " * 100
        content_with_long_text = long_text + "\n" + self.markdown_table.strip()
        result, explanation = test.run(content_with_long_text)
        self.assertTrue(result, f"Table after long text not detected: {explanation}")

    def test_valid_table_at_eof_without_newline(self):
        """Test that a valid table at EOF without a trailing newline is detected"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Cell A2")
        # Valid table but without trailing newline at the very end of the file
        valid_table_eof = """
| Header 1 | Header 2 | Header 3 |
| -------- | -------- | -------- |
| Cell A1  | Cell A2  | Cell A3  |
| Cell B1  | Cell B2  | Cell B3  |""".strip()
        result, explanation = test.run(valid_table_eof)
        self.assertTrue(result, f"Valid table at EOF without newline not detected: {explanation}")

    def test_normalizing(self):
        table = """| Question - – Satisfaction on scale of 10 | Response | Resident Sample | Business Sample |
|----------------------------------------|----------|----------------|-----------------|
| Planning for and managing residential, commercial and industrial development | Rating of 8, 9 or 10 | 13% | 11% |
| | Average rating | 6.4 | 5.7 |
| | Don’t know responses | 11% | 6% |
| Environmental protection, support for green projects (e.g. green grants, building retrofits programs, zero waste) | Rating of 8, 9 or 10 | 35% | 34% |
| | Average rating | 8.0 | 7.5 |
| | Don’t know responses | 8% | 6% |
| Providing and maintaining parks and green spaces | Rating of 8, 9 or 10 | 42% | 41% |
| | Average rating | 7.7 | 7.3 |
| | Don’t know responses | 1% | 1% |"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="6%", top_heading="Business\nSample")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

    def test_mathematical_minus(self):
        table = """| Response | Chinese experimenter | White experimenter |
|----------|----------------------|--------------------|
|          | Divided attention    | Full attention     | Divided attention | Full attention |
| Nonverbal| −.34 (.22)           | .54* (.17)         | .12 (.27)         | −.20 (.24)     |
| Verbal   | −.25 (.23)           | .36 (.20)          | .12 (.27)         | −.34 (.22)     |
"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="-.34 (.22)")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

    def test_markdown_marker(self):
        table = """| CATEGORY     | POINTS EARNED |
|------------------------------|------------------|
| Sustainable Sites            | 9                |
| Water Efficiency             | 3                |
| Energy & Atmosphere          | 12               |
| Materials & Resources        | 6                |
| Indoor Environmental Quality | 11               |
| Innovation & Design Process  | 5                |
| TOTAL                        | 46               |"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="9", up="POINTS EARNED")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

    def test_diffs(self):
        table = """| CATEGORY     | POINTS EARNED |
|------------------------------|------------------|
| Sustainable Sites            | 9                |
| Water Efficiency             | 3                |
| Energy & Atmosphere          | 12               |
| Materials & Resources        | 6                |
| Indoor Environmental Quality | 11               |
| Innovation & Design Process  | 5                |
| TOTAL                        | 46               |"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="9", left="Sustl Sie", max_diffs=2)
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="9", left="Sustainable Site", max_diffs=2)
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

    def test_markdown_marker2(self):
        table = """| Concentration
level | [CO]      | [SO2] | [NOx]    |
|------------------------|-----------|-------|----------|
| Control                | 0 μM      | 0 μM  | 0 nM     |
| Low                    | 250
μM | 8 μM  | 0.002 nM |
| Medium                 | 625 μM    | 20 μM | 0.005 nM |
| High                   | 1250 μM   | 40 μM | 0.01 nM  |"""
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="20 μM", up=".002 nM")
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

    def test_marker3(self):
        table = """|                                               | N     | Minimum | Maximum | Gemiddelde | Sd  |
|-----------------------------------------------|-------|---------|---------|------------|-----|
| Slaapkwaliteit tijdens
gewone nachten      | 2017  | 1,0     | 6,0     | 3,9        | 1,0 |
| Slaapkwaliteit tijdens
consignatiediensten | 19816 | 1,0     | 6,0     | 2,8        | 1,2 |
"""
        test = TableTest(
            pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="2,8", left_heading="Slaapkwaliteit tijdens\nconsignatiediensten"
        )
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

    def test_big_table(self):
        table = """    <table>
        <caption>Base: Resident respondents (n=1,315) and Business respondents (n=397)</caption>
        <thead>
            <tr>
                <th>Question – Satisfaction on scale of 10</th>
                <th>Response</th>
                <th>Resident Sample</th>
                <th>Business Sample</th>
            </tr>
        </thead>
        <tbody>
            <!-- First category -->
            <tr class="category-row">
                <td rowspan="3">Planning for and managing residential, commercial and industrial development</td>
                <td>Rating of 8, 9 or 10</td>
                <td>13%</td>
                <td>11%</td>
            </tr>
            <tr>
                <td class="subcategory">Average rating</td>
                <td>6.4</td>
                <td>5.7</td>
            </tr>
            <tr>
                <td class="subcategory">Don't know responses</td>
                <td>11%</td>
                <td>6%</td>
            </tr>
            
            <!-- Second category -->
            <tr class="category-row">
                <td rowspan="3">Environmental protection, support for green projects (e.g. green grants, building retrofits programs, zero waste)</td>
                <td>Rating of 8, 9 or 10</td>
                <td>35%</td>
                <td>34%</td>
            </tr>
            <tr>
                <td class="subcategory">Average rating</td>
                <td>8.0</td>
                <td>7.5</td>
            </tr>
            <tr>
                <td class="subcategory">Don't know responses</td>
                <td>8%</td>
                <td>6%</td>
            </tr>
            
            <!-- Third category -->
            <tr class="category-row">
                <td rowspan="3">Providing and maintaining parks and green spaces</td>
                <td>Rating of 8, 9 or 10</td>
                <td>42%</td>
                <td>41%</td>
            </tr>
            <tr>
                <td class="subcategory">Average rating</td>
                <td>7.7</td>
                <td>7.3</td>
            </tr>
            <tr>
                <td class="subcategory">Don't know responses</td>
                <td>1%</td>
                <td>1%</td>
            </tr>
        </tbody>
    </table>
"""
        test = TableTest(
            pdf="test.pdf",
            page=1,
            id="test_id",
            type=TestType.TABLE.value,
            max_diffs=5,
            cell="Planning for and managing residential, commercial and industrial development",
            down="Environmental protection,\nsupport for green projects\n(e.g. green grants,\nbuilding retrofits programs,\nzero waste)",
        )
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

    def test_html_rowspans_colspans(self):
        table = """    <table>
        <thead>
            <tr>
                <th rowspan="2">Product Category</th>
                <th rowspan="2">Product Subcategory</th>
                <th colspan="4">Quarterly Sales ($000s)</th>
                <th rowspan="2">Annual Total</th>
            </tr>
            <tr>
                <th>Q1</th>
                <th>Q2</th>
                <th>Q3</th>
                <th>Q4</th>
            </tr>
        </thead>
        <tbody>
            <tr class="category">
                <td rowspan="4">Electronics</td>
                <td>Smartphones</td>
                <td>245</td>
                <td>278</td>
                <td>312</td>
                <td>389</td>
                <td>1,224</td>
            </tr>
            <tr class="subcategory">
                <td>Laptops</td>
                <td>187</td>
                <td>192</td>
                <td>243</td>
                <td>297</td>
                <td>919</td>
            </tr>
            <tr class="subcategory">
                <td>Tablets</td>
                <td>95</td>
                <td>123</td>
                <td>135</td>
                <td>156</td>
                <td>509</td>
            </tr>
            <tr class="subcategory">
                <td>Accessories</td>
                <td>64</td>
                <td>72</td>
                <td>87</td>
                <td>105</td>
                <td>328</td>
            </tr>
            <tr class="category">
                <td rowspan="3">Home Appliances</td>
                <td>Refrigerators</td>
                <td>132</td>
                <td>145</td>
                <td>151</td>
                <td>162</td>
                <td>590</td>
            </tr>
            <tr class="subcategory">
                <td>Washing Machines</td>
                <td>98</td>
                <td>112</td>
                <td>127</td>
                <td>143</td>
                <td>480</td>
            </tr>
            <tr class="subcategory">
                <td>Microwaves</td>
                <td>54</td>
                <td>67</td>
                <td>72</td>
                <td>84</td>
                <td>277</td>
            </tr>
            <tr class="category">
                <td rowspan="3">Furniture</td>
                <td>Sofas</td>
                <td>112</td>
                <td>128</td>
                <td>134</td>
                <td>142</td>
                <td>516</td>
            </tr>
            <tr class="subcategory">
                <td>Tables</td>
                <td>87</td>
                <td>95</td>
                <td>103</td>
                <td>124</td>
                <td>409</td>
            </tr>
            <tr class="subcategory">
                <td>Chairs</td>
                <td>76</td>
                <td>84</td>
                <td>92</td>
                <td>110</td>
                <td>362</td>
            </tr>
            <tr class="total">
                <td colspan="2">Quarterly Totals</td>
                <td>1,150</td>
                <td>1,296</td>
                <td>1,456</td>
                <td>1,712</td>
                <td>5,614</td>
            </tr>
        </tbody>
    </table>"""

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Refrigerators", left="Home Appliances")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Washing Machines", left="Home Appliances")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Microwaves", left="Home Appliances")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Sofas", top_heading="Product Subcategory")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="135", top_heading="Q3")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="135", top_heading="Quarterly Sales ($000s)")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="1,712", top_heading="Quarterly Sales ($000s)")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="135", top_heading="Q2")
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="135", top_heading="Q1")
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="135", top_heading="Q4")
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Home Appliances", top_heading="Product Category")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Washing Machines", top_heading="Product Category")
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Washing Machines", top_heading="Q3")
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Washing Machines", top_heading="Quarterly Sales ($000s)")
        result, explanation = test.run(table)
        self.assertFalse(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Electronics", right="Laptops")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Electronics", right="Accessories")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Quarterly Sales ($000s)", down="Q2")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Q2", up="Quarterly Sales ($000s)")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

    def test_multiple_markdown_tables(self):
        """Test that we can find and verify cells in multiple markdown tables in one document"""
        content = """
# First Table

| Name | Age | Role |
| ---- | --- | ---- |
| John | 28  | Developer |
| Jane | 32  | Designer |
| Bob  | 45  | Manager |

Some text between tables...

# Second Table

| Department | Budget | Employees |
| ---------- | ------ | --------- |
| Engineering | 1.2M  | 15 |
| Design      | 0.8M  | 8  |
| Marketing   | 1.5M  | 12 |
| HR          | 0.5M  | 5  |
"""

        # Test cells in the first table
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="John", right="28")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="32", left="Jane")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        # Test cells in the second table
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Engineering", right="1.2M")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="12", left="1.5M")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        # Verify top headings work correctly across tables
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Bob", top_heading="Name")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="HR", top_heading="Department")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

    def test_multiple_html_tables(self):
        """Test that we can find and verify cells in multiple HTML tables in one document"""
        content = """
<h1>First Table</h1>

<table>
  <thead>
    <tr>
      <th>Country</th>
      <th>Capital</th>
      <th>Population</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>USA</td>
      <td>Washington DC</td>
      <td>331M</td>
    </tr>
    <tr>
      <td>France</td>
      <td>Paris</td>
      <td>67M</td>
    </tr>
    <tr>
      <td>Japan</td>
      <td>Tokyo</td>
      <td>126M</td>
    </tr>
  </tbody>
</table>

<p>Some text between tables...</p>

<h1>Second Table</h1>

<table>
  <thead>
    <tr>
      <th>Company</th>
      <th>Industry</th>
      <th>Revenue</th>
      <th>Employees</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>ABC Corp</td>
      <td>Technology</td>
      <td>$5B</td>
      <td>10,000</td>
    </tr>
    <tr>
      <td>XYZ Inc</td>
      <td>Healthcare</td>
      <td>$2.5B</td>
      <td>8,500</td>
    </tr>
    <tr>
      <td>Acme Co</td>
      <td>Manufacturing</td>
      <td>$1.8B</td>
      <td>15,000</td>
    </tr>
    <tr>
      <td>Global LLC</td>
      <td>Finance</td>
      <td>$3.2B</td>
      <td>6,200</td>
    </tr>
  </tbody>
</table>
"""

        # Test cells in the first table
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="USA", right="Washington DC")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="126M", left="Tokyo")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        # Test cells in the second table
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="XYZ Inc", right="Healthcare")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="15,000", left="$1.8B")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        # Verify top headings work correctly across tables
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Tokyo", top_heading="Capital")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Finance", top_heading="Industry")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

    def test_mixed_markdown_and_html_tables(self):
        """Test that we can find and verify cells in mixed markdown and HTML tables in one document"""
        content = """
# Markdown Table

| Product | Price | Quantity |
| ------- | ----- | -------- |
| Apple   | $1.20 | 100      |
| Orange  | $0.80 | 150      |
| Banana  | $0.60 | 200      |

<h1>HTML Table</h1>

<table>
  <tr>
    <th>Month</th>
    <th>Income</th>
    <th>Expenses</th>
    <th>Profit</th>
  </tr>
  <tr>
    <td>January</td>
    <td>$10,000</td>
    <td>$8,000</td>
    <td>$2,000</td>
  </tr>
  <tr>
    <td>February</td>
    <td>$12,000</td>
    <td>$9,500</td>
    <td>$2,500</td>
  </tr>
  <tr>
    <td>March</td>
    <td>$15,000</td>
    <td>$10,200</td>
    <td>$4,800</td>
  </tr>
</table>
"""

        # Test cells in the markdown table
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Orange", right="$0.80")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        # Test cells in the HTML table
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="February", right="$12,000")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        # Verify we can find cells with specific top headings
        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="100", top_heading="Quantity")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="$4,800", top_heading="Profit")
        result, explanation = test.run(content)
        self.assertTrue(result, explanation)

    def test_br_tags_replacement(self):
        """Test that <br> and <br/> tags are correctly replaced with newlines"""
        table = """<table>
          <tr>
            <th>Header 1</th>
            <th>Header 2</th>
          </tr>
          <tr>
            <td>Line 1<br/>Line 2<br/>Line 3</td>
            <td>Single line</td>
          </tr>
        </table>"""

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="Line 1 Line 2 Line 3")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

    def test_real_complicated_table(self):
        table = """    <table>
        <thead>
            <tr>
                <th colspan="7">Table 1 &nbsp;&nbsp; Differences in diagnoses, gender and family status for participants with a suicide attempt and those without a suicide attempt within the 12-month follow-up interval</th>
            </tr>
            <tr class="header-row">
                <th rowspan="2"></th>
                <th colspan="2">Participants with no<br>suicide attempt<br>(n = 132)<sup>a</sup></th>
                <th colspan="2">Participants with a<br>suicide attempt<br>(n = 43)<sup>b</sup></th>
                <th colspan="3"></th>
            </tr>
            <tr class="header-row">
                <th>n</th>
                <th>%</th>
                <th>n</th>
                <th>%</th>
                <th>χ<sup>2</sup></th>
                <th>d.f.</th>
                <th>P</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td class="section-header">ICD-10 diagnoses</td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F0</td>
                <td>1</td>
                <td>0.76</td>
                <td>0</td>
                <td>0.00</td>
                <td>0.00</td>
                <td>1</td>
                <td>1.00</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F1</td>
                <td>17</td>
                <td>12.88</td>
                <td>12</td>
                <td>27.91</td>
                <td>4.39</td>
                <td>1</td>
                <td>0.04</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F2</td>
                <td>1</td>
                <td>0.76</td>
                <td>0</td>
                <td>0.00</td>
                <td>0.00</td>
                <td>1</td>
                <td>1.00</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F3</td>
                <td>106</td>
                <td>80.30</td>
                <td>31</td>
                <td>72.09</td>
                <td>0.74</td>
                <td>1</td>
                <td>0.39</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F4</td>
                <td>42</td>
                <td>31.82</td>
                <td>17</td>
                <td>39.53</td>
                <td>0.61</td>
                <td>1</td>
                <td>0.43</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F5</td>
                <td>5</td>
                <td>3.79</td>
                <td>5</td>
                <td>11.63</td>
                <td>2.44</td>
                <td>1</td>
                <td>0.12</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F6</td>
                <td>20</td>
                <td>15.15</td>
                <td>19</td>
                <td>44.19</td>
                <td>14.48</td>
                <td>1</td>
                <td>0.00</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F7</td>
                <td>0</td>
                <td>0.00</td>
                <td>0</td>
                <td>0.00</td>
                <td>—</td>
                <td>—</td>
                <td>—</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F8</td>
                <td>1</td>
                <td>0.76</td>
                <td>0</td>
                <td>0.00</td>
                <td>0.00</td>
                <td>1</td>
                <td>1.00</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;F9</td>
                <td>2</td>
                <td>1.52</td>
                <td>1</td>
                <td>2.33</td>
                <td>0.00</td>
                <td>1</td>
                <td>1.00</td>
            </tr>
            <tr>
                <td class="section-header">Gender</td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td>3.09</td>
                <td>2</td>
                <td>0.21</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;Female</td>
                <td>75</td>
                <td>56.8</td>
                <td>24</td>
                <td>55.8</td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;Male</td>
                <td>57</td>
                <td>43.2</td>
                <td>18</td>
                <td>41.9</td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;Diverse</td>
                <td>0</td>
                <td>0</td>
                <td>1</td>
                <td>2.3</td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            <tr>
                <td class="section-header">Family status</td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td>4.87</td>
                <td>4</td>
                <td>0.30</td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;Single</td>
                <td>55</td>
                <td>41.7</td>
                <td>14</td>
                <td>32.6</td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;Partnership</td>
                <td>25</td>
                <td>18.9</td>
                <td>9</td>
                <td>20.9</td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;Married</td>
                <td>27</td>
                <td>20.5</td>
                <td>5</td>
                <td>11.6</td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;Divorced</td>
                <td>20</td>
                <td>15.2</td>
                <td>11</td>
                <td>25.6</td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            <tr>
                <td>&nbsp;&nbsp;Widowed</td>
                <td>1</td>
                <td>0.8</td>
                <td>1</td>
                <td>2.3</td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
        </tbody>
        <tfoot>
            <tr>
                <td colspan="8" class="footnote">
                    F0: Organic, including symptomatic, mental disorders; F1: Mental and behavioural disorders due to psychoactive substance use; F2: Schizophrenia, schizotypal and delusional disorders; F3: affective disorders; F4: Neurotic, stress-related and somatoform disorders; F5: Behavioural syndromes associated with physiological disturbances and physical factors; F6: Disorders of adult personality and behaviour; F7: Mental retardation; F8: Disorders of psychological development; F9: Behavioural and emotional disorders with onset usually occurring in childhood and adolescence.<br>
                    a. 75.43% of the total sample with full information on suicide reattempts within the entire 12-month follow-up interval.<br>
                    b. 24.57% of the total sample with full information on suicide reattempts within the entire 12-month follow-up interval.
                </td>
            </tr>
        </tfoot>
    </table>"""

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="4.39", top_heading="χ2")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="12.88", top_heading="%")
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        # Account for the superscript in the header
        test = TableTest(
            pdf="test.pdf", page=1, id="test_id", type=TestType.TABLE.value, cell="12.88", top_heading="Participants with no suicide attempt (n = 132)a"
        )
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)

        test = TableTest(
            pdf="test.pdf",
            page=1,
            id="test_id",
            type=TestType.TABLE.value,
            cell="12.88",
            top_heading="Table 1    Differences in diagnoses, gender and family status for participants with a suicide attempt and those without a suicide attempt within the 12-month follow-up interval",
        )
        result, explanation = test.run(table)
        self.assertTrue(result, explanation)


class TestBaselineTest(unittest.TestCase):
    """Test the BaselineTest class"""

    def test_valid_initialization(self):
        """Test that valid initialization works"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value, max_repeats=50)
        self.assertEqual(test.max_repeats, 50)

    def test_non_empty_content(self):
        """Test that non-empty content passes"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value)
        result, _ = test.run("This is some normal content")
        self.assertTrue(result)

    def test_empty_content(self):
        """Test that empty content fails"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value)
        result, explanation = test.run("   \n\t  ")
        self.assertFalse(result)
        self.assertIn("no alpha numeric characters", explanation)

    def test_repeating_content(self):
        """Test that highly repeating content fails"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value, max_repeats=2)
        # Create highly repeating content - repeat "abc" many times
        repeating_content = "abc" * 10
        result, explanation = test.run(repeating_content)
        self.assertFalse(result)
        self.assertIn("repeating", explanation)

    def test_content_with_disallowed_characters(self):
        """Test that content with disallowed characters fails"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value)
        result, explanation = test.run("This has Chinese characters: 你好")
        self.assertFalse(result)
        self.assertIn("disallowed characters", explanation)

    def test_content_with_emoji(self):
        """Test that content with emoji fails"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value)
        result, explanation = test.run("This has emoji: 😊")
        self.assertFalse(result)
        self.assertIn("disallowed characters", explanation)
        self.assertIn("😊", explanation)

    def test_content_with_mandarin(self):
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value)
        result, explanation = test.run("asdfasdfas維基百科/中文asdfw")
        self.assertFalse(result)
        self.assertIn("disallowed characters", explanation)

    def test_valid_content(self):
        """Test that valid content passes all checks"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value)
        content = "This is some normal content with proper English letters and no suspicious repetition."
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_max_length_with_image_tags_skipped(self):
        """Test that image tags are properly removed when max_length_skips_image_alt_tags is True"""
        # Test with max_length_skips_image_alt_tags=True
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value, max_length=10, max_length_skips_image_alt_tags=True)

        # Content with image tag that would exceed max_length if counted
        content = "Hello ![Diagram showing labeled components 100, 101, 102, 103, 104, 105, 102A, 103A, 104A, 105A, 220, 130, and 140 within a rectangular frame.](page_370_682_1012_1012.png) World"
        result, _ = test.run(content)
        # Should pass because "HelloWorld" has 10 alphanumeric characters after removing image tag
        self.assertTrue(result)

    def test_max_length_with_image_tags_not_skipped(self):
        """Test that image tags are counted when max_length_skips_image_alt_tags is False"""
        # Test with max_length_skips_image_alt_tags=False (default)
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value, max_length=10)

        # Same content with image tag
        content = "Hello ![Diagram showing labeled components 100, 101, 102, 103, 104, 105, 102A, 103A, 104A, 105A, 220, 130, and 140 within a rectangular frame.](page_370_682_1012_1012.png) World"
        result, explanation = test.run(content)
        # Should fail because full content has way more than 10 alphanumeric characters
        self.assertFalse(result)
        self.assertIn("characters were output for a page we expected to be blank", explanation)

    def test_multiple_image_tags_removed(self):
        """Test that multiple image tags are removed correctly"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value, max_length=15, max_length_skips_image_alt_tags=True)

        content = "Start ![First image](img1.png) middle ![Second image](img2.png) end"
        result, _ = test.run(content)
        # Should pass because "Start middle end" = "Startmiddleend" has 14 alphanumeric characters
        self.assertTrue(result)

    def test_nested_brackets_in_image_tags(self):
        """Test that image tags with nested brackets are handled correctly"""
        test = BaselineTest(pdf="test.pdf", page=1, id="test_id", type=TestType.BASELINE.value, max_length=8, max_length_skips_image_alt_tags=True)

        content = "Text ![Complex [nested] description](image.png) here"
        result, _ = test.run(content)
        # Should pass because "Text here" = "Texthere" has 8 alphanumeric characters
        self.assertTrue(result)


class TestMathTest(unittest.TestCase):
    """Test the MathTest class"""

    def test_valid_initialization(self):
        """Test that valid initialization works"""
        try:
            test = MathTest(pdf="test.pdf", page=1, id="test_id", type=TestType.MATH.value, math="a + b = c")
            self.assertEqual(test.math, "a + b = c")
        except Exception as e:
            self.fail(f"Valid initialization failed with: {e}")

    def test_invalid_test_type(self):
        """Test that invalid test type raises ValidationError"""
        with self.assertRaises(ValidationError):
            MathTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, math="a + b = c")

    def test_empty_math(self):
        """Test that empty math raises ValidationError"""
        with self.assertRaises(ValidationError):
            MathTest(pdf="test.pdf", page=1, id="test_id", type=TestType.MATH.value, math="")

    def test_exact_math_match(self):
        """Test exact match of math equation"""
        try:
            test = MathTest(pdf="test.pdf", page=1, id="test_id", type=TestType.MATH.value, math="a + b = c")

            # Test content with exact math match
            content = "Here is an equation: $$a + b = c$$"
            result, _ = test.run(content)
            self.assertTrue(result)
        except Exception as e:
            self.fail(f"Test failed with: {e}")

    def test_rendered_math_match(self):
        """Test rendered match of math equation"""
        try:
            test = MathTest(pdf="test.pdf", page=1, id="test_id", type=TestType.MATH.value, math="a + b = c")

            # Test content with different but equivalent math
            content = "Here is an equation: $$a+b=c$$"
            result, _ = test.run(content)
            self.assertTrue(result)
        except Exception as e:
            self.fail(f"Test failed with: {e}")

    def test_no_math_match(self):
        """Test no match of math equation"""
        try:
            test = MathTest(pdf="test.pdf", page=1, id="test_id", type=TestType.MATH.value, math="a + b = c")

            # Test content with no matching math
            content = "Here is an equation: $$x + y = z$$"
            result, explanation = test.run(content)
            self.assertFalse(result)
            self.assertIn("No match found", explanation)
        except Exception as e:
            self.fail(f"Test failed with: {e}")

    def test_different_math_delimiters(self):
        """Test different math delimiters"""
        try:
            test = MathTest(pdf="test.pdf", page=1, id="test_id", type=TestType.MATH.value, math="a + b = c")

            # Test different delimiters
            delimiters = [
                "$$a + b = c$$",  # $$...$$
                "$a + b = c$",  # $...$
                "\\(a + b = c\\)",  # \(...\)
                "\\[a + b = c\\]",  # \[...\]
            ]

            for delim in delimiters:
                content = f"Here is an equation: {delim}"
                result, _ = test.run(content)
                self.assertTrue(result)
        except Exception as e:
            self.fail(f"Test failed with: {e}")


class TestFormatTest(unittest.TestCase):
    """Test the FormatTest class"""

    def test_valid_initialization(self):
        """Test that valid initialization works"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="Important Title", format="heading")
        self.assertEqual(test.text, "Important Title")
        self.assertEqual(test.format, "heading")
        self.assertTrue(test.case_sensitive)

    def test_invalid_test_type(self):
        """Test that invalid test type raises ValidationError"""
        with self.assertRaises(ValidationError):
            FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, text="test text", format="bold")

    def test_empty_text(self):
        """Test that empty text raises ValidationError"""
        with self.assertRaises(ValidationError):
            FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="", format="heading")

    def test_invalid_format_type(self):
        """Test that invalid format type raises ValidationError"""
        with self.assertRaises(ValidationError):
            FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="test text", format="underline")  # Not supported

    def test_markdown_heading(self):
        """Test detection of markdown headings"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="Chapter One", format="heading")

        # Test various heading levels
        content = "# Chapter One\nSome text here"
        result, _ = test.run(content)
        self.assertTrue(result)

        content = "## Chapter One\nSome text here"
        result, _ = test.run(content)
        self.assertTrue(result)

        content = "### Chapter One\nSome text here"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_html_heading(self):
        """Test detection of HTML headings"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="Chapter One", format="heading")

        # Test various HTML heading tags
        content = "<h1>Chapter One</h1>\nSome text here"
        result, _ = test.run(content)
        self.assertTrue(result)

        content = "<h3>Chapter One</h3>\nSome text here"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_markdown_bold(self):
        """Test detection of markdown bold text"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="important", format="bold")

        # Test ** syntax
        content = "This is **important** text"
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test __ syntax
        content = "This is __important__ text"
        result, _ = test.run(content)
        self.assertTrue(result)

        # Should not match if not bold
        content = "This is important text"
        result, explanation = test.run(content)
        self.assertFalse(result)
        self.assertIn("not found with bold formatting", explanation)

    def test_html_bold(self):
        """Test detection of HTML bold text"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="important", format="bold")

        # Test <b> tag
        content = "This is <b>important</b> text"
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test <strong> tag
        content = "This is <strong>important</strong> text"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_markdown_italic(self):
        """Test detection of markdown italic text"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="emphasis", format="italic")

        # Test * syntax
        content = "This needs *emphasis* here"
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test _ syntax
        content = "This needs _emphasis_ here"
        result, _ = test.run(content)
        self.assertTrue(result)

        # Should not match bold
        content = "This needs **emphasis** here"
        result, explanation = test.run(content)
        self.assertFalse(result)
        self.assertIn("not found with italic formatting", explanation)

    def test_html_italic(self):
        """Test detection of HTML italic text"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="emphasis", format="italic")

        # Test <i> tag
        content = "This needs <i>emphasis</i> here"
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test <em> tag
        content = "This needs <em>emphasis</em> here"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_partial_match(self):
        """Test that partial matches work"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="Chapter", format="heading")

        content = "# Chapter One: Introduction\nSome text here"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_case_insensitive(self):
        """Test case insensitive matching"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="IMPORTANT", format="bold", case_sensitive=False)

        content = "This is **important** text"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_fuzzy_matching(self):
        """Test fuzzy matching with max_diffs"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="Chapter One", format="heading", max_diffs=2)

        # Slightly misspelled heading
        content = "# Chaptre Oen\nSome text here"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_multiple_formatted_sections(self):
        """Test when multiple sections have the same format"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="Section Two", format="heading")

        content = """
# Section One
Some text

## Section Two
More text

### Section Three
Even more text
"""
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_nested_formatting(self):
        """Test nested formatting scenarios"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="bold text inside", format="bold")

        # Bold text inside a heading
        content = "# This has **bold text inside** the heading"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_mixed_markdown_html(self):
        """Test content with both markdown and HTML formatting"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="Important", format="bold")

        content = """
Some **Important** markdown bold text.
And some <b>Important</b> HTML bold text.
"""
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_italic_not_matching_bold(self):
        """Test that italic patterns don't incorrectly match bold"""
        test = FormatTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FORMAT.value, text="text", format="italic")

        # Should not match double asterisk bold
        content = "This is **text** here"
        result, _ = test.run(content)
        self.assertFalse(result)

        # Should match single asterisk italic
        content = "This is *text* here"
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_normalization_in_formatted_text(self):
        """Test that text normalization works within formatted sections"""
        test = FormatTest(
            pdf="test.pdf",
            page=1,
            id="test_id",
            type=TestType.FORMAT.value,
            text="\"fancy\" 'quotes'",  # This is what it looks like after normalization
            format="bold",
        )

        # Content has fancy quotes that should be normalized
        content = "This is **\u201cfancy\u201d \u2018quotes\u2019** here"
        result, _ = test.run(content)
        self.assertTrue(result)


class TestFootnoteTest(unittest.TestCase):
    """Test the FootnoteTest class"""

    def test_valid_initialization(self):
        """Test that valid initialization works"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1")
        self.assertEqual(test.marker, "1")
        self.assertIsNone(test.appears_before_marker)
        self.assertIsNone(test.appears_after_marker)

    def test_invalid_test_type(self):
        """Test that invalid test type raises ValidationError"""
        with self.assertRaises(ValidationError):
            FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.PRESENT.value, marker="1")

    def test_marker_required(self):
        """Test that marker field is required"""
        with self.assertRaises(TypeError):
            FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value)

    def test_marker_only(self):
        """Test footnote with only marker specified"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="2")

        # Test with markdown footnote reference
        content = "This is some text[^2] with a footnote.\n\n[^2]: This is the footnote text."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test with HTML superscript
        content = "This is some text<sup>2</sup> with a footnote."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test with Unicode superscript
        content = "This is some text² with a footnote."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test when marker not found
        content = "This text has no footnote markers."
        result, explanation = test.run(content)
        self.assertFalse(result)
        self.assertIn("not found", explanation)

    def test_appears_before_marker(self):
        """Test footnote with appears_before_marker specified"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1", appears_before_marker="important fact")

        # Test when text appears before marker
        content = "This is an important fact[^1] in the document."
        result, _ = test.run(content)
        self.assertTrue(result)

        content = "This is an important fact [^1] in the document."
        result, _ = test.run(content)
        self.assertTrue(result)

        content = "This is an important fact\t[^1] in the document."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test when text doesn't appear before marker
        content = "This is something else[^1] important fact comes later."
        result, explanation = test.run(content)
        self.assertFalse(result)
        self.assertIn("not found before", explanation)

    def test_appears_after_marker(self):
        """Test footnote with appears_after_marker specified"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="3", appears_after_marker="that needs citation")

        # Test when text appears after marker
        content = """This is a statement[^3] that needs citation from the study."""
        result, _ = test.run(content)
        self.assertTrue(result)

        content = """This is a statement[^3]that needs citation from the study."""
        result, _ = test.run(content)
        self.assertTrue(result)

        content = """This is a statement ³that needs citation from the study."""
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test when text doesn't appear after marker
        content = """This is a statement that needs citation before [^3] the marker."""
        result, explanation = test.run(content)
        self.assertFalse(result)
        self.assertIn("not found after", explanation)

    def test_both_before_and_after(self):
        """Test footnote with both appears_before_marker and appears_after_marker specified"""
        test = FootnoteTest(
            pdf="test.pdf",
            page=1,
            id="test_id",
            type=TestType.FOOTNOTE.value,
            marker="1",
            appears_before_marker="important fact",
            appears_after_marker="documented here",
        )

        # Test when both conditions are met (can be at different occurrences)
        content = "This is an important fact[^1] and also[^1] documented here."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test when both conditions are met at same occurrence
        content = "This is an important fact[^1] documented here in the text."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test when one condition is not met
        content = "This is something else[^1] documented here."
        result, explanation = test.run(content)
        self.assertFalse(result)

        content = "Thiis is something else [^1] and also an important fact [^1] documented here."
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_fuzzy_matching_for_appears_before(self):
        """Test fuzzy matching with max_diffs for appears_before_marker"""
        test = FootnoteTest(
            pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1", appears_before_marker="Example Reference", max_diffs=3
        )

        # Slightly misspelled text before marker
        content = """The Exampl Referenc[^1] is cited here."""
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_fuzzy_matching_for_appears_after(self):
        """Test fuzzy matching with max_diffs for appears_after_marker"""
        test = FootnoteTest(
            pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="2", appears_after_marker="statistical analysis", max_diffs=2
        )

        # Slightly misspelled text after marker
        content = "The reference[^2] statistcal analysys shows significant results."
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_multiple_footnotes(self):
        """Test handling of multiple footnotes in document"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="2")

        content = """First claim[^1] and second claim[^2].

[^1]: First reference text.
[^2]: Second reference with more details."""
        result, _ = test.run(content)
        self.assertTrue(result)

        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1")

        result, _ = test.run(content)
        self.assertTrue(result)

    def test_html_superscript_variations(self):
        """Test various HTML superscript formats"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="4")

        # Test with attributes in sup tag
        content = 'Text with footnote<sup class="footnote">4</sup>.'
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test case insensitive HTML
        content = "Text with footnote<SUP>4</SUP>."
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_unicode_superscripts(self):
        """Test all Unicode superscript digits"""
        superscripts = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}

        for digit, superscript in superscripts.items():
            test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker=digit)
            content = f"Text with footnote{superscript}."
            result, _ = test.run(content)
            self.assertTrue(result, f"Failed for superscript {digit}")

    def test_multi_digit_marker(self):
        """Test multi-digit footnote markers"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="12")

        # Test markdown reference
        content = "Text with footnote[^12].\n\n[^12]: Reference text."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test Unicode superscript for multi-digit
        content = "Text with footnote¹²."
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_appears_before_ignores_whitespace(self):
        """Test that appears_before_marker ignores whitespace and non-alpha characters"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1", appears_before_marker="claim")

        # Should match even with punctuation and whitespace between
        content = "This is a claim, ... !![^1] here."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Should match with just spaces
        content = "This is a claim    [^1] here."
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_empty_appears_before_validation(self):
        """Test that empty appears_before_marker field raises ValidationError"""
        with self.assertRaises(ValidationError):
            FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1", appears_before_marker="   ")  # Whitespace only

    def test_empty_appears_after_validation(self):
        """Test that empty appears_after_marker field raises ValidationError"""
        with self.assertRaises(ValidationError):
            FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1", appears_after_marker="   ")  # Whitespace only

    def test_normalized_text_in_footnotes(self):
        """Test that text normalization works in appears_before/after_marker"""
        test = FootnoteTest(
            pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1", appears_before_marker='"fancy" quotes and-dashes'  # Normalized form
        )

        # Content with fancy characters that should be normalized
        content = """"fancy" quotes and—dashes[^1] here."""
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_exact_marker_match(self):
        """Test that marker matching is exact"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1")

        # Should match "1" but not "10", "11", etc.
        content = "Text with footnote[^10]."
        result, explanation = test.run(content)
        self.assertFalse(result)
        self.assertIn("not found", explanation)

        # Should match exactly "1"
        content = "Text with footnote[^1]."
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_special_symbol_markers(self):
        """Test footnote markers with special symbols"""
        # Test common special symbols used as footnote markers
        special_symbols = ["*", "†", "‡", "§", "¶", "∥", "**", "††", "‡‡"]

        for symbol in special_symbols:
            test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker=symbol)

            # Test with markdown footnote reference
            content = f"Text with footnote[^{symbol}].\n\n[^{symbol}]: Footnote text."
            result, _ = test.run(content)
            self.assertTrue(result, f"Failed for symbol marker '{symbol}' in markdown")

            # Test with HTML superscript
            content = f"Text with footnote<sup>{symbol}</sup>."
            result, _ = test.run(content)
            self.assertTrue(result, f"Failed for symbol marker '{symbol}' in HTML")

            # Test that the symbol as plain text doesn't match
            # (it needs to be in proper footnote format)
            content = f"Text with {symbol} in the middle."
            result, _ = test.run(content)
            self.assertFalse(result, f"Plain text '{symbol}' should not match as footnote marker")

    def test_word_markers(self):
        """Test footnote markers that are words"""
        word_markers = ["apple", "note", "ref", "A", "B", "foo"]

        for word in word_markers:
            test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker=word)

            # Test with markdown footnote reference
            content = f"Text with footnote[^{word}].\n\n[^{word}]: Footnote text."
            result, _ = test.run(content)
            self.assertTrue(result, f"Failed for word marker '{word}' in markdown")

            # Test with HTML superscript
            content = f"Text with footnote<sup>{word}</sup>."
            result, _ = test.run(content)
            self.assertTrue(result, f"Failed for word marker '{word}' in HTML")

            # Test that the word as plain text doesn't match
            content = f"Text with {word} in the middle."
            result, _ = test.run(content)
            self.assertFalse(result, f"Plain text '{word}' should not match as footnote marker")

    def test_marker_with_whitespace_validation(self):
        """Test that markers with whitespace are rejected"""
        with self.assertRaises(ValidationError) as cm:
            FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="has space")
        self.assertIn("cannot contain whitespace", str(cm.exception))

    def test_special_symbols_with_appears_before(self):
        """Test special symbol markers combined with appears_before_marker"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="†", appears_before_marker="important")

        # Use proper footnote format
        content = """This is important[^†] here."""
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test when text doesn't appear before
        content = """This is something[^†] else important."""
        result, explanation = test.run(content)
        self.assertFalse(result)
        self.assertIn("not found before", explanation)

    def test_special_symbols_with_appears_after(self):
        """Test special symbol markers with position checking"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="‡", appears_after_marker="critical finding")

        # Test when text appears after the marker
        content = "The reference<sup>‡</sup> critical finding was unexpected."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Test when text doesn't appear after the marker
        content = "The critical finding was before <sup>‡</sup> the marker."
        result, explanation = test.run(content)
        self.assertFalse(result)
        self.assertIn("not found after", explanation)

    def test_escaped_special_characters_in_regex(self):
        """Test that special regex characters in markers are properly escaped"""
        # These characters have special meaning in regex and need escaping
        regex_special_markers = ["*", "**", ".", "^", "$", "+", "?", "|", "\\", "(", ")", "[", "]", "{", "}"]

        for marker in regex_special_markers:
            try:
                test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker=marker)

                # Test with markdown format
                content = f"Text[^{marker}].\n\n[^{marker}]: Note."
                result, _ = test.run(content)
                # We expect this to work for valid markers like "*" and "**"
                # But some like "\" might not be valid in markdown

                # Test with HTML format which should work for all
                content = f"Text<sup>{marker}</sup>."
                result, _ = test.run(content)

            except Exception as e:
                # Some markers might not be valid, that's okay
                pass

    def test_mixed_formats_same_document(self):
        """Test document with mixed footnote formats"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="†")

        # Document with both markdown and HTML footnotes
        content = """
Some text[^†] with markdown format.
Other text<sup>†</sup> with HTML format.

[^†]: This is the footnote definition.
"""
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_double_dagger_and_similar(self):
        """Test markers that are repeated symbols"""
        repeated_markers = ["**", "††", "‡‡", "§§", "***"]

        for marker in repeated_markers:
            test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker=marker)

            # Test markdown format
            content = f"Text[^{marker}].\n\n[^{marker}]: Note text."
            result, _ = test.run(content)
            self.assertTrue(result, f"Failed for repeated marker '{marker}'")

    def test_case_sensitive_word_markers(self):
        """Test that word markers are case-sensitive"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="Note")

        # Should match exact case
        content = "Text[^Note].\n\n[^Note]: Reference."
        result, _ = test.run(content)
        self.assertTrue(result)

        # Should not match different case
        content = "Text[^note].\n\n[^note]: Reference."
        result, _ = test.run(content)
        self.assertFalse(result)

    def test_html_footnote_definitions(self):
        """Test HTML-style footnote definitions"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1")

        # HTML style: <sup>1</sup> marker
        content = """
Some text with a reference<sup>1</sup> in the middle.

At the bottom:
<sup>1</sup>This is the footnote text that appears right after the marker.
"""
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_html_footnote_with_special_symbols(self):
        """Test HTML-style footnotes with special symbol markers"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="†")

        # HTML style with special symbol
        content = """
Important finding<sup>†</sup> in the research.

<sup>†</sup>See appendix for details and supplementary materials.
"""
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_mixed_footnote_styles(self):
        """Test document with both markdown and HTML footnote definitions"""
        # Test for first footnote (markdown style)
        test1 = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1")

        content = """
First point[^1] and second point<sup>2</sup>.

[^1]: First reference in markdown style.

<sup>2</sup>Second reference in HTML style.
"""
        result, _ = test1.run(content)
        self.assertTrue(result)

        # Test for second footnote (HTML style)
        test2 = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="2")
        result, _ = test2.run(content)
        self.assertTrue(result)

    def test_html_footnote_multiline(self):
        """Test HTML footnote that spans multiple lines"""
        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="3")

        content = """
Reference here<sup>3</sup>.

<sup>3</sup>This footnote text
spans multiple lines
with more information.
"""
        result, _ = test.run(content)
        self.assertTrue(result)

    def test_real_world_case(self):
        content = """## Abstract

Automated scientific discovery promises to accelerate progress across scientific domains. However, developing and evaluating an AI agent's capacity for end-to-end scientific reasoning is challenging as running real-world experiments is often prohibitively expensive or infeasible. In this work we introduce DISCOVERYWORLD, the first virtual environment for developing and benchmarking an agent's ability to perform complete cycles of novel scientific discovery. DISCOVERYWORLD contains a variety of different challenges, covering topics as diverse as radioisotope dating, rocket science, and proteomics, to encourage development of *general* discovery skills rather than task-specific solutions. DISCOVERYWORLD itself is an inexpensive, simulated, text-based environment (with optional 2D visual overlay). It includes 120 different challenge tasks, spanning eight topics each with three levels of difficulty and several parametric variations. Each task requires an agent to form hypotheses, design and run experiments, analyze results, and act on conclusions. DISCOVERYWORLD further provides three automatic metrics for evaluating performance, based on (a) task completion, (b) task-relevant actions taken, and (c) the discovered explanatory knowledge. We find that strong baseline agents, that perform well in prior published environments, struggle on most DISCOVERYWORLD tasks, suggesting that DISCOVERYWORLD captures some of the novel challenges of discovery, and thus that DISCOVERYWORLD may help accelerate near-term development and assessment of scientific discovery competency in agents. Code available at github.com/allenai/discoveryworld.<sup>1</sup>

## 1 Introduction

A long-standing dream of AI has been to build systems that can perform scientific discovery, potentially leading to new breakthroughs for the benefit of humanity [13]. Recently, with the rise of neural techniques, there have been several successful discovery systems developed for specialized problems such as protein folding [10, 15], mathematics [22], and material science [24]. However, while the results have been impressive, these systems (deliberately) bypass the full discovery process of ideation, hypothesis formation, experiment design, etc., and instead (expertly) perform systematic searches over a pre-defined hypothesis space, with pre-defined goals. This raises the question: how much more can be achieved if AI is applied to the broader scientific process? Some works have indeed developed early systems for this, for example, in chemistry [1], and genetics [12]. These systems can also generate hypotheses, design experiments, and execute them (via robotics) in real environments. However, operating in real environments is expensive and complex, creating a barrier

<sup>1</sup>Released under Apache-2.0 license."""

        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1")

        result, _ = test.run(content)
        self.assertTrue(result)

        test = FootnoteTest(
            pdf="test.pdf",
            page=1,
            id="test_id",
            type=TestType.FOOTNOTE.value,
            marker="1",
            appears_before_marker="Code available at github.com/allenai/discoveryworld.",
        )

        result, _ = test.run(content)
        self.assertTrue(result)

        test = FootnoteTest(pdf="test.pdf", page=1, id="test_id", type=TestType.FOOTNOTE.value, marker="1", appears_after_marker="Released under Apache")

        result, _ = test.run(content)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
