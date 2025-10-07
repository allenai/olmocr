#!/usr/bin/env python3
# Input arguments:
# path to olmocr-bench/bench_data directory
# Path to metadata jsonl file
# Path to sqlite db
# Steps:
# Find all jsonl files in bench_data directory, read all "url" fields and make a set
# In metadata jsonl file, read all lines, get source_url field
# Do mapping between source_url and real_url by
# first turning ex. s3://ai2-s2-pdfs/b2d8/3a50695174f1de4973248fcf03c681ba1218.pdf into b2d83a50695174f1de4973248fcf03c681ba1218
# Then, in sqlite db with schema below, look up the real uri
# CREATE TABLE pdf_mapping (
#                 pdf_hash TEXT PRIMARY KEY,
#                 uri TEXT
#             );
# Report if any of the final uri's match with original set
#
# Also support things if the source_url is in the following format, starting with ./
# ex ./synth_tables/56441bdefb2397d956da725903948e0893c9_pg1.pdf, then get the 56441bdefb2397d956da725903948e0893c9
# Then, using the schema below in the same db, look up the full hash first some this given hash, then get the full uri to continue the lookup
# CREATE TABLE substr_to_full_hash (
#     pdf_hash TEXT PRIMARY KEY,  -- this will be the shortened hash
#     full_hash TEXT              -- this is the original hash
# );

import argparse
import json
import os
import re
import sqlite3
from pathlib import Path


def get_bench_urls(bench_data_dir):
    """Read all JSONL files in bench_data directory and extract URLs."""
    bench_urls = set()
    bench_data_path = Path(bench_data_dir)

    for jsonl_file in bench_data_path.rglob("*.jsonl"):
        with open(jsonl_file, "r") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if "url" in data:
                        bench_urls.add(data["url"])
                except json.JSONDecodeError:
                    continue

    return bench_urls


def s3_url_to_hash(s3_url):
    """Convert S3 URL to hash format.
    e.g., s3://ai2-s2-pdfs/b2d8/3a50695174f1de4973248fcf03c681ba1218.pdf -> b2d83a50695174f1de4973248fcf03c681ba1218
    """
    match = re.search(r"s3://[^/]+/([^/]+)/([^.]+)", s3_url)
    if match:
        prefix = match.group(1)
        hash_part = match.group(2)
        return prefix + hash_part
    return None


def local_path_to_short_hash(local_path):
    """Extract short hash from local path format.
    e.g., ./synth_tables/56441bdefb2397d956da725903948e0893c9_pg1.pdf -> 56441bdefb2397d956da725903948e0893c9
    """
    match = re.search(r"([a-f0-9]+)(?:_pg\d+)?\.pdf", local_path)
    if match:
        return match.group(1)
    return None


def find_and_handle_contaminated_files(metadata_jsonl_path, contaminated_pdf_ids, delete_mode=False):
    """Find and optionally delete files related to contaminated PDFs.

    Returns:
        List of files that were deleted or would be deleted
    """
    # Get the base directory from metadata jsonl path
    metadata_dir = Path(metadata_jsonl_path).parent
    output_dir = metadata_dir.parent  # Go up one level from metadata directory

    # Get the name from the metadata jsonl filename (e.g., "synthetic" from "synthetic.jsonl")
    name = Path(metadata_jsonl_path).stem

    files_to_delete = []

    for pdf_id in contaminated_pdf_ids:
        # Pattern for files related to this pdf_id
        # Based on mine_html_templates.py, the files are named with pattern:
        # {pdf_id}_page{page_num}.{extension}

        # Find HTML files
        html_dir = output_dir / "html" / name
        if html_dir.exists():
            for html_file in html_dir.glob(f"{pdf_id}_page*.html"):
                files_to_delete.append(html_file)

        # Find PDF files (both original and rendered)
        pdfs_dir = output_dir / "pdfs" / name
        if pdfs_dir.exists():
            for pdf_file in pdfs_dir.glob(f"{pdf_id}_page*.pdf"):
                files_to_delete.append(pdf_file)

        # Find markdown files in training directory
        training_dir = output_dir / "training" / name
        if training_dir.exists():
            for md_file in training_dir.glob(f"{pdf_id}_page*.md"):
                files_to_delete.append(md_file)
            # Also check for PDF symlinks
            for pdf_link in training_dir.glob(f"{pdf_id}_page*.pdf"):
                files_to_delete.append(pdf_link)

        # Find files in bench_data directory
        bench_data_dir = output_dir / "bench_data"

        # Check synthetic PDFs subdirectory
        bench_synthetic_dir = bench_data_dir / "pdfs" / name
        if bench_synthetic_dir.exists():
            for pdf_file in bench_synthetic_dir.glob(f"{pdf_id}_page*.pdf"):
                files_to_delete.append(pdf_file)

        # Check claude_original subdirectory
        claude_original_dir = bench_data_dir / "claude_original" / name
        if claude_original_dir.exists():
            for md_file in claude_original_dir.glob(f"{pdf_id}_page*.md"):
                files_to_delete.append(md_file)

    # Remove tests from bench_data JSONL file
    jsonl_file = bench_data_dir / f"{name}.jsonl"
    if jsonl_file.exists():
        # Read all tests
        remaining_tests = []
        removed_tests = 0

        with open(jsonl_file, "r") as f:
            for line in f:
                try:
                    test = json.loads(line)
                    # Check if this test belongs to a contaminated PDF
                    # Test PDFs are in format "{name}/{pdf_id}_page{page_num}.pdf"
                    test_pdf = test.get("pdf", "")
                    is_contaminated = False
                    for pdf_id in contaminated_pdf_ids:
                        if f"{pdf_id}_page" in test_pdf:
                            is_contaminated = True
                            removed_tests += 1
                            break

                    if not is_contaminated:
                        remaining_tests.append(test)
                except json.JSONDecodeError:
                    continue

        if removed_tests > 0:
            if delete_mode:
                # Rewrite the file without contaminated tests
                with open(jsonl_file, "w") as f:
                    for test in remaining_tests:
                        f.write(json.dumps(test) + "\n")
                print(f"Removed {removed_tests} tests from {jsonl_file}")
            else:
                print(f"Would remove {removed_tests} tests from {jsonl_file}")

    # Print summary of files to delete
    if files_to_delete:
        print(f"\n{'Deleting' if delete_mode else 'Would delete'} {len(files_to_delete)} files:")
        for file_path in sorted(files_to_delete):  # Show first 10
            relative_path = file_path.relative_to(output_dir) if output_dir in file_path.parents else file_path
            print(f"  - {relative_path}")

            # Actually delete if in delete mode
            if delete_mode:
                try:
                    if file_path.is_symlink() or file_path.exists():
                        file_path.unlink()
                except Exception as e:
                    print(f"    Error deleting: {e}")

        if delete_mode:
            print(f"\nSuccessfully deleted {len(files_to_delete)} files")
        else:
            print(f"\nTo actually delete these files, run with --delete flag")
    else:
        print("\nNo files found to delete")

    return files_to_delete


def check_contamination(bench_data_dir, metadata_jsonl_path, sqlite_db_path, delete_mode=False):
    """Main function to check for contamination between bench data and training data."""
    print(f"Checking contamination...")
    print(f"Bench data directory: {bench_data_dir}")
    print(f"Metadata JSONL: {metadata_jsonl_path}")
    print(f"SQLite database: {sqlite_db_path}\n")

    # Step 1: Get all URLs from bench data
    print("Step 1: Reading URLs from bench data...")
    bench_urls = get_bench_urls(bench_data_dir)
    print(f"Found {len(bench_urls)} unique URLs in bench data\n")

    # Step 2: Read metadata JSONL and process source URLs
    print("Step 2: Processing metadata JSONL...")
    metadata_entries = []
    with open(metadata_jsonl_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line)
                if "source_url" in data:
                    metadata_entries.append(data)
            except json.JSONDecodeError:
                print(f"Warning: Could not parse line {line_num}")

    print(f"Found {len(metadata_entries)} entries with source URLs in metadata\n")

    # Step 3: Map URLs to hashes and query database
    print("Step 3: Mapping URLs and querying database...")
    conn = sqlite3.connect(sqlite_db_path)
    cursor = conn.cursor()

    real_urls = set()
    unmapped_count = 0
    s3_count = 0
    local_count = 0
    empty_result_count = 0
    blank_url_entries = []  # Store entries with blank URLs

    for metadata_entry in metadata_entries:
        source_url = metadata_entry.get("source_url")
        pdf_id = metadata_entry.get("pdf_id", "N/A")
        pdf_hash = None

        # Handle S3 URLs
        if source_url.startswith("s3://"):
            s3_count += 1
            pdf_hash = s3_url_to_hash(source_url)

        # Handle local paths starting with ./
        elif source_url.startswith("./"):
            local_count += 1
            short_hash = local_path_to_short_hash(source_url)
            if short_hash:
                # First lookup: get full hash from short hash
                cursor.execute("SELECT full_hash FROM substr_to_full_hash WHERE pdf_hash = ?", (short_hash,))
                result = cursor.fetchone()
                if result:
                    pdf_hash = result[0]

        # If we have a hash, look up the real URI
        if pdf_hash:
            cursor.execute("SELECT uri FROM pdf_mapping WHERE pdf_hash = ?", (pdf_hash,))
            result = cursor.fetchone()
            if result:
                # Check if the looked up URL is empty/blank
                if result[0] == "" or result[0] is None:
                    empty_result_count += 1
                    blank_url_entries.append({"pdf_id": pdf_id, "source_url": source_url, "pdf_hash": pdf_hash, "db_result": result[0]})
                else:
                    real_urls.add(result[0])
        else:
            unmapped_count += 1

    conn.close()

    print(list(real_urls)[:5])

    print(f"Successfully mapped {len(real_urls)} URLs from database")
    print(f"  - S3 URLs processed: {s3_count}")
    print(f"  - Local paths processed: {local_count}")
    print(f"  - Empty/blank URLs from database: {empty_result_count}")
    if unmapped_count > 0:
        print(f"Warning: {unmapped_count} URLs could not be mapped\n")

    # Print entries with blank URLs
    if blank_url_entries:
        print(f"\n⚠️  Entries with blank URLs ({len(blank_url_entries)} total):")
        for entry in blank_url_entries[:20]:  # Show first 20
            print(f"  PDF ID: {entry['pdf_id']}")
            print(f"    Source URL: {entry['source_url']}")
            print(f"    PDF Hash: {entry['pdf_hash']}")
            print(f"    DB Result: {repr(entry['db_result'])}")
        if len(blank_url_entries) > 20:
            print(f"  ... and {len(blank_url_entries) - 20} more entries with blank URLs\n")

    # Step 4: Check for contamination
    print("Step 4: Checking for contamination...")
    contaminated_urls = bench_urls.intersection(real_urls)

    # Track which PDF IDs are contaminated (including those with blank URLs)
    contaminated_pdf_ids = set()

    # Add PDF IDs with blank URLs to contaminated set
    for entry in blank_url_entries:
        pdf_id = entry.get("pdf_id", "N/A")
        if pdf_id != "N/A":
            contaminated_pdf_ids.add(pdf_id)

    if contaminated_urls:
        # Find the pdf_ids that correspond to contaminated URLs
        for metadata_entry in metadata_entries:
            source_url = metadata_entry.get("source_url")
            pdf_id = metadata_entry.get("pdf_id", "N/A")
            pdf_hash = None

            # Process URL to get hash
            if source_url.startswith("s3://"):
                pdf_hash = s3_url_to_hash(source_url)
            elif source_url.startswith("./"):
                short_hash = local_path_to_short_hash(source_url)
                if short_hash:
                    conn_temp = sqlite3.connect(sqlite_db_path)
                    cursor_temp = conn_temp.cursor()
                    cursor_temp.execute("SELECT full_hash FROM substr_to_full_hash WHERE pdf_hash = ?", (short_hash,))
                    result = cursor_temp.fetchone()
                    if result:
                        pdf_hash = result[0]
                    conn_temp.close()

            # If we have a hash, look up the real URI
            if pdf_hash:
                conn_temp = sqlite3.connect(sqlite_db_path)
                cursor_temp = conn_temp.cursor()
                cursor_temp.execute("SELECT uri FROM pdf_mapping WHERE pdf_hash = ?", (pdf_hash,))
                result = cursor_temp.fetchone()
                conn_temp.close()

                if result and result[0] and result[0] in contaminated_urls:
                    contaminated_pdf_ids.add(pdf_id)

    # Check if we have any contamination (URL matches or blank URLs)
    total_contaminated = len(contaminated_urls) + len(blank_url_entries)

    if total_contaminated > 0:
        print(f"\n⚠️  CONTAMINATION DETECTED!")
        if contaminated_urls:
            print(f"  - Found {len(contaminated_urls)} matching URLs")
        if blank_url_entries:
            print(f"  - Found {len(blank_url_entries)} entries with blank URLs (treated as contaminated)")
        print(f"  - Total contaminated PDF IDs: {len(contaminated_pdf_ids)}")

        if contaminated_urls:
            print(f"\nMatching URLs (first 10):")
            for url in sorted(contaminated_urls)[:10]:
                print(f"  - {url}")
            if len(contaminated_urls) > 10:
                print(f"  ... and {len(contaminated_urls) - 10} more")

        # Handle file deletion/dry run
        if contaminated_pdf_ids:
            print(f"\nProcessing files for {len(contaminated_pdf_ids)} contaminated PDFs...")
            find_and_handle_contaminated_files(metadata_jsonl_path, contaminated_pdf_ids, delete_mode)
    else:
        print("\n✅ No contamination detected. Bench URLs and training URLs are disjoint, and no blank URLs found.")

    # Print summary statistics
    print(f"\nSummary:")
    print(f"  Bench URLs: {len(bench_urls)}")
    print(f"  Training URLs (mapped): {len(real_urls)}")
    print(f"  Contaminated URLs: {len(contaminated_urls)}")
    print(f"  Blank URL entries: {len(blank_url_entries)}")
    print(f"  Total contaminated: {total_contaminated}")
    if bench_urls:
        contamination_rate = (len(contaminated_urls) / len(bench_urls)) * 100
        print(f"  Contamination rate: {contamination_rate:.2f}%")

    return total_contaminated


def main():
    parser = argparse.ArgumentParser(description="Check for contamination between benchmark data and training data")
    parser.add_argument("bench_data_dir", help="Path to olmocr-bench/bench_data directory")
    parser.add_argument("metadata_jsonl", help="Path to metadata JSONL file")
    parser.add_argument("sqlite_db", help="Path to SQLite database with pdf_mapping table")
    parser.add_argument("--delete", action="store_true", help="Delete contaminated files (default is dry run)")

    args = parser.parse_args()

    # Validate paths
    if not Path(args.bench_data_dir).is_dir():
        print(f"Error: {args.bench_data_dir} is not a directory")
        return 1

    if not Path(args.metadata_jsonl).is_file():
        print(f"Error: {args.metadata_jsonl} is not a file")
        return 1

    if not Path(args.sqlite_db).is_file():
        print(f"Error: {args.sqlite_db} is not a file")
        return 1

    # Run contamination check
    contaminated_count = check_contamination(args.bench_data_dir, args.metadata_jsonl, args.sqlite_db, delete_mode=args.delete)

    # Return non-zero exit code if contamination found
    return 1 if contaminated_count > 0 else 0


if __name__ == "__main__":
    exit(main())
