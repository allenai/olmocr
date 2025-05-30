"""
Worker management module for parallel document processing.

This module handles the coordination of multiple workers processing documents
in parallel, including work distribution, result collection, and output writing.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

from olmocr.metrics import MetricsKeeper, WorkerTracker
from olmocr.pipeline.processing import DocumentProcessor
from olmocr.s3_utils import parse_s3_path
from olmocr.work_queue import WorkQueue

logger = logging.getLogger(__name__)


class WorkerManager:
    """
    Manages a pool of workers for parallel document processing.
    """
    
    def __init__(self, 
                 document_processor: DocumentProcessor,
                 metrics: MetricsKeeper,
                 tracker: WorkerTracker,
                 workspace_s3_client,
                 pdf_s3_client):
        """
        Initialize the worker manager.
        
        Args:
            document_processor: Document processor for handling PDFs
            metrics: Metrics keeper for tracking statistics
            tracker: Worker tracker for monitoring progress
            workspace_s3_client: S3 client for workspace operations
            pdf_s3_client: S3 client for PDF operations
        """
        self.document_processor = document_processor
        self.metrics = metrics
        self.tracker = tracker
        self.workspace_s3_client = workspace_s3_client
        self.pdf_s3_client = pdf_s3_client
    
    async def worker(self, 
                    args, 
                    work_queue: WorkQueue, 
                    semaphore: asyncio.Semaphore, 
                    worker_id: int):
        """
        Worker function that processes work items from the queue.
        
        Args:
            args: Command line arguments
            work_queue: Work queue containing items to process
            semaphore: Semaphore for controlling worker access
            worker_id: Unique identifier for this worker
        """
        while True:
            # Wait until allowed to proceed
            await semaphore.acquire()

            work_item = await work_queue.get_work()

            if work_item is None:
                logger.info(f"Worker {worker_id} exiting due to empty queue")
                semaphore.release()
                break

            logger.info(f"Worker {worker_id} processing work item {work_item.hash}")
            await self.tracker.clear_work(worker_id)

            try:
                await self._process_work_item(args, work_item, worker_id)
                await work_queue.mark_done(work_item)
            except Exception as e:
                logger.exception(f"Exception occurred while processing work_hash {work_item.hash}: {e}")
            finally:
                semaphore.release()
    
    async def _process_work_item(self, args, work_item, worker_id: int):
        """
        Process a single work item containing multiple PDFs.
        
        Args:
            args: Command line arguments
            work_item: Work item containing PDF paths to process
            worker_id: Worker ID
        """
        # Process all PDFs in the work item
        dolma_docs = await self._process_pdfs_in_work_item(args, work_item, worker_id)
        
        logger.info(f"Got {len(dolma_docs)} docs for {work_item.hash}")
        
        # Write results
        await self._write_results(args, work_item, dolma_docs)
        
        # Update metrics
        self.metrics.add_metrics(
            finished_input_tokens=sum(doc["metadata"]["total-input-tokens"] for doc in dolma_docs),
            finished_output_tokens=sum(doc["metadata"]["total-output-tokens"] for doc in dolma_docs),
        )
    
    async def _process_pdfs_in_work_item(self, args, work_item, worker_id: int) -> List[Dict[str, Any]]:
        """
        Process all PDFs in a work item.
        
        Args:
            args: Command line arguments
            work_item: Work item containing PDF paths
            worker_id: Worker ID
            
        Returns:
            List of successfully processed Dolma documents
        """
        dolma_docs = []
        
        try:
            async with asyncio.TaskGroup() as tg:
                dolma_tasks = [
                    tg.create_task(
                        self.document_processor.process_pdf(args, worker_id, pdf, self.pdf_s3_client)
                    ) 
                    for pdf in work_item.work_paths
                ]
                logger.info(f"Created all tasks for {work_item.hash}")

            logger.info(f"Finished TaskGroup for worker on {work_item.hash}")

            for task in dolma_tasks:
                try:
                    result = task.result()
                    if result is not None:
                        dolma_docs.append(result)
                except Exception:
                    # Some dolma doc creations may have failed
                    pass
                    
        except Exception as e:
            logger.exception(f"Exception in _process_pdfs_in_work_item for {work_item.hash}: {e}")
        
        return dolma_docs
    
    async def _write_results(self, args, work_item, dolma_docs: List[Dict[str, Any]]):
        """
        Write processing results to storage.
        
        Args:
            args: Command line arguments
            work_item: Work item being processed
            dolma_docs: List of Dolma documents to write
        """
        # Write Dolma documents
        await self._write_dolma_documents(args, work_item, dolma_docs)
        
        # Write markdown files if requested
        if args.markdown:
            await self._write_markdown_files(args, work_item, dolma_docs)
    
    async def _write_dolma_documents(self, args, work_item, dolma_docs: List[Dict[str, Any]]):
        """
        Write Dolma documents to JSONL format.
        
        Args:
            args: Command line arguments
            work_item: Work item being processed
            dolma_docs: List of Dolma documents
        """
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
                self.workspace_s3_client.upload_file(temp_path, bucket, key)
            else:
                os.makedirs(os.path.dirname(output_final_path), exist_ok=True)
                shutil.copyfile(temp_path, output_final_path)
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    async def _write_markdown_files(self, args, work_item, dolma_docs: List[Dict[str, Any]]):
        """
        Write markdown files preserving folder structure.
        
        Args:
            args: Command line arguments
            work_item: Work item being processed
            dolma_docs: List of Dolma documents
        """
        logger.info(f"Writing {len(dolma_docs)} markdown files for {work_item.hash}")
        
        for doc in dolma_docs:
            source_file = doc["metadata"]["Source-File"]
            natural_text = doc["text"]

            # Create the output markdown path that preserves the folder structure
            if source_file.startswith("s3://"):
                # Extract the path after the bucket name for S3 sources
                parsed = urlparse(source_file)
                relative_path = parsed.path.lstrip("/")
            else:
                # For local files, use the full path
                relative_path = source_file

            # Change the extension to .md
            md_filename = os.path.splitext(os.path.basename(relative_path))[0] + ".md"
            # Get the directory path without the filename
            dir_path = os.path.dirname(relative_path)

            # Create the output markdown path
            markdown_dir = os.path.join(args.workspace, "markdown", dir_path)
            markdown_path = os.path.join(markdown_dir, md_filename)

            # Create the directory structure if it doesn't exist
            if markdown_path.startswith("s3://"):
                # For S3 paths, we'll create a temporary file and upload it
                with tempfile.NamedTemporaryFile(mode="w+", delete=False) as md_tf:
                    md_tf.write(natural_text)
                    md_tf.flush()
                    md_temp_path = md_tf.name

                try:
                    md_bucket, md_key = parse_s3_path(markdown_path)
                    self.workspace_s3_client.upload_file(md_temp_path, md_bucket, md_key)
                finally:
                    # Make sure to clean up the temporary file even if upload fails
                    if os.path.exists(md_temp_path):
                        os.unlink(md_temp_path)
            else:
                # For local paths, create the directory structure and write the file
                os.makedirs(markdown_dir, exist_ok=True)
                with open(markdown_path, "w") as md_f:
                    md_f.write(natural_text)


def create_worker_manager(document_processor: DocumentProcessor,
                         metrics: MetricsKeeper,
                         tracker: WorkerTracker,
                         workspace_s3_client,
                         pdf_s3_client) -> WorkerManager:
    """
    Create a WorkerManager instance.
    
    Args:
        document_processor: Document processor
        metrics: Metrics keeper
        tracker: Worker tracker
        workspace_s3_client: S3 client for workspace
        pdf_s3_client: S3 client for PDFs
        
    Returns:
        Configured WorkerManager
    """
    return WorkerManager(document_processor, metrics, tracker, workspace_s3_client, pdf_s3_client)
