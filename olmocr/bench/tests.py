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
    BASELINE = "baseline"
    PRESENT = "present"
    ABSENT = "absent"
    ORDER = "order"
    TABLE = "table"
    MATH = "math"


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

    # Normalize whitespace in the md_content
    md_content = re.sub(r"\s+", " ", md_content)

    # Remove markdown bold formatting (** or __ for bold)
    md_content = re.sub(r"\*\*(.*?)\*\*", r"\1", md_content)
    md_content = re.sub(r"__(.*?)__", r"\1", md_content)
    md_content = re.sub(r"</?b>", "", md_content)  # Remove <b> tags if they exist
    md_content = re.sub(r"</?i>", "", md_content)  # Remove <i> tags if they exist

    # Remove markdown italics formatting (* or _ for italics)
    md_content = re.sub(r"\*(.*?)\*", r"\1", md_content)
    md_content = re.sub(r"_(.*?)_", r"\1", md_content)

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
