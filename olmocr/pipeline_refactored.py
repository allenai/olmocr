"""
Refactored olmOCR Pipeline

This is the refactored version of the olmOCR pipeline that uses the new modular
architecture while maintaining 100% backward compatibility with the original
monolithic implementation.

The pipeline is now organized into focused modules:
- core: Main orchestration and workflow coordination  
- processing: Page and document processing logic
- workers: Worker management and parallel processing
- http_client: HTTP communication with SGLang backend
- document_builder: Dolma document creation and formatting
"""

import argparse
import asyncio
import logging
import os
import random
import sys
import tempfile
from tqdm import tqdm

from olmocr.check import check_poppler_version
from olmocr.image_utils import is_jpeg, is_png
from olmocr.pipeline import create_pipeline_orchestrator
from olmocr.s3_utils import expand_s3_glob, get_s3_bytes
from olmocr.work_queue import LocalWorkQueue, S3WorkQueue
from pypdf import PdfReader

# Initialize logger with same configuration as original
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False

sglang_logger = logging.getLogger("sglang")
sglang_logger.propagate = False

file_handler = logging.FileHandler("olmocr-pipeline-debug.log", mode="a")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)
sglang_logger.addHandler(file_handler)

# Quiet logs from pypdf
logging.getLogger("pypdf").setLevel(logging.ERROR)


async def populate_work_queue(args, orchestrator):
    """
    Populate the work queue with PDF paths from command line arguments.
    
    Args:
        args: Command line arguments
        orchestrator: Pipeline orchestrator instance
        
    Returns:
        Initialized work queue
    """
    # Create work queue
    work_queue = await orchestrator.create_work_queue(args)
    
    if not args.pdfs:
        return work_queue
    
    logger.info("Got --pdfs argument, going to add to the work queue")
    pdf_work_paths = set()

    for pdf_path in args.pdfs:
        # Expand s3 paths
        if pdf_path.startswith("s3://"):
            logger.info(f"Expanding s3 glob at {pdf_path}")
            pdf_work_paths |= set(expand_s3_glob(orchestrator.pdf_s3, pdf_path))
        elif os.path.exists(pdf_path):
            if (
                pdf_path.lower().endswith(".pdf")
                or pdf_path.lower().endswith(".png")
                or pdf_path.lower().endswith(".jpg")
                or pdf_path.lower().endswith(".jpeg")
            ):
                if open(pdf_path, "rb").read(4) == b"%PDF":
                    logger.info(f"Loading file at {pdf_path} as PDF document")
                    pdf_work_paths.add(pdf_path)
                elif is_png(pdf_path) or is_jpeg(pdf_path):
                    logger.info(f"Loading file at {pdf_path} as image document")
                    pdf_work_paths.add(pdf_path)
                else:
                    logger.warning(f"File at {pdf_path} is not a valid PDF")
            elif pdf_path.lower().endswith(".txt"):
                logger.info(f"Loading file at {pdf_path} as list of paths")
                with open(pdf_path, "r") as f:
                    pdf_work_paths |= set(filter(None, (line.strip() for line in f)))
            else:
                raise ValueError(f"Unsupported file extension for {pdf_path}")
        else:
            raise ValueError("pdfs argument needs to be either a local path, an s3 path, or an s3 glob pattern...")

    logger.info(f"Found {len(pdf_work_paths):,} total pdf paths to add")

    # Estimate average pages per pdf
    sample_size = min(100, len(pdf_work_paths))
    sampled_pdfs = random.sample(list(pdf_work_paths), sample_size)
    page_counts = []

    for pdf in tqdm(sampled_pdfs, desc="Sampling PDFs to calculate optimal length"):
        try:
            # Download the PDF to a temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp_file:
                tmp_file.write(get_s3_bytes(orchestrator.pdf_s3, pdf))
                tmp_file.flush()
                if is_png(tmp_file.name) or is_jpeg(tmp_file.name):
                    page_counts.append(1)
                else:
                    reader = PdfReader(tmp_file.name)
                    page_counts.append(len(reader.pages))
        except Exception as e:
            logger.warning(f"Failed to read {pdf}: {e}")

    if page_counts:
        avg_pages_per_pdf = sum(page_counts) / len(page_counts)
    else:
        logger.warning("Could not read any PDFs to estimate average page count.")
        avg_pages_per_pdf = 10  # Default to 10 pages per PDF if sampling fails

    items_per_group = max(1, int(args.pages_per_group / avg_pages_per_pdf))
    logger.info(f"Calculated items_per_group: {items_per_group} based on average pages per PDF: {avg_pages_per_pdf:.2f}")

    # Now call populate_queue
    await work_queue.populate_queue(pdf_work_paths, items_per_group)
    
    return work_queue


async def handle_beaker_submission(args):
    """Handle Beaker job submission."""
    # Import the original Beaker submission function
    from olmocr.pipeline import submit_beaker_job
    submit_beaker_job(args)


async def handle_stats_printing(args, work_queue):
    """Handle statistics printing."""
    # Import the original stats printing function
    from olmocr.pipeline import print_stats
    print_stats(args, work_queue)


async def setup_beaker_environment():
    """Set up Beaker environment if running in Beaker."""
    if "BEAKER_JOB_NAME" not in os.environ:
        return
    
    # Set up credentials and logging for Beaker environment
    sglang_logger.addHandler(console_handler)
    
    # Set up AWS credentials
    cred_path = os.path.join(os.path.expanduser("~"), ".aws", "credentials")
    os.makedirs(os.path.dirname(cred_path), exist_ok=True)
    with open(cred_path, "w") as f:
        f.write(os.environ.get("AWS_CREDENTIALS_FILE", ""))
    
    # Set up GCS credentials
    cred_path = os.path.join(os.path.expanduser("~"), ".gcs", "credentials")
    os.makedirs(os.path.dirname(cred_path), exist_ok=True)
    with open(cred_path, "w") as f:
        f.write(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_FILE", ""))
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path

    # Wait a little bit so that not all beaker jobs start at the same time
    replica_count = int(os.environ.get("BEAKER_REPLICA_COUNT", "1"))
    interval = 10 if (replica_count - 1) * 10 <= 240 else 240 / max(1, replica_count - 1)
    sleep_time = int(int(os.environ.get("BEAKER_REPLICA_RANK", "0")) * interval)
    logger.info(f"Beaker job sleeping for {sleep_time} seconds to stagger model downloads")
    await asyncio.sleep(sleep_time)


async def main():
    """Main pipeline function with refactored modular architecture."""
    parser = argparse.ArgumentParser(description="Manager for running millions of PDFs through a batch inference pipeline")
    parser.add_argument(
        "workspace",
        help="The filesystem path where work will be stored, can be a local folder, or an s3 path if coordinating work with many workers, s3://bucket/prefix/ ",
    )
    parser.add_argument(
        "--pdfs",
        nargs="*",
        help="Path to add pdfs stored in s3 to the workspace, can be a glob path s3://bucket/prefix/*.pdf or path to file containing list of pdf paths",
        default=None,
    )
    parser.add_argument("--workspace_profile", help="S3 configuration profile for accessing the workspace", default=None)
    parser.add_argument("--pdf_profile", help="S3 configuration profile for accessing the raw pdf documents", default=None)
    parser.add_argument("--pages_per_group", type=int, default=500, help="Aiming for this many pdf pages per work item group")
    parser.add_argument("--max_page_retries", type=int, default=8, help="Max number of times we will retry rendering a page")
    parser.add_argument("--max_page_error_rate", type=float, default=0.004, help="Rate of allowable failed pages in a document, 1/250 by default")
    parser.add_argument("--workers", type=int, default=8, help="Number of workers to run at a time")
    parser.add_argument("--apply_filter", action="store_true", help="Apply basic filtering to English pdfs which are not forms, and not likely seo spam")
    parser.add_argument("--stats", action="store_true", help="Instead of running any job, reports some statistics about the current workspace")
    parser.add_argument("--markdown", action="store_true", help="Also write natural text to markdown files preserving the folder structure of the input pdfs")

    # Model parameters
    parser.add_argument(
        "--model",
        help="List of paths where you can find the model to convert this pdf. You can specify several different paths here, and the script will try to use the one which is fastest to access",
        default="allenai/olmOCR-7B-0225-preview",
    )
    parser.add_argument("--model_max_context", type=int, default="8192", help="Maximum context length that the model was fine tuned under")
    parser.add_argument("--model_chat_template", type=str, default="qwen2-vl", help="Chat template to pass to sglang server")
    parser.add_argument("--target_longest_image_dim", type=int, help="Dimension on longest side to use for rendering the pdf pages", default=1024)
    parser.add_argument("--target_anchor_text_len", type=int, help="Maximum amount of anchor text to use (characters)", default=6000)

    # Beaker/job running stuff
    parser.add_argument("--beaker", action="store_true", help="Submit this job to beaker instead of running locally")
    parser.add_argument("--beaker_workspace", help="Beaker workspace to submit to", default="ai2/olmocr")
    parser.add_argument(
        "--beaker_cluster",
        help="Beaker clusters you want to run on",
        default=["ai2/jupiter-cirrascale-2", "ai2/ceres-cirrascale", "ai2/neptune-cirrascale", "ai2/saturn-cirrascale", "ai2/augusta-google-1"],
    )
    parser.add_argument("--beaker_gpus", type=int, default=1, help="Number of gpu replicas to run")
    parser.add_argument("--beaker_priority", type=str, default="normal", help="Beaker priority level for the job")
    parser.add_argument("--port", type=int, default=30024, help="Port to use for the SGLang server")
    args = parser.parse_args()

    # Set up Beaker environment if needed
    await setup_beaker_environment()

    # Create and initialize pipeline orchestrator
    orchestrator = create_pipeline_orchestrator()
    await orchestrator.initialize(args)

    # Create work queue and populate if needed
    work_queue = await populate_work_queue(args, orchestrator)

    # Handle special modes
    if args.stats:
        await handle_stats_printing(args, work_queue)
        return

    if args.beaker:
        await handle_beaker_submission(args)
        return

    logger.info(f"Starting pipeline with PID {os.getpid()}")

    # Download the model before you do anything else
    model_name_or_path = await orchestrator.download_model(args.model)

    # Initialize the work queue
    qsize = await work_queue.initialize_queue()

    if qsize == 0:
        logger.info("No work to do, exiting")
        return

    # Create a semaphore to control worker access
    semaphore = asyncio.Semaphore(1)

    # Start SGLang server
    sglang_server = await orchestrator.start_sglang_server(model_name_or_path, args)
    await orchestrator.wait_for_sglang_ready(args.port)

    # Start metrics reporter
    metrics_task = await orchestrator.start_metrics_reporter(work_queue)

    # Start worker tasks
    worker_tasks = await orchestrator.start_workers(args, work_queue, semaphore)

    try:
        # Wait for all worker tasks to finish
        await asyncio.gather(*worker_tasks)
    finally:
        # Clean up
        orchestrator.cleanup()
        sglang_server.cancel()
        metrics_task.cancel()
        logger.info("Work done")


if __name__ == "__main__":
    asyncio.run(main())
