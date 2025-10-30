#!/usr/bin/env python
"""Convert HuggingFace models to MLX format for use with Apple Silicon.

This utility wraps mlx_vlm.convert to make it easy to convert olmOCR models
to MLX format for efficient inference on Apple Silicon Macs.

Example usage:
    # Convert from HuggingFace Hub
    python -m olmocr.convert_to_mlx allenai/olmOCR-2-7B-1025 --output ~/models/olmocr-mlx

    # Convert with 4-bit quantization
    python -m olmocr.convert_to_mlx allenai/olmOCR-2-7B-1025 --quantize 4 --output ~/models/olmocr-mlx-4bit

    # Convert local checkpoint with 8-bit quantization
    python -m olmocr.convert_to_mlx /path/to/local/model --quantize 8 --output ~/models/olmocr-mlx
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def convert_to_mlx(
    model_path: str,
    output_path: str,
    quantize_bits: Optional[int] = None,
    group_size: int = 64,
    upload_to_hub: bool = False,
    hf_repo: Optional[str] = None,
) -> None:
    """
    Convert a model to MLX format.

    Args:
        model_path: Path to HuggingFace model (local or hub ID)
        output_path: Directory to save converted model
        quantize_bits: Quantization bits (4 or 8, None for no quantization)
        group_size: Group size for quantization (default: 64)
        upload_to_hub: Whether to upload result to HuggingFace Hub
        hf_repo: HuggingFace Hub path for upload (required if upload_to_hub=True)
    """
    try:
        from mlx_vlm import convert
    except ImportError:
        logger.error(
            "mlx-vlm not installed. Install with: pip install mlx-vlm\n"
            "Or install olmocr with MLX support: pip install olmocr[mlx]"
        )
        sys.exit(1)

    # Validate platform
    import platform

    if platform.system() != "Darwin":
        logger.error("MLX conversion only works on macOS")
        sys.exit(1)

    if platform.machine() not in ["arm64", "aarch64"]:
        logger.error("MLX requires Apple Silicon (M-series chips)")
        sys.exit(1)

    # Create output directory if it doesn't exist
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info(f"Converting {model_path} to MLX format")
    logger.info("=" * 70)
    logger.info(f"Output directory: {output_path}")

    if quantize_bits:
        logger.info(f"Quantization: {quantize_bits}-bit, group_size={group_size}")
    else:
        logger.info("Quantization: None (full precision)")

    try:
        logger.info("Step 1/3: Downloading model from HuggingFace...")
        logger.info("This may take a while depending on your internet connection")

        logger.info("Step 2/3: Converting model to MLX format...")

        # Call mlx_vlm convert function directly
        convert(
            hf_path=model_path,
            mlx_path=output_path,
            quantize=bool(quantize_bits),
            q_bits=quantize_bits if quantize_bits else 16,
            q_group_size=group_size,
            upload_repo=hf_repo if upload_to_hub else None,
        )

        logger.info("Step 3/3: Saving converted model...")
        logger.info(f"✓ Model successfully converted and saved to: {output_path}")

        # Print model details
        logger.info("\nConverted model details:")
        logger.info(f"  - Model: {model_path}")
        if quantize_bits:
            logger.info(f"  - Quantization: {quantize_bits}-bit")
            logger.info(f"  - Group size: {group_size}")
        logger.info(f"  - Location: {output_path}")

        # Print usage instructions
        logger.info("\nTo use this model with olmOCR:")
        logger.info(f"  olmocr <workspace> --backend mlx-vlm --model {output_path}")

    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        logger.error("Make sure you have:")
        logger.error("  1. Sufficient disk space (~20GB)")
        logger.error("  2. Sufficient memory (16GB+ recommended)")
        logger.error("  3. Working internet connection")
        logger.error("  4. All dependencies installed")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Convert HuggingFace models to MLX format for Apple Silicon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert from HuggingFace Hub (full precision)
  %(prog)s allenai/olmOCR-2-7B-1025 --output ~/models/olmocr-mlx

  # Convert with 4-bit quantization (smallest size)
  %(prog)s allenai/olmOCR-2-7B-1025 --quantize 4 --output ~/models/olmocr-mlx-4bit

  # Convert with 8-bit quantization (balanced)
  %(prog)s allenai/olmOCR-2-7B-1025 --quantize 8 --output ~/models/olmocr-mlx-8bit

  # Convert local checkpoint
  %(prog)s /path/to/checkpoint --quantize 8 --output ~/models/olmocr-mlx

Quantization options:
  4           - 4-bit quantization (~2GB, fastest, slightly reduced accuracy)
  8           - 8-bit quantization (~4GB, good balance of size and quality)
  (none)      - Full precision (~14GB, best accuracy, slowest)
        """,
    )

    parser.add_argument(
        "model_path",
        help="HuggingFace model ID (e.g., allenai/olmOCR-2-7B-1025) or local path",
    )

    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory for converted MLX model",
    )

    parser.add_argument(
        "--quantize",
        "-q",
        type=int,
        choices=[4, 8],
        default=None,
        help="Quantization bits: 4 or 8 (default: no quantization)",
    )

    parser.add_argument(
        "--group-size",
        "-g",
        type=int,
        default=64,
        help="Group size for quantization (default: 64)",
    )

    parser.add_argument(
        "--upload-to-hub",
        action="store_true",
        help="Upload converted model to HuggingFace Hub",
    )

    parser.add_argument(
        "--hf-repo",
        help="HuggingFace repo path for upload (required with --upload-to-hub)",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # Validate arguments
    if args.upload_to_hub and not args.hf_repo:
        parser.error("--hf-repo is required when using --upload-to-hub")

    # Run conversion
    convert_to_mlx(
        model_path=args.model_path,
        output_path=args.output,
        quantize_bits=args.quantize,
        group_size=args.group_size,
        upload_to_hub=args.upload_to_hub,
        hf_repo=args.hf_repo,
    )


if __name__ == "__main__":
    main()
