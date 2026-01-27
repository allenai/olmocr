#!/usr/bin/env python3
"""
Annotate JSONL documents with URLs from a SQLite database mapping pdf_hash -> uri.

The SQLite database must have schema:
    CREATE TABLE pdf_uri_mapping (
        pdf_hash TEXT PRIMARY KEY,
        uri TEXT
    );

The pdf_hash is extracted from each document's metadata.Source-File field,
taking the portion after ".tar.gz::" (e.g. "4660a54e62284b5c8baf523edd9b27c53969008f").

Example usage:
    python scripts/tag_uri.py \
        --input-dir /path/to/jsonl_files \
        --output-dir /path/to/output \
        --db /path/to/pdf_uri_mapping.db \
        --workers 8
"""

import argparse
import json
import re
import sqlite3
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple

import zstandard as zstd
from tqdm import tqdm

# Shared across workers after fork
_db_path: str = ""


def _extract_hash(source_file: str) -> str:
    """Extract the pdf hash from a Source-File string.

    Looks for the pattern after '.tar.gz::' and strips the file extension.
    E.g. '.tar.gz::4660a54e62284b5c8baf523edd9b27c53969008f.pdf' -> '4660a54e62284b5c8baf523edd9b27c53969008f'
    """
    match = re.search(r'\.tar\.gz::(.+)$', source_file)
    if not match:
        return ""
    name = match.group(1)
    # Strip file extension if present
    dot_idx = name.rfind('.')
    if dot_idx > 0:
        name = name[:dot_idx]
    return name


def _query_uris_batch(db_path: str, hashes: List[str]) -> Dict[str, str]:
    """Query the SQLite database for a batch of pdf hashes, returning hash->uri mapping."""
    if not hashes:
        return {}

    result: Dict[str, str] = {}
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # Query in batches of 500 to stay within SQLite variable limits
        batch_size = 500
        for i in range(0, len(hashes), batch_size):
            batch = hashes[i:i + batch_size]
            placeholders = ','.join('?' * len(batch))
            cursor.execute(
                f"SELECT pdf_hash, uri FROM pdf_uri_mapping WHERE pdf_hash IN ({placeholders})",
                batch,
            )
            for row in cursor.fetchall():
                result[row[0]] = row[1]
    finally:
        conn.close()

    return result


def process_file(args: Tuple[Path, Path, str]) -> Tuple[str, int, int, int]:
    """Process a single .jsonl.zst file.

    Returns (filename, total_lines, matched_lines, unmatched_lines).
    """
    input_path, output_path, db_path = args

    # 1. Read all lines and collect hashes
    dctx = zstd.ZstdDecompressor()
    lines: List[dict] = []
    hashes: List[str] = []

    with open(input_path, 'rb') as f:
        with dctx.stream_reader(f) as reader:
            text = reader.read().decode('utf-8')
            for raw_line in text.strip().split('\n'):
                if not raw_line:
                    continue
                record = json.loads(raw_line)
                lines.append(record)

                source_file = record.get("metadata", {}).get("Source-File", "")
                h = _extract_hash(source_file)
                hashes.append(h)

    # 2. Batch query all unique hashes from SQLite
    unique_hashes = list(set(h for h in hashes if h))
    uri_map = _query_uris_batch(db_path, unique_hashes)

    # 3. Annotate each line
    matched = 0
    unmatched = 0
    for record, h in zip(lines, hashes):
        if h and h in uri_map:
            record["metadata"]["url"] = uri_map[h]
            matched += 1
        else:
            unmatched += 1

    # 4. Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cctx = zstd.ZstdCompressor(level=3)
    content = '\n'.join(json.dumps(r, ensure_ascii=False) for r in lines).encode('utf-8')
    with open(output_path, 'wb') as f:
        f.write(cctx.compress(content))

    return input_path.name, len(lines), matched, unmatched


def main():
    parser = argparse.ArgumentParser(
        description='Annotate JSONL documents with URLs from a SQLite pdf_hash->uri database.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--input-dir', type=Path, required=True, help='Directory containing .jsonl.zst files')
    parser.add_argument('--output-dir', type=Path, required=True, help='Directory to write annotated .jsonl.zst files')
    parser.add_argument('--db', type=Path, required=True, help='Path to SQLite database with pdf_uri_mapping table')
    parser.add_argument('--workers', type=int, default=8, help='Number of parallel workers (default: 8)')

    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: input directory not found: {args.input_dir}")
        return 1

    if not args.db.is_file():
        print(f"Error: database file not found: {args.db}")
        return 1

    input_files = sorted(args.input_dir.glob('*.jsonl.zst'))
    if not input_files:
        print(f"Error: no .jsonl.zst files found in {args.input_dir}")
        return 1

    db_path = str(args.db.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(input_files)} files to process")
    print(f"Database: {args.db}")
    print(f"Output: {args.output_dir}")
    print(f"Workers: {args.workers}")
    print()

    work_items = [
        (f, args.output_dir / f.name, db_path)
        for f in input_files
    ]

    total_lines = 0
    total_matched = 0
    total_unmatched = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_file, item): item[0] for item in work_items}

        with tqdm(total=len(input_files), desc="Processing files") as pbar:
            for future in as_completed(futures):
                filepath = futures[future]
                try:
                    name, n_lines, matched, unmatched = future.result()
                    total_lines += n_lines
                    total_matched += matched
                    total_unmatched += unmatched
                except Exception as e:
                    print(f"\nError processing {filepath}: {e}")
                pbar.update(1)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files processed: {len(input_files)}")
    print(f"Total documents: {total_lines:,}")
    print(f"URLs matched:    {total_matched:,}")
    print(f"URLs missing:    {total_unmatched:,}")
    if total_lines > 0:
        print(f"Match rate:      {total_matched / total_lines * 100:.1f}%")
    print(f"Output written to: {args.output_dir}")

    return 0


if __name__ == '__main__':
    exit(main())
