# This script prepares Library of congress transcriptions for use with olmOCR training
# Ex. Find proper transcription datasets here: https://www.loc.gov/search/?q=transcription+dataset&st=list&c=150
# Now, download the archives, extract them, and point this script to a list of all the CSVs
# This script will go through each CSV file, convert each page to PDF format, clean up the transcription using a grounded prompt in chatgpt-4o
# and then output data in olmocr-format, where you have a .md file and a .pdf file named with the ItemID in a folder structure for
# each initial CSV

import argparse
import csv
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import requests
from tqdm import tqdm

from olmocr.image_utils import convert_image_to_pdf_bytes


def fix_image_url(url: str) -> str:
    """Fix image URL to use full resolution instead of percentage-based sizing."""
    import re

    # Replace any pct:XX pattern with just "full"
    pattern = r"full/pct:\d+/0/default\.jpg"
    if re.search(pattern, url):
        return re.sub(pattern, "full/full/0/default.jpg", url)
    return url


def download_image(url: str, output_path: Path, max_retries: int = 3) -> bool:
    """Download image from URL with exponential backoff retry logic."""
    # Fix URL if needed
    url = fix_image_url(url)

    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=30, stream=True)
            response.raise_for_status()

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed for {url}: {e}")
            if attempt < max_retries - 1:
                # Exponential backoff: 2^attempt seconds (2, 4, 8, ...)
                wait_time = 2 ** (attempt + 1)
                time.sleep(wait_time)
    return False


def convert_image_to_pdf(image_path: Path, pdf_path: Path) -> bool:
    """Convert image to PDF."""
    try:
        with open(pdf_path, "wb") as f:
            f.write(convert_image_to_pdf_bytes(str(image_path)))
        return True
    except Exception as e:
        print(f"Failed to convert {image_path} to PDF: {e}")
        return False


def create_markdown_file(transcription: str, md_path: Path) -> None:
    """Create markdown file with transcription."""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(transcription)


def get_safe_filename(item_id: str) -> str:
    """Create safe filename from item ID."""
    # Replace problematic characters
    safe_name = item_id.replace("/", "_").replace("\\", "_").replace(":", "_")
    # If the name is too long, hash it
    if len(safe_name) > 200:
        hash_suffix = hashlib.md5(safe_name.encode()).hexdigest()[:8]
        safe_name = safe_name[:150] + "_" + hash_suffix
    return safe_name


def scan_existing_outputs(output_dir: Path) -> Set[str]:
    """Scan output directory to find all already processed assets."""
    processed_assets = set()

    if not output_dir.exists():
        return processed_assets

    # Scan each dataset subdirectory
    for dataset_dir in output_dir.iterdir():
        if not dataset_dir.is_dir():
            continue

        # Find all pairs of .pdf and .md files
        pdf_files = {f.stem for f in dataset_dir.glob("*.pdf")}
        md_files = {f.stem for f in dataset_dir.glob("*.md")}

        # Only consider fully processed (both pdf and md exist)
        complete_files = pdf_files.intersection(md_files)

        # Verify PDF files are not empty (md can be empty)
        for filename in complete_files:
            pdf_path = dataset_dir / f"{filename}.pdf"
            _md_path = dataset_dir / f"{filename}.md"
            if pdf_path.stat().st_size > 0:  # Only PDF needs to be non-empty
                processed_assets.add(filename)

    return processed_assets


def process_single_item(
    row: Dict[str, str], dataset_output_dir: Path, skip_cleanup: bool, processed_lock: threading.Lock, processed_assets: Set[str]
) -> Tuple[str, bool, Optional[str]]:
    """Process a single row/item from the CSV. Returns (asset, success, error_msg)."""

    # Check required fields (Transcription can be empty)
    if not all(key in row for key in ["Asset", "DownloadUrl"]):
        return ("", False, "Missing required fields")

    # Check AssetStatus is completed
    asset_status = row.get("AssetStatus", "")
    if asset_status != "completed":
        return (row.get("Asset", ""), False, f"AssetStatus is not completed: {asset_status}")

    asset = row["Asset"]
    download_url = row["DownloadUrl"]
    transcription = row.get("Transcription", "")  # Allow empty transcription

    if not asset or not download_url:
        return (asset, False, "Empty required fields (Asset or DownloadUrl)")

    # Create safe filename using Asset column
    safe_filename = get_safe_filename(asset)

    # Check if already processed (thread-safe)
    with processed_lock:
        if safe_filename in processed_assets:
            return (asset, True, None)

    # Define output paths
    pdf_path = dataset_output_dir / f"{safe_filename}.pdf"
    md_path = dataset_output_dir / f"{safe_filename}.md"

    # Double-check if files already exist on disk
    if pdf_path.exists() and md_path.exists():
        # Verify PDF is not empty (md can be empty)
        if pdf_path.stat().st_size > 0:
            with processed_lock:
                processed_assets.add(safe_filename)
            return (asset, True, None)
        else:
            # Remove files to reprocess if PDF is empty
            pdf_path.unlink(missing_ok=True)
            md_path.unlink(missing_ok=True)

    # Process the item
    temp_dir = dataset_output_dir / "temp"
    temp_dir.mkdir(exist_ok=True)

    try:
        # Download image with unique temp filename to avoid collisions
        image_path = temp_dir / f"{safe_filename}_{threading.current_thread().ident}.jpg"

        if not download_image(download_url, image_path):
            raise Exception(f"Failed to download image")

        # Convert to PDF
        if not convert_image_to_pdf(image_path, pdf_path):
            raise Exception(f"Failed to convert image to PDF")

        # Clean up transcription if needed (skipping for now)
        if skip_cleanup:
            cleaned_transcription = transcription
        else:
            # TODO: Add transcription cleanup using GPT-4o
            cleaned_transcription = transcription

        # Create markdown file
        create_markdown_file(cleaned_transcription, md_path)

        # Verify both files exist (md can be empty, pdf should not be)
        if pdf_path.exists() and md_path.exists():
            if pdf_path.stat().st_size > 0:  # Only PDF needs to be non-empty
                with processed_lock:
                    processed_assets.add(safe_filename)

                # Clean up temp image
                image_path.unlink(missing_ok=True)
                return (asset, True, None)
            else:
                raise Exception("PDF file is empty")
        else:
            raise Exception("Output files were not created")

    except Exception as e:
        # Clean up any partial files
        pdf_path.unlink(missing_ok=True)
        md_path.unlink(missing_ok=True)
        if "image_path" in locals() and image_path.exists():
            image_path.unlink(missing_ok=True)
        return (asset, False, str(e))


def process_csv_file(csv_path: Path, output_dir: Path, processed_assets: Set[str], skip_cleanup: bool = True, max_workers: int = 1) -> None:
    """Process a single CSV file containing LOC transcription data with parallel processing."""
    csv_name = csv_path.stem
    dataset_output_dir = output_dir / csv_name
    dataset_output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nProcessing {csv_path.name} with {max_workers} workers")

    # Read CSV
    with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Filter out already processed items upfront
    rows_to_process = []
    already_done = 0

    for row in rows:
        if "Asset" in row and row["Asset"]:
            safe_filename = get_safe_filename(row["Asset"])
            if safe_filename not in processed_assets:
                rows_to_process.append(row)
            else:
                already_done += 1

    if already_done > 0:
        print(f"  Skipping {already_done} already processed items")

    if not rows_to_process:
        print(f"  All items already processed for {csv_name}")
        return

    # Create temp directory for downloads
    temp_dir = dataset_output_dir / "temp"
    temp_dir.mkdir(exist_ok=True)

    # Thread-safe counters and lock
    processed_lock = threading.Lock()
    processed = already_done
    newly_processed = 0
    skipped = 0

    # Process items in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(process_single_item, row, dataset_output_dir, skip_cleanup, processed_lock, processed_assets): row for row in rows_to_process
        }

        # Process results with progress bar
        with tqdm(total=len(rows_to_process), desc=f"Processing {csv_name}") as pbar:
            for future in as_completed(futures):
                asset, success, error_msg = future.result()

                if success:
                    with processed_lock:
                        processed += 1
                        if error_msg is None:  # None means newly processed
                            newly_processed += 1
                else:
                    with processed_lock:
                        skipped += 1
                    if error_msg and asset:
                        tqdm.write(f"Error processing {asset}: {error_msg}")

                pbar.update(1)

    # Clean up temp directory
    if temp_dir.exists():
        # Remove any remaining temp files
        for temp_file in temp_dir.glob("*"):
            temp_file.unlink(missing_ok=True)
        try:
            temp_dir.rmdir()
        except:
            pass

    print(f"Completed {csv_name}: {processed} total processed ({newly_processed} new), {skipped} skipped")


def main():
    parser = argparse.ArgumentParser(description="Prepare LOC transcriptions for olmOCR training")
    parser.add_argument("--input-dir", type=str, required=True, help="Directory containing CSV files from LOC transcription datasets")
    parser.add_argument("--output-dir", type=str, required=True, help="Output directory for processed files")
    parser.add_argument("--skip-cleanup", action="store_true", default=True, help="Skip transcription cleanup with GPT-4o (default: True)")
    parser.add_argument("--csv-pattern", type=str, default="*.csv", help="Pattern to match CSV files (default: *.csv)")
    parser.add_argument("--parallel", type=int, default=1, help="Number of parallel download/processing threads (default: 1)")

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        print(f"Error: Input directory {input_dir} does not exist")
        return

    if args.parallel < 1:
        print(f"Error: --parallel must be at least 1")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all CSV files
    csv_files = sorted(input_dir.glob(args.csv_pattern))

    if not csv_files:
        print(f"No CSV files found in {input_dir} matching pattern {args.csv_pattern}")
        return

    print(f"Found {len(csv_files)} CSV files to process")
    print(f"Using {args.parallel} parallel workers")

    # Scan existing outputs to avoid reprocessing
    print("Scanning existing outputs...")
    processed_assets = scan_existing_outputs(output_dir)

    if processed_assets:
        print(f"Found {len(processed_assets)} already processed items")

    # Process each CSV file
    for csv_file in csv_files:
        process_csv_file(csv_file, output_dir, processed_assets, args.skip_cleanup, args.parallel)

    print(f"\nAll processing complete. Output saved to {output_dir}")
    print(f"Total items processed: {len(processed_assets)}")


if __name__ == "__main__":
    main()
