# This script prepares transcriptions from the National Archives into a format usable by olmOCR
# What it will do is take in a path which will contain a folder structure of either collections or record groups from the NA
# Inside each of those folders, it will go and read every jsonl file and check each record
# {
#     "record": {
#         "accessRestriction": {
#             "status": "Unrestricted"
#         },
# ....
# So, first we check to see that the record.accessRestriction.status is Unrestricted
# Next, we go look for the digitalObjects section
# "digitalObjects": [
#     {
#         "objectFileSize": 12368728,
#         "objectFilename": "23857158-001-068-0001.tif",
#         "objectId": "310993715",
#         "objectType": "Image (TIFF)",
#         "objectUrl": "https://s3.amazonaws.com/NARAprodstorage/lz/dc-metro/rg-341/23857158/23857158-001-068/23857158-001-068-0001.tif"
#     },
#     {
#         "objectFileSize": 9496446,
#         "objectFilename": "23857158-001-068-0002.tif",
#         "objectId": "310993716",
#         "objectType": "Image (TIFF)",
#         "objectUrl": "https://s3.amazonaws.com/NARAprodstorage/lz/dc-metro/rg-341/23857158/23857158-001-068/23857158-001-068-0002.tif"
#     }, ...
# If they are images, we download them and move onto to the next phase
# Where we look at record_transcription tags...
# "record_transcription": [
#         {
#             "contribution": "This is the transcription",
#             "contributionId": "b1200268-0802-3e96-950e-86cb490af7a5",
#             "contributionSequence": 2,
#             "contributionType": "transcription",
#             "contributors": [
#                 {
#                     "contributionSequence": 1,
#                     "createdAt": "2018-09-07 22:03:02",
#                     "fullName": "Cody Jones",
#                     "naraStaff": false,
#                     "userId": "dff3eed0-38e5-35fc-b7e7-d2d58b023262",
#                     "userName": "Avogadro"
#                 },
#                 {
#                     "contributionSequence": 2,
#                     "createdAt": "2018-09-07 22:05:53",
#                     "fullName": "Cody Jones",
#                     "naraStaff": false,
#                     "userId": "dff3eed0-38e5-35fc-b7e7-d2d58b023262",
#                     "userName": "Avogadro"
#                 }
#             ],
#             "createdAt": "2018-09-07 22:05:53",
#             "parentContributionId": "01c9fab3-8d1e-3027-96f9-890728825f63",
#             "recordType": "contribution",
#             "target": {
#                 "naId": 75718510,
#                 "objectId": "75718511",
#                 "pageNum": 1
#             }
#         }
# We also check the  record tag to make sure aiMachineGenerated is false
# "record_tag": [
#         {
#             "aiMachineGenerated": false,
#             "contribution": "uap-tx-2023",
#             "contributionId": "2f3e9a6e-cfb9-4823-8251-a0f2d129b9e2",
#             "contributionType": "tag",
#             "contributor": {
#                 "fullName": "Erica Boudreau",
#                 "naraStaff": true,
#                 "userId": "8882c6b7-0906-3298-916b-d35132a528be",
#                 "userName": "NARADescriptionProgramStaff"
#             },
#             "createdAt": "2024-12-16 16:47:12",
#             "recordType": "contribution",
#             "source": "naraStaff",
#             "target": {
#                 "naId": 310993714
#             }
#         },
# Then, for each image, which is typically a scanned document page, we create a dataset in olmocr-format, where you have a .md file and a .pdf file named with the ItemID in a folder structure for
# each initial jsonl file. Ex if you had rg_341/rg_341-53.jsonl, then you'd make rg_341/object_id.md and rg_341/object_id.pdf
# If you have a TIFF file, you can compress it to jpg at 98% quality, targetting around 1-2MB in size.
# Output files are named as naId-objectId-page-pageNum.{md,pdf} based on the target object from transcriptions.
# Each JSONL file gets its own subfolder for organization.

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import requests
from PIL import Image
from tqdm import tqdm

from olmocr.image_utils import convert_image_to_pdf_bytes


def download_image(url: str, output_path: Path, max_retries: int = 5) -> bool:
    """Download image from URL with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=60, stream=True)
            response.raise_for_status()

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed for {url}: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** (attempt + 1)
                time.sleep(wait_time)
    return False


def process_image_file(image_path: Path, output_path: Path, target_size_mb: float = 1.5) -> bool:
    """Process image file - convert TIFF/JP2 to JPEG if needed, then to PDF."""
    try:
        # Check file extension
        ext = image_path.suffix.lower()

        # For JP2 and TIFF files, convert to JPEG first
        if ext in [".tif", ".tiff", ".jp2"]:
            img = Image.open(image_path)

            # Convert to RGB if necessary
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Start with quality 98 and reduce if file is too large
            quality = 98
            temp_jpg = image_path.with_suffix(".jpg")

            while quality >= 70:
                # Save with current quality
                img.save(temp_jpg, "JPEG", quality=quality)

                # Check file size
                size_mb = temp_jpg.stat().st_size / (1024 * 1024)
                if size_mb <= target_size_mb:
                    break

                # Reduce quality for next iteration
                quality -= 5

            # Convert JPEG to PDF
            with open(output_path, "wb") as f:
                f.write(convert_image_to_pdf_bytes(str(temp_jpg)))

            # Clean up temp file
            temp_jpg.unlink(missing_ok=True)

        else:
            # For other formats, convert directly to PDF
            with open(output_path, "wb") as f:
                f.write(convert_image_to_pdf_bytes(str(image_path)))

        return True
    except Exception as e:
        print(f"Failed to process image {image_path}: {e}")
        return False


def extract_transcriptions_with_target(record: Dict, object_id: str) -> Tuple[str, Optional[Dict]]:
    """Extract transcriptions and target info for a specific object ID.
    Returns (transcription_text, target_dict)
    """
    # Check if record_transcription exists
    if "record_transcription" not in record:
        return None, None

    for trans in record.get("record_transcription", []):
        # Check if this transcription is for our object
        target = trans.get("target", {})
        if str(target.get("objectId")) == str(object_id):
            # Check contributionType is transcription
            if trans.get("contributionType") == "transcription":
                contribution = trans.get("contribution", "")
                if contribution:
                    return contribution, target

    # If nothing was found, then we will be skipping this entry
    return None, None


def check_ai_generated_tags(record: Dict) -> bool:
    """Check if any tags are AI/machine generated."""
    for tag in record.get("record_tag", []):
        if tag.get("aiMachineGenerated", False):
            return True
    return False


def scan_existing_outputs(output_dir: Path) -> Set[str]:
    """Scan output directory to find all already processed items.
    Returns set of processed identifiers in format 'naId-objectId-pageNum'
    """
    processed_items = set()

    if not output_dir.exists():
        return processed_items

    # Scan each subdirectory (including nested subdirs for JSONL files)
    for subdir in output_dir.rglob("*"):
        if not subdir.is_dir():
            continue

        # Find all pairs of .pdf and .md files
        pdf_files = {f.stem for f in subdir.glob("*.pdf")}
        md_files = {f.stem for f in subdir.glob("*.md")}

        # Only consider fully processed (both pdf and md exist)
        complete_files = pdf_files.intersection(md_files)

        # Verify PDF files are not empty (md can be empty)
        for filename in complete_files:
            pdf_path = subdir / f"{filename}.pdf"
            if pdf_path.stat().st_size > 0:
                processed_items.add(filename)

    return processed_items


def process_single_record(
    record_data: Dict, output_dir: Path, processed_lock: threading.Lock, processed_items: Set[str], jsonl_stem: str
) -> Tuple[int, int, int]:
    """Process a single record. Returns (processed_count, skipped_count, error_count)."""

    processed = 0
    skipped = 0
    errors = 0

    # Check access restriction
    if record_data.get("record", {}).get("accessRestriction", {}).get("status") != "Unrestricted":
        return 0, 1, 0

    record = record_data.get("record", {})

    # Skip if AI generated tags
    if check_ai_generated_tags(record_data):
        return 0, 1, 0

    # Process digital objects
    digital_objects = record.get("digitalObjects", [])

    for obj in digital_objects:
        object_id = obj.get("objectId", "")
        object_type = obj.get("objectType", "")
        object_url = obj.get("objectUrl", "")

        if not object_id or not object_url:
            skipped += 1
            continue

        # Check if it's an image type
        if not any(img_type in object_type.lower() for img_type in ["image", "tiff", "jp2", "jpeg", "jpg"]):
            skipped += 1
            continue

        # Extract transcription and target info
        transcription, target_info = extract_transcriptions_with_target(record_data, object_id)

        if transcription is None or target_info is None:
            skipped += 1
            continue

        # Build filename from target info
        na_id = target_info.get("naId", "")
        obj_id = target_info.get("objectId", object_id)
        page_num = target_info.get("pageNum", 1)
        filename = f"{na_id}-{obj_id}-page-{page_num}"

        # Check if already processed
        with processed_lock:
            if filename in processed_items:
                processed += 1
                continue

        # Create subfolder for this JSONL file
        jsonl_output_dir = output_dir / jsonl_stem
        jsonl_output_dir.mkdir(exist_ok=True)

        # Define output paths
        pdf_path = jsonl_output_dir / f"{filename}.pdf"
        md_path = jsonl_output_dir / f"{filename}.md"

        # Double-check files on disk
        if pdf_path.exists() and md_path.exists():
            if pdf_path.stat().st_size > 0:
                with processed_lock:
                    processed_items.add(object_id)
                processed += 1
                continue

        # Create temp directory
        temp_dir = jsonl_output_dir / "temp"
        temp_dir.mkdir(exist_ok=True)

        try:
            # Download image
            ext = Path(object_url).suffix or ".jpg"
            image_path = temp_dir / f"{object_id}_{threading.current_thread().ident}{ext}"

            if not download_image(object_url, image_path):
                raise Exception(f"Failed to download image")

            # Process and convert to PDF
            if not process_image_file(image_path, pdf_path):
                raise Exception(f"Failed to convert to PDF")

            # Create markdown file (can be empty)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(transcription)

            # Verify files created
            if pdf_path.exists() and md_path.exists():
                if pdf_path.stat().st_size > 0:
                    with processed_lock:
                        processed_items.add(filename)
                    processed += 1

                    # Clean up temp image
                    image_path.unlink(missing_ok=True)
                else:
                    raise Exception("PDF file is empty")
            else:
                raise Exception("Output files were not created")

        except Exception as e:
            print(f"Error processing object {object_id}: {e}")
            errors += 1
            # Clean up any partial files
            pdf_path.unlink(missing_ok=True)
            md_path.unlink(missing_ok=True)
            if "image_path" in locals() and image_path.exists():
                image_path.unlink(missing_ok=True)

    return processed, skipped, errors


def process_jsonl_file(jsonl_path: Path, output_dir: Path, processed_items: Set[str], max_workers: int = 1) -> None:
    """Process a single JSONL file containing National Archives records."""

    # Create output subdirectory based on parent folder name
    parent_name = jsonl_path.parent.name
    dataset_output_dir = output_dir / parent_name
    dataset_output_dir.mkdir(parents=True, exist_ok=True)

    # Get JSONL file stem for subfolder creation
    jsonl_stem = jsonl_path.stem

    print(f"\nProcessing {jsonl_path.name} with {max_workers} workers")

    # Read JSONL file
    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not records:
        print(f"  No valid records found in {jsonl_path.name}")
        return

    # Thread-safe lock
    processed_lock = threading.Lock()
    total_processed = 0
    total_skipped = 0
    total_errors = 0

    # Process records in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_single_record, record, dataset_output_dir, processed_lock, processed_items, jsonl_stem): record for record in records
        }

        with tqdm(total=len(records), desc=f"Processing {parent_name}/{jsonl_path.stem}") as pbar:
            for future in as_completed(futures):
                processed, skipped, errors = future.result()
                total_processed += processed
                total_skipped += skipped
                total_errors += errors
                pbar.update(1)

    # Clean up temp directories in all jsonl subfolders
    for jsonl_subdir in dataset_output_dir.glob("*/"):
        if jsonl_subdir.is_dir():
            temp_dir = jsonl_subdir / "temp"
            if temp_dir.exists():
                for temp_file in temp_dir.glob("*"):
                    temp_file.unlink(missing_ok=True)
                try:
                    temp_dir.rmdir()
                except:
                    pass

    print(f"Completed {jsonl_path.name}: {total_processed} processed, {total_skipped} skipped, {total_errors} errors")


def main():
    parser = argparse.ArgumentParser(description="Prepare National Archives transcriptions for olmOCR training")
    parser.add_argument("--input-dir", type=str, required=True, help="Directory containing National Archives JSONL files")
    parser.add_argument("--output-dir", type=str, required=True, help="Output directory for processed files")
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

    # Find all JSONL files recursively
    jsonl_files = sorted(input_dir.rglob("*.jsonl"))

    if not jsonl_files:
        print(f"No JSONL files found in {input_dir}")
        return

    print(f"Found {len(jsonl_files)} JSONL files to process")
    print(f"Using {args.parallel} parallel workers")

    # Scan existing outputs to avoid reprocessing
    print("Scanning existing outputs...")
    processed_items = scan_existing_outputs(output_dir)

    if processed_items:
        print(f"Found {len(processed_items)} already processed items")

    # Process each JSONL file
    for jsonl_file in jsonl_files:
        process_jsonl_file(jsonl_file, output_dir, processed_items, args.parallel)

    print(f"\nAll processing complete. Output saved to {output_dir}")
    print(f"Total items processed: {len(processed_items)}")


if __name__ == "__main__":
    main()
