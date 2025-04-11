import os
import glob
import boto3
import random
import base64
import argparse

from tqdm import tqdm
from typing import List
from pypdf import PdfReader, PdfWriter
from urllib.parse import urlparse
from concurrent.futures import ProcessPoolExecutor, as_completed

from olmocr.filter import PdfFilter
from olmocr.data.renderpdf import render_pdf_to_base64png


pdf_filter = PdfFilter()


def sample_pdf_pages(num_pages: int, first_n_pages: int, max_sample_pages: int) -> List[int]:
    """
    Returns a list of sampled page indices (1-based).
    - Always include the first_n_pages (or all pages if num_pages < first_n_pages).
    - Randomly sample the remaining pages up to a total of max_sample_pages.
    """
    if num_pages <= first_n_pages:
        return list(range(1, num_pages + 1))
    sample_pages    = list(range(1, first_n_pages + 1))
    remaining_pages = list(range(first_n_pages + 1, num_pages + 1))
    if remaining_pages:
        # How many random pages to pick beyond the first_n_pages
        random_pick = min(max_sample_pages - first_n_pages, len(remaining_pages))
        sample_pages += random.sample(remaining_pages, random_pick)
    return sample_pages


def fetch_s3_file(s3_url: str, local_path: str) -> str:
    """
    Download a file from an S3 URI (s3://bucket/key) to local_path.
    """
    parsed      = urlparse(s3_url)
    bucket_name = parsed.netloc
    key         = parsed.path.lstrip("/")
    s3          = boto3.client("s3")
    s3.download_file(bucket_name, key, local_path)
    return local_path


def extract_single_page_pdf(input_pdf_path: str, page_number: int, output_pdf_path: str) -> None:
    """
    Extracts exactly one page (page_number, 1-based) from input_pdf_path
    and writes to output_pdf_path.
    """
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()
    # Page numbers in PdfReader are 0-based
    writer.add_page(reader.pages[page_number - 1])
    with open(output_pdf_path, "wb") as f:
        writer.write(f)


def process_pdf(pdf_path: str, first_n_pages: int, max_sample_pages: int, no_filter: bool, output_dir: str):
    """
    - Download the PDF locally if it's in S3.
    - Optionally filter the PDF (if no_filter=False).
    - Sample the pages.
    - For each sampled page, extract a one-page PDF and also render it to PNG.
    """
    if pdf_path.startswith("s3://"):
        local_pdf_path = os.path.join("/tmp", os.path.basename(pdf_path))
        fetch_s3_file(pdf_path, local_pdf_path)
    else:
        local_pdf_path = pdf_path

    if (not no_filter) and pdf_filter.filter_out_pdf(local_pdf_path):
        print(f"Skipping {local_pdf_path} due to filter.")
        return False

    # Make sure we have an absolute path for the PDF name
    base_pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]

    reader        = PdfReader(local_pdf_path)
    num_pages     = len(reader.pages)

    sampled_pages = sample_pdf_pages(num_pages, first_n_pages, max_sample_pages)

    # For each sampled page, produce a single-page PDF and a PNG
    for page_num in sampled_pages:
        single_pdf_name = f"{base_pdf_name}_page{page_num}.pdf"
        single_png_name = f"{base_pdf_name}_page{page_num}.png"

        single_pdf_path = os.path.join(output_dir, single_pdf_name)
        single_png_path = os.path.join(output_dir, single_png_name)

        try:
            # 1) Extract single-page PDF
            extract_single_page_pdf(local_pdf_path, page_num, single_pdf_path)

            # 2) Render that single-page PDF to a PNG
            b64png = render_pdf_to_base64png(single_pdf_path, page_num=0, target_longest_image_dim=1024)

            with open(single_png_path, "wb") as pngf:
                pngf.write(base64.b64decode(b64png))

        except Exception as e:
            print(f"Error while processing {pdf_path}, page {page_num}: {e}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Sample PDFs, extract single-page PDFs, and render them as PNG.")
    parser.add_argument("--glob_path", type=str, help="Local or S3 path glob (e.g., *.pdf or s3://bucket/pdfs/*.pdf).")
    parser.add_argument("--path_list", type=str, help="Path to a file containing paths to PDFs, one per line.")
    parser.add_argument("--no_filter", action="store_true", help="Disables filtering so that ALL PDFs are processed.")
    parser.add_argument("--num_sample_docs", type=int, default=2000, help="Number of PDF documents to sample.")
    parser.add_argument("--first_n_pages", type=int, default=0, help="Always sample the first N pages of each PDF.")
    parser.add_argument("--max_sample_pages", type=int, default=1, help="Max number of pages to sample per PDF.")
    parser.add_argument("--output_dir", type=str, default="sampled_pages_output", help="Output directory for the extracted PDFs and PNGs.")
    parser.add_argument("--reservoir_size", type=int, default=None, help="Size of the reservoir for sampling paths. Defaults to 10x num_sample_docs.")
    args = parser.parse_args()

    # Set default reservoir_size if not provided
    if args.reservoir_size is None:
        args.reservoir_size = 10 * args.num_sample_docs

    os.makedirs(args.output_dir, exist_ok=True)

    # Reservoir sample for PDF paths
    pdf_paths = []
    n = 0               # total number of items seen

    # Either load from glob or from path_list
    if args.glob_path:
        if args.glob_path.startswith("s3://"):
            # Handle S3 globbing
            parsed        = urlparse(args.glob_path)
            s3            = boto3.client("s3")
            bucket_name   = parsed.netloc
            prefix        = os.path.dirname(parsed.path.lstrip("/")) + "/"
            paginator     = s3.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

            for page in page_iterator:
                for obj in page.get("Contents", []):
                    if obj["Key"].endswith(".pdf"):
                        n += 1
                        path = f"s3://{bucket_name}/{obj['Key']}"
                        if len(pdf_paths) < args.reservoir_size:
                            pdf_paths.append(path)
                        else:
                            s = random.randint(1, n)
                            if s <= args.reservoir_size:
                                pdf_paths[s - 1] = path
        else:
            # Handle local globbing
            for path in glob.iglob(args.glob_path, recursive=True):
                n += 1
                if len(pdf_paths) < args.reservoir_size:
                    pdf_paths.append(path)
                else:
                    s = random.randint(1, n)
                    if s <= args.reservoir_size:
                        pdf_paths[s - 1] = path
    elif args.path_list:
        with open(args.path_list, "r") as f:
            for line in f:
                path = line.strip()
                if not path:
                    continue
                n += 1
                if len(pdf_paths) < args.reservoir_size:
                    pdf_paths.append(path)
                else:
                    s = random.randint(1, n)
                    if s <= args.reservoir_size:
                        pdf_paths[s - 1] = path

    # Shuffle the reservoir so we don't always pick from the front
    random.shuffle(pdf_paths)
    print(f"Loaded and shuffled {len(pdf_paths)} PDF paths. Will process up to {args.num_sample_docs} of them.")

    pdfs_with_output = 0

    # Use a ProcessPoolExecutor to parallelize PDF processing
    # You may reduce max_workers if you have memory/CPU constraints
    with ProcessPoolExecutor() as executor:
        futures = {}
        # Submit tasks
        for pdf_path in pdf_paths:
            future = executor.submit(process_pdf, pdf_path, args.first_n_pages, args.max_sample_pages, args.no_filter, args.output_dir)
            futures[future] = pdf_path

        # Track completion
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing PDFs"):
            if future.result():
                pdfs_with_output += 1
            if pdfs_with_output >= args.num_sample_docs:
                # Cancel remaining tasks
                executor.shutdown(cancel_futures=True)
                break

    print(f"Done. Processed or attempted to process {pdfs_with_output} PDFs. Output is in: {args.output_dir}")


if __name__ == "__main__":
    main()
