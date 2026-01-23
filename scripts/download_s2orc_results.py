#!/usr/bin/env python3
"""
Script to download and aggregate results from s2orcforolmo workspaces.

Downloads all result files from workspaces matching s2orcforolmo*_workspace,
adds license information extracted from the Source-File path, and saves
to a local folder preserving original filenames.

Usage:
    python scripts/download_s2orc_results.py /path/to/output_folder
    python scripts/download_s2orc_results.py /path/to/output_folder --workers 64
"""

import argparse
import gzip
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed

import boto3
from tqdm import tqdm

BUCKET = "ai2-oe-data"
KEY_PREFIX = "jakep/dolma4pdfs_workspaces/"


def parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse an S3 path into bucket and key."""
    if not s3_path.startswith("s3://"):
        raise ValueError(f"Invalid S3 path: {s3_path}")
    path = s3_path[5:]
    parts = path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


def extract_license_from_source_file(source_file: str) -> str | None:
    """
    Extract license from the Source-File path.

    Examples:
        s3://ai2-oe-data/jakep/dolma4pdfs_frontier/s2orcforolmo-gpl-2/file.pdf -> "gpl-2"
        s3://ai2-oe-data/jakep/dolma4pdfs_frontier/s2orcforolmo/file.pdf -> None
    """
    if not source_file:
        return None

    # Look for s2orcforolmo or s2orcforolmo-{license} in the path
    match = re.search(r'/s2orcforolmo(?:-([^/]+))?/', source_file)
    if match:
        return match.group(1)  # Returns None if no capture group (just /s2orcforolmo/)
    return None


def list_workspaces(s3_client) -> list[str]:
    """List all s2orcforolmo*_workspace prefixes."""
    paginator = s3_client.get_paginator("list_objects_v2")
    workspaces = set()

    # List with delimiter to get "directories"
    for page in paginator.paginate(Bucket=BUCKET, Prefix=KEY_PREFIX, Delimiter="/"):
        for prefix_info in page.get("CommonPrefixes", []):
            prefix = prefix_info["Prefix"]
            # Extract the workspace name (last part before trailing /)
            workspace_name = prefix.rstrip("/").split("/")[-1]
            if workspace_name.startswith("s2orcforolmo") and workspace_name.endswith("_workspace"):
                workspaces.add(f"s3://{BUCKET}/{prefix.rstrip('/')}")

    return sorted(workspaces)


def list_result_files(s3_client, workspace: str) -> list[str]:
    """List all result files in a workspace."""
    bucket, key_prefix = parse_s3_path(f"{workspace}/results/")
    paginator = s3_client.get_paginator("list_objects_v2")
    files = []

    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []):
            files.append(f"s3://{bucket}/{obj['Key']}")

    return files


def process_single_file(s3_path: str, output_dir: str) -> tuple[str, int]:
    """
    Download and process a single result file, saving to output directory.
    Returns tuple of (output_filename, line_count).
    """
    s3_client = boto3.client("s3")
    bucket, key = parse_s3_path(s3_path)

    # Get original filename
    original_filename = os.path.basename(key)
    # Remove .gz extension if present for output
    if original_filename.endswith(".gz"):
        original_filename = original_filename[:-3]

    output_path = os.path.join(output_dir, original_filename)

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()

        # Handle gzipped files
        if s3_path.endswith(".gz"):
            content = gzip.decompress(content)

        line_count = 0
        with open(output_path, "w") as out_f:
            for line in content.decode("utf-8").strip().split("\n"):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # Extract license from metadata.Source-File
                    source_file = data.get("metadata", {}).get("Source-File", "")
                    data["license"] = extract_license_from_source_file(source_file)
                    out_f.write(json.dumps(data) + "\n")
                    line_count += 1
                except json.JSONDecodeError:
                    continue

        return (original_filename, line_count)
    except Exception as e:
        print(f"Error processing {s3_path}: {e}")
        return (original_filename, 0)


def main():
    parser = argparse.ArgumentParser(
        description="Download and aggregate s2orcforolmo workspace results with license extraction."
    )
    parser.add_argument(
        "output_dir",
        help="Output directory path (will contain JSONL files with original names)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=32,
        help="Number of parallel workers (default: 32)",
    )
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    s3_client = boto3.client("s3")

    # Step 1: List all matching workspaces
    print("Finding s2orcforolmo workspaces...")
    workspaces = list_workspaces(s3_client)
    print(f"Found {len(workspaces)} workspaces:")
    for ws in workspaces:
        print(f"  - {ws}")

    if not workspaces:
        print("No matching workspaces found.")
        return 1

    # Step 2: List all result files from all workspaces
    print("\nListing result files from all workspaces...")
    all_files = []
    for workspace in tqdm(workspaces, desc="Scanning workspaces"):
        files = list_result_files(s3_client, workspace)
        all_files.extend(files)

    print(f"Found {len(all_files):,} result files across all workspaces")

    if not all_files:
        print("No result files found.")
        return 1

    # Step 3: Process files in parallel and save to output directory
    print(f"\nProcessing files with {args.workers} workers...")
    total_lines = 0
    total_files = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_single_file, f, args.output_dir): f
            for f in all_files
        }

        with tqdm(total=len(futures), desc="Downloading & processing") as pbar:
            for future in as_completed(futures):
                try:
                    filename, line_count = future.result()
                    total_lines += line_count
                    total_files += 1
                except Exception as e:
                    print(f"Error: {e}")
                pbar.update(1)
                pbar.set_postfix({"files": f"{total_files:,}", "lines": f"{total_lines:,}"})

    print(f"\nComplete!")
    print(f"  Total files processed: {total_files:,}")
    print(f"  Total lines written: {total_lines:,}")
    print(f"  Output directory: {args.output_dir}")

    return 0


if __name__ == "__main__":
    exit(main())
