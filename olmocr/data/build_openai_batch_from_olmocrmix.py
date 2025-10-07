#!/usr/bin/env python3
"""
Build OpenAI batch requests from OLMoCR-mix folder structure.

This script processes the folder structure created by prepare_olmocrmix.py
and generates OpenAI batch API requests for processing PDFs.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple

from pypdf import PdfReader
from tqdm import tqdm

from olmocr.data.renderpdf import (
    get_png_dimensions_from_base64,
    render_pdf_to_base64png,
)
from olmocr.prompts.prompts import (
    build_openai_silver_data_prompt_v3_simple,
    openai_response_format_schema,
)

TARGET_IMAGE_DIM = 2048
MAX_FILE_SIZE = 99 * 1024 * 1024  # 99MB in bytes


def validate_single_page_pdf(pdf_path: Path) -> bool:
    """
    Validate that a PDF has exactly one page.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        True if PDF has exactly one page, False otherwise
    """
    try:
        pdf = PdfReader(pdf_path)
        return len(pdf.pages) == 1
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
        return False


def build_custom_id(pdf_path: Path, base_dir: Path) -> str:
    """
    Build a custom ID for the request that can be used to recover the file later.

    The ID preserves the full path structure for easy recovery.
    Example: extracted/document_id.pdf becomes "extracted/document_id"

    Args:
        pdf_path: Full path to the PDF file
        base_dir: Base directory containing the processed folder

    Returns:
        Custom ID string that preserves path structure
    """
    # Get relative path from base directory
    rel_path = pdf_path.relative_to(base_dir)
    # Remove .pdf extension but keep directory structure
    path_without_ext = str(rel_path).replace(".pdf", "")
    return path_without_ext


def process_single_pdf(pdf_path: Path, base_dir: Path) -> Optional[Tuple[Dict[str, Any], Path]]:
    """
    Process a single PDF and return the batch request if valid.

    Args:
        pdf_path: Path to the PDF file
        base_dir: Base directory for building custom IDs

    Returns:
        Tuple of (request dict, pdf_path) if successful, None otherwise
    """
    # Validate PDF has single page
    try:
        pdf = PdfReader(pdf_path)
        if len(pdf.pages) != 1:
            return None
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
        return None

    try:
        # Render PDF to base64 image
        image_base64 = render_pdf_to_base64png(str(pdf_path), page_num=1, target_longest_image_dim=TARGET_IMAGE_DIM)

        # Get image dimensions for the prompt
        width, height = get_png_dimensions_from_base64(image_base64)

        # Build the prompt using v3 simple version
        prompt = build_openai_silver_data_prompt_v3_simple(width, height)

        # Build custom ID
        custom_id = build_custom_id(pdf_path, base_dir)

        # Build the request in OpenAI batch format
        request = {
            "custom_id": custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4.1",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                        ],
                    }
                ],
                "temperature": 0.1,
                "max_completion_tokens": 12000,
                "response_format": openai_response_format_schema(),
            },
        }

        return (request, pdf_path)
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}")
        return None


def find_pdf_files(input_dir: Path) -> Generator[Path, None, None]:
    """
    Find all PDF files in the processed folder structure.

    The structure is expected to be:
    processed_XX_subset_split/
        extracted/
            *.pdf

    Or for hugging_face downloads:
    hugging_face/
        pdf_tarballs/
            extracted/
                *.pdf

    Args:
        input_dir: Input directory path

    Yields:
        Path objects for each PDF file found
    """

    for pdf_path in input_dir.rglob("*.pdf"):
        yield pdf_path


def process_pdfs_to_batch_requests(input_dir: Path, output_dir: Path, max_pdfs: int = None, num_workers: int = 8) -> int:
    """
    Process PDFs and create batch request files using parallel processing.

    Args:
        input_dir: Directory containing the processed folder structure
        output_dir: Directory to save batch request files
        max_pdfs: Maximum number of PDFs to process (None for all)
        num_workers: Number of parallel workers for processing

    Returns:
        Number of PDFs processed
    """
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize file management
    file_num = 0
    current_file_size = 0
    current_file_path = output_dir / f"batch_requests_{file_num:04d}.jsonl"
    current_file = open(current_file_path, "w")

    pdfs_processed = 0
    pdfs_skipped = 0

    # Find PDF files
    pdf_files = list(find_pdf_files(input_dir))

    # Limit files if max_pdfs is specified
    if max_pdfs:
        pdf_files = pdf_files[:max_pdfs]

    total_pdfs = len(pdf_files)

    print(f"Found {total_pdfs} PDF files to process")
    print(f"Using {num_workers} parallel workers")

    # Process PDFs in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all PDF processing tasks
        future_to_pdf = {executor.submit(process_single_pdf, pdf_path, input_dir): pdf_path for pdf_path in pdf_files}

        # Process results as they complete
        with tqdm(total=total_pdfs, desc="Processing PDFs") as pbar:
            for future in as_completed(future_to_pdf):
                pdf_path = future_to_pdf[future]

                try:
                    result = future.result()

                    if result is None:
                        # PDF was skipped (multi-page or error)
                        pdfs_skipped += 1
                    else:
                        request, _ = result
                        request_json = json.dumps(request)
                        request_size = len(request_json.encode("utf-8"))

                        # Check if we need to start a new file
                        if current_file_size + request_size > MAX_FILE_SIZE:
                            current_file.close()
                            file_num += 1
                            current_file_path = output_dir / f"batch_requests_{file_num:04d}.jsonl"
                            current_file = open(current_file_path, "w")
                            current_file_size = 0
                            print(f"\nStarting new batch file: {current_file_path.name}")

                        # Write the request (only in main thread)
                        current_file.write(request_json)
                        current_file.write("\n")
                        current_file_size += request_size

                        pdfs_processed += 1

                except Exception as e:
                    print(f"\nError with {pdf_path}: {e}")
                    pdfs_skipped += 1

                pbar.update(1)

    # Close the last file
    current_file.close()

    print(f"\nProcessing complete:")
    print(f"  - PDFs processed: {pdfs_processed}")
    print(f"  - PDFs skipped: {pdfs_skipped}")
    print(f"  - Batch files created: {file_num + 1}")
    print(f"  - Output directory: {output_dir}")

    return pdfs_processed


def main():
    parser = argparse.ArgumentParser(description="Build OpenAI batch requests from OLMoCR-mix folder structure")
    parser.add_argument("--output_dir", type=str, default=None, help="Output directory for batch request files (default: input_dir/batch_requests)")
    parser.add_argument("--max_pdfs", type=int, default=None, help="Maximum number of PDFs to process (default: all)")
    parser.add_argument("--num_workers", type=int, default=8, help="Number of parallel workers for processing (default: 8)")
    parser.add_argument(
        "input_dir",
        type=str,
        help="Input directory containing processed folder structure (e.g., ~/olmOCR-mix-0225/processed_00_documents_eval_s2pdf or ~/olmOCR-mix-0225)",
    )

    args = parser.parse_args()

    # Convert paths to Path objects
    input_dir = Path(args.input_dir).expanduser().resolve()

    if not input_dir.exists():
        print(f"Error: Input directory does not exist: {input_dir}")
        return 1

    # Set default output directory if not specified
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        output_dir = input_dir / "batch_requests"

    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")

    # Process PDFs
    process_pdfs_to_batch_requests(input_dir=input_dir, output_dir=output_dir, max_pdfs=args.max_pdfs, num_workers=args.num_workers)

    return 0


if __name__ == "__main__":
    exit(main())
