import base64
import concurrent.futures
import glob
import hashlib
import logging
import os
import time
from io import BytesIO, TextIOWrapper
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import boto3
import requests  # type: ignore
import zstandard as zstd
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError
from google.cloud import storage
from tqdm import tqdm

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ============ Path Type Helper Functions ============


def is_s3_path(path: str) -> bool:
    """Check if path is an S3 or Weka path (both use boto3)."""
    return path.startswith("s3://") or path.startswith("weka://")


def is_gcs_path(path: str) -> bool:
    """Check if path is a GCS path."""
    return path.startswith("gs://")


def is_cloud_path(path: str) -> bool:
    """Check if path is any cloud storage path."""
    return is_s3_path(path) or is_gcs_path(path)


def parse_cloud_path(cloud_path: str) -> tuple[str, str]:
    """Parse a cloud storage path into bucket and key components.

    Supports s3://, gs://, and weka:// prefixes.
    """
    if not (cloud_path.startswith("s3://") or cloud_path.startswith("gs://") or cloud_path.startswith("weka://")):
        raise ValueError("cloud_path must start with s3://, gs://, or weka://")
    parsed = urlparse(cloud_path)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    return bucket, key


# Backwards compatibility alias
def parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Backwards compatibility alias for parse_cloud_path."""
    return parse_cloud_path(s3_path)


def expand_s3_glob(s3_client, s3_glob: str) -> dict[str, str]:
    """
    Expand an S3 path that may or may not contain wildcards (e.g., *.pdf).
    Returns a dict of {'s3://bucket/key': etag} for each matching object.
    Raises a ValueError if nothing is found or if a bare prefix was provided by mistake.
    """
    parsed = urlparse(s3_glob)
    if not parsed.scheme.startswith("s3"):
        raise ValueError("Path must start with s3://")

    bucket = parsed.netloc
    raw_path = parsed.path.lstrip("/")

    # Case 1: We have a wildcard - find the longest fixed prefix before any wildcard
    # Note: '?' is not supported as it conflicts with URL query parameters
    if any(wc in raw_path for wc in ["*", "[", "]"]):
        # Find the first wildcard character and use everything before it as the S3 prefix
        first_wildcard = min((raw_path.index(wc) for wc in ["*", "[", "]"] if wc in raw_path))
        prefix = raw_path[:first_wildcard]

        paginator = s3_client.get_paginator("list_objects_v2")
        matched = {}
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if glob.fnmatch.fnmatch(key, raw_path):
                    matched[f"s3://{bucket}/{key}"] = obj["ETag"].strip('"')
        return matched

    # Case 2: No wildcard → single file or a bare prefix
    try:
        # Attempt to head a single file
        resp = s3_client.head_object(Bucket=bucket, Key=raw_path)

        if resp["ContentType"] == "application/x-directory":
            raise ValueError(f"'{s3_glob}' appears to be a folder. " f"Use a wildcard (e.g., '{s3_glob.rstrip('/')}/*.pdf') to match files.")

        return {f"s3://{bucket}/{raw_path}": resp["ETag"].strip('"')}
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            # Check if it's actually a folder with contents
            check_prefix = raw_path if raw_path.endswith("/") else raw_path + "/"
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=check_prefix):
                if page.get("Contents"):
                    raise ValueError(f"'{s3_glob}' appears to be a folder. " f"Use a wildcard (e.g., '{s3_glob.rstrip('/')}/*.pdf') to match files.")
            raise ValueError(f"No object or prefix found at '{s3_glob}'. Check your path or add a wildcard.")
        else:
            raise


def get_s3_bytes(s3_client, s3_path: str, start_index: Optional[int] = None, end_index: Optional[int] = None) -> bytes:
    """Download bytes from an S3 or Weka path (both use boto3)."""
    is_s3_or_weka = is_s3_path(s3_path)

    # Fall back for local files
    if not is_s3_or_weka:
        if os.path.exists(s3_path):
            assert start_index is None and end_index is None, "Range query not supported yet"
            with open(s3_path, "rb") as f:
                return f.read()
        else:
            logger.error(f"Could not find local file {s3_path}")
            raise Exception(f"Could not find local file {s3_path}")

    bucket, key = parse_s3_path(s3_path)

    # Build the range header if start_index and/or end_index are specified
    range_header = None
    if start_index is not None and end_index is not None:
        # Range: bytes=start_index-end_index
        range_value = f"bytes={start_index}-{end_index}"
        range_header = {"Range": range_value}
    elif start_index is not None and end_index is None:
        # Range: bytes=start_index-
        range_value = f"bytes={start_index}-"
        range_header = {"Range": range_value}
    elif start_index is None and end_index is not None:
        # Range: bytes=-end_index (last end_index bytes)
        range_value = f"bytes=-{end_index}"
        range_header = {"Range": range_value}

    if range_header:
        obj = s3_client.get_object(Bucket=bucket, Key=key, Range=range_header["Range"])
    else:
        obj = s3_client.get_object(Bucket=bucket, Key=key)

    return obj["Body"].read()


def get_s3_bytes_with_backoff(s3_client, pdf_s3_path, max_retries: int = 8, backoff_factor: int = 2):
    attempt = 0

    while attempt < max_retries:
        try:
            return get_s3_bytes(s3_client, pdf_s3_path)
        except ClientError as e:
            # Check for some error kinds AccessDenied error and raise immediately
            if e.response["Error"]["Code"] in ("AccessDenied", "NoSuchKey"):
                logger.error(f"{e.response['Error']['Code']} error when trying to access {pdf_s3_path}: {e}")
                raise
            else:
                wait_time = backoff_factor**attempt
                logger.warning(f"Attempt {attempt+1} failed to get_s3_bytes for {pdf_s3_path}: {e}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                attempt += 1
        except Exception as e:
            wait_time = backoff_factor**attempt
            logger.warning(f"Attempt {attempt+1} failed to get_s3_bytes for {pdf_s3_path}: {e}. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
            attempt += 1

    logger.error(f"Failed to get_s3_bytes for {pdf_s3_path} after {max_retries} retries.")
    raise Exception("Failed to get_s3_bytes after retries")


def put_s3_bytes(s3_client, s3_path: str, data: bytes):
    bucket, key = parse_s3_path(s3_path)

    s3_client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="text/plain; charset=utf-8")


def parse_custom_id(custom_id: str) -> tuple[str, int]:
    s3_path = custom_id[: custom_id.rindex("-")]
    page_num = int(custom_id[custom_id.rindex("-") + 1 :])
    return s3_path, page_num


def download_zstd_csv(s3_client, s3_path):
    """Download and decompress a .zstd CSV file from S3."""
    try:
        compressed_data = get_s3_bytes(s3_client, s3_path)
        dctx = zstd.ZstdDecompressor()
        decompressed = dctx.decompress(compressed_data)
        text_stream = TextIOWrapper(BytesIO(decompressed), encoding="utf-8")
        lines = text_stream.readlines()
        logger.info(f"Downloaded and decompressed {s3_path}")
        return lines
    except s3_client.exceptions.NoSuchKey:
        logger.info(f"No existing {s3_path} found in s3, starting fresh.")
        return []


def upload_zstd_csv(s3_client, s3_path, lines):
    """Compress and upload a list of lines as a .zstd CSV file to S3."""
    joined_text = "\n".join(lines)
    compressor = zstd.ZstdCompressor()
    compressed = compressor.compress(joined_text.encode("utf-8"))
    put_s3_bytes(s3_client, s3_path, compressed)
    logger.info(f"Uploaded compressed {s3_path}")


def is_running_on_gcp():
    """Check if the script is running on a Google Cloud Platform (GCP) instance."""
    try:
        # GCP metadata server URL to check instance information
        response = requests.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/", headers={"Metadata-Flavor": "Google"}, timeout=1  # Set a short timeout
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def download_directory(model_choices: List[str], local_dir: str):
    """
    Download the model to a specified local directory.
    The function will attempt to download from the first available source in the provided list.
    Supports Weka (weka://), Google Cloud Storage (gs://), and Amazon S3 (s3://) links.

    Args:
        model_choices (List[str]): List of model paths (weka://, gs://, or s3://).
        local_dir (str): Local directory path where the model will be downloaded.

    Raises:
        ValueError: If no valid model path is found in the provided choices.
    """
    local_path = Path(os.path.expanduser(local_dir))
    local_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Local directory set to: {local_path}")

    # Reorder model_choices to prioritize weka:// links
    weka_choices = [path for path in model_choices if path.startswith("weka://")]

    # This is so hacky, but if you are on beaker/pluto, don't use weka
    if os.environ.get("BEAKER_NODE_HOSTNAME", "").lower().startswith("pluto") or os.environ.get("BEAKER_NODE_HOSTNAME", "").lower().startswith("augusta"):
        weka_choices = []

    other_choices = [path for path in model_choices if not path.startswith("weka://")]
    prioritized_choices = weka_choices + other_choices

    for model_path in prioritized_choices:
        logger.info(f"Attempting to download from: {model_path}")
        try:
            if model_path.startswith("weka://"):
                download_dir_from_storage(model_path, str(local_path), storage_type="weka")
                logger.info(f"Successfully downloaded model from Weka: {model_path}")
                return
            elif model_path.startswith("gs://"):
                download_dir_from_storage(model_path, str(local_path), storage_type="gcs")
                logger.info(f"Successfully downloaded model from Google Cloud Storage: {model_path}")
                return
            elif model_path.startswith("s3://"):
                download_dir_from_storage(model_path, str(local_path), storage_type="s3")
                logger.info(f"Successfully downloaded model from S3: {model_path}")
                return
            else:
                logger.warning(f"Unsupported model path scheme: {model_path}")
        except Exception as e:
            logger.error(f"Failed to download from {model_path}: {e}")
            continue

    raise ValueError("Failed to download the model from all provided sources.")


def download_dir_from_storage(storage_path: str, local_dir: str, storage_type: str):
    """
    Generalized function to download model files from different storage services
    to a local directory, syncing using MD5 hashes where possible.

    Args:
        storage_path (str): The path to the storage location (weka://, gs://, or s3://).
        local_dir (str): The local directory where files will be downloaded.
        storage_type (str): Type of storage ('weka', 'gcs', or 's3').

    Raises:
        ValueError: If the storage type is unsupported or credentials are missing.
    """
    bucket_name, prefix = parse_s3_path(storage_path)
    total_files = 0
    objects = []

    if storage_type == "gcs":
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix))
        total_files = len(blobs)
        logger.info(f"Found {total_files} files in GCS bucket '{bucket_name}' with prefix '{prefix}'.")

        def should_download(blob, local_file_path):
            return compare_hashes_gcs(blob, local_file_path)

        def download_blob(blob, local_file_path):
            try:
                blob.download_to_filename(local_file_path)
                logger.info(f"Successfully downloaded {blob.name} to {local_file_path}")
            except Exception as e:
                logger.error(f"Failed to download {blob.name} to {local_file_path}: {e}")
                raise

        items = blobs
    elif storage_type in ("s3", "weka"):
        if storage_type == "weka":
            weka_access_key = os.getenv("WEKA_ACCESS_KEY_ID")
            weka_secret_key = os.getenv("WEKA_SECRET_ACCESS_KEY")
            if not weka_access_key or not weka_secret_key:
                raise ValueError("WEKA_ACCESS_KEY_ID and WEKA_SECRET_ACCESS_KEY must be set for Weka access.")
            endpoint_url = "https://weka-aus.beaker.org:9000"
            boto3_config = Config(max_pool_connections=500, signature_version="s3v4", retries={"max_attempts": 10, "mode": "standard"})
            s3_client = boto3.client(
                "s3", endpoint_url=endpoint_url, aws_access_key_id=weka_access_key, aws_secret_access_key=weka_secret_key, config=boto3_config
            )
        else:
            s3_client = boto3.client("s3", config=Config(max_pool_connections=500))

        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        for page in pages:
            if "Contents" in page:
                objects.extend(page["Contents"])
            else:
                logger.warning(f"No contents found in page: {page}")
        total_files = len(objects)
        logger.info(f"Found {total_files} files in {'Weka' if storage_type == 'weka' else 'S3'} bucket '{bucket_name}' with prefix '{prefix}'.")

        transfer_config = TransferConfig(
            multipart_threshold=8 * 1024 * 1024, multipart_chunksize=8 * 1024 * 1024, max_concurrency=10, use_threads=True  # Reduced for WekaFS compatibility
        )

        def should_download(obj, local_file_path):
            return compare_hashes_s3(obj, local_file_path, storage_type)

        def download_blob(obj, local_file_path):
            logger.info(f"Starting download of {obj['Key']} to {local_file_path}")
            try:
                with open(local_file_path, "wb") as f:
                    s3_client.download_fileobj(bucket_name, obj["Key"], f, Config=transfer_config)
                logger.info(f"Successfully downloaded {obj['Key']} to {local_file_path}")
            except Exception as e:
                logger.error(f"Failed to download {obj['Key']} to {local_file_path}: {e}")
                raise

        items = objects
    else:
        raise ValueError(f"Unsupported storage type: {storage_type}")

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for item in items:
            if storage_type == "gcs":
                relative_path = os.path.relpath(item.name, prefix)
            else:
                relative_path = os.path.relpath(item["Key"], prefix)
            local_file_path = os.path.join(local_dir, relative_path)
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            if should_download(item, local_file_path):
                futures.append(executor.submit(download_blob, item, local_file_path))
            else:
                total_files -= 1  # Decrement total_files as we're skipping this file

        if total_files > 0:
            for future in tqdm(concurrent.futures.as_completed(futures), total=total_files, desc=f"Downloading from {storage_type.upper()}"):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Error occurred during download: {e}")
        else:
            logger.info("All files are up-to-date. No downloads needed.")

    logger.info(f"Downloaded model from {storage_type.upper()} to {local_dir}")


def compare_hashes_gcs(blob, local_file_path: str) -> bool:
    """Compare MD5 hashes for GCS blobs."""
    if os.path.exists(local_file_path):
        remote_md5_base64 = blob.md5_hash
        hash_md5 = hashlib.md5()
        with open(local_file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        local_md5 = hash_md5.digest()
        remote_md5 = base64.b64decode(remote_md5_base64)
        if remote_md5 == local_md5:
            logger.info(f"File '{local_file_path}' already up-to-date. Skipping download.")
            return False
        else:
            logger.info(f"File '{local_file_path}' differs from GCS. Downloading.")
            return True
    else:
        logger.info(f"File '{local_file_path}' does not exist locally. Downloading.")
        return True


def compare_hashes_s3(obj, local_file_path: str, storage_type: str) -> bool:
    """Compare MD5 hashes or sizes for S3 objects (including Weka)."""
    if os.path.exists(local_file_path):
        if storage_type == "weka":
            return True
        else:
            etag = obj["ETag"].strip('"')
            if "-" in etag:
                # Multipart upload, compare sizes
                remote_size = obj["Size"]
                local_size = os.path.getsize(local_file_path)
                if remote_size == local_size:
                    logger.info(f"File '{local_file_path}' size matches remote multipart file. Skipping download.")
                    return False
                else:
                    logger.info(f"File '{local_file_path}' size differs from remote multipart file. Downloading.")
                    return True
            else:
                hash_md5 = hashlib.md5()
                with open(local_file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        hash_md5.update(chunk)
                local_md5 = hash_md5.hexdigest()
                if etag == local_md5:
                    logger.info(f"File '{local_file_path}' already up-to-date. Skipping download.")
                    return False
                else:
                    logger.info(f"File '{local_file_path}' differs from remote. Downloading.")
                    return True
    else:
        logger.info(f"File '{local_file_path}' does not exist locally. Downloading.")
        return True


# ============ GCS Helper Functions ============


def expand_gcs_glob(gcs_client, gcs_glob: str) -> dict[str, str]:
    """
    Expand a GCS path that may or may not contain wildcards (e.g., *.pdf).
    Returns a dict of {'gs://bucket/key': md5_hash} for each matching object.
    Raises a ValueError if nothing is found or if a bare prefix was provided by mistake.
    """
    parsed = urlparse(gcs_glob)
    if parsed.scheme != "gs":
        raise ValueError("Path must start with gs://")

    bucket_name = parsed.netloc
    raw_path = parsed.path.lstrip("/")

    bucket = gcs_client.bucket(bucket_name)

    # Case 1: We have a wildcard - find the longest fixed prefix before any wildcard
    # Note: '?' is supported for GCS glob patterns
    if any(wc in raw_path for wc in ["*", "?", "[", "]"]):
        # Find the first wildcard character and use everything before it as the GCS prefix
        first_wildcard = min((raw_path.index(wc) for wc in ["*", "?", "[", "]"] if wc in raw_path))
        prefix = raw_path[:first_wildcard]

        blobs = bucket.list_blobs(prefix=prefix)
        matched = {}
        for blob in blobs:
            if glob.fnmatch.fnmatch(blob.name, raw_path):
                # Use md5_hash if available, otherwise use crc32c
                hash_val = blob.md5_hash or blob.crc32c or ""
                matched[f"gs://{bucket_name}/{blob.name}"] = hash_val
        return matched

    # Case 2: No wildcard -> single file or a bare prefix
    blob = bucket.blob(raw_path)
    if blob.exists():
        blob.reload()  # Load metadata
        hash_val = blob.md5_hash or blob.crc32c or ""
        return {f"gs://{bucket_name}/{raw_path}": hash_val}

    # Check if it's actually a folder with contents
    check_prefix = raw_path if raw_path.endswith("/") else raw_path + "/"
    blobs = list(bucket.list_blobs(prefix=check_prefix, max_results=1))
    if blobs:
        raise ValueError(f"'{gcs_glob}' appears to be a folder. " f"Use a wildcard (e.g., '{gcs_glob.rstrip('/')}/*.pdf') to match files.")
    raise ValueError(f"No object or prefix found at '{gcs_glob}'. Check your path or add a wildcard.")


def get_gcs_bytes(gcs_client, gcs_path: str, start_index: Optional[int] = None, end_index: Optional[int] = None) -> bytes:
    """Download bytes from a GCS path with optional range query support.

    Raises:
        FileNotFoundError: If the object doesn't exist in GCS
    """
    from google.api_core.exceptions import NotFound

    bucket_name, key = parse_cloud_path(gcs_path)
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(key)
    try:
        return blob.download_as_bytes(start=start_index, end=end_index)
    except NotFound:
        raise FileNotFoundError(f"GCS object not found: {gcs_path}")


def get_gcs_bytes_with_backoff(gcs_client, gcs_path: str, max_retries: int = 8, backoff_factor: int = 2) -> bytes:
    """Download bytes from a GCS path with exponential backoff retry logic.

    Raises:
        FileNotFoundError: If the object doesn't exist in GCS (not retried)
        PermissionError: If access is forbidden (not retried)
    """
    from google.api_core.exceptions import Forbidden

    attempt = 0
    while attempt < max_retries:
        try:
            return get_gcs_bytes(gcs_client, gcs_path)
        except (FileNotFoundError, PermissionError):
            # Don't retry these - they won't succeed on retry
            raise
        except Forbidden as e:
            # Convert to standard PermissionError
            raise PermissionError(f"GCS access forbidden: {gcs_path}") from e
        except Exception as e:
            wait_time = backoff_factor**attempt
            logger.warning(f"Attempt {attempt + 1} failed for {gcs_path}: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
            attempt += 1

    logger.error(f"Failed to get_gcs_bytes for {gcs_path} after {max_retries} retries.")
    raise Exception(f"Failed to get_gcs_bytes for {gcs_path} after {max_retries} retries")


def put_gcs_bytes(gcs_client, gcs_path: str, data: bytes):
    """Upload bytes to a GCS path."""
    bucket_name, key = parse_cloud_path(gcs_path)
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(key)
    blob.upload_from_string(data, content_type="application/octet-stream")


def download_zstd_csv_gcs(gcs_client, gcs_path: str) -> List[str]:
    """Download and decompress a .zstd CSV file from GCS."""
    try:
        compressed_data = get_gcs_bytes(gcs_client, gcs_path)
        dctx = zstd.ZstdDecompressor()
        decompressed = dctx.decompress(compressed_data)
        text_stream = TextIOWrapper(BytesIO(decompressed), encoding="utf-8")
        lines = text_stream.readlines()
        logger.info(f"Downloaded and decompressed {gcs_path}")
        return lines
    except FileNotFoundError:
        logger.info(f"No existing {gcs_path} found in GCS, starting fresh.")
        return []


def upload_zstd_csv_gcs(gcs_client, gcs_path: str, lines: List[str]):
    """Compress and upload a list of lines as a .zstd CSV file to GCS."""
    joined_text = "\n".join(lines)
    compressor = zstd.ZstdCompressor()
    compressed = compressor.compress(joined_text.encode("utf-8"))
    put_gcs_bytes(gcs_client, gcs_path, compressed)
    logger.info(f"Uploaded compressed {gcs_path}")


# ============ Unified Cloud Interface Functions ============


def get_cloud_bytes(
    path: str,
    s3_client=None,
    gcs_client=None,
    start_index: Optional[int] = None,
    end_index: Optional[int] = None,
) -> bytes:
    """Download bytes from any cloud path or local file.

    Args:
        path: Local file path, s3://, gs://, or weka:// path
        s3_client: boto3 S3 client (required for s3:// or weka:// paths)
        gcs_client: GCS storage client (required for gs:// paths)
        start_index: Optional start byte for range query
        end_index: Optional end byte for range query

    Returns:
        bytes: The file contents

    Raises:
        ValueError: If required client is not provided for cloud paths
        FileNotFoundError: If local file doesn't exist
    """
    if not is_cloud_path(path):
        if os.path.exists(path):
            with open(path, "rb") as f:
                if start_index is not None or end_index is not None:
                    if start_index is not None:
                        f.seek(start_index)
                    if end_index is not None:
                        return f.read(end_index - (start_index or 0) + 1)
                return f.read()
        else:
            raise FileNotFoundError(f"Could not find local file {path}")

    if is_gcs_path(path):
        if gcs_client is None:
            raise ValueError("gcs_client required for gs:// paths")
        return get_gcs_bytes(gcs_client, path, start_index, end_index)

    # S3 or Weka path
    if s3_client is None:
        raise ValueError("s3_client required for s3:// or weka:// paths")
    return get_s3_bytes(s3_client, path, start_index, end_index)


def get_cloud_bytes_with_backoff(
    path: str,
    s3_client=None,
    gcs_client=None,
    max_retries: int = 8,
    backoff_factor: int = 2,
) -> bytes:
    """Download bytes with exponential backoff, works for any path type.

    Args:
        path: Local file path, s3://, gs://, or weka:// path
        s3_client: boto3 S3 client (required for s3:// or weka:// paths)
        gcs_client: GCS storage client (required for gs:// paths)
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for exponential backoff

    Returns:
        bytes: The file contents

    Raises:
        ValueError: If required client is not provided for cloud paths
        FileNotFoundError: If local file doesn't exist
        Exception: If all retries are exhausted
    """
    if not is_cloud_path(path):
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        else:
            raise FileNotFoundError(f"Could not find local file {path}")

    if is_gcs_path(path):
        if gcs_client is None:
            raise ValueError("gcs_client required for gs:// paths")
        return get_gcs_bytes_with_backoff(gcs_client, path, max_retries, backoff_factor)

    # S3 or Weka path
    if s3_client is None:
        raise ValueError("s3_client required for s3:// or weka:// paths")
    return get_s3_bytes_with_backoff(s3_client, path, max_retries, backoff_factor)
