#!/usr/bin/env python3
"""
Compresses OlmOCR checkpoints using FP8 quantization:
1. Loads model from source (local or S3)
2. Applies FP8 dynamic quantization with optional calibration dataset
3. Saves compressed model to destination (local or S3)

Usage:
    python compress_checkpoint.py <source_path> <destination_path> --recipe <recipe_path> [--num-calibration-samples N] [--calibration-pdfs PDF1+PDF2+...]

    source_path: Path to checkpoint (local or S3)
    destination_path: Where to save compressed checkpoint (local or S3)
    recipe_path: Path to quantization config YAML file
    num_calibration_samples: Number of calibration samples to use (default: 512, set to 0 to disable)
    calibration_pdfs: Glob pattern for PDF paths to use for calibration (required when num_calibration_samples > 0)
"""

import argparse
import asyncio
import base64
import glob
import json
import os
import random
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple, Union

import boto3
import torch
from datasets import Dataset
from llmcompressor import oneshot
from PIL import Image
from transformers import (
    AutoProcessor,
    AutoTokenizer,
    Qwen2_5_VLForConditionalGeneration,
    Qwen2VLForConditionalGeneration,
)

from olmocr.pipeline import build_page_query
from olmocr.cloud_utils import parse_s3_path

s3_client = boto3.client("s3")


def get_calibration_pdfs(num_samples: int, pdf_paths: List[str]) -> List[str]:
    """Get calibration PDFs from provided paths.

    Args:
        num_samples: Number of samples to use
        pdf_paths: List of local PDF paths

    Returns:
        List of valid PDF paths
    """
    print(f"Using {len(pdf_paths)} provided calibration PDFs")

    # If more PDFs provided than needed, randomly sample
    if len(pdf_paths) > num_samples:
        pdf_paths = random.sample(pdf_paths, num_samples)
        print(f"Randomly sampled {num_samples} PDFs from provided paths")

    # Verify all PDFs exist
    valid_paths = []
    for path in pdf_paths:
        if os.path.exists(path) and path.endswith(".pdf"):
            valid_paths.append(path)
        else:
            print(f"  Warning: Skipping invalid path: {path}")

    if not valid_paths:
        raise ValueError("No valid PDF paths found in the provided list")

    print(f"Using {len(valid_paths)} valid calibration PDFs")
    return valid_paths


async def prepare_calibration_dataset(pdf_paths: List[str], processor) -> Dataset:
    """Prepare calibration dataset from PDFs using build_page_query."""
    dataset_items = []

    for pdf_path in pdf_paths:
        # Get first page of each PDF (page 0)
        query = await build_page_query(pdf_path, page=0, target_longest_image_dim=1024)

        # Extract the messages
        messages = query["messages"]

        # Extract images from the message content
        images = []
        for message in messages:
            if message.get("role") == "user":
                content = message.get("content", [])
                for item in content:
                    if item.get("type") == "image_url":
                        image_url = item["image_url"]["url"]
                        # Extract base64 image data
                        if image_url.startswith("data:image"):
                            base64_str = image_url.split(",")[1]
                            image_bytes = base64.b64decode(base64_str)
                            image = Image.open(BytesIO(image_bytes))
                            images.append(image)

        # Apply chat template to get the text
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

        # Process with tokenizer
        inputs = processor(
            text=[text],
            images=images if images else None,
            padding=False,
            max_length=8192,
            truncation=True,
        )

        dataset_items.append(inputs)

    # Convert list of dicts to HuggingFace Dataset
    if dataset_items:
        # Create dataset in batches to avoid overflow
        batch_size = 50  # Process in smaller batches
        all_datasets = []

        for i in range(0, len(dataset_items), batch_size):
            batch = dataset_items[i : i + batch_size]
            # Flatten the batch into a dict of lists
            batch_dict = {}
            for key in batch[0].keys():
                batch_dict[key] = [item[key] for item in batch]

            # Create dataset for this batch
            batch_dataset = Dataset.from_dict(batch_dict)
            all_datasets.append(batch_dataset)

        # Concatenate all batch datasets
        if len(all_datasets) == 1:
            return all_datasets[0]
        else:
            from datasets import concatenate_datasets

            return concatenate_datasets(all_datasets)
    else:
        return Dataset.from_dict({})


def is_s3_path(path: str) -> bool:
    """Check if a path is an S3 path."""
    return path.startswith("s3://")


def download_s3_to_local(bucket: str, prefix: str, local_dir: str) -> None:
    """Download all files from S3 prefix to local directory."""
    os.makedirs(local_dir, exist_ok=True)

    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    print(f"Downloading checkpoint from s3://{bucket}/{prefix} to {local_dir}...")

    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue

            rel_path = os.path.relpath(key, prefix)
            local_path = os.path.join(local_dir, rel_path)

            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            s3_client.download_file(bucket, key, local_path)
            print(f"  Downloaded {rel_path}")


def upload_local_to_s3(local_dir: str, bucket: str, prefix: str) -> None:
    """Upload all files from local directory to S3."""
    print(f"Uploading compressed checkpoint from {local_dir} to s3://{bucket}/{prefix}...")

    for root, _, files in os.walk(local_dir):
        for file in files:
            local_path = os.path.join(root, file)
            rel_path = os.path.relpath(local_path, local_dir)
            s3_key = os.path.join(prefix, rel_path)

            s3_client.upload_file(local_path, bucket, s3_key)
            print(f"  Uploaded {rel_path}")


def load_model_and_tokenizer(
    source_path: str,
) -> Tuple[Union[Qwen2VLForConditionalGeneration, Qwen2_5_VLForConditionalGeneration], AutoTokenizer, Optional[str]]:
    """Load model and tokenizer from source path (local or S3)."""
    if is_s3_path(source_path):
        # Download from S3 to temporary directory
        temp_dir = tempfile.mkdtemp()
        bucket, prefix = parse_s3_path(source_path)
        download_s3_to_local(bucket, prefix, temp_dir)
        model_path = temp_dir
    else:
        model_path = source_path
        temp_dir = None

    # Read config to determine model architecture
    config_path = os.path.join(model_path, "config.json")
    with open(config_path, "r") as f:
        config = json.load(f)

    # Get model name from config
    model_name = config.get("name_or_path", "")

    print(f"Loading model from {model_path}...")

    # Load appropriate model class based on name
    if "Qwen2.5-VL" in model_name:
        print("Detected Qwen2.5-VL model")
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_path, device_map="auto", torch_dtype="auto")
    elif "Qwen2-VL" in model_name:
        print("Detected Qwen2-VL model")
        model = Qwen2VLForConditionalGeneration.from_pretrained(model_path, device_map="auto", torch_dtype="auto")
    else:
        # Default to checking architectures list
        architectures = config.get("architectures", [])
        if "Qwen2_5_VLForConditionalGeneration" in architectures:
            print("Detected Qwen2.5-VL model from architectures")
            model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_path, device_map="auto", torch_dtype="auto")
        else:
            print("Detected Qwen2-VL model from architectures")
            model = Qwen2VLForConditionalGeneration.from_pretrained(model_path, device_map="auto", torch_dtype="auto")

    print(f"Loading tokenizer from {model_path}...")
    tokenizer = AutoTokenizer.from_pretrained(model_path)

    return model, tokenizer, temp_dir


def copy_additional_files(source_path: str, dest_path: str, temp_source_dir: Optional[str] = None) -> None:
    """Copy additional config files that are needed but not saved by save_pretrained."""
    # List of additional files to copy if they exist
    additional_files = ["preprocessor_config.json", "chat_template.json"]

    # Determine the actual source path (could be temp dir if downloaded from S3)
    actual_source = temp_source_dir if temp_source_dir else source_path

    for filename in additional_files:
        source_file = os.path.join(actual_source, filename)
        if os.path.exists(source_file):
            dest_file = os.path.join(dest_path, filename)
            print(f"Copying {filename} to destination...")
            shutil.copy2(source_file, dest_file)


# Define a oneshot data collator for multimodal inputs.
def data_collator(batch):
    assert len(batch) == 1
    return {key: torch.tensor(value) for key, value in batch[0].items()}


def compress_checkpoint(
    source_path: str, dest_path: str, recipe_path: str, num_calibration_samples: int = 512, calibration_pdfs: Optional[List[str]] = None
) -> None:
    """Compress OlmOCR checkpoint using FP8 quantization."""
    # Load model and tokenizer
    model, tokenizer, temp_source_dir = load_model_and_tokenizer(source_path)

    try:
        # Print all model tensor names
        print("\n=== Model Tensor Names ===")
        for name, param in model.named_parameters():
            print(f"{name}: shape={list(param.shape)}, dtype={param.dtype}")
        print("=========================\n")

        # Prepare calibration dataset if requested
        dataset = None

        if num_calibration_samples > 0:
            if not calibration_pdfs:
                raise ValueError("Calibration PDFs must be provided when num_calibration_samples > 0. Use --calibration-pdfs argument.")

            print(f"\nPreparing calibration dataset with {num_calibration_samples} samples...")

            # Load processor for the model
            processor = AutoProcessor.from_pretrained(source_path if not temp_source_dir else temp_source_dir)

            # Get calibration PDFs from provided paths
            pdf_paths = get_calibration_pdfs(num_calibration_samples, calibration_pdfs)

            # Prepare dataset
            dataset = asyncio.run(prepare_calibration_dataset(pdf_paths, processor))

            print(f"✓ Prepared {len(dataset)} calibration samples")

        # Apply quantization using provided recipe
        print(f"\nApplying quantization using recipe: {recipe_path}")

        if dataset:
            oneshot(model=model, recipe=recipe_path, dataset=dataset, max_seq_length=8192, num_calibration_samples=len(dataset), data_collator=data_collator)
        else:
            oneshot(model=model, recipe=recipe_path)

        print("✓ Quantization completed successfully")

        # Save the compressed model
        if is_s3_path(dest_path):
            # Save to temporary directory first, then upload to S3
            with tempfile.TemporaryDirectory() as temp_dest_dir:
                print(f"\nSaving compressed model to temporary directory...")
                model.save_pretrained(temp_dest_dir)
                tokenizer.save_pretrained(temp_dest_dir)

                # Copy additional files
                copy_additional_files(source_path, temp_dest_dir, temp_source_dir)

                # Upload to S3
                bucket, prefix = parse_s3_path(dest_path)
                upload_local_to_s3(temp_dest_dir, bucket, prefix)
        else:
            # Save directly to local destination
            print(f"\nSaving compressed model to {dest_path}...")
            os.makedirs(dest_path, exist_ok=True)
            model.save_pretrained(dest_path)
            tokenizer.save_pretrained(dest_path)

            # Copy additional files
            copy_additional_files(source_path, dest_path, temp_source_dir)

        print(f"\n✓ Successfully compressed checkpoint and saved to {dest_path}")

    finally:
        # Clean up temporary source directory if needed
        if temp_source_dir:
            print(f"Cleaning up temporary directory {temp_source_dir}...")
            shutil.rmtree(temp_source_dir)

        # Free up GPU memory
        del model
        torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(
        description="Compress OlmOCR checkpoint using FP8 quantization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Local to local
    python compress_checkpoint.py /path/to/checkpoint /path/to/compressed --recipe train/quantization_configs/qwen2_5vl_w8a8_fp8.yaml
    
    # S3 to S3
    python compress_checkpoint.py s3://bucket/checkpoint s3://bucket/compressed --recipe train/quantization_configs/qwen2vl_w8a8_fp8.yaml
    
    # S3 to local
    python compress_checkpoint.py s3://bucket/checkpoint /path/to/compressed --recipe train/quantization_configs/qwen2_5vl_w8a8_fp8.yaml
    
    # Local to S3
    python compress_checkpoint.py /path/to/checkpoint s3://bucket/compressed --recipe train/quantization_configs/qwen2vl_w8a8_fp8.yaml
    
    # Using glob pattern for calibration PDFs
    python compress_checkpoint.py /path/to/checkpoint /path/to/compressed --recipe recipe.yaml --calibration-pdfs "/data/pdfs/*.pdf"
    
    # Using recursive glob pattern
    python compress_checkpoint.py /path/to/checkpoint /path/to/compressed --recipe recipe.yaml --calibration-pdfs "/data/**/*.pdf"
        """,
    )
    parser.add_argument("source", help="Source checkpoint path (local or S3)")
    parser.add_argument("destination", help="Destination path for compressed checkpoint (local or S3)")
    parser.add_argument("--recipe", required=True, help="Path to quantization recipe YAML file")
    parser.add_argument("--num-calibration-samples", type=int, default=512, help="Number of calibration samples to use (default: 512, set to 0 to disable)")
    parser.add_argument(
        "--calibration-pdfs",
        type=str,
        default=None,
        help="Glob pattern for calibration PDF paths (e.g., '/path/to/pdfs/*.pdf' or '/data/**/*.pdf'). Required when num-calibration-samples > 0.",
    )

    args = parser.parse_args()

    # Parse calibration PDFs if provided
    calibration_pdfs = None
    if args.calibration_pdfs:
        # Use pathlib for better glob handling
        pattern = args.calibration_pdfs

        # Handle both absolute and relative paths with recursive glob
        if "**" in pattern:
            # For recursive patterns, we need to handle them specially
            if pattern.startswith("/"):
                # Absolute path with **
                parts = pattern.split("**")
                base_path = Path(parts[0])
                glob_pattern = "**" + parts[1] if len(parts) > 1 else "**/*.pdf"
                calibration_pdfs = list(base_path.glob(glob_pattern.lstrip("/")))
            else:
                # Relative path with **
                calibration_pdfs = list(Path(".").glob(pattern))
            calibration_pdfs = [str(p.absolute()) for p in calibration_pdfs if p.suffix.lower() == ".pdf"]
        else:
            # Use standard glob for non-recursive patterns
            calibration_pdfs = glob.glob(pattern)
            calibration_pdfs = [p for p in calibration_pdfs if p.lower().endswith(".pdf")]

        print(f"Found {len(calibration_pdfs)} PDF files matching pattern: {args.calibration_pdfs}")

    compress_checkpoint(args.source, args.destination, args.recipe, args.num_calibration_samples, calibration_pdfs)


if __name__ == "__main__":
    exit(main())
