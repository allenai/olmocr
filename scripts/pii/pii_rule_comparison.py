#!/usr/bin/env python3
"""
Compare PII Detection Rules and Calculate IoU

This script processes documents and their attributes from S3 or local storage,
applies different rules for PII detection, and calculates the
Intersection over Union (IoU) to measure how well they overlap.

How it works:
1. Documents are stored in one location (--docs-folder)
2. Attributes are automatically found in ../attributes/ relative to the documents folder
3. The script merges documents with all available attributes by matching filenames and document IDs
4. PII detection rules are applied to the merged documents
5. IoU and other metrics are calculated to compare the results

Expected folder structure:
- s3://bucket/path/documents/ - Contains the main document JSONL files
- s3://bucket/path/attributes/ - Contains attributes that can be matched with documents by ID

Document and attribute matching:
- Files are matched by basename (example.jsonl in documents matches example.jsonl in attributes)
- Within each file, documents are matched by their "id" field
- When a match is found, attributes from the attribute file are merged into the document

Example usage:
python pii_rule_comparison.py \
    --docs-folder s3://bucket/path/documents \
    --ref-rule "gpt_4_1_contains_pii:any" \
    --hyp-rule "gpt_4_1_contains_email_addresses:any" \
    --output-file iou_results.json \
    --recursive

Rule expression syntax:
- Simple rule: "attribute_name:rule_type" where rule_type is "any" or "all"
- Boolean expressions: "not rule1:any and rule2:all"
- Parentheses for grouping: "(rule1:any or rule2:any) and not rule3:all"
"""

import argparse
import base64
import gzip
import html as pyhtml
import io
import json
import logging
import os
from collections import defaultdict
from enum import Enum, auto
from io import BytesIO
from pathlib import Path

import boto3
import numpy as np
import zstandard as zstd
from matplotlib.figure import Figure

# Initialize logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# Define token types for the rule expression parser
class TokenType(Enum):
    RULE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    EOF = auto()


class Token:
    """Token for rule expression parsing"""

    def __init__(self, type, value=None):
        self.type = type
        self.value = value

    def __repr__(self):
        if self.value:
            return f"Token({self.type}, {self.value})"
        return f"Token({self.type})"


class ExpressionNode:
    """Base class for expression tree nodes"""

    pass


class RuleNode(ExpressionNode):
    """Leaf node representing a single rule"""

    def __init__(self, attribute_name, rule_type):
        self.attribute_name = attribute_name
        self.rule_type = rule_type

    def __repr__(self):
        return f"Rule({self.attribute_name}:{self.rule_type})"


class NotNode(ExpressionNode):
    """Unary NOT operation node"""

    def __init__(self, operand):
        self.operand = operand

    def __repr__(self):
        return f"NOT({self.operand})"


class BinaryNode(ExpressionNode):
    """Binary operation (AND/OR) node"""

    def __init__(self, left, right, operator):
        self.left = left
        self.right = right
        self.operator = operator

    def __repr__(self):
        return f"{self.operator}({self.left}, {self.right})"


def parse_args():
    parser = argparse.ArgumentParser(description="Compare PII detection rules and calculate IoU")
    parser.add_argument("--docs-folder", required=True, help="Documents folder path containing JSONL files (local or s3://)")
    parser.add_argument("--attr-folder", help="Attributes folder path (if different from standard ../attributes/ location)")
    parser.add_argument(
        "--ref-rule",
        required=True,
        help="""Reference rule expression. Can be a simple rule in format 'attribute_name:rule_type',
                        where rule_type is 'any' or 'all'. Or a boolean expression like
                        'not rule1:any and rule2:all' or '(rule1:any or rule2:any) and not rule3:all'""",
    )
    parser.add_argument(
        "--hyp-rule",
        required=True,
        help="""Hypothesis rule expression. Can be a simple rule in format 'attribute_name:rule_type',
                        where rule_type is 'any' or 'all'. Or a boolean expression like
                        'not rule1:any and rule2:all' or '(rule1:any or rule2:any) and not rule3:all'""",
    )
    parser.add_argument("--output-dir", default="results", help="Directory to save HTML result files")
    parser.add_argument("--aws-profile", help="AWS profile for S3 access")
    parser.add_argument("--recursive", action="store_true", help="Recursively process folder structure")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging for more detailed output")
    parser.add_argument("--disable-plots", action="store_true", help="Disable CDF plots generation")
    parser.add_argument("--max-plots", type=int, default=200, help="Maximum number of CDF plots to generate (default: 200)")
    return parser.parse_args()


def parse_s3_path(s3_path):
    """Parse S3 path into bucket and prefix."""
    parts = s3_path.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix


def get_attributes_folder(docs_folder, attr_folder=None):
    """
    Determine the attributes folder path based on the documents folder.

    Args:
        docs_folder: Path to the documents folder
        attr_folder: Manually specified attributes folder (optional)

    Returns:
        Path to the attributes folder
    """
    if attr_folder:
        return attr_folder

    # If no attributes folder specified, derive it from the documents folder
    if docs_folder.startswith("s3://"):
        # For S3 paths
        bucket, prefix = parse_s3_path(docs_folder)

        # Remove trailing slashes for consistent path handling
        prefix = prefix.rstrip("/")

        # Check if the documents folder is in a 'documents' directory
        if prefix.endswith("/documents"):
            # Replace /documents with /attributes
            attr_prefix = prefix[: -len("/documents")] + "/attributes"
        else:
            # Otherwise, add a parent level and include 'attributes'
            path_parts = prefix.split("/")
            # Remove the last part (assumed to be the documents directory name)
            path_parts.pop()
            # Add 'attributes'
            path_parts.append("attributes")
            attr_prefix = "/".join(path_parts)

        return f"s3://{bucket}/{attr_prefix}"
    else:
        # For local paths
        docs_path = Path(docs_folder)

        # Check if the documents folder is in a 'documents' directory
        if docs_path.name == "documents":
            # Replace /documents with /attributes
            attr_path = docs_path.parent / "attributes"
        else:
            # Otherwise, add a parent level and include 'attributes'
            attr_path = docs_path.parent / "attributes"

        return str(attr_path)


def get_s3_bytes(s3_client, s3_path):
    """Get bytes from S3 object."""
    bucket, key = parse_s3_path(s3_path)
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def list_jsonl_files(path, s3_client=None, recursive=False):
    """List all JSONL files in the given path, locally or in S3."""
    jsonl_files = []

    if path.startswith("s3://"):
        bucket, prefix = parse_s3_path(path)
        prefix = prefix.rstrip("/") + "/"

        # List objects in S3 bucket with given prefix
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if "Contents" in page:
                for obj in page["Contents"]:
                    key = obj["Key"]
                    if (
                        key.endswith(".jsonl")
                        or key.endswith(".json")
                        or key.endswith(".jsonl.gz")
                        or key.endswith(".jsonl.zst")
                        or key.endswith(".jsonl.ztd")
                        or key.endswith(".jsonl.zstd")
                    ):
                        jsonl_files.append(f"s3://{bucket}/{key}")
    else:
        # Local file system
        path_obj = Path(path)
        if recursive:
            for file_path in path_obj.rglob("*"):
                if (
                    file_path.name.endswith(".jsonl")
                    or file_path.name.endswith(".json")
                    or file_path.name.endswith(".jsonl.gz")
                    or file_path.name.endswith(".jsonl.zst")
                    or file_path.name.endswith(".jsonl.ztd")
                    or file_path.name.endswith(".jsonl.zstd")
                ):
                    jsonl_files.append(str(file_path))
        else:
            for file_path in path_obj.glob("*"):
                if (
                    file_path.name.endswith(".jsonl")
                    or file_path.name.endswith(".json")
                    or file_path.name.endswith(".jsonl.gz")
                    or file_path.name.endswith(".jsonl.zst")
                    or file_path.name.endswith(".jsonl.ztd")
                    or file_path.name.endswith(".jsonl.zstd")
                ):
                    jsonl_files.append(str(file_path))

    return jsonl_files


def load_jsonl_file(file_path, s3_client=None):
    """Load and decompress a JSONL file, either from local or S3."""
    try:
        # Get file content
        if file_path.startswith("s3://"):
            if s3_client is None:
                raise ValueError("S3 client is required for S3 paths")
            raw_data = get_s3_bytes(s3_client, file_path)
        else:
            with open(file_path, "rb") as f:
                raw_data = f.read()

        # Decompress if needed
        if file_path.endswith(".gz"):
            decompressed = gzip.decompress(raw_data)
        elif file_path.endswith((".zst", ".ztd", ".zstd")):
            try:
                # First try with standard decompression
                dctx = zstd.ZstdDecompressor()
                decompressed = dctx.decompress(raw_data)
            except zstd.ZstdError as e:
                # If that fails, try with stream decompression
                logger.warning(f"Standard zstd decompression failed for {file_path}, trying stream decompression: {e}")

                try:
                    # Try with content-size not required
                    dctx = zstd.ZstdDecompressor(max_window_size=2147483648)  # Use a large window size
                    decompressor = dctx.stream_reader(io.BytesIO(raw_data))
                    decompressed = decompressor.read()
                except Exception as inner_e:
                    # If both methods fail, try with chunking
                    logger.warning(f"Stream decompression also failed, trying chunked reading: {inner_e}")

                    # Chunked reading approach
                    buffer = io.BytesIO()
                    dctx = zstd.ZstdDecompressor(max_window_size=2147483648)
                    with dctx.stream_reader(io.BytesIO(raw_data)) as reader:
                        while True:
                            chunk = reader.read(16384)  # Read in 16KB chunks
                            if not chunk:
                                break
                            buffer.write(chunk)

                    buffer.seek(0)
                    decompressed = buffer.read()
        else:
            decompressed = raw_data

        # Parse JSON lines
        lines = decompressed.decode("utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]

    except Exception as e:
        logger.error(f"Error loading file {file_path}: {e}")
        return []


def load_documents_and_attributes(docs_folder, attr_folder, s3_client=None, recursive=False):
    """
    Load documents and merge them with their attributes from all subdirectories.

    Args:
        docs_folder: Path to the documents folder
        attr_folder: Path to the attributes folder
        s3_client: S3 client for S3 paths
        recursive: Whether to process folders recursively

    Returns:
        List of documents with their attributes merged in
    """
    try:
        # List all document files
        logger.info(f"Finding document files in: {docs_folder}")
        doc_files = list_jsonl_files(docs_folder, s3_client, recursive)
        logger.info(f"Found {len(doc_files)} document files")

        if not doc_files:
            logger.warning(f"No document files found in {docs_folder}. Check the path and permissions.")
            return []

        # Get all attribute subdirectories if it's an S3 path
        attr_subdirs = []
        if attr_folder.startswith("s3://"):
            bucket, attr_prefix = parse_s3_path(attr_folder)
            attr_prefix = attr_prefix.rstrip("/") + "/"

            # List top-level directories in the attributes folder
            logger.info(f"Finding attribute subdirectories in: {attr_folder}")

            # Using delimiter parameter to list "directories" in S3
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=attr_prefix, Delimiter="/"):
                if "CommonPrefixes" in page:
                    for prefix in page["CommonPrefixes"]:
                        subdir = f"s3://{bucket}/{prefix['Prefix']}"
                        attr_subdirs.append(subdir)
                        logger.info(f"Found attribute subdirectory: {subdir}")

            # If no subdirectories, use the main folder
            if not attr_subdirs:
                attr_subdirs = [attr_folder]
                logger.info(f"No subdirectories found, using main attribute folder: {attr_folder}")
        else:
            # For local paths
            attr_path = Path(attr_folder)
            if attr_path.exists() and attr_path.is_dir():
                # Get subdirectories
                subdirs = [str(d) for d in attr_path.iterdir() if d.is_dir()]
                if subdirs:
                    attr_subdirs = subdirs
                    logger.info(f"Found {len(attr_subdirs)} attribute subdirectories")
                else:
                    attr_subdirs = [attr_folder]
                    logger.info(f"No subdirectories found, using main attribute folder: {attr_folder}")
            else:
                logger.warning(f"Attributes folder not found or not a directory: {attr_folder}")
                attr_subdirs = []

        # Load and merge documents with all attributes from all subdirectories
        merged_docs = []
        docs_by_id = {}
        total_attr_files = 0

        # First, load all document files and create a document-by-ID mapping
        for doc_path in doc_files:
            try:
                if doc_path.startswith("s3://"):
                    _, doc_key = parse_s3_path(doc_path)
                    basename = os.path.basename(doc_key)
                else:
                    basename = os.path.basename(doc_path)

                # Load documents
                docs = load_jsonl_file(doc_path, s3_client)
                if not docs:
                    logger.warning(f"No documents loaded from {basename} (path: {doc_path})")
                    continue

                logger.info(f"Loaded {len(docs)} documents from {basename}")

                # Add to the merged documents list and create ID mapping
                for doc in docs:
                    if "id" in doc:
                        # If the document already exists, use the one with attributes if possible
                        doc_id = doc["id"]
                        if doc_id in docs_by_id:
                            if "attributes" not in doc and "attributes" in docs_by_id[doc_id]:
                                # Keep the existing document that has attributes
                                continue

                        # Initialize attributes if needed
                        if "attributes" not in doc:
                            doc["attributes"] = {}

                        # Add to the mapping
                        docs_by_id[doc_id] = doc
                    else:
                        # No ID, can't match with attributes
                        if "attributes" not in doc:
                            doc["attributes"] = {}
                        merged_docs.append(doc)
            except Exception as e:
                logger.error(f"Error processing document file {doc_path}: {e}")
                continue

        logger.info(f"Loaded {len(docs_by_id)} unique documents with IDs")

        # Now process each attribute subdirectory
        for subdir in attr_subdirs:
            try:
                logger.info(f"Processing attribute directory: {subdir}")
                attr_files = list_jsonl_files(subdir, s3_client, recursive)
                total_attr_files += len(attr_files)
                logger.info(f"Found {len(attr_files)} attribute files in {subdir}")

                # Create a mapping from document basename to attribute file path
                attr_file_map = {}
                for attr_path in attr_files:
                    if attr_path.startswith("s3://"):
                        _, attr_key = parse_s3_path(attr_path)
                        basename = os.path.basename(attr_key)
                    else:
                        basename = os.path.basename(attr_path)

                    attr_file_map[basename] = attr_path

                # Go through the document files again to find matching attributes
                for doc_path in doc_files:
                    try:
                        if doc_path.startswith("s3://"):
                            _, doc_key = parse_s3_path(doc_path)
                            basename = os.path.basename(doc_key)
                        else:
                            basename = os.path.basename(doc_path)

                        # Find matching attribute file
                        if basename in attr_file_map:
                            attr_path = attr_file_map[basename]
                            attrs = load_jsonl_file(attr_path, s3_client)

                            if not attrs:
                                logger.warning(f"No attributes loaded from {os.path.basename(attr_path)} (path: {attr_path})")
                                continue

                            logger.info(f"Loaded {len(attrs)} attributes from {os.path.basename(attr_path)}")

                            # Create a mapping from document ID to attributes
                            attr_by_id = {attr["id"]: attr for attr in attrs if "id" in attr}

                            # Count documents with matched attributes
                            docs_matched_in_file = 0

                            # Merge attributes into documents by ID
                            for doc_id, doc in docs_by_id.items():
                                if doc_id in attr_by_id:
                                    docs_matched_in_file += 1

                                    # If attributes document has attributes field, merge them
                                    if "attributes" in attr_by_id[doc_id]:
                                        doc["attributes"].update(attr_by_id[doc_id]["attributes"])

                            logger.info(f"Matched attributes for {docs_matched_in_file} documents from {basename} in {subdir}")

                    except Exception as e:
                        logger.error(f"Error processing attribute file {attr_path}: {e}")
                        continue
            except Exception as e:
                logger.error(f"Error processing attribute subdirectory {subdir}: {e}")
                continue

        # Convert the dictionary to a list for return
        merged_docs.extend(docs_by_id.values())

        logger.info(f"Total documents processed: {len(merged_docs)}")
        logger.info(f"Total attribute files processed: {total_attr_files}")
        logger.info(f"Total attribute subdirectories processed: {len(attr_subdirs)}")

        return merged_docs
    except Exception as e:
        logger.error(f"Error in load_documents_and_attributes: {e}")
        raise


def apply_rule(doc, rule):
    """
    Apply a rule to determine if a document meets the PII criteria.

    Args:
        doc: The document JSON object
        rule: Either a tuple (attribute_name, rule_type) for simple rules,
              or an ExpressionNode for complex boolean expressions

    Returns:
        True if the document matches the rule, False otherwise
    """
    # Handle simple rule
    if not is_complex_expression(rule):
        return apply_simple_rule(doc, rule[0], rule[1])

    # Handle complex expression
    return evaluate_expression(doc, rule)


def calculate_attribute_aggregate(doc, attribute_name, operation_type):
    """
    Calculate an aggregate value for a numeric attribute.

    Args:
        doc: The document JSON object
        attribute_name: The attribute field to aggregate (e.g., "pii_tagging_ratio")
        operation_type: The type of aggregation to perform (e.g., "avg")

    Returns:
        The aggregated value, or None if calculation is not possible
    """
    # Check if document has attributes
    if "attributes" not in doc or not doc["attributes"]:
        logger.debug(f"Document {doc.get('id', 'unknown')} has no attributes")
        return None

    attributes = doc["attributes"]

    # Check if the specific attribute exists
    if attribute_name not in attributes:
        logger.debug(f"Document {doc.get('id', 'unknown')} doesn't have attribute: {attribute_name}")
        return None

    if not attributes[attribute_name]:
        logger.debug(f"Document {doc.get('id', 'unknown')} has empty attribute: {attribute_name}")
        return None

    # Extract the numeric values from the attribute spans
    # Each span is formatted as [start_pos, end_pos, value]
    values = [span[2] for span in attributes[attribute_name] if len(span) >= 3 and span[2] is not None]

    if not values:
        logger.debug(f"Document {doc.get('id', 'unknown')} has no valid values for attribute: {attribute_name}")
        return None

    # Convert all values to float
    try:
        numeric_values = [float(value) for value in values]
    except (ValueError, TypeError):
        logger.debug(f"Document {doc.get('id', 'unknown')} has non-numeric values for attribute: {attribute_name}")
        return None

    # Perform the aggregation
    if operation_type == "avg":
        if not numeric_values:
            return None
        return sum(numeric_values) / len(numeric_values)
    # Add more aggregation types here as needed
    else:
        raise ValueError(f"Unknown operation type: {operation_type}")


def apply_simple_rule(doc, attribute_name, rule_type):
    """
    Apply a simple rule to determine if a document meets the PII criteria.

    Args:
        doc: The document JSON object
        attribute_name: The attribute field to check (e.g., "gpt_4_1_contains_pii")
        rule_type: 'any' for any true value, 'all' for all true values,
                   or a string containing an operation and comparison (e.g., 'avg>0.3')

    Returns:
        True if the document matches the rule, False otherwise
    """
    # Check if document has attributes
    if "attributes" not in doc or not doc["attributes"]:
        logger.debug(f"Document {doc.get('id', 'unknown')} has no attributes")
        return False

    attributes = doc["attributes"]

    # Check if the specific attribute exists
    if attribute_name not in attributes:
        logger.debug(f"Document {doc.get('id', 'unknown')} doesn't have attribute: {attribute_name}")
        return False

    if not attributes[attribute_name]:
        logger.debug(f"Document {doc.get('id', 'unknown')} has empty attribute: {attribute_name}")
        return False

    # Handle numeric comparison rules (e.g., 'avg>0.3')
    if any(op in rule_type for op in [">", "<", ">=", "<=", "=="]):
        # Parse the rule type into operation and comparison
        operation_parts = rule_type.split(">")
        if len(operation_parts) == 2:
            operation_type, threshold = operation_parts
            comparison_op = ">"
        else:
            operation_parts = rule_type.split("<")
            if len(operation_parts) == 2:
                operation_type, threshold = operation_parts
                comparison_op = "<"
            else:
                operation_parts = rule_type.split(">=")
                if len(operation_parts) == 2:
                    operation_type, threshold = operation_parts
                    comparison_op = ">="
                else:
                    operation_parts = rule_type.split("<=")
                    if len(operation_parts) == 2:
                        operation_type, threshold = operation_parts
                        comparison_op = "<="
                    else:
                        operation_parts = rule_type.split("==")
                        if len(operation_parts) == 2:
                            operation_type, threshold = operation_parts
                            comparison_op = "=="
                        else:
                            raise ValueError(f"Invalid rule type: {rule_type}")

        # Convert threshold to float
        try:
            threshold = float(threshold)
        except ValueError:
            raise ValueError(f"Invalid threshold value: {threshold}")

        # Calculate the aggregate value
        aggregate_value = calculate_attribute_aggregate(doc, attribute_name, operation_type)
        if aggregate_value is None:
            logger.debug(f"Document {doc.get('id', 'unknown')} has no valid aggregate value for attribute: {attribute_name}")
            return False

        # Apply the comparison
        if comparison_op == ">":
            result = aggregate_value > threshold
        elif comparison_op == "<":
            result = aggregate_value < threshold
        elif comparison_op == ">=":
            result = aggregate_value >= threshold
        elif comparison_op == "<=":
            result = aggregate_value <= threshold
        elif comparison_op == "==":
            result = aggregate_value == threshold
        else:
            raise ValueError(f"Invalid comparison operator: {comparison_op}")

        if result:
            logger.debug(f"Document {doc.get('id', 'unknown')} matched numeric rule '{attribute_name}:{rule_type}' with value {aggregate_value}")
        return result

    # Handle boolean rules (any/all)
    if rule_type in ["any", "all"]:
        # Extract the boolean values from the attribute spans
        # Each span is formatted as [start_pos, end_pos, value]
        values = [span[2] for span in attributes[attribute_name] if len(span) >= 3 and span[2] is not None]

        if not values:
            logger.debug(f"Document {doc.get('id', 'unknown')} has no valid values for attribute: {attribute_name}")
            return False

        # Apply the rule
        if rule_type == "any":
            result = any(values)
            if result:
                logger.debug(f"Document {doc.get('id', 'unknown')} matched rule '{attribute_name}:{rule_type}' (found True in {len(values)} values)")
            return result
        elif rule_type == "all":
            result = all(values)
            if result:
                logger.debug(f"Document {doc.get('id', 'unknown')} matched rule '{attribute_name}:{rule_type}' (all {len(values)} values are True)")
            return result

    raise ValueError(f"Unknown rule type: {rule_type}")


def evaluate_expression(doc, expr):
    """
    Evaluate a boolean expression on a document.

    Args:
        doc: The document JSON object
        expr: An ExpressionNode representing a boolean expression

    Returns:
        True if the document matches the expression, False otherwise
    """
    if isinstance(expr, RuleNode):
        # Base case: evaluate a leaf rule node
        return apply_simple_rule(doc, expr.attribute_name, expr.rule_type)

    elif isinstance(expr, NotNode):
        # NOT operator
        return not evaluate_expression(doc, expr.operand)

    elif isinstance(expr, BinaryNode):
        # Binary operators (AND/OR)
        if expr.operator == "AND":
            # Short-circuit AND evaluation
            return evaluate_expression(doc, expr.left) and evaluate_expression(doc, expr.right)
        elif expr.operator == "OR":
            # Short-circuit OR evaluation
            return evaluate_expression(doc, expr.left) or evaluate_expression(doc, expr.right)

    # Should not reach here if the expression tree is well-formed
    raise ValueError(f"Invalid expression node type: {type(expr)}")


def tokenize_expression(expression):
    """
    Tokenize a rule expression string into a list of tokens.

    Args:
        expression: A string containing a boolean rule expression
                   (e.g., "not rule1:any and rule2:all")

    Returns:
        A list of Token objects
    """
    tokens = []
    i = 0
    expression = expression.strip()

    while i < len(expression):
        char = expression[i]

        # Skip whitespace
        if char.isspace():
            i += 1
            continue

        # Handle parentheses
        elif char == "(":
            tokens.append(Token(TokenType.LPAREN))
            i += 1
        elif char == ")":
            tokens.append(Token(TokenType.RPAREN))
            i += 1

        # Handle operators
        elif i + 2 < len(expression) and expression[i : i + 3].lower() == "and":
            # Check if it's a standalone 'and' and not part of a word
            if (i == 0 or expression[i - 1].isspace() or expression[i - 1] in "()") and (
                i + 3 >= len(expression) or expression[i + 3].isspace() or expression[i + 3] in "()"
            ):
                tokens.append(Token(TokenType.AND))
                i += 3
            else:
                # It's part of an attribute name
                rule_start = i
                while i < len(expression) and not expression[i].isspace() and expression[i] not in "()":
                    if i + 1 < len(expression) and expression[i] == ":":
                        break
                    i += 1

                # Process rule if we found a colon
                if i < len(expression) and expression[i] == ":":
                    rule_end = i
                    i += 1  # Skip the colon

                    # Find the rule type
                    type_start = i
                    while i < len(expression) and not expression[i].isspace() and expression[i] not in "()":
                        i += 1

                    rule_name = expression[rule_start:rule_end]
                    rule_type = expression[type_start:i]

                    tokens.append(Token(TokenType.RULE, (rule_name, rule_type)))
                else:
                    raise ValueError(f"Invalid rule format at position {rule_start}")

        elif i + 1 < len(expression) and expression[i : i + 2].lower() == "or":
            # Check if it's a standalone 'or' and not part of a word
            if (i == 0 or expression[i - 1].isspace() or expression[i - 1] in "()") and (
                i + 2 >= len(expression) or expression[i + 2].isspace() or expression[i + 2] in "()"
            ):
                tokens.append(Token(TokenType.OR))
                i += 2
            else:
                # Part of an attribute name
                rule_start = i
                while i < len(expression) and not expression[i].isspace() and expression[i] not in "()":
                    if i + 1 < len(expression) and expression[i] == ":":
                        break
                    i += 1

                # Process rule if we found a colon
                if i < len(expression) and expression[i] == ":":
                    rule_end = i
                    i += 1  # Skip the colon

                    # Find the rule type
                    type_start = i
                    while i < len(expression) and not expression[i].isspace() and expression[i] not in "()":
                        i += 1

                    rule_name = expression[rule_start:rule_end]
                    rule_type = expression[type_start:i]

                    tokens.append(Token(TokenType.RULE, (rule_name, rule_type)))
                else:
                    raise ValueError(f"Invalid rule format at position {rule_start}")

        elif i + 2 < len(expression) and expression[i : i + 3].lower() == "not":
            # Check if it's a standalone 'not' and not part of a word
            if (i == 0 or expression[i - 1].isspace() or expression[i - 1] in "()") and (
                i + 3 >= len(expression) or expression[i + 3].isspace() or expression[i + 3] in "()"
            ):
                tokens.append(Token(TokenType.NOT))
                i += 3
            else:
                # Part of an attribute name
                rule_start = i
                while i < len(expression) and not expression[i].isspace() and expression[i] not in "()":
                    if i + 1 < len(expression) and expression[i] == ":":
                        break
                    i += 1

                # Process rule if we found a colon
                if i < len(expression) and expression[i] == ":":
                    rule_end = i
                    i += 1  # Skip the colon

                    # Find the rule type
                    type_start = i
                    while i < len(expression) and not expression[i].isspace() and expression[i] not in "()":
                        i += 1

                    rule_name = expression[rule_start:rule_end]
                    rule_type = expression[type_start:i]

                    tokens.append(Token(TokenType.RULE, (rule_name, rule_type)))
                else:
                    raise ValueError(f"Invalid rule format at position {rule_start}")

        # Handle rule (attribute:type)
        else:
            rule_start = i
            while i < len(expression) and not expression[i].isspace() and expression[i] not in "()":
                if i + 1 < len(expression) and expression[i] == ":":
                    break
                i += 1

            # Process rule if we found a colon
            if i < len(expression) and expression[i] == ":":
                rule_end = i
                i += 1  # Skip the colon

                # Find the rule type
                type_start = i
                while i < len(expression) and not expression[i].isspace() and expression[i] not in "()":
                    i += 1

                rule_name = expression[rule_start:rule_end]
                rule_type = expression[type_start:i]

                tokens.append(Token(TokenType.RULE, (rule_name, rule_type)))
            else:
                raise ValueError(f"Invalid rule format at position {rule_start}")

    tokens.append(Token(TokenType.EOF))
    return tokens


class Parser:
    """
    Parser for boolean rule expressions.
    Implements a recursive descent parser for expressions with the following grammar:

    expression    → or_expr
    or_expr       → and_expr ("or" and_expr)*
    and_expr      → unary_expr ("and" unary_expr)*
    unary_expr    → "not" unary_expr | primary
    primary       → rule | "(" expression ")"
    rule          → ATTRIBUTE ":" RULE_TYPE
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.current = 0

    def parse(self):
        """Parse the tokens into an expression tree."""
        return self.expression()

    def expression(self):
        """Parse an expression (top level)."""
        return self.or_expr()

    def or_expr(self):
        """Parse an OR expression."""
        expr = self.and_expr()

        while self.match(TokenType.OR):
            right = self.and_expr()
            expr = BinaryNode(expr, right, "OR")

        return expr

    def and_expr(self):
        """Parse an AND expression."""
        expr = self.unary_expr()

        while self.match(TokenType.AND):
            right = self.unary_expr()
            expr = BinaryNode(expr, right, "AND")

        return expr

    def unary_expr(self):
        """Parse a unary expression (NOT)."""
        if self.match(TokenType.NOT):
            operand = self.unary_expr()
            return NotNode(operand)

        return self.primary()

    def primary(self):
        """Parse a primary expression (rule or parenthesized expression)."""
        if self.match(TokenType.RULE):
            rule_tuple = self.previous().value
            attribute_name, rule_type = rule_tuple

            # Validate rule type
            if rule_type not in ["any", "all"] and not any(op in rule_type for op in [">", "<", ">=", "<=", "=="]):
                raise ValueError(f"Invalid rule type: {rule_type}. Supported types: 'any', 'all', or numeric comparison (e.g., 'avg>0.3')")

            return RuleNode(attribute_name, rule_type)

        if self.match(TokenType.LPAREN):
            expr = self.expression()
            self.consume(TokenType.RPAREN, "Expected ')' after expression.")
            return expr

        raise ValueError(f"Expected rule or '(' at position {self.current}")

    def match(self, *types):
        """Check if the current token matches any of the given types."""
        for type in types:
            if self.check(type):
                self.advance()
                return True

        return False

    def check(self, type):
        """Check if the current token is of the given type without advancing."""
        if self.is_at_end():
            return False
        return self.peek().type == type

    def advance(self):
        """Advance to the next token and return the previous one."""
        if not self.is_at_end():
            self.current += 1
        return self.previous()

    def consume(self, type, message):
        """Consume the current token if it matches the expected type."""
        if self.check(type):
            return self.advance()

        raise ValueError(f"{message} at position {self.current}")

    def is_at_end(self):
        """Check if we've reached the end of the tokens."""
        return self.peek().type == TokenType.EOF

    def peek(self):
        """Return the current token without advancing."""
        return self.tokens[self.current]

    def previous(self):
        """Return the previous token."""
        return self.tokens[self.current - 1]


def parse_rule(rule_string):
    """
    Parse a rule string into an expression tree or a simple attribute-rule_type tuple.

    Args:
        rule_string: A string containing a rule or boolean expression of rules

    Returns:
        Either a tuple (attribute_name, rule_type) for simple rules,
        or an ExpressionNode for complex boolean expressions
    """
    # Check if this is a simple rule
    if (
        "and" not in rule_string.lower()
        and "or" not in rule_string.lower()
        and "not" not in rule_string.lower()
        and "(" not in rule_string
        and ")" not in rule_string
    ):
        # Simple rule format: attribute_name:rule_type
        parts = rule_string.split(":", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid rule format: {rule_string}. Expected format: 'attribute_name:rule_type'")

        attribute_name, rule_type = parts

        # Check for numeric comparison rule_type
        if any(op in rule_type for op in [">", "<", ">=", "<=", "=="]):
            # This is a numeric comparison rule - we'll validate it in apply_simple_rule
            return attribute_name, rule_type
        elif rule_type not in ["any", "all"]:
            raise ValueError(f"Invalid rule type: {rule_type}. Supported types: 'any', 'all', or numeric comparison (e.g., 'avg>0.3')")

        return attribute_name, rule_type
    else:
        # Complex rule expression
        try:
            tokens = tokenize_expression(rule_string)
            parser = Parser(tokens)
            return parser.parse()
        except Exception as e:
            raise ValueError(f"Error parsing expression '{rule_string}': {e}")


def is_complex_expression(rule):
    """Check if the rule is a complex boolean expression."""
    return isinstance(rule, ExpressionNode)


def calculate_iou(ref_ids, hyp_ids):
    """Calculate Intersection over Union of two sets of document IDs."""
    ref_set = set(ref_ids)
    hyp_set = set(hyp_ids)

    intersection = ref_set.intersection(hyp_set)
    union = ref_set.union(hyp_set)

    if not union:
        return 0.0

    return len(intersection) / len(union)


def collect_rule_stats(expression, doc):
    """
    Collect statistics for all rules within a complex expression.

    Args:
        expression: A rule expression (either a tuple or ExpressionNode)
        doc: The document to analyze

    Returns:
        A dictionary with rule statistics
    """
    rule_stats = defaultdict(int)

    # Handle simple rule
    if not is_complex_expression(expression):
        attribute_name, rule_type = expression
        # Only process if document has this attribute
        if "attributes" in doc and doc["attributes"] and attribute_name in doc["attributes"] and doc["attributes"][attribute_name]:
            # The rule name will be the key for the statistics
            rule_name = f"{attribute_name}:{rule_type}"

            # Count entries in the attribute
            entries = doc["attributes"][attribute_name]
            rule_stats[f"{rule_name}_total_entries"] += len(entries)

            # Count positive values
            for span in entries:
                if len(span) >= 3 and span[2] is True:
                    rule_stats[f"{rule_name}_positive_entries"] += 1

            # Check if document matches the rule
            if apply_simple_rule(doc, attribute_name, rule_type):
                rule_stats[f"{rule_name}_matched_docs"] += 1

        return rule_stats

    # For complex expressions, traverse the expression tree
    if isinstance(expression, RuleNode):
        # Base case: leaf node is a simple rule
        attribute_name, rule_type = expression.attribute_name, expression.rule_type
        if "attributes" in doc and doc["attributes"] and attribute_name in doc["attributes"] and doc["attributes"][attribute_name]:
            # The rule name will be the key for the statistics
            rule_name = f"{attribute_name}:{rule_type}"

            # Count entries in the attribute
            entries = doc["attributes"][attribute_name]
            rule_stats[f"{rule_name}_total_entries"] += len(entries)

            # Count positive values
            for span in entries:
                if len(span) >= 3 and span[2] is True:
                    rule_stats[f"{rule_name}_positive_entries"] += 1

            # Check if document matches the rule
            if apply_simple_rule(doc, attribute_name, rule_type):
                rule_stats[f"{rule_name}_matched_docs"] += 1

    elif isinstance(expression, NotNode):
        # Get stats from the operand
        operand_stats = collect_rule_stats(expression.operand, doc)
        # Merge with current stats
        for key, value in operand_stats.items():
            rule_stats[key] += value

    elif isinstance(expression, BinaryNode):
        # Get stats from both sides
        left_stats = collect_rule_stats(expression.left, doc)
        right_stats = collect_rule_stats(expression.right, doc)

        # Merge with current stats
        for key, value in left_stats.items():
            rule_stats[key] += value
        for key, value in right_stats.items():
            rule_stats[key] += value

    return rule_stats


def get_expression_summary(expression):
    """
    Generate a string representation of a rule expression.

    Args:
        expression: A rule expression (either a tuple or ExpressionNode)

    Returns:
        A string representation of the expression
    """
    if not is_complex_expression(expression):
        return f"{expression[0]}:{expression[1]}"

    if isinstance(expression, RuleNode):
        return f"{expression.attribute_name}:{expression.rule_type}"

    elif isinstance(expression, NotNode):
        return f"not {get_expression_summary(expression.operand)}"

    elif isinstance(expression, BinaryNode):
        left_summary = get_expression_summary(expression.left)
        right_summary = get_expression_summary(expression.right)
        return f"({left_summary} {expression.operator.lower()} {right_summary})"

    return str(expression)


def compare_documents(ref_docs, hyp_docs, ref_rule, hyp_rule):
    """
    Compare two sets of documents using the specified rules and calculate IoU.

    Args:
        ref_docs: List of reference documents
        hyp_docs: List of hypothesis documents
        ref_rule: Rule expression for reference (tuple or ExpressionNode)
        hyp_rule: Rule expression for hypothesis (tuple or ExpressionNode)

    Returns:
        Dictionary with comparison results
    """
    # Extract document IDs and create ID-to-document maps
    ref_id_to_doc = {doc["id"]: doc for doc in ref_docs if "id" in doc}
    hyp_id_to_doc = {doc["id"]: doc for doc in hyp_docs if "id" in doc}

    # Get common document IDs
    common_ids = set(ref_id_to_doc.keys()).intersection(set(hyp_id_to_doc.keys()))

    # Apply rules to each document
    ref_matches = set()
    hyp_matches = set()

    # Track rule statistics
    ref_rule_stats = defaultdict(int)
    hyp_rule_stats = defaultdict(int)

    for doc_id in common_ids:
        ref_doc = ref_id_to_doc[doc_id]
        hyp_doc = hyp_id_to_doc[doc_id]

        # Collect statistics for all rules in the expressions
        doc_ref_rule_stats = collect_rule_stats(ref_rule, ref_doc)
        doc_hyp_rule_stats = collect_rule_stats(hyp_rule, hyp_doc)

        # Merge with overall stats
        for key, value in doc_ref_rule_stats.items():
            ref_rule_stats[key] += value
        for key, value in doc_hyp_rule_stats.items():
            hyp_rule_stats[key] += value

        # Check if document matches the rule expressions
        if apply_rule(ref_doc, ref_rule):
            ref_matches.add(doc_id)
            ref_rule_stats["expression_matched_docs"] += 1

        if apply_rule(hyp_doc, hyp_rule):
            hyp_matches.add(doc_id)
            hyp_rule_stats["expression_matched_docs"] += 1

    # Calculate IoU
    iou = calculate_iou(ref_matches, hyp_matches)

    # Collect detailed statistics
    tp = len(ref_matches.intersection(hyp_matches))
    fp = len(hyp_matches - ref_matches)
    fn = len(ref_matches - hyp_matches)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    # Generate string representations of the expressions
    ref_rule_str = get_expression_summary(ref_rule)
    hyp_rule_str = get_expression_summary(hyp_rule)

    return {
        "total_docs": len(common_ids),
        "ref_rule": ref_rule_str,
        "hyp_rule": hyp_rule_str,
        "ref_matches": len(ref_matches),
        "hyp_matches": len(hyp_matches),
        "intersection": tp,
        "union": tp + fp + fn,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "iou": iou,
        "ref_rule_stats": dict(ref_rule_stats),
        "hyp_rule_stats": dict(hyp_rule_stats),
    }


def format_rule_stats(rule_stats):
    """Format rule statistics for display."""
    # Group the statistics by rule name
    grouped_stats = defaultdict(dict)

    # Process regular rule stats (format: "{rule_name}_{stat_type}")
    for key, value in rule_stats.items():
        if key == "expression_matched_docs":
            # Special case for the overall expression match count
            continue

        # Extract rule name and stat type
        if "_total_entries" in key:
            rule_name = key.replace("_total_entries", "")
            grouped_stats[rule_name]["total_entries"] = value
        elif "_positive_entries" in key:
            rule_name = key.replace("_positive_entries", "")
            grouped_stats[rule_name]["positive_entries"] = value
        elif "_matched_docs" in key:
            rule_name = key.replace("_matched_docs", "")
            grouped_stats[rule_name]["matched_docs"] = value

    # Format the grouped statistics as a list of strings
    formatted_stats = []
    for rule_name, stats in grouped_stats.items():
        formatted_stats.append(
            f"  {rule_name}:\n"
            f"    - Total Entries: {stats.get('total_entries', 0)}\n"
            f"    - Positive Entries: {stats.get('positive_entries', 0)}\n"
            f"    - Matched Documents: {stats.get('matched_docs', 0)}"
        )

    # Add the expression matched count if available
    if "expression_matched_docs" in rule_stats:
        formatted_stats.append(f"  Overall Expression Matched Documents: {rule_stats['expression_matched_docs']}")

    return "\n".join(formatted_stats)


def collect_numeric_attributes(documents):
    """
    Collect all numeric attribute values from documents.

    Args:
        documents: List of documents with attributes

    Returns:
        Dictionary mapping attribute names to lists of numeric values
    """
    numeric_attributes = defaultdict(list)

    for doc in documents:
        if "attributes" not in doc or not doc["attributes"]:
            continue

        for attr_name, attr_values in doc["attributes"].items():
            if not attr_values:
                continue

            # Try to extract numeric values from the attribute spans
            # Each span is formatted as [start_pos, end_pos, value]
            for span in attr_values:
                if len(span) >= 3 and span[2] is not None:
                    try:
                        # Convert to float if it's a numeric value
                        value = float(span[2])
                        numeric_attributes[attr_name].append(value)
                    except (ValueError, TypeError):
                        # Not a numeric value, skip
                        pass

    # Filter out attributes with no or too few numeric values
    return {k: v for k, v in numeric_attributes.items() if len(v) > 5}


def generate_cdf_plot(values, attribute_name):
    """
    Generate a CDF plot for the given numeric values.

    Args:
        values: List of numeric values
        attribute_name: Name of the attribute (for plot title)

    Returns:
        Base64-encoded PNG image of the plot or None if there's an error
    """
    try:
        # Ensure we have enough data points
        if len(values) < 5:
            logger.warning(f"Not enough data points to generate CDF for {attribute_name}")
            return None

        # Remove any NaN or infinite values
        values = np.array([v for v in values if np.isfinite(v)])
        if len(values) < 5:
            logger.warning(f"Not enough finite data points to generate CDF for {attribute_name}")
            return None

        # Handle extreme values by removing outliers (optional)
        # if len(values) > 30:  # Only apply if we have enough data points
        #     q1, q3 = np.percentile(values, [25, 75])
        #     iqr = q3 - q1
        #     lower_bound = q1 - 3 * iqr
        #     upper_bound = q3 + 3 * iqr
        #     values = values[(values >= lower_bound) & (values <= upper_bound)]

        # Sort values for CDF calculation
        values = np.sort(values)

        # Create a Figure object (no interactive display)
        fig = Figure(figsize=(10, 6))
        ax = fig.add_subplot(1, 1, 1)

        # Calculate CDF (y-values are 0 to 1 for cumulative probability)
        y = np.arange(1, len(values) + 1) / len(values)

        # Plot the CDF
        ax.plot(values, y, "b-", linewidth=2)
        ax.grid(True, linestyle="--", alpha=0.7)

        # Add labels and title
        ax.set_xlabel("Value", fontsize=12)
        ax.set_ylabel("Cumulative Probability", fontsize=12)
        ax.set_title(f"CDF of {attribute_name}", fontsize=14)

        # Ensure the y-axis goes from 0 to 1 for probability
        ax.set_ylim(0, 1.05)

        # Add some statistics to the plot
        if len(values) > 0:
            mean_val = np.mean(values)
            median_val = np.median(values)
            min_val = np.min(values)
            max_val = np.max(values)
            stats_text = f"n={len(values)}\nmin={min_val:.2f}\nmax={max_val:.2f}\nmean={mean_val:.2f}\nmedian={median_val:.2f}"
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, verticalalignment="top", bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

        # Make layout tight
        fig.tight_layout()

        # Convert to base64 for embedding in HTML
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return img_base64

    except Exception as e:
        logger.error(f"Error generating CDF plot for {attribute_name}: {e}")
        return None


def generate_attribute_plots_html(numeric_attributes, max_plots=20):
    """
    Generate HTML section with CDF plots for all numeric attributes.

    Args:
        numeric_attributes: Dictionary mapping attribute names to lists of numeric values
        max_plots: Maximum number of plots to generate

    Returns:
        HTML string with embedded CDF plots
    """
    if not numeric_attributes:
        return ""

    html = """
    <h2>Numeric Attribute Distributions</h2>
    <div class="attribute-plots">
    """

    plot_count = 0

    # Sort attributes by number of values (most values first)
    sorted_attrs = sorted(numeric_attributes.items(), key=lambda x: len(x[1]), reverse=True)

    for attr_name, values in sorted_attrs:
        if len(values) < 10:  # Skip attributes with too few values for meaningful plots
            continue

        if plot_count >= max_plots:
            logger.info(f"Limiting CDF plots to {max_plots} attributes to avoid performance issues")
            break

        # Generate the CDF plot
        img_base64 = generate_cdf_plot(values, attr_name)

        # Only add to HTML if plot generation was successful
        if img_base64:
            html += f"""
            <div class="plot-container">
                <h3>{attr_name}</h3>
                <img src="data:image/png;base64,{img_base64}" alt="CDF plot for {attr_name}" class="cdf-plot">
                <p>Number of values: {len(values)}</p>
            </div>
            """
            plot_count += 1

    if plot_count == 0:
        return ""  # Don't add the section if no plots were generated

    html += """
    </div>
    """

    return html


def generate_html_report(docs, title, summary, output_path):
    """
    Generate an HTML report file with document texts

    Args:
        docs: List of documents to include in the report
        title: Title of the report
        summary: Summary statistics to include at the top
        output_path: Path to save the HTML file

    Returns:
        None
    """
    # Create header with CSS styling
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            scroll-behavior: smooth;
        }}
        
        /* Header bar styles */
        .header {{
            background-color: #f8f9fa;
            padding: 8px 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 100;
            display: flex;
            justify-content: space-between;
            align-items: center;
            height: 40px;
        }}
        
        .title {{
            font-size: 1.2em;
            font-weight: bold;s
            color: #333;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 60%;
        }}
        
        .controls {{
            display: flex;
            align-items: center;
        }}
        
        .keyboard-controls {{
            font-size: 0.85em;
            margin-right: 15px;
        }}
        
        .toggle-summary {{
            background-color: #e9ecef;
            border: 1px solid #ced4da;
            padding: 4px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85em;
        }}
        
        /* Summary panel styles */
        #summary-panel {{
            position: fixed;
            top: 57px;
            left: 0;
            right: 0;
            background-color: #f8f9fa;
            border-bottom: 1px solid #ddd;
            padding: 15px 20px;
            z-index: 90;
            display: none;
            max-height: 300px;
            overflow-y: auto;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        
        /* Main content styles */
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 60px 20px 20px 20px;
        }}
        
        /* Document styles */
        .document {{
            background-color: #fff;
            padding: 15px;
            margin-bottom: 15px;
            border: 1px solid #ddd;
            border-radius: 5px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            transition: all 0.2s ease-in-out;
            scroll-margin-top: 60px;
        }}
        
        .document:hover {{
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }}
        
        .document.selected {{
            border: 2px solid #007bff;
            box-shadow: 0 0 8px rgba(0, 123, 255, 0.5);
            background-color: #f8f9fa;
        }}
        
        .document-id {{
            color: #007bff;
            font-weight: bold;
            margin-bottom: 5px;
            font-size: 0.9em;
        }}
        
        .document-text {{
            white-space: pre-wrap;
            overflow-wrap: break-word;
        }}
        
        /* Helper styles */
        h2 {{
            margin-top: 0;
            font-size: 1.2em;
            color: #333;
        }}
        
        pre {{
            font-size: 0.9em;
            white-space: pre-wrap;
        }}
        
        .stats {{
            color: #666;
            font-size: 0.8em;
            font-weight: normal;
        }}
        
        .keyboard-shortcut {{
            display: inline-block;
            padding: 1px 4px;
            margin: 0 1px;
            border-radius: 3px;
            background-color: #f1f3f5;
            border: 1px solid #ced4da;
            font-family: monospace;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <!-- Fixed header -->
    <div class="header">
        <div class="title">{title} <span class="stats">({len(docs)} documents)</span></div>
        <div class="controls">
            <div class="keyboard-controls">
                <span class="keyboard-shortcut">↑</span>/<span class="keyboard-shortcut">↓</span> to navigate
                &nbsp;<span class="keyboard-shortcut">Home</span>/<span class="keyboard-shortcut">End</span>
            </div>
            <button class="toggle-summary" onclick="toggleSummary()">Show Summary</button>
        </div>
    </div>
    
    <!-- Summary panel (initially hidden) -->
    <div id="summary-panel">
        <h2>Summary</h2>
        <pre>{summary}</pre>
    </div>
    
    <!-- Main content -->
    <div class="container">
        <div id="document-container">
"""

    # Add each document with a unique ID
    for i, doc in enumerate(docs, 1):
        doc_id = doc.get("id", f"unknown_{i}")
        # Get document text, falling back to JSON representation if not available
        doc_text = doc.get("text", json.dumps(doc, indent=2))

        # The first document gets the "selected" class
        selected_class = " selected" if i == 1 else ""

        html += f"""
            <div id="doc-{i}" class="document{selected_class}" tabindex="0">
                <div class="document-id">Document ID: {doc_id}</div>
                <pre class="document-text">{pyhtml.escape(doc_text)}</pre>
            </div>
"""

    # Add JavaScript for keyboard navigation and summary toggle
    html += """
        </div>
    </div>

    <script>
        // Get all documents
        const documents = document.querySelectorAll('.document');
        let selectedIndex = 0; // First document is selected by default
        let summaryVisible = false;
        
        // Function to toggle summary panel
        function toggleSummary() {
            const panel = document.getElementById('summary-panel');
            const button = document.querySelector('.toggle-summary');
            
            if (summaryVisible) {
                panel.style.display = 'none';
                button.textContent = 'Show Summary';
            } else {
                panel.style.display = 'block';
                button.textContent = 'Hide Summary';
            }
            
            summaryVisible = !summaryVisible;
        }
        
        // Function to select a document
        function selectDocument(index) {
            // Validate index
            if (index < 0) index = 0;
            if (index >= documents.length) index = documents.length - 1;
            
            // Store current index for use in setTimeout
            const targetIndex = index;
            
            // Remove selected class from all documents
            documents.forEach(doc => doc.classList.remove('selected'));
            
            // Add selected class to the current document
            documents[targetIndex].classList.add('selected');
            
            // Update selected index
            selectedIndex = targetIndex;
            
            // Use a more direct approach for scrolling
            // Get the element's offset from the top of the document
            const headerHeight = 60; // Fixed header height
            const element = documents[targetIndex];
            const elementPosition = element.offsetTop;
            
            // Scroll the element to the top of the viewport, accounting for header
            window.scrollTo({
                top: elementPosition - headerHeight,
                behavior: 'smooth'
            });
            
            // Focus the selected document for accessibility
            documents[targetIndex].focus();
        }
        
        // Add keyboard event listener to the document
        document.addEventListener('keydown', function(event) {
            // Arrow up
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                selectDocument(selectedIndex - 1);
            }
            // Arrow down
            else if (event.key === 'ArrowDown') {
                event.preventDefault();
                selectDocument(selectedIndex + 1);
            }
            // Home key - go to first document
            else if (event.key === 'Home') {
                event.preventDefault();
                selectDocument(0);
            }
            // End key - go to last document
            else if (event.key === 'End') {
                event.preventDefault();
                selectDocument(documents.length - 1);
            }
            // Escape key - hide summary if visible
            else if (event.key === 'Escape' && summaryVisible) {
                toggleSummary();
            }
            // S key - toggle summary
            else if (event.key === 's' || event.key === 'S') {
                toggleSummary();
            }
        });
        
        // Make documents clickable to select them
        documents.forEach((doc, index) => {
            doc.addEventListener('click', () => {
                selectDocument(index);
            });
        });
        
        // Select the first document when the page loads
        window.addEventListener('load', () => {
            // If there are documents, select the first one
            if (documents.length > 0) {
                selectDocument(0);
            }
        });
    </script>
</body>
</html>
"""

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Write HTML to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Generated HTML report: {output_path}")


def main():
    global args
    args = parse_args()

    # Set up logging based on arguments
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # Set up S3 client if needed
    s3_client = None
    if args.docs_folder.startswith("s3://") or (args.attr_folder and args.attr_folder.startswith("s3://")):
        session = boto3.Session(profile_name=args.aws_profile) if args.aws_profile else boto3.Session()
        s3_client = session.client("s3")

    # Parse the rules
    logger.info(f"Parsing reference rule expression: {args.ref_rule}")
    ref_rule = parse_rule(args.ref_rule)

    logger.info(f"Parsing hypothesis rule expression: {args.hyp_rule}")
    hyp_rule = parse_rule(args.hyp_rule)

    # Generate string representations of the expressions
    ref_rule_str = get_expression_summary(ref_rule)
    hyp_rule_str = get_expression_summary(hyp_rule)

    logger.info(f"Reference rule parsed as: {ref_rule_str}")
    logger.info(f"Hypothesis rule parsed as: {hyp_rule_str}")

    # Determine attributes folder
    attr_folder = get_attributes_folder(args.docs_folder, args.attr_folder)
    logger.info(f"Using attributes folder: {attr_folder}")

    # Load documents and merge with attributes from all subdirectories
    logger.info("Loading documents and merging with all attributes...")
    all_docs = load_documents_and_attributes(args.docs_folder, attr_folder, s3_client, args.recursive)

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # Use the same documents for both reference and hypothesis evaluation
    # since we've loaded all attributes into each document
    ref_docs = all_docs
    hyp_docs = all_docs

    # Compare the documents
    logger.info("Comparing documents using reference and hypothesis rules...")
    comparison_result = compare_documents(ref_docs, hyp_docs, ref_rule, hyp_rule)

    # Get document IDs for each category
    ref_matches = set()
    hyp_matches = set()

    # Create mappings from document IDs to documents
    doc_map = {doc["id"]: doc for doc in all_docs if "id" in doc}

    # Find documents that match the reference and hypothesis rules
    for doc_id, doc in doc_map.items():
        if apply_rule(doc, ref_rule):
            ref_matches.add(doc_id)
        if apply_rule(doc, hyp_rule):
            hyp_matches.add(doc_id)

    # Calculate document sets for each category
    true_positives_ids = ref_matches.intersection(hyp_matches)
    true_negatives_ids = set(doc_map.keys()) - ref_matches - hyp_matches
    false_positives_ids = hyp_matches - ref_matches
    false_negatives_ids = ref_matches - hyp_matches

    # Create document lists for each category
    true_positives = [doc_map[doc_id] for doc_id in true_positives_ids]
    true_negatives = [doc_map[doc_id] for doc_id in true_negatives_ids]
    false_positives = [doc_map[doc_id] for doc_id in false_positives_ids]
    false_negatives = [doc_map[doc_id] for doc_id in false_negatives_ids]

    # Calculate metrics
    tp = len(true_positives)
    tn = len(true_negatives)
    fp = len(false_positives)
    fn = len(false_negatives)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    iou = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0

    # Prepare overall statistics
    overall_stats = {
        "total_docs": len(doc_map),
        "ref_matches": len(ref_matches),
        "hyp_matches": len(hyp_matches),
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "iou": iou,
        "ref_rule_stats": comparison_result["ref_rule_stats"],
        "hyp_rule_stats": comparison_result["hyp_rule_stats"],
    }

    # Prepare summary
    summary = f"""Reference Rule: {args.ref_rule}
Hypothesis Rule: {args.hyp_rule}

Total Documents: {overall_stats['total_docs']}
Reference Matches: {overall_stats['ref_matches']}
Hypothesis Matches: {overall_stats['hyp_matches']}

True Positives: {tp}
True Negatives: {tn}
False Positives: {fp}
False Negatives: {fn}

Precision: {precision:.4f}
Recall: {recall:.4f}
F1 Score: {f1:.4f}
IoU: {iou:.4f}
"""

    # Generate HTML reports for each category
    logger.info("Generating HTML reports...")

    # True Positives
    generate_html_report(
        true_positives[:1000],
        "True Positives - Documents matching both Reference and Hypothesis Rules",
        summary,
        os.path.join(args.output_dir, "true_positives.html"),
    )

    # True Negatives
    generate_html_report(
        true_negatives[:1000], "True Negatives - Documents not matching either Rule", summary, os.path.join(args.output_dir, "true_negatives.html")
    )

    # False Positives
    generate_html_report(
        false_positives[:1000],
        "False Positives - Documents matching Hypothesis but not Reference Rule",
        summary,
        os.path.join(args.output_dir, "false_positives.html"),
    )

    # False Negatives
    generate_html_report(
        false_negatives[:1000],
        "False Negatives - Documents matching Reference but not Hypothesis Rule",
        summary,
        os.path.join(args.output_dir, "false_negatives.html"),
    )

    # Collect numeric attributes and generate CDF plots if not disabled
    attribute_plots_html = ""
    if not args.disable_plots:
        logger.info("Collecting numeric attributes for CDF plots...")
        numeric_attributes = collect_numeric_attributes(all_docs)

        if numeric_attributes:
            logger.info(f"Found {len(numeric_attributes)} numeric attributes suitable for CDF plots")
            # Generate CDF plots HTML with the specified maximum number of plots
            attribute_plots_html = generate_attribute_plots_html(numeric_attributes, args.max_plots)
        else:
            logger.info("No numeric attributes found for CDF plots")
    else:
        logger.info("CDF plot generation disabled by --disable-plots flag")

    # Generate index.html file that links to all reports
    index_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>PII Rule Comparison Results</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            max-width: 1000px;
            margin: 0 auto;
        }}
        .summary {{
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 5px solid #007bff;
        }}
        .category {{
            margin-bottom: 20px;
            padding: 15px;
            border-radius: 5px;
        }}
        .true-positives {{
            background-color: #d4edda;
            border-left: 5px solid #28a745;
        }}
        .true-negatives {{
            background-color: #e2e3e5;
            border-left: 5px solid #6c757d;
        }}
        .false-positives {{
            background-color: #f8d7da;
            border-left: 5px solid #dc3545;
        }}
        .false-negatives {{
            background-color: #fff3cd;
            border-left: 5px solid #ffc107;
        }}
        h1 {{
            border-bottom: 2px solid #007bff;
            padding-bottom: 10px;
            color: #333;
        }}
        a {{
            color: #007bff;
            text-decoration: none;
            font-weight: bold;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .attribute-plots {{
            margin-top: 30px;
        }}
        .plot-container {{
            margin-bottom: 30px;
            padding: 15px;
            background-color: #fff;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .cdf-plot {{
            max-width: 100%;
            height: auto;
        }}
        h2 {{
            color: #333;
            border-bottom: 1px solid #eee;
            padding-bottom: 10px;
            margin-top: 30px;
        }}
        h3 {{
            color: #007bff;
        }}
    </style>
</head>
<body>
    <h1>PII Rule Comparison Results</h1>
    <div class="summary">
        <h2>Summary</h2>
        <pre>{summary}</pre>
    </div>
    <h2>Result Categories</h2>
    <div class="category true-positives">
        <h3>True Positives: {tp}</h3>
        <p>Documents that match both the reference and hypothesis rules.</p>
        <a href="true_positives.html">View True Positives</a>
    </div>
    <div class="category true-negatives">
        <h3>True Negatives: {tn}</h3>
        <p>Documents that don't match either the reference or hypothesis rules.</p>
        <a href="true_negatives.html">View True Negatives</a>
    </div>
    <div class="category false-positives">
        <h3>False Positives: {fp}</h3>
        <p>Documents that match the hypothesis rule but not the reference rule.</p>
        <a href="false_positives.html">View False Positives</a>
    </div>
    <div class="category false-negatives">
        <h3>False Negatives: {fn}</h3>
        <p>Documents that match the reference rule but not the hypothesis rule.</p>
        <a href="false_negatives.html">View False Negatives</a>
    </div>
    
    {attribute_plots_html}
</body>
</html>
"""

    with open(os.path.join(args.output_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    # Print summary
    logger.info("\n--- COMPARISON SUMMARY ---")
    logger.info(f"Documents Folder: {args.docs_folder}")
    logger.info(f"Attributes Folder: {attr_folder}")
    logger.info(f"Reference Rule Expression: {args.ref_rule}")
    logger.info(f"  Parsed as: {ref_rule_str}")
    logger.info(f"Hypothesis Rule Expression: {args.hyp_rule}")
    logger.info(f"  Parsed as: {hyp_rule_str}")
    logger.info(f"Total Documents: {overall_stats['total_docs']}")

    # Print rule statistics
    logger.info("\n--- RULE MATCH STATISTICS ---")

    logger.info("\nReference Rules:")
    logger.info(format_rule_stats(overall_stats["ref_rule_stats"]))

    logger.info("\nHypothesis Rules:")
    logger.info(format_rule_stats(overall_stats["hyp_rule_stats"]))

    # Print comparison metrics
    logger.info("\n--- COMPARISON METRICS ---")
    logger.info(f"True Positives: {tp}")
    logger.info(f"True Negatives: {tn}")
    logger.info(f"False Positives: {fp}")
    logger.info(f"False Negatives: {fn}")
    logger.info(f"Precision: {precision:.4f}")
    logger.info(f"Recall: {recall:.4f}")
    logger.info(f"F1 Score: {f1:.4f}")
    logger.info(f"IoU: {iou:.4f}")

    # Output all available attributes that have been loaded
    logger.info("\n--- AVAILABLE ATTRIBUTES ---")
    all_attributes = set()
    for doc in all_docs:
        if "attributes" in doc and doc["attributes"]:
            all_attributes.update(doc["attributes"].keys())

    if all_attributes:
        logger.info(f"Found {len(all_attributes)} unique attributes:")
        for attr in sorted(all_attributes):
            logger.info(f"  - {attr}")
    else:
        logger.info("No attributes found in any documents.")

    logger.info(f"\nResults saved to: {args.output_dir}/index.html")


if __name__ == "__main__":
    main()

# Example commands with actual S3 paths:
"""
# Example for AI2 OE data with resume detection:
python scripts/pii_rule_comparison.py \
  --docs-folder s3://ai2-oe-data/jakep/s2pdf_dedupe_minhash_v1_mini/documents/ \
  --ref-rule "gpt_4_1_contains_pii:any and not gpt_4_1_is_public_document:all" \
  --hyp-rule "google_gemma-3-4b-it_is_resume_cv:any" \
  --output-dir results/resume_detection \
  --recursive \
  --debug

# Example for PII detection comparison:
python scripts/pii_rule_comparison.py \
  --docs-folder s3://allenai-dolma/documents/v1.5 \
  --ref-rule "contains_pii:any" \
  --hyp-rule "(contains_email_addresses:any or contains_phone_numbers:any) and not false_positive:any" \
  --output-dir results/pii_detection \
  --recursive \
  --aws-profile dolma

# Example with custom attributes folder:
python scripts/pii_rule_comparison.py \
  --docs-folder s3://bucket/path/documents \
  --attr-folder s3://bucket/custom/location/attributes \
  --ref-rule "gpt_4_1_contains_pii:any" \
  --hyp-rule "custom_model_pii_detection:any" \
  --output-dir results/custom_comparison \
  --recursive
"""
