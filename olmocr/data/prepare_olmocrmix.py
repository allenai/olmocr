import argparse
import json
import tarfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from os import PathLike
from pathlib import Path
from typing import Optional

import pandas as pd
from huggingface_hub import snapshot_download
from tqdm import tqdm


def extract_tarball(tarball_path: Path, extract_dir: Path) -> int:
    """Extract a single tarball and return the number of files extracted."""
    try:
        with tarfile.open(tarball_path, "r") as tar:
            tar.extractall(extract_dir)
            return len(tar.getmembers())
    except Exception as e:
        print(f"Error extracting {tarball_path}: {e}")
        return 0


def prepare_olmocr_mix(dataset_path: str, subset: str, split: str, destination: str | PathLike, max_examples: Optional[int] = None) -> str:
    """
    Prepare OLMoCR mix dataset by downloading from HuggingFace and organizing into a folder structure.

    Args:
        dataset_path: HuggingFace dataset path
        subset: Dataset subset name
        split: Dataset split (train/validation/test)
        destination: Destination directory path
        max_examples: Maximum number of examples to process (None for all)
    """
    # Step 1: Download dataset using hugging face hub snapshot_download to destination/hugging_face folder
    dest_path = Path(destination)
    hugging_face_dir = dest_path / "hugging_face"
    hugging_face_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading dataset {dataset_path} to {hugging_face_dir}...")

    # Download the entire repository including PDFs and parquet files
    local_dir = snapshot_download(
        repo_id=dataset_path,
        repo_type="dataset",
        local_dir=hugging_face_dir,
    )

    print(f"Downloaded to: {local_dir}")

    # Step 2: Create destination folder structure for processed markdown files
    processed_dir = dest_path / f"processed_{subset}_{split}"
    processed_dir.mkdir(exist_ok=True)

    # Manual map to parquet files for now
    assert dataset_path == "allenai/olmOCR-mix-0225", "Only supporting the olmocr-mix for now, later will support other training sets"
    if subset == "00_documents" and split == "train_s2pdf":
        parquet_files = [dest_path / "hugging_face" / "train-s2pdf.parquet"]
    elif subset == "00_documents" and split == "eval_s2pdf":
        parquet_files = [dest_path / "hugging_face" / "eval-s2pdf.parquet"]
    elif subset == "01_books" and split == "train_iabooks":
        parquet_files = [dest_path / "hugging_face" / "train-iabooks.parquet"]
    elif subset == "01_books" and split == "eval_iabooks":
        parquet_files = [dest_path / "hugging_face" / "eval-iabooks.parquet"]
    else:
        raise NotImplementedError()

    # Step 3: Extract PDF tarballs
    pdf_tarballs_dir = dest_path / "hugging_face" / "pdf_tarballs"
    if pdf_tarballs_dir.exists():
        extracted_dir = pdf_tarballs_dir / "extracted"
        extracted_dir.mkdir(exist_ok=True)

        # Check if PDFs are already extracted
        existing_pdfs = list(extracted_dir.glob("*.pdf"))
        if existing_pdfs:
            print(f"Found {len(existing_pdfs)} already extracted PDFs in {extracted_dir}, skipping extraction step")
        else:
            # Find all tarball files
            tarball_files = list(pdf_tarballs_dir.glob("*.tar*")) + list(pdf_tarballs_dir.glob("*.tgz"))

            if tarball_files:
                print(f"\nFound {len(tarball_files)} PDF tarballs to extract...")

                # Use ProcessPoolExecutor for parallel extraction
                with ProcessPoolExecutor() as executor:
                    # Submit all tasks
                    future_to_tarball = {}
                    for tarball in tarball_files:
                        future = executor.submit(extract_tarball, tarball, extracted_dir)
                        future_to_tarball[future] = tarball

                    # Process results as they complete with progress bar
                    total_files_extracted = 0
                    with tqdm(total=len(tarball_files), desc="Extracting tarballs") as pbar:
                        for future in as_completed(future_to_tarball):
                            tarball = future_to_tarball[future]
                            try:
                                files_extracted = future.result()
                                total_files_extracted += files_extracted
                                pbar.set_postfix({"files": total_files_extracted})
                            except Exception as e:
                                print(f"\nError with {tarball.name}: {e}")
                            pbar.update(1)

                print(f"Extracted {total_files_extracted} files from tarballs to {extracted_dir}")
    else:
        print(f"No PDF tarballs directory found at {pdf_tarballs_dir}")

    # Step 4: Process parquet files
    total_processed = 0
    total_errors = 0

    for parquet_file in parquet_files:
        print(f"Processing {parquet_file.name}...")
        df = pd.read_parquet(parquet_file)

        # Process each row
        for idx, row in df.iterrows():
            if max_examples and total_processed >= max_examples:
                break

            try:

                # Extract fields from the row
                # The rows in the parquet will look like url, page_number, response (json format), and id
                response = row.get("response", "")
                doc_id = str(idx)

                assert len(doc_id) > 4

                # Parse response if it's a JSON string
                response_data = json.loads(response)
                response = response_data

                # Create folder structure using first 4 digits of id
                # Make a folder structure, to prevent a huge amount of files in one folder, using the first 4 digits of the id, ex. id[:4]/id[4:].md
                folder_name = doc_id[:4]
                file_name = f"{doc_id[4:]}.md"

                # Create directory
                output_dir = processed_dir / folder_name
                output_dir.mkdir(exist_ok=True)

                # Write markdown file with front matter and natural text
                output_file = output_dir / file_name
                with open(output_file, "w", encoding="utf-8") as f:
                    # Extract natural_text and other fields for front matter
                    natural_text = response.get("natural_text", "")
                    # Create front matter from other fields
                    front_matter = {k: v for k, v in response.items() if k != "natural_text"}

                    # Write front matter
                    f.write("---\n")
                    for k, v in front_matter.items():
                        f.write(f"{k}: {v}\n")

                    if natural_text is not None and len(natural_text.strip()) > 0:
                        f.write("---\n")

                        # Write natural text
                        f.write(natural_text)
                    else:
                        f.write("---")

                # Look for matching PDF in extracted directory and create symlinks
                extracted_pdfs_dir = dest_path / "hugging_face" / "pdf_tarballs" / "extracted"

                # Find PDFs that match the ID pattern
                matched_pdf_path = extracted_pdfs_dir / f"{doc_id}.pdf"
                assert matched_pdf_path.exists(), "Matching PDF not found"

                symlink_path = output_dir / f"{doc_id[4:]}.pdf"

                # Create relative symlink to the PDF
                if not symlink_path.exists():
                    symlink_path.symlink_to(matched_pdf_path)

                total_processed += 1
                if total_processed % 1000 == 0:
                    print(f"Processed {total_processed} examples...")
            except Exception as ex:
                print(f"Error processing line: {ex}")
                total_errors += 1

        if max_examples and total_processed >= max_examples:
            break

    print(f"Completed! Processed {total_processed} examples to {processed_dir}")
    print(f"Total errors: {total_errors}")

    return str(processed_dir)


def main():
    parser = argparse.ArgumentParser(description="Prepare OLMoCR mix dataset")
    parser.add_argument("--dataset-path", type=str, default="allenai/olmOCR-mix-0225", help="HuggingFace dataset path (e.g., 'allenai/olmocr-mix')")
    parser.add_argument("--subset", type=str, default="00_documents", required=True, help="Dataset subset name")
    parser.add_argument("--split", type=str, default="eval_s2pdf", required=True, help="Dataset split ex eval_s2pdf")
    parser.add_argument("--destination", type=str, required=True, help="Destination directory path")
    parser.add_argument("--max-examples", type=int, default=None, help="Maximum number of examples to process (default: all)")

    args = parser.parse_args()

    prepare_olmocr_mix(dataset_path=args.dataset_path, subset=args.subset, split=args.split, destination=args.destination, max_examples=args.max_examples)


if __name__ == "__main__":
    main()
