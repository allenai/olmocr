#!/usr/bin/env python3
# Script to map S3 URLs to real URIs using SQLite database
# Input: text file with S3 paths (one per line)
# Output: text file with mapped URIs (skipping blank results)

import argparse
import re
import sqlite3
from functools import partial
from multiprocessing import Pool, cpu_count
from pathlib import Path

from tqdm import tqdm


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


def process_batch(batch, db_path):
    """Process a batch of S3 URLs and return results."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    results = []
    for s3_url in batch:
        s3_url = s3_url.strip()
        if not s3_url:
            continue

        pdf_hash = s3_url_to_hash(s3_url)

        if pdf_hash:
            cursor.execute("SELECT uri FROM pdf_mapping WHERE pdf_hash = ?", (pdf_hash,))
            result = cursor.fetchone()

            if result:
                uri = result[0]
                if uri and uri.strip():
                    results.append((s3_url, "mapped"))
                else:
                    results.append((None, "blank"))
            else:
                results.append((None, "failed"))
        else:
            results.append((None, "failed"))

    conn.close()
    return results


def file_line_count(filename):
    """Count lines in file efficiently."""
    count = 0
    with open(filename, "rb") as f:
        while True:
            buffer = f.read(1024 * 1024)  # Read 1MB at a time
            if not buffer:
                break
            count += buffer.count(b"\n")
    return count


def read_file_in_chunks(filename, chunk_size=1000):
    """Generator that yields chunks of lines from file."""
    chunk = []
    with open(filename, "r") as f:
        for line in f:
            chunk.append(line)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:  # Yield remaining lines
            yield chunk


def main():
    parser = argparse.ArgumentParser(description="Map S3 URLs to real URIs using SQLite database")
    parser.add_argument("input_file", help="Input text file containing S3 URLs (one per line)")
    parser.add_argument("sqlite_db", help="Path to SQLite database with pdf_mapping table")
    parser.add_argument("output_file", help="Output text file for mapped URIs")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker processes (default: number of CPU cores)")
    parser.add_argument("--batch-size", type=int, default=1000, help="Number of lines per batch (default: 1000)")

    args = parser.parse_args()

    # Validate input files
    if not Path(args.input_file).is_file():
        print(f"Error: {args.input_file} is not a file")
        return 1

    if not Path(args.sqlite_db).is_file():
        print(f"Error: {args.sqlite_db} is not a file")
        return 1

    # Count total lines for progress bar
    print("Counting lines in input file...")
    total_lines = file_line_count(args.input_file)
    print(f"Total lines to process: {total_lines:,}")

    # Determine number of workers
    num_workers = args.workers or cpu_count()
    print(f"Using {num_workers} worker processes with batch size {args.batch_size}")

    # Process batches in parallel
    mapped_count = 0
    blank_count = 0
    failed_count = 0

    with open(args.output_file, "w") as outfile:
        with Pool(num_workers) as pool:
            process_func = partial(process_batch, db_path=args.sqlite_db)

            # Create chunk generator
            chunk_generator = read_file_in_chunks(args.input_file, args.batch_size)

            # Use imap for streaming processing
            with tqdm(total=total_lines, desc="Processing S3 URLs", unit=" lines") as pbar:
                for batch_results in pool.imap_unordered(process_func, chunk_generator):
                    for s3_url, status in batch_results:
                        if status == "mapped":
                            outfile.write(s3_url + "\n")
                            mapped_count += 1
                        elif status == "blank":
                            blank_count += 1
                        elif status == "failed":
                            failed_count += 1

                        # Update progress bar with current stats
                        pbar.update(1)
                        pbar.set_postfix({"mapped": mapped_count, "blank": blank_count, "failed": failed_count})

    # Print summary
    print(f"\nProcessing complete!")
    print(f"  Total lines processed: {total_lines:,}")
    print(f"  Successfully mapped: {mapped_count:,}")
    print(f"  Blank URIs skipped: {blank_count:,}")
    print(f"  Failed to map: {failed_count:,}")
    print(f"  Output written to: {args.output_file}")

    return 0


if __name__ == "__main__":
    exit(main())
