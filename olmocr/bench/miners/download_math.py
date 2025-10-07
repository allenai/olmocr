# This script goes to
# https://arxiv.org/list/math/recent?skip=0&show=2000
# and downloads all the source PDFs, as well as latex equivalents, and puts them together into
# Searching for:
# <a href="/pdf/2503.08675" title="Download PDF" id="pdf-2503.08675" aria-labelledby="pdf-2503.08675">pdf</a>
# a math_data folder
#!/usr/bin/env python3
import argparse
import io
import os
import re
import tarfile
import time

import requests
from tqdm import tqdm


def download_and_extract_source(paper_id, data_dir):
    source_url = f"https://export.arxiv.org/src/{paper_id}"
    print(f"Downloading source for {paper_id} from {source_url}...")
    response = requests.get(source_url)
    if response.status_code != 200:
        print(f"Error downloading source for {paper_id}: HTTP {response.status_code}")
        return False

    # Try to open as a tar archive.
    try:
        file_obj = io.BytesIO(response.content)
        with tarfile.open(fileobj=file_obj, mode="r:*") as tar:
            # Filter for regular .tex files.
            members = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".tex")]
            print("Found TeX files:", [m.name for m in members])
            if len(members) == 1:
                member = members[0]
                extracted = tar.extractfile(member)
                if extracted is None:
                    print(f"Error extracting {paper_id}: Could not read the file from the archive.")
                    return False
                content = extracted.read()
                out_path = os.path.join(data_dir, f"{paper_id}.tex")
                with open(out_path, "wb") as f:
                    f.write(content)
                print(f"Saved tex source for {paper_id} as {out_path}")
                return True
            else:
                print(f"Error: {paper_id} contains multiple .tex files or none. Skipping extraction.")
                return False
    except tarfile.ReadError:
        # Not a tar archive; assume it's a single file.
        out_path = os.path.join(data_dir, f"{paper_id}.tex")
        with open(out_path, "wb") as f:
            f.write(response.content)
        print(f"Saved non-archive tex source for {paper_id} as {out_path}")
        return True


def download_pdf(paper_id, data_dir):
    pdf_url = f"https://export.arxiv.org/pdf/{paper_id}.pdf"
    print(f"Downloading PDF for {paper_id} from {pdf_url}...")
    response = requests.get(pdf_url)
    if response.status_code != 200:
        print(f"Error downloading PDF for {paper_id}: HTTP {response.status_code}")
        return False
    out_path = os.path.join(data_dir, f"{paper_id}.pdf")
    with open(out_path, "wb") as f:
        f.write(response.content)
    print(f"Saved PDF for {paper_id} as {out_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Download and extract arXiv LaTeX source files and PDFs only if both succeed.")
    parser.add_argument(
        "--url", type=str, default="https://arxiv.org/list/math/recent?skip=0&show=2000", help="URL of the arXiv list page to scrape (default: %(default)s)"
    )
    parser.add_argument("--data_dir", type=str, default="math_data/pdfs", help="Directory to save downloaded files (default: %(default)s)")
    parser.add_argument("--pdf_only", action="store_true", help="Skip LaTeX verification and only download PDFs")
    args = parser.parse_args()

    if not os.path.exists(args.data_dir):
        os.makedirs(args.data_dir)

    print(f"Downloading list page from {args.url}...")
    response = requests.get(args.url)
    if response.status_code != 200:
        print(f"Error downloading list page: HTTP {response.status_code}")
        return

    # Find all pdf links in the form: <a href="/pdf/2503.08675" ...>pdf</a>
    pattern = re.compile(r'href="/pdf/(\d+\.\d+)"')
    paper_ids = pattern.findall(response.text)
    print(f"Found {len(paper_ids)} papers.")

    # For each paper, download based on the mode
    for paper_id in tqdm(paper_ids):
        if args.pdf_only:
            # Only download PDFs, skip LaTeX verification
            pdf_success = download_pdf(paper_id, args.data_dir)
            if not pdf_success:
                print(f"Failed to download PDF for {paper_id}")
        else:
            # Original behavior: only keep files if both tex extraction and pdf download succeed
            tex_success = download_and_extract_source(paper_id, args.data_dir)
            if not tex_success:
                print(f"Skipping PDF download for {paper_id} because tex extraction failed.")
                continue

            pdf_success = download_pdf(paper_id, args.data_dir)
            if not pdf_success:
                # Remove the tex file if the PDF download fails.
                tex_path = os.path.join(args.data_dir, f"{paper_id}.tex")
                if os.path.exists(tex_path):
                    os.remove(tex_path)
                    print(f"Removed tex file for {paper_id} because PDF download failed.")
        time.sleep(3)


if __name__ == "__main__":
    main()
