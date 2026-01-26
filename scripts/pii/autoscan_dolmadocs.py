import argparse
import json
import os
import random
import tempfile
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import boto3
import pydantic
from openai import OpenAI
from tqdm import tqdm

from olmocr.data.renderpdf import render_pdf_to_base64png
from olmocr.cloud_utils import get_s3_bytes, parse_s3_path

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
    parser = argparse.ArgumentParser(description="Automatically scan OLMO OCR workspace results using ChatGPT")
    parser.add_argument("workspace", help="OLMO OCR workspace path (s3://bucket/workspace)")
    parser.add_argument("--pages_per_run", type=int, default=30, help="Number of pages per run")
    parser.add_argument("--pdf_profile", help="AWS profile for accessing PDFs")
    parser.add_argument("--output_dir", default="dolma_samples", help="Directory to save output files")
    parser.add_argument("--max_workers", type=int, default=4, help="Maximum number of worker threads")
    parser.add_argument("--openai_api_key", help="OpenAI API key (or set OPENAI_API_KEY env var)")
    parser.add_argument("--openai_model", default="gpt-4.1", help="OpenAI model to use")
    return parser.parse_args()


def list_result_files(s3_client, workspace_path):
    """List all JSON result files in the workspace results directory."""
    bucket, prefix = parse_s3_path(workspace_path)
    results_prefix = os.path.join(prefix, "results").rstrip("/") + "/"

    all_files = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=results_prefix):
        if "Contents" in page:
            all_files.extend([f"s3://{bucket}/{obj['Key']}" for obj in page["Contents"] if obj["Key"].endswith(".jsonl") or obj["Key"].endswith(".json")])

        # if len(all_files) > 1000:
        #     break

    return all_files


def get_random_pages(s3_client, result_files, count=30):
    """Get random pages from the result files."""
    random_pages = []

    # Try to collect the requested number of pages
    attempts = 0
    max_attempts = count * 3  # Allow extra attempts to handle potential failures

    while len(random_pages) < count and attempts < max_attempts:
        attempts += 1

        # Pick a random result file
        if not result_files:
            print("No result files found!")
            break

        result_file = random.choice(result_files)

        try:
            # Get the content of the file
            content = get_s3_bytes(s3_client, result_file)
            lines = content.decode("utf-8").strip().split("\n")

            if not lines:
                continue

            # Pick a random line (which contains a complete document)
            line = random.choice(lines)
            doc = json.loads(line)

            # A Dolma document has "text", "metadata", and "attributes" fields
            if "text" not in doc or "metadata" not in doc or "attributes" not in doc:
                print(f"Document in {result_file} is not a valid Dolma document")
                continue

            # Get the original PDF path from metadata
            pdf_path = doc["metadata"].get("Source-File")
            if not pdf_path:
                continue

            # Get page spans from attributes
            page_spans = doc["attributes"].get("pdf_page_numbers", [])
            if not page_spans:
                continue

            # Pick a random page span
            page_span = random.choice(page_spans)
            if len(page_span) >= 3:
                # Page spans are [start_pos, end_pos, page_num]
                page_num = page_span[2]

                # Extract text for this page
                start_pos, end_pos = page_span[0], page_span[1]
                page_text = doc["text"][start_pos:end_pos].strip()

                # Include the text snippet with the page info
                random_pages.append((pdf_path, page_num, page_text, result_file))

                if len(random_pages) >= count:
                    break

        except Exception as e:
            print(f"Error processing {result_file}: {e}")
            continue

    print(f"Found {len(random_pages)} random pages from Dolma documents")
    return random_pages


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

        # Prepare the user message with all instructions
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
        print(f"Error analyzing page {pdf_path} (page {page_num}): {e}")
        return None


def create_presigned_url(s3_client, pdf_path, expiration=3600 * 24 * 7):
    """Create a presigned URL for the given S3 path."""
    try:
        bucket, key = parse_s3_path(pdf_path)
        url = s3_client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expiration)
        return url
    except Exception as e:
        print(f"Error creating presigned URL for {pdf_path}: {e}")
        return None


def process_pages(random_pages, pdf_s3_client, openai_api_key, openai_model, max_workers):
    """Process multiple pages in parallel using ThreadPoolExecutor."""
    results = []

    # First generate presigned URLs for all PDFs
    print("Generating presigned URLs for PDFs...")
    presigned_urls = {}
    for pdf_path, page_num, _, _ in random_pages:
        if pdf_path not in presigned_urls and pdf_path.startswith("s3://"):
            url = create_presigned_url(pdf_s3_client, pdf_path)
            if url:
                presigned_urls[pdf_path] = url

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        # Submit all tasks
        for pdf_path, page_num, page_text, result_file in tqdm(random_pages, desc="Submitting pages for analysis"):
            future = executor.submit(chatgpt_analyze_page, pdf_path, page_num, pdf_s3_client, openai_api_key, openai_model)
            futures[future] = (pdf_path, page_num, page_text, result_file)

        # Process results as they complete
        for future in tqdm(futures, desc="Processing results"):
            pdf_path, page_num, page_text, result_file = futures[future]
            try:
                annotation = future.result()
                if annotation:
                    # Get presigned URL with page number
                    presigned_url = None
                    if pdf_path in presigned_urls:
                        presigned_url = f"{presigned_urls[pdf_path]}#page={page_num}"

                    results.append((pdf_path, page_num, page_text, result_file, annotation, presigned_url))
                else:
                    print(f"Failed to get annotation for {pdf_path} (page {page_num})")
            except Exception as e:
                print(f"Error processing {pdf_path} (page {page_num}): {e}")

    return results


def categorize_results(all_results):
    """Categorize results for reporting."""
    categories = {
        "public_document": [],
        "private_document": [],
        "cannot_read": [],
        "report_content": [],
        "no_annotation": [],
    }

    for pdf_path, page_num, page_text, result_file, annotation, presigned_url in all_results:
        if annotation.cannot_read or annotation.language_code != LanguageCode.en:
            categories["cannot_read"].append({"pdf_path": pdf_path, "pdf_page": page_num, "result_file": result_file, "presigned_url": presigned_url})
        elif annotation.inappropriate_content:
            categories["report_content"].append({"pdf_path": pdf_path, "pdf_page": page_num, "result_file": result_file, "presigned_url": presigned_url})
        elif annotation.is_public_document:
            categories["public_document"].append(
                {
                    "pdf_path": pdf_path,
                    "pdf_page": page_num,
                    "result_file": result_file,
                    "pii_types": annotation.get_pii_types(),
                    "has_pii": annotation.has_pii,
                    "description": annotation.other_pii,
                    "presigned_url": presigned_url,
                }
            )
        else:
            # Private document
            categories["private_document"].append(
                {
                    "pdf_path": pdf_path,
                    "pdf_page": page_num,
                    "result_file": result_file,
                    "pii_types": annotation.get_pii_types(),
                    "has_pii": annotation.has_pii,
                    "description": annotation.other_pii,
                    "presigned_url": presigned_url,
                }
            )

    return categories


def print_annotation_report(annotation_results: Dict[str, List[Dict[str, Any]]]):
    """Print a summary report of annotations."""
    total_pages = sum(len(items) for items in annotation_results.values())

    print("\n" + "=" * 80)
    print(f"ANNOTATION REPORT - Total Pages: {total_pages}")
    print("=" * 80)

    # Count pages with PII in public documents
    public_with_pii = [page for page in annotation_results["public_document"] if page.get("has_pii", False)]
    public_without_pii = [page for page in annotation_results["public_document"] if not page.get("has_pii", False)]

    # Count pages with PII in private documents
    private_with_pii = [page for page in annotation_results["private_document"] if page.get("has_pii", False)]
    private_without_pii = [page for page in annotation_results["private_document"] if not page.get("has_pii", False)]

    # Print summary statistics
    print("\nSummary:")
    print(
        f"  Public documents (total): {len(annotation_results['public_document'])} ({len(annotation_results['public_document'])/total_pages*100:.1f}% of all pages)"
    )
    print(f"    - With PII: {len(public_with_pii)} ({len(public_with_pii)/max(1, len(annotation_results['public_document']))*100:.1f}% of public docs)")
    print(
        f"    - Without PII: {len(public_without_pii)} ({len(public_without_pii)/max(1, len(annotation_results['public_document']))*100:.1f}% of public docs)"
    )

    print(
        f"  Private documents (total): {len(annotation_results['private_document'])} ({len(annotation_results['private_document'])/total_pages*100:.1f}% of all pages)"
    )
    print(f"    - With PII: {len(private_with_pii)} ({len(private_with_pii)/max(1, len(annotation_results['private_document']))*100:.1f}% of private docs)")
    print(
        f"    - Without PII: {len(private_without_pii)} ({len(private_without_pii)/max(1, len(annotation_results['private_document']))*100:.1f}% of private docs)"
    )

    print(f"  Unreadable pages: {len(annotation_results['cannot_read'])} ({len(annotation_results['cannot_read'])/total_pages*100:.1f}%)")
    print(f"  Pages with reported content: {len(annotation_results['report_content'])} ({len(annotation_results['report_content'])/total_pages*100:.1f}%)")
    print(f"  Pages without annotation: {len(annotation_results['no_annotation'])} ({len(annotation_results['no_annotation'])/total_pages*100:.1f}%)")

    # Analyze PII types in private documents
    if private_with_pii:
        # Categorize the PII types for clearer reporting
        pii_categories = {
            "Identifiers": ["names", "email", "phone"],
            "PII requiring identifiers": ["addresses", "biographical", "location", "employment", "education", "medical"],
            "Always sensitive PII": ["government-id", "financial", "biometric", "login-info"],
        }

        # Dictionary to track all PII counts
        pii_counts_private = {}
        for page in private_with_pii:
            for pii_type in page.get("pii_types", []):
                pii_counts_private[pii_type] = pii_counts_private.get(pii_type, 0) + 1

        # Print categorized PII counts
        print("\nPII Types in Private Documents:")

        # Print each category
        for category, pii_types in pii_categories.items():
            print(f"\n  {category}:")
            for pii_type in pii_types:
                count = pii_counts_private.get(pii_type, 0)
                if count > 0:
                    print(f"    - {pii_type}: {count} ({count/len(private_with_pii)*100:.1f}%)")

        # Print any other PII types not in our categories (like "other")
        other_pii = [pii_type for pii_type in pii_counts_private.keys() if not any(pii_type in types for types in pii_categories.values())]
        if other_pii:
            print("\n  Other PII types:")
            for pii_type in other_pii:
                count = pii_counts_private.get(pii_type, 0)
                print(f"    - {pii_type}: {count} ({count/len(private_with_pii)*100:.1f}%)")

    # Print detailed report for private documents with PII
    if private_with_pii:
        print("\nDetailed Report - Private Documents with PII:")
        print("-" * 80)
        for i, item in enumerate(private_with_pii, 1):
            pdf_path = item["pdf_path"]
            pdf_page = item["pdf_page"]
            presigned_url = item.get("presigned_url")

            print(f"{i}. PDF: {pdf_path}")
            print(f"   Page: {pdf_page}")
            if presigned_url:
                print(f"   Presigned URL: {presigned_url}")
            print(f"   PII Types: {', '.join(item['pii_types'])}")
            if item.get("description"):
                print(f"   Description: {item['description']}")
            print("-" * 80)

    # Print links to unreadable pages
    # if annotation_results["cannot_read"]:
    #     print("\nUnreadable Pages:")
    #     print("-" * 80)
    #     for i, item in enumerate(annotation_results["cannot_read"], 1):
    #         pdf_path = item["pdf_path"]
    #         pdf_page = item["pdf_page"]
    #         presigned_url = item.get("presigned_url")

    #         print(f"{i}. PDF: {pdf_path}")
    #         print(f"   Page: {pdf_page}")
    #         if presigned_url:
    #             print(f"   Presigned URL: {presigned_url}")
    #         print("-" * 80)

    # Print links to inappropriate content
    if annotation_results["report_content"]:
        print("\nReported Content:")
        print("-" * 80)
        for i, item in enumerate(annotation_results["report_content"], 1):
            pdf_path = item["pdf_path"]
            pdf_page = item["pdf_page"]
            presigned_url = item.get("presigned_url")

            print(f"{i}. PDF: {pdf_path}")
            print(f"   Page: {pdf_page}")
            if presigned_url:
                print(f"   Presigned URL: {presigned_url}")
            print("-" * 80)

    print("\nReport complete.")


def save_results(results, output_dir):
    """Save the results to a JSON file."""
    output_path = Path(output_dir) / "autoscan_results.json"

    # Convert results to serializable format
    serializable_results = []
    for pdf_path, page_num, page_text, result_file, annotation, presigned_url in results:
        serializable_results.append(
            {
                "pdf_path": pdf_path,
                "page_num": page_num,
                "page_text": page_text,
                "result_file": result_file,
                "annotation": annotation.dict(),
                "presigned_url": presigned_url,
            }
        )

    with open(output_path, "w") as f:
        json.dump(serializable_results, f, indent=2, default=lambda o: o.value if isinstance(o, Enum) else o)

    print(f"Results saved to {output_path}")


def main():
    args = parse_args()

    # Get OpenAI API key from args or environment
    openai_api_key = args.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OpenAI API key must be provided via --openai_api_key or OPENAI_API_KEY environment variable")

    # Set up S3 clients
    s3_client = boto3.client("s3")

    # Set up PDF S3 client with profile if specified
    if args.pdf_profile:
        pdf_session = boto3.Session(profile_name=args.pdf_profile)
        pdf_s3_client = pdf_session.client("s3")
    else:
        pdf_s3_client = s3_client

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # List all result files
    print(f"Listing result files in {args.workspace}/results...")
    result_files = list_result_files(s3_client, args.workspace)
    print(f"Found {len(result_files)} result files")

    # Get random pages
    random_pages = get_random_pages(s3_client, result_files, args.pages_per_run)

    # Process pages with ChatGPT
    print(f"Processing {len(random_pages)} pages with ChatGPT...")
    all_results = process_pages(random_pages, pdf_s3_client, openai_api_key, args.openai_model, args.max_workers)

    # Save results
    save_results(all_results, args.output_dir)

    # Categorize and report results
    categorized_results = categorize_results(all_results)
    print_annotation_report(categorized_results)


if __name__ == "__main__":
    main()
