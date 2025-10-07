#!/usr/bin/env python3
"""
Rich Autoscan Dolma Documents with ChatGPT Vision

This script combines the functionality of autoscan_dolmadocs.py and rich_tagging_pipeline.py:
1. Uses ChatGPT Vision API to analyze PDF pages for PII
2. Creates attribute folders mirroring the document structure
3. Simplifies with direct ThreadPoolExecutor usage instead of work queue system
"""
import argparse
import gzip
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import List, Optional

import boto3
import pydantic
import zstandard as zstd
from openai import OpenAI
from tqdm import tqdm

from olmocr.data.renderpdf import render_pdf_to_base64png
from olmocr.s3_utils import get_s3_bytes, parse_s3_path

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False

file_handler = logging.FileHandler("rich-autoscan-debug.log", mode="a")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)


LanguageCode = Enum(
    "LanguageCode",
    {
        "en": "English",
        "zh": "Chinese",
        "hi": "Hindi",
        "es": "Spanish",
        "fr": "French",
        "ar": "Arabic",
        "bn": "Bengali",
        "ru": "Russian",
        "pt": "Portuguese",
        "ur": "Urdu",
        "id": "Indonesian",
        "de": "German",
        "ja": "Japanese",
        "sw": "Swahili",
        "mr": "Marathi",
        "te": "Telugu",
        "tr": "Turkish",
        "vi": "Vietnamese",
        "ta": "Tamil",
        "ko": "Korean",
        "other": "Other",
    },
)


class PIIAnnotation(pydantic.BaseModel):
    """Structured model for PII annotations returned by ChatGPT"""

    document_description: str
    language_code: LanguageCode
    cannot_read: bool
    inappropriate_content: bool
    is_public_document: bool

    # PII identifiers
    contains_names: bool
    contains_email_addresses: bool
    contains_phone_numbers: bool

    # PII that must co-occur with identifiers
    contains_addresses: bool
    contains_biographical_info: bool  # DOB, gender, etc.
    contains_location_info: bool
    contains_employment_info: bool
    contains_education_info: bool
    contains_medical_info: bool

    # Always sensitive PII
    contains_government_ids: bool
    contains_financial_info: bool
    contains_biometric_data: bool
    contains_login_info: bool

    other_pii: str

    @property
    def has_pii(self) -> bool:
        """Check if the document contains any PII"""
        pii_fields = [
            self.contains_names,
            self.contains_email_addresses,
            self.contains_phone_numbers,
            self.contains_addresses,
            self.contains_biographical_info,
            self.contains_location_info,
            self.contains_employment_info,
            self.contains_education_info,
            self.contains_medical_info,
            self.contains_government_ids,
            self.contains_financial_info,
            self.contains_biometric_data,
            self.contains_login_info,
        ]
        return any(pii_fields) or bool(self.other_pii.strip())

    def get_pii_types(self) -> List[str]:
        """Get a list of all PII types found in the document"""
        pii_types = []

        if self.contains_names:
            pii_types.append("names")
        if self.contains_email_addresses:
            pii_types.append("email")
        if self.contains_phone_numbers:
            pii_types.append("phone")
        if self.contains_addresses:
            pii_types.append("addresses")
        if self.contains_biographical_info:
            pii_types.append("biographical")
        if self.contains_location_info:
            pii_types.append("location")
        if self.contains_employment_info:
            pii_types.append("employment")
        if self.contains_education_info:
            pii_types.append("education")
        if self.contains_medical_info:
            pii_types.append("medical")
        if self.contains_government_ids:
            pii_types.append("government-id")
        if self.contains_financial_info:
            pii_types.append("financial")
        if self.contains_biometric_data:
            pii_types.append("biometric")
        if self.contains_login_info:
            pii_types.append("login-info")
        if self.other_pii.strip():
            pii_types.append("other")

        return pii_types


def parse_args():
    parser = argparse.ArgumentParser(description="Rich Autoscan for OLMO OCR workspace using ChatGPT Vision")
    parser.add_argument("workspace", help="OLMO OCR workspace path (s3://bucket/workspace)")
    parser.add_argument("--workspace_profile", help="AWS profile for accessing workspace (documents and attributes)")
    parser.add_argument("--pdf_profile", help="AWS profile for accessing PDFs (can be different from workspace profile)")
    parser.add_argument("--output_dir", default="dolma_samples", help="Directory to save output files")
    parser.add_argument("--max_workers", type=int, default=16, help="Maximum number of worker threads")
    parser.add_argument("--openai_api_key", help="OpenAI API key (or set OPENAI_API_KEY env var)")
    parser.add_argument("--openai_model", default="gpt-4.1", help="OpenAI model to use")
    parser.add_argument("--attribute_name", default="chatgpt_pii_vision", help="Path to use for attribute naming")
    parser.add_argument("--batch_size", type=int, default=1000, help="Number of documents to process in each batch")
    return parser.parse_args()


def list_result_files(s3_client, workspace_path):
    """List all JSONL files in the workspace documents directory."""
    bucket, prefix = parse_s3_path(workspace_path)
    documents_prefix = os.path.join(prefix, "documents").rstrip("/") + "/"

    all_files = []
    paginator = s3_client.get_paginator("list_objects_v2")

    logger.info(f"Listing files from s3://{bucket}/{documents_prefix}")
    for page in paginator.paginate(Bucket=bucket, Prefix=documents_prefix):
        if "Contents" in page:
            all_files.extend(
                [
                    f"s3://{bucket}/{obj['Key']}"
                    for obj in page["Contents"]
                    if (
                        obj["Key"].endswith(".jsonl")
                        or obj["Key"].endswith(".json")
                        or obj["Key"].endswith(".jsonl.gz")
                        or obj["Key"].endswith(".jsonl.zst")
                        or obj["Key"].endswith(".jsonl.ztd")
                        or obj["Key"].endswith(".jsonl.zstd")
                    )
                ]
            )

            if len(all_files) % 100 == 0:
                logger.info(f"Found {len(all_files)} files so far...")

    logger.info(f"Total files found: {len(all_files)}")
    return all_files


def load_document_file(s3_client, file_path):
    """Load a single document file and return its contents."""
    try:
        # Fetch raw bytes (S3 or local)
        if file_path.startswith("s3://"):
            raw = get_s3_bytes(s3_client, file_path)
        else:
            with open(file_path, "rb") as f:
                raw = f.read()

        # Decompress if needed
        if file_path.endswith(".gz"):
            file_bytes = gzip.decompress(raw)
        elif file_path.endswith(".zst") or file_path.endswith(".ztd") or file_path.endswith(".zstd"):
            dctx = zstd.ZstdDecompressor()
            file_bytes = dctx.decompress(raw, max_output_size=1_000_000_000)
        else:
            file_bytes = raw

        # Return the decoded lines
        return file_bytes.decode("utf-8").strip().split("\n")
    except Exception as e:
        logger.error(f"Error loading file {file_path}: {e}")
        return []


def get_document_info_from_line(line, file_path, line_index):
    """Extract document information from a single line."""
    try:
        doc = json.loads(line)

        # A Dolma document has "text", "metadata", and "attributes" fields
        if "text" not in doc or "metadata" not in doc or "attributes" not in doc:
            logger.warning(f"Document in {file_path} line {line_index} is not a valid Dolma document")
            return None

        # Get the original PDF path from metadata
        pdf_path = doc["metadata"].get("Source-File")
        if not pdf_path:
            return None

        # Get page spans from attributes
        page_spans = doc["attributes"].get("pdf_page_numbers", [])
        if not page_spans:
            return None

        # Just use the first page for each document
        if page_spans:
            page_span = page_spans[0]  # Just get the first page
            if len(page_span) >= 3:
                # Page spans are [start_pos, end_pos, page_num]
                page_num = page_span[2]

                # Extract text for this page
                start_pos, end_pos = page_span[0], page_span[1]
                page_text = doc["text"][start_pos:end_pos].strip()

                # Return the information
                return {
                    "pdf_path": pdf_path,
                    "page_num": page_num,
                    "page_text": page_text,
                    "start_pos": start_pos,
                    "end_pos": end_pos,
                    "doc_id": doc["id"],
                    "source_file": file_path,
                    "line_index": line_index,
                }

        return None
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON in {file_path} line {line_index}")
        return None
    except Exception as e:
        logger.warning(f"Error processing document in {file_path} line {line_index}: {e}")
        return None


def get_all_pages(s3_client, document_files):
    """Get all pages from the document files for processing, preserving file and line order."""
    file_contents = {}

    # First, collect all file paths and their document info
    for file_path in tqdm(document_files, desc="Loading document files"):
        lines = load_document_file(s3_client, file_path)
        if not lines:
            logger.warning(f"Empty or invalid file: {file_path}")
            continue

        # Parse each line for document info
        documents = []
        for i, line in enumerate(lines):
            doc_info = get_document_info_from_line(line, file_path, i)
            # Always add an entry for each line, even if None, to preserve line alignment
            documents.append(doc_info)

        # Store all documents for this file
        file_contents[file_path] = documents
        logger.info(f"Loaded {len(documents)} documents from {file_path}")

    logger.info(f"Loaded documents from {len(file_contents)} files")
    return file_contents


def chatgpt_analyze_page(pdf_path: str, page_num: int, pdf_s3_client, openai_api_key: str, openai_model: str) -> Optional[PIIAnnotation]:
    """Analyze a page using the ChatGPT vision model with structured outputs."""
    try:
        # Download PDF to temp file and render to image
        bucket, key = parse_s3_path(pdf_path)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            pdf_data = pdf_s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
            temp_file.write(pdf_data)
            temp_file_path = temp_file.name

        # Render PDF to base64 image
        base64_image = render_pdf_to_base64png(temp_file_path, page_num, target_longest_image_dim=2048)

        # Clean up temp file
        os.unlink(temp_file_path)

        # Create OpenAI client
        client = OpenAI(api_key=openai_api_key)

        # Prepare the user message with all instructions - Keep exact prompt from autoscan_dolmadocs.py
        user_message = """
You are a document analyzer that identifies Personally Identifiable Information (PII) in documents. 
Your task is to analyze the provided document image and determine:
1. Whether the document is intended for public release or dissemination (e.g., research paper, public report, etc.)
2. If the document contains any PII

For PII identification, follow these specific guidelines:

IDENTIFIERS FOR PII:
The following are considered identifiers that can make information PII:
- Names (full names, first names, last names, nicknames)
- Email addresses
- Phone numbers

PII THAT MUST CO-OCCUR WITH AN IDENTIFIER:
The following types of information should ONLY be marked as PII if they occur ALONGSIDE an identifier (commonly, a person's name):
- Addresses (street address, postal code, etc.)
- Biographical Information (date of birth, place of birth, gender, sexual orientation, race, ethnicity, citizenship/immigration status, religion)
- Location Information (geolocations, specific coordinates)
- Employment Information (job titles, workplace names, employment history)
- Education Information (school names, degrees, transcripts)
- Medical Information (health records, diagnoses, genetic or neural data)

PII THAT OCCURS EVEN WITHOUT AN IDENTIFIER:
The following should ALWAYS be marked as PII even if they do not occur alongside an identifier:
- Government IDs (Social Security Numbers, passport numbers, driver's license numbers, tax IDs)
- Financial Information (credit card numbers, bank account/routing numbers)
- Biometric Data (fingerprints, retina scans, facial recognition data, voice signatures)
- Login information (ONLY mark as PII when a username, password, and login location are present together)

If the document is a form, then only consider fields which are filled out with specific values as potential PII.
If this page does not itself contain PII, but references documents (such as curriculum vitae, personal statements) that typically contain PII, then do not mark it as PII.
Only consider actual occurrences of the PII within the document shown.
"""

        # Use the chat completions API with the custom schema
        completion = client.beta.chat.completions.parse(
            model=openai_model,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_message}, {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{base64_image}"}}],
                }
            ],
            response_format=PIIAnnotation,
            max_tokens=1000,
        )

        return completion.choices[0].message.parsed

    except Exception as e:
        logger.error(f"Error analyzing page {pdf_path} (page {page_num}): {e}")
        return None


def process_single_page(args, doc_info, pdf_s3_client=None):
    """Process a single document and generate attribute data."""
    # Skip if document info is None
    if doc_info is None:
        return None

    # Extract info from the document info
    pdf_path = doc_info["pdf_path"]
    page_num = doc_info["page_num"]
    start_pos = doc_info["start_pos"]
    end_pos = doc_info["end_pos"]
    doc_id = doc_info["doc_id"]
    source_file = doc_info["source_file"]
    line_index = doc_info["line_index"]

    # Use provided PDF S3 client if given, otherwise create one
    if pdf_s3_client is None:
        if args.pdf_profile:
            pdf_session = boto3.Session(profile_name=args.pdf_profile)
            pdf_s3_client = pdf_session.client("s3")
        else:
            pdf_s3_client = boto3.client("s3")

    # Get OpenAI API key
    openai_api_key = args.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OpenAI API key must be provided via --openai_api_key or OPENAI_API_KEY environment variable")

    # Analyze page with ChatGPT
    annotation = chatgpt_analyze_page(pdf_path, page_num, pdf_s3_client, openai_api_key, args.openai_model)

    if not annotation:
        logger.warning(f"No annotation for {pdf_path} page {page_num}")
        return {
            "id": doc_id,
            "line_index": line_index,
            "attributes": None,
            "source_file": source_file,
        }

    # Generate attribute key names using model name
    model_prefix = args.openai_model.replace("/", "_").replace("-", "_").replace(".", "_")
    language_key_name = f"{model_prefix}_language"
    contains_pii_key_name = f"{model_prefix}_contains_pii"

    # Initialize result attributes with all PIIAnnotation fields
    result_attributes = {
        contains_pii_key_name: [[start_pos, end_pos, annotation.has_pii]],
        language_key_name: [[start_pos, end_pos, annotation.language_code.name]],
        f"{model_prefix}_is_public_document": [[start_pos, end_pos, annotation.is_public_document]],
        f"{model_prefix}_contains_names": [[start_pos, end_pos, annotation.contains_names]],
        f"{model_prefix}_contains_email_addresses": [[start_pos, end_pos, annotation.contains_email_addresses]],
        f"{model_prefix}_contains_phone_numbers": [[start_pos, end_pos, annotation.contains_phone_numbers]],
        f"{model_prefix}_contains_addresses": [[start_pos, end_pos, annotation.contains_addresses]],
        f"{model_prefix}_contains_biographical_info": [[start_pos, end_pos, annotation.contains_biographical_info]],
        f"{model_prefix}_contains_location_info": [[start_pos, end_pos, annotation.contains_location_info]],
        f"{model_prefix}_contains_employment_info": [[start_pos, end_pos, annotation.contains_employment_info]],
        f"{model_prefix}_contains_education_info": [[start_pos, end_pos, annotation.contains_education_info]],
        f"{model_prefix}_contains_medical_info": [[start_pos, end_pos, annotation.contains_medical_info]],
        f"{model_prefix}_contains_government_ids": [[start_pos, end_pos, annotation.contains_government_ids]],
        f"{model_prefix}_contains_financial_info": [[start_pos, end_pos, annotation.contains_financial_info]],
        f"{model_prefix}_contains_biometric_data": [[start_pos, end_pos, annotation.contains_biometric_data]],
        f"{model_prefix}_contains_login_info": [[start_pos, end_pos, annotation.contains_login_info]],
        f"{model_prefix}_other_pii": [[start_pos, end_pos, annotation.other_pii]],
    }

    # Return document ID, line index, and attributes
    return {
        "id": doc_id,
        "line_index": line_index,
        "attributes": result_attributes,
        "source_file": source_file,
    }


def write_attribute_file(args, processed_docs, file_documents, workspace_s3):
    """Write attribute results to the appropriate files, preserving exact line order."""
    # Group results by source file and organize by line index
    results_by_file = {}
    for result in processed_docs:
        if result is None:
            continue

        source_file = result["source_file"]
        if source_file not in results_by_file:
            results_by_file[source_file] = {}

        # Store by line index to preserve order
        results_by_file[source_file][result["line_index"]] = {"id": result["id"], "attributes": result["attributes"]}

    # Process each source file
    for source_file, file_results_dict in results_by_file.items():
        try:
            # 1. Build the relative path that mirrors documents/…
            if source_file.startswith("s3://"):
                _, key = parse_s3_path(source_file)
                _, docs_prefix = parse_s3_path(args.workspace)
                rel_path = key[len(os.path.join(docs_prefix, "documents/")) :]
            else:
                docs_root = os.path.join(args.workspace, "documents")
                rel_path = os.path.relpath(source_file, docs_root)

            # 2. Create ordered attribute entries in exact same order as source file
            file_entries = []
            # Get the original documents to ensure we have ALL lines in order
            original_docs = file_documents[source_file]

            # Create attribute entries for every line
            for i, doc_info in enumerate(original_docs):
                if i in file_results_dict and file_results_dict[i]["attributes"] is not None:
                    # We have a processed result for this line
                    file_entries.append(file_results_dict[i])
                elif doc_info is not None:
                    # We have document info but no processed attributes (processing failed)
                    # Create an empty attributes entry with the correct ID
                    file_entries.append({"id": doc_info["doc_id"], "attributes": {}})
                else:
                    # This line in the source file was invalid or not a document
                    # Create a placeholder with a generated ID
                    placeholder_id = f"placeholder_{source_file}_{i}"
                    file_entries.append({"id": placeholder_id, "attributes": {}})

            # 3. Create output JSONL
            out_rel = os.path.join("attributes", args.attribute_name, rel_path)
            out_jsonl = "\n".join(json.dumps(entry) for entry in file_entries) + "\n"

            # 4. Preserve compression type
            if rel_path.endswith(".gz"):
                payload = gzip.compress(out_jsonl.encode("utf-8"))
            elif rel_path.endswith((".zst", ".ztd", ".zstd")):
                payload = zstd.ZstdCompressor().compress(out_jsonl.encode("utf-8"))
            else:
                payload = out_jsonl.encode("utf-8")

            # 5. Write to args.workspace (local or S3)
            if args.workspace.startswith("s3://"):
                bucket, prefix = parse_s3_path(args.workspace)
                key = os.path.join(prefix, out_rel)
                workspace_s3.put_object(Bucket=bucket, Key=key, Body=payload)
                logger.info(f"Wrote {len(file_entries)} attribute entries to s3://{bucket}/{key}")
            else:
                out_path = os.path.join(args.workspace, out_rel)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as fh:
                    fh.write(payload)
                logger.info(f"Wrote {len(file_entries)} attribute entries to {out_path}")

        except Exception as e:
            logger.error(f"Error writing attributes for {source_file}: {e}")
            continue


def save_results(results, output_dir):
    """Save the full results to a JSON file for analysis."""
    output_path = Path(output_dir) / "rich_autoscan_results.json"

    # Convert results to serializable format
    serializable_results = []
    for result in results:
        if result is None:
            continue
        serializable_results.append(result)

    with open(output_path, "w") as f:
        json.dump(serializable_results, f, indent=2, default=lambda o: o.value if isinstance(o, Enum) else o)

    print(f"Results saved to {output_path}")


def main():
    args = parse_args()

    # Set up S3 clients with appropriate profiles
    if args.workspace_profile:
        workspace_session = boto3.Session(profile_name=args.workspace_profile)
        workspace_s3 = workspace_session.client("s3")
        logger.info(f"Using AWS profile '{args.workspace_profile}' for workspace access")
    else:
        workspace_s3 = boto3.client("s3")
        logger.info("Using default AWS credentials for workspace access")

    if args.pdf_profile:
        pdf_session = boto3.Session(profile_name=args.pdf_profile)
        pdf_s3 = pdf_session.client("s3")
        logger.info(f"Using AWS profile '{args.pdf_profile}' for PDF access")
    else:
        # If no PDF profile specified, use the workspace profile or default
        if args.workspace_profile:
            pdf_s3 = workspace_s3
            logger.info(f"Using workspace profile '{args.workspace_profile}' for PDF access")
        else:
            pdf_s3 = boto3.client("s3")
            logger.info("Using default AWS credentials for PDF access")

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # List all document files
    logger.info(f"Listing document files in {args.workspace}/documents...")
    document_files = list_result_files(workspace_s3, args.workspace)
    logger.info(f"Found {len(document_files)} document files")

    # Load all document files and their contents, organized by file
    logger.info("Loading all document files...")
    file_documents = get_all_pages(workspace_s3, document_files)

    # Process each file individually
    for file_index, (file_path, documents) in enumerate(file_documents.items()):
        logger.info(f"Processing file {file_index+1}/{len(file_documents)}: {file_path}")

        # Only process documents that have valid information
        valid_docs = []
        for doc in documents:
            if doc is not None:
                valid_docs.append(doc)

        # Skip if no valid documents
        if not valid_docs:
            logger.warning(f"No valid documents in {file_path}")
            continue

        # Process in batches to manage memory and API rate limits
        total_docs = len(valid_docs)
        logger.info(f"Found {total_docs} valid documents to process in {file_path}")

        # Process in batches (process by document, but maintain file coherence)
        all_results = []
        for i in range(0, total_docs, args.batch_size):
            batch = valid_docs[i : i + args.batch_size]
            batch_num = i // args.batch_size + 1
            total_batches = (total_docs + args.batch_size - 1) // args.batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} of {file_path} ({len(batch)} documents)...")
            results = []

            with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                futures = []
                # Process documents in parallel but within the same file
                for doc_info in batch:
                    futures.append(executor.submit(process_single_page, args, doc_info, pdf_s3))

                for future in tqdm(futures, desc=f"Processing batch {batch_num} of {file_path}"):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Error processing document: {e}")

            # Save results for this batch
            batch_output_dir = os.path.join(args.output_dir, f"file_{file_index+1}_batch_{batch_num}")
            os.makedirs(batch_output_dir, exist_ok=True)
            save_results(results, batch_output_dir)

            # Collect all results for this file
            all_results.extend(results)
            logger.info(f"Completed batch {batch_num}/{total_batches} of {file_path}")

        # Write attributes for the entire file, maintaining line order
        write_attribute_file(args, all_results, file_documents, workspace_s3)
        logger.info(f"Completed processing file {file_index+1}/{len(file_documents)}: {file_path}")

    logger.info(f"Processing complete - processed {len(file_documents)} files")


if __name__ == "__main__":
    main()
