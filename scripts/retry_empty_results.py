#!/usr/bin/env python3
"""
Script to check for and optionally retry 0-byte result files in an olmOCR workspace.

Usage:
    python scripts/retry_empty_results.py s3://bucket/path/to/workspace
    python scripts/retry_empty_results.py s3://bucket/path/to/workspace --retry
"""

import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from tqdm import tqdm


def parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse an S3 path into bucket and key."""
    if not s3_path.startswith("s3://"):
        raise ValueError(f"Invalid S3 path: {s3_path}")
    path = s3_path[5:]
    parts = path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


def list_s3_objects(s3_client, prefix: str, desc: str = "Listing S3 objects") -> list[dict]:
    """List all objects under an S3 prefix, returning list of {key, size}."""
    bucket, key_prefix = parse_s3_path(prefix)
    objects = []
    paginator = s3_client.get_paginator("list_objects_v2")

    pbar = tqdm(desc=desc, unit=" objects")
    for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
        page_objects = page.get("Contents", [])
        for obj in page_objects:
            objects.append({"key": obj["Key"], "size": obj["Size"]})
        pbar.update(len(page_objects))
    pbar.close()

    return objects


def delete_s3_object(s3_client, bucket: str, key: str) -> bool:
    """Delete an S3 object. Returns True on success."""
    try:
        s3_client.delete_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        print(f"Failed to delete s3://{bucket}/{key}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Check for and optionally retry 0-byte result files in an olmOCR workspace.")
    parser.add_argument(
        "workspace",
        help="S3 path to the workspace (e.g., s3://bucket/path/to/workspace)",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Delete 0-byte result files and their corresponding done_flags to allow retry",
    )
    args = parser.parse_args()

    workspace = args.workspace.rstrip("/")

    if not workspace.startswith("s3://"):
        print("Error: Only S3 workspaces are supported")
        return 1

    s3_client = boto3.client("s3")
    bucket, _ = parse_s3_path(workspace)

    # List all result files
    results_prefix = f"{workspace}/results/"
    result_objects = list_s3_objects(s3_client, results_prefix, desc="Listing result files")

    total_files = len(result_objects)
    zero_byte_files = [obj for obj in result_objects if obj["size"] == 0]
    zero_byte_count = len(zero_byte_files)

    if total_files == 0:
        print("No files found in results/")
        return 0

    percentage = (zero_byte_count / total_files) * 100

    print(f"\nResults:")
    print(f"  Total files: {total_files:,}")
    print(f"  0-byte files: {zero_byte_count:,}")
    print(f"  Percentage: {percentage:.4f}%")

    if not args.retry:
        if zero_byte_count > 0:
            print(f"\nTo delete these 0-byte files and their done_flags (allowing retry), run with --retry")
        return 0

    if zero_byte_count == 0:
        print("\nNo 0-byte files to delete.")
        return 0

    # Extract hashes from 0-byte result files
    # Format: output_{hash}.jsonl
    hash_pattern = re.compile(r"output_([a-f0-9]+)\.jsonl$")
    hashes_to_retry = []

    for obj in tqdm(zero_byte_files, desc="Extracting hashes"):
        match = hash_pattern.search(obj["key"])
        if match:
            hashes_to_retry.append(match.group(1))

    print(f"\nDeleting {len(hashes_to_retry)} 0-byte result files and their done_flags...")

    # Build list of objects to delete
    objects_to_delete = []
    for h in tqdm(hashes_to_retry, desc="Building deletion list"):
        # Result file
        _, result_key = parse_s3_path(f"{workspace}/results/output_{h}.jsonl")
        objects_to_delete.append(result_key)
        # Done flag
        _, done_flag_key = parse_s3_path(f"{workspace}/done_flags/done_{h}.flag")
        objects_to_delete.append(done_flag_key)

    # Delete in parallel
    deleted_count = 0
    failed_count = 0

    def delete_object(key):
        return delete_s3_object(s3_client, bucket, key)

    with ThreadPoolExecutor(max_workers=32) as executor:
        futures = {executor.submit(delete_object, key): key for key in objects_to_delete}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Deleting objects"):
            if future.result():
                deleted_count += 1
            else:
                failed_count += 1

    print(f"\nDeletion complete:")
    print(f"  Successfully deleted: {deleted_count:,} objects")
    print(f"  Failed to delete: {failed_count:,} objects")
    print(f"  Work items ready for retry: {len(hashes_to_retry):,}")

    return 0


if __name__ == "__main__":
    exit(main())
