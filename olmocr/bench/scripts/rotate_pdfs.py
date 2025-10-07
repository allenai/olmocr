#!/usr/bin/env python3
import json
import os
import random
import shutil
from collections import defaultdict
from pathlib import Path


def main():
    # Set paths
    bench_data_dir = Path("./olmOCR-bench/bench_data")
    pdfs_dir = Path("./olmOCR-bench/bench_data/pdfs")
    rotated_pdfs_dir = pdfs_dir / "rotated"
    output_jsonl = Path("rotated.jsonl")

    # Create rotated directory if it doesn't exist
    rotated_pdfs_dir.mkdir(parents=True, exist_ok=True)

    # Load all JSONL files and group by PDF
    pdf_groups = defaultdict(list)

    print("Loading JSONL files...")
    for jsonl_file in bench_data_dir.glob("*.jsonl"):
        print(f"  Reading {jsonl_file}")
        with open(jsonl_file, "r") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    if "pdf" in data:
                        pdf_groups[data["pdf"]].append(data)
                except json.JSONDecodeError:
                    continue

    print(f"Found {len(pdf_groups)} unique PDF groups")

    # Randomly select 10% of PDF groups
    num_to_select = max(1, int(len(pdf_groups) * 0.1))
    selected_pdfs = random.sample(list(pdf_groups.keys()), num_to_select)

    print(f"Selected {num_to_select} PDF groups (10% of total)")

    # Write selected entries to rotated.jsonl
    print(f"Writing selected entries to {output_jsonl}")
    with open(output_jsonl, "w") as f:
        for pdf_name in selected_pdfs:
            for entry in pdf_groups[pdf_name]:
                f.write(json.dumps(entry) + "\n")

    # Copy corresponding PDF files
    print("Copying PDF files to rotated directory...")
    copied_count = 0
    missing_count = 0

    for pdf_name in selected_pdfs:
        # Try to find the PDF in subdirectories
        pdf_found = False
        print(pdf_name)
        source_path = pdfs_dir / pdf_name
        if source_path.exists():
            dest_path = rotated_pdfs_dir / os.path.basename(pdf_name)
            print(f"  Copying {source_path} -> {dest_path}")
            shutil.copy2(source_path, dest_path)
            copied_count += 1
            pdf_found = True

        if not pdf_found:
            print(f"  Warning: PDF not found: {pdf_name}")
            missing_count += 1

    print(f"\nSummary:")
    print(f"  Total PDF groups: {len(pdf_groups)}")
    print(f"  Selected groups: {num_to_select}")
    print(f"  PDFs copied: {copied_count}")
    if missing_count > 0:
        print(f"  PDFs not found: {missing_count}")
    print(f"  Output JSONL: {output_jsonl}")
    print(f"  Rotated PDFs directory: {rotated_pdfs_dir}")


if __name__ == "__main__":
    main()
