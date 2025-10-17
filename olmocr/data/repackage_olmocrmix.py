#!/usr/bin/env python3
"""
Repackage locally processed OLMoCR-mix style data back into parquet metadata and PDF tarballs.

Given a directory that mirrors the layout produced by prepare_olmocrmix.py (folders of markdown/PDF
pairs), this script rebuilds a HuggingFace-style payload by:
  * walking the processed directory to recover document ids, metadata, and natural text
  * emitting a parquet file with dedicated columns for PageResponse fields plus document helpers
  * chunking PDFs into .tar.gz archives that stay under a user-configurable size (default 1 GiB)
"""

from __future__ import annotations

import argparse
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import pandas as pd
from tqdm import tqdm

from olmocr.prompts import PageResponse
from olmocr.train.dataloader import FrontMatterParser

DEFAULT_MAX_TAR_BYTES = 1_073_741_824  # 1 GiB


@dataclass(slots=True)
class DocumentRecord:
    doc_id: str
    markdown_path: Path
    pdf_path: Path
    pdf_size: int
    primary_language: Optional[str]
    is_rotation_valid: Optional[bool]
    rotation_correction: Optional[int]
    is_table: Optional[bool]
    is_diagram: Optional[bool]
    natural_text: Optional[str]
    page_number: Optional[int]
    url: Optional[str]
    extras_json: Optional[str]
    chunk_name: Optional[str] = None
    pdf_relpath: Optional[str] = None


def infer_doc_id(md_path: Path, processed_root: Path) -> str:
    """Reconstruct the doc_id used in parquet/index space."""
    rel = md_path.relative_to(processed_root)

    # Simply preserve the directory structure as the doc_id
    # Convert path to doc_id by removing extension
    return str(rel.with_suffix(""))


def infer_pdf_path(md_path: Path, doc_id: str, pdf_root: Optional[Path]) -> Path:
    """Locate the PDF file corresponding to the markdown doc."""
    pdf_candidate = md_path.with_suffix(".pdf")
    if pdf_candidate.exists():
        return pdf_candidate.resolve()

    if pdf_root is not None:
        alt_path = pdf_root / f"{doc_id}.pdf"
        if alt_path.exists():
            return alt_path.resolve()

    raise FileNotFoundError(f"No PDF found for {md_path}")


def normalize_response_payload(front_matter: Dict[str, object], body_text: str) -> Dict[str, object]:
    """Merge parsed fields with the natural text payload."""
    payload = dict(front_matter)
    text = body_text if body_text and body_text.strip() else None

    # Handle primary_language field - convert booleans to None
    if "primary_language" in payload:
        val = payload["primary_language"]
        if isinstance(val, bool):
            # Convert boolean to None (no language detected)
            print(f"[DEBUG] Converting boolean primary_language value '{val}' to None")
            payload["primary_language"] = None
        elif not isinstance(val, (str, type(None))):
            # Convert other types to string or None
            print(f"[DEBUG] Converting unexpected primary_language type {type(val)} value '{val}' to string/None")
            payload["primary_language"] = str(val) if val else None
    else:
        payload["primary_language"] = None

    payload.setdefault("is_rotation_valid", True)
    payload.setdefault("rotation_correction", 0)
    payload.setdefault("is_table", False)
    payload.setdefault("is_diagram", False)
    payload["natural_text"] = text
    return payload


def load_url_mappings(processed_dir: Path) -> Dict[str, str]:
    """Load URL mappings from urls.jsonl if it exists."""
    urls_file = processed_dir / "urls.jsonl"
    url_map = {}

    if urls_file.exists():
        print(f"Loading URL mappings from {urls_file}")
        with open(urls_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                url_map[entry["id"]] = entry["url"]
        print(f"Loaded {len(url_map)} URL mappings")

    return url_map


def guess_url(front_matter: Dict[str, object], doc_id: str, source_url_template: Optional[str]) -> Optional[str]:
    # TODO, we will have to add some better support for this
    return None


def parse_page_number(doc_id: str, front_matter: Dict[str, object]) -> Optional[int]:
    """Extract page number from front matter or doc_id suffix."""
    if "page_number" in front_matter:
        value = front_matter["page_number"]
        try:
            return int(value)
        except (TypeError, ValueError):
            pass

    if "-" in doc_id:
        suffix = doc_id.rsplit("-", 1)[-1]
        try:
            return int(suffix)
        except ValueError:
            return None
    return None


def collect_documents(
    processed_dir: Path,
    pdf_root: Optional[Path],
    url_template: Optional[str],
    strict: bool,
) -> List[DocumentRecord]:
    """Scan processed markdown/pdf pairs into DocumentRecord objects."""
    records: List[DocumentRecord] = []
    md_files = sorted(processed_dir.rglob("*.md"))
    canonical_keys = {
        "primary_language",
        "is_rotation_valid",
        "rotation_correction",
        "is_table",
        "is_diagram",
        "natural_text",
    }

    # Load URL mappings from urls.jsonl if it exists
    url_map = load_url_mappings(processed_dir)

    parser = FrontMatterParser(front_matter_class=PageResponse)

    for md_path in tqdm(md_files, desc="Scanning markdown files"):
        try:
            doc_id = infer_doc_id(md_path, processed_dir)
            pdf_path = infer_pdf_path(md_path, doc_id, pdf_root)
            markdown_text = md_path.read_text(encoding="utf-8")
            front_matter, body_text = parser._extract_front_matter_and_text(markdown_text)
            response_payload = normalize_response_payload(front_matter, body_text)
            pdf_size = pdf_path.stat().st_size
            page_number = parse_page_number(doc_id, front_matter)

            # Try to get URL from the loaded url_map
            # Handle both formats: "0001/234567" and "0001234567"
            url = url_map.get(doc_id)
            if not url and "/" in doc_id:
                # Try combining the parts (e.g., "0001/234567" -> "0001234567")
                combined_id = doc_id.replace("/", "")
                url = url_map.get(combined_id)
            if not url:
                # Fall back to guess_url if URL not found in map
                url = guess_url(front_matter, doc_id, url_template)

            extras = {k: v for k, v in response_payload.items() if k not in canonical_keys}
            extras_json = json.dumps(extras, ensure_ascii=False) if extras else None

            records.append(
                DocumentRecord(
                    doc_id=doc_id,
                    markdown_path=md_path,
                    pdf_path=pdf_path,
                    pdf_size=pdf_size,
                    primary_language=response_payload.get("primary_language"),
                    is_rotation_valid=response_payload.get("is_rotation_valid"),
                    rotation_correction=response_payload.get("rotation_correction"),
                    is_table=response_payload.get("is_table"),
                    is_diagram=response_payload.get("is_diagram"),
                    natural_text=response_payload.get("natural_text"),
                    page_number=page_number,
                    url=url,
                    extras_json=extras_json,
                )
            )
        except Exception as exc:
            if strict:
                raise
            tqdm.write(f"[WARN] Skipping {md_path}: {exc}")

    return records


def write_parquet(records: List[DocumentRecord], parquet_path: Path, compression: str) -> None:
    """Emit the textual payload into a parquet file."""
    if not records:
        raise RuntimeError("No records to write into parquet")

    pdf_relpaths: List[str] = []
    for rec in records:
        path_value = rec.pdf_relpath or f"{rec.doc_id}.pdf"
        pdf_relpaths.append(path_value)

    data = {
        "url": [rec.url for rec in records],
        "page_number": [rec.page_number for rec in records],
        "pdf_relpath": pdf_relpaths,
        "primary_language": [rec.primary_language for rec in records],
        "is_rotation_valid": [rec.is_rotation_valid for rec in records],
        "rotation_correction": [rec.rotation_correction for rec in records],
        "is_table": [rec.is_table for rec in records],
        "is_diagram": [rec.is_diagram for rec in records],
        "natural_text": [rec.natural_text for rec in records],
        "extras": [rec.extras_json for rec in records],
    }
    index = [rec.doc_id for rec in records]
    df = pd.DataFrame(data, index=index)
    df.index.name = "id"

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, compression=compression)


def chunk_records_by_size(records: List[DocumentRecord], max_bytes: int) -> Iterator[List[DocumentRecord]]:
    """Yield batches of records whose summed PDF sizes stay under max_bytes."""
    batch: List[DocumentRecord] = []
    batch_size = 0
    overhead = 1024  # rough tar header allowance per entry

    for record in records:
        entry_size = record.pdf_size + overhead
        if entry_size > max_bytes:
            raise RuntimeError(f"Single PDF {record.pdf_path} exceeds max tar size {max_bytes} bytes")

        if batch and batch_size + entry_size > max_bytes:
            yield batch
            batch = []
            batch_size = 0

        batch.append(record)
        batch_size += entry_size

    if batch:
        yield batch


def write_pdf_tarballs(
    records: List[DocumentRecord],
    pdf_dir: Path,
    chunk_prefix: str,
    max_bytes: int,
    manifest_path: Path,
    chunk_dir_name: str,
) -> None:
    """Bundle PDFs into .tar.gz archives under the size cap."""
    pdf_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest_rows: List[Dict[str, str]] = []
    batches = chunk_records_by_size(records, max_bytes)

    normalized_dir = chunk_dir_name.strip().strip("/") if chunk_dir_name else ""

    for chunk_idx, batch in tqdm(enumerate(batches), desc="Writing PDF tarballs"):
        tar_name = f"{chunk_prefix}_{chunk_idx:05d}.tar.gz"
        tar_path = pdf_dir / tar_name
        with tarfile.open(tar_path, "w:gz", dereference=True) as tar:
            for rec in batch:
                tar.add(rec.pdf_path, arcname=f"{rec.doc_id}.pdf", recursive=False)
                rec.chunk_name = tar_name
                inner_ref = f"{tar_name}:{rec.doc_id}.pdf"
                rec.pdf_relpath = f"{normalized_dir}/{inner_ref}" if normalized_dir else inner_ref
                manifest_rows.append({"doc_id": rec.doc_id, "chunk": tar_name, "arcname": f"{rec.doc_id}.pdf", "pdf_relpath": rec.pdf_relpath})

        actual_size = tar_path.stat().st_size
        if actual_size > max_bytes:
            raise RuntimeError(f"{tar_path} exceeded size cap ({actual_size} bytes > {max_bytes} bytes)")

    with manifest_path.open("w", encoding="utf-8") as manifest_file:
        for row in manifest_rows:
            manifest_file.write(json.dumps(row) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repackage processed olmocr-mix data into parquet + PDF tarballs.")
    parser.add_argument("--processed-dir", required=True, type=Path, help="Directory with markdown/PDF pairs (output of prepare_olmocrmix.py).")
    parser.add_argument("--subset", required=True, help="Dataset subset identifier (e.g. 00_documents).")
    parser.add_argument("--split", required=True, help="Dataset split identifier (e.g. train_s2pdf).")
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Destination directory for the parquet file and pdf tarballs.",
    )
    parser.add_argument(
        "--parquet-name",
        default=None,
        help="Filename for the generated parquet file (defaults to {subset}_{split}.parquet).",
    )
    parser.add_argument(
        "--pdf-chunk-dir",
        default="pdf_tarballs",
        help="Name of the subdirectory (under output-dir) to place PDF tarballs in.",
    )
    parser.add_argument(
        "--pdf-chunk-prefix",
        default=None,
        help="Prefix for generated tarball filenames (defaults to {subset}_{split}).",
    )
    parser.add_argument(
        "--max-tar-size-bytes",
        type=int,
        default=DEFAULT_MAX_TAR_BYTES,
        help="Maximum uncompressed size (in bytes) to pack into a single tarball (default 1 GiB).",
    )
    parser.add_argument(
        "--pdf-root",
        type=Path,
        default=None,
        help="Optional directory containing {doc_id}.pdf files if they are not alongside the markdown.",
    )
    parser.add_argument(
        "--url-template",
        type=str,
        default=None,
        help="Optional template to synthesize URLs, e.g. 's3://bucket/{prefix}/{base_pdf}.pdf'.",
    )
    parser.add_argument(
        "--parquet-compression",
        default="snappy",
        help="Compression codec passed to pandas.to_parquet (default: snappy).",
    )
    parser.add_argument(
        "--manifest-name",
        default="pdf_chunk_manifest.jsonl",
        help="Filename for the emitted chunk manifest (stored under output-dir).",
    )
    parser.add_argument("--strict", action="store_true", help="Fail immediately when a markdown/PDF pair cannot be processed.")
    return parser.parse_args()


def build_dataset_tag(subset: str, split: str) -> str:
    """Normalize subset/split into a filesystem-friendly tag."""
    return f"{subset.strip().replace('/', '_')}_{split.strip().replace('/', '_')}"


def main() -> None:
    args = parse_args()

    processed_dir = args.processed_dir.expanduser().resolve()
    if not processed_dir.exists():
        raise FileNotFoundError(f"Processed directory not found: {processed_dir}")

    pdf_root = args.pdf_root.expanduser().resolve() if args.pdf_root else None
    output_dir = args.output_dir.expanduser().resolve()
    dataset_tag = build_dataset_tag(args.subset, args.split)
    parquet_name = args.parquet_name or f"{dataset_tag}.parquet"
    chunk_prefix = args.pdf_chunk_prefix or dataset_tag
    parquet_path = output_dir / parquet_name
    pdf_dir = output_dir / args.pdf_chunk_dir
    manifest_path = output_dir / args.manifest_name

    records = collect_documents(processed_dir, pdf_root, args.url_template, args.strict)
    if not records:
        raise RuntimeError("No markdown/PDF pairs discovered - nothing to package.")

    records.sort(key=lambda rec: rec.doc_id)

    write_pdf_tarballs(records, pdf_dir, chunk_prefix, args.max_tar_size_bytes, manifest_path, args.pdf_chunk_dir)
    write_parquet(records, parquet_path, args.parquet_compression)

    print(f"Wrote parquet: {parquet_path}")
    print(f"Wrote PDF tarballs to: {pdf_dir}")
    print(f"Wrote manifest: {manifest_path}")
    print(f"Total documents packaged: {len(records)}")


if __name__ == "__main__":
    main()
