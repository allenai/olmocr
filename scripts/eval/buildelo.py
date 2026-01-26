import argparse
import dataclasses
import functools
import random
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations

import boto3
from dolma_refine.evaluate.aligners import HirschbergAligner
from dolma_refine.evaluate.metrics import DocumentEditSimilarity
from dolma_refine.evaluate.segmenters import SpacySegmenter
from tqdm import tqdm

from olmocr.eval.evalhtml import create_review_html
from olmocr.cloud_utils import expand_s3_glob, get_s3_bytes


@dataclasses.dataclass
class Comparison:
    pdf_path: str
    comparison_a_path: str
    comparison_b_path: str
    comparison_a_str: str
    comparison_b_str: str
    alignment: float

    @property
    def comparison_a_method(self):
        match = re.search(r"page[0-9]+_(\w+)\.md$", self.comparison_a_path)
        if match:
            return match.group(1)
        raise ValueError(f"No match found in path: {self.comparison_a_path}")

    @property
    def comparison_b_method(self):
        match = re.search(r"page[0-9]+_(\w+)\.md$", self.comparison_b_path)
        if match:
            return match.group(1)
        raise ValueError(f"No match found in path: {self.comparison_b_path}")


def process_single_pdf(pdf_path, all_mds, comparisons, segmenter_name="spacy"):
    """Process a single PDF and return its comparisons."""
    # Create resources inside the worker process
    s3_client = boto3.client("s3")
    segmenter = SpacySegmenter(segmenter_name)
    aligner = HirschbergAligner(match_score=1, mismatch_score=-1, indel_score=-1)
    comparer = DocumentEditSimilarity(segmenter=segmenter, aligner=aligner)

    pdf_comps = []
    result_comps = []

    # Get all comparison files for this PDF
    for comp in comparisons:
        comp_path = pdf_path.replace(".pdf", f"_{comp}.md")
        if comp_path in all_mds:
            pdf_comps.append(comp_path)

    # Generate all possible combinations
    for compa, compb in combinations(pdf_comps, 2):
        if random.choice([True, False]):
            compa, compb = compb, compa

        # Get the text content
        text_a = get_s3_bytes(s3_client, compa).decode("utf-8")
        text_b = get_s3_bytes(s3_client, compb).decode("utf-8")

        result_comps.append(
            Comparison(
                pdf_path=pdf_path,
                comparison_a_path=compa,
                comparison_b_path=compb,
                comparison_a_str=text_a,
                comparison_b_str=text_b,
                alignment=comparer.compute(text_a, text_b),
            )
        )

    return result_comps


def build_review_page(args, comparisons, index=0):
    page_data = []

    for comp in comparisons:
        page_data.append(
            {
                "s3_path": comp.pdf_path,
                "page": 1,
                "entry_key": comp.pdf_path + "-" + comp.comparison_a_method + "-" + comp.comparison_b_method,
                "gold_text": comp.comparison_a_str,
                "gold_metadata": comp.comparison_a_method,
                "eval_text": comp.comparison_b_str,
                "eval_metadata": comp.comparison_b_method,
                "alignment": comp.alignment,
            }
        )

    report_name = f"{args.name}{f'_{index}' if args.num_copies > 1 else ''}.html"
    create_review_html(page_data, report_name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generates comparison voting pages between different pairs of parses for a PDF.")
    parser.add_argument("--name", default="review_page", help="What name to give to this evaluation/comparison")
    parser.add_argument(
        "--review_size",
        default=50,
        type=int,
        help="Number of entries to show on the generated review page",
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=None,
        help="Maximum number of worker processes to use for parallel processing",
    )
    parser.add_argument("--comparisons", default=["pdelf", "marker", "gotocr_format", "mineru"], help="Different variants to compare against")
    parser.add_argument(
        "--num_copies",
        default=1,
        type=int,
        help="Number of reports to generate, labeled _0, _1, etc. if greater than 1",
    )
    parser.add_argument(
        "s3_path", type=str, help="Path to the folder where you keep your data files, expecting to see *.md files in there along with *.png and *.pdf"
    )

    args = parser.parse_args()

    # Create S3 client only for initial file listing
    s3_client = boto3.client("s3")

    # Get all PDFs and MD files
    all_pdfs = set(expand_s3_glob(s3_client, args.s3_path + "/*.pdf"))
    all_mds = set(expand_s3_glob(s3_client, args.s3_path + "/*.md"))

    all_comps = []

    # Create a partial function with all the common arguments
    process_pdf = functools.partial(process_single_pdf, all_mds=all_mds, comparisons=args.comparisons)

    # Use ProcessPoolExecutor for parallel processing
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        # Submit all PDF processing tasks
        future_to_pdf = {executor.submit(process_pdf, pdf_path): pdf_path for pdf_path in all_pdfs}

        # Process results as they complete using tqdm for progress
        for future in tqdm(as_completed(future_to_pdf), total=len(all_pdfs)):
            pdf_path = future_to_pdf[future]
            try:
                pdf_results = future.result()
                all_comps.extend(pdf_results)
            except Exception as e:
                print(f"Error processing {pdf_path}: {str(e)}")

    # Remove all results where the alignment is > 0.96 as these are just too similar to be useful
    all_comps = [c for c in all_comps if c.alignment < 0.96]

    # Shuffle the results
    random.shuffle(all_comps)

    # Generate the specified number of copies of the report
    for i in range(args.num_copies):
        start_index = i * args.review_size
        end_index = start_index + args.review_size

        # Check if there is enough data for the next report
        if start_index >= len(all_comps):
            print(f"Not enough data to generate report {i}. Stopping early.")
            break

        build_review_page(args, all_comps[start_index:end_index], index=i)
