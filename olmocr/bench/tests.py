import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Union

import numpy as np
from bs4 import BeautifulSoup
from fuzzysearch import find_near_matches
from rapidfuzz import fuzz
from tqdm import tqdm

from olmocr.repeatdetect import RepeatDetector

from .katex.render import compare_rendered_equations, render_equation


@dataclass
class TableData:
    """Class to hold table data and metadata about headers."""

    data: np.ndarray  # The actual table data
    header_rows: Set[int] = field(default_factory=set)  # Indices of rows that are headers
    header_cols: Set[int] = field(default_factory=set)  # Indices of columns that are headers
    col_headers: dict = field(default_factory=dict)  # Maps column index to header text, handling colspan
    row_headers: dict = field(default_factory=dict)  # Maps row index to header text, handling rowspan

    def __repr__(self) -> str:
        """Returns a concise representation of the TableData object for debugging."""
        return f"TableData(shape={self.data.shape}, header_rows={len(self.header_rows)}, header_cols={len(self.header_cols)})"

    def __str__(self) -> str:
        """Returns a pretty string representation of the table with header information."""
        output = []

        # Table dimensions
        output.append(f"Table: {self.data.shape[0]} rows × {self.data.shape[1]} columns")

        # Header info
        output.append(f"Header rows: {sorted(self.header_rows)}")
        output.append(f"Header columns: {sorted(self.header_cols)}")

        # Table content with formatting
        separator = "+" + "+".join(["-" * 17] * self.data.shape[1]) + "+"

        # Add a header for row indices
        output.append(separator)
        headers = [""] + [f"Column {i}" for i in range(self.data.shape[1])]
        output.append("| {:<5} | ".format("Row") + " | ".join(["{:<15}".format(h) for h in headers[1:]]) + " |")
        output.append(separator)

        # Format each row
        for i in range(min(self.data.shape[0], 15)):  # Limit to 15 rows for readability
            # Format cells, mark header cells
            cells = []
            for j in range(self.data.shape[1]):
                cell = str(self.data[i, j])
                if len(cell) > 15:
                    cell = cell[:12] + "..."
                # Mark header cells with *
                if i in self.header_rows or j in self.header_cols:
                    cell = f"*{cell}*"
                cells.append(cell)

            row_str = "| {:<5} | ".format(i) + " | ".join(["{:<15}".format(c) for c in cells]) + " |"
            output.append(row_str)
            output.append(separator)

        # If table is too large, indicate truncation
        if self.data.shape[0] > 15:
            output.append(f"... {self.data.shape[0] - 15} more rows ...")

        # Column header details if available
        if self.col_headers:
            output.append("\nColumn header mappings:")
            for col, headers in sorted(self.col_headers.items()):
                header_strs = [f"({row}, '{text}')" for row, text in headers]
                output.append(f"  Column {col}: {', '.join(header_strs)}")

        # Row header details if available
        if self.row_headers:
            output.append("\nRow header mappings:")
            for row, headers in sorted(self.row_headers.items()):
                header_strs = [f"({col}, '{text}')" for col, text in headers]
                output.append(f"  Row {row}: {', '.join(header_strs)}")

        return "\n".join(output)


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


def parse_markdown_tables(md_content: str) -> List[TableData]:
    """
    Extract and parse all markdown tables from the provided content.
    Uses a direct approach to find and parse tables, which is more robust for tables
    at the end of files or with irregular formatting.

    Args:
        md_content: The markdown content containing tables

    Returns:
        A list of TableData objects, each containing the table data and header information
    """
    # Split the content into lines and process line by line
    lines = md_content.strip().split("\n")

    parsed_tables = []
    current_table_lines = []
    in_table = False

    # Identify potential tables by looking for lines with pipe characters
    for i, line in enumerate(lines):
        # Check if this line has pipe characters (a table row indicator)
        if "|" in line:
            # If we weren't in a table before, start a new one
            if not in_table:
                in_table = True
                current_table_lines = [line]
            else:
                # Continue adding to the current table
                current_table_lines.append(line)
        else:
            # No pipes in this line, so if we were in a table, we've reached its end
            if in_table:
                # Process the completed table if it has at least 2 rows
                if len(current_table_lines) >= 2:
                    table_data = _process_table_lines(current_table_lines)
                    if table_data and len(table_data) > 0:
                        # Convert to numpy array for easier manipulation
                        max_cols = max(len(row) for row in table_data)
                        padded_data = [row + [""] * (max_cols - len(row)) for row in table_data]
                        table_array = np.array(padded_data)

                        # In markdown tables, the first row is typically a header row
                        header_rows = {0} if len(table_array) > 0 else set()

                        # Set up col_headers with first row headers for each column
                        col_headers = {}
                        if len(table_array) > 0:
                            for col_idx in range(table_array.shape[1]):
                                if col_idx < len(table_array[0]):
                                    col_headers[col_idx] = [(0, table_array[0, col_idx])]

                        # Set up row_headers with first column headers for each row
                        row_headers = {}
                        if table_array.shape[1] > 0:
                            for row_idx in range(1, table_array.shape[0]):  # Skip header row
                                row_headers[row_idx] = [(0, table_array[row_idx, 0])]  # First column as heading

                        # Create TableData object
                        parsed_tables.append(
                            TableData(
                                data=table_array,
                                header_rows=header_rows,
                                header_cols={0} if table_array.shape[1] > 0 else set(),  # First column as header
                                col_headers=col_headers,
                                row_headers=row_headers,
                            )
                        )
                in_table = False

    # Process the last table if we're still tracking one at the end of the file
    if in_table and len(current_table_lines) >= 2:
        table_data = _process_table_lines(current_table_lines)
        if table_data and len(table_data) > 0:
            # Convert to numpy array
            max_cols = max(len(row) for row in table_data)
            padded_data = [row + [""] * (max_cols - len(row)) for row in table_data]
            table_array = np.array(padded_data)

            # In markdown tables, the first row is typically a header row
            header_rows = {0} if len(table_array) > 0 else set()

            # Set up col_headers with first row headers for each column
            col_headers = {}
            if len(table_array) > 0:
                for col_idx in range(table_array.shape[1]):
                    if col_idx < len(table_array[0]):
                        col_headers[col_idx] = [(0, table_array[0, col_idx])]

            # Set up row_headers with first column headers for each row
            row_headers = {}
            if table_array.shape[1] > 0:
                for row_idx in range(1, table_array.shape[0]):  # Skip header row
                    row_headers[row_idx] = [(0, table_array[row_idx, 0])]  # First column as heading

            # Create TableData object
            parsed_tables.append(
                TableData(
                    data=table_array,
                    header_rows=header_rows,
                    header_cols={0} if table_array.shape[1] > 0 else set(),  # First column as header
                    col_headers=col_headers,
                    row_headers=row_headers,
                )
            )

    return parsed_tables


def _process_table_lines(table_lines: List[str]) -> List[List[str]]:
    """
    Process a list of lines that potentially form a markdown table.

    Args:
        table_lines: List of strings, each representing a line in a potential markdown table

    Returns:
        A list of rows, each a list of cell values
    """
    table_data = []
    separator_row_index = None

    # First, identify the separator row (the row with dashes)
    for i, line in enumerate(table_lines):
        # Check if this looks like a separator row (contains mostly dashes)
        content_without_pipes = line.replace("|", "").strip()
        if content_without_pipes and all(c in "- :" for c in content_without_pipes):
            separator_row_index = i
            break

    # Process each line, filtering out the separator row
    for i, line in enumerate(table_lines):
        # Skip the separator row
        if i == separator_row_index:
            continue

        # Skip lines that are entirely formatting
        if line.strip() and all(c in "- :|" for c in line):
            continue

        # Process the cells in this row
        cells = [cell.strip() for cell in line.split("|")]

        # Remove empty cells at the beginning and end (caused by leading/trailing pipes)
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]

        if cells:  # Only add non-empty rows
            table_data.append(cells)

    return table_data


def parse_html_tables(html_content: str) -> List[TableData]:
    """
    Extract and parse all HTML tables from the provided content.
    Identifies header rows and columns, and maps them properly handling rowspan/colspan.

    Args:
        html_content: The HTML content containing tables

    Returns:
        A list of TableData objects, each containing the table data and header information
    """
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")

    parsed_tables = []

    for table in tables:
        rows = table.find_all(["tr"])
        table_data = []
        header_rows = set()
        header_cols = set()
        col_headers = {}  # Maps column index to all header cells above it
        row_headers = {}  # Maps row index to all header cells to its left

        # Find rows inside thead tags - these are definitely header rows
        thead = table.find("thead")
        if thead:
            thead_rows = thead.find_all("tr")
            for tr in thead_rows:
                header_rows.add(rows.index(tr))

        # Initialize a grid to track filled cells due to rowspan/colspan
        cell_grid = {}
        col_span_info = {}  # Tracks which columns contain headers
        row_span_info = {}  # Tracks which rows contain headers

        # First pass: process each row to build the raw table data and identify headers
        for row_idx, row in enumerate(rows):
            cells = row.find_all(["th", "td"])
            row_data = []
            col_idx = 0

            # If there are th elements in this row, it's likely a header row
            if row.find("th"):
                header_rows.add(row_idx)

            for cell in cells:
                # Skip positions already filled by rowspans from above
                while (row_idx, col_idx) in cell_grid:
                    row_data.append(cell_grid[(row_idx, col_idx)])
                    col_idx += 1

                # Replace <br> and <br/> tags with newlines before getting text
                for br in cell.find_all("br"):
                    br.replace_with("\n")
                cell_text = cell.get_text().strip()

                # Handle rowspan/colspan
                rowspan = int(cell.get("rowspan", 1))
                colspan = int(cell.get("colspan", 1))

                # Add the cell to the row data
                row_data.append(cell_text)

                # Fill the grid for this cell and its rowspan/colspan
                for i in range(rowspan):
                    for j in range(colspan):
                        if i == 0 and j == 0:
                            continue  # Skip the main cell position
                        # For rowspan cells, preserve the text in all spanned rows
                        if j == 0 and i > 0:  # Only for cells directly below
                            cell_grid[(row_idx + i, col_idx + j)] = cell_text
                        else:
                            cell_grid[(row_idx + i, col_idx + j)] = ""  # Mark other spans as empty

                # If this is a header cell (th), mark it and its span
                if cell.name == "th":
                    # Mark columns as header columns
                    for j in range(colspan):
                        header_cols.add(col_idx + j)

                    # For rowspan, mark spanned rows as part of header
                    for i in range(1, rowspan):
                        if row_idx + i < len(rows):
                            header_rows.add(row_idx + i)

                    # Record this header for all spanned columns
                    for j in range(colspan):
                        curr_col = col_idx + j
                        if curr_col not in col_headers:
                            col_headers[curr_col] = []
                        col_headers[curr_col].append((row_idx, cell_text))

                        # Store which columns are covered by this header
                        if cell_text and colspan > 1:
                            if cell_text not in col_span_info:
                                col_span_info[cell_text] = set()
                            col_span_info[cell_text].add(curr_col)

                    # Store which rows are covered by this header for rowspan
                    if cell_text and rowspan > 1:
                        if cell_text not in row_span_info:
                            row_span_info[cell_text] = set()
                        for i in range(rowspan):
                            row_span_info[cell_text].add(row_idx + i)

                # Also handle row headers from data cells that have rowspan
                if cell.name == "td" and rowspan > 1 and col_idx in header_cols:
                    for i in range(1, rowspan):
                        if row_idx + i < len(rows):
                            if row_idx + i not in row_headers:
                                row_headers[row_idx + i] = []
                            row_headers[row_idx + i].append((col_idx, cell_text))

                col_idx += colspan

            # Pad the row if needed to handle different row lengths
            table_data.append(row_data)

        # Second pass: expand headers to cells that should inherit them
        # First handle column headers
        for header_text, columns in col_span_info.items():
            for col in columns:
                # Add this header to all columns it spans over
                for row_idx in range(len(table_data)):
                    if row_idx not in header_rows:  # Only apply to data rows
                        for j in range(col, len(table_data[row_idx]) if row_idx < len(table_data) else 0):
                            # Add header info to data cells in these columns
                            if j not in col_headers:
                                col_headers[j] = []
                            if not any(h[1] == header_text for h in col_headers[j]):
                                header_row = min([r for r, t in col_headers.get(col, [(0, "")])])
                                col_headers[j].append((header_row, header_text))

        # Handle row headers
        for header_text, rows in row_span_info.items():
            for row in rows:
                if row < len(table_data):
                    # Find first header column
                    header_col = min(header_cols) if header_cols else 0
                    if row not in row_headers:
                        row_headers[row] = []
                    if not any(h[1] == header_text for h in row_headers.get(row, [])):
                        row_headers[row].append((header_col, header_text))

        # Process regular row headers - each cell in a header column becomes a header for its row
        for col_idx in header_cols:
            for row_idx, row in enumerate(table_data):
                if col_idx < len(row) and row[col_idx].strip():
                    if row_idx not in row_headers:
                        row_headers[row_idx] = []
                    if not any(h[1] == row[col_idx] for h in row_headers.get(row_idx, [])):
                        row_headers[row_idx].append((col_idx, row[col_idx]))

        # Calculate max columns for padding
        max_cols = max(len(row) for row in table_data) if table_data else 0

        # Ensure all rows have the same number of columns
        if table_data:
            padded_data = [row + [""] * (max_cols - len(row)) for row in table_data]
            table_array = np.array(padded_data)

            # Create TableData object with the table and header information
            parsed_tables.append(
                TableData(data=table_array, header_rows=header_rows, header_cols=header_cols, col_headers=col_headers, row_headers=row_headers)
            )

    return parsed_tables


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
            # Removed debug print statement
            table_array = table_data.data
            header_rows = table_data.header_rows
            header_cols = table_data.header_cols

            # Find all cells that match the target cell using fuzzy matching
            matches = []
            for i in range(table_array.shape[0]):
                for j in range(table_array.shape[1]):
                    cell_content = normalize_text(table_array[i, j])
                    similarity = fuzz.ratio(self.cell, cell_content) / 100.0

                    if similarity >= threshold:
                        matches.append((i, j))

            # If no matches found in this table, continue to the next table
            if not matches:
                continue

            # Check the relationships for each matching cell
            for row_idx, col_idx in matches:
                all_relationships_satisfied = True
                current_failed_reasons = []

                # Check up relationship
                if self.up and row_idx > 0:
                    up_cell = normalize_text(table_array[row_idx - 1, col_idx])
                    up_similarity = fuzz.ratio(self.up, up_cell) / 100.0
                    if up_similarity < max(0.5, 1.0 - (self.max_diffs / (len(self.up) if len(self.up) > 0 else 1))):
                        all_relationships_satisfied = False
                        current_failed_reasons.append(f"Cell above '{up_cell}' doesn't match expected '{self.up}' (similarity: {up_similarity:.2f})")

                # Check down relationship
                if self.down and row_idx < table_array.shape[0] - 1:
                    down_cell = normalize_text(table_array[row_idx + 1, col_idx])
                    down_similarity = fuzz.ratio(self.down, down_cell) / 100.0
                    if down_similarity < max(0.5, 1.0 - (self.max_diffs / (len(self.down) if len(self.down) > 0 else 1))):
                        all_relationships_satisfied = False
                        current_failed_reasons.append(f"Cell below '{down_cell}' doesn't match expected '{self.down}' (similarity: {down_similarity:.2f})")

                # Check left relationship
                if self.left and col_idx > 0:
                    left_cell = normalize_text(table_array[row_idx, col_idx - 1])
                    left_similarity = fuzz.ratio(self.left, left_cell) / 100.0
                    if left_similarity < max(0.5, 1.0 - (self.max_diffs / (len(self.left) if len(self.left) > 0 else 1))):
                        all_relationships_satisfied = False
                        current_failed_reasons.append(
                            f"Cell to the left '{left_cell}' doesn't match expected '{self.left}' (similarity: {left_similarity:.2f})"
                        )

                # Check right relationship
                if self.right and col_idx < table_array.shape[1] - 1:
                    right_cell = normalize_text(table_array[row_idx, col_idx + 1])
                    right_similarity = fuzz.ratio(self.right, right_cell) / 100.0
                    if right_similarity < max(0.5, 1.0 - (self.max_diffs / (len(self.right) if len(self.right) > 0 else 1))):
                        all_relationships_satisfied = False
                        current_failed_reasons.append(
                            f"Cell to the right '{right_cell}' doesn't match expected '{self.right}' (similarity: {right_similarity:.2f})"
                        )

                # Check top heading relationship
                if self.top_heading:
                    # Try to find a match in the column headers
                    top_heading_found = False
                    best_match = ""
                    best_similarity = 0

                    # Check the col_headers dictionary first (this handles colspan properly)
                    if col_idx in table_data.col_headers:
                        for _, header_text in table_data.col_headers[col_idx]:
                            header_text = normalize_text(header_text)
                            similarity = fuzz.ratio(self.top_heading, header_text) / 100.0
                            if similarity > best_similarity:
                                best_similarity = similarity
                                best_match = header_text
                                if best_similarity >= max(0.5, 1.0 - (self.max_diffs / (len(self.top_heading) if len(self.top_heading) > 0 else 1))):
                                    top_heading_found = True
                                    break

                    # If no match found in col_headers, fall back to checking header rows
                    if not top_heading_found and header_rows:
                        for i in sorted(header_rows):
                            if i < row_idx and table_array[i, col_idx].strip():
                                header_text = normalize_text(table_array[i, col_idx])
                                similarity = fuzz.ratio(self.top_heading, header_text) / 100.0
                                if similarity > best_similarity:
                                    best_similarity = similarity
                                    best_match = header_text
                                    if best_similarity >= max(0.5, 1.0 - (self.max_diffs / (len(self.top_heading) if len(self.top_heading) > 0 else 1))):
                                        top_heading_found = True
                                        break

                    # If still no match, use any non-empty cell above as a last resort
                    if not top_heading_found and not best_match and row_idx > 0:
                        for i in range(row_idx):
                            if table_array[i, col_idx].strip():
                                header_text = normalize_text(table_array[i, col_idx])
                                similarity = fuzz.ratio(self.top_heading, header_text) / 100.0
                                if similarity > best_similarity:
                                    best_similarity = similarity
                                    best_match = header_text

                    if not best_match:
                        all_relationships_satisfied = False
                        current_failed_reasons.append(f"No top heading found for cell at ({row_idx}, {col_idx})")
                    elif best_similarity < max(0.5, 1.0 - (self.max_diffs / (len(self.top_heading) if len(self.top_heading) > 0 else 1))):
                        all_relationships_satisfied = False
                        current_failed_reasons.append(
                            f"Top heading '{best_match}' doesn't match expected '{self.top_heading}' (similarity: {best_similarity:.2f})"
                        )

                # Check left heading relationship
                if self.left_heading:
                    # Try to find a match in the row headers
                    left_heading_found = False
                    best_match = ""
                    best_similarity = 0

                    # Check the row_headers dictionary first (this handles rowspan properly)
                    if row_idx in table_data.row_headers:
                        for _, header_text in table_data.row_headers[row_idx]:
                            header_text = normalize_text(header_text)
                            similarity = fuzz.ratio(self.left_heading, header_text) / 100.0
                            if similarity > best_similarity:
                                best_similarity = similarity
                                best_match = header_text
                                if best_similarity >= max(0.5, 1.0 - (self.max_diffs / (len(self.left_heading) if len(self.left_heading) > 0 else 1))):
                                    left_heading_found = True
                                    break

                    # If no match found in row_headers, fall back to checking header columns
                    if not left_heading_found and header_cols:
                        for j in sorted(header_cols):
                            if j < col_idx and table_array[row_idx, j].strip():
                                header_text = normalize_text(table_array[row_idx, j])
                                similarity = fuzz.ratio(self.left_heading, header_text) / 100.0
                                if similarity > best_similarity:
                                    best_similarity = similarity
                                    best_match = header_text
                                    if best_similarity >= max(0.5, 1.0 - (self.max_diffs / (len(self.left_heading) if len(self.left_heading) > 0 else 1))):
                                        left_heading_found = True
                                        break

                    # If still no match, use any non-empty cell to the left as a last resort
                    if not left_heading_found and not best_match and col_idx > 0:
                        for j in range(col_idx):
                            if table_array[row_idx, j].strip():
                                header_text = normalize_text(table_array[row_idx, j])
                                similarity = fuzz.ratio(self.left_heading, header_text) / 100.0
                                if similarity > best_similarity:
                                    best_similarity = similarity
                                    best_match = header_text

                    if not best_match:
                        all_relationships_satisfied = False
                        current_failed_reasons.append(f"No left heading found for cell at ({row_idx}, {col_idx})")
                    elif best_similarity < max(0.5, 1.0 - (self.max_diffs / (len(self.left_heading) if len(self.left_heading) > 0 else 1))):
                        all_relationships_satisfied = False
                        current_failed_reasons.append(
                            f"Left heading '{best_match}' doesn't match expected '{self.left_heading}' (similarity: {best_similarity:.2f})"
                        )

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
