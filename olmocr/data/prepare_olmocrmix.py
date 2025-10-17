import argparse
import json
import shutil
import tarfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from os import PathLike
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from huggingface_hub import snapshot_download
from tqdm import tqdm


def extract_tarball(tarball_path: Path, extract_dir: Path) -> int:
    """Extract a single tarball and return the number of files extracted."""
    try:
        with tarfile.open(tarball_path, "r") as tar:
            # Extract with overwrite for existing files
            members = tar.getmembers()
            for member in members:
                try:
                    tar.extract(member, extract_dir)
                except (OSError, IOError) as e:
                    # If extraction fails due to existing file, try to remove and re-extract
                    target_path = extract_dir / member.name
                    if target_path.exists():
                        if target_path.is_dir():
                            # Skip existing directories
                            continue
                        else:
                            # Remove existing file and re-extract
                            target_path.unlink()
                            tar.extract(member, extract_dir)
                    else:
                        # Re-raise if it's not a file exists issue
                        raise e
            return len(members)
    except Exception as e:
        print(f"Error extracting {tarball_path}: {e}")
        return 0


PAGE_RESPONSE_COLUMNS = [
    "primary_language",
    "is_rotation_valid",
    "rotation_correction",
    "is_table",
    "is_diagram",
    "natural_text",
]


def _coerce_optional(value: Any) -> Optional[Any]:
    """Convert pandas nulls to None."""
    if pd.isna(value):
        return None
    return value


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None or pd.isna(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _coerce_rotation(value: Any, default: int = 0) -> int:
    if value is None or pd.isna(value):
        return default
    try:
        rotation = int(value)
        if rotation in {0, 90, 180, 270}:
            return rotation
    except (TypeError, ValueError):
        pass
    return default


def _coerce_text(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value)
    return text if text.strip() else None


def extract_response_from_row(row: pd.Series) -> dict[str, Any]:
    """Return a PageResponse-like dict regardless of parquet schema."""
    response_data: dict[str, Any] = {}
    raw_response = row.get("response")

    if isinstance(raw_response, str):
        stripped = raw_response.strip()
        if stripped:
            try:
                response_data = json.loads(stripped)
            except json.JSONDecodeError:
                response_data = {}
    elif isinstance(raw_response, dict):
        response_data = dict(raw_response)

    if not response_data:
        for column in PAGE_RESPONSE_COLUMNS:
            if column in row:
                response_data[column] = _coerce_optional(row[column])

    extras = row.get("extras")
    if isinstance(extras, str):
        extras = extras.strip()
        if extras:
            try:
                response_data.update(json.loads(extras))
            except json.JSONDecodeError:
                pass
    elif isinstance(extras, dict):
        response_data.update(extras)

    response_data["primary_language"] = _coerce_optional(response_data.get("primary_language"))
    response_data["is_rotation_valid"] = _coerce_bool(response_data.get("is_rotation_valid"), True)
    response_data["rotation_correction"] = _coerce_rotation(response_data.get("rotation_correction"), 0)
    response_data["is_table"] = _coerce_bool(response_data.get("is_table"), False)
    response_data["is_diagram"] = _coerce_bool(response_data.get("is_diagram"), False)
    response_data["natural_text"] = _coerce_text(response_data.get("natural_text"))

    return response_data


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

    if Path(dataset_path).exists():
        print("Dataset path is a local folder, using that")
        local_dir = dataset_path
        shutil.copytree(local_dir, hugging_face_dir, dirs_exist_ok=True)
    else:
        print(f"Downloading dataset {dataset_path} to {hugging_face_dir}...")

        # For allenai/olmOCR-mix-0225, download everything as before
        # For other datasets, filter to only download needed files
        if dataset_path == "allenai/olmOCR-mix-0225":
            # Download the entire repository including PDFs and parquet files
            local_dir = snapshot_download(
                repo_id=dataset_path,
                repo_type="dataset",
                local_dir=hugging_face_dir,
            )
        else:
            # For other datasets, only download the specific parquet file and related PDF tarballs
            # Construct the dataset tag for filtering
            dataset_tag = f"{subset}_{split}"

            # Define patterns to allow:
            # 1. The specific parquet file
            # 2. Related PDF tarballs in pdf_tarballs directory
            # 3. README and metadata files (for dataset info)
            # 4. urls.jsonl for URL mappings if it exists
            allow_patterns = [
                f"{dataset_tag}.parquet",
                f"pdf_tarballs/{dataset_tag}_*.tar.gz",
                "README.md",
                "*.json",  # Include any metadata JSON files
            ]

            print(f"Filtering download to patterns: {allow_patterns}")

            local_dir = snapshot_download(
                repo_id=dataset_path,
                repo_type="dataset",
                local_dir=hugging_face_dir,
                allow_patterns=allow_patterns,
            )

        print(f"Downloaded to: {local_dir}")

    # Step 2: Create destination folder structure for processed markdown files
    processed_dir = dest_path / f"processed_{subset}_{split}"
    processed_dir.mkdir(exist_ok=True)

    # Manual map to parquet files for now
    if dataset_path == "allenai/olmOCR-mix-0225":
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
    else:
        parquet_files = [dest_path / "hugging_face" / f"{subset}_{split}.parquet"]

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
            # Find tarball files based on dataset type
            if dataset_path == "allenai/olmOCR-mix-0225":
                # Extract all tarballs for the full dataset
                tarball_files = list(pdf_tarballs_dir.glob("*.tar*")) + list(pdf_tarballs_dir.glob("*.tgz"))
            else:
                # Only extract tarballs matching the dataset_tag pattern
                dataset_tag = f"{subset}_{split}"
                tarball_files = list(pdf_tarballs_dir.glob(f"{dataset_tag}_*.tar*")) + list(pdf_tarballs_dir.glob(f"{dataset_tag}_*.tgz"))
                print(f"Filtering tarballs to pattern: {dataset_tag}_*")

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

    # Create urls.jsonl file for id-to-url mappings
    urls_file_path = processed_dir / "urls.jsonl"
    urls_file = open(urls_file_path, "w", encoding="utf-8")

    for parquet_file in parquet_files:
        print(f"Processing {parquet_file.name}...")
        df = pd.read_parquet(parquet_file)

        # Process each row
        for idx, row in df.iterrows():
            if max_examples and total_processed >= max_examples:
                break

            try:

                response = extract_response_from_row(row)
                doc_id = str(idx)

                assert len(doc_id) > 4

                # Extract URL from row and write to urls.jsonl
                url = row.get("url", None)
                if url:
                    url_entry = {"id": doc_id, "url": url}
                    urls_file.write(json.dumps(url_entry) + "\n")

                # Create folder structure
                # For allenai/olmOCR-mix-0225: use first 4 characters as folder
                # For other datasets: preserve the existing structure

                if dataset_path == "allenai/olmOCR-mix-0225":
                    # Standard format: use first 4 characters as folder
                    folder_name = doc_id[:4]
                    file_name = f"{doc_id[4:]}.md"

                    # Create directory
                    output_dir = processed_dir / folder_name
                    output_dir.mkdir(exist_ok=True)
                else:
                    # Custom format: preserve directory structure from doc_id
                    # The doc_id already contains the full path structure
                    if "/" in doc_id:
                        # doc_id contains path separators
                        path_parts = doc_id.rsplit("/", 1)
                        folder_path = Path(path_parts[0])
                        file_name = f"{path_parts[1]}.md"
                        output_dir = processed_dir / folder_path
                        output_dir.mkdir(parents=True, exist_ok=True)
                    else:
                        # No path separator, put at root
                        file_name = f"{doc_id}.md"
                        output_dir = processed_dir

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

                # Create symlink path based on dataset type
                if dataset_path == "allenai/olmOCR-mix-0225":
                    symlink_path = output_dir / f"{doc_id[4:]}.pdf"
                else:
                    # For custom datasets, use the same filename as the markdown
                    symlink_path = output_file.with_suffix(".pdf")

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

    # Close the urls.jsonl file
    urls_file.close()
    print(f"Created urls.jsonl with {total_processed} id-to-url mappings")

    print(f"Completed! Processed {total_processed} examples to {processed_dir}")
    print(f"Total errors: {total_errors}")

    return str(processed_dir)


def main():
    parser = argparse.ArgumentParser(description="Prepare OLMoCR mix dataset")
    parser.add_argument("--dataset-path", type=str, default="allenai/olmOCR-mix-0225", help="HuggingFace dataset path (e.g., 'allenai/olmocr-mix')")

    # Add subset and split to the parser (not the group) but they'll be validated later
    parser.add_argument("--subset", type=str, default=None, help="Dataset subset name")
    parser.add_argument("--split", type=str, default=None, help="Dataset split ex eval_s2pdf")

    parser.add_argument("--destination", type=str, required=True, help="Destination directory path")
    parser.add_argument("--max-examples", type=int, default=None, help="Maximum number of examples to process (default: all)")

    args = parser.parse_args()

    prepare_olmocr_mix(dataset_path=args.dataset_path, subset=args.subset, split=args.split, destination=args.destination, max_examples=args.max_examples)


if __name__ == "__main__":
    main()
