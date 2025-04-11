
import os
import re
import glob
import boto3
import logging

from typing import Optional
from datasets import Dataset, load_dataset
from filelock import FileLock

from olmocr.data.renderpdf import get_pdf_media_box_width_height
from olmocr.prompts.anchor import get_anchor_text
from olmocr.s3_utils import parse_custom_id, parse_s3_path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Quiet logs from pypdf and smart open
logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("smart_open").setLevel(logging.ERROR)


def list_dataset_files(s3_glob_path: str):
    """
    Lists files in the specified S3 path that match the glob pattern.
    """
    if s3_glob_path.startswith("s3://"):
        s3 = boto3.client("s3")
        match = re.match(r"s3://([^/]+)/(.+)", s3_glob_path)
        if not match:
            logger.error(f"Invalid S3 path: {s3_glob_path}")
            raise ValueError(f"Invalid S3 path: {s3_glob_path}")

        bucket, prefix_pattern = match.groups()
        prefix = prefix_pattern.split("*")[0]  # Extract prefix before the wildcard
        paginator = s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

        files = []
        pattern = re.compile(prefix_pattern.replace("*", ".*"))
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if pattern.fullmatch(key):
                    files.append(f"s3://{bucket}/{key}")
        return files
    else:
        return glob.glob(s3_glob_path)


def load_jsonl_into_ds(s3_glob_path: str, first_n_files: Optional[int] = None) -> Dataset:
    """
    Loads JSONL files from the specified S3 path into a Hugging Face Dataset.
    """
    all_json_files = list_dataset_files(s3_glob_path)

    if first_n_files:
        all_json_files = all_json_files[:first_n_files]

    # Use datasets library to load JSON files from S3
    dataset = load_dataset(
        "json",
        data_files=all_json_files,
    )

    return dataset


def extract_openai_batch_response(example):
    custom_id = example.get("custom_id", None)

    # Parse the custom id into an s3 document path and page number (1indexed)
    s3_path, page_num = parse_custom_id(custom_id)

    response_body = example.get("response", {}).get("body", {})
    choices = response_body.get("choices", [])
    response = ""
    finish_reason = ""
    if choices:
        first_choice = choices[0]
        message = first_choice.get("message", {})
        response = message.get("content", "")
        finish_reason = first_choice.get("finish_reason", "")

    # TODO Maybe in the future we can parse the response (which is a structured JSON document itself)
    # into its own columns

    return {"s3_path": s3_path, "page_num": page_num, "response": response, "finish_reason": finish_reason}


def _cache_s3_file(s3_path: str, local_cache_dir: str):
    """
    Downloads an S3 object to a local cache directory, ensuring no two writers corrupt the same file.
    """
    bucket, key = parse_s3_path(s3_path)

    # Define the local file path
    local_file_path = os.path.join(local_cache_dir, bucket + "__" + key.replace("/", "_"))
    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
    lock_file = f"{local_file_path}.lock"

    # Use a file lock to prevent concurrent writes
    with FileLock(lock_file):
        if not os.path.exists(local_file_path):
            logger.info(f"Downloading {s3_path} to {local_file_path}")
            s3_client = boto3.client("s3", aws_access_key_id=os.getenv("DS_AWS_ACCESS_KEY_ID"), aws_secret_access_key=os.getenv("DS_AWS_SECRET_ACCESS_KEY"))
            s3_client.download_file(bucket, key, local_file_path)
        else:
            pass
            # logger.info(f"File {local_file_path} already exists, skipping download.")

    return local_file_path


def cache_s3_files(dataset: Dataset, pdf_cache_location: str, num_proc: int = 32) -> Dataset:
    """
    Caches all S3 paths in the dataset to the local cache directory.
    """

    # Define the download function to use in parallel processing
    def cache_file(example):
        s3_path = example["s3_path"]
        if s3_path:
            # Download the file and cache it locally
            local_path = _cache_s3_file(s3_path, pdf_cache_location)
            return {"local_pdf_path": local_path}
        return {"local_pdf_path": None}

    # Map the caching function to the dataset (with parallelism if needed)
    dataset = dataset.map(cache_file, num_proc=num_proc, load_from_cache_file=False)

    return dataset


def build_finetuning_dataset(response_glob_path: str, pdf_cache_location: Optional[str] = None, num_proc: int = 32) -> Dataset:
    if pdf_cache_location is None:
        pdf_cache_location = os.path.join(os.path.expanduser("~"), ".cache", "olmocr_pdfs")

    logger.info("Loading fine tuning dataset from OpenAI style batch responses")
    response_data = load_jsonl_into_ds(response_glob_path)
    response_data = response_data["train"]

    response_data = response_data.map(extract_openai_batch_response, remove_columns=response_data.column_names, num_proc=num_proc)

    # Don't include data where the model cut off due to a length issue, or moderation issue
    logger.info("Filtering on finish_reason == stop")
    final_dataset = response_data.filter(lambda x: x["finish_reason"] == "stop", num_proc=num_proc)

    # Cache all the s3_paths that were accessed to a local storage location,
    final_dataset = cache_s3_files(final_dataset, pdf_cache_location, num_proc)

    # Filter out pages where you cannot get an anchor text generated, to prevent errors during actual training
    def _can_create_anchor_text(example):
        try:
            anchor_text = get_anchor_text(example["local_pdf_path"], example["page_num"], pdf_engine="pdfreport", target_length=4000)
            _ = get_pdf_media_box_width_height(example["local_pdf_path"], example["page_num"])
            return anchor_text is not None
        except:
            logger.exception("Could not generate anchor text for file, be sure you have all dependencies installed")
            return False

    final_dataset = final_dataset.filter(_can_create_anchor_text, num_proc=num_proc)

    return final_dataset
