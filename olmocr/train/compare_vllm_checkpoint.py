#!/usr/bin/env python3
"""
Batch VLM inference comparison between vLLM and HuggingFace.
Processes prompts and images from WildVision-bench until finding significant mismatch.
"""

import argparse
import asyncio
import base64
import logging
import os
import random
import shutil
import tempfile
from io import BytesIO
from typing import Dict, List

import numpy as np
import PIL.Image
import torch
from huggingface_hub import snapshot_download
from transformers import AutoModelForVision2Seq, AutoProcessor
from vllm import LLM, SamplingParams

from olmocr.pipeline import build_page_query
from olmocr.cloud_utils import download_directory

logger = logging.getLogger(__name__)


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
            logger.warning(f"Model download failed (attempt {retry + 1}/{max_retries}), retrying...")
            await asyncio.sleep(2**retry)  # Exponential backoff


def image_to_base64_data_url(image):
    """Convert PIL image to base64 data URL."""
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"


async def load_pdf_prompts(num_samples: int = 100, seed: int = 42, max_length: int = 2048) -> List[Dict[str, str]]:
    """Load prompts and images from olmOCR-mix-0225-benchmarkset dataset with fixed random seed."""
    print(f"Loading olmOCR-mix-0225-benchmarkset dataset with {num_samples} samples and seed {seed}")

    # Set random seed for reproducibility
    random.seed(seed)
    np.random.seed(seed)

    # Import huggingface_hub utilities to list files
    from huggingface_hub import hf_hub_download, list_repo_files

    # List all PDF files in the repository
    print("Listing PDF files in dataset...")
    all_files = list_repo_files(repo_id="allenai/olmOCR-mix-0225-benchmarkset", repo_type="dataset")

    # Filter for PDF files in the pdfs directory
    pdf_files = [f for f in all_files if f.startswith("pdfs/") and f.endswith(".pdf")]

    if not pdf_files:
        raise ValueError("No PDF files found in the dataset")

    print(f"Found {len(pdf_files)} PDF files in dataset")

    # Randomly sample num_samples PDFs
    if len(pdf_files) > num_samples:
        sampled_pdf_files = random.sample(pdf_files, num_samples)
    else:
        sampled_pdf_files = pdf_files
        print(f"Warning: Only {len(pdf_files)} PDFs available, less than requested {num_samples}")

    print(f"Sampled {len(sampled_pdf_files)} PDFs to download")

    # Download only the sampled PDFs and process them
    queries = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for pdf_file in sampled_pdf_files:
            try:
                # Download individual PDF file
                print(f"Downloading {pdf_file}...")
                local_pdf_path = hf_hub_download(repo_id="allenai/olmOCR-mix-0225-benchmarkset", filename=pdf_file, repo_type="dataset", local_dir=temp_dir)

                # Build page query for page 1 of each PDF
                query = await build_page_query(local_pdf_path=local_pdf_path, page=1, target_longest_image_dim=1280, image_rotation=0)
                queries.append(query)
            except Exception as e:
                print(f"Error processing {os.path.basename(pdf_file)}: {e}")
                continue

        print(f"Successfully processed {len(queries)} PDFs")
        return queries


def process_single_prompt(sample: Dict[str, any], llm, hf_model, processor, sampling_params, device, args):
    """Process a single prompt with image and return comparison results."""
    # Track if we found the first mismatch for max_prob_first_diff
    found_first_mismatch = False
    max_prob_first_diff = 0.0
    # Extract messages from the sample (which is the output of build_page_query)
    messages = sample["messages"]

    # Extract the text prompt and image from the messages
    user_message = messages[0]
    text_prompt = None
    image_base64 = None

    for content in user_message["content"]:
        if content["type"] == "text":
            text_prompt = content["text"]
        elif content["type"] == "image_url":
            image_url = content["image_url"]["url"]
            # Extract base64 data after the comma
            if "," in image_url:
                image_base64 = image_url.split(",")[1]
            else:
                image_base64 = image_url

    if text_prompt is None or image_base64 is None:
        raise ValueError("Failed to extract text prompt or image from messages")

    # Decode the base64 image to PIL Image
    image_bytes = base64.b64decode(image_base64)
    image = PIL.Image.open(BytesIO(image_bytes))

    print(f"\n{'='*80}")
    print(f"PROMPT: {text_prompt[:100]}..." if len(text_prompt) > 100 else f"PROMPT: {text_prompt}")
    print(f"IMAGE: {image.size} {image.mode}")

    # Generate with vLLM
    print("\n=== vLLM Generation ===")

    # For VLLM, use the messages just as comes out of build_page_query
    outputs = llm.chat(messages, sampling_params)
    output = outputs[0]

    # Extract prompt and generated token IDs
    prompt_token_ids = output.prompt_token_ids
    generated_token_ids = output.outputs[0].token_ids

    print(
        f"Prompt tokens ({len(prompt_token_ids)}): {prompt_token_ids[:10]}..."
        if len(prompt_token_ids) > 10
        else f"Prompt tokens ({len(prompt_token_ids)}): {prompt_token_ids}"
    )
    print(f"Generated tokens ({len(generated_token_ids)}): {generated_token_ids}")
    print(f"Generated text: {processor.decode(generated_token_ids, skip_special_tokens=True)}")

    # Create input tensor from concatenated token IDs
    # input_ids = torch.tensor([all_token_ids], device=device)  # Not needed for HF VLM models

    # HuggingFace forward pass
    print("\n=== HuggingFace Forward Pass ===")
    # Prepare inputs for HF model using the extracted image and text
    conversation = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": text_prompt}]}]
    hf_text_prompt = processor.apply_chat_template(conversation, add_generation_prompt=True, tokenize=False)
    inputs = processor(text=[hf_text_prompt], images=[image], return_tensors="pt").to(device)

    print("INPUTS", inputs)

    # Concatenate the generated tokens to the input_ids
    generated_ids_tensor = torch.tensor([generated_token_ids], device=device)
    inputs["input_ids"] = torch.cat([inputs["input_ids"], generated_ids_tensor], dim=1)
    inputs["attention_mask"] = torch.ones_like(inputs["input_ids"])

    with torch.no_grad():
        outputs_hf = hf_model(**inputs)
        logits = outputs_hf.logits[0]  # [seq_len, vocab_size]

    # Token-by-token comparison
    print(f"\n{'Pos':>4} {'Token ID':>8} {'Token':>20} {'Type':>8} {'vLLM Prob':>12} {'HF Argmax':>10} {'HF Prob':>12} {'Match':>6} {'HF Token':>20}")
    print("-" * 125)

    # Get vLLM logprobs for generated tokens
    vllm_logprobs = output.outputs[0].logprobs

    # Track mismatch info
    first_mismatch_idx = None

    # Get all token IDs from the HF model's input
    all_token_ids = inputs["input_ids"][0].tolist()

    # Compare ALL tokens (prompt + generated)
    for pos, token_id in enumerate(all_token_ids):
        token_str = processor.decode([token_id], skip_special_tokens=False).replace("\n", "\\n").replace("\r", "\\r")

        # Determine if this is a prompt or generated token
        is_prompt = pos < len(prompt_token_ids)
        token_type = "prompt" if is_prompt else "gen"

        # vLLM probability (only for generated tokens)
        vllm_prob_str = "N/A"
        vllm_prob = None
        if not is_prompt:
            gen_idx = pos - len(prompt_token_ids)
            if vllm_logprobs and gen_idx < len(vllm_logprobs):
                # vLLM logprobs is a list of dicts mapping token_id to logprob
                token_logprobs = vllm_logprobs[gen_idx]
                if token_logprobs and token_id in token_logprobs:
                    # Convert logprob to probability
                    vllm_prob = torch.exp(torch.tensor(token_logprobs[token_id].logprob)).item()
                    vllm_prob_str = f"{vllm_prob:12.6f}"

        # HF prediction - only for generated tokens (skip prompt tokens entirely)
        if pos > 0 and not is_prompt:
            hf_logits_at_pos = logits[pos - 1]
            hf_probs = torch.softmax(hf_logits_at_pos, dim=-1)
            hf_argmax = torch.argmax(hf_logits_at_pos).item()
            hf_prob = hf_probs[token_id].item()

            # Check if predictions match
            match = "✓" if token_id == hf_argmax else "✗"

            # Track first mismatch and probability difference
            if token_id != hf_argmax:
                if first_mismatch_idx is None:
                    first_mismatch_idx = pos - len(prompt_token_ids)
                    # Calculate probability difference only for the first mismatch
                    if vllm_prob is not None and not found_first_mismatch:
                        max_prob_first_diff = abs(vllm_prob - hf_prob)
                        found_first_mismatch = True

            # Decode HF argmax token (only show if mismatch)
            hf_token_str = ""
            if token_id != hf_argmax:
                hf_token_str = processor.decode([hf_argmax], skip_special_tokens=False).replace("\n", "\\n").replace("\r", "\\r")

            print(f"{pos:>4} {token_id:>8} {token_str:>20} {token_type:>8} {vllm_prob_str:>12} {hf_argmax:>10} {hf_prob:>12.6f} {match:>6} {hf_token_str:>20}")
        else:
            # Prompt tokens or first token - no HF comparison
            print(f"{pos:>4} {token_id:>8} {token_str:>20} {token_type:>8} {vllm_prob_str:>12} {'':>10} {'':>12} {'':>6} {'':<20}")

    # Summary
    print(f"\n=== Summary ===")
    print(f"Total tokens generated: {len(generated_token_ids)}")

    # Calculate match rate
    matches = 0
    for i, token_id in enumerate(generated_token_ids):
        pos = len(prompt_token_ids) + i
        hf_logits_at_pos = logits[pos - 1]
        hf_argmax = torch.argmax(hf_logits_at_pos).item()
        if token_id == hf_argmax:
            matches += 1

    match_rate = matches / len(generated_token_ids) * 100 if generated_token_ids else 0
    print(f"Token match rate: {matches}/{len(generated_token_ids)} ({match_rate:.1f}%)")

    # Report first mismatch index
    if first_mismatch_idx is not None:
        print(f"First mismatch at generation index: {first_mismatch_idx}")
        print(f"First mismatch probability difference: {max_prob_first_diff:.6f}")
    else:
        print("No mismatches found in generated tokens")

    return {
        "first_mismatch_idx": first_mismatch_idx,
        "max_prob_first_diff": max_prob_first_diff,
        "match_rate": match_rate,
        "num_generated": len(generated_token_ids),
    }


async def async_main():
    parser = argparse.ArgumentParser(description="Batch compare VLM inference between vLLM and HuggingFace")
    parser.add_argument("--model", type=str, default="Qwen/Qwen2.5-VL-7B-Instruct", help="Model name or path")
    parser.add_argument("--max-tokens", type=int, default=20, help="Maximum tokens to generate per prompt")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    parser.add_argument("--num-prompts", type=int, default=100, help="Number of prompts to load from WildVision")
    parser.add_argument("--prob-threshold", type=float, default=0.20, help="Probability difference threshold to stop")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for prompt selection")
    args = parser.parse_args()

    print(f"Model: {args.model}")
    print(f"Max tokens: {args.max_tokens}")
    print(f"Temperature: {args.temperature}")
    print(f"Probability threshold: {args.prob_threshold}")
    print(f"Loading {args.num_prompts} samples from olmOCR-mix-0225-benchmarkset\n")

    # Download the model before loading prompts
    model_path = await download_model(args.model)

    # Load prompts and images
    samples = await load_pdf_prompts(num_samples=args.num_prompts, seed=args.seed)

    # Load HuggingFace model and processor first
    print("\n=== Loading HuggingFace Model ===")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    processor_hf = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
    hf_model = AutoModelForVision2Seq.from_pretrained(model_path, trust_remote_code=True, torch_dtype=torch.float16, device_map="auto")
    hf_model.eval()

    # Create vLLM engine once
    print("\n=== Creating vLLM Engine ===")
    llm = LLM(model=model_path, trust_remote_code=True, gpu_memory_utilization=0.5)
    sampling_params = SamplingParams(temperature=args.temperature, max_tokens=args.max_tokens, logprobs=1)  # Get top-1 logprobs

    # Process samples until finding significant mismatch
    print("\n=== Processing Samples ===")

    # Initialize statistics tracking
    all_results = []
    for i, sample in enumerate(samples):
        print(f"\n\n{'#'*80}")
        print(f"### Processing sample {i+1}/{len(samples)}")
        print(f"{'#'*80}")

        # Process single sample
        result = process_single_prompt(sample, llm, hf_model, processor_hf, sampling_params, device, args)
        all_results.append(result)

        # Check if we found significant mismatch
        if result["first_mismatch_idx"] is not None and result["max_prob_first_diff"] > args.prob_threshold:
            print(f"\n\n{'*'*80}")
            print(f"*** FOUND SIGNIFICANT MISMATCH ***")
            print(f"*** First mismatch probability difference: {result['max_prob_first_diff']:.6f} > {args.prob_threshold} ***")
            print(f"*** Stopping after sample {i+1}/{len(samples)} ***")
            print(f"{'*'*80}")

    # Report aggregated statistics
    print(f"\n\n{'='*80}")
    print("=== AGGREGATED STATISTICS ===")
    print(f"{'='*80}")

    total_samples = len(all_results)
    samples_with_mismatches = sum(1 for r in all_results if r["first_mismatch_idx"] is not None)
    total_tokens_generated = sum(r["num_generated"] for r in all_results)

    print(f"Total samples processed: {total_samples}")
    print(f"Samples with mismatches: {samples_with_mismatches} ({samples_with_mismatches/total_samples*100:.1f}%)")
    print(f"Total tokens generated: {total_tokens_generated}")

    if samples_with_mismatches > 0:
        avg_match_rate = sum(r["match_rate"] for r in all_results) / total_samples
        max_prob_diffs = [r["max_prob_first_diff"] for r in all_results if r["first_mismatch_idx"] is not None]
        avg_prob_diff = sum(max_prob_diffs) / len(max_prob_diffs)
        max_prob_diff_overall = max(max_prob_diffs)

        first_mismatch_positions = [r["first_mismatch_idx"] for r in all_results if r["first_mismatch_idx"] is not None]
        avg_first_mismatch_pos = sum(first_mismatch_positions) / len(first_mismatch_positions)

        print(f"\nMismatch Statistics:")
        print(f"  Average token match rate: {avg_match_rate:.1f}%")
        print(f"  Average first mismatch position: {avg_first_mismatch_pos:.1f}")
        print(f"  Average first mismatch prob diff: {avg_prob_diff:.6f}")
        print(f"  Max first mismatch prob diff: {max_prob_diff_overall:.6f}")
    else:
        print("\nNo mismatches found in any samples!")

    print(f"\n{'='*80}")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
