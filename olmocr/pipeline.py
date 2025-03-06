import os
import re
import sys
import time
import json
import boto3
import httpx
import torch
import random
import atexit
import base64
import shutil
import asyncio
import hashlib
import logging
import argparse
import datetime
import tempfile
import multiprocessing

from io import BytesIO
from PIL import Image
from tqdm import tqdm
from pypdf import PdfReader
from functools import cache, partial
from dataclasses import dataclass
from urllib.parse import urlparse
from botocore.exceptions import ClientError
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool


from olmocr.check import (
    check_poppler_version,
    check_sglang_version,
    check_torch_gpu_available,
)
from olmocr.data.renderpdf import render_pdf_to_base64png
from olmocr.filter.filter import Language, PdfFilter
from olmocr.metrics import MetricsKeeper, WorkerTracker
from olmocr.prompts import PageResponse, build_finetuning_prompt
from olmocr.prompts.anchor import get_anchor_text
from olmocr.s3_utils import (
    download_zstd_csv,
    expand_s3_glob,
    get_s3_bytes,
    get_s3_bytes_with_backoff,
    parse_s3_path,
)
from olmocr.version import VERSION
from olmocr.work_queue import LocalWorkQueue, S3WorkQueue, WorkQueue

# Initialize logger
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

# Global s3 clients fo the whole script, we have two separate ones in case your workspace and your pdfs are in different accounts
workspace_s3 = boto3.client("s3")
pdf_s3 = boto3.client("s3")

# Global variables for token statistics
metrics = MetricsKeeper(window=60 * 5)
tracker = WorkerTracker()

# Process pool for offloading cpu bound work, like calculating anchor texts, max 32 workers, otherwise it can spawn way too many workers on a big machine
process_pool = ProcessPoolExecutor(max_workers=min(multiprocessing.cpu_count() // 2 + 1, 32), mp_context=multiprocessing.get_context("spawn"))

# Filter object, cached so it will only get loaded when/if you need it
get_pdf_filter = cache(lambda: PdfFilter(languages_to_keep={Language.ENGLISH, None}, apply_download_spam_check=True, apply_form_check=True))

SGLANG_SERVER_PORT = 30024


@dataclass(frozen=True)
class PageResult:
    s3_path: str
    page_num: int
    response: PageResponse

    input_tokens: int
    output_tokens: int
    is_fallback: bool


async def build_page_query(local_pdf_path: str, page: int, target_longest_image_dim: int, target_anchor_text_len: int, image_rotation: int = 0) -> dict:
    MAX_TOKENS = 3000
    assert image_rotation in [0, 90, 180, 270], "Invalid image rotation provided in build_page_query"

    # Allow the page rendering to process in the background while we get the anchor text (which blocks the main thread)
    image_base64 = asyncio.to_thread(render_pdf_to_base64png, local_pdf_path, page, target_longest_image_dim=target_longest_image_dim)

    # GET ANCHOR TEXT IS NOT THREAD SAFE!! Ahhhh..... don't try to do it
    # and it's also CPU bound, so it needs to run in a process pool
    loop = asyncio.get_running_loop()
    anchor_text = loop.run_in_executor(
        process_pool, partial(get_anchor_text, pdf_engine="pdfreport", target_length=target_anchor_text_len), local_pdf_path, page
    )

    image_base64, anchor_text = await asyncio.gather(image_base64, anchor_text)  # type: ignore
    if image_rotation != 0:
        image_bytes = base64.b64decode(image_base64)
        with Image.open(BytesIO(image_bytes)) as img:
            rotated_img = img.rotate(-image_rotation, expand=True)

            # Save the rotated image to a bytes buffer
            buffered = BytesIO()
            rotated_img.save(buffered, format="PNG")

        # Encode the rotated image back to base64
        image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return {
        "model": "Qwen/Qwen2-VL-7B-Instruct",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_finetuning_prompt(anchor_text)},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.8,
    }


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


async def process_page(args, worker_id: int, pdf_orig_path: str, pdf_local_path: str, page_num: int) -> PageResult:
    COMPLETION_URL = f"http://localhost:{SGLANG_SERVER_PORT}/v1/chat/completions"
    MAX_RETRIES = args.max_page_retries

    exponential_backoffs = 0
    local_anchor_text_len = args.target_anchor_text_len
    local_image_rotation = 0
    attempt = 0
    await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "started")

    while attempt < MAX_RETRIES:
        query = await build_page_query(pdf_local_path, page_num, args.target_longest_image_dim, local_anchor_text_len, image_rotation=local_image_rotation)

        logger.info(f"Built page query for {pdf_orig_path}-{page_num}")

        try:
            status_code, response_body = await apost(COMPLETION_URL, json_data=query)

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

            metrics.add_metrics(
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

            await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "finished")
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

            # Now we want to do exponential backoff, and not count this as an actual page retry
            # Page retrys are supposed to be for fixing bad results from the model, but actual requests to sglang
            # are supposed to work. Probably this means that the server is just restarting
            sleep_delay = 10 * (2**exponential_backoffs)
            exponential_backoffs += 1
            logger.info(f"Sleeping for {sleep_delay} seconds on {pdf_orig_path}-{page_num} to allow server restart")
            await asyncio.sleep(sleep_delay)
        except asyncio.CancelledError:
            logger.info(f"Process page {pdf_orig_path}-{page_num} cancelled")
            await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "cancelled")
            raise
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error on attempt {attempt} for {pdf_orig_path}-{page_num}: {e}")
            attempt += 1
        except ValueError as e:
            logger.warning(f"ValueError on attempt {attempt} for {pdf_orig_path}-{page_num}: {type(e)} - {e}")
            attempt += 1
        except Exception as e:
            logger.exception(f"Unexpected error on attempt {attempt} for {pdf_orig_path}-{page_num}: {type(e)} - {e}")
            attempt += 1

    logger.error(f"Failed to process {pdf_orig_path}-{page_num} after {MAX_RETRIES} attempts.")
    await tracker.track_work(worker_id, f"{pdf_orig_path}-{page_num}", "errored")

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


async def process_pdf(args, worker_id: int, pdf_orig_path: str):
    with tempfile.NamedTemporaryFile("wb+", suffix=".pdf") as tf:
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

        try:
            reader = PdfReader(tf.name)
            num_pages = reader.get_num_pages()
        except:
            logger.exception(f"Could not count number of pages for {pdf_orig_path}, aborting document")
            return None

        logger.info(f"Got {num_pages} pages to do for {pdf_orig_path} in worker {worker_id}")

        if args.apply_filter and get_pdf_filter().filter_out_pdf(tf.name):
            logger.info(f"Filtering out pdf {pdf_orig_path}")
            return None

        # List to hold the tasks for processing each page
        page_tasks = []
        page_results = []

        try:
            async with asyncio.TaskGroup() as tg:
                for page_num in range(1, num_pages + 1):
                    task = tg.create_task(process_page(args, worker_id, pdf_orig_path, tf.name, page_num))
                    page_tasks.append(task)

            # Collect the results from the entire task group, assuming no exceptions
            page_results = [task.result() for task in page_tasks]

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
            # Check for ExceptionGroup with BrokenProcessPool
            if isinstance(e, ExceptionGroup):
                broken_pool, other = e.split(BrokenProcessPool)
                if broken_pool is not None:  # Found at least one BrokenProcessPool
                    logger.critical("Encountered BrokenProcessPool, exiting process.")
                    sys.exit(1)

            logger.exception(f"Exception in process_pdf for {pdf_orig_path}: {e}")
            # You can't build a dolma doc with even 1 failed page, so just get out of here
            # However, you don't want to propagate an exception higher up and cancel the entire work_group
            return None


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
        "attributes": {"pdf_page_numbers": pdf_page_spans},
    }
    return dolma_doc


async def worker(args, work_queue: WorkQueue, semaphore, worker_id):
    while True:
        # Wait until allowed to proceed
        await semaphore.acquire()

        work_item = await work_queue.get_work()

        if work_item is None:
            logger.info(f"Worker {worker_id} exiting due to empty queue")
            semaphore.release()
            break

        logger.info(f"Worker {worker_id} processing work item {work_item.hash}")
        await tracker.clear_work(worker_id)

        try:
            async with asyncio.TaskGroup() as tg:
                dolma_tasks = [tg.create_task(process_pdf(args, worker_id, pdf)) for pdf in work_item.work_paths]
                logger.info(f"Created all tasks for {work_item.hash}")

            logger.info(f"Finished TaskGroup for worker on {work_item.hash}")

            dolma_docs = []
            for task in dolma_tasks:
                try:
                    result = task.result()
                except:
                    # some dolma doc creations may have failed
                    pass

                if result is not None:
                    dolma_docs.append(result)

            logger.info(f"Got {len(dolma_docs)} docs for {work_item.hash}")

            # Write the Dolma documents to a local temporary file in JSONL format
            with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tf:
                for doc in dolma_docs:
                    tf.write(json.dumps(doc))
                    tf.write("\n")
                tf.flush()

                # Define the output S3 path using the work_hash
                output_final_path = os.path.join(args.workspace, "results", f"output_{work_item.hash}.jsonl")

                if output_final_path.startswith("s3://"):
                    bucket, key = parse_s3_path(output_final_path)
                    workspace_s3.upload_file(tf.name, bucket, key)
                else:
                    shutil.copyfile(tf.name, output_final_path)

            # Update finished token counts from successful documents
            metrics.add_metrics(
                finished_input_tokens=sum(doc["metadata"]["total-input-tokens"] for doc in dolma_docs),
                finished_output_tokens=sum(doc["metadata"]["total-output-tokens"] for doc in dolma_docs),
            )

            await work_queue.mark_done(work_item)
        except Exception as e:
            logger.exception(f"Exception occurred while processing work_hash {work_item.hash}: {e}")
        finally:
            semaphore.release()


async def sglang_server_task(args, semaphore):
    model_name_or_path = args.model

    # if "://" in model_name_or_path:
    #     # TODO, Fix this code so that we support the multiple s3/weka paths, or else remove it
    #     model_cache_dir = os.path.join(os.path.expanduser('~'), '.cache', 'olmocr', 'model')
    #     download_directory(model_name_or_path, model_cache_dir)

    #     # Check the rope config and make sure it's got the proper key
    #     with open(os.path.join(model_cache_dir, "config.json"), "r") as cfin:
    #         config_data = json.load(cfin)

    #     if "rope_type" in config_data["rope_scaling"]:
    #         del config_data["rope_scaling"]["rope_type"]
    #         config_data["rope_scaling"]["type"] = "mrope"

    #         with open(os.path.join(model_cache_dir, "config.json"), "w") as cfout:
    #             json.dump(config_data, cfout)

    # Check GPU memory, lower mem devices need a bit less KV cache space because the VLM takes additional memory
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
        # "--context-length", str(args.model_max_context),  # Commented out due to crashes
        "--port",
        str(SGLANG_SERVER_PORT),
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

    # Shared variables between tasks
    last_running_req, last_queue_req = 0, 0
    server_printed_ready_message = False
    last_semaphore_release = time.time()

    async def process_line(line):
        nonlocal last_running_req, last_queue_req, last_semaphore_release, server_printed_ready_message
        sglang_logger.info(line)

        # if the server hasn't initialized yet, log all the lines to the main logger also, so that the user
        # can see any warnings/errors more easily
        if not server_printed_ready_message:
            logger.info(line)

        if "Detected errors during sampling" in line:
            logger.error("Cannot continue, sampling errors detected, model is probably corrupt")
            sys.exit(1)

        # TODO, need to trace down this issue in sglang itself, but it will otherwise cause the server to lock up
        if "IndexError: list index out of range" in line:
            logger.error("IndexError in model, restarting server")
            proc.terminate()

        if not server_printed_ready_message and "The server is fired up and ready to roll!" in line:
            server_printed_ready_message = True
            last_semaphore_release = time.time()

        match = re.search(r"#running-req: (\d+)", line)
        if match:
            last_running_req = int(match.group(1))

        match = re.search(r"#queue-req: (\d+)", line)
        if match:
            last_queue_req = int(match.group(1))
            logger.info(f"sglang running req: {last_running_req} queue req: {last_queue_req}")

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

    async def timeout_task():
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
    timeout_task = asyncio.create_task(timeout_task())

    try:
        await proc.wait()
    except asyncio.CancelledError:
        logger.info("Got cancellation request for SGLang server")
        proc.terminate()
        raise

    timeout_task.cancel()
    await asyncio.gather(stdout_task, stderr_task, timeout_task, return_exceptions=True)


async def sglang_server_host(args, semaphore):
    MAX_RETRIES = 5
    retry = 0

    while retry < MAX_RETRIES:
        await sglang_server_task(args, semaphore)
        logger.warning("SGLang server task ended")
        retry += 1

    if retry >= MAX_RETRIES:
        logger.error(f"Ended up starting the sglang server more than {retry} times, cancelling pipeline")
        logger.error("")
        logger.error("Please make sure sglang is installed according to the latest instructions here: https://docs.sglang.ai/start/install.html")
        sys.exit(1)


async def sglang_server_ready():
    max_attempts = 300
    delay_sec = 1
    url = f"http://localhost:{SGLANG_SERVER_PORT}/v1/models"

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient() as session:
                response = await session.get(url)

                if response.status_code == 200:
                    logger.info("sglang server is ready.")
                    return
                else:
                    logger.info(f"Attempt {attempt}: Unexpected status code {response.status_code}")
        except Exception as e:
            logger.warning(f"Attempt {attempt}: {e}")

        await asyncio.sleep(delay_sec)

    raise Exception("sglang server did not become ready after waiting.")


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
        budget="ai2/oe-data",
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
                env_vars=[EnvVar(name="BEAKER_JOB_NAME", value=task_name), EnvVar(name="OWNER", value=owner)] + env_var_secrets,
                resources=TaskResources(gpu_count=1),
                constraints=Constraints(cluster=args.beaker_cluster if isinstance(args.beaker_cluster, list) else [args.beaker_cluster]),
                result=ResultSpec(path="/noop-results"),
            )
        ],
    )

    experiment_data = b.experiment.create(spec=experiment_spec, workspace=args.beaker_workspace)

    print(f"Experiment URL: https://beaker.org/ex/{experiment_data.id}")


def print_stats(args):
    LONG_CONTEXT_THRESHOLD = 32768

    assert args.workspace.startswith("s3://"), "Printing stats functionality only works with s3 workspaces for now."

    # Get total work items and completed items
    index_file_s3_path = os.path.join(args.workspace, "work_index_list.csv.zstd")
    output_glob = os.path.join(args.workspace, "results", "*.jsonl")

    done_work_items = expand_s3_glob(workspace_s3, output_glob)
    work_queue = {parts[0]: parts[1:] for line in download_zstd_csv(workspace_s3, index_file_s3_path) if (parts := line.strip().split(",")) and line.strip()}

    total_items = len(work_queue)
    completed_items = len(done_work_items)

    def process_output_file(s3_path):
        try:
            data = get_s3_bytes(workspace_s3, s3_path)
            doc_count = 0
            total_input_tokens = 0
            total_output_tokens = 0
            total_pages = 0
            total_fallback_pages = 0
            processed_paths = set()

            # Counters for long context docs within a single file
            long_context_docs = 0
            long_context_tokens = 0

            for line in data.decode("utf-8").splitlines():
                if line.strip():
                    doc = json.loads(line)
                    doc_count += 1
                    doc_input_tokens = doc["metadata"].get("total-input-tokens", 0)
                    doc_output_tokens = doc["metadata"].get("total-output-tokens", 0)
                    doc_pages = doc["metadata"].get("pdf-total-pages", 0)
                    doc_fallback_pages = doc["metadata"].get("total-fallback-pages", 0)

                    total_input_tokens += doc_input_tokens
                    total_output_tokens += doc_output_tokens
                    total_pages += doc_pages
                    total_fallback_pages += doc_fallback_pages
                    processed_paths.add(doc["metadata"]["Source-File"])

                    # Check if this doc exceeds the long context threshold
                    if doc_output_tokens > LONG_CONTEXT_THRESHOLD:
                        long_context_docs += 1
                        long_context_tokens += doc_output_tokens

            return (
                doc_count,
                total_input_tokens,
                total_output_tokens,
                total_pages,
                total_fallback_pages,
                processed_paths,
                long_context_docs,
                long_context_tokens,
            )
        except Exception as e:
            logger.warning(f"Error processing {s3_path}: {e}")
            return 0, 0, 0, 0, 0, set(), 0, 0

    print("\nProcessing output files...")
    docs_total = 0
    input_tokens_total = 0
    output_tokens_total = 0
    pages_total = 0
    fallback_pages_total = 0
    all_processed_paths = set()
    original_paths = set()

    # Counters for long context documents across all files
    long_context_docs_count = 0
    long_context_tokens_total = 0

    # First collect all original PDF paths
    for done_work_item in done_work_items:
        if match := re.search(r"output_(\w+).jsonl", done_work_item):
            done_work_hash = match.group(1)
            original_paths.update(work_queue[done_work_hash])

    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(process_output_file, item): item for item in done_work_items}

        for future in tqdm(as_completed(futures), total=len(futures)):
            (doc_count, input_tokens, output_tokens, pages, fallback_pages, processed_paths, long_context_docs, long_context_tokens) = future.result()
            docs_total += doc_count
            input_tokens_total += input_tokens
            output_tokens_total += output_tokens
            pages_total += pages
            fallback_pages_total += fallback_pages
            all_processed_paths.update(processed_paths)
            long_context_docs_count += long_context_docs
            long_context_tokens_total += long_context_tokens

    skipped_paths = original_paths - all_processed_paths

    print("\nWork Items Status:")
    print(f"Total work items: {total_items:,}")
    print(f"Completed items: {completed_items:,}")
    print(f"Remaining items: {total_items - completed_items:,}")

    print("\nResults:")
    print(f"Total documents processed: {docs_total:,}")
    print(f"Total documents skipped: {len(skipped_paths):,}")
    print(f"Total pages on fallback: {fallback_pages_total:,}")
    print(f"Total pages processed: {pages_total:,}")

    print(f"\nTotal output tokens: {output_tokens_total:,}")
    print(f"Projected output tokens: {round((output_tokens_total/max(1, completed_items))*total_items):,}")

    print(f"\nAverage pages per doc: {pages_total/max(1,docs_total):,.1f}")
    print(f"Average output tokens per doc: {output_tokens_total/max(1,docs_total):,.1f}")
    print(f"Average output tokens per page: {output_tokens_total/max(1,pages_total):,.1f}")

    # Print long context documents stats
    print(f"\nLong Context Documents (>{LONG_CONTEXT_THRESHOLD} tokens): {long_context_docs_count:,}")
    print(f"Total tokens in long context documents: {long_context_tokens_total:,}")


async def main():
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
    args = parser.parse_args()

    global workspace_s3, pdf_s3

    # setup the job to work in beaker environment, load secrets, adjust logging, etc.
    if "BEAKER_JOB_NAME" in os.environ:
        sglang_logger.addHandler(console_handler)
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
        work_queue = S3WorkQueue(workspace_s3, args.workspace)
    else:
        work_queue = LocalWorkQueue(args.workspace)

    if args.pdfs:
        logger.info("Got --pdfs argument, going to add to the work queue")
        pdf_work_paths = set()

        for pdf_path in args.pdfs:
            # Expand s3 paths
            if pdf_path.startswith("s3://"):
                logger.info(f"Expanding s3 glob at {pdf_path}")
                pdf_work_paths |= set(expand_s3_glob(pdf_s3, pdf_path))
            elif os.path.exists(pdf_path):
                if open(pdf_path, "rb").read(4) == b"%PDF":
                    logger.info(f"Loading file at {pdf_path} as PDF document")
                    pdf_work_paths.add(pdf_path)
                else:
                    logger.info(f"Loading file at {args.pdfs} as list of paths")
                    with open(args.pdfs, "r") as f:
                        pdf_work_paths |= set(filter(None, (line.strip() for line in f)))
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
                    tmp_file.write(get_s3_bytes(pdf_s3, pdf))
                    tmp_file.flush()
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

    if args.stats:
        print_stats(args)
        return

    if args.beaker:
        submit_beaker_job(args)
        return

    # If you get this far, then you are doing inference and need a GPU
    check_sglang_version()
    check_torch_gpu_available()

    logger.info(f"Starting pipeline with PID {os.getpid()}")

    # Initialize the work queue
    await work_queue.initialize_queue()

    # Create a semaphore to control worker access
    # We only allow one worker to move forward with requests, until the server has no more requests in its queue
    # This lets us get full utilization by having many workers, but also to be outputting dolma docs as soon as possible
    # As soon as one worker is no longer saturating the gpu, the next one can start sending requests
    semaphore = asyncio.Semaphore(1)

    sglang_server = asyncio.create_task(sglang_server_host(args, semaphore))

    await sglang_server_ready()

    metrics_task = asyncio.create_task(metrics_reporter(work_queue))

    # Create worker tasks to process the queue concurrently.
    worker_tasks = []
    for i in range(args.workers):
        task = asyncio.create_task(worker(args, work_queue, semaphore, worker_id=i))
        worker_tasks.append(task)

    # Wait for all worker tasks to finish
    await asyncio.gather(*worker_tasks)

    # Wait for server to stop
    process_pool.shutdown(wait=False)

    sglang_server.cancel()
    metrics_task.cancel()
    logger.info("Work done")


if __name__ == "__main__":
    asyncio.run(main())
