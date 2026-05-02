import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from fuzzysearch import find_near_matches
from rapidfuzz import fuzz
from tqdm import tqdm

from olmocr.repeatdetect import RepeatDetector

from .katex.render import compare_rendered_equations, render_equation
from .table_parsing import parse_html_tables, parse_markdown_tables

# Tell pytest these are not tests
__test__ = False


class TestType(str, Enum):
    __test__ = False  # Tell pytest this is not a test class

    BASELINE = "baseline"
    PRESENT = "present"
    ABSENT = "absent"
    ORDER = "order"
    TABLE = "table"
    MATH = "math"
    FORMAT = "format"
    FOOTNOTE = "footnote"


class TestChecked(str, Enum):
    VERIFIED = "verified"
    REJECTED = "rejected"


class ValidationError(Exception):
    """Exception raised for validation errors."""

    pass


def normalize_text(md_content: str) -> str:
    if md_content is None:
        return None

    # Normalize <br> and <br/> to newlines
    md_content = re.sub(r"<br/?>", " ", md_content)

    # Remove markdown bold formatting (** or __ for bold)
    md_content = re.sub(r"\*\*(.*?)\*\*", r"\1", md_content)
    md_content = re.sub(r"__(.*?)__", r"\1", md_content)
    md_content = re.sub(r"</?b>", "", md_content)  # Remove <b> tags if they exist
    md_content = re.sub(r"</?i>", "", md_content)  # Remove <i> tags if they exist

    # Remove markdown italics formatting (* or _ for italics)
    # Logic: The dot (.) in regex matches any character EXCEPT a newline.
    # This automatically prevents matching **start \n\n end**.
    # We use group \1 to ensure we match matching pairs (**...** or __...__).
    md_content = re.sub(r"(\*\*|__)(.*?)\1", r"\2", md_content)  # Bold
    md_content = re.sub(r"(\*|_)(.*?)\1", r"\2", md_content)  # Italics

    # Normalize whitespace in the md_content
    md_content = re.sub(r"\s+", " ", md_content)

    # Convert down to a consistent unicode form, so é == e + accent, unicode forms
    md_content = unicodedata.normalize("NFC", md_content)

    # Dictionary of characters to replace: keys are fancy characters, values are ASCII equivalents, unicode micro with greek mu comes up often enough too
    replacements = {"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"', "＿": "_", "–": "-", "—": "-", "‑": "-", "‒": "-", "−": "-", "\u00b5": "\u03bc"}

    # Apply all replacements from the dictionary
    for fancy_char, ascii_char in replacements.items():
        md_content = md_content.replace(fancy_char, ascii_char)

    return md_content


@dataclass(kw_only=True)
class BasePDFTest:
    """
    Base class for all PDF test types.

    Attributes:
        pdf: The PDF filename.
        page: The page number for the test.
        id: Unique identifier for the test.
        type: The type of test.
        threshold: A float between 0 and 1 representing the threshold for fuzzy matching.
    """

    pdf: str
    page: int
    id: str
    type: str
    max_diffs: int = 0
    checked: Optional[TestChecked] = None
    url: Optional[str] = None

    def __post_init__(self):
        if not self.pdf:
            raise ValidationError("PDF filename cannot be empty")
        if not self.id:
            raise ValidationError("Test ID cannot be empty")
        if not isinstance(self.max_diffs, int) or self.max_diffs < 0:
            raise ValidationError("Max diffs must be positive number or 0")
        if self.type not in {t.value for t in TestType}:
            raise ValidationError(f"Invalid test type: {self.type}")

    def run(self, md_content: str) -> Tuple[bool, str]:
        """
        Run the test on the provided markdown content.

        Args:
            md_content: The content of the .md file.

        Returns:
            A tuple (passed, explanation) where 'passed' is True if the test passes,
            and 'explanation' provides details when the test fails.
        """
        raise NotImplementedError("Subclasses must implement the run method")


@dataclass
class TextPresenceTest(BasePDFTest):
    """
    Test to verify the presence or absence of specific text in a PDF.

    Attributes:
        text: The text string to search for.
    """

    text: str
    case_sensitive: bool = True
    first_n: Optional[int] = None
    last_n: Optional[int] = None

    def __post_init__(self):
        super().__post_init__()
        if self.type not in {TestType.PRESENT.value, TestType.ABSENT.value}:
            raise ValidationError(f"Invalid type for TextPresenceTest: {self.type}")
        self.text = normalize_text(self.text)
        if not self.text.strip():
            raise ValidationError("Text field cannot be empty")

    def run(self, md_content: str) -> Tuple[bool, str]:
        reference_query = self.text

        # Normalize whitespace in the md_content
        md_content = normalize_text(md_content)

        if not self.case_sensitive:
            reference_query = reference_query.lower()
            md_content = md_content.lower()

        if self.first_n and self.last_n:
            md_content = md_content[: self.first_n] + md_content[-self.last_n :]
        elif self.first_n:
            md_content = md_content[: self.first_n]
        elif self.last_n:
            md_content = md_content[-self.last_n :]

        # Length guard against rapidfuzz.partial_ratio's symmetric behavior.
        # partial_ratio scales by min(len(a), len(b)) — when md_content is much
        # shorter than reference_query the metric inverts: e.g.
        # partial_ratio("a long phrase", " ") = 1.0, because the single space
        # in md_content matches the single space inside the query. With
        # max_diffs=0 the threshold is 1.0 so PRESENT falsely passes and
        # ABSENT falsely fails for any space-containing query whenever a
        # downstream pipeline emits effectively empty content (e.g. "\n",
        # which normalize_text collapses to " "). For PRESENT to be plausibly
        # satisfiable, md_content needs at least len(reference_query) -
        # max_diffs characters.
        min_required = len(reference_query) - self.max_diffs
        if len(md_content) < min_required:
            if self.type == TestType.PRESENT.value:
                msg = (
                    f"Candidate too short ({len(md_content)} chars) to plausibly contain "
                    f"'{reference_query[:40]}...' (need >= {min_required} chars)"
                )
                return False, msg
            else:  # ABSENT
                return True, ""

        # Threshold for fuzzy matching derived from max_diffs
        threshold = 1.0 - (self.max_diffs / (len(reference_query) if len(reference_query) > 0 else 1))
        best_ratio = fuzz.partial_ratio(reference_query, md_content) / 100.0

        if self.type == TestType.PRESENT.value:
            if best_ratio >= threshold:
                return True, ""
            else:
                msg = f"Expected '{reference_query[:40]}...' with threshold {threshold} " f"but best match ratio was {best_ratio:.3f}"
                return False, msg
        else:  # ABSENT
            if best_ratio < threshold:
                return True, ""
            else:
                msg = f"Expected absence of '{reference_query[:40]}...' with threshold {threshold} " f"but best match ratio was {best_ratio:.3f}"
                return False, msg


@dataclass
class TextOrderTest(BasePDFTest):
    """
    Test to verify that one text appears before another in a PDF.

    Attributes:
        before: The text expected to appear first.
        after: The text expected to appear after the 'before' text.
    """

    before: str
    after: str

    def __post_init__(self):
        super().__post_init__()
        if self.type != TestType.ORDER.value:
            raise ValidationError(f"Invalid type for TextOrderTest: {self.type}")
        self.before = normalize_text(self.before)
        self.after = normalize_text(self.after)
        if not self.before.strip():
            raise ValidationError("Before field cannot be empty")
        if not self.after.strip():
            raise ValidationError("After field cannot be empty")
        if self.max_diffs > len(self.before) // 2 or self.max_diffs > len(self.after) // 2:
            raise ValidationError("Max diffs is too large for this test, greater than 50% of the search string")

    def run(self, md_content: str) -> Tuple[bool, str]:
        md_content = normalize_text(md_content)

        before_matches = find_near_matches(self.before, md_content, max_l_dist=self.max_diffs)
        after_matches = find_near_matches(self.after, md_content, max_l_dist=self.max_diffs)

        if not before_matches:
            return False, f"'before' text '{self.before[:40]}...' not found with max_l_dist {self.max_diffs}"
        if not after_matches:
            return False, f"'after' text '{self.after[:40]}...' not found with max_l_dist {self.max_diffs}"

        for before_match in before_matches:
            for after_match in after_matches:
                if before_match.start < after_match.start:
                    return True, ""
        return False, (f"Could not find a location where '{self.before[:40]}...' appears before " f"'{self.after[:40]}...'.")


@dataclass
class FormatTest(BasePDFTest):
    """
    Test to verify that specific text appears with the correct formatting.

    Attributes:
        text: The text to search for.
        format: The expected format ("heading", "bold", or "italic").
    """

    text: str
    format: str
    case_sensitive: bool = True

    def __post_init__(self):
        super().__post_init__()
        if self.type != TestType.FORMAT.value:
            raise ValidationError(f"Invalid type for FormatTest: {self.type}")
        self.text = normalize_text(self.text)
        if not self.text.strip():
            raise ValidationError("Text field cannot be empty")
        if self.format not in {"heading", "bold", "italic"}:
            raise ValidationError(f"Invalid format type: {self.format}. Must be 'heading', 'bold', or 'italic'")

    def run(self, md_content: str) -> Tuple[bool, str]:
        """
        Extract all text with the specified format and check if our text is among them.
        """
        # Store the original content before any normalization for pattern matching
        original_content = md_content

        # Extract formatted text based on the format type
        formatted_texts = []

        if self.format == "heading":
            # Markdown headings (# through ######)
            heading_patterns = [
                r"^#{1,6}\s+(.+?)$",  # Standard markdown headings
            ]
            for pattern in heading_patterns:
                matches = re.findall(pattern, original_content, re.MULTILINE)
                formatted_texts.extend(matches)

            # HTML headings (<h1> through <h6>)
            html_heading_pattern = r"<h[1-6][^>]*>(.*?)</h[1-6]>"
            matches = re.findall(html_heading_pattern, original_content, re.IGNORECASE | re.DOTALL)
            formatted_texts.extend(matches)

        elif self.format == "bold":
            # Markdown bold patterns
            bold_patterns = [
                r"\*\*(.*?)\*\*",  # **text**
                r"__(.*?)__",  # __text__
            ]
            for pattern in bold_patterns:
                matches = re.findall(pattern, original_content, re.DOTALL)
                formatted_texts.extend(matches)

            # HTML bold patterns
            html_bold_patterns = [r"<b[^>]*>(.*?)</b>", r"<strong[^>]*>(.*?)</strong>"]  # <b>text</b>  # <strong>text</strong>
            for pattern in html_bold_patterns:
                matches = re.findall(pattern, original_content, re.IGNORECASE | re.DOTALL)
                formatted_texts.extend(matches)

        elif self.format == "italic":
            # Markdown italic patterns - be careful not to match bold
            # We need to match single * or _ that are not part of ** or __
            italic_patterns = [
                r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)",  # *text* but not **text**
                r"(?<!_)_(?!_)(.*?)(?<!_)_(?!_)",  # _text_ but not __text__
            ]
            for pattern in italic_patterns:
                matches = re.findall(pattern, original_content, re.DOTALL)
                formatted_texts.extend(matches)

            # HTML italic patterns
            html_italic_patterns = [r"<i[^>]*>(.*?)</i>", r"<em[^>]*>(.*?)</em>"]  # <i>text</i>  # <em>text</em>
            for pattern in html_italic_patterns:
                matches = re.findall(pattern, original_content, re.IGNORECASE | re.DOTALL)
                formatted_texts.extend(matches)

        # Normalize all extracted formatted texts
        normalized_formatted_texts = [normalize_text(text) for text in formatted_texts]

        # Normalize the search text
        search_text = self.text
        if not self.case_sensitive:
            search_text = search_text.lower()
            normalized_formatted_texts = [text.lower() for text in normalized_formatted_texts]

        # Check if the text appears in any of the formatted texts using fuzzy matching
        threshold = 1.0 - (self.max_diffs / (len(search_text) if len(search_text) > 0 else 1))

        for formatted_text in normalized_formatted_texts:
            # Use partial_ratio for substring matching
            ratio = fuzz.partial_ratio(search_text, formatted_text) / 100.0
            if ratio >= threshold:
                return True, ""

        # If we didn't find the text with the specified format
        found_formats = []
        if len(normalized_formatted_texts) > 0:
            # Show a sample of what we did find with this format
            sample = normalized_formatted_texts[:3]
            sample_str = ", ".join([f"'{t[:20]}...'" if len(t) > 20 else f"'{t}'" for t in sample])
            found_formats.append(f"Found {self.format} text: {sample_str}")
        else:
            found_formats.append(f"No {self.format} formatted text found")

        return False, f"Text '{self.text[:40]}...' not found with {self.format} formatting. {'; '.join(found_formats)}"


@dataclass
class TableTest(BasePDFTest):
    """
    Test to verify certain properties of a table are held, namely that some cells appear relative to other cells correctly
    """

    # This is the target cell, which must exist in at least one place in the table
    cell: str

    # These properties say that the cell immediately up/down/left/right of the target cell has the string specified
    up: str = ""
    down: str = ""
    left: str = ""
    right: str = ""

    # These properties say that the cell all the way up, or all the way left of the target cell (ex. headings) has the string value specified
    top_heading: str = ""
    left_heading: str = ""

    ignore_markdown_tables: bool = False

    def __post_init__(self):
        super().__post_init__()
        if self.type != TestType.TABLE.value:
            raise ValidationError(f"Invalid type for TableTest: {self.type}")

        # Normalize the search text too
        self.cell = normalize_text(self.cell)
        self.up = normalize_text(self.up)
        self.down = normalize_text(self.down)
        self.left = normalize_text(self.left)
        self.right = normalize_text(self.right)
        self.top_heading = normalize_text(self.top_heading)
        self.left_heading = normalize_text(self.left_heading)

    def run(self, content: str) -> Tuple[bool, str]:
        """
        Run the table test on provided content.

        Finds all tables (markdown and/or HTML based on content_type) and checks if any cell
        matches the target cell and satisfies the specified relationships.

        Args:
            content: The content containing tables (markdown or HTML)

        Returns:
            A tuple (passed, explanation) where 'passed' is True if the test passes,
            and 'explanation' provides details when the test fails.
        """
        # Initialize variables to track tables and results
        tables_to_check = []
        failed_reasons = []

        # Threshold for fuzzy matching derived from max_diffs
        threshold = 1.0 - (self.max_diffs / (len(self.cell) if len(self.cell) > 0 else 1))
        threshold = max(0.5, threshold)

        # Parse tables based on content_type
        if not self.ignore_markdown_tables:
            md_tables = parse_markdown_tables(content)
            tables_to_check.extend(md_tables)

        html_tables = parse_html_tables(content)
        tables_to_check.extend(html_tables)

        # If no tables found, return failure
        if not tables_to_check:
            return False, "No tables found in the content"

        # Check each table
        for table_data in tables_to_check:
            # Find all cells that match the target cell using fuzzy matching
            matches = []
            for rowcol, cell_content in table_data.cell_text.items():
                similarity = fuzz.ratio(self.cell, normalize_text(cell_content)) / 100.0

                if similarity >= threshold:
                    matches.append(rowcol)

            # If no matches found in this table, continue to the next table
            if not matches:
                continue

            # Check the relationships for each matching cell
            for rowcol in matches:
                all_relationships_satisfied = True
                current_failed_reasons = []

                def _check_relationship(comparison_str: str, relation_func):
                    nonlocal all_relationships_satisfied
                    cur_relation_satisified = False
                    best_similarity = 0
                    best_similarity_text = None

                    for rowcol_up in relation_func(rowcol):
                        test_cell = normalize_text(table_data.cell_text[rowcol_up])
                        test_similarity = fuzz.ratio(comparison_str, test_cell) / 100.0
                        if test_similarity > best_similarity:
                            best_similarity = test_similarity
                            best_similarity_text = test_cell

                        if test_similarity >= max(0.5, 1.0 - (self.max_diffs / (len(comparison_str) if len(comparison_str) > 0 else 1))):
                            cur_relation_satisified = True

                    if not cur_relation_satisified:
                        all_relationships_satisfied = False
                        current_failed_reasons.append(
                            f"Cell compared to '{best_similarity_text}' doesn't match expected '{comparison_str}' (best similarity: {best_similarity:.2f})"
                        )

                # Check up relationship
                if self.up:
                    _check_relationship(self.up, lambda rowcol: table_data.up_relations[rowcol])

                if self.down:
                    _check_relationship(self.down, lambda rowcol: table_data.down_relations[rowcol])

                if self.left:
                    _check_relationship(self.left, lambda rowcol: table_data.left_relations[rowcol])

                if self.right:
                    _check_relationship(self.right, lambda rowcol: table_data.right_relations[rowcol])

                if self.left_heading:
                    _check_relationship(self.left_heading, lambda rowcol: table_data.left_heading_relations(*rowcol))

                if self.top_heading:
                    _check_relationship(self.top_heading, lambda rowcol: table_data.top_heading_relations(*rowcol))

                # If all relationships are satisfied for this cell, the test passes
                if all_relationships_satisfied:
                    return True, ""
                else:
                    failed_reasons.extend(current_failed_reasons)

        # If we've gone through all tables and all matching cells and none satisfied all relationships
        if not failed_reasons:
            return False, f"No cell matching '{self.cell}' found in any table with threshold {threshold}"
        else:
            return False, f"Found cells matching '{self.cell}' but relationships were not satisfied: {'; '.join(failed_reasons)}"


@dataclass
class BaselineTest(BasePDFTest):
    """
    This test makes sure that several baseline quality checks pass for the output generation.

    Namely, the output is not blank, not endlessly repeating, and contains characters of the proper
    character sets.

    """

    max_length: Optional[int] = None  # Used to implement blank page checks
    max_length_skips_image_alt_tags: bool = False

    max_repeats: int = 30
    check_disallowed_characters: bool = True

    def run(self, content: str) -> Tuple[bool, str]:
        base_content_len = len("".join(c for c in content if c.isalnum()).strip())

        # If this a blank page check, then it short circuits the rest of the checks
        if self.max_length is not None:
            if self.max_length_skips_image_alt_tags:
                # Remove markdown image tags like ![alt text](image.png) from the text length count
                content_for_length_check = re.sub(r"!\[.*?\]\(.*?\)", "", content)
                base_content_len = len("".join(c for c in content_for_length_check if c.isalnum()).strip())

            if base_content_len > self.max_length:
                return False, f"{base_content_len} characters were output for a page we expected to be blank"
            else:
                return True, ""

        if base_content_len == 0:
            return False, "The text contains no alpha numeric characters"

        # Makes sure that the content has no egregious repeated ngrams at the end, which indicate a degradation of quality
        # Honestly, this test doesn't seem to catch anything at the moment, maybe it can be refactored to a "text-quality"
        # test or something, that measures repetition, non-blanks, charsets, etc
        d = RepeatDetector(max_ngram_size=5)
        d.add_letters(content)
        repeats = d.ngram_repeats()

        for index, count in enumerate(repeats):
            if count > self.max_repeats:
                return False, f"Text ends with {count} repeating {index+1}-grams, invalid"

        pattern = re.compile(
            r"["
            r"\u4e00-\u9FFF"  # CJK Unified Ideographs (Chinese characters)
            r"\u3040-\u309F"  # Hiragana (Japanese)
            r"\u30A0-\u30FF"  # Katakana (Japanese)
            r"\U0001F600-\U0001F64F"  # Emoticons (Emoji)
            r"\U0001F300-\U0001F5FF"  # Miscellaneous Symbols and Pictographs (Emoji)
            r"\U0001F680-\U0001F6FF"  # Transport and Map Symbols (Emoji)
            r"\U0001F1E0-\U0001F1FF"  # Regional Indicator Symbols (flags, Emoji)
            r"]",
            flags=re.UNICODE,
        )

        matches = pattern.findall(content)
        if self.check_disallowed_characters and matches:
            return False, f"Text contains disallowed characters {matches}"

        return True, ""


@dataclass
class MathTest(BasePDFTest):
    math: str

    ignore_dollar_delimited: bool = False

    def __post_init__(self):
        super().__post_init__()
        if self.type != TestType.MATH.value:
            raise ValidationError(f"Invalid type for MathTest: {self.type}")
        if len(self.math.strip()) == 0:
            raise ValidationError("Math test must have non-empty math expression")

        self.reference_render = render_equation(self.math)

        if self.reference_render is None:
            raise ValidationError(f"Math equation {self.math} was not able to render")

    def run(self, content: str) -> Tuple[bool, str]:
        # Store both the search pattern and the full pattern to replace
        patterns = [
            (r"\\\((.+?)\\\)", r"\\\((.+?)\\\)"),  # \(...\)
            (r"\\\[(.+?)\\\]", r"\\\[(.+?)\\\]"),  # \[...\]
        ]

        if not self.ignore_dollar_delimited:
            patterns.extend(
                [
                    (r"\$\$(.+?)\$\$", r"\$\$(.+?)\$\$"),  # $$...$$
                    (r"\$(.+?)\$", r"\$(.+?)\$"),  # $...$])
                ]
            )

        equations = []
        modified_content = content

        for search_pattern, replace_pattern in patterns:
            # Find all matches for the current pattern
            matches = re.findall(search_pattern, modified_content, re.DOTALL)
            equations.extend([e.strip() for e in matches])

            # Replace all instances of this pattern with empty strings
            modified_content = re.sub(replace_pattern, "", modified_content, flags=re.DOTALL)

        # If an equation in the markdown exactly matches our math string, then that's good enough
        # we don't have to do a more expensive comparison
        if any(hyp == self.math for hyp in equations):
            return True, ""

        # If not, then let's render the math equation itself and now compare to each hypothesis
        # But, to speed things up, since rendering equations is hard, we sort the equations on the page
        # by fuzzy similarity to the hypothesis
        equations.sort(key=lambda x: -fuzz.ratio(x, self.math))
        for hypothesis in equations:
            hypothesis_render = render_equation(hypothesis)

            if not hypothesis_render:
                continue

            if compare_rendered_equations(self.reference_render, hypothesis_render):
                return True, ""

        # self.reference_render.save(f"maths/{self.id}_ref.png", format="PNG")
        # best_match_render.save(f"maths/{self.id}_hyp.png", format="PNG")

        return False, f"No match found for {self.math} anywhere in content"


@dataclass
class FootnoteTest(BasePDFTest):
    """
    Test to verify that footnotes appear correctly on a page.

    Attributes:
        marker: The footnote marker (e.g., "1", "2"). Must appear as superscript or [^marker]. Required.
        appears_before_marker: Optional text that should appear before the marker (ignoring whitespace/non-alpha).
        appears_after_marker: Optional text that should appear after the marker (ignoring whitespace/non-alpha).
    """

    marker: str
    appears_before_marker: Optional[str] = None
    appears_after_marker: Optional[str] = None

    def __post_init__(self):
        super().__post_init__()
        if self.type != TestType.FOOTNOTE.value:
            raise ValidationError(f"Invalid type for FootnoteTest: {self.type}")

        # marker is required
        if not self.marker:
            raise ValidationError("marker field is required")

        # Validate marker doesn't contain whitespace
        if " " in self.marker:
            raise ValidationError("Marker cannot contain whitespace")

        # Normalize the optional text fields
        if self.appears_before_marker:
            self.appears_before_marker = normalize_text(self.appears_before_marker)
            if not self.appears_before_marker.strip():
                raise ValidationError("appears_before_marker field cannot be empty if provided")

        if self.appears_after_marker:
            self.appears_after_marker = normalize_text(self.appears_after_marker)
            if not self.appears_after_marker.strip():
                raise ValidationError("appears_after_marker field cannot be empty if provided")

    def run(self, md_content: str) -> Tuple[bool, str]:
        """
        Run the footnote test on provided markdown content.

        Args:
            md_content: The markdown content to test.

        Returns:
            A tuple (passed, explanation) where 'passed' is True if the test passes,
            and 'explanation' provides details when the test fails.
        """
        # Find all occurrences of the marker in various formats
        marker_positions = []

        # Check for markdown footnote reference [^marker] (but not definition [^marker]:)
        markdown_pattern = rf"\[\^{re.escape(self.marker)}\](?!:)"
        for match in re.finditer(markdown_pattern, md_content):
            marker_positions.append({"start": match.start(), "end": match.end(), "type": "markdown"})

        # Check for superscript HTML <sup>marker</sup>
        html_sup_pattern = rf"<sup[^>]*>{re.escape(self.marker)}</sup>"
        for match in re.finditer(html_sup_pattern, md_content, re.IGNORECASE):
            marker_positions.append({"start": match.start(), "end": match.end(), "type": "html"})

        # Check for Unicode superscript characters (for common digits)
        superscript_map = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}

        # Convert marker to superscript if all characters are digits
        if all(c in superscript_map for c in self.marker):
            superscript_marker = "".join(superscript_map[c] for c in self.marker)
            for match in re.finditer(re.escape(superscript_marker), md_content):
                marker_positions.append({"start": match.start(), "end": match.end(), "type": "unicode"})

        # If no markers found at all, fail
        if not marker_positions:
            return False, f"Footnote marker '{self.marker}' not found as [^{self.marker}], <sup>{self.marker}</sup>, or superscript"

        # If no additional checks needed, pass
        if not self.appears_before_marker and not self.appears_after_marker:
            return True, ""

        # Helper function to clean text for comparison (remove whitespace and non-alpha)
        def clean_for_comparison(text):
            # Remove all non-alphanumeric characters and normalize
            return "".join(c for c in normalize_text(text) if c.isalnum()).lower()

        # Check appears_before_marker if provided
        before_found = False if self.appears_before_marker else True
        if self.appears_before_marker:
            clean_target_before = clean_for_comparison(self.appears_before_marker)
            threshold = 1.0 - (self.max_diffs / (len(self.appears_before_marker) if len(self.appears_before_marker) > 0 else 1))

            for pos in marker_positions:
                # Get text before this marker position
                start_pos = max(0, pos["start"] - 200)  # Look back up to 200 chars
                text_before = md_content[start_pos : pos["start"]]

                # Clean the text before for comparison
                clean_text_before = clean_for_comparison(text_before)

                # Check if appears_before_marker is at the end of this text (using fuzzy matching)
                if clean_text_before:
                    # Use partial_ratio to check if target appears at the end
                    # We'll check the last portion that's roughly the size of our target
                    check_length = min(len(clean_text_before), len(clean_target_before) * 2)
                    text_to_check = clean_text_before[-check_length:] if check_length > 0 else clean_text_before

                    similarity = fuzz.partial_ratio(clean_target_before, text_to_check) / 100.0
                    if similarity >= threshold:
                        before_found = True
                        break

        # Check appears_after_marker if provided
        after_found = False if self.appears_after_marker else True
        if self.appears_after_marker:
            clean_target_after = clean_for_comparison(self.appears_after_marker)
            threshold = 1.0 - (self.max_diffs / (len(self.appears_after_marker) if len(self.appears_after_marker) > 0 else 1))

            for pos in marker_positions:
                # Get text after this marker position
                end_pos = min(len(md_content), pos["end"] + 200)  # Look ahead up to 200 chars
                text_after = md_content[pos["end"] : end_pos]

                # Clean the text after for comparison
                clean_text_after = clean_for_comparison(text_after)

                # Check if appears_after_marker is at the beginning of this text (using fuzzy matching)
                if clean_text_after:
                    # Use partial_ratio to check if target appears at the beginning
                    # We'll check the first portion that's roughly the size of our target
                    check_length = min(len(clean_text_after), len(clean_target_after) * 2)
                    text_to_check = clean_text_after[:check_length] if check_length > 0 else clean_text_after

                    similarity = fuzz.partial_ratio(clean_target_after, text_to_check) / 100.0
                    if similarity >= threshold:
                        after_found = True
                        break

        # Build failure message if needed
        failures = []
        if self.appears_before_marker and not before_found:
            failures.append(f"Text '{self.appears_before_marker[:40]}...' not found before any occurrence of marker '{self.marker}'")
        if self.appears_after_marker and not after_found:
            failures.append(f"Text '{self.appears_after_marker[:40]}...' not found after any occurrence of marker '{self.marker}'")

        if failures:
            return False, "; ".join(failures)
        else:
            return True, ""


def load_single_test(data: Union[str, Dict]) -> BasePDFTest:
    """
    Load a single test from a JSON line string or JSON object.

    Args:
        data: Either a JSON string to parse or a dictionary containing test data.

    Returns:
        A test object of the appropriate type.

    Raises:
        ValidationError: If the test type is unknown or data is invalid.
        json.JSONDecodeError: If the string cannot be parsed as JSON.
    """
    # Handle JSON string input
    if isinstance(data, str):
        data = data.strip()
        if not data:
            raise ValueError("Empty string provided")
        data = json.loads(data)

    # Process the test data
    test_type = data.get("type")
    if test_type in {TestType.PRESENT.value, TestType.ABSENT.value}:
        test = TextPresenceTest(**data)
    elif test_type == TestType.ORDER.value:
        test = TextOrderTest(**data)
    elif test_type == TestType.TABLE.value:
        test = TableTest(**data)
    elif test_type == TestType.MATH.value:
        test = MathTest(**data)
    elif test_type == TestType.BASELINE.value:
        test = BaselineTest(**data)
    elif test_type == TestType.FORMAT.value:
        test = FormatTest(**data)
    elif test_type == TestType.FOOTNOTE.value:
        test = FootnoteTest(**data)
    else:
        raise ValidationError(f"Unknown test type: {test_type}")

    return test


def load_tests(jsonl_file: str) -> List[BasePDFTest]:
    """
    Load tests from a JSONL file using parallel processing with a ThreadPoolExecutor.

    Args:
        jsonl_file: Path to the JSONL file containing test definitions.

    Returns:
        A list of test objects.
    """

    def process_line_with_number(line_tuple: Tuple[int, str]) -> Optional[Tuple[int, BasePDFTest]]:
        """
        Process a single line from the JSONL file and return a tuple of (line_number, test object).
        Returns None for empty lines.
        """
        line_number, line = line_tuple
        line = line.strip()
        if not line:
            return None

        try:
            test = load_single_test(line)
            return (line_number, test)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON on line {line_number}: {e}")
            raise
        except (ValidationError, KeyError) as e:
            print(f"Error on line {line_number}: {e}")
            raise
        except Exception as e:
            print(f"Unexpected error on line {line_number}: {e}")
            raise

    tests = []

    # Read all lines along with their line numbers.
    with open(jsonl_file, "r") as f:
        lines = list(enumerate(f, start=1))

    # Use a ThreadPoolExecutor to process each line in parallel.
    with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 1, 64)) as executor:
        # Submit all tasks concurrently.
        futures = {executor.submit(process_line_with_number, item): item[0] for item in lines}
        # Use tqdm to show progress as futures complete.
        for future in tqdm(as_completed(futures), total=len(futures), desc="Loading tests"):
            result = future.result()
            if result is not None:
                _, test = result
                tests.append(test)

    # Check for duplicate test IDs after parallel processing.
    unique_ids = set()
    for test in tests:
        if test.id in unique_ids:
            raise ValidationError(f"Test with duplicate id {test.id} found, error loading tests.")
        unique_ids.add(test.id)

    return tests


def save_tests(tests: List[BasePDFTest], jsonl_file: str) -> None:
    """
    Save tests to a JSONL file using asdict for conversion.

    Args:
        tests: A list of test objects.
        jsonl_file: Path to the output JSONL file.
    """
    with open(jsonl_file, "w") as file:
        for test in tests:
            file.write(json.dumps(asdict(test)) + "\n")
