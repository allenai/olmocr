#!/usr/bin/env python3
# Takes a dataset location in olmocr-mix format, (ex. a nested directory structure folder/subfolder/document.md with a corresponding folder/subfolder/document.pdf)
# Then, it will randomly shuffle these (with a fixed seed), and prompt chatgpt to clean up the transcription, and output a cleaned document
# Uses structured output to get a good result, then writes things back in the same format in a new root folder, preserving the original folder structure

import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openai import OpenAI
from pydantic import BaseModel, Field
from pypdf import PdfReader
from tqdm import tqdm

from olmocr.data.renderpdf import render_pdf_to_base64png


# Structured output model for ChatGPT response
class CleanedDocument(BaseModel):
    cleaned_text: str = Field(description="The cleaned and corrected version of the OCR transcription")
    confidence_score: float = Field(description="Confidence score from 0 to 1 indicating how confident the model is in the cleaning", ge=0.0, le=1.0)
    corrections_made: List[str] = Field(description="List of major corrections or improvements made to the text")
    is_page_all_blank: bool = Field(description="Document consists entirely of blank page, or only headers/footers that would otherwise be removed")
    primary_language: str = Field(default="en", description="Primary language of the document (ISO 639-1 code, e.g. 'en' for English, 'es' for Spanish)")
    is_rotation_valid: bool = Field(default=True, description="Whether the page orientation/rotation appears correct")
    rotation_correction: int = Field(default=0, description="Degrees of rotation needed to correct orientation (0, 90, 180, or 270)")
    is_table: bool = Field(default=False, description="Whether the page primarily contains a table")
    is_diagram: bool = Field(default=False, description="Whether the page primarily contains a diagram or figure")


@dataclass
class DocumentPair:
    md_path: Path
    pdf_path: Path
    relative_path: Path  # Relative path from root for preserving structure


def parse_args():
    parser = argparse.ArgumentParser(description="Clean OCR transcriptions using ChatGPT with visual PDF context")
    parser.add_argument("input_dir", help="Input directory containing olmocr-mix format data (MD files with corresponding PDFs)")
    parser.add_argument("output_dir", help="Output directory for cleaned documents (preserves folder structure)")
    parser.add_argument(
        "--openai-api-key", help="OpenAI API key (can also be set via OPENAI_API_KEY environment variable)", default=os.getenv("OPENAI_API_KEY")
    )
    parser.add_argument("--model", default="gpt-4o-2024-08-06", help="OpenAI model to use (default: gpt-4o-mini)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for shuffling documents (default: 42)")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of documents to process in parallel (default: 10)")
    parser.add_argument("--max-documents", type=int, help="Maximum number of documents to process (useful for testing)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip documents that already have cleaned versions in the output directory")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    return parser.parse_args()


def check_single_page_pdf(pdf_path: Path) -> bool:
    """Check if a PDF has exactly one page."""
    try:
        with open(pdf_path, "rb") as pdf_file:
            pdf_reader = PdfReader(pdf_file)
            return len(pdf_reader.pages) == 1
    except Exception as e:
        print(f"Error checking PDF {pdf_path}: {e}")
        return False


def find_document_pairs(input_dir: Path, verbose: bool = False) -> List[DocumentPair]:
    """Find all MD files with corresponding PDF files."""
    pairs = []
    skipped_no_pdf = 0

    for md_path in input_dir.rglob("*.md"):
        # Check for corresponding PDF
        pdf_path = md_path.with_suffix(".pdf")
        if not pdf_path.exists():
            if verbose:
                print(f"Warning: No PDF found for {md_path}")
            skipped_no_pdf += 1
            continue

        relative_path = md_path.relative_to(input_dir)
        pairs.append(DocumentPair(md_path, pdf_path, relative_path))

    if skipped_no_pdf > 0:
        print(f"Skipped {skipped_no_pdf} files without PDFs")

    return pairs


def render_single_page_pdf(pdf_path: Path) -> str:
    """Render a single-page PDF to base64 PNG image."""
    try:
        # Use render_pdf_to_base64png with target_longest_image_dim=2048
        base64_png = render_pdf_to_base64png(str(pdf_path), 1, target_longest_image_dim=2048)  # Always page 1 since we validated it's a single-page PDF
        return base64_png
    except Exception as e:
        raise RuntimeError(f"Could not render PDF {pdf_path}: {e}")


def clean_document_with_chatgpt(client: OpenAI, model: str, md_content: str, pdf_image: str, verbose: bool = False) -> CleanedDocument:
    """Use ChatGPT to clean the OCR transcription with PDF context."""

    # Prepare the messages
    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an expert at cleaning and correcting OCR transcriptions. "
                "You will be given an OCR transcription and an image of the original PDF page. "
                "Your task is to:\n"
                "1. Correct formatting issues.\n"
                "2. Preserve the exact spelling of words from the original document.\n"
                "3. Remove any original transcriber's marks and notes, usually indicated by [ and ] symbols.\n"
                "4. Fix word breaks and line breaks\n"
                "5. Ensure mathematical formulas and special characters are correct\n"
                "6. If there are any figures or charts, label them with the following markdown syntax ![Alt text describing the contents of the figure](page_startx_starty_width_height.png)\n"
                "7. Maintain the semantic structure of the document\n"
                "8. Remove any headers or footers that are not semantically relevant to the main document contents, ex page numbers, document classifications, etc.\n"
                "9. Convert tables into HTML format. Keep the syntax simple, but use <th> for header rows, and use rowspan and colspans appropriately. Don't use <br> inside of table cells, just split that into new rows as needed. Do NOT use LaTeX or Markdown table syntax.\n"
                "10. If the page is blank, you are allowed to return 'null' for the text.\n"
                "Return a cleaned version that accurately represents the original document."
            ),
        }
    ]

    # Add the content with the PDF image
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": f"Please clean the following OCR transcription based on the provided PDF page image:\n\n{md_content}"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{pdf_image}"}},
    ]

    messages.append({"role": "user", "content": content})

    # Make the API call with structured output
    try:
        response = client.beta.chat.completions.parse(
            model=model,
            messages=messages,  # type: ignore
            response_format=CleanedDocument,
            temperature=0.2,  # Lower temperature for more consistent cleaning
            max_tokens=16384,
        )

        parsed_result = response.choices[0].message.parsed
        if parsed_result is None:
            raise ValueError("ChatGPT returned no parsed result")
        return parsed_result
    except Exception as e:
        print(f"Error calling ChatGPT: {e}")
        raise


def process_document(doc_pair: DocumentPair, client: OpenAI, model: str, output_dir: Path, skip_existing: bool, verbose: bool) -> Tuple[bool, str]:
    """Process a single document pair."""

    # Check if output already exists
    output_path = output_dir / doc_pair.relative_path
    if skip_existing and output_path.exists():
        return True, f"Skipped (already exists): {doc_pair.relative_path}"

    try:
        # Check if PDF has exactly one page
        if not check_single_page_pdf(doc_pair.pdf_path):
            return False, f"Skipped multi-page PDF: {doc_pair.pdf_path}"

        # Read the markdown content
        md_content = doc_pair.md_path.read_text(encoding="utf-8")

        # Render the single PDF page
        pdf_image = render_single_page_pdf(doc_pair.pdf_path)

        # Clean with ChatGPT
        cleaned_result = clean_document_with_chatgpt(client, model, md_content, pdf_image, verbose)

        # Create output directory if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare front matter
        front_matter = f"""---
primary_language: {cleaned_result.primary_language}
is_rotation_valid: {str(cleaned_result.is_rotation_valid)}
rotation_correction: {cleaned_result.rotation_correction}
is_table: {str(cleaned_result.is_table)}
is_diagram: {str(cleaned_result.is_diagram)}
---"""

        # Write cleaned text with front matter
        if cleaned_result.is_page_all_blank:
            # For blank pages, write only the front matter, ending exactly after ---
            output_path.write_text(front_matter, encoding="utf-8")
        else:
            # Add front matter and cleaned text with a newline separator
            full_content = front_matter + "\n" + cleaned_result.cleaned_text
            output_path.write_text(full_content, encoding="utf-8")

        # Create soft link for the original MD file as .md.orig
        orig_md_link_path = output_path.with_suffix(".md.orig")
        if orig_md_link_path.exists() or orig_md_link_path.is_symlink():
            orig_md_link_path.unlink()
        orig_md_link_path.symlink_to(doc_pair.md_path.absolute())

        # Create soft link for the PDF file
        pdf_link_path = output_dir / doc_pair.relative_path.with_suffix(".pdf")
        if pdf_link_path.exists() or pdf_link_path.is_symlink():
            pdf_link_path.unlink()
        pdf_link_path.symlink_to(doc_pair.pdf_path.absolute())

        # Also write metadata
        metadata_path = output_path.with_suffix(".json")
        metadata = {
            "original_md": str(doc_pair.md_path),
            "original_pdf": str(doc_pair.pdf_path),
            "confidence_score": cleaned_result.confidence_score,
            "corrections_made": cleaned_result.corrections_made,
            "is_page_all_blank": cleaned_result.is_page_all_blank,
            "primary_language": cleaned_result.primary_language,
            "is_rotation_valid": cleaned_result.is_rotation_valid,
            "rotation_correction": cleaned_result.rotation_correction,
            "is_table": cleaned_result.is_table,
            "is_diagram": cleaned_result.is_diagram,
            "model": model,
            "pages_rendered": 1,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        return True, f"Processed: {doc_pair.relative_path} (confidence: {cleaned_result.confidence_score:.2f})"

    except Exception as e:
        return False, f"Error processing {doc_pair.relative_path}: {e}"


def main():
    args = parse_args()

    # Validate API key
    if not args.openai_api_key:
        print("Error: OpenAI API key is required. Set via --openai-api-key or OPENAI_API_KEY environment variable.")
        sys.exit(1)

    # Initialize OpenAI client
    client = OpenAI(api_key=args.openai_api_key)

    # Set up paths
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        print(f"Error: Input directory {input_dir} does not exist.")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all document pairs
    print(f"Scanning {input_dir} for document pairs...")
    doc_pairs = find_document_pairs(input_dir, args.verbose)
    print(f"Found {len(doc_pairs)} document pairs (will check page count during processing).")

    if not doc_pairs:
        print("No document pairs found.")
        return

    # Shuffle with fixed seed
    random.seed(args.seed)
    random.shuffle(doc_pairs)

    # Limit if requested
    if args.max_documents:
        doc_pairs = doc_pairs[: args.max_documents]
        print(f"Processing first {args.max_documents} documents after shuffling.")

    # Process documents in batches
    successful = 0
    failed = 0
    skipped_multi_page = 0

    with ThreadPoolExecutor(max_workers=args.batch_size) as executor:
        futures = []

        for doc_pair in doc_pairs:
            future = executor.submit(process_document, doc_pair, client, args.model, output_dir, args.skip_existing, args.verbose)
            futures.append(future)

        # Process results with progress bar
        with tqdm(total=len(futures), desc="Processing documents") as pbar:
            for future in as_completed(futures):
                success, message = future.result()
                if success:
                    successful += 1
                else:
                    if "multi-page" in message.lower():
                        skipped_multi_page += 1
                    else:
                        failed += 1

                if args.verbose:
                    tqdm.write(message)

                pbar.update(1)
                pbar.set_postfix({"successful": successful, "skipped": skipped_multi_page, "failed": failed})

    # Print summary
    print(f"\nProcessing complete:")
    print(f"  Successful: {successful}")
    print(f"  Skipped (multi-page): {skipped_multi_page}")
    print(f"  Failed (other errors): {failed}")
    print(f"  Output directory: {output_dir}")


if __name__ == "__main__":
    main()
