import argparse
import asyncio
import atexit
import base64
import datetime
import hashlib
import json
import logging
import multiprocessing
import os
import random
import re
import shutil
import ssl
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import cache
from io import BytesIO
from urllib.parse import urlparse

import boto3
import httpx
from botocore.exceptions import ClientError
from huggingface_hub import snapshot_download
from PIL import Image
from pypdf import PdfReader
from tqdm import tqdm

from olmocr.check import (
    check_poppler_version,
    check_torch_gpu_available,
)
from olmocr.data.renderpdf import render_pdf_to_base64png
from olmocr.filter.filter import Language, PdfFilter
from olmocr.image_utils import convert_image_to_pdf_bytes, is_jpeg, is_png
from olmocr.metrics import MetricsKeeper, WorkerTracker
from olmocr.prompts import PageResponse, build_no_anchoring_v4_yaml_prompt
from olmocr.prompts.anchor import get_anchor_text
from olmocr.s3_utils import (
    download_directory,
    download_zstd_csv,
    expand_s3_glob,
    get_s3_bytes,
    get_s3_bytes_with_backoff,
    parse_s3_path,
)
from olmocr.train.dataloader import FrontMatterParser
from olmocr.version import VERSION
from olmocr.work_queue import LocalBackend, S3Backend, WorkQueue

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False

server_logger = logging.getLogger("vllm")
server_logger.propagate = False

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Add console handler to loggers (file handler added later if disk logging enabled)
logger.addHandler(console_handler)
server_logger.addHandler(console_handler)

# Quiet logs from pypdf
logging.getLogger("pypdf").setLevel(logging.ERROR)

# Global s3 clients fo the whole script, we have two separate ones in case your workspace and your pdfs are in different accounts
workspace_s3 = boto3.client("s3")
pdf_s3 = boto3.client("s3")

# Global variables for token statistics
metrics = MetricsKeeper(window=60 * 5)
tracker = WorkerTracker()

# Global variable for vLLM queue status (updated by vllm_server_task)
vllm_queued_requests = None

# Temperature values for retry attempts - higher temperature helps overcome repetition issues
TEMPERATURE_BY_ATTEMPT = [0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 0.9, 1.0]

pdf_render_max_workers_limit = asyncio.BoundedSemaphore(int(float(os.environ.get("BEAKER_ASSIGNED_CPU_COUNT", max(1, multiprocessing.cpu_count() - 2)))))
max_concurrent_requests_limit = asyncio.BoundedSemaphore(1)  # Actual value set by args in main()

# Filter object, cached so it will only get loaded when/if you need it
get_pdf_filter = cache(lambda: PdfFilter(languages_to_keep={Language.ENGLISH, None}, apply_download_spam_check=True, apply_form_check=True))


@dataclass(frozen=True)
class PageResult:
    s3_path: str
    page_num: int
    response: PageResponse

    input_tokens: int
    output_tokens: int
    is_fallback: bool
    is_valid: bool


async def build_page_query(local_pdf_path: str, page: int, target_longest_image_dim: int, image_rotation: int = 0, model_name: str = "olmocr") -> dict:
    MAX_TOKENS = 8000
    assert image_rotation in [0, 90, 180, 270], "Invalid image rotation provided in build_page_query"

    # Allow the page rendering to process in the background, but limit the number of workers otherwise you can overload the system
    async with pdf_render_max_workers_limit:
        image_base64 = await asyncio.to_thread(render_pdf_to_base64png, local_pdf_path, page, target_longest_image_dim=target_longest_image_dim)

    if image_rotation != 0:
        image_bytes = base64.b64decode(image_base64)
        with Image.open(BytesIO(image_bytes)) as img:
            if image_rotation == 90:
                tranpose = Image.Transpose.ROTATE_90
            elif image_rotation == 180:
                tranpose = Image.Transpose.ROTATE_180
            else:
                tranpose = Image.Transpose.ROTATE_270

            rotated_img = img.transpose(tranpose)

            # Save the rotated image to a bytes buffer
            buffered = BytesIO()
            rotated_img.save(buffered, format="PNG")

        # Encode the rotated image back to base64
        image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_no_anchoring_v4_yaml_prompt()},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,  # This will get overridden later
    }


async def try_single_page(
    args,
    pdf_orig_path: str,
    pdf_local_path: str,
    page_num: int,
    attempt: int,
    rotation: int,
) -> PageResult | None:
    """
    Try processing a single page once. Returns PageResult on success, None on failure.
    Does NOT handle retries - caller is responsible for retry logic.
    """
    COMPLETION_URL = f"{args.server.rstrip('/')}/chat/completions"
    MODEL_MAX_CONTEXT = 16384

    temp_idx = min(attempt, len(TEMPERATURE_BY_ATTEMPT) - 1)
    temperature = TEMPERATURE_BY_ATTEMPT[temp_idx]

    api_key = args.api_key if args.server and hasattr(args, "api_key") else None

    try:
        query = await build_page_query(
            pdf_local_path,
            page_num,
            args.target_longest_image_dim,
            image_rotation=rotation,
            model_name=args.model,
        )
        query["temperature"] = temperature

        if args.guided_decoding:
            query["guided_regex"] = (
                r"---\nprimary_language: (?:[a-z]{2}|null)\nis_rotation_valid: (?:True|False|true|false)\nrotation_correction: (?:0|90|180|270)\nis_table: (?:True|False|true|false)\nis_diagram: (?:True|False|true|false)\n(?:---|---\n[\s\S]+)"
            )

        async with max_concurrent_requests_limit:
            status_code, response_body = await apost(COMPLETION_URL, json_data=query, api_key=api_key)

        if status_code != 200:
            return None

        base_response_data = json.loads(response_body)

        metrics.add_metrics(
            server_input_tokens=base_response_data["usage"].get("prompt_tokens", 0),
            server_output_tokens=base_response_data["usage"].get("completion_tokens", 0),
        )

        is_valid = True

        if base_response_data["usage"]["total_tokens"] > MODEL_MAX_CONTEXT:
            is_valid = False

        if base_response_data["choices"][0]["finish_reason"] != "stop":
            is_valid = False

        model_response_markdown = base_response_data["choices"][0]["message"]["content"]
        parser = FrontMatterParser(front_matter_class=PageResponse)
        front_matter, text = parser._extract_front_matter_and_text(model_response_markdown)
        page_response = parser._parse_front_matter(front_matter, text)

        return PageResult(
            pdf_orig_path,
            page_num,
            page_response,
            input_tokens=base_response_data["usage"].get("prompt_tokens", 0),
            output_tokens=base_response_data["usage"].get("completion_tokens", 0),
            is_fallback=False,
            is_valid=is_valid,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return None


def make_fallback_result(pdf_orig_path: str, pdf_local_path: str, page_num: int) -> PageResult:
    """Create a fallback PageResult using pdftotext."""
    return PageResult(
        pdf_orig_path,
        page_num,
        PageResponse(
            natural_text=get_anchor_text(pdf_local_path, page_num, pdf_engine="pdftotext"),
            primary_language=None,
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        ),
        input_tokens=0,
        output_tokens=0,
        is_fallback=True,
        is_valid=True,
    )


async def process_page(args, worker_id: int, pdf_orig_path: str, pdf_local_path: str, page_num: int) -> PageResult:
    """
    Process a single page with retry logic:
    1. Try first attempt
    2. If success: return result
    3. If rotation error: retry sequentially (need model feedback for rotation correction)
    4. If other error: race sequential retries against parallel retries that fire when queue empties
    """
    MAX_RETRIES = args.max_page_retries
    retry_attempts = list(range(1, MAX_RETRIES))
    cumulative_rotation = 0

    await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "started")

    # === First attempt ===
    result = await try_single_page(args, pdf_orig_path, pdf_local_path, page_num, attempt=0, rotation=cumulative_rotation)

    if result is not None and not result.response.is_rotation_valid:
        cumulative_rotation = result.response.rotation_correction % 360

    # Success on first try
    if result is not None and result.is_valid and result.response.is_rotation_valid:
        metrics.add_metrics(**{"completed_pages": 1, "finished_on_attempt_0": 1})
        await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "finished")
        return result

    # === Rotation error path: sequential retries with model feedback ===
    if result is not None and not result.response.is_rotation_valid:
        logger.info(f"Rotation error for {pdf_orig_path}-{page_num}, retrying sequentially with rotation={cumulative_rotation}")

        for attempt in retry_attempts:
            result = await try_single_page(args, pdf_orig_path, pdf_local_path, page_num, attempt, cumulative_rotation)

            if result is not None and result.is_valid and result.response.is_rotation_valid:
                metrics.add_metrics(**{"completed_pages": 1, f"finished_on_attempt_{attempt}": 1})
                await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "finished")
                return result

            if result is not None:  # Another rotation correction needed
                cumulative_rotation = (cumulative_rotation + result.response.rotation_correction) % 360

        # If you tried many times and all rotations were invalid, but you at least had a valid response, then return that in the end
        if result is not None and result.is_valid:
            metrics.add_metrics(**{"completed_pages": 1, f"finished_on_attempt_{MAX_RETRIES}": 1})
            await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "finished")
            return result

        # Otherwise you can do a full fallback
        logger.error(f"Failed {pdf_orig_path}-{page_num} after {MAX_RETRIES} rotation retries")
        metrics.add_metrics(failed_pages=1)
        await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "errored")
        return make_fallback_result(pdf_orig_path, pdf_local_path, page_num)

    # === Non-rotation error path: race sequential retries vs parallel-on-empty ===
    winner: PageResult | None = None
    last_valid: PageResult | None = None  # Track any valid result, even if rotation_valid is false
    done = asyncio.Event()

    async def sequential_retries():
        nonlocal winner, last_valid, cumulative_rotation
        for attempt in retry_attempts:
            if done.is_set():
                return
            r = await try_single_page(args, pdf_orig_path, pdf_local_path, page_num, attempt, cumulative_rotation)
            if done.is_set():
                return
            if r is not None and r.is_valid:
                last_valid = r
                cumulative_rotation = (cumulative_rotation + r.response.rotation_correction) % 360
            if r is not None and r.is_valid and r.response.is_rotation_valid:
                winner = r
                done.set()
                return

    async def parallel_when_queue_empty():
        nonlocal winner, last_valid, cumulative_rotation
        # Wait for queue to empty
        while not done.is_set() and vllm_queued_requests != 0:
            await asyncio.sleep(1)

        if done.is_set():
            return

        logger.info(f"Queue empty, firing {len(retry_attempts)} parallel retries for {pdf_orig_path}-{page_num}")

        # Fire all retries in parallel
        tasks = [
            asyncio.create_task(try_single_page(args, pdf_orig_path, pdf_local_path, page_num, a, cumulative_rotation))
            for a in retry_attempts
        ]
        try:
            for coro in asyncio.as_completed(tasks):
                if done.is_set():
                    break
                r = await coro
                if r is not None and r.is_valid:
                    last_valid = r
                if r is not None and r.is_valid and r.response.is_rotation_valid:
                    winner = r
                    done.set()
                    break
        finally:
            for t in tasks:
                t.cancel()

    await asyncio.gather(sequential_retries(), parallel_when_queue_empty())

    if winner:
        metrics.add_metrics(**{"completed_pages": 1, "finished_on_retry": 1})
        await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "finished")
        return winner

    # No perfect result, but return a valid one if we have it (even with wrong rotation)
    if last_valid:
        metrics.add_metrics(**{"completed_pages": 1, "finished_on_retry": 1})
        await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "finished")
        return last_valid

    # All retries exhausted with no valid results
    logger.error(f"Failed {pdf_orig_path}-{page_num} after {MAX_RETRIES} attempts")
    metrics.add_metrics(failed_pages=1)
    await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "errored")
    return make_fallback_result(pdf_orig_path, pdf_local_path, page_num)


# Manual simple implementation of HTTP Post
# It feels strange perhaps, but httpx and aiohttp are very complex beasts
# Ex. the sessionpool in httpcore has 4 different locks in it, and I've noticed
# that at the scale of 100M+ requests, that they deadlock in different strange ways
async def apost(url, json_data, api_key=None):
    parsed_url = urlparse(url)
    host = parsed_url.hostname
    # Default to 443 for HTTPS, 80 for HTTP
    if parsed_url.scheme == "https":
        port = parsed_url.port or 443
        use_ssl = True
    else:
        port = parsed_url.port or 80
        use_ssl = False
    path = parsed_url.path or "/"

    writer = None
    try:
        if use_ssl:
            ssl_context = ssl.create_default_context()
            reader, writer = await asyncio.open_connection(host, port, ssl=ssl_context)
        else:
            reader, writer = await asyncio.open_connection(host, port)

        json_payload = json.dumps(json_data)

        headers = [
            f"POST {path} HTTP/1.1",
            f"Host: {host}",
            f"Content-Type: application/json",
            f"Content-Length: {len(json_payload)}",
        ]

        if api_key:
            headers.append(f"Authorization: Bearer {api_key}")

        headers.append("Connection: close")

        request = "\r\n".join(headers) + "\r\n\r\n" + json_payload
        writer.write(request.encode())
        await writer.drain()

        status_line = await reader.readline()
        if not status_line:
            raise ConnectionError("No response from server")
        status_parts = status_line.decode().strip().split(" ", 2)
        if len(status_parts) < 2:
            raise ValueError(f"Malformed status line: {status_line.decode().strip()}")
        status_code = int(status_parts[1])

        # Read headers
        headers = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            key, _, value = line.decode().partition(":")
            headers[key.strip().lower()] = value.strip()

        # Read response body
        if "content-length" in headers:
            body_length = int(headers["content-length"])
            response_body = await reader.readexactly(body_length)
        elif headers.get("transfer-encoding", "") == "chunked":
            chunks = []
            while True:
                # Read chunk size line
                size_line = await reader.readline()
                chunk_size = int(size_line.strip(), 16)  # Hex format

                if chunk_size == 0:
                    await reader.readline()  # Read final CRLF
                    break

                chunk_data = await reader.readexactly(chunk_size)
                chunks.append(chunk_data)

                # Read trailing CRLF after chunk data
                await reader.readline()

            response_body = b"".join(chunks)
        elif headers.get("connection", "") == "close":
            # Read until connection closes
            response_body = await reader.read()
        else:
            raise ConnectionError("Cannot determine response body length")

        return status_code, response_body
    except Exception as e:
        # Pass through errors
        raise e
    finally:
        # But just make sure to close the socket on your way out
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass


def is_tarball_path(path: str) -> bool:
    """Check if a path is a tarball based on extension."""
    lower = path.lower()
    return lower.endswith(".tar.gz") or lower.endswith(".tgz")


async def process_tarball(args, worker_id: int, tarball_path: str) -> list:
    """Process all PDFs inside a tarball concurrently and return list of Dolma documents."""
    logger.info(f"Worker {worker_id} processing tarball {tarball_path}")

    tarball_bytes = await asyncio.to_thread(lambda: get_s3_bytes_with_backoff(pdf_s3, tarball_path))

    # Extract all PDFs to a temp directory
    temp_dir = tempfile.mkdtemp()
    try:
        pdf_files = []  # (source_path, local_path)
        with tarfile.open(fileobj=BytesIO(tarball_bytes), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.lower().endswith(".pdf"):
                    local_path = os.path.join(temp_dir, os.path.basename(member.name))
                    with open(local_path, "wb") as f:
                        extracted = tar.extractfile(member)
                        if extracted:
                            f.write(extracted.read())
                            pdf_files.append((f"{tarball_path}::{member.name}", local_path))

        logger.info(f"Worker {worker_id} extracted {len(pdf_files)} PDFs from {tarball_path}")

        # Process all PDFs concurrently
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(process_single_pdf(args, worker_id, src, local)) for src, local in pdf_files]

        dolma_docs = [t.result() for t in tasks if t.result() is not None]
        logger.info(f"Worker {worker_id} processed {len(dolma_docs)} PDFs from tarball {tarball_path}")
        return dolma_docs
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def process_single_pdf(args, worker_id: int, pdf_orig_path: str, local_pdf_path: str):
    """Process a single PDF that's already on disk.

    Args:
        args: Pipeline arguments
        worker_id: Worker ID for logging
        pdf_orig_path: Original path (for metadata, can be tarball::internal format)
        local_pdf_path: Local path to the PDF file

    Returns:
        Dolma document or None
    """
    try:
        try:
            reader = PdfReader(local_pdf_path)
            num_pages = reader.get_num_pages()
        except:
            logger.exception(f"Could not count number of pages for {pdf_orig_path}, aborting document")
            return None

        logger.debug(f"Got {num_pages} pages to do for {pdf_orig_path} in worker {worker_id}")

        if args.apply_filter and get_pdf_filter().filter_out_pdf(local_pdf_path):
            logger.info(f"Filtering out pdf {pdf_orig_path}")
            return None

        # List to hold the tasks for processing each page
        page_tasks = []
        page_results = []

        async with asyncio.TaskGroup() as tg:
            for page_num in range(1, num_pages + 1):
                task = tg.create_task(process_page(args, worker_id, pdf_orig_path, local_pdf_path, page_num))
                page_tasks.append(task)

        # Collect the results from the entire task group, assuming no exceptions, if there is an exception propagated to this point in any page, it will abort the PDF itself
        page_results = [task.result() for task in page_tasks]
        assert all(page_result.is_valid for page_result in page_results)

        num_fallback_pages = sum(page_result.is_fallback for page_result in page_results)

        if num_fallback_pages / num_pages > args.max_page_error_rate:
            logger.error(
                f"Document {pdf_orig_path} has {num_fallback_pages} fallback pages out of {num_pages} exceeding max_page_error_rate of {args.max_page_error_rate}, discarding document."
            )
            return None
        elif num_fallback_pages > 0:
            logger.warning(
                f"Document {pdf_orig_path} processed with {num_fallback_pages} fallback pages out of {num_pages}, proceeding to build Dolma document."
            )

        return build_dolma_document(pdf_orig_path, page_results)
    except Exception as e:
        logger.exception(f"Exception in process_single_pdf for {pdf_orig_path}: {e}")
        return None


async def process_pdf(args, worker_id: int, pdf_orig_path: str):
    """Process a single PDF from S3/local path and return a Dolma document."""
    with tempfile.NamedTemporaryFile("wb+", suffix=".pdf", delete=False) as tf:
        try:
            data = await asyncio.to_thread(lambda: get_s3_bytes_with_backoff(pdf_s3, pdf_orig_path))
            tf.write(data)
            tf.flush()
        except ClientError as ex:
            if ex.response["Error"]["Code"] == "NoSuchKey":
                logger.info(f"S3 File Not found, skipping it completely {pdf_orig_path}")
                return None
            else:
                raise

        if is_png(tf.name) or is_jpeg(tf.name):
            logger.info(f"Converting {pdf_orig_path} from image to PDF format...")
            tf.seek(0)
            tf.write(convert_image_to_pdf_bytes(tf.name))
            tf.flush()

    try:
        return await process_single_pdf(args, worker_id, pdf_orig_path, tf.name)
    finally:
        if os.path.exists(tf.name):
            os.unlink(tf.name)


def build_dolma_document(pdf_orig_path, page_results):
    # Build the document text and page spans
    document_text = ""
    pdf_page_spans = []
    current_char_pos = 0

    for index, page_result in enumerate(page_results):
        if page_result.response.natural_text is not None:
            content = page_result.response.natural_text + ("\n" if index < len(page_results) - 1 else "")
        else:
            content = ""

        start_pos = current_char_pos
        document_text += content
        current_char_pos = len(document_text)
        pdf_page_spans.append([start_pos, current_char_pos, page_result.page_num])

    if not document_text:
        logger.info(f"No document text for {pdf_orig_path}")
        return None  # Return None if the document text is empty

    # Build the Dolma document
    metadata = {
        "Source-File": pdf_orig_path,
        "olmocr-version": VERSION,
        "pdf-total-pages": len(page_results),
        "total-input-tokens": sum(page.input_tokens for page in page_results),
        "total-output-tokens": sum(page.output_tokens for page in page_results),
        "total-fallback-pages": sum(page.is_fallback for page in page_results),
    }

    id_ = hashlib.sha1(document_text.encode()).hexdigest()

    dolma_doc = {
        "id": id_,
        "text": document_text,
        "source": "olmocr",
        "added": datetime.datetime.now().strftime("%Y-%m-%d"),
        "created": datetime.datetime.now().strftime("%Y-%m-%d"),
        "metadata": metadata,
        "attributes": {
            "pdf_page_numbers": pdf_page_spans,
            "primary_language": [p.response.primary_language for p in page_results],
            "is_rotation_valid": [p.response.is_rotation_valid for p in page_results],
            "rotation_correction": [p.response.rotation_correction for p in page_results],
            "is_table": [p.response.is_table for p in page_results],
            "is_diagram": [p.response.is_diagram for p in page_results],
        },
    }
    return dolma_doc


def get_markdown_path(workspace: str, source_file: str) -> str:
    """
    Calculate the markdown output path for a given source file.

    Args:
        workspace: The workspace directory path
        source_file: The original source file path (can be S3, local, or tarball::internal_path)

    Returns:
        The full path where the markdown file should be written
    """
    # Handle tarball paths (format: tarball_path::internal_path)
    if "::" in source_file:
        tarball_path, internal_path = source_file.split("::", 1)
        # Use tarball basename + internal path structure
        tarball_basename = os.path.splitext(os.path.basename(tarball_path))[0]
        if tarball_basename.endswith(".tar"):
            tarball_basename = tarball_basename[:-4]
        relative_path = os.path.join(tarball_basename, internal_path)
    elif source_file.startswith("s3://"):
        # Extract the path after the bucket name for S3 sources
        parsed = urlparse(source_file)
        relative_path = parsed.path.lstrip("/")
    else:
        # For local files, strip leading slash to make it relative
        relative_path = source_file.lstrip("/")

    # Sanitize path: remove any .. components to prevent path traversal
    parts = relative_path.split("/")
    safe_parts = [p for p in parts if p and p != ".."]
    relative_path = "/".join(safe_parts)

    # Change the extension to .md
    md_filename = os.path.splitext(os.path.basename(relative_path))[0] + ".md"
    # Get the directory path without the filename
    dir_path = os.path.dirname(relative_path)

    # Create the output markdown path
    markdown_dir = os.path.join(workspace, "markdown", dir_path)
    markdown_path = os.path.join(markdown_dir, md_filename)

    return markdown_path


async def worker(args, work_queue: WorkQueue, worker_id):
    while True:

        work_item = await work_queue.get_work()

        if work_item is None:
            logger.info(f"Worker {worker_id} exiting due to empty queue")
            break

        logger.info(f"Worker {worker_id} processing work item {work_item.hash}")
        await tracker.clear_work(worker_id)

        try:
            async with asyncio.TaskGroup() as tg:
                dolma_tasks = []
                for path in work_item.work_paths:
                    if is_tarball_path(path):
                        # Tarball returns a list of docs, so we handle it specially
                        dolma_tasks.append(tg.create_task(process_tarball(args, worker_id, path)))
                    else:
                        dolma_tasks.append(tg.create_task(process_pdf(args, worker_id, path)))
                logger.info(f"Created all tasks for {work_item.hash}")

            logger.info(f"Finished TaskGroup for worker on {work_item.hash}")

            dolma_docs = []
            for task in dolma_tasks:
                try:
                    result = task.result()
                except:
                    # some dolma doc creations may have failed
                    result = None

                if result is None:
                    continue
                # process_tarball returns a list, process_pdf returns a single doc
                if isinstance(result, list):
                    dolma_docs.extend(result)
                else:
                    dolma_docs.append(result)

            logger.info(f"Got {len(dolma_docs)} docs for {work_item.hash}")

            # Write the Dolma documents to a local temporary file in JSONL format
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tf:
                for doc in dolma_docs:
                    tf.write(json.dumps(doc))
                    tf.write("\n")
                tf.flush()
                temp_path = tf.name

            try:
                # Define the output S3 path using the work_hash
                output_final_path = os.path.join(args.workspace, "results", f"output_{work_item.hash}.jsonl")

                if output_final_path.startswith("s3://"):
                    bucket, key = parse_s3_path(output_final_path)
                    workspace_s3.upload_file(temp_path, bucket, key)
                else:
                    # Ensure the results directory exists for local workspace
                    os.makedirs(os.path.dirname(output_final_path), exist_ok=True)
                    shutil.copyfile(temp_path, output_final_path)
            finally:
                # Clean up the temporary file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

            # If --markdown flag is set, also write the natural text to markdown files
            if args.markdown:
                logger.info(f"Writing {len(dolma_docs)} markdown files for {work_item.hash}")
                for doc in dolma_docs:
                    source_file = doc["metadata"]["Source-File"]
                    natural_text = doc["text"]

                    markdown_path = get_markdown_path(args.workspace, source_file)
                    markdown_dir = os.path.dirname(markdown_path)

                    # Create the directory structure if it doesn't exist
                    if markdown_path.startswith("s3://"):
                        # For S3 paths, we'll create a temporary file and upload it
                        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as md_tf:
                            md_tf.write(natural_text)
                            md_tf.flush()
                            md_temp_path = md_tf.name

                        try:
                            md_bucket, md_key = parse_s3_path(markdown_path)
                            workspace_s3.upload_file(md_temp_path, md_bucket, md_key)
                        finally:
                            # Make sure to clean up the temporary file even if upload fails
                            if os.path.exists(md_temp_path):
                                os.unlink(md_temp_path)
                    else:
                        # For local paths, create the directory structure and write the file
                        os.makedirs(markdown_dir, exist_ok=True)
                        with open(markdown_path, "w") as md_f:
                            md_f.write(natural_text)

            # Update finished token counts from successful documents
            metrics.add_metrics(
                finished_input_tokens=sum(doc["metadata"]["total-input-tokens"] for doc in dolma_docs),
                finished_output_tokens=sum(doc["metadata"]["total-output-tokens"] for doc in dolma_docs),
            )

            await work_queue.mark_done(work_item)
        except Exception as e:
            logger.exception(f"Exception occurred while processing work_hash {work_item.hash}: {e}")


async def vllm_server_task(model_name_or_path, args, unknown_args=None):
    cmd = [
        "vllm",
        "serve",
        model_name_or_path,
        "--port",
        str(args.port),
        "--disable-log-requests",
        "--uvicorn-log-level",
        "warning",
        "--served-model-name",
        "olmocr",
        "--tensor-parallel-size",
        str(args.tensor_parallel_size),
        "--data-parallel-size",
        str(args.data_parallel_size),
        "--limit-mm-per-prompt",
        '{"video": 0}',  # Disabling video encoder saves RAM that you can put towards the KV cache, thanks @charitarthchugh
    ]

    if args.gpu_memory_utilization is not None:
        cmd.extend(["--gpu-memory-utilization", str(args.gpu_memory_utilization)])

    if args.max_model_len is not None:
        cmd.extend(["--max-model-len", str(args.max_model_len)])

    if unknown_args:
        cmd.extend(unknown_args)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # OMP_NUM_THREADS needs to be 1, otherwise you could have contention if you are running multiple copies of olmOCR on a machine with several GPUS
        env={**os.environ, "OMP_NUM_THREADS": "1"},
    )

    # Ensure the subprocess is terminated on exit
    def _kill_proc():
        try:
            proc.terminate()
        except:
            logger.info("VLLM Process already terminated")

    atexit.register(_kill_proc)

    # Shared variables between tasks
    last_running_req, peak_running_req, last_queue_req = 0, 0, 0
    server_printed_ready_message = False

    async def process_line(line):
        nonlocal last_running_req, last_queue_req, peak_running_req, server_printed_ready_message
        server_logger.info(line)

        if "Detected errors during sampling" in line:
            logger.error("Cannot continue, sampling errors detected, model is probably corrupt")
            sys.exit(1)

        if not server_printed_ready_message and ("The server is fired up and ready to roll!" in line or "Starting vLLM API server" in line):
            server_printed_ready_message = True

        if match := re.search(r"Running: (\d+)", line):
            current_running = int(match.group(1))
            # Track peak running requests
            if current_running > peak_running_req:
                peak_running_req = current_running
                logger.info(f"New peak running requests: {peak_running_req}")
            last_running_req = current_running

        if match := re.search(r"(?:Waiting|Pending):\s*(\d+)", line):
            global vllm_queued_requests
            last_queue_req = int(match.group(1))
            vllm_queued_requests = last_queue_req
            logger.info(f"vllm running req: {last_running_req} queue req: {last_queue_req}")

    async def read_stream(stream):
        while True:
            line = await stream.readline()
            if not line:
                break
            try:
                line = line.decode("utf-8").rstrip()
                await process_line(line)
            except Exception as ex:
                logger.warning(f"Got {ex} when reading log line from inference server, skipping")

    # Start tasks to read stdout, stderr, and handle timeout logic
    stdout_task = asyncio.create_task(read_stream(proc.stdout))
    stderr_task = asyncio.create_task(read_stream(proc.stderr))

    try:
        await proc.wait()
    except asyncio.CancelledError:
        logger.info("Got cancellation request for VLLM server")
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("VLLM server did not terminate within 10 seconds")
        raise

    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)


async def vllm_server_host(model_name_or_path, args, unknown_args=None):
    MAX_RETRIES = 5
    retry = 0

    while retry < MAX_RETRIES:
        await vllm_server_task(model_name_or_path, args, unknown_args)
        logger.warning("VLLM server task ended")
        retry += 1

    if retry >= MAX_RETRIES:
        logger.error(f"Ended up starting the vllm server more than {retry} times, cancelling pipeline")
        logger.error("")
        logger.error(
            "Please make sure vllm is installed according to the latest instructions here: https://docs.vllm.ai/en/stable/getting_started/installation/gpu.html"
        )
        sys.exit(1)


async def vllm_server_ready(args):
    max_attempts = args.max_server_ready_timeout
    delay_sec = 1
    url = f"{args.server.rstrip('/')}/models"

    for attempt in range(1, max_attempts + 1):
        try:
            headers = {}
            if args.server and hasattr(args, "api_key") and args.api_key:
                headers["Authorization"] = f"Bearer {args.api_key}"

            async with httpx.AsyncClient() as session:
                response = await session.get(url, headers=headers)

                if response.status_code == 200:
                    logger.info("vllm server is ready.")
                    return
                else:
                    logger.info(f"Attempt {attempt}: Unexpected status code {response.status_code}")
        except Exception:
            logger.warning(f"Attempt {attempt}: Please wait for vllm server to become ready...")

        await asyncio.sleep(delay_sec)

    raise Exception("vllm server did not become ready after waiting.")


async def download_model(model_name_or_path: str, max_retries: int = 5):
    for retry in range(max_retries):
        try:
            if model_name_or_path.startswith("s3://") or model_name_or_path.startswith("gs://") or model_name_or_path.startswith("weka://"):
                logger.info(f"Downloading model directory from '{model_name_or_path}'")
                model_cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "olmocr", "model")
                # Delete existing model cache directory if it exists
                if os.path.exists(model_cache_dir):
                    shutil.rmtree(model_cache_dir)
                download_directory([model_name_or_path], model_cache_dir)
                return model_cache_dir
            elif os.path.isabs(model_name_or_path) and os.path.isdir(model_name_or_path):
                logger.info(f"Using local model path at '{model_name_or_path}'")
                return model_name_or_path
            else:
                logger.info(f"Downloading model with hugging face '{model_name_or_path}'")
                snapshot_download(repo_id=model_name_or_path)
                return model_name_or_path
        except Exception:
            if retry == max_retries - 1:
                raise  # Raise on final attempt and fail the job

            sleep_time = random.randrange(2, 20) * 2**retry
            logger.exception(f"Could not download model, sleeping for {sleep_time} seconds to retry ({retry + 1}/{max_retries})")
            await asyncio.sleep(random.randrange(10, 30) * 2**retry)


async def metrics_reporter(work_queue):
    while True:
        # Leading newlines preserve table formatting in logs
        logger.info(f"Queue remaining: {work_queue.size}")
        logger.info("\n" + str(metrics))
        logger.info("\n" + str(await tracker.get_status_table()))
        await asyncio.sleep(10)


def submit_beaker_job(args):
    from beaker import (  # type: ignore
        Beaker,
        Constraints,
        EnvVar,
        ExperimentSpec,
        ImageSource,
        Priority,
        ResultSpec,
        RetrySpec,
        SecretNotFound,
        TaskContext,
        TaskResources,
        TaskSpec,
    )

    b = Beaker.from_env(default_workspace=args.beaker_workspace)
    account = b.account.whoami()
    owner = account.name
    beaker_image = f"jakep/olmocr-inference-{VERSION}"

    task_name = f"olmocr-{os.path.basename(args.workspace.rstrip('/'))}"

    # Take out --beaker flag so the workers will just run things
    args_list = [arg for arg in sys.argv[1:] if arg != "--beaker"]

    # Take out the --pdfs [arg] or --pdfs=[arg], since the queue is populated locally
    args_list = [arg for i, arg in enumerate(args_list) if not (arg.startswith("--pdfs") or (i > 0 and args_list[i - 1] == "--pdfs"))]

    try:
        b.secret.get(f"{owner}-WEKA_ACCESS_KEY_ID", args.beaker_workspace)
        b.secret.get(f"{owner}-WEKA_SECRET_ACCESS_KEY", args.beaker_workspace)
        b.secret.get(f"{owner}-AWS_CREDENTIALS_FILE", args.beaker_workspace)
    except SecretNotFound:
        print(
            f"Expected beaker secrets for accessing Weka and S3 are not found. Are you okay to write those to your beaker workspace {args.beaker_workspace}? [y/n]"
        )

        if input().strip().lower() != "y":
            print("Exiting...")
            sys.exit(1)

        b.secret.write(f"{owner}-WEKA_ACCESS_KEY_ID", os.environ.get("WEKA_ACCESS_KEY_ID", ""), args.beaker_workspace)
        b.secret.write(f"{owner}-WEKA_SECRET_ACCESS_KEY", os.environ.get("WEKA_SECRET_ACCESS_KEY", ""), args.beaker_workspace)
        b.secret.write(
            f"{owner}-AWS_CREDENTIALS_FILE",
            open(os.path.join(os.path.expanduser("~"), ".aws", "credentials")).read(),
            args.beaker_workspace,
        )

    env_var_secrets = [
        EnvVar(name="WEKA_ACCESS_KEY_ID", secret=f"{owner}-WEKA_ACCESS_KEY_ID"),
        EnvVar(name="WEKA_SECRET_ACCESS_KEY", secret=f"{owner}-WEKA_SECRET_ACCESS_KEY"),
        EnvVar(name="AWS_CREDENTIALS_FILE", secret=f"{owner}-AWS_CREDENTIALS_FILE"),
    ]

    try:
        b.secret.get("OLMOCR_PREVIEW_HF_TOKEN", args.beaker_workspace)
        env_var_secrets.append(EnvVar(name="HF_TOKEN", secret="OLMOCR_PREVIEW_HF_TOKEN"))
    except SecretNotFound:
        pass

    try:
        b.secret.get("OE_DATA_GCS_SA_KEY", args.beaker_workspace)
        env_var_secrets.append(EnvVar(name="GOOGLE_APPLICATION_CREDENTIALS_FILE", secret="OE_DATA_GCS_SA_KEY"))
    except SecretNotFound:
        print("Input the olmo-gcs SA key if you would like to load weights from gcs (end with a double newline):")
        lines = []
        prev_empty = False
        for line in iter(input, None):
            if not line and prev_empty:
                break
            prev_empty = not line
            lines.append(line)
        gcs_sa_key = "\n".join(lines[:-1]).strip()  # Remove the last empty line
        if gcs_sa_key:
            b.secret.write("OE_DATA_GCS_SA_KEY", gcs_sa_key, args.beaker_workspace)
            env_var_secrets.append(EnvVar(name="GOOGLE_APPLICATION_CREDENTIALS_FILE", secret="OE_DATA_GCS_SA_KEY"))

    # Create the experiment spec
    experiment_spec = ExperimentSpec(
        budget="ai2/oe-base",
        description=task_name,
        tasks=[
            TaskSpec(
                name=task_name,
                propagate_failure=False,
                propagate_preemption=False,
                replicas=args.beaker_gpus,
                context=TaskContext(
                    priority=Priority(args.beaker_priority),
                    preemptible=True,
                ),
                image=ImageSource(beaker=beaker_image),
                command=["python", "-m", "olmocr.pipeline"] + args_list,
                env_vars=[EnvVar(name="BEAKER_JOB_NAME", value=task_name), EnvVar(name="OWNER", value=owner), EnvVar(name="HF_HUB_OFFLINE", value="1")]
                + env_var_secrets,
                resources=TaskResources(gpu_count=1, memory="150GiB"),  # Have to set a memory limit, otherwise VLLM may use too much on its own
                constraints=Constraints(cluster=args.beaker_cluster if isinstance(args.beaker_cluster, list) else [args.beaker_cluster]),
                result=ResultSpec(path="/noop-results"),
            )
        ],
        retry=RetrySpec(allowed_task_retries=10),
    )

    experiment_data = b.experiment.create(spec=experiment_spec, workspace=args.beaker_workspace)

    print(f"Experiment URL: https://beaker.org/ex/{experiment_data.id}")


def print_stats(args, root_work_queue):
    LONG_CONTEXT_THRESHOLD = 32768
    assert args.workspace.startswith("s3://"), "Printing stats functionality only works with s3 workspaces for now."

    done_work_items = expand_s3_glob(workspace_s3, os.path.join(args.workspace, "results", "*.jsonl"))
    work_queue_lines = download_zstd_csv(workspace_s3, os.path.join(args.workspace, "work_index_list.csv.zstd"))
    work_queue = {parts[0]: parts[1:] for line in work_queue_lines if line.strip() and (parts := root_work_queue._decode_csv_row(line.strip()))}

    total_items, completed_items = len(work_queue), len(done_work_items)

    def process_output_file(s3_path):
        try:
            stats = {
                "docs": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "pages": 0,
                "fallback_pages": 0,
                "long_docs": 0,
                "long_tokens": 0,
                "en_docs": 0,
                "en_tokens": 0,
            }
            paths = set()
            for line in get_s3_bytes(workspace_s3, s3_path).decode("utf-8").splitlines():
                if not line.strip():
                    continue
                doc = json.loads(line)
                meta, attrs = doc["metadata"], doc.get("attributes", {})
                out_tokens = meta.get("total-output-tokens", 0)
                stats["docs"] += 1
                stats["input_tokens"] += meta.get("total-input-tokens", 0)
                stats["output_tokens"] += out_tokens
                stats["pages"] += meta.get("pdf-total-pages", 0)
                stats["fallback_pages"] += meta.get("total-fallback-pages", 0)
                paths.add(meta["Source-File"])
                if out_tokens > LONG_CONTEXT_THRESHOLD:
                    stats["long_docs"] += 1
                    stats["long_tokens"] += out_tokens
                langs = attrs.get("primary_language", [])
                if langs and sum(1 for ln in langs if ln == "en") > len(langs) / 2:
                    stats["en_docs"] += 1
                    stats["en_tokens"] += out_tokens
            return stats, paths
        except Exception as e:
            logger.warning(f"Error processing {s3_path}: {e}")
            return {
                k: 0 for k in ["docs", "input_tokens", "output_tokens", "pages", "fallback_pages", "long_docs", "long_tokens", "en_docs", "en_tokens"]
            }, set()

    print(f"\nCompleted work items {completed_items:,} out of {total_items:,}: {completed_items/total_items*100:.2f}%")
    print("\nProcessing output files...")

    totals = {"docs": 0, "input_tokens": 0, "output_tokens": 0, "pages": 0, "fallback_pages": 0, "long_docs": 0, "long_tokens": 0, "en_docs": 0, "en_tokens": 0}
    all_processed, original_paths = set(), set()

    for item in done_work_items:
        if (match := re.search(r"output_(\w+).jsonl", item)) and match.group(1) in work_queue:
            original_paths.update(work_queue[match.group(1)])

    with ThreadPoolExecutor() as executor:
        for stats, paths in tqdm(executor.map(process_output_file, done_work_items), total=len(done_work_items)):
            for k in totals:
                totals[k] += stats[k]
            all_processed.update(paths)

    d, p, o, c = totals["docs"], totals["pages"], totals["output_tokens"], max(1, completed_items)
    print(
        f"""
Work Items Status:
Total work items: {total_items:,}
Completed items: {completed_items:,}
Remaining items: {total_items - completed_items:,}

Results:
Total documents processed: {d:,}
Total documents skipped: {len(original_paths - all_processed):,}
Total pages on fallback: {totals['fallback_pages']:,}
Total pages processed: {p:,}

Total output tokens: {o:,}
Projected output tokens: {round(o / c * total_items):,}

Average pages per doc: {p / max(1, d):,.1f}
Average output tokens per doc: {o / max(1, d):,.1f}
Average output tokens per page: {o / max(1, p):,.1f}

Long Context Documents (>{LONG_CONTEXT_THRESHOLD} tokens): {totals['long_docs']:,}
Total tokens in long context documents: {totals['long_tokens']:,}

English-only documents (>50% pages with 'en'): {totals['en_docs']:,}
Total output tokens in English-only documents: {totals['en_tokens']:,}
Projected English-only output tokens: {round(totals['en_tokens'] / c * total_items):,}"""
    )


async def main():
    parser = argparse.ArgumentParser(description="Manager for running millions of PDFs through a batch inference pipeline.")
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
    parser.add_argument(
        "--model",
        help="Path where the model is located, allenai/olmOCR-2-7B-1025-FP8 is the default, can be local, s3, or hugging face.",
        default="allenai/olmOCR-2-7B-1025-FP8",
    )

    # More detailed config options, usually you shouldn't have to change these
    parser.add_argument("--workspace_profile", help="S3 configuration profile for accessing the workspace", default=None)
    parser.add_argument("--pdf_profile", help="S3 configuration profile for accessing the raw pdf documents", default=None)
    parser.add_argument("--pages_per_group", type=int, default=argparse.SUPPRESS, help="Aiming for this many pdf pages per work item group")
    parser.add_argument("--max_page_retries", type=int, default=8, help="Max number of times we will retry rendering a page")
    parser.add_argument("--max_page_error_rate", type=float, default=0.004, help="Rate of allowable failed pages in a document, 1/250 by default")
    parser.add_argument("--workers", type=int, default=20, help="Number of workers to run at a time")
    parser.add_argument("--max_concurrent_requests", type=int, default=1600, help="Max number of concurrent VLLM server requests at a time.")
    parser.add_argument("--max_server_ready_timeout", type=int, default=600, help="Number of seconds to wait for vllm to become ready before exiting.")
    parser.add_argument("--apply_filter", action="store_true", help="Apply basic filtering to English pdfs which are not forms, and not likely seo spam")
    parser.add_argument("--stats", action="store_true", help="Instead of running any job, reports some statistics about the current workspace")
    parser.add_argument("--markdown", action="store_true", help="Also write natural text to markdown files preserving the folder structure of the input pdfs")
    parser.add_argument("--target_longest_image_dim", type=int, help="Dimension on longest side to use for rendering the pdf pages", default=1288)
    parser.add_argument("--target_anchor_text_len", type=int, help="Maximum amount of anchor text to use (characters), not used for new models", default=-1)
    parser.add_argument("--guided_decoding", action="store_true", help="Enable guided decoding for model YAML type outputs")
    parser.add_argument(
        "--disk_logging",
        type=str,
        nargs="?",
        const="olmocr-pipeline-debug.log",
        default=None,
        help="Enable writing logs to disk, optionally specify filename (default: olmocr-pipeline-debug.log)",
    )

    server_group = parser.add_argument_group("Server arguments, to specify where your VLLM inference engine is running")
    server_group.add_argument(
        "--server",
        type=str,
        help="URL of external vLLM (or other compatible provider) server (e.g., http://hostname:port/v1). If provided, skips spawning local vLLM instance",
    )
    server_group.add_argument("--api_key", type=str, default=None, help="API key for authenticated remote servers (e.g., DeepInfra)")

    vllm_group = parser.add_argument_group(
        "VLLM arguments", "These arguments are passed to vLLM. Any unrecognized arguments are also automatically forwarded to vLLM."
    )
    vllm_group.add_argument(
        "--gpu-memory-utilization", type=float, help="Fraction of VRAM vLLM may pre-allocate for KV-cache " "(passed through to vllm serve)."
    )
    vllm_group.add_argument("--max_model_len", type=int, default=16384, help="Upper bound (tokens) vLLM will allocate KV-cache for, lower if VLLM won't start")
    vllm_group.add_argument("--tensor-parallel-size", "-tp", type=int, default=1, help="Tensor parallel size for vLLM")
    vllm_group.add_argument("--data-parallel-size", "-dp", type=int, default=1, help="Data parallel size for vLLM")
    vllm_group.add_argument("--port", type=int, default=30024, help="Port to use for the VLLM server")

    # Beaker/job running stuff
    beaker_group = parser.add_argument_group("beaker/cluster execution")
    beaker_group.add_argument("--beaker", action="store_true", help="Submit this job to beaker instead of running locally")
    beaker_group.add_argument("--beaker_workspace", help="Beaker workspace to submit to", default="ai2/olmocr")
    beaker_group.add_argument(
        "--beaker_cluster",
        help="Beaker clusters you want to run on",
        default=["ai2/jupiter", "ai2/ceres", "ai2/neptune", "ai2/saturn"],
    )
    beaker_group.add_argument("--beaker_gpus", type=int, default=1, help="Number of gpu replicas to run")
    beaker_group.add_argument("--beaker_priority", type=str, default="normal", help="Beaker priority level for the job")

    args, unknown_args = parser.parse_known_args()

    # Set up file logging if enabled
    if args.disk_logging:
        file_handler = logging.FileHandler(args.disk_logging, mode="a")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logger.addHandler(file_handler)
        server_logger.addHandler(file_handler)

    logger.info(
        "If you run out of GPU memory during start-up or get 'KV cache is larger than available memory' errors, retry with lower values, e.g. --gpu_memory_utilization 0.80  --max_model_len 16384"
    )

    use_internal_server = not args.server
    global workspace_s3, pdf_s3, max_concurrent_requests_limit

    max_concurrent_requests_limit = asyncio.BoundedSemaphore(args.max_concurrent_requests)

    # setup the job to work in beaker environment, load secrets, adjust logging, etc.
    if "BEAKER_JOB_NAME" in os.environ:
        cred_path = os.path.join(os.path.expanduser("~"), ".aws", "credentials")
        os.makedirs(os.path.dirname(cred_path), exist_ok=True)
        with open(cred_path, "w") as f:
            f.write(os.environ.get("AWS_CREDENTIALS_FILE"))
        cred_path = os.path.join(os.path.expanduser("~"), ".gcs", "credentials")
        os.makedirs(os.path.dirname(cred_path), exist_ok=True)
        with open(cred_path, "w") as f:
            f.write(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_FILE"))
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        workspace_s3 = boto3.client("s3")
        pdf_s3 = boto3.client("s3")

        # Wait a little bit so that not all beaker jobs in a task start at the same time and download the model at the same time
        replica_count = int(os.environ.get("BEAKER_REPLICA_COUNT", "1"))
        interval = 10 if (replica_count - 1) * 10 <= 30 else 30 / max(1, replica_count - 1)
        sleep_time = int(os.environ.get("BEAKER_REPLICA_RANK", "0")) * interval
        logger.info(f"Beaker job sleeping for {sleep_time} seconds to stagger model downloads")
        await asyncio.sleep(sleep_time)

    # If you specify an API key, meaning you are on a remote provider, then lower the group size default, not to overwhelm such servers
    # and not to waste money if a group doesn't finish right away
    if not hasattr(args, "pages_per_group"):
        args.pages_per_group = 50 if args.api_key is not None else 500

    if args.workspace_profile:
        workspace_session = boto3.Session(profile_name=args.workspace_profile)
        workspace_s3 = workspace_session.client("s3")

    if args.pdf_profile:
        pdf_session = boto3.Session(profile_name=args.pdf_profile)
        pdf_s3 = pdf_session.client("s3")

    # We need poppler to load the initial pdfs, even if we are not processing them here
    check_poppler_version()

    # Create work queue
    if args.workspace.startswith("s3://"):
        work_queue = WorkQueue(S3Backend(workspace_s3, args.workspace))
    else:
        work_queue = WorkQueue(LocalBackend(args.workspace))

    if args.pdfs:
        logger.info("Got --pdfs argument, going to add to the work queue")
        pdf_work_paths = set()
        tarball_paths = set()

        for pdf_path in args.pdfs:
            # Expand s3 glob paths first, then categorize results
            if pdf_path.startswith("s3://"):
                logger.info(f"Expanding s3 glob at {pdf_path}")
                expanded_paths = set(expand_s3_glob(pdf_s3, pdf_path))
                tarball_paths.update(p for p in expanded_paths if is_tarball_path(p))
                pdf_work_paths.update(p for p in expanded_paths if not is_tarball_path(p))
            elif os.path.exists(pdf_path):
                # Check if this is a tar.gz file (local)
                if is_tarball_path(pdf_path):
                    tarball_paths.add(pdf_path)
                elif (
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
                        lines = [line.strip() for line in f if line.strip()]
                    tarball_paths.update(p for p in lines if is_tarball_path(p))
                    pdf_work_paths.update(p for p in lines if not is_tarball_path(p))
                else:
                    raise ValueError(f"Unsupported file extension for {pdf_path}")
            else:
                raise ValueError("pdfs argument needs to be either a local path, an s3 path, or an s3 glob pattern...")

        logger.info(f"Found {len(pdf_work_paths):,} regular pdf paths and {len(tarball_paths):,} tarballs to add")

        # Process regular PDFs with calculated items_per_group
        if pdf_work_paths:
            # Estimate average pages per pdf
            sample_size = min(100, len(pdf_work_paths))
            sampled_pdfs = random.sample(list(pdf_work_paths), sample_size)
            page_counts = []

            for pdf in tqdm(sampled_pdfs, desc="Sampling PDFs to calculate optimal length"):
                try:
                    # Download the PDF to a temp file
                    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp_file:
                        tmp_file.write(get_s3_bytes(pdf_s3, pdf))
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

            # Now call populate_queue for regular PDFs
            await work_queue.populate_queue(list(pdf_work_paths), items_per_group)

        # Add tarballs to the queue - each tarball is one work item
        if tarball_paths:
            await work_queue.populate_queue(tarball_paths, 1)

    if args.stats:
        print_stats(args, work_queue)
        return

    if args.beaker:
        submit_beaker_job(args)
        return

    # If you get this far, then you are doing inference and need a GPU
    # check_sglang_version()
    if use_internal_server:
        check_torch_gpu_available()

    logger.info(f"Starting pipeline with PID {os.getpid()}")

    # Download the model before you do anything else
    if use_internal_server:
        model_name_or_path = await download_model(args.model)
        args.server = f"http://localhost:{args.port}/v1"
        args.model = "olmocr"  # Internal server always uses this name for the model, for supporting weird local model paths
        logger.info(f"Using internal server at {args.server}")
    else:
        logger.info(f"Using external server at {args.server}")
        model_name_or_path = None

    # Initialize the work queue
    qsize = await work_queue.initialize_queue()

    if qsize == 0:
        logger.info("No work to do, exiting")
        return

    # Start local vLLM instance if not using external one
    vllm_server = None
    if use_internal_server:
        vllm_server = asyncio.create_task(vllm_server_host(model_name_or_path, args, unknown_args))

    await vllm_server_ready(args)

    metrics_task = asyncio.create_task(metrics_reporter(work_queue))

    # Create worker tasks to process the queue concurrently.
    worker_tasks = []
    for i in range(args.workers):
        task = asyncio.create_task(worker(args, work_queue, worker_id=i))
        worker_tasks.append(task)

    # Wait for all worker tasks to finish
    await asyncio.gather(*worker_tasks)

    # Cancel vLLM server if it was started
    if vllm_server is not None:
        vllm_server.cancel()
    metrics_task.cancel()

    # Wait for cancelled tasks to complete
    tasks_to_wait = [metrics_task]
    if vllm_server is not None:
        tasks_to_wait.append(vllm_server)
    await asyncio.gather(*tasks_to_wait, return_exceptions=True)

    # Output final metrics summary
    metrics_summary = metrics.get_metrics_summary()
    logger.info("=" * 80)
    logger.info("FINAL METRICS SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total elapsed time: {metrics_summary['elapsed_time_seconds']:.2f} seconds")

    # Output token counts and rates
    total_metrics = metrics_summary["total_metrics"]
    rates = metrics_summary["rates"]

    logger.info(f"Total Server Input tokens: {total_metrics.get('server_input_tokens', 0):,}")
    logger.info(f"Total Server Output tokens: {total_metrics.get('server_output_tokens', 0):,}")

    logger.info(f"Finished input tokens: {total_metrics.get('finished_input_tokens', 0):,}")
    logger.info(f"Finished output tokens: {total_metrics.get('finished_output_tokens', 0):,}")

    logger.info(f"Completed pages: {total_metrics.get('completed_pages', 0):,}")
    logger.info(f"Failed pages: {total_metrics.get('failed_pages', 0):,}")
    logger.info(
        f"Page Failure rate: {total_metrics.get('failed_pages', 0) / max(total_metrics.get('completed_pages', 0) + total_metrics.get('failed_pages', 0), 1) * 100:.2f}%"
    )

    # Output finished_on_attempt statistics
    logger.info("")
    logger.info("Pages finished by attempt number:")
    total_finished = sum(total_metrics.get(f"finished_on_attempt_{i}", 0) for i in range(args.max_page_retries))
    cumulative = 0

    for i in range(args.max_page_retries):
        if f"finished_on_attempt_{i}" in total_metrics:
            count = total_metrics[f"finished_on_attempt_{i}"]
            cumulative += count
            percentage = (count / total_finished * 100) if total_finished > 0 else 0
            cumulative_percentage = (cumulative / total_finished * 100) if total_finished > 0 else 0
            logger.info(f"  Attempt {i}: {count:,} pages ({percentage:.1f}%) - Cumulative: {cumulative:,} ({cumulative_percentage:.1f}%)")

    # Output rates
    if "server_input_tokens_per_sec" in rates:
        logger.info(f"Server Input tokens/sec rate: {rates['server_input_tokens_per_sec']:.2f}")
    if "server_output_tokens_per_sec" in rates:
        logger.info(f"Server Output tokens/sec rate: {rates['server_output_tokens_per_sec']:.2f}")
    if "finished_input_tokens_per_sec" in rates:
        logger.info(f"Finished Input tokens/sec rate: {rates['finished_input_tokens_per_sec']:.2f}")
    if "finished_output_tokens_per_sec" in rates:
        logger.info(f"Finished Output tokens/sec rate: {rates['finished_output_tokens_per_sec']:.2f}")

    logger.info("=" * 80)
    logger.info("Work done")


if __name__ == "__main__":
    asyncio.run(main())
