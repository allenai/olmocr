"""
GRPO (Generative Reward-based Policy Optimization) training script for OlmOCR.
"""

import argparse
import asyncio
import base64
import glob
import json
import logging
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, partial
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import torch
import torch.distributed as dist
import wandb
from PIL import Image
from rapidfuzz import fuzz
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoProcessor,
    Qwen2_5_VLForConditionalGeneration,
    Qwen2VLForConditionalGeneration,
)
from trl import GRPOConfig, GRPOTrainer

from olmocr.bench.tests import load_single_test
from olmocr.data.renderpdf import render_pdf_to_base64png
from olmocr.prompts import PageResponse, build_no_anchoring_v4_yaml_prompt
from olmocr.train.dataloader import FrontMatterParser

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_rank():
    """Get the rank of the current process in distributed training."""
    # Check environment variables for rank information
    rank = 0

    # Try different environment variables that might contain rank
    if "LOCAL_RANK" in os.environ:
        rank = int(os.environ["LOCAL_RANK"])
    elif "RANK" in os.environ:
        rank = int(os.environ["RANK"])
    elif dist.is_available() and dist.is_initialized():
        rank = dist.get_rank()

    return rank


def is_main_process():
    """Check if this is the main process (rank 0)."""
    return get_rank() == 0


class OlmOCRBenchDataset(Dataset):
    """Dataset for loading PDF pages from Olmocr-bench format JSONL files."""

    def __init__(
        self,
        bench_data_folder: str,
        processor,
        max_samples: Optional[int] = None,
        target_longest_image_dim: int = 1024,
    ):
        self.bench_data_folder = bench_data_folder
        self.processor = processor
        self.target_longest_image_dim = target_longest_image_dim
        self.max_samples = max_samples

        # Find PDF folder
        self.pdf_folder = os.path.join(bench_data_folder, "pdfs")
        if not os.path.exists(self.pdf_folder):
            raise ValueError(f"PDFs folder not found at {self.pdf_folder}")

        # Set claude_original folder path
        self.claude_original_folder = os.path.join(bench_data_folder, "claude_original")
        if os.path.exists(self.claude_original_folder):
            logger.info(f"Found claude_original folder at {self.claude_original_folder}")
        else:
            logger.warning(f"No claude_original folder found at {self.claude_original_folder}")

        # Load unique PDFs from JSONL files
        self.samples = self._load_unique_pdfs_from_jsonl()

        logger.info(f"Created dataset with {len(self.samples)} unique PDF samples")

    def _load_claude_original(self, pdf_name: str, page: int) -> Optional[str]:
        """Load the claude_original markdown file for a given PDF and page."""
        if not os.path.exists(self.claude_original_folder):
            return None

        # Extract the base PDF name and construct the expected filename
        # pdf_name like "s2pdf/pdf_00017_page2.pdf" -> construct the markdown filename
        pdf_base = os.path.basename(pdf_name).replace(".pdf", "")

        # Handle case where page is already in the filename
        if "_page" in pdf_base:
            pdf_base_parts = pdf_base.split("_page")
            pdf_base_name = pdf_base_parts[0]
            # Use the page from the filename if it exists
            page_from_name = int(pdf_base_parts[1]) if len(pdf_base_parts) > 1 and pdf_base_parts[1].isdigit() else page
        else:
            pdf_base_name = pdf_base
            page_from_name = page

        # Extract folder structure from pdf_name (e.g., "s2pdf/" or "arxiv_math/")
        pdf_dir = os.path.dirname(pdf_name)

        # Construct the expected claude_original filename
        # Format: pdf_00017_page2_pg1_repeat1.md
        claude_filename = f"{pdf_base_name}_page{page_from_name}_pg1_repeat1.md"

        # Build the full path to the claude_original file
        claude_file_path = os.path.join(self.claude_original_folder, pdf_dir, claude_filename)

        if os.path.exists(claude_file_path):
            try:
                with open(claude_file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Parse the frontmatter to validate the content
                parser = FrontMatterParser(front_matter_class=PageResponse)
                try:
                    front_matter, text = parser._extract_front_matter_and_text(content)
                    page_response = parser._parse_front_matter(front_matter, text)
                    # Parsing succeeded, return the original content
                    return content
                except Exception as parse_error:
                    logger.error(f"CRITICAL: Failed to parse frontmatter from claude_original file {claude_file_path}")
                    logger.error(f"Parse error: {type(parse_error).__name__}: {str(parse_error)}")
                    logger.error("Aborting run due to invalid claude_original file format")
                    sys.exit(1)

            except Exception as e:
                logger.warning(f"Failed to read claude_original file {claude_file_path}: {e}")
        else:
            logger.debug(f"Claude original file not found: {claude_file_path}")

        return None

    def _load_unique_pdfs_from_jsonl(self) -> List[Dict[str, Any]]:
        """Load unique PDFs from JSONL files in the bench_data folder, tracking all test cases per PDF."""
        jsonl_files = sorted(glob.glob(os.path.join(self.bench_data_folder, "*.jsonl")))

        if not jsonl_files:
            raise ValueError(f"No JSONL files found in {self.bench_data_folder}")

        logger.info(f"Found {len(jsonl_files)} JSONL files")

        # Track unique PDFs and their test cases
        pdf_data: Dict[str, Dict[str, Any]] = {}

        for jsonl_file in jsonl_files:
            logger.info(f"Processing {os.path.basename(jsonl_file)}")

            with open(jsonl_file, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        pdf_name = entry.get("pdf")
                        page = entry.get("page", 0)
                        test_id = entry.get("id")

                        if pdf_name and test_id:
                            # Create unique key for PDF+page combination
                            pdf_page_key = f"{pdf_name}::{page}"

                            if pdf_page_key not in pdf_data:
                                # First time seeing this PDF+page
                                pdf_path = os.path.join(self.pdf_folder, pdf_name)
                                claude_original = self._load_claude_original(pdf_name, page)
                                pdf_data[pdf_page_key] = {
                                    "pdf_path": pdf_path,
                                    "pdf_name": pdf_name,
                                    "page": page,
                                    "jsonl_file": jsonl_file,
                                    "test_ids": [test_id],
                                    "entries": [entry],
                                    "claude_original": claude_original,
                                }
                            else:
                                # Add test case to existing PDF+page
                                pdf_data[pdf_page_key]["test_ids"].append(test_id)
                                pdf_data[pdf_page_key]["entries"].append(entry)

                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse line in {jsonl_file}: {e}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error processing entry in {jsonl_file}: {e}")
                        continue

        # Convert to list with sorted keys for reproducibility
        samples = [pdf_data[key] for key in sorted(pdf_data.keys())]
        if self.max_samples:
            samples = samples[: self.max_samples]

        return samples

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        sample = self.samples[idx]
        pdf_path = sample["pdf_path"]
        page_num = sample["page"]
        jsonl_file = sample["jsonl_file"]
        test_ids = sample["test_ids"]

        try:
            # Render PDF page to base64 image
            image_base64 = render_pdf_to_base64png(pdf_path, page_num, target_longest_image_dim=self.target_longest_image_dim)

            # Convert base64 to PIL Image
            image_bytes = base64.b64decode(image_base64)
            image = Image.open(BytesIO(image_bytes)).convert("RGB")

            # Build the text prompt
            text_prompt = build_no_anchoring_v4_yaml_prompt()

            # Create messages in the format expected by Qwen2-VL
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_prompt},
                        {"type": "image"},
                    ],
                }
            ]

            # Return the required format
            return {
                "prompt": messages,
                "pdf_path": pdf_path,
                "jsonl_file": jsonl_file,
                "test_ids": test_ids,
                "image": image,  # Include the PIL image for processing later
                "claude_original": sample.get("claude_original"),  # Include claude_original if available
            }

        except Exception as e:
            logger.error(f"Failed to process sample {idx}: {e}")
            # Return None if processing fails
            return None


@lru_cache(maxsize=1024)
def load_specific_tests_cached(jsonl_file: str, test_ids_tuple: tuple):
    """
    Cached version that loads specific tests by their IDs from a JSONL file.
    Uses load_single_test to parse individual test entries.

    Args:
        jsonl_file: Path to the JSONL file containing test definitions
        test_ids_tuple: Tuple of test IDs to load (tuple for hashability in lru_cache)

    Returns:
        List of test objects matching the specified IDs
    """
    test_ids = set(test_ids_tuple)

    relevant_tests = []
    with open(jsonl_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                # Parse just enough to get the ID
                test_data = json.loads(line)
                if test_data.get("id") in test_ids:
                    # Use load_single_test to properly parse and validate the test
                    test = load_single_test(test_data)
                    relevant_tests.append(test)
                    # Early exit if we've found all tests
                    if len(relevant_tests) == len(test_ids):
                        break
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Error parsing test line: {e}")
                continue

    return relevant_tests


def evaluate_single_completion(args: Tuple[int, Any, str, str, List[str]]) -> Tuple[int, Optional[float]]:
    """
    Helper function to evaluate a single completion against its tests.

    Args:
        args: Tuple of (index, completion, jsonl_file, pdf_path, test_ids)

    Returns:
        Tuple of (index, reward) where reward is float or None for errors
    """
    i, completion, comp_jsonl_file, comp_pdf_path, comp_test_ids = args

    logger.info(f"Completion {i}: PDF: {comp_pdf_path}, JSONL: {comp_jsonl_file}, Test IDs: {comp_test_ids}")

    if completion is None or not (isinstance(completion, str) or isinstance(completion, list)):
        logger.warning(f"Invalid completion at index {i}: {type(completion)}")
        logger.warning(f"completion: {completion}")
        return i, None

    if comp_jsonl_file is None or comp_test_ids is None or len(comp_test_ids) == 0:
        logger.warning(f"Missing metadata for completion {i}")
        return i, None

    if isinstance(completion, list):
        completion = completion[0]["content"]

    try:
        # Load only the specific tests we need from the JSONL file (cached)
        # Convert list to tuple for hashability in lru_cache
        relevant_tests = load_specific_tests_cached(comp_jsonl_file, tuple(comp_test_ids))

        if not relevant_tests:
            logger.warning(f"No relevant tests found for test IDs: {comp_test_ids}")
            return i, None

        logger.info(f"Found {len(relevant_tests)} relevant tests for completion {i}")

        # Run all relevant tests on this completion
        passed = 0
        total = len(relevant_tests)

        for test in relevant_tests:
            try:
                test_passed, failure_reason = test.run(completion)
                if test_passed:
                    passed += 1
                else:
                    logger.debug(f"Test {test.id} failed: {failure_reason}")
            except Exception as e:
                logger.warning(f"Error running test {test.id}: {e}")
                # Count errored tests as failures
                continue

        # Calculate reward as proportion of tests passed
        reward = passed / total if total > 0 else 0.0

        logger.info(f"Completion {i}: {passed}/{total} tests passed, reward={reward:.3f}")
        return i, reward

    except Exception as e:
        logger.error(f"Error processing completion {i}: {e}")
        return i, None


def bench_edit_distance_reward(prompts, completions: list[str] | list[list[dict]], claude_original: list[Optional[str]], **kwargs):
    """
    Reward function based on edit distance similarity to claude_original files.

    Calculates the normalized edit distance between each completion and its corresponding
    claude_original reference. Returns 1.0 for perfect match, lower for more distance.

    Args:
        prompts: List of prompts
        completions: List of generated completions (model outputs)
        claude_original: List of claude_original reference texts (one per completion)
        **kwargs: Additional arguments

    Returns:
        List of reward scores between 0 and 1, where 1.0 is perfect match
    """
    logger.info(f"Running bench edit distance reward function for {len(completions)} completions")

    rewards = []

    for i, completion in enumerate(completions):
        # Extract text from completion
        if isinstance(completion, list):
            comp_text = completion[0]["content"] if completion else ""
        elif isinstance(completion, str):
            comp_text = completion
        else:
            comp_text = ""

        # Get the corresponding claude_original reference
        reference = claude_original[i] if i < len(claude_original) else None

        if reference is None:
            logger.warning(f"No claude_original reference for completion {i}")
            rewards.append(0.0)
            continue

        # Calculate edit distance
        similarity_ratio = fuzz.ratio(comp_text, reference) / 100.0
        rewards.append(similarity_ratio)

    logger.info(f"Bench edit distance rewards range: [{min(rewards) if rewards else 0:.3f}, {max(rewards) if rewards else 0:.3f}]")
    return rewards


def medoid_reward(prompts, completions: list[str] | list[list[dict]], **kwargs):
    """
    Reward function based on edit distance to the medoid completion.

    The medoid is the completion with the minimum average edit distance to all others.
    Rewards are calculated as 1 - normalized_distance_to_medoid.

    Args:
        prompts: List of prompts
        completions: List of generated completions (model outputs)
        **kwargs: Additional arguments

    Returns:
        List of reward scores between 0 and 1, where medoid gets 1.0
    """
    logger.info(f"Running medoid reward function for {len(completions)} completions")

    # Extract text from completions
    completion_texts = []
    for completion in completions:
        if isinstance(completion, list):
            text = completion[0]["content"] if completion else ""
        elif isinstance(completion, str):
            text = completion
        else:
            text = ""
        completion_texts.append(text)

    n = len(completion_texts)

    # Handle edge cases
    if n == 0:
        return []
    if n == 1:
        return [1.0]

    # Calculate pairwise edit distances
    distances = [[0.0] * n for _ in range(n)]
    max_distance = 0.0

    for i in range(n):
        for j in range(i + 1, n):
            # Calculate Levenshtein distance
            dist = distance.Levenshtein.distance(completion_texts[i], completion_texts[j])
            distances[i][j] = dist
            distances[j][i] = dist
            max_distance = max(max_distance, dist)

    # Find the medoid (completion with minimum average distance to others)
    avg_distances = [sum(distances[i]) / (n - 1) if n > 1 else 0 for i in range(n)]
    medoid_idx = min(range(n), key=lambda i: avg_distances[i])

    # Calculate rewards based on distance from medoid
    rewards = []
    medoid_distances = distances[medoid_idx]

    # Normalize distances and compute rewards
    for i in range(n):
        if i == medoid_idx:
            rewards.append(1.0)
        else:
            # Normalize distance to [0, 1] range
            if max_distance > 0:
                normalized_dist = medoid_distances[i] / max_distance
            else:
                normalized_dist = 0.0
            # Reward is 1 minus normalized distance
            reward = 1.0 - normalized_dist
            rewards.append(max(0.0, reward))  # Ensure non-negative

    logger.info(f"Medoid at index {medoid_idx}, rewards range: [{min(rewards):.3f}, {max(rewards):.3f}]")
    return rewards


def reward_front_matter(prompts, completions: list[str] | list[list[dict]], claude_original: list[Optional[str]] = None, **kwargs):
    """
    Reward function that checks if completions can be successfully parsed by FrontMatterParser
    and compares fields to claude_original values.

    Scoring:
    - 0.0: Cannot parse frontmatter at all
    - 0.5: Can parse frontmatter successfully
    - +0.1: For each matching field (primary_language, is_rotation_valid,
            rotation_correction, is_table, is_diagram)

    Maximum score: 1.0 (0.5 + 5 * 0.1)

    Args:
        prompts: List of prompts
        completions: List of generated completions (model outputs)
        claude_original: List of claude_original markdown content (optional)
        **kwargs: Additional arguments

    Returns:
        List of reward scores between 0.0 and 1.0
    """
    logger.info(f"Running front matter reward function for {len(completions)} completions")

    rewards = []
    parser = FrontMatterParser(front_matter_class=PageResponse)

    # Fields to compare
    fields_to_compare = ["primary_language", "is_rotation_valid", "rotation_correction", "is_table", "is_diagram"]

    for i, completion in enumerate(completions):
        # Extract text from completion
        if isinstance(completion, list):
            if completion and "content" in completion[0]:
                model_response_markdown = completion[0]["content"]
            else:
                model_response_markdown = ""
        elif isinstance(completion, str):
            model_response_markdown = completion
        else:
            model_response_markdown = ""

        reward = 0.0

        try:
            # Try to parse the completion
            front_matter, text = parser._extract_front_matter_and_text(model_response_markdown)
            completion_response = parser._parse_front_matter(front_matter, text)

            # Parsing succeeded - base reward of 0.5
            reward = 0.5
            logger.debug(f"Completion {i}: Successfully parsed frontmatter (base reward: 0.5)")

            # Try to compare with claude_original if available
            if claude_original and i < len(claude_original) and claude_original[i]:
                try:
                    # Parse claude_original frontmatter
                    claude_fm, claude_text = parser._extract_front_matter_and_text(claude_original[i])
                    claude_response = parser._parse_front_matter(claude_fm, claude_text)

                    # Compare each field
                    fields_matched = 0
                    for field in fields_to_compare:
                        completion_value = getattr(completion_response, field, None)
                        claude_value = getattr(claude_response, field, None)

                        if completion_value == claude_value:
                            fields_matched += 1
                            reward += 0.1
                            logger.debug(f"  Field {field} matches: {completion_value}")
                        else:
                            logger.debug(f"  Field {field} mismatch: completion={completion_value}, claude={claude_value}")

                    logger.debug(f"Completion {i}: Matched {fields_matched}/{len(fields_to_compare)} fields")

                except Exception as e:
                    logger.warning(f"Failed to parse claude_original for comparison at index {i}: {e}")
                    # Keep the base 0.5 reward for successful parsing
            else:
                logger.debug(f"Completion {i}: No claude_original available for comparison")

        except Exception as e:
            # Any parsing error results in 0 reward
            reward = 0.0
            logger.debug(f"Completion {i}: Failed to parse frontmatter - {type(e).__name__}: {str(e)}")

        rewards.append(reward)

    # Log summary statistics
    zero_rewards = sum(1 for r in rewards if r == 0.0)
    partial_rewards = sum(1 for r in rewards if 0.0 < r < 1.0)
    perfect_rewards = sum(1 for r in rewards if r == 1.0)
    avg_reward = sum(rewards) / len(rewards) if rewards else 0.0

    logger.info(f"Front matter rewards summary: {zero_rewards} failed, {partial_rewards} partial, " f"{perfect_rewards} perfect. Average: {avg_reward:.3f}")

    return rewards


def reward_element_count(prompts, completions: list[str] | list[list[dict]], claude_original: list[Optional[str]] = None, **kwargs):
    """
    Reward function based on matching element counts between completion and claude_original.

    Counts HTML tables (<table>...</table>) and LaTeX math equations ($$...$$, \(...\), \[...\])
    in both the completion and claude_original text, then calculates reward based on matches:
    - 1.0: Both table count and math equation count match
    - 0.5: One of the counts matches
    - 0.0: Neither count matches

    Args:
        prompts: List of prompts
        completions: List of generated completions (model outputs)
        claude_original: List of claude_original reference texts (one per completion)
        **kwargs: Additional arguments

    Returns:
        List of reward scores between 0.0 and 1.0
    """
    import re

    logger.info(f"Running element count reward function for {len(completions)} completions")

    rewards = []

    def count_elements(text: str) -> tuple[int, int]:
        """Count HTML tables and LaTeX math equations in text."""
        # Count HTML tables
        table_pattern = r"<table\b[^>]*>.*?</table>"
        tables = re.findall(table_pattern, text, re.DOTALL | re.IGNORECASE)
        table_count = len(tables)

        # Count LaTeX math equations using the specified patterns
        math_patterns = [
            r"\$\$(.+?)\$\$",  # $$...$$
            r"\\\((.+?)\\\)",  # \(...\)
            r"\\\[(.+?)\\\]",  # \[...\]
        ]

        math_count = 0
        for pattern in math_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            math_count += len(matches)

        return table_count, math_count

    for i, completion in enumerate(completions):
        # Extract text from completion
        if isinstance(completion, list):
            comp_text = completion[0]["content"] if completion else ""
        elif isinstance(completion, str):
            comp_text = completion
        else:
            comp_text = ""

        # Get the corresponding claude_original reference
        reference = claude_original[i] if i < len(claude_original) else None

        if reference is None:
            logger.warning(f"No claude_original reference for completion {i}")
            rewards.append(0.0)
            continue

        # Count elements in both texts
        comp_table_count, comp_math_count = count_elements(comp_text)
        ref_table_count, ref_math_count = count_elements(reference)

        # Calculate reward based on matches
        matches = 0
        if comp_table_count == ref_table_count:
            matches += 1
        if comp_math_count == ref_math_count:
            matches += 1

        # Map matches to reward: 0 matches -> 0.0, 1 match -> 0.5, 2 matches -> 1.0
        reward = matches * 0.5

        logger.debug(
            f"Completion {i}: tables (comp={comp_table_count}, ref={ref_table_count}), "
            f"math (comp={comp_math_count}, ref={ref_math_count}), reward={reward:.1f}"
        )

        rewards.append(reward)

    logger.info(
        f"Element count rewards - avg: {sum(rewards)/len(rewards) if rewards else 0:.3f}, "
        f"range: [{min(rewards) if rewards else 0:.3f}, {max(rewards) if rewards else 0:.3f}]"
    )

    return rewards


def reward_eos(eos_token_id: int, prompts, completions: list[str] | list[list[dict]], completion_ids: list[list[int]], **kwargs):
    """
    Reward function that checks if the EOS token is the last token in completion_ids.

    Returns 1.0 if the EOS token is the last token, 0.0 otherwise.

    Args:
        eos_token_id: The EOS token ID from the tokenizer
        prompts: List of prompts
        completions: List of generated completions (model outputs)
        completion_ids: List of lists of token IDs for each completion
        **kwargs: Additional arguments

    Returns:
        List of reward scores (1.0 if EOS is last, 0.0 otherwise)
    """
    logger.info(f"Running EOS reward function for {len(completions)} completions (EOS token ID: {eos_token_id})")

    rewards = []

    for i, comp_ids in enumerate(completion_ids):
        if comp_ids and len(comp_ids) > 0:
            last_token = comp_ids[-1]
            if last_token == eos_token_id:
                rewards.append(1.0)
                logger.debug(f"Completion {i}: EOS token {last_token} found at end")
            else:
                rewards.append(0.0)
                logger.debug(f"Completion {i}: Last token {last_token} is not EOS (expected {eos_token_id})")
        else:
            # Empty completion, no EOS
            rewards.append(0.0)
            logger.debug(f"Completion {i}: Empty completion, no EOS")

    eos_count = sum(rewards)
    logger.info(f"EOS rewards: {eos_count}/{len(rewards)} completions have EOS as last token")

    return rewards


def olmocr_bench_reward(
    prompts,
    completions: list[str] | list[list[dict]],
    completion_ids: list[list[int]],
    pdf_path: list[str],
    jsonl_file: list[str],
    test_ids: list[list[str]],
    **kwargs,
):
    """
    Reward function that runs unit tests on completions and returns average pass rate.
    Uses ThreadPoolExecutor to evaluate completions in parallel.

    For each completion, loads the corresponding tests from the JSONL file and runs them.
    Returns the proportion of tests that pass as the reward score.

    Args:
        prompts: List of prompts
        completions: List of generated completions (model outputs)
        completion_ids: List of completion token IDs
        pdf_path: List of PDF file paths (one per completion)
        jsonl_file: List of JSONL file paths containing test definitions (one per completion)
        test_ids: List of test ID lists associated with each PDF page (one list per completion)
        **kwargs: Additional arguments

    Returns:
        List of reward scores (float) based on test pass rates, or None for errors
    """
    logger.info(f"Running olmocr bench reward function for {len(completions)} completions")

    # Prepare arguments for parallel processing
    eval_args = []
    for i, completion in enumerate(completions):
        comp_pdf_path = pdf_path[i] if i < len(pdf_path) else None
        comp_jsonl_file = jsonl_file[i] if i < len(jsonl_file) else None
        comp_test_ids = test_ids[i] if i < len(test_ids) else []
        eval_args.append((i, completion, comp_jsonl_file, comp_pdf_path, comp_test_ids))

    # Process completions in parallel using ThreadPoolExecutor
    rewards = [None] * len(completions)  # Pre-allocate results list

    # Use number of CPUs for thread pool size, with a reasonable maximum
    max_workers = min(os.cpu_count() or 4, 16, len(completions))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks at once
        futures = [executor.submit(evaluate_single_completion, args) for args in eval_args]

        # Collect results as they complete (but maintain order)
        for future in futures:
            idx, reward = future.result()
            rewards[idx] = reward

    return rewards


def main():
    # Log rank information early
    rank = get_rank()
    if "LOCAL_RANK" in os.environ:
        logger.info(f"LOCAL_RANK environment variable: {os.environ['LOCAL_RANK']}")
    if "RANK" in os.environ:
        logger.info(f"RANK environment variable: {os.environ['RANK']}")
    logger.info(f"Current process rank: {rank}, is_main_process: {is_main_process()}")

    parser = argparse.ArgumentParser(description="GRPO training for OlmOCR")
    parser.add_argument(
        "--train_bench_data_folder", type=str, required=True, help="Path to training bench data folder containing JSONL files and pdfs subfolder"
    )
    parser.add_argument(
        "--eval_bench_data_folder",
        type=str,
        required=False,
        default=None,
        help="Path to evaluation bench data folder (optional, uses train folder if not specified)",
    )
    parser.add_argument("--model_name", type=str, default="Qwen/Qwen2.5-VL-7B-Instruct", help="Model checkpoint to load")
    parser.add_argument("--output_dir", type=str, default="outputs/grpo_test", help="Output directory for checkpoints")
    parser.add_argument("--learning_rate", type=float, default=2e-6, help="Learning rate")
    parser.add_argument("--num_train_epochs", type=int, default=1, help="Number of training epochs")
    parser.add_argument("--per_device_train_batch_size", type=int, default=1, help="Training batch size per device")
    parser.add_argument("--per_device_eval_batch_size", type=int, default=1, help="Evaluation batch size per device")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=8, help="Gradient accumulation steps")
    parser.add_argument("--warmup_steps", type=int, default=100, help="Number of warmup steps for learning rate scheduler")
    parser.add_argument("--seed", type=int, default=42, help="Seed passed to TRL trainer to shuffle data, etc")
    parser.add_argument("--max_train_samples", type=int, default=None, help="Maximum number of training samples to use (default: use all)")
    parser.add_argument("--max_eval_samples", type=int, default=10, help="Maximum number of evaluation samples to use (default: 10)")
    parser.add_argument("--wandb_project", type=str, default="olmocr-grpo", help="Weights & Biases project name")
    parser.add_argument("--wandb_run_name", type=str, default=None, help="Weights & Biases run name (default: auto-generated)")
    parser.add_argument("--loss_type", type=str, default="bnpo", choices=["bnpo", "grpo", "exo"], help="Loss formulation to use (default: bnpo)")
    parser.add_argument(
        "--scale_rewards",
        type=str,
        default="group",
        choices=["group", "batch", "none"],
        help="Scaling strategy for rewards: 'group' (scale by std within each group), 'batch' (scale by std across batch), or 'none' (no scaling). Default: 'group'",
    )
    parser.add_argument("--beta", type=float, default=0.0, help="KL coefficient for reference model (default: 0.0, no reference model)")
    parser.add_argument(
        "--importance_sampling_level", type=str, default="token", choices=["token", "sequence"], help="Level for importance sampling ratios (default: token)"
    )
    parser.add_argument(
        "--reward_bench", nargs="?", const=1.0, type=float, default=None, help="Use bench-based reward function with optional weight (default: 1.0)"
    )
    parser.add_argument(
        "--reward_medoid", nargs="?", const=1.0, type=float, default=None, help="Use medoid-based reward function with optional weight (default: 1.0)"
    )
    parser.add_argument(
        "--reward_bench_edit_distance",
        nargs="?",
        const=1.0,
        type=float,
        default=None,
        help="Use bench edit distance reward with optional weight (default: 1.0)",
    )
    parser.add_argument(
        "--reward_front_matter",
        nargs="?",
        const=1.0,
        type=float,
        default=None,
        help="Use front matter validation and field matching reward with optional weight (default: 1.0)",
    )
    parser.add_argument(
        "--reward_element_count",
        nargs="?",
        const=1.0,
        type=float,
        default=None,
        help="Use element count matching reward (tables and math equations) with optional weight (default: 1.0)",
    )
    parser.add_argument(
        "--reward_eos",
        nargs="?",
        const=1.0,
        type=float,
        default=None,
        help="Use EOS token check reward - scores 1 if EOS is last token, 0 otherwise (default: 1.0)",
    )
    parser.add_argument(
        "--vllm_mode",
        type=str,
        default="colocate",
        choices=["colocate", "server", "none"],
        help="VLLM execution mode: colocate, server, or none to disable vllm (default: colocate)",
    )
    parser.add_argument("--num_iterations", type=int, default=1, help="Number of GRPO iterations (default: 1)")
    parser.add_argument("--num_generations", type=int, default=28, help="Number of generations per prompt (default: 28)")

    args = parser.parse_args()

    # Set up output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Initialize wandb only on the main process (rank 0)
    if is_main_process():
        wandb.init(project=args.wandb_project, name=args.wandb_run_name, config=vars(args))
        logger.info(f"Initialized wandb project: {args.wandb_project} (rank {get_rank()})")
        report_to = ["wandb"]
    else:
        logger.info(f"Skipping wandb initialization on rank {get_rank()}")
        report_to = []  # No reporting for non-main processes

    # Verify train bench_data_folder exists
    if not os.path.exists(args.train_bench_data_folder):
        logger.error(f"Train bench data folder not found: {args.train_bench_data_folder}")
        return

    # Set eval folder to train folder if not specified
    if args.eval_bench_data_folder is None:
        args.eval_bench_data_folder = args.train_bench_data_folder
        logger.info(f"Using train folder for evaluation: {args.eval_bench_data_folder}")
    elif not os.path.exists(args.eval_bench_data_folder):
        logger.error(f"Eval bench data folder not found: {args.eval_bench_data_folder}")
        return

    # Load processor
    logger.info(f"Loading processor: {args.model_name}")
    processor = AutoProcessor.from_pretrained(
        args.model_name,
        trust_remote_code=True,
    )

    # Load model
    logger.info(f"Loading model: {args.model_name}")
    if "Qwen2-VL" in args.model_name:
        model_class = Qwen2VLForConditionalGeneration
    else:
        model_class = Qwen2_5_VLForConditionalGeneration

    model = model_class.from_pretrained(
        args.model_name,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )

    # Create training dataset
    logger.info(f"Creating training dataset from: {args.train_bench_data_folder}")
    train_dataset = OlmOCRBenchDataset(
        bench_data_folder=args.train_bench_data_folder,
        processor=processor,
        max_samples=args.max_train_samples,
        target_longest_image_dim=1288,
    )

    if len(train_dataset) == 0:
        logger.error("No samples found in training dataset!")
        return

    # Create evaluation dataset
    logger.info(f"Creating evaluation dataset from: {args.eval_bench_data_folder}")
    eval_dataset = OlmOCRBenchDataset(
        bench_data_folder=args.eval_bench_data_folder,
        processor=processor,
        max_samples=args.max_eval_samples,
        target_longest_image_dim=1288,
    )

    if len(eval_dataset) == 0:
        logger.warning("No samples found in evaluation dataset, using training dataset for eval")
        eval_dataset = train_dataset

    # Build list of reward functions and weights based on command-line arguments
    reward_funcs = []
    reward_weights = []
    reward_names = []

    if args.reward_bench is not None:
        reward_funcs.append(olmocr_bench_reward)
        reward_weights.append(args.reward_bench)
        reward_names.append("bench")
        logger.info(f"Added bench-based reward function with weight {args.reward_bench}")

    if args.reward_medoid is not None:
        reward_funcs.append(medoid_reward)
        reward_weights.append(args.reward_medoid)
        reward_names.append("medoid")
        logger.info(f"Added medoid-based reward function with weight {args.reward_medoid}")

    if args.reward_bench_edit_distance is not None:
        reward_funcs.append(bench_edit_distance_reward)
        reward_weights.append(args.reward_bench_edit_distance)
        reward_names.append("bench_edit_distance")
        logger.info(f"Added bench edit distance reward function with weight {args.reward_bench_edit_distance}")

    if args.reward_front_matter is not None:
        reward_funcs.append(reward_front_matter)
        reward_weights.append(args.reward_front_matter)
        reward_names.append("front_matter")
        logger.info(f"Added front matter validation reward function with weight {args.reward_front_matter}")

    if args.reward_element_count is not None:
        reward_funcs.append(reward_element_count)
        reward_weights.append(args.reward_element_count)
        reward_names.append("element_count")
        logger.info(f"Added element count matching reward function with weight {args.reward_element_count}")

    if args.reward_eos is not None:
        # Get EOS token ID from processor's tokenizer
        eos_token_id = processor.tokenizer.eos_token_id
        logger.info(f"EOS token ID from tokenizer: {eos_token_id}")

        # Create a wrapper function with proper __name__ attribute
        def reward_eos_wrapper(prompts, completions, completion_ids, **kwargs):
            return reward_eos(eos_token_id, prompts, completions, completion_ids, **kwargs)

        reward_eos_wrapper.__name__ = "reward_eos"
        reward_funcs.append(reward_eos_wrapper)
        reward_weights.append(args.reward_eos)
        reward_names.append("eos")
        logger.info(f"Added EOS token check reward function with weight {args.reward_eos}")

    if not reward_funcs:
        logger.error(
            "No reward function specified. Use at least one of: --reward_bench, --reward_medoid, --reward_bench_edit_distance, --reward_front_matter, --reward_element_count, --reward_eos"
        )
        return

    # Log summary of reward configuration
    logger.info(f"\n" + "=" * 50)
    logger.info(f"Reward Configuration:")
    logger.info(f"Using {len(reward_funcs)} reward function(s):")
    for name, weight in zip(reward_names, reward_weights):
        logger.info(f"  - {name}: weight={weight}")
    logger.info("=" * 50 + "\n")

    # Set up GRPO configuration
    grpo_config = GRPOConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.per_device_train_batch_size,
        per_device_eval_batch_size=args.per_device_eval_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        logging_steps=10,
        save_steps=100,
        save_total_limit=3,
        eval_steps=50,
        warmup_steps=args.warmup_steps,
        max_prompt_length=3000,
        max_completion_length=3000,
        temperature=0.7,
        report_to=report_to,
        remove_unused_columns=False,
        bf16=True,
        shuffle_dataset=True,
        seed=args.seed,
        dataloader_num_workers=8,
        dataloader_drop_last=True,
        # GRPO-specific parameters
        loss_type=args.loss_type,
        scale_rewards=args.scale_rewards,
        beta=args.beta,
        importance_sampling_level=args.importance_sampling_level,
        reward_weights=reward_weights,
        num_iterations=args.num_iterations,
        num_generations=args.num_generations,
        # Vllm setup to speed up generation
        use_vllm=(args.vllm_mode != "none"),
        vllm_mode=args.vllm_mode if args.vllm_mode != "none" else "colocate",
        vllm_gpu_memory_utilization=0.15,
        log_completions=True,
    )

    # Initialize GRPO trainer
    logger.info("Initializing GRPO trainer")
    trainer = GRPOTrainer(
        model=model,
        args=grpo_config,
        processing_class=processor,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        reward_funcs=reward_funcs,
    )

    # Start training
    logger.info("Starting GRPO training")
    try:
        trainer.train()

        # Save final model
        logger.info(f"Saving final model to {args.output_dir}/step-final")
        trainer.save_model()
        processor.save_pretrained(os.path.join(args.output_dir, "step-final"))

        logger.info("Training completed successfully!")

        # Close wandb only on main process
        if is_main_process():
            wandb.finish()

    except Exception as e:
        logger.error(f"Training failed: {e}")
        raise


if __name__ == "__main__":
    main()
