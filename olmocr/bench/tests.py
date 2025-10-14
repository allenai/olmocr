import json
import os
import re
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Union
from bs4 import BeautifulSoup
from fuzzysearch import find_near_matches
from rapidfuzz import fuzz
from tqdm import tqdm

from olmocr.repeatdetect import RepeatDetector

from .katex.render import compare_rendered_equations, render_equation

# Tell pytest these are not tests
__test__ = False

@dataclass(frozen=True)
class TableData:
    """Class which holds table data as a graph of cells. Ex. you can access the value at any row, col
    However, you can also ask, given a row, col, which set of row,col pairs is "left", "right", "up", and "down"
    from that one. There can be multiple values returned, because rowspans and colspans mean that you can have multiple cells in each direction.

    Further more, you can also query "top_heading" and "left_heading". Where we also mark cells that are considered "headings", ex. if they are in a thead
    html tag.
    Then, for each cell, you may request top_heading/left_heading, which returns all cell positions that are headings in those directions
    """
    cell_text: Dict[tuple[int, int], str] # Stores map from row, col to cell text
    heading_cells: Set[tuple[int, int]] # Contains the row, col pairs which are headings

    up_relations: Dict[tuple[int, int], Set[tuple[int, int]]]
    down_relations: Dict[tuple[int, int], Set[tuple[int, int]]]
    left_relations: Dict[tuple[int, int], Set[tuple[int, int]]]
    right_relations: Dict[tuple[int, int], Set[tuple[int, int]]]

    top_heading_relations: Dict[tuple[int, int], Set[tuple[int, int]]]
    left_heading_relations: Dict[tuple[int, int], Set[tuple[int, int]]]


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


def _safe_span_int(value: Optional[Union[str, int]], default: int = 1) -> int:
    """Convert rowspan/colspan attributes to positive integers."""
    if value in (None, "", 0):
        return default
    try:
        span = int(value)
    except (TypeError, ValueError):
        return default
    if span <= 0:
        return default
    return span


def _build_table_data_from_specs(row_specs: List[List[Dict[str, Union[str, int, bool]]]]) -> Optional[TableData]:
    """
    Build a TableData object from a list of row specifications.

    Each row specification is a list of dictionaries with keys:
        - text: cell text content
        - rowspan: integer rowspan (>= 1)
        - colspan: integer colspan (>= 1)
        - is_heading: bool indicating if the cell should be treated as a heading
    """
    if not row_specs:
        return None

    cell_text: Dict[Tuple[int, int], str] = {}
    heading_cells: Set[Tuple[int, int]] = set()
    cell_meta: Dict[Tuple[int, int], Dict[str, Union[int, bool]]] = {}
    occupancy: List[List[Optional[Tuple[int, int]]]] = []
    active_rowspans: List[Optional[Tuple[Tuple[int, int], int]]] = []

    for row_idx, cells in enumerate(row_specs):
        row_entries: List[Optional[Tuple[int, int]]] = []
        col_index = 0
        spec_idx = 0
        total_specs = len(cells)

        while spec_idx < total_specs or col_index < len(active_rowspans):
            if col_index < len(active_rowspans) and active_rowspans[col_index] is not None:
                cell_id, remaining = active_rowspans[col_index]
                row_entries.append(cell_id)
                remaining -= 1
                active_rowspans[col_index] = (cell_id, remaining) if remaining > 0 else None
                col_index += 1
                continue

            if spec_idx >= total_specs:
                if col_index < len(active_rowspans):
                    row_entries.append(None)
                    col_index += 1
                    continue
                break

            spec = cells[spec_idx]
            spec_idx += 1

            text = spec.get("text", "") or ""
            rowspan = spec.get("rowspan", 1)
            colspan = spec.get("colspan", 1)
            is_heading = bool(spec.get("is_heading", False))

            rowspan = rowspan if isinstance(rowspan, int) else _safe_span_int(rowspan)
            colspan = colspan if isinstance(colspan, int) else _safe_span_int(colspan)
            rowspan = max(1, rowspan)
            colspan = max(1, colspan)

            cell_id = (row_idx, col_index)
            cell_text[cell_id] = text
            if is_heading:
                heading_cells.add(cell_id)

            cell_meta[cell_id] = {
                "row": row_idx,
                "col": col_index,
                "rowspan": rowspan,
                "colspan": colspan,
            }

            required_len = col_index + colspan
            if len(active_rowspans) < required_len:
                active_rowspans.extend([None] * (required_len - len(active_rowspans)))

            for offset in range(colspan):
                current_col = col_index + offset
                row_entries.append(cell_id)
                if rowspan > 1:
                    active_rowspans[current_col] = (cell_id, rowspan - 1)
                else:
                    active_rowspans[current_col] = None

            col_index += colspan

        occupancy.append(row_entries)

    # Flush any remaining active rowspans into additional rows
    while any(entry is not None for entry in active_rowspans):
        row_entries: List[Optional[Tuple[int, int]]] = []
        for col_index, span_entry in enumerate(active_rowspans):
            if span_entry is None:
                row_entries.append(None)
                continue
            cell_id, remaining = span_entry
            row_entries.append(cell_id)
            remaining -= 1
            active_rowspans[col_index] = (cell_id, remaining) if remaining > 0 else None
        occupancy.append(row_entries)

    if not cell_text:
        return None

    # Normalize occupancy to a consistent width based on populated columns
    valid_columns = {idx for row in occupancy for idx, value in enumerate(row) if value is not None}
    if valid_columns:
        table_width = max(valid_columns) + 1
        for row in occupancy:
            if len(row) < table_width:
                row.extend([None] * (table_width - len(row)))
            elif len(row) > table_width:
                del row[table_width:]
    else:
        return None

    table_height = len(occupancy)

    up_rel = defaultdict(set)
    down_rel = defaultdict(set)
    left_rel = defaultdict(set)
    right_rel = defaultdict(set)
    top_heading_rel = defaultdict(set)
    left_heading_rel = defaultdict(set)

    for cell_id, meta in cell_meta.items():
        row_start = meta["row"]
        col_start = meta["col"]
        rowspan = meta["rowspan"]
        colspan = meta["colspan"]
        row_end = row_start + rowspan - 1
        col_end = col_start + colspan - 1

        # Right relations
        for row in range(row_start, row_end + 1):
            for col in range(col_end + 1, table_width):
                neighbor = occupancy[row][col]
                if neighbor is None or neighbor == cell_id:
                    continue
                right_rel[cell_id].add(neighbor)
                break

        # Left relations
        for row in range(row_start, row_end + 1):
            for col in range(col_start - 1, -1, -1):
                neighbor = occupancy[row][col]
                if neighbor is None or neighbor == cell_id:
                    continue
                left_rel[cell_id].add(neighbor)
                break

        # Down relations
        for col in range(col_start, col_end + 1):
            for row in range(row_end + 1, table_height):
                if col >= len(occupancy[row]):
                    continue
                neighbor = occupancy[row][col]
                if neighbor is None or neighbor == cell_id:
                    continue
                down_rel[cell_id].add(neighbor)
                break

        # Up relations
        for col in range(col_start, col_end + 1):
            for row in range(row_start - 1, -1, -1):
                neighbor = occupancy[row][col]
                if neighbor is None or neighbor == cell_id:
                    continue
                up_rel[cell_id].add(neighbor)
                break

        # Top heading relations
        for col in range(col_start, col_end + 1):
            seen = set()
            for row in range(row_start - 1, -1, -1):
                neighbor = occupancy[row][col]
                if neighbor is None or neighbor == cell_id or neighbor in seen:
                    continue
                seen.add(neighbor)
                if neighbor in heading_cells:
                    top_heading_rel[cell_id].add(neighbor)

        # Left heading relations
        for row in range(row_start, row_end + 1):
            seen = set()
            for col in range(col_start - 1, -1, -1):
                neighbor = occupancy[row][col]
                if neighbor is None or neighbor == cell_id or neighbor in seen:
                    continue
                seen.add(neighbor)
                if neighbor in heading_cells:
                    left_heading_rel[cell_id].add(neighbor)

    # Ensure every cell has an entry in relations dictionaries
    up_relations = {cell_id: set(up_rel[cell_id]) for cell_id in cell_text}
    down_relations = {cell_id: set(down_rel[cell_id]) for cell_id in cell_text}
    left_relations = {cell_id: set(left_rel[cell_id]) for cell_id in cell_text}
    right_relations = {cell_id: set(right_rel[cell_id]) for cell_id in cell_text}
    top_heading_relations = {cell_id: set(top_heading_rel[cell_id]) for cell_id in cell_text}
    left_heading_relations = {cell_id: set(left_heading_rel[cell_id]) for cell_id in cell_text}

    return TableData(
        cell_text=cell_text,
        heading_cells=heading_cells,
        up_relations=up_relations,
        down_relations=down_relations,
        left_relations=left_relations,
        right_relations=right_relations,
        top_heading_relations=top_heading_relations,
        left_heading_relations=left_heading_relations,
    )


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
                        row_specs: List[List[Dict[str, Union[str, int, bool]]]] = []
                        for row_idx, row in enumerate(table_data):
                            row_specs.append(
                                [
                                    {
                                        "text": cell,
                                        "rowspan": 1,
                                        "colspan": 1,
                                        "is_heading": row_idx == 0 or col_idx == 0,
                                    }
                                    for col_idx, cell in enumerate(row)
                                ]
                            )

                        table = _build_table_data_from_specs(row_specs)
                        if table:
                            parsed_tables.append(table)
                in_table = False

    # Process the last table if we're still tracking one at the end of the file
    if in_table and len(current_table_lines) >= 2:
        table_data = _process_table_lines(current_table_lines)
        if table_data and len(table_data) > 0:
            row_specs = []
            for row_idx, row in enumerate(table_data):
                row_specs.append(
                    [
                        {
                            "text": cell,
                            "rowspan": 1,
                            "colspan": 1,
                            "is_heading": row_idx == 0 or col_idx == 0,
                        }
                        for col_idx, cell in enumerate(row)
                    ]
                )

            table = _build_table_data_from_specs(row_specs)
            if table:
                parsed_tables.append(table)

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
        rows = table.find_all("tr")
        if not rows:
            continue

        row_specs: List[List[Dict[str, Union[str, int, bool]]]] = []
        total_rows = len(rows)

        for row_idx, row in enumerate(rows):
            cells = row.find_all(["th", "td"], recursive=False)
            heading_context = row.find_parent("thead") is not None

            row_spec: List[Dict[str, Union[str, int, bool]]] = []
            for cell in cells:
                for br in cell.find_all("br"):
                    br.replace_with("\n")

                text = cell.get_text(separator="\n").strip()
                raw_rowspan = cell.get("rowspan")
                raw_colspan = cell.get("colspan")

                rowspan = _safe_span_int(raw_rowspan, 1)
                colspan = _safe_span_int(raw_colspan, 1)

                # HTML specifies rowspan=0 to extend to the end of the table section
                if isinstance(raw_rowspan, str) and raw_rowspan.strip() == "0":
                    rowspan = max(1, total_rows - row_idx)

                is_heading = cell.name == "th" or heading_context

                row_spec.append({"text": text, "rowspan": rowspan, "colspan": colspan, "is_heading": is_heading})

            row_specs.append(row_spec)

        table_data = _build_table_data_from_specs(row_specs)
        if table_data:
            parsed_tables.append(table_data)

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
            normalized_cell_text = {pos: (normalize_text(text) or "") for pos, text in table_data.cell_text.items()}
            matches = []
            for position, cell_content in normalized_cell_text.items():
                similarity = fuzz.ratio(self.cell, cell_content) / 100.0
                if similarity >= threshold:
                    matches.append(position)

            if not matches:
                continue

            def evaluate_relation(
                target_pos: Tuple[int, int],
                expected_text: str,
                relations: Dict[Tuple[int, int], Set[Tuple[int, int]]],
                label: str,
            ) -> Optional[str]:
                if not expected_text:
                    return None

                neighbors = relations.get(target_pos, set())
                if not neighbors:
                    return f"No {label} found for cell at {target_pos}"

                direction_threshold = max(0.5, 1.0 - (self.max_diffs / max(len(expected_text), 1)))
                best_similarity = -1.0
                best_match = ""

                for neighbor_pos in neighbors:
                    neighbor_text = normalized_cell_text.get(neighbor_pos, "")
                    similarity = fuzz.ratio(expected_text, neighbor_text) / 100.0
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = neighbor_text
                    
                    if best_similarity >= direction_threshold:
                        return None

                if best_match:
                    return f"{label.title()} '{best_match}' doesn't match expected '{expected_text}' (similarity: {best_similarity:.2f})"
                return f"No {label} found for cell at {target_pos}"

            for target_pos in matches:
                all_relationships_satisfied = True
                current_failed_reasons = []

                for expected, relations, label in [
                    (self.up, table_data.up_relations, "up"),
                    (self.down, table_data.down_relations, "down"),
                    (self.left, table_data.left_relations, "left"),
                    (self.right, table_data.right_relations, "right"),
                ]:
                    if expected:
                        error = evaluate_relation(target_pos, expected, relations, label)
                        if error:
                            all_relationships_satisfied = False
                            current_failed_reasons.append(error)

                if self.top_heading:
                    error = evaluate_relation(target_pos, self.top_heading, table_data.top_heading_relations, "top heading")
                    if error:
                        all_relationships_satisfied = False
                        current_failed_reasons.append(error)

                if self.left_heading:
                    error = evaluate_relation(target_pos, self.left_heading, table_data.left_heading_relations, "left heading")
                    if error:
                        all_relationships_satisfied = False
                        current_failed_reasons.append(error)

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
