#!/usr/bin/env python3
"""
Merge attribute data from multiple attribute folders into document JSONL files.

Example usage:
    python merge_attributes.py \
        --input-folder /path/to/dataset/deduped_eng \
        --output-folder /path/to/output \
        --attribute-folders model_pii_tagging model_rich_pii_tagging \
        --workers 8
"""

import argparse
import json
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple

import zstandard as zstd
from tqdm import tqdm


def read_jsonl_zst(filepath: Path) -> List[dict]:
    """Read a .jsonl.zst file and return list of JSON objects."""
    records = []
    dctx = zstd.ZstdDecompressor()
    with open(filepath, 'rb') as f:
        with dctx.stream_reader(f) as reader:
            text = reader.read().decode('utf-8')
            for line in text.strip().split('\n'):
                if line:
                    records.append(json.loads(line))
    return records


def write_jsonl_zst(filepath: Path, records: List[dict], compression_level: int = 3):
    """Write list of JSON objects to a .jsonl.zst file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    cctx = zstd.ZstdCompressor(level=compression_level)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    content = '\n'.join(lines).encode('utf-8')
    with open(filepath, 'wb') as f:
        f.write(cctx.compress(content))


def process_shard(
    doc_path: Path,
    input_folder: Path,
    output_folder: Path,
    attribute_folders: List[str]
) -> Tuple[str, int, Dict[str, int], Dict[str, int]]:
    """
    Process a single document shard, merging attributes from all attribute folders.

    Returns:
        Tuple of (shard_name, doc_count, missing_attr_files, id_mismatches)
    """
    shard_name = doc_path.name
    missing_attr_files: Dict[str, int] = {}  # attr_folder -> 1 if missing
    id_mismatches: Dict[str, int] = {}  # attr_folder -> count of mismatched IDs

    # Read documents and index by ID
    documents = read_jsonl_zst(doc_path)
    doc_by_id: Dict[str, dict] = {doc['id']: doc for doc in documents}
    doc_ids = set(doc_by_id.keys())

    # Process each attribute folder in order
    for attr_folder in attribute_folders:
        attr_path = input_folder / 'attributes' / attr_folder / shard_name

        if not attr_path.exists():
            missing_attr_files[attr_folder] = 1
            continue

        # Read attribute file
        attr_records = read_jsonl_zst(attr_path)

        # Merge attributes into documents
        mismatch_count = 0
        for attr_record in attr_records:
            attr_id = attr_record.get('id')
            if attr_id not in doc_ids:
                mismatch_count += 1
                continue

            # Merge attributes at root level
            if 'attributes' in attr_record:
                for key, value in attr_record['attributes'].items():
                    doc_by_id[attr_id][key] = value

        if mismatch_count > 0:
            id_mismatches[attr_folder] = mismatch_count

    # Write output (preserve original order)
    merged_docs = [doc_by_id[doc['id']] for doc in documents]
    output_path = output_folder / 'documents' / shard_name
    write_jsonl_zst(output_path, merged_docs)

    return shard_name, len(documents), missing_attr_files, id_mismatches


def main():
    parser = argparse.ArgumentParser(
        description='Merge attribute data into document JSONL files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--input-folder',
        type=Path,
        required=True,
        help='Path to folder containing documents/ and attributes/ subfolders'
    )
    parser.add_argument(
        '--output-folder',
        type=Path,
        required=True,
        help='Path to output folder (will create documents/ subfolder)'
    )
    parser.add_argument(
        '--attribute-folders',
        nargs='+',
        required=True,
        help='List of attribute folder names to merge (order matters - later overwrites earlier)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=8,
        help='Number of parallel workers (default: 8)'
    )

    args = parser.parse_args()

    # Validate input folder
    docs_folder = args.input_folder / 'documents'
    if not docs_folder.exists():
        print(f"Error: documents folder not found at {docs_folder}")
        return 1

    # Find all document shards
    doc_files = sorted(docs_folder.glob('*.jsonl.zst'))
    if not doc_files:
        print(f"Error: no .jsonl.zst files found in {docs_folder}")
        return 1

    print(f"Found {len(doc_files)} document shards")
    print(f"Attribute folders to merge: {args.attribute_folders}")
    print(f"Output folder: {args.output_folder}")
    print(f"Workers: {args.workers}")
    print()

    # Aggregate statistics
    total_docs = 0
    total_missing_attr_files: Dict[str, int] = defaultdict(int)
    total_id_mismatches: Dict[str, int] = defaultdict(int)

    # Process shards in parallel
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_shard,
                doc_path,
                args.input_folder,
                args.output_folder,
                args.attribute_folders
            ): doc_path
            for doc_path in doc_files
        }

        with tqdm(total=len(doc_files), desc="Processing shards") as pbar:
            for future in as_completed(futures):
                doc_path = futures[future]
                try:
                    shard_name, doc_count, missing_attrs, mismatches = future.result()
                    total_docs += doc_count

                    for attr_folder, count in missing_attrs.items():
                        total_missing_attr_files[attr_folder] += count

                    for attr_folder, count in mismatches.items():
                        total_id_mismatches[attr_folder] += count

                except Exception as e:
                    print(f"\nError processing {doc_path}: {e}")

                pbar.update(1)

    # Print summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total shards processed: {len(doc_files)}")
    print(f"Total documents processed: {total_docs:,}")
    print()

    if total_missing_attr_files:
        print("Missing attribute files by folder:")
        for attr_folder in args.attribute_folders:
            count = total_missing_attr_files.get(attr_folder, 0)
            print(f"  {attr_folder}: {count} shards missing")
    else:
        print("No missing attribute files.")

    print()

    if total_id_mismatches:
        print("ID mismatches (attribute IDs not found in documents):")
        for attr_folder in args.attribute_folders:
            count = total_id_mismatches.get(attr_folder, 0)
            if count > 0:
                print(f"  {attr_folder}: {count:,} mismatched IDs")
    else:
        print("No ID mismatches.")

    print()
    print(f"Output written to: {args.output_folder / 'documents'}")

    return 0


if __name__ == '__main__':
    exit(main())
