#!/usr/bin/env python3
"""
Prepares OlmOCR checkpoints for deployment by:
1. Validating the model architecture
2. Copying model files to destination (disk or S3)
3. Downloading required tokenizer files from Hugging Face

Supports model souping (averaging weights of multiple checkpoints).

Usage:
    python prepare_olmocr_checkpoint.py <source_path> <destination_path>

    source_path: Path to checkpoint (local or S3)
    destination_path: Where to save prepared checkpoint (local or S3)

For souping multiple checkpoints:
    python prepare_olmocr_checkpoint.py <source1> <source2> ... <destination>

    This will average the weights of all sources and prepare the souped checkpoint.

Examples:
    # Single local to local
    python prepare_olmocr_checkpoint.py /path/to/checkpoint /path/to/output

    # Souping multiple S3 to S3
    python prepare_olmocr_checkpoint.py s3://bucket/ckpt1 s3://bucket/ckpt2 s3://bucket/souped

    # Mixed souping
    python prepare_olmocr_checkpoint.py s3://bucket/ckpt1 /local/ckpt2 s3://bucket/souped
"""

import argparse
import concurrent.futures
import fnmatch
import json
import os
import shutil
import tempfile
from typing import Optional

import boto3
import requests
import torch
from botocore.exceptions import ClientError
from smart_open import smart_open
from tqdm import tqdm
from transformers import (
    AutoConfig,
    Qwen2_5_VLForConditionalGeneration,
    Qwen2VLForConditionalGeneration,
)

try:
    from safetensors.torch import load_file, save_file
except ImportError:
    raise ImportError("Please install safetensors: pip install safetensors")

from olmocr.cloud_utils import parse_s3_path

# Hugging Face model IDs for tokenizer files
HF_MODEL_IDS = {"Qwen2VLForConditionalGeneration": "Qwen/Qwen2-VL-7B-Instruct", "Qwen2_5_VLForConditionalGeneration": "Qwen/Qwen2.5-VL-7B-Instruct"}

# Required tokenizer files to download from Hugging Face
TOKENIZER_FILES = ["chat_template.json", "merges.txt", "preprocessor_config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json"]

# Supported model architectures
SUPPORTED_ARCHITECTURES = ["Qwen2VLForConditionalGeneration", "Qwen2_5_VLForConditionalGeneration"]

# Map architectures to corresponding model classes
MODEL_CLASS_MAP = {
    "Qwen2VLForConditionalGeneration": Qwen2VLForConditionalGeneration,
    "Qwen2_5_VLForConditionalGeneration": Qwen2_5_VLForConditionalGeneration,
}

# Files to exclude from copying (training-related files)
# Supports exact matches and glob patterns
EXCLUDED_FILES = {"optimizer.pt", "scheduler.pt", "rng_state.pth", "trainer_state.json", "training_args.bin", "*.pt", "*.pth"}

s3_client = boto3.client("s3")


def should_exclude_file(filename: str) -> bool:
    """Check if a file should be excluded based on EXCLUDED_FILES patterns."""
    for pattern in EXCLUDED_FILES:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


def is_s3_path(path: str) -> bool:
    """Check if a path is an S3 path."""
    return path.startswith("s3://")


def join_path(base: str, *parts: str) -> str:
    """Join paths for local and S3-style URIs."""
    if not parts:
        return base
    if is_s3_path(base):
        cleaned = [base.rstrip("/")]
        for part in parts:
            cleaned.append(part.strip("/"))
        return "/".join(segment for segment in cleaned if segment)
    return os.path.join(base, *parts)


def load_json_if_exists(path: str) -> Optional[dict]:
    """Load JSON from a path if it exists, otherwise return None."""
    try:
        with smart_open(path, "r") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in {"NoSuchKey", "404"}:
            return None
        raise
    except OSError as exc:
        if "No such file" in str(exc):
            return None
        raise


def load_adapter_config(source_path: str) -> Optional[dict]:
    """Return the LoRA adapter configuration if present for the given source."""
    adapter_config_path = join_path(source_path, "adapter_config.json")
    return load_json_if_exists(adapter_config_path)


def download_file_from_hf(filename: str, destination_dir: str, hf_base_url: str) -> None:
    """Download a file from Hugging Face model repository."""
    url = f"{hf_base_url}/{filename}"
    local_path = os.path.join(destination_dir, filename)

    print(f"Downloading {filename} from Hugging Face...")
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(local_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"Downloaded {filename}")


def detect_checkpoint_architecture(config_path: str) -> str:
    """Detect and validate the checkpoint architecture."""
    print(f"Detecting checkpoint architecture from {config_path}...")

    with smart_open(config_path, "r") as f:
        config_data = json.load(f)

    architectures = config_data.get("architectures", [])

    # Find the supported architecture
    detected_architecture = None
    for arch in architectures:
        if arch in SUPPORTED_ARCHITECTURES:
            detected_architecture = arch
            break

    if not detected_architecture:
        # Try to detect from model name
        model_name = config_data.get("name_or_path", "")
        if "Qwen2.5-VL" in model_name:
            detected_architecture = "Qwen2_5_VLForConditionalGeneration"
        elif "Qwen2-VL" in model_name:
            detected_architecture = "Qwen2VLForConditionalGeneration"
        else:
            raise ValueError(f"No supported architecture found. Expected one of {SUPPORTED_ARCHITECTURES} " f"but found: {architectures}")

    print(f"✓ Detected architecture: {detected_architecture}")
    return detected_architecture


def copy_local_to_local(source_dir: str, dest_dir: str) -> None:
    """Copy files from local directory to local directory."""
    os.makedirs(dest_dir, exist_ok=True)

    # Get list of files to copy
    files_to_copy = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            if should_exclude_file(file):
                print(f"Skipping excluded file: {file}")
                continue
            src_path = os.path.join(root, file)
            rel_path = os.path.relpath(src_path, source_dir)
            files_to_copy.append((src_path, os.path.join(dest_dir, rel_path)))

    print(f"Copying {len(files_to_copy)} files from {source_dir} to {dest_dir}...")

    for src_path, dst_path in tqdm(files_to_copy, desc="Copying files"):
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        shutil.copy2(src_path, dst_path)


def download_file_from_s3(bucket: str, key: str, local_path: str) -> None:
    """Download a single file from S3."""
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    s3_client.download_file(bucket, key, local_path)


def upload_file_to_s3(local_path: str, bucket: str, key: str) -> None:
    """Upload a single file to S3."""
    s3_client.upload_file(local_path, bucket, key)


def copy_s3_to_local(source_bucket: str, source_prefix: str, dest_dir: str) -> None:
    """Copy files from S3 to local directory."""
    os.makedirs(dest_dir, exist_ok=True)

    # List all objects in source
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=source_bucket, Prefix=source_prefix)

    download_tasks = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue

            filename = os.path.basename(key)
            if should_exclude_file(filename):
                print(f"Skipping excluded file: {filename}")
                continue

            rel_path = os.path.relpath(key, source_prefix)
            local_path = os.path.join(dest_dir, rel_path)
            download_tasks.append((source_bucket, key, local_path))

    print(f"Downloading {len(download_tasks)} files from s3://{source_bucket}/{source_prefix} to {dest_dir}...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(download_file_from_s3, bucket, key, local_path) for bucket, key, local_path in download_tasks]

        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Downloading"):
            future.result()


def copy_local_to_s3(source_dir: str, dest_bucket: str, dest_prefix: str) -> None:
    """Copy files from local directory to S3."""
    # Get list of files to upload
    upload_tasks = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            if should_exclude_file(file):
                print(f"Skipping excluded file: {file}")
                continue
            local_path = os.path.join(root, file)
            rel_path = os.path.relpath(local_path, source_dir)
            s3_key = os.path.join(dest_prefix, rel_path)
            upload_tasks.append((local_path, dest_bucket, s3_key))

    print(f"Uploading {len(upload_tasks)} files from {source_dir} to s3://{dest_bucket}/{dest_prefix}...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(upload_file_to_s3, local_path, bucket, key) for local_path, bucket, key in upload_tasks]

        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Uploading"):
            future.result()


def copy_s3_to_s3(source_bucket: str, source_prefix: str, dest_bucket: str, dest_prefix: str) -> None:
    """Copy files from S3 to S3."""
    # List all objects in source
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=source_bucket, Prefix=source_prefix)

    copy_tasks = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue

            filename = os.path.basename(key)
            if should_exclude_file(filename):
                print(f"Skipping excluded file: {filename}")
                continue

            rel_path = os.path.relpath(key, source_prefix)
            dest_key = os.path.join(dest_prefix, rel_path)
            copy_source = {"Bucket": source_bucket, "Key": key}
            copy_tasks.append((copy_source, dest_bucket, dest_key))

    print(f"Copying {len(copy_tasks)} files from s3://{source_bucket}/{source_prefix} to s3://{dest_bucket}/{dest_prefix}...")

    for copy_source, bucket, key in tqdm(copy_tasks, desc="Copying"):
        s3_client.copy_object(CopySource=copy_source, Bucket=bucket, Key=key)


def get_weight_files(dir_path: str) -> list[str]:
    """Get list of weight files (full paths) in the directory."""
    weight_files = []
    for root, _, files in os.walk(dir_path):
        for file in files:
            full_path = os.path.join(root, file)
            if (file.startswith("pytorch_model") and file.endswith(".bin")) or file.endswith(".safetensors"):
                weight_files.append(full_path)
    return weight_files


def merge_lora_adapter_checkpoint(adapter_dir: str, base_model_name: str, output_dir: str) -> str:
    """Merge a LoRA adapter into its base model and save the merged weights.

    Returns:
        The detected architecture string of the merged model.
    """
    try:
        from peft import PeftModel
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise ImportError("Merging LoRA adapters requires the `peft` package. Install it with `pip install peft`.") from exc

    print(f"Merging LoRA adapter from {adapter_dir} with base model '{base_model_name}'...")
    base_config = AutoConfig.from_pretrained(base_model_name, trust_remote_code=True)

    architecture = None
    for arch in base_config.architectures or []:
        if arch in MODEL_CLASS_MAP:
            architecture = arch
            break

    if architecture is None:
        raise ValueError(
            f"Base model '{base_model_name}' uses an unsupported architecture: {base_config.architectures}. "
            f"Supported architectures: {SUPPORTED_ARCHITECTURES}"
        )

    model_class = MODEL_CLASS_MAP[architecture]
    base_model = model_class.from_pretrained(
        base_model_name,
        trust_remote_code=True,
        torch_dtype="auto",
    )

    lora_model = PeftModel.from_pretrained(base_model, adapter_dir, is_trainable=False)
    merged_model = lora_model.merge_and_unload()
    merged_model = merged_model.to("cpu")

    if hasattr(merged_model, "config"):
        merged_model.config._name_or_path = base_model_name
        merged_model.config.base_model_name_or_path = base_model_name

    os.makedirs(output_dir, exist_ok=True)
    merged_model.save_pretrained(output_dir)
    print(f"✓ Saved merged model to {output_dir}")

    # Explicit cleanup
    del merged_model
    del lora_model
    del base_model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return architecture


def prepare_checkpoints(sources: list[str], dest_path: str) -> None:
    """Prepare OlmOCR checkpoint(s) for deployment, with support for souping."""
    print(f"Preparing {'souped ' if len(sources) > 1 else ''}checkpoint from {len(sources)} source(s) to {dest_path}")

    sources = [source.rstrip("/") for source in sources]
    dest_path = dest_path.rstrip("/")

    source_infos = []
    for source in sources:
        adapter_config = load_adapter_config(source)
        if adapter_config is not None:
            source_infos.append({"path": source, "is_lora": True, "adapter_config": adapter_config})
        else:
            config_path = join_path(source, "config.json")
            arch = detect_checkpoint_architecture(config_path)
            source_infos.append({"path": source, "is_lora": False, "architecture": arch})

    num_lora_sources = sum(1 for info in source_infos if info["is_lora"])
    final_architecture: Optional[str] = None

    if num_lora_sources > 0:
        if len(source_infos) > 1:
            raise ValueError("LoRA adapter checkpoints can only be processed individually, not during souping.")

        source_info = source_infos[0]
        source_path = source_info["path"]
        adapter_config = source_info["adapter_config"]
        base_model_name = adapter_config.get("base_model_name_or_path")
        if not base_model_name:
            raise ValueError("adapter_config.json is missing 'base_model_name_or_path'; cannot merge LoRA adapter.")

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter_local_dir = os.path.join(temp_dir, "adapter")
            print("\nDownloading LoRA adapter locally for merging...")
            if is_s3_path(source_path):
                bucket, prefix = parse_s3_path(source_path)
                copy_s3_to_local(bucket, prefix, adapter_local_dir)
            else:
                copy_local_to_local(source_path, adapter_local_dir)

            merged_dir = os.path.join(temp_dir, "merged")
            final_architecture = merge_lora_adapter_checkpoint(adapter_local_dir, base_model_name, merged_dir)

            print("\nCopying merged model files to destination...")
            if is_s3_path(dest_path):
                dest_bucket, dest_prefix = parse_s3_path(dest_path)
                copy_local_to_s3(merged_dir, dest_bucket, dest_prefix)
            else:
                copy_local_to_local(merged_dir, dest_path)
    else:
        architectures = [info["architecture"] for info in source_infos]
        if len(set(architectures)) > 1:
            raise ValueError("All sources must have the same architecture")

        final_architecture = architectures[0]

        if len(sources) == 1:
            source_path = sources[0]
            print("\nCopying model files...")
            if is_s3_path(source_path) and is_s3_path(dest_path):
                source_bucket, source_prefix = parse_s3_path(source_path)
                dest_bucket, dest_prefix = parse_s3_path(dest_path)
                copy_s3_to_s3(source_bucket, source_prefix, dest_bucket, dest_prefix)
            elif is_s3_path(source_path) and not is_s3_path(dest_path):
                source_bucket, source_prefix = parse_s3_path(source_path)
                copy_s3_to_local(source_bucket, source_prefix, dest_path)
            elif not is_s3_path(source_path) and is_s3_path(dest_path):
                dest_bucket, dest_prefix = parse_s3_path(dest_path)
                copy_local_to_s3(source_path, dest_bucket, dest_prefix)
            else:
                copy_local_to_local(source_path, dest_path)
        else:
            # Souping multiple checkpoints
            with tempfile.TemporaryDirectory() as temp_dir:
                # Download all sources to local temp dirs
                source_temps = []
                for i, source in enumerate(sources):
                    source_temp = os.path.join(temp_dir, f"source_{i}")
                    if is_s3_path(source):
                        bucket, prefix = parse_s3_path(source)
                        copy_s3_to_local(bucket, prefix, source_temp)
                    else:
                        copy_local_to_local(source, source_temp)
                    source_temps.append(source_temp)

                first_source = source_temps[0]

                # Get weight files
                weight_full_paths = get_weight_files(first_source)
                weight_rel_paths = [os.path.relpath(p, first_source) for p in weight_full_paths]

                # Verify others have same weight files
                for i in range(1, len(sources)):
                    other_dir = source_temps[i]
                    other_weights = [os.path.relpath(p, other_dir) for p in get_weight_files(other_dir)]
                    if set(other_weights) != set(weight_rel_paths):
                        raise ValueError(f"Source {sources[i]} has different weight files")

                # Create souped_dir
                souped_dir = os.path.join(temp_dir, "souped")
                # Copy first source (including its weights, which will be overwritten)
                copy_local_to_local(first_source, souped_dir)

                # Average weights
                for rel_path in tqdm(weight_rel_paths, desc="Averaging weight files"):
                    all_paths = [os.path.join(st, rel_path) for st in source_temps]
                    file_path = all_paths[0]
                    souped_path = os.path.join(souped_dir, rel_path)
                    os.makedirs(os.path.dirname(souped_path), exist_ok=True)

                    if file_path.endswith(".safetensors"):
                        sum_state = load_file(file_path, device="cpu")
                        # Store original dtypes for each tensor
                        original_dtypes = {k: v.dtype for k, v in sum_state.items()}
                        # Upconvert to at least fp32 for accurate averaging
                        for k in sum_state:
                            if sum_state[k].dtype in (torch.float16, torch.bfloat16):
                                sum_state[k] = sum_state[k].to(torch.float32)

                        for other_path in all_paths[1:]:
                            other_state = load_file(other_path, device="cpu")
                            if set(sum_state.keys()) != set(other_state.keys()):
                                raise ValueError(f"Key mismatch in {rel_path}")
                            for k in sum_state:
                                # Upconvert other state to match sum_state dtype
                                if other_state[k].dtype in (torch.float16, torch.bfloat16):
                                    other_state[k] = other_state[k].to(torch.float32)
                                sum_state[k] += other_state[k]
                            del other_state

                        n = len(all_paths)
                        for k in sum_state:
                            sum_state[k] /= n
                            # Cast back to original dtype
                            sum_state[k] = sum_state[k].to(original_dtypes[k])
                        save_file(sum_state, souped_path)
                    elif file_path.endswith(".bin"):
                        sum_state = torch.load(file_path, map_location="cpu")
                        # Store original dtypes for each tensor
                        original_dtypes = {k: v.dtype for k, v in sum_state.items()}
                        # Upconvert to at least fp32 for accurate averaging
                        for k in sum_state:
                            if sum_state[k].dtype in (torch.float16, torch.bfloat16):
                                sum_state[k] = sum_state[k].to(torch.float32)

                        for other_path in all_paths[1:]:
                            other_state = torch.load(other_path, map_location="cpu")
                            if set(sum_state.keys()) != set(other_state.keys()):
                                raise ValueError(f"Key mismatch in {rel_path}")
                            for k in sum_state:
                                # Upconvert other state to match sum_state dtype
                                if other_state[k].dtype in (torch.float16, torch.bfloat16):
                                    other_state[k] = other_state[k].to(torch.float32)
                                sum_state[k] += other_state[k]
                            del other_state

                        n = len(all_paths)
                        for k in sum_state:
                            sum_state[k] /= n
                            # Cast back to original dtype
                            sum_state[k] = sum_state[k].to(original_dtypes[k])
                        torch.save(sum_state, souped_path)
                    else:
                        print(f"Skipping unknown weight file: {rel_path}")
                        continue

                # Now copy souped_dir to dest_path
                print("\nCopying souped model files to destination...")
                if is_s3_path(dest_path):
                    dest_bucket, dest_prefix = parse_s3_path(dest_path)
                    copy_local_to_s3(souped_dir, dest_bucket, dest_prefix)
                else:
                    copy_local_to_local(souped_dir, dest_path)

    if final_architecture is None:
        raise ValueError("Unable to determine the architecture of the prepared checkpoint.")

    hf_model_id = HF_MODEL_IDS[final_architecture]
    hf_base_url = f"https://huggingface.co/{hf_model_id}/resolve/main"
    print(f"Using HuggingFace model: {hf_model_id}")

    # Download tokenizer files from Hugging Face
    print("\nDownloading tokenizer files from Hugging Face...")

    if is_s3_path(dest_path):
        # Download to temp directory first, then upload to S3
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download files
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(download_file_from_hf, filename, temp_dir, hf_base_url) for filename in TOKENIZER_FILES]
                for future in concurrent.futures.as_completed(futures):
                    future.result()

            # Upload to S3
            dest_bucket, dest_prefix = parse_s3_path(dest_path)
            upload_tasks = []
            for filename in TOKENIZER_FILES:
                local_path = os.path.join(temp_dir, filename)
                s3_key = os.path.join(dest_prefix, filename)
                upload_tasks.append((local_path, dest_bucket, s3_key))

            print("Uploading tokenizer files to S3...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(upload_file_to_s3, local_path, bucket, key) for local_path, bucket, key in upload_tasks]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
    else:
        # Download directly to destination
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(download_file_from_hf, filename, dest_path, hf_base_url) for filename in TOKENIZER_FILES]
            for future in concurrent.futures.as_completed(futures):
                future.result()

    print(f"\n✓ Successfully prepared checkpoint at {dest_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Prepare OlmOCR checkpoint for deployment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:")[1],  # Use the docstring for epilog
    )
    parser.add_argument("paths", nargs="+", help="One or more source paths followed by destination path (local or S3)")

    args = parser.parse_args()

    if len(args.paths) < 2:
        parser.error("At least one source and one destination required")

    sources = args.paths[:-1]
    destination = args.paths[-1]

    try:
        prepare_checkpoints(sources, destination)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
