#!/usr/bin/env python3
"""
Process OpenAI batch results and create output folder with PDFs and Markdown files.

This script takes completed OpenAI batch results and creates an output folder
that mirrors the original structure with side-by-side PDF and MD files.
"""

import argparse
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional

from tqdm import tqdm


def parse_batch_response(response_line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single line from the batch response file.

    Args:
        response_line: JSON line from batch response file

    Returns:
        Parsed response dictionary or None if error
    """
    try:
        data = json.loads(response_line)

        # Extract the custom_id and response
        custom_id = data.get("custom_id")

        # Check if the response was successful
        if "response" in data and data["response"].get("status_code") == 200:
            body = data["response"]["body"]
            if "choices" in body and len(body["choices"]) > 0:
                content = body["choices"][0]["message"]["content"]
                # Parse the JSON response
                parsed_content = json.loads(content)
                return {"custom_id": custom_id, "content": parsed_content}
        else:
            print(f"Error in response for {custom_id}: {data.get('error', 'Unknown error')}")
            return None

    except Exception as e:
        print(f"Error parsing response line: {e}")
        return None


def format_frontmatter_markdown(response_data: Dict[str, Any]) -> str:
    """
    Format the response data as FrontMatter markdown.

    Args:
        response_data: Parsed response data from OpenAI

    Returns:
        Formatted markdown string with FrontMatter
    """
    # Extract fields from response
    primary_language = response_data.get("primary_language", None)
    is_rotation_valid = response_data.get("is_rotation_valid", True)
    rotation_correction = response_data.get("rotation_correction", 0)
    is_table = response_data.get("is_table", False)
    is_diagram = response_data.get("is_diagram", False)
    natural_text = response_data.get("natural_text", "")

    # Format as FrontMatter
    markdown = "---\n"
    markdown += f"primary_language: {primary_language if primary_language else 'null'}\n"
    markdown += f"is_rotation_valid: {str(is_rotation_valid)}\n"
    markdown += f"rotation_correction: {rotation_correction}\n"
    markdown += f"is_table: {str(is_table)}\n"
    markdown += f"is_diagram: {str(is_diagram)}\n"
    markdown += "---\n"

    # Add the natural text content
    if natural_text:
        markdown += natural_text

    return markdown.strip()


def process_single_result(custom_id: str, response_content: Dict[str, Any], original_pdf_dir: Path, output_dir: Path) -> bool:
    """
    Process a single batch result: copy PDF and create MD file.

    Args:
        custom_id: Custom ID from the batch request
        response_content: Parsed response content
        original_pdf_dir: Directory containing original PDFs
        output_dir: Output directory for results

    Returns:
        True if successful, False otherwise
    """
    try:
        # Reconstruct the original PDF path from custom_id
        # Custom ID format: "folder/filename" (without .pdf)
        pdf_relative_path = f"{custom_id}.pdf"
        original_pdf_path = original_pdf_dir / pdf_relative_path

        if not original_pdf_path.exists():
            print(f"Warning: Original PDF not found: {original_pdf_path}")

            original_pdf_path = str(original_pdf_path)
            pattern = r"(.+?)(-\d+)\.pdf$"
            replacement = r"\1.pdf\2.pdf"

            original_pdf_path = Path(re.sub(pattern, replacement, original_pdf_path))

            if not original_pdf_path.exists():
                print(f"Error: Original PDF not found: {original_pdf_path}")
                return False

        # Create output paths
        output_pdf_path = output_dir / pdf_relative_path
        output_md_path = output_dir / f"{custom_id}.md"

        # Create parent directories if needed
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy the PDF file
        shutil.copy2(original_pdf_path, output_pdf_path)

        # Create the markdown file
        markdown_content = format_frontmatter_markdown(response_content)
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return True

    except Exception as e:
        print(f"Error processing {custom_id}: {e}")
        return False


def process_batch_results(batch_results_dir: Path, original_pdf_dir: Path, output_dir: Path, num_workers: int = 8) -> int:
    """
    Process all batch result files and create output structure.

    Args:
        batch_results_dir: Directory containing batch result JSONL files
        original_pdf_dir: Directory containing original PDFs
        output_dir: Output directory for processed results
        num_workers: Number of parallel workers

    Returns:
        Number of successfully processed results
    """
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all batch result files (both .jsonl and .json)
    batch_files = list(batch_results_dir.glob("*.jsonl")) + list(batch_results_dir.glob("*.json"))

    if not batch_files:
        print(f"No batch result files found in {batch_results_dir}")
        return 0

    print(f"Found {len(batch_files)} batch result files")

    # Collect all results to process
    results_to_process = []

    for batch_file in batch_files:
        print(f"Reading {batch_file.name}...")
        with open(batch_file, "r") as f:
            for line in f:
                if line.strip():
                    parsed = parse_batch_response(line)
                    if parsed:
                        results_to_process.append(parsed)

    total_results = len(results_to_process)
    print(f"Found {total_results} valid results to process")
    print(f"Using {num_workers} parallel workers")

    successful = 0
    failed = 0

    # Process results in parallel
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all processing tasks
        future_to_result = {
            executor.submit(process_single_result, result["custom_id"], result["content"], original_pdf_dir, output_dir): result["custom_id"]
            for result in results_to_process
        }

        # Process results as they complete
        with tqdm(total=total_results, desc="Processing results") as pbar:
            for future in as_completed(future_to_result):
                custom_id = future_to_result[future]

                try:
                    success = future.result()
                    if success:
                        successful += 1
                    else:
                        failed += 1
                except Exception as e:
                    print(f"\nError with {custom_id}: {e}")
                    failed += 1

                pbar.update(1)

    print(f"\nProcessing complete:")
    print(f"  - Successfully processed: {successful}")
    print(f"  - Failed: {failed}")
    print(f"  - Output directory: {output_dir}")

    return successful


def main():
    parser = argparse.ArgumentParser(description="Process OpenAI batch results and create output folder with PDFs and Markdown files")
    parser.add_argument("batch_results_dir", type=str, help="Directory containing completed OpenAI batch result files (JSONL)")
    parser.add_argument(
        "original_pdf_dir", type=str, help="Directory containing original PDF files (e.g., ~/olmOCR-mix-0225/processed_00_documents_eval_s2pdf)"
    )
    parser.add_argument("output_dir", type=str, help="Output directory for processed results with PDFs and MD files")
    parser.add_argument("--num_workers", type=int, default=8, help="Number of parallel workers for processing (default: 8)")

    args = parser.parse_args()

    # Convert paths to Path objects
    batch_results_dir = Path(args.batch_results_dir).expanduser().resolve()
    original_pdf_dir = Path(args.original_pdf_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    # Validate input directories
    if not batch_results_dir.exists():
        print(f"Error: Batch results directory does not exist: {batch_results_dir}")
        return 1

    if not original_pdf_dir.exists():
        print(f"Error: Original PDF directory does not exist: {original_pdf_dir}")
        return 1

    print(f"Batch results directory: {batch_results_dir}")
    print(f"Original PDF directory: {original_pdf_dir}")
    print(f"Output directory: {output_dir}")

    # Process the batch results
    process_batch_results(batch_results_dir=batch_results_dir, original_pdf_dir=original_pdf_dir, output_dir=output_dir, num_workers=args.num_workers)

    return 0


if __name__ == "__main__":
    exit(main())
