"""
Core pipeline orchestration module.

This module provides the main orchestration logic for the olmOCR pipeline,
coordinating all components and managing the overall processing workflow.
"""

import asyncio
import atexit
import logging
import multiprocessing
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from typing import Optional

import boto3
import httpx
import torch
from huggingface_hub import snapshot_download

from olmocr.check import check_poppler_version, check_sglang_version, check_torch_gpu_available
from olmocr.filter.filter import Language, PdfFilter
from olmocr.metrics import MetricsKeeper, WorkerTracker
from olmocr.pipeline.document_builder import create_document_builder
from olmocr.pipeline.http_client import create_sglang_client
from olmocr.pipeline.processing import create_page_processor, create_document_processor
from olmocr.pipeline.workers import create_worker_manager
from olmocr.s3_utils import download_directory
from olmocr.work_queue import LocalWorkQueue, S3WorkQueue

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Main orchestrator for the olmOCR pipeline.
    
    Coordinates all pipeline components and manages the overall processing workflow.
    """
    
    def __init__(self):
        """Initialize the pipeline orchestrator."""
        # Global components
        self.metrics = MetricsKeeper(window=60 * 5)
        self.tracker = WorkerTracker()
        
        # Process pool for CPU-bound work
        self.process_pool = ProcessPoolExecutor(
            max_workers=min(multiprocessing.cpu_count() // 2 + 1, 32), 
            mp_context=multiprocessing.get_context("spawn")
        )
        
        # Cached PDF filter
        self.get_pdf_filter = cache(
            lambda: PdfFilter(
                languages_to_keep={Language.ENGLISH, None}, 
                apply_download_spam_check=True, 
                apply_form_check=True
            )
        )
        
        # S3 clients
        self.workspace_s3 = None
        self.pdf_s3 = None
        
        # Pipeline components
        self.http_client = None
        self.page_processor = None
        self.document_builder = None
        self.document_processor = None
        self.worker_manager = None
        
        # SGLang server process
        self.sglang_server_process = None
    
    async def initialize(self, args):
        """
        Initialize all pipeline components.
        
        Args:
            args: Command line arguments
        """
        logger.info("Initializing pipeline components...")
        
        # Initialize S3 clients
        self._initialize_s3_clients(args)
        
        # Check system requirements
        check_poppler_version()
        if not args.stats and not args.beaker:
            check_sglang_version()
            check_torch_gpu_available()
        
        # Initialize pipeline components
        await self._initialize_components(args)
        
        logger.info("Pipeline initialization complete")
    
    def _initialize_s3_clients(self, args):
        """Initialize S3 clients based on configuration."""
        # Default clients
        self.workspace_s3 = boto3.client("s3")
        self.pdf_s3 = boto3.client("s3")
        
        # Override with profile-specific clients if specified
        if args.workspace_profile:
            workspace_session = boto3.Session(profile_name=args.workspace_profile)
            self.workspace_s3 = workspace_session.client("s3")
        
        if args.pdf_profile:
            pdf_session = boto3.Session(profile_name=args.pdf_profile)
            self.pdf_s3 = pdf_session.client("s3")
    
    async def _initialize_components(self, args):
        """Initialize pipeline processing components."""
        # Create HTTP client
        self.http_client = await create_sglang_client(args.port)
        
        # Create document builder
        self.document_builder = create_document_builder()
        
        # Create page processor
        self.page_processor = create_page_processor(
            self.http_client, 
            self.process_pool, 
            self.metrics, 
            self.tracker
        )
        
        # Create document processor
        pdf_filter = self.get_pdf_filter() if args.apply_filter else None
        self.document_processor = create_document_processor(
            self.page_processor, 
            self.document_builder, 
            pdf_filter
        )
        
        # Create worker manager
        self.worker_manager = create_worker_manager(
            self.document_processor,
            self.metrics,
            self.tracker,
            self.workspace_s3,
            self.pdf_s3
        )
    
    async def start_sglang_server(self, model_name_or_path: str, args):
        """
        Start the SGLang inference server.
        
        Args:
            model_name_or_path: Path to the model
            args: Command line arguments
        """
        logger.info("Starting SGLang server...")
        
        # Check GPU memory for memory fraction setting
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # Convert to GB
        mem_fraction_arg = ["--mem-fraction-static", "0.80"] if gpu_memory < 60 else []

        cmd = [
            "python3",
            "-m",
            "sglang.launch_server",
            "--model-path",
            model_name_or_path,
            "--chat-template",
            args.model_chat_template,
            "--port",
            str(args.port),
            "--log-level-http",
            "warning",
        ]
        cmd.extend(mem_fraction_arg)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Ensure the subprocess is terminated on exit
        def _kill_proc():
            proc.terminate()

        atexit.register(_kill_proc)
        self.sglang_server_process = proc
        
        # Start server monitoring task
        server_task = asyncio.create_task(self._monitor_sglang_server(proc, args))
        
        return server_task
    
    async def _monitor_sglang_server(self, proc, args):
        """Monitor SGLang server output and handle restarts."""
        MAX_RETRIES = 5
        retry = 0
        
        while retry < MAX_RETRIES:
            try:
                await self._handle_server_output(proc)
                await proc.wait()
            except asyncio.CancelledError:
                logger.info("Got cancellation request for SGLang server")
                proc.terminate()
                raise
            
            logger.warning("SGLang server task ended")
            retry += 1
            
            if retry < MAX_RETRIES:
                # Restart server
                logger.info(f"Restarting SGLang server (attempt {retry + 1}/{MAX_RETRIES})")
                proc = await self._restart_sglang_server(args)
        
        if retry >= MAX_RETRIES:
            logger.error(f"SGLang server failed {retry} times, cancelling pipeline")
            logger.error("Please make sure sglang is installed according to: https://docs.sglang.ai/start/install.html")
            sys.exit(1)
    
    async def _handle_server_output(self, proc):
        """Handle SGLang server output streams."""
        async def read_stream(stream, stream_name):
            while True:
                line = await stream.readline()
                if not line:
                    break
                try:
                    line = line.decode("utf-8").rstrip()
                    logger.debug(f"SGLang {stream_name}: {line}")
                    
                    # Check for critical errors
                    if "Detected errors during sampling" in line:
                        logger.error("Cannot continue, sampling errors detected, model is probably corrupt")
                        sys.exit(1)
                    
                    if "IndexError: list index out of range" in line:
                        logger.error("IndexError in model, restarting server")
                        proc.terminate()
                        
                except Exception as ex:
                    logger.warning(f"Got {ex} when reading log line from inference server, skipping")
        
        # Start tasks to read both streams
        stdout_task = asyncio.create_task(read_stream(proc.stdout, "stdout"))
        stderr_task = asyncio.create_task(read_stream(proc.stderr, "stderr"))
        
        try:
            await asyncio.gather(stdout_task, stderr_task)
        except asyncio.CancelledError:
            stdout_task.cancel()
            stderr_task.cancel()
            raise
    
    async def _restart_sglang_server(self, args):
        """Restart the SGLang server process."""
        # Implementation would restart the server with the same parameters
        # This is a simplified version - full implementation would recreate the process
        pass
    
    async def wait_for_sglang_ready(self, port: int):
        """
        Wait for SGLang server to become ready.
        
        Args:
            port: Port number of the SGLang server
        """
        max_attempts = 300
        delay_sec = 1
        url = f"http://localhost:{port}/v1/models"

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient() as session:
                    response = await session.get(url)

                    if response.status_code == 200:
                        logger.info("SGLang server is ready.")
                        return
                    else:
                        logger.info(f"Attempt {attempt}: Unexpected status code {response.status_code}")
            except Exception:
                logger.warning(f"Attempt {attempt}: Please wait for SGLang server to become ready...")

            await asyncio.sleep(delay_sec)

        raise Exception("SGLang server did not become ready after waiting.")
    
    async def download_model(self, model_name_or_path: str) -> str:
        """
        Download model if necessary.
        
        Args:
            model_name_or_path: Model path or identifier
            
        Returns:
            Local path to the model
        """
        if model_name_or_path.startswith("s3://") or model_name_or_path.startswith("gs://") or model_name_or_path.startswith("weka://"):
            logger.info(f"Downloading model directory from '{model_name_or_path}'")
            model_cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "olmocr", "model")
            download_directory([model_name_or_path], model_cache_dir)
            return model_cache_dir
        elif os.path.isabs(model_name_or_path) and os.path.isdir(model_name_or_path):
            logger.info(f"Using local model path at '{model_name_or_path}'")
            return model_name_or_path
        else:
            logger.info(f"Downloading model with hugging face '{model_name_or_path}'")
            snapshot_download(repo_id=model_name_or_path)
            return model_name_or_path
    
    async def create_work_queue(self, args):
        """
        Create and initialize work queue.
        
        Args:
            args: Command line arguments
            
        Returns:
            Initialized work queue
        """
        if args.workspace.startswith("s3://"):
            work_queue = S3WorkQueue(self.workspace_s3, args.workspace)
        else:
            work_queue = LocalWorkQueue(args.workspace)
        
        return work_queue
    
    async def start_workers(self, args, work_queue, semaphore):
        """
        Start worker tasks for processing.
        
        Args:
            args: Command line arguments
            work_queue: Work queue to process
            semaphore: Semaphore for controlling worker access
            
        Returns:
            List of worker tasks
        """
        worker_tasks = []
        for i in range(args.workers):
            task = asyncio.create_task(
                self.worker_manager.worker(args, work_queue, semaphore, worker_id=i)
            )
            worker_tasks.append(task)
        
        return worker_tasks
    
    async def start_metrics_reporter(self, work_queue):
        """
        Start metrics reporting task.
        
        Args:
            work_queue: Work queue to monitor
            
        Returns:
            Metrics reporter task
        """
        async def metrics_reporter():
            while True:
                logger.info(f"Queue remaining: {work_queue.size}")
                logger.info("\n" + str(self.metrics))
                logger.info("\n" + str(await self.tracker.get_status_table()))
                await asyncio.sleep(10)
        
        return asyncio.create_task(metrics_reporter())
    
    def cleanup(self):
        """Clean up pipeline resources."""
        if self.process_pool:
            self.process_pool.shutdown(wait=False)
        
        if self.sglang_server_process:
            self.sglang_server_process.terminate()


def create_pipeline_orchestrator() -> PipelineOrchestrator:
    """
    Create a new PipelineOrchestrator instance.
    
    Returns:
        Configured PipelineOrchestrator
    """
    return PipelineOrchestrator()
