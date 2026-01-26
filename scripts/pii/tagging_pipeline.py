#!/usr/bin/env python3
"""
Tagging pipeline for Dolma JSONL datasets.

For each .jsonl, .jsonl.gz, or .jsonl.ztd file under the dataset/documents folder,
this script issues a model prompt completion
collects the yes/no answers, and writes corresponding Dolma attributes JSONL files under
scratch/attributes/, mirroring the input structure.
"""

import argparse
import asyncio
import atexit
import gzip
import json
import logging
import os
import re
import sys
import time
from typing import Optional
from urllib.parse import urlparse

import boto3
import httpx
import zstandard as zstd
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field, ValidationError

from olmocr.check import check_torch_gpu_available
from olmocr.metrics import MetricsKeeper
from olmocr.cloud_utils import (
    download_directory,
    expand_s3_glob,
    get_s3_bytes_with_backoff,
    parse_s3_path,
)
from olmocr.version import VERSION
from olmocr.work_queue import LocalBackend, S3Backend, WorkQueue

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.propagate = False

server_logger = logging.getLogger("vllm")
server_logger.propagate = False

file_handler = logging.FileHandler("olmocr-pipeline-debug.log", mode="a")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)
server_logger.addHandler(file_handler)


# Default port; overridden by --port
SERVER_PORT = 30024

# Global variables for token statistics
metrics = MetricsKeeper(window=60 * 5)


class PIIClassification(BaseModel):
    primary_language: str = Field(..., description="Primary language as a two-letter code")
    document_type: str = Field(..., description="Basic summary of document type classification")
    is_resume_cv: Optional[bool] = Field(None, description="True if the document is a page from a resume or cv")

    is_academic_paper: Optional[bool] = None
    is_textbook: Optional[bool] = None
    is_news_article: Optional[bool] = None
    is_test_or_quiz: Optional[bool] = None
    is_homework_assignment: Optional[bool] = None
    is_class_syllabus: Optional[bool] = None
    is_meeting_minutes: Optional[bool] = None
    is_legal_contract: Optional[bool] = None
    is_form: Optional[bool] = None
    is_correspondence_or_letter: Optional[bool] = None
    is_public_order: Optional[bool] = None
    is_court_notice: Optional[bool] = None
    is_completion_certificate: Optional[bool] = None

    contains_pii: Optional[bool] = Field(None, description="True if document contains PII")


async def _process_single_page(page_text: str) -> PIIClassification:
    """Helper function to process a single document or page."""
    text = page_text

    query = {
        "model": "google/gemma-3-4b-it",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{text}\n\n-----------\n"
                            "Given the text above, determine what type of document it is. Answer in JSON. The format of your json object should be {'primary_language': str, 'document_type': str, 'is_resume_cv': bool, 'is_academic_paper': bool, 'is_textbook': bool, 'is_news_article': bool, 'is_test_or_quiz': bool, 'is_homework_assignment': bool, 'is_class_syllabus': bool, 'is_meeting_minutes': bool, 'is_legal_contract': bool, 'is_form': bool, 'is_correspondence_or_letter': bool, 'is_public_order': bool, 'is_court_notice': bool, 'is_completion_certificate': bool, 'contains_pii': bool}"
                        ),
                    }
                ],
            }
        ],
        "max_tokens": 400,
        "temperature": 0.0,
        "response_format": {"type": "json_schema", "json_schema": {"name": "PIIClassification", "schema": PIIClassification.model_json_schema()}},
    }

    url = f"http://localhost:{SERVER_PORT}/v1/chat/completions"

    # ---------- HTTP call ---------------------------------------------------
    try:
        status, body = await apost(url, json_data=query)
    except Exception as e:
        logger.warning(f"Server network error: {e!s}")
        metrics.add_metrics(server_errors=1)
        return PIIClassification(primary_language="en", document_type="unknown", is_resume_cv=None, contains_pii=None)

    metrics.add_metrics(server_requests=1)

    if status != 200:
        logger.warning(f"Server HTTP {status}: {body[:250]!r}")
        metrics.add_metrics(server_errors=1)
        return PIIClassification(primary_language="en", document_type="unknown", is_resume_cv=None, contains_pii=None)

    # ---------- Parse base JSON --------------------------------------------
    try:
        base = json.loads(body)
    except json.JSONDecodeError:
        logger.warning(f"Server response is not valid JSON: {body[:250]!r}")
        metrics.add_metrics(server_errors=1)
        return PIIClassification(primary_language="en", document_type="unknown", is_resume_cv=None, contains_pii=None)

    # Token accounting if available
    if "usage" in base:
        metrics.add_metrics(
            server_input_tokens=base["usage"].get("prompt_tokens", 0),
            server_output_tokens=base["usage"].get("completion_tokens", 0),
        )

    # ---------- Extract the model message ----------------------------------
    try:
        content = base["choices"][0]["message"].get("content")
    except (KeyError, IndexError, AttributeError) as e:
        logger.warning(f"Missing fields in Server response: {e!s}")
        metrics.add_metrics(server_errors=1)
        return PIIClassification(primary_language="en", document_type="unknown", is_resume_cv=None, contains_pii=None)

    if not isinstance(content, str):
        logger.warning("Server `content` is not a string; treating as error.")
        metrics.add_metrics(server_errors=1)
        return PIIClassification(primary_language="en", document_type="unknown", is_resume_cv=None, contains_pii=None)

    try:
        pii_classification: PIIClassification = PIIClassification.model_validate_json(content)
        return pii_classification
    except ValidationError as e:
        logger.warning(f"Unable to parse pii classification object: {e!s}")
        metrics.add_metrics(server_errors=1)
        return PIIClassification(primary_language="en", document_type="unknown", is_resume_cv=None, contains_pii=None)


# Manual simple implementation of HTTP Post
# It feels strange perhaps, but httpx and aiohttp are very complex beasts
# Ex. the sessionpool in httpcore has 4 different locks in it, and I've noticed
# that at the scale of 100M+ requests, that they deadlock in different strange ways
async def apost(url, json_data):
    parsed_url = urlparse(url)
    host = parsed_url.hostname
    port = parsed_url.port or 80
    path = parsed_url.path or "/"

    writer = None
    try:
        reader, writer = await asyncio.open_connection(host, port)

        json_payload = json.dumps(json_data)
        request = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(json_payload)}\r\n"
            f"Connection: close\r\n\r\n"
            f"{json_payload}"
        )
        writer.write(request.encode())
        await writer.drain()

        # Read status line
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
        else:
            raise ConnectionError("Anything other than fixed content length responses are not implemented yet")

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


async def process_dolma_document(args, dolma_doc, sem):
    """
    Query model to detect PII, enforcing a JSON schema.

    Resilient to:
      • Transport / HTTP errors
      • Missing or malformed fields in the response
      • Non-string or None `content`
      • Bad JSON in the model's answer

    Always returns: (doc_id, contains_pii: bool, text_length: int)
    """
    text = dolma_doc.get("text", "") or ""

    # Create keys for all fields in PIIClassification
    prefix = args.model.replace("/", "_") + "_v2tag_"
    result_attributes = {}

    # Initialize attribute lists for all PIIClassification fields
    for field_name in PIIClassification.model_fields:
        key_name = f"{prefix}_{field_name}"
        result_attributes[key_name] = []

    # Take first 5000 characters of the document for classification
    sample_text = text[:5000]
    text_length = len(text)
    span_end = min(5000, text_length)

    # Process the sample with the semaphore to limit concurrent requests
    async with sem:
        pii_class = await _process_single_page(sample_text)

    # Add all classification attributes to results
    for field_name in PIIClassification.model_fields:
        key_name = f"{prefix}_{field_name}"
        attribute_value = getattr(pii_class, field_name)

        # Create a span from 0 to min(5000, len(text)) with the attribute value
        result_attributes[key_name].append([0, span_end, attribute_value])

        # If the document is longer than 5000 characters, add a null span for the rest
        if text_length > 5000:
            result_attributes[key_name].append([span_end, text_length, None])

    return result_attributes


async def process_file(args, worker_id: int, file_uri: str):
    """
    Download a JSONL file, query model per record, and collect attributes.
    """
    # Fetch raw bytes (S3 or local)
    if file_uri.startswith("s3://"):
        raw = await asyncio.to_thread(get_s3_bytes_with_backoff, dataset_s3, file_uri)
    else:
        with open(file_uri, "rb") as f:
            raw = f.read()

    # Decompress if needed
    if file_uri.endswith(".gz"):
        file_bytes = gzip.decompress(raw)
    elif file_uri.endswith(".ztd") or file_uri.endswith(".zst") or file_uri.endswith(".zstd"):
        dctx = zstd.ZstdDecompressor()
        file_bytes = dctx.decompress(raw, max_output_size=1_000_000_000)
    else:
        file_bytes = raw

    lines = file_bytes.decode("utf-8").splitlines()
    page_tasks = {}

    # Send all records in parallel, max N queued at a time
    sem = asyncio.Semaphore(args.parallel_requests)

    async with asyncio.TaskGroup() as tg:
        for line in lines:
            dolma_doc = json.loads(line)
            task = tg.create_task(process_dolma_document(args, dolma_doc, sem))
            page_tasks[dolma_doc["id"]] = (task, dolma_doc)

    logger.info(f"Finished taskgroup with {len(page_tasks)} items for {file_uri}")

    # Collect results and build attributes
    attributes = []
    for doc_id, (task, dolma_doc) in page_tasks.items():
        doc_attributes = task.result()

        attributes.append({"id": doc_id, "attributes": doc_attributes})

    return attributes


async def worker(args, work_queue: WorkQueue, semaphore: asyncio.Semaphore, worker_id: int):
    """
    Pop work-items off the queue, run PII tagging, write the attributes file
    next to the dataset (keeping the original compression), mark the item done,
    and drop an empty sentinel file in <workspace>/results/.
    """
    while True:
        await semaphore.acquire()
        work_item = await work_queue.get_work()

        if work_item is None:
            logger.info(f"Worker {worker_id} exiting – queue empty")
            semaphore.release()
            break

        file_uri = work_item.work_paths[0]
        logger.info(f"Worker {worker_id} processing {file_uri}")

        try:
            # ------------------------------------------------------------------
            # Run the per-file pipeline
            # ------------------------------------------------------------------
            attributes = await process_file(args, worker_id, file_uri)

            # 1. Build the relative path that mirrors documents/…
            if file_uri.startswith("s3://"):
                _, key = parse_s3_path(file_uri)
                _, docs_prefix = parse_s3_path(args.dataset)
                rel_path = key[len(os.path.join(docs_prefix, "documents/")) :]
            else:
                docs_root = os.path.join(args.dataset, "documents")
                rel_path = os.path.relpath(file_uri, docs_root)

            out_rel = os.path.join("attributes", args.attribute_name, rel_path)
            out_jsonl = "\n".join(json.dumps(x) for x in attributes) + "\n"

            # 2. Preserve compression type
            if rel_path.endswith(".gz"):
                payload = gzip.compress(out_jsonl.encode("utf-8"))
            elif rel_path.endswith((".zst", ".ztd")):
                payload = zstd.ZstdCompressor().compress(out_jsonl.encode("utf-8"))
            else:
                payload = out_jsonl.encode("utf-8")

            # 3. Write to args.dataset (local or S3)
            if args.dataset.startswith("s3://"):
                bucket, prefix = parse_s3_path(args.dataset)
                key = os.path.join(prefix, out_rel)
                workspace_s3.put_object(Bucket=bucket, Key=key, Body=payload)
            else:
                out_path = os.path.join(args.dataset, out_rel)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as fh:
                    fh.write(payload)

            # 4. Mark queue item done
            await work_queue.mark_done(work_item)

            # 5. Drop empty sentinel file in <workspace>/results/
            sentinel_rel = os.path.join("results", f"output_{work_item.hash}.jsonl")
            if args.scratch.startswith("s3://"):
                bkt, pfx = parse_s3_path(args.scratch)
                key = os.path.join(pfx, sentinel_rel)
                workspace_s3.put_object(Bucket=bkt, Key=key, Body=b"")
            else:
                sentinel_path = os.path.join(args.scratch, sentinel_rel)
                os.makedirs(os.path.dirname(sentinel_path), exist_ok=True)
                open(sentinel_path, "w").close()

        except Exception as exc:
            logger.exception(f"Worker {worker_id} exception: {exc!s}")
        finally:
            semaphore.release()


async def server_task(model_name_or_path, args, semaphore):
    # Check GPU memory, lower mem devices need a bit less KV cache space because the VLM takes additional memory
    # mem_fraction_arg = ["--mem-fraction-static", "0.80"]

    cmd = [
        "vllm",
        "serve",
        model_name_or_path,
        "--port",
        str(SERVER_PORT),
        "--uvicorn-log-level",
        "warning",
        "--disable-log-requests",
        "--limit-mm-per-prompt",
        '{"image":0, "video": 0}',  # Disabling video encoder saves RAM that you can put towards the KV cache, thanks @charitarthchugh
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Ensure the subprocess is terminated on exit
    def _kill_proc():
        proc.terminate()

    atexit.register(_kill_proc)

    # Shared variables between tasks
    last_running_req, last_queue_req = 0, 0
    server_printed_ready_message = False
    last_semaphore_release = time.time()

    async def process_line(line):
        nonlocal last_running_req, last_queue_req, last_semaphore_release, server_printed_ready_message
        server_logger.info(line)

        # if the server hasn't initialized yet, log all the lines to the main logger also, so that the user
        # can see any warnings/errors more easily
        if not server_printed_ready_message:
            logger.info(line)

        if not server_printed_ready_message and "The server is fired up and ready to roll!" in line:
            server_printed_ready_message = True
            last_semaphore_release = time.time()

        match = re.search(r"Running: (\d+) reqs", line)
        if match:
            last_running_req = int(match.group(1))

        match = re.search(r"Waiting: (\d+) reqs", line)
        if match:
            last_queue_req = int(match.group(1))
            logger.info(f"running req: {last_running_req} queue req: {last_queue_req}")

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

    async def timeout_handler():
        nonlocal last_running_req, last_queue_req, last_semaphore_release
        try:
            while True:
                await asyncio.sleep(1)
                if server_printed_ready_message and last_queue_req == 0 and time.time() - last_semaphore_release > 30 and semaphore.locked():
                    semaphore.release()
                    last_semaphore_release = time.time()
                    logger.info("Semaphore released, allowing a worker to proceed.")
        except asyncio.CancelledError:
            pass  # Clean up if the task is cancelled

    # Start tasks to read stdout, stderr, and handle timeout logic
    stdout_task = asyncio.create_task(read_stream(proc.stdout))
    stderr_task = asyncio.create_task(read_stream(proc.stderr))
    timeout_task = asyncio.create_task(timeout_handler())

    try:
        await proc.wait()
    except asyncio.CancelledError:
        logger.info("Got cancellation request for server")
        proc.terminate()
        raise

    timeout_task.cancel()
    await asyncio.gather(stdout_task, stderr_task, timeout_task, return_exceptions=True)


async def server_host(model_name_or_path, args, semaphore):
    MAX_RETRIES = 5
    retry = 0

    while retry < MAX_RETRIES:
        await server_task(model_name_or_path, args, semaphore)
        logger.warning("Server task ended")
        retry += 1

    if retry >= MAX_RETRIES:
        logger.error(f"Ended up starting the server more than {retry} times, cancelling pipeline")
        logger.error("")
        logger.error("Please make sure vllm is installed according to the latest instructions for 0.8.4")
        sys.exit(1)


async def check_server_ready():
    max_attempts = 300
    delay_sec = 1
    url = f"http://localhost:{SERVER_PORT}/v1/models"

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient() as session:
                response = await session.get(url)

                if response.status_code == 200:
                    logger.info("server is ready.")
                    return
                else:
                    logger.info(f"Attempt {attempt}: Unexpected status code {response.status_code}")
        except Exception:
            logger.warning(f"Attempt {attempt}: Please wait for model server to become ready...")

        await asyncio.sleep(delay_sec)

    raise Exception("model server did not become ready after waiting.")


async def download_model(model_name_or_path: str):
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


async def metrics_reporter(work_queue):
    while True:
        # Leading newlines preserve table formatting in logs
        logger.info(f"Queue remaining: {work_queue.size}")
        logger.info("\n" + str(metrics))
        await asyncio.sleep(10)


def submit_beaker_job(args):
    from beaker import (  # type: ignore
        Beaker,
        BeakerConstraints,
        BeakerEnvVar,
        BeakerExperimentSpec,
        BeakerImageSource,
        BeakerJobPriority,
        BeakerResultSpec,
        BeakerRetrySpec,
        BeakerTaskContext,
        BeakerTaskResources,
        BeakerTaskSpec,
    )
    from beaker.exceptions import BeakerSecretNotFound

    Beaker.TIMEOUT = 60
    b = Beaker.from_env(default_workspace=args.beaker_workspace)
    owner = b.user_name
    beaker_image = f"jakep/olmocr-inference-{VERSION}"

    task_name = f"olmocr-tagging-{os.path.basename(args.scratch.rstrip('/'))}"

    # Take out --beaker flag so the workers will just run things
    args_list = [arg for arg in sys.argv[1:] if arg != "--beaker"]

    # Take out the --pdfs [arg] or --pdfs=[arg], since the queue is populated locally
    args_list = [arg for i, arg in enumerate(args_list) if not (arg.startswith("--pdfs") or (i > 0 and args_list[i - 1] == "--pdfs"))]

    try:
        b.secret.get(f"{owner}-WEKA_ACCESS_KEY_ID")
        b.secret.get(f"{owner}-WEKA_SECRET_ACCESS_KEY")
        b.secret.get(f"{owner}-AWS_CREDENTIALS_FILE")
    except BeakerSecretNotFound:
        print(
            f"Expected beaker secrets for accessing Weka and S3 are not found. Are you okay to write those to your beaker workspace {args.beaker_workspace}? [y/n]"
        )

        if input().strip().lower() != "y":
            print("Exiting...")
            sys.exit(1)

        b.secret.write(f"{owner}-WEKA_ACCESS_KEY_ID", os.environ.get("WEKA_ACCESS_KEY_ID", ""))
        b.secret.write(f"{owner}-WEKA_SECRET_ACCESS_KEY", os.environ.get("WEKA_SECRET_ACCESS_KEY", ""))
        b.secret.write(
            f"{owner}-AWS_CREDENTIALS_FILE",
            open(os.path.join(os.path.expanduser("~"), ".aws", "credentials")).read(),
        )

    env_var_secrets = [
        BeakerEnvVar(name="WEKA_ACCESS_KEY_ID", secret=f"{owner}-WEKA_ACCESS_KEY_ID"),
        BeakerEnvVar(name="WEKA_SECRET_ACCESS_KEY", secret=f"{owner}-WEKA_SECRET_ACCESS_KEY"),
        BeakerEnvVar(name="AWS_CREDENTIALS_FILE", secret=f"{owner}-AWS_CREDENTIALS_FILE"),
    ]

    try:
        b.secret.get("OLMOCR_PREVIEW_HF_TOKEN")
        env_var_secrets.append(BeakerEnvVar(name="HF_TOKEN", secret="OLMOCR_PREVIEW_HF_TOKEN"))
    except BeakerSecretNotFound:
        pass

    try:
        b.secret.get("OE_DATA_GCS_SA_KEY")
        env_var_secrets.append(BeakerEnvVar(name="GOOGLE_APPLICATION_CREDENTIALS_FILE", secret="OE_DATA_GCS_SA_KEY"))
    except BeakerSecretNotFound:
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
            b.secret.write("OE_DATA_GCS_SA_KEY", gcs_sa_key)
            env_var_secrets.append(BeakerEnvVar(name="GOOGLE_APPLICATION_CREDENTIALS_FILE", secret="OE_DATA_GCS_SA_KEY"))

    # Create the experiment spec
    experiment_spec = BeakerExperimentSpec(
        budget="ai2/oe-base",
        description=task_name,
        tasks=[
            BeakerTaskSpec(
                name=task_name,
                propagate_failure=False,
                propagate_preemption=False,
                replicas=args.beaker_gpus,
                context=BeakerTaskContext(
                    priority=BeakerJobPriority[args.beaker_priority],
                    preemptible=True,
                ),
                image=BeakerImageSource(beaker=beaker_image),
                command=["python", "scripts/pii/tagging_pipeline.py"] + args_list,
                env_vars=[
                    BeakerEnvVar(name="BEAKER_JOB_NAME", value=task_name),
                    BeakerEnvVar(name="OWNER", value=owner),
                ]
                + env_var_secrets,
                resources=BeakerTaskResources(gpu_count=1, memory="125GB"),
                constraints=BeakerConstraints(cluster=args.beaker_cluster if isinstance(args.beaker_cluster, list) else [args.beaker_cluster]),
                result=BeakerResultSpec(path="/noop-results"),
            )
        ],
        retry=BeakerRetrySpec(allowed_task_retries=10),
    )

    workload = b.experiment.create(spec=experiment_spec)

    print(f"Experiment URL: https://beaker.org/ex/{workload.experiment.id}")


async def main():
    parser = argparse.ArgumentParser(description="Tagging pipeline for Dolma JSONL dataset")
    parser.add_argument("dataset", help="Dolma dataset root (local or s3://) with documents/ folder")
    parser.add_argument("scratch", help="Scratch workspace (local dir or s3://)")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers")
    parser.add_argument("--parallel_requests", type=int, default=800, help="Max number of parallel requests to send to model")
    parser.add_argument("--model", default="google/gemma-3-4b-it", help="Model path or name, hugging face or local path format")
    parser.add_argument("--attribute_name", default="model_pii_tagging", help="Path to use for attribute naming")

    # Beaker/job running stuff
    parser.add_argument("--beaker", action="store_true", help="Submit this job to beaker instead of running locally")
    parser.add_argument("--beaker_workspace", help="Beaker workspace to submit to", default="ai2/olmocr")
    parser.add_argument(
        "--beaker_cluster",
        help="Beaker clusters you want to run on",
        default=["ai2/jupiter", "ai2/ceres", "ai2/neptune", "ai2/saturn"],
    )
    parser.add_argument("--beaker_gpus", type=int, default=1, help="Number of gpu replicas to run")
    parser.add_argument("--beaker_priority", type=str, default="normal", help="Beaker priority level for the job")

    parser.add_argument("--port", type=int, default=30024, help="Port for Model server")
    args = parser.parse_args()

    global SERVER_PORT, workspace_s3, dataset_s3
    SERVER_PORT = args.port
    workspace_s3 = boto3.client("s3")
    dataset_s3 = boto3.client("s3")

    # setup the job to work in beaker environment, load secrets, adjust logging, etc.
    if "BEAKER_JOB_NAME" in os.environ:
        cred_path = os.path.join(os.path.expanduser("~"), ".aws", "credentials")
        os.makedirs(os.path.dirname(cred_path), exist_ok=True)
        with open(cred_path, "w") as f:
            f.write(os.environ.get("AWS_CREDENTIALS_FILE", ""))
        cred_path = os.path.join(os.path.expanduser("~"), ".gcs", "credentials")
        os.makedirs(os.path.dirname(cred_path), exist_ok=True)
        with open(cred_path, "w") as f:
            f.write(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_FILE", ""))
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        workspace_s3 = boto3.client("s3")
        dataset_s3 = boto3.client("s3")

        # Wait a little bit so that not all beaker jobs in a task start at the same time and download the model at the same time
        replica_count = int(os.environ.get("BEAKER_REPLICA_COUNT", "1"))
        interval = 10 if (replica_count - 1) * 10 <= 30 else 30 / max(1, replica_count - 1)
        sleep_time = int(os.environ.get("BEAKER_REPLICA_RANK", "0")) * interval
        logger.info(f"Beaker job sleeping for {sleep_time} seconds to stagger model downloads")
        await asyncio.sleep(sleep_time)

    # Initialize work queue
    if args.scratch.startswith("s3://"):
        work_queue = WorkQueue(S3Backend(workspace_s3, args.scratch))
    else:
        work_queue = WorkQueue(LocalBackend(args.scratch))

    # Discover input files
    files = set()
    if args.dataset.startswith("s3://"):
        pattern = args.dataset.rstrip("/") + "/documents/*.jsonl*"
        matched = expand_s3_glob(dataset_s3, pattern)
        files = set(matched.keys())
    else:
        docs_dir = os.path.join(args.dataset, "documents")
        for root, _, fns in os.walk(docs_dir):
            for fn in fns:
                if fn.endswith((".jsonl", ".jsonl.gz", ".jsonl.ztd")):
                    files.add(os.path.join(root, fn))

    # Populate the work queue if needed
    await work_queue.populate_queue(list(files), items_per_group=1)

    if args.beaker:
        submit_beaker_job(args)
        return

    # If you get this far, then you are doing inference and need a GPU
    check_torch_gpu_available()

    logger.info(f"Starting pipeline with PID {os.getpid()}")

    # Download the model before you do anything else
    model_name_or_path = await download_model(args.model)

    # Initialize the work queue
    qsize = await work_queue.initialize_queue()

    if qsize == 0:
        logger.info("No work to do, exiting")
        return

    # Create a semaphore to control worker access
    # We only allow one worker to move forward with requests, until the server has no more requests in its queue
    # This lets us get full utilization by having many workers, but also to be outputting dolma docs as soon as possible
    # As soon as one worker is no longer saturating the gpu, the next one can start sending requests
    semaphore = asyncio.Semaphore(1)

    model_server = asyncio.create_task(server_host(model_name_or_path, args, semaphore))

    await check_server_ready()

    metrics_task = asyncio.create_task(metrics_reporter(work_queue))

    # Create worker tasks to process the queue concurrently.
    worker_tasks = []
    for i in range(args.workers):
        task = asyncio.create_task(worker(args, work_queue, semaphore, worker_id=i))
        worker_tasks.append(task)

    # Wait for all worker tasks to finish
    await asyncio.gather(*worker_tasks)

    model_server.cancel()
    metrics_task.cancel()
    logger.info("Work done")


if __name__ == "__main__":
    asyncio.run(main())
