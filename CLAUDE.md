# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

olmOCR is a toolkit for converting PDFs and other image-based document formats into clean, readable, plain text format. It's powered by a 7B parameter Vision Language Model and requires GPU acceleration.

Core features:
- Convert PDF, PNG, and JPEG documents into clean Markdown
- Support for equations, tables, handwriting, and complex formatting
- Automatically removes headers and footers
- Natural reading order extraction from multi-column layouts and complex documents
- Efficient batch processing for millions of documents

## Architecture

The codebase is organized into several key modules:

### Core Pipeline (`olmocr/pipeline.py`)
The main entry point for document conversion. Handles:
- PDF rendering to images using poppler
- Batch processing with work queue management
- vLLM server integration for model inference
- S3 integration for distributed processing
- Parallel processing and error handling

### Data Processing (`olmocr/data/`)
- `renderpdf.py`: PDF to image rendering utilities
- `buildsilver.py`: Data preparation and prompting strategies for training

### Benchmarking (`olmocr/bench/`)
- Comprehensive benchmark suite (olmOCR-Bench) with 7,000+ test cases
- Multiple runner implementations for different OCR systems
- Evaluation metrics and reporting tools

### Training (`olmocr/train/`)
- Training infrastructure for VLM models
- Support for Qwen2-VL and Molmo-O architectures
- Data preparation and configuration management

### Filtering (`olmocr/filter/`)
- Language detection and SEO spam filtering
- Document quality assessment

### Utilities
- `s3_utils.py`: AWS S3 integration for distributed processing
- `image_utils.py`: Image processing utilities
- `work_queue.py`: Distributed work coordination

## Development Commands

### Setup
```bash
# Create conda environment
conda create -n olmocr python=3.11
conda activate olmocr

# Install for development
pip install olmocr[dev] --extra-index-url https://download.pytorch.org/whl/cu128

# Install for GPU inference
pip install olmocr[gpu] --extra-index-url https://download.pytorch.org/whl/cu128

# Install for benchmarking only
pip install olmocr[bench]
```

### Code Quality and Testing
```bash
# Run all checks (linting, formatting, type checking, tests)
make run-checks

# Individual commands
isort --check .          # Import sorting
black --check .          # Code formatting
ruff check .             # Linting
mypy .                   # Type checking
pytest -v tests/         # Run tests
```

### Building and Documentation
```bash
# Build package
make build

# Build and serve documentation
make docs
```

### Running the Pipeline

Local inference:
```bash
python -m olmocr.pipeline ./workspace --markdown --pdfs path/to/files/*.pdf
```

With external vLLM server:
```bash
python -m olmocr.pipeline ./workspace --server http://server:8000 --markdown --pdfs files/*.pdf
```

Distributed processing with S3:
```bash
python -m olmocr.pipeline s3://bucket/workspace --pdfs s3://bucket/pdfs/*.pdf
```

### Benchmarking
```bash
# Run benchmark evaluation
python -m olmocr.bench.benchmark --workspace ./bench_workspace --models olmocr
```

### Training
```bash
# Train new model
python -m olmocr.train.train --config path/to/config.yaml
```

## Key Configuration

- **Model**: Default is `allenai/olmOCR-7B-0825-FP8` from HuggingFace
- **Dependencies**: Requires poppler-utils for PDF rendering, CUDA for GPU acceleration
- **Memory Requirements**: ~15GB GPU RAM minimum
- **Supported Formats**: PDF, PNG, JPEG

## Testing Strategy

- Unit tests in `tests/` directory using pytest
- Benchmarking framework for end-to-end evaluation
- GPU tests are disabled by default (`CUDA_VISIBLE_DEVICES=''`)
- Integration tests cover the full pipeline workflow

## Release Process

1. Update version in `olmocr/version.py`
2. Run `./scripts/release.sh` to create tag and trigger GitHub Actions workflow