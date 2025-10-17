# This code takes in a path to an olmocr-mix processed data folder
# and removes any documents that come from a premade deny list
#
# Example deny list, txt file:
# s3://ai2-s2-pdfs/4444/111111111111111111111111111111111111.pdf
# s3://ai2-s2-pdfs/5555/111111111111111111111111111111111112.pdf
# s3://ai2-s2-pdfs/6666/111111111111111111111111111111111113.pdf
#
# Should match paths like
#
# processed_00_documents_eval_s2pdf/4444/111111111111111111111111111111111111-1.md
# processed_00_documents_eval_s2pdf/4444/111111111111111111111111111111111111-1.pdf
# Where the path to processed_00_documents_eval_s2pdf is provided as an argument

# What it should do is move the bad files to a rejected folder, match both .md and .pdf

import argparse
import re
import shutil
from pathlib import Path
from typing import Set, Tuple

from tqdm import tqdm


def parse_deny_list(deny_list_file: Path) -> Set[Tuple[str, str]]:
    """Parse deny list file and extract subdirectory and base filename patterns."""
    patterns = set()

    with open(deny_list_file, "r") as f:
        for line in tqdm(f):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Extract the subdirectory (e.g., "4444") and base filename from S3 path
            # Pattern: s3://bucket-name/subdirectory/filename.pdf
            match = re.match(r"s3://[^/]+/(\S+)/([^/]+)\.pdf$", line)
            if match:
                subdir = match.group(1)
                base_filename = match.group(2)
                patterns.add((subdir, base_filename))
            else:
                print(f"Warning: Could not parse deny list entry: {line}")

    return patterns


def find_matching_files(processed_dir: Path, deny_patterns: Set[Tuple[str, str]]) -> list[Path]:
    """Find all files that match the deny patterns."""
    matching_files = []

    # First, glob all .pdf and .md files in the processed directory
    all_pdf_files = list(processed_dir.glob("**/*.pdf"))
    all_md_files = list(processed_dir.glob("**/*.md"))
    all_files = all_pdf_files + all_md_files

    print(f"Found {len(all_files)} total files ({len(all_pdf_files)} PDFs, {len(all_md_files)} MDs)")

    # Now check each file against the deny patterns
    for file_path in tqdm(all_files, desc="Checking files against deny list"):
        # Extract the parent directory name and base filename
        # Expected pattern: processed_dir/subdir/filename-pagenum.ext
        try:
            relative_path = file_path.relative_to(processed_dir)
            parts = relative_path.parts

            if len(parts) >= 2:
                subdir = parts[0]
                filename = parts[-1]

                # Extract base filename without page number and extension
                # Pattern: base_filename-pagenum.ext
                match = re.match(r"^(.+?)-\d+\.(pdf|md)$", filename)
                if match:
                    base_filename = match.group(1)

                    # Check if this (subdir, base_filename) pair is in our deny set
                    if (subdir, base_filename) in deny_patterns:
                        matching_files.append(file_path)
        except Exception as e:
            print(f"Warning: Could not process file {file_path}: {e}")

    return matching_files


def move_files_to_rejected(files_to_move: list[Path], processed_dir: Path, rejected_dir: Path):
    """Move files to the rejected folder, maintaining directory structure."""
    moved_count = 0

    for file_path in files_to_move:
        # Calculate relative path from processed_dir
        relative_path = file_path.relative_to(processed_dir)

        # Create target path in rejected folder
        target_path = rejected_dir / relative_path

        # Create target directory if it doesn't exist
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Move the file
            shutil.move(str(file_path), str(target_path))
            print(f"Moved: {file_path} -> {target_path}")
            moved_count += 1
        except Exception as e:
            print(f"Error moving {file_path}: {e}")

    return moved_count


def main():
    parser = argparse.ArgumentParser(description="Remove documents from olmocr-mix processed data based on a deny list")
    parser.add_argument("processed_dir", type=Path, help="Path to the processed documents directory (e.g., processed_00_documents_eval_s2pdf)")
    parser.add_argument("deny_list", type=Path, help="Path to the deny list text file containing S3 paths to reject")
    parser.add_argument("--rejected-dir", type=Path, default=None, help="Path to the rejected files directory (default: processed_dir_rejected)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be moved without actually moving files")

    args = parser.parse_args()

    # Validate inputs
    if not args.processed_dir.exists():
        print(f"Error: Processed directory does not exist: {args.processed_dir}")
        return 1

    if not args.deny_list.exists():
        print(f"Error: Deny list file does not exist: {args.deny_list}")
        return 1

    # Set rejected directory
    if args.rejected_dir is None:
        args.rejected_dir = args.processed_dir.parent / f"{args.processed_dir.name}_rejected"

    print(f"Processing directory: {args.processed_dir}")
    print(f"Deny list file: {args.deny_list}")
    print(f"Rejected directory: {args.rejected_dir}")

    if args.dry_run:
        print("\n** DRY RUN MODE - No files will be moved **\n")

    # Parse deny list
    deny_patterns = parse_deny_list(args.deny_list)
    print(f"\nFound {len(deny_patterns)} unique deny patterns")

    # Find matching files
    matching_files = find_matching_files(args.processed_dir, deny_patterns)
    print(f"Found {len(matching_files)} files to remove")

    if not matching_files:
        print("No files to remove.")
        return 0

    # Show summary
    print("\nFiles to be moved:")
    for f in matching_files[:10]:  # Show first 10
        print(f"  - {f}")
    if len(matching_files) > 10:
        print(f"  ... and {len(matching_files) - 10} more files")

    # Move files (or simulate in dry-run mode)
    if not args.dry_run:
        # Create rejected directory
        args.rejected_dir.mkdir(parents=True, exist_ok=True)

        # Move the files
        moved_count = move_files_to_rejected(matching_files, args.processed_dir, args.rejected_dir)
        print(f"\nSuccessfully moved {moved_count} files to {args.rejected_dir}")
    else:
        print(f"\nDry run complete. Would move {len(matching_files)} files.")

    return 0


if __name__ == "__main__":
    exit(main())
