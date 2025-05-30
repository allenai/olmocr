"""
Page and document processing module.

This module handles the core processing logic for individual PDF pages and
complete documents, including query building, model inference, and result handling.
"""

import asyncio
import base64
import json
import logging
import tempfile
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from io import BytesIO
from typing import Dict, Any, Optional, List

from PIL import Image
from pypdf import PdfReader
from botocore.exceptions import ClientError

from olmocr.data.renderpdf import render_pdf_to_base64png
from olmocr.filter.filter import PdfFilter
from olmocr.image_utils import convert_image_to_pdf_bytes, is_jpeg, is_png
from olmocr.prompts import PageResponse, build_finetuning_prompt
from olmocr.prompts.anchor import get_anchor_text
from olmocr.s3_utils import get_s3_bytes_with_backoff
from olmocr.pipeline.document_builder import PageResult, DolmaDocumentBuilder
from olmocr.pipeline.http_client import SGLangHTTPClient
from olmocr.metrics import MetricsKeeper, WorkerTracker

logger = logging.getLogger(__name__)


class PageProcessor:
    """
    Handles processing of individual PDF pages through the OCR pipeline.
    """
    
    def __init__(self, 
                 http_client: SGLangHTTPClient,
                 process_pool: ProcessPoolExecutor,
                 metrics: MetricsKeeper,
                 tracker: WorkerTracker):
        """
        Initialize the page processor.
        
        Args:
            http_client: HTTP client for SGLang communication
            process_pool: Process pool for CPU-bound tasks
            metrics: Metrics keeper for tracking statistics
            tracker: Worker tracker for monitoring progress
        """
        self.http_client = http_client
        self.process_pool = process_pool
        self.metrics = metrics
        self.tracker = tracker
    
    async def build_page_query(self, 
                              local_pdf_path: str, 
                              page: int, 
                              target_longest_image_dim: int, 
                              target_anchor_text_len: int, 
                              image_rotation: int = 0) -> Dict[str, Any]:
        """
        Build a query for processing a single PDF page.
        
        Args:
            local_pdf_path: Path to the local PDF file
            page: Page number to process (1-indexed)
            target_longest_image_dim: Target dimension for image rendering
            target_anchor_text_len: Target length for anchor text
            image_rotation: Rotation angle (0, 90, 180, 270)
            
        Returns:
            Query dictionary for the model
        """
        MAX_TOKENS = 4500
        assert image_rotation in [0, 90, 180, 270], "Invalid image rotation provided in build_page_query"

        # Allow the page rendering to process in the background while we get the anchor text
        image_base64 = asyncio.to_thread(
            render_pdf_to_base64png, 
            local_pdf_path, 
            page, 
            target_longest_image_dim=target_longest_image_dim
        )

        # GET ANCHOR TEXT IS NOT THREAD SAFE!! and it's also CPU bound, so it needs to run in a process pool
        loop = asyncio.get_running_loop()
        anchor_text = loop.run_in_executor(
            self.process_pool, 
            partial(get_anchor_text, pdf_engine="pdfreport", target_length=target_anchor_text_len), 
            local_pdf_path, 
            page
        )

        image_base64, anchor_text = await asyncio.gather(image_base64, anchor_text)  # type: ignore
        
        if image_rotation != 0:
            image_base64 = self._rotate_image(image_base64, image_rotation)

        return {
            "model": "Qwen/Qwen2-VL-7B-Instruct",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                        {"type": "text", "text": build_finetuning_prompt(anchor_text)},
                    ],
                }
            ],
            "max_tokens": MAX_TOKENS,
            "temperature": 0.0,
        }
    
    def _rotate_image(self, image_base64: str, rotation: int) -> str:
        """
        Rotate a base64-encoded image.
        
        Args:
            image_base64: Base64-encoded image
            rotation: Rotation angle in degrees
            
        Returns:
            Base64-encoded rotated image
        """
        image_bytes = base64.b64decode(image_base64)
        with Image.open(BytesIO(image_bytes)) as img:
            rotated_img = img.rotate(-rotation, expand=True)

            # Save the rotated image to a bytes buffer
            buffered = BytesIO()
            rotated_img.save(buffered, format="PNG")

        # Encode the rotated image back to base64
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
    
    async def process_page(self, 
                          args, 
                          worker_id: int, 
                          pdf_orig_path: str, 
                          pdf_local_path: str, 
                          page_num: int) -> PageResult:
        """
        Process a single PDF page through the OCR pipeline.
        
        Args:
            args: Command line arguments
            worker_id: ID of the worker processing this page
            pdf_orig_path: Original path to the PDF
            pdf_local_path: Local path to the PDF file
            page_num: Page number to process (1-indexed)
            
        Returns:
            PageResult containing the processing results
        """
        MAX_RETRIES = args.max_page_retries
        TEMPERATURE_BY_ATTEMPT = [0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 0.1, 0.8]
        FORCE_NO_DOCUMENT_ANCHORING_BY_ATTEMPT = [False, False, False, False, False, False, True, True]
        assert len(TEMPERATURE_BY_ATTEMPT) == len(FORCE_NO_DOCUMENT_ANCHORING_BY_ATTEMPT)
        
        exponential_backoffs = 0
        local_anchor_text_len = args.target_anchor_text_len
        local_image_rotation = 0
        attempt = 0
        await self.tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "started")

        while attempt < MAX_RETRIES:
            lookup_attempt = min(attempt, len(FORCE_NO_DOCUMENT_ANCHORING_BY_ATTEMPT) - 1)
            query = await self.build_page_query(
                pdf_local_path,
                page_num,
                args.target_longest_image_dim,
                local_anchor_text_len if not FORCE_NO_DOCUMENT_ANCHORING_BY_ATTEMPT[lookup_attempt] else -1,
                image_rotation=local_image_rotation,
            )
            # Change temperature as number of attempts increases to overcome repetition issues at expense of quality
            query["temperature"] = TEMPERATURE_BY_ATTEMPT[lookup_attempt]

            logger.info(f"Built page query for {pdf_orig_path}-{page_num}")

            try:
                status_code, response_body = await self.http_client.post_completion(query)

                if status_code == 400:
                    raise ValueError(f"Got BadRequestError from server: {response_body}, skipping this response")
                elif status_code == 500:
                    raise ValueError(f"Got InternalServerError from server: {response_body}, skipping this response")
                elif status_code != 200:
                    raise ValueError(f"Error http status {status_code}")

                base_response_data = json.loads(response_body)

                if base_response_data["usage"]["total_tokens"] > args.model_max_context:
                    local_anchor_text_len = max(1, local_anchor_text_len // 2)
                    logger.info(f"Reducing anchor text len to {local_anchor_text_len} for {pdf_orig_path}-{page_num}")
                    raise ValueError("Response exceeded model_max_context, cannot use this response")

                self.metrics.add_metrics(
                    sglang_input_tokens=base_response_data["usage"].get("prompt_tokens", 0),
                    sglang_output_tokens=base_response_data["usage"].get("completion_tokens", 0),
                )

                model_response_json = json.loads(base_response_data["choices"][0]["message"]["content"])
                page_response = PageResponse(**model_response_json)

                if not page_response.is_rotation_valid and attempt < MAX_RETRIES - 1:
                    logger.info(
                        f"Got invalid_page rotation for {pdf_orig_path}-{page_num} attempt {attempt}, retrying with {page_response.rotation_correction} rotation"
                    )
                    local_image_rotation = page_response.rotation_correction
                    raise ValueError(f"invalid_page rotation for {pdf_orig_path}-{page_num}")

                await self.tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "finished")
                return PageResult(
                    pdf_orig_path,
                    page_num,
                    page_response,
                    input_tokens=base_response_data["usage"].get("prompt_tokens", 0),
                    output_tokens=base_response_data["usage"].get("completion_tokens", 0),
                    is_fallback=False,
                )
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                logger.warning(f"Client error on attempt {attempt} for {pdf_orig_path}-{page_num}: {type(e)} {e}")

                # Exponential backoff for connection issues
                sleep_delay = 10 * (2**exponential_backoffs)
                exponential_backoffs += 1
                logger.info(f"Sleeping for {sleep_delay} seconds on {pdf_orig_path}-{page_num} to allow server restart")
                await asyncio.sleep(sleep_delay)
            except asyncio.CancelledError:
                logger.info(f"Process page {pdf_orig_path}-{page_num} cancelled")
                await self.tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "cancelled")
                raise
            except json.JSONDecodeError as e:
                logger.warning(f"JSON decode error on attempt {attempt} for {pdf_orig_path}-{page_num}: {e}")
                local_anchor_text_len = max(1, local_anchor_text_len // 2)
                logger.info(f"Reducing anchor text len to {local_anchor_text_len} for {pdf_orig_path}-{page_num}")
                attempt += 1
            except ValueError as e:
                logger.warning(f"ValueError on attempt {attempt} for {pdf_orig_path}-{page_num}: {type(e)} - {e}")
                attempt += 1
            except Exception as e:
                logger.exception(f"Unexpected error on attempt {attempt} for {pdf_orig_path}-{page_num}: {type(e)} - {e}")
                attempt += 1

        logger.error(f"Failed to process {pdf_orig_path}-{page_num} after {MAX_RETRIES} attempts.")
        await self.tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "errored")

        # Return fallback result
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
        )


class DocumentProcessor:
    """
    Handles processing of complete PDF documents.
    """

    def __init__(self,
                 page_processor: PageProcessor,
                 document_builder: DolmaDocumentBuilder,
                 pdf_filter: Optional[PdfFilter] = None):
        """
        Initialize the document processor.

        Args:
            page_processor: Page processor for handling individual pages
            document_builder: Document builder for creating Dolma documents
            pdf_filter: Optional PDF filter for document filtering
        """
        self.page_processor = page_processor
        self.document_builder = document_builder
        self.pdf_filter = pdf_filter

    async def process_pdf(self,
                         args,
                         worker_id: int,
                         pdf_orig_path: str,
                         pdf_s3_client) -> Optional[Dict[str, Any]]:
        """
        Process a complete PDF document.

        Args:
            args: Command line arguments
            worker_id: ID of the worker processing this document
            pdf_orig_path: Original path to the PDF
            pdf_s3_client: S3 client for downloading PDFs

        Returns:
            Dolma document dictionary, or None if processing failed
        """
        with tempfile.NamedTemporaryFile("wb+", suffix=".pdf") as tf:
            try:
                data = await asyncio.to_thread(lambda: get_s3_bytes_with_backoff(pdf_s3_client, pdf_orig_path))
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
                reader = PdfReader(tf.name)
                num_pages = reader.get_num_pages()
            except Exception:
                logger.exception(f"Could not count number of pages for {pdf_orig_path}, aborting document")
                return None

            logger.info(f"Got {num_pages} pages to do for {pdf_orig_path} in worker {worker_id}")

            if args.apply_filter and self.pdf_filter and self.pdf_filter.filter_out_pdf(tf.name):
                logger.info(f"Filtering out pdf {pdf_orig_path}")
                return None

            # Process all pages
            page_results = await self._process_all_pages(args, worker_id, pdf_orig_path, tf.name, num_pages)

            if page_results is None:
                return None

            # Check error rate
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

            return self.document_builder.build_document(pdf_orig_path, page_results)

    async def _process_all_pages(self,
                                args,
                                worker_id: int,
                                pdf_orig_path: str,
                                pdf_local_path: str,
                                num_pages: int) -> Optional[List[PageResult]]:
        """
        Process all pages of a PDF document.

        Args:
            args: Command line arguments
            worker_id: Worker ID
            pdf_orig_path: Original PDF path
            pdf_local_path: Local PDF path
            num_pages: Number of pages in the document

        Returns:
            List of PageResult objects, or None if processing failed
        """
        try:
            page_tasks = []
            async with asyncio.TaskGroup() as tg:
                for page_num in range(1, num_pages + 1):
                    task = tg.create_task(
                        self.page_processor.process_page(args, worker_id, pdf_orig_path, pdf_local_path, page_num)
                    )
                    page_tasks.append(task)

            # Collect the results from the entire task group
            page_results = [task.result() for task in page_tasks]
            return page_results

        except Exception as e:
            # Check for ExceptionGroup with BrokenProcessPool
            if isinstance(e, ExceptionGroup):
                from concurrent.futures.process import BrokenProcessPool
                broken_pool, other = e.split(BrokenProcessPool)
                if broken_pool is not None:  # Found at least one BrokenProcessPool
                    logger.critical("Encountered BrokenProcessPool, exiting process.")
                    import sys
                    sys.exit(1)

            logger.exception(f"Exception in process_pdf for {pdf_orig_path}: {e}")
            return None


def create_page_processor(http_client: SGLangHTTPClient,
                         process_pool: ProcessPoolExecutor,
                         metrics: MetricsKeeper,
                         tracker: WorkerTracker) -> PageProcessor:
    """
    Create a PageProcessor instance.

    Args:
        http_client: HTTP client for SGLang communication
        process_pool: Process pool for CPU-bound tasks
        metrics: Metrics keeper
        tracker: Worker tracker

    Returns:
        Configured PageProcessor
    """
    return PageProcessor(http_client, process_pool, metrics, tracker)


def create_document_processor(page_processor: PageProcessor,
                             document_builder: DolmaDocumentBuilder,
                             pdf_filter: Optional[PdfFilter] = None) -> DocumentProcessor:
    """
    Create a DocumentProcessor instance.

    Args:
        page_processor: Page processor
        document_builder: Document builder
        pdf_filter: Optional PDF filter

    Returns:
        Configured DocumentProcessor
    """
    return DocumentProcessor(page_processor, document_builder, pdf_filter)
