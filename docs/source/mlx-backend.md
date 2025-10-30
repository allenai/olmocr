# MLX-VLM Backend for Apple Silicon

This guide explains how to use olmOCR with the MLX-VLM backend for efficient inference on Apple Silicon Macs (M1, M2, M3, M4, etc.).

## Table of Contents

- [Overview](#overview)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Options](#configuration-options)
- [Model Selection](#model-selection)
- [Performance Optimization](#performance-optimization)
- [Troubleshooting](#troubleshooting)
- [API Differences](#api-differences)
- [Limitations](#limitations)

## Overview

### What is MLX-VLM?

MLX-VLM is a vision-language model inference engine built on Apple's MLX framework. It provides:

- **Native Apple Silicon support**: Optimized for M-series chips
- **Unified memory architecture**: Efficient use of shared CPU/GPU memory
- **On-device inference**: No need for cloud APIs or remote servers
- **Quantization support**: 4-bit and 8-bit quantization for reduced memory usage

### Why Use MLX-VLM?

- **No NVIDIA GPU required**: Run olmOCR on your Mac laptop or desktop
- **Cost-effective**: No cloud inference costs
- **Privacy**: All processing happens on-device
- **Portability**: Develop and test locally before deploying to production

### vLLM vs MLX-VLM

| Feature | vLLM | MLX-VLM |
|---------|------|---------|
| Platform | Linux + NVIDIA GPUs | macOS + Apple Silicon |
| Memory | VRAM (dedicated GPU) | Unified memory (CPU+GPU) |
| Guided decoding | ✅ Yes | ❌ No (post-validation instead) |
| Quantization | FP8, INT8 | 4-bit, 8-bit, mixed |
| Default port | 30024 | 8000 |
| API format | OpenAI Chat Completions | OpenAI Responses |

## System Requirements

### Hardware

- **Apple Silicon Mac** (M1, M2, M3, M4, or later)
- **16GB+ RAM recommended** (8GB minimum for 4-bit quantized models)
- **20GB+ free disk space** for model storage

### Software

- **macOS 15.0+** (Sequoia or later)
- **Python 3.11+**
- **olmocr** with MLX support

### Verification

Check your system:

```bash
# Check architecture
uname -m
# Should output: arm64

# Check macOS version
sw_vers
# Should show ProductVersion: 15.0 or higher
```

## Installation

### Standard Installation

```bash
# Install olmocr with MLX support
pip install olmocr[mlx]

# Or add to existing installation
pip install mlx-vlm>=0.3.5
```

### Development Installation

```bash
# Clone and install in development mode
git clone https://github.com/allenai/olmocr.git
cd olmocr
pip install -e .[mlx]
```

### Verify Installation

```bash
python -c "import mlx_vlm; print('MLX-VLM installed:', mlx_vlm.__version__)"
```

## Quick Start

### Using Pre-Quantized Models

The fastest way to get started is with pre-quantized MLX models from HuggingFace:

```bash
# Create a workspace directory
mkdir -p ~/olmocr-test/workspace

# Download a sample PDF (or use your own)
curl -o ~/olmocr-test/sample.pdf https://arxiv.org/pdf/2410.12971

# Run olmOCR with 4-bit quantized model
olmocr ~/olmocr-test/workspace \
  --pdfs ~/olmocr-test/sample.pdf \
  --backend mlx-vlm \
  --model mlx-community/olmOCR-2-7B-1025-mlx-4bit
```

The first run will:
1. Download the model (~2GB for 4-bit, ~4GB for 8-bit)
2. Start the MLX-VLM server
3. Process your PDFs
4. Save results to `~/olmocr-test/workspace/results/`

### Using 8-bit Model (Better Quality)

For improved quality with more memory:

```bash
olmocr ~/olmocr-test/workspace \
  --pdfs ~/olmocr-test/sample.pdf \
  --backend mlx-vlm \
  --model mlx-community/olmOCR-2-7B-1025-mlx-8bit
```

### Programmatic API

```python
import asyncio
from olmocr import run_pipeline, PipelineConfig

config = PipelineConfig(
    workspace="./workspace",
    pdfs=["document.pdf"],
    backend="mlx-vlm",
    model="mlx-community/olmOCR-2-7B-1025-mlx-4bit",
    markdown=True,
    workers=10
)

asyncio.run(run_pipeline(config))
```

## Configuration Options

### Backend Selection

```bash
# Use MLX-VLM (default: vllm)
--backend mlx-vlm
```

### Model Selection

```bash
# Pre-quantized models (recommended)
--model mlx-community/olmOCR-2-7B-1025-mlx-4bit    # ~2GB, fastest
--model mlx-community/olmOCR-2-7B-1025-mlx-8bit    # ~4GB, better quality

# Convert from HuggingFace (advanced)
--model /path/to/converted/mlx/model
```

### Server Configuration

```bash
# Custom port (default: 8000 for MLX-VLM)
--port 8080

# Number of concurrent workers (default: 20)
--workers 10
```

### Output Options

```bash
# Also generate markdown files
--markdown

# Custom OCR prompt
--custom_prompt "Extract all text from this document, preserving formatting..."
```

### Advanced Options

```bash
# Maximum retry attempts per page (default: 8)
--max_page_retries 5

# Maximum error rate before discarding document (default: 0.004)
--max_page_error_rate 0.01

# Target image dimension for PDF rendering (default: 1288)
--target_longest_image_dim 1024
```

## Model Selection

### Available Pre-Quantized Models

| Model | Size | Memory | Quality | Use Case |
|-------|------|--------|---------|----------|
| `mlx-community/olmOCR-2-7B-1025-mlx-4bit` | ~2GB | 8GB+ RAM | Good | Laptops, quick tests |
| `mlx-community/olmOCR-2-7B-1025-mlx-8bit` | ~4GB | 12GB+ RAM | Better | Production, accuracy-critical |

### Converting Custom Models

If you have a fine-tuned olmOCR model:

```bash
# Convert HuggingFace model to MLX format
python -m olmocr.convert_to_mlx \
  allenai/olmOCR-2-7B-1025 \
  --output ~/models/olmocr-mlx \
  --quantize 4bit

# Use converted model
olmocr workspace/ --backend mlx-vlm --model ~/models/olmocr-mlx
```

### Quantization Trade-offs

**4-bit quantization:**
- ✅ Smallest size (~2GB)
- ✅ Fastest inference
- ✅ Lowest memory usage
- ❌ Slightly reduced accuracy

**8-bit quantization:**
- ✅ Better accuracy
- ✅ Good size/quality balance (~4GB)
- ❌ Higher memory usage
- ❌ Slightly slower inference

## Performance Optimization

### Memory Management

MLX uses unified memory (shared between CPU and GPU). Monitor usage:

```bash
# Check memory usage while processing
while true; do
  ps aux | grep mlx_vlm.server | grep -v grep
  sleep 5
done
```

### Optimal Worker Count

The `--workers` parameter controls concurrency:

```bash
# Conservative (safer for 8GB Macs)
--workers 5

# Balanced (16GB+ Macs)
--workers 10

# Aggressive (32GB+ Macs)
--workers 20
```

Monitor and adjust based on memory pressure.

### Batch Processing

For large document collections, process in batches:

```bash
# Process 100 PDFs at a time
find pdfs/ -name "*.pdf" | head -100 > batch1.txt
olmocr workspace/ --pdfs batch1.txt --backend mlx-vlm --model mlx-community/olmOCR-2-7B-1025-mlx-4bit
```

### Image Resolution

Lower resolution reduces memory and increases speed:

```bash
# Default: 1288
--target_longest_image_dim 1024  # Faster, lower quality
--target_longest_image_dim 1536  # Slower, better quality
```

## Troubleshooting

### "mlx-vlm not installed"

```bash
pip install mlx-vlm>=0.3.5
# Or
pip install olmocr[mlx]
```

### "MLX backend requires Apple Silicon"

MLX-VLM only works on Apple Silicon Macs (M1/M2/M3/M4). For Intel Macs or other platforms, use vLLM:

```bash
olmocr workspace/ --backend vllm --model allenai/olmOCR-2-7B-1025-FP8
```

### Out of Memory Errors

1. **Use 4-bit quantization:**
   ```bash
   --model mlx-community/olmOCR-2-7B-1025-mlx-4bit
   ```

2. **Reduce workers:**
   ```bash
   --workers 5
   ```

3. **Lower image resolution:**
   ```bash
   --target_longest_image_dim 1024
   ```

4. **Close other applications** to free memory

### Server Won't Start

Check if port is already in use:

```bash
lsof -i :8000
# If occupied, use different port
--port 8080
```

### Slow Performance

1. **Check memory pressure:**
   ```bash
   # Open Activity Monitor and check Memory Pressure
   open -a "Activity Monitor"
   ```

2. **Reduce concurrent workers**

3. **Use 4-bit model** instead of 8-bit

4. **Close background applications**

### Invalid Response Format

MLX-VLM doesn't support guided decoding. Invalid responses are automatically retried. If you see many retries:

1. Check model quality (try 8-bit instead of 4-bit)
2. Inspect the PDF quality (scans, complex layouts)
3. Try a custom prompt with clearer instructions

## API Differences

### Request Format

**vLLM (Chat Completions API):**
```json
{
  "model": "olmocr",
  "messages": [...],
  "max_tokens": 8000,
  "temperature": 0.0
}
```

**MLX-VLM (Responses API):**
```json
{
  "model": "current",
  "input": [...],
  "max_output_tokens": 8000,
  "temperature": 0.0
}
```

### Response Format

**vLLM:**
```json
{
  "choices": [{"message": {"content": "..."}}],
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 200
  }
}
```

**MLX-VLM:**
```json
{
  "output": [{"content": [{"text": "..."}]}],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 200
  }
}
```

### Guided Decoding

**vLLM:** Supports `guided_regex` for constrained generation

**MLX-VLM:** No guided decoding support. The backend automatically validates responses and retries if the YAML format is invalid.

## Limitations

### Current Limitations

1. **No guided decoding**: Responses are validated after generation, may require retries
2. **macOS only**: Requires Apple Silicon Mac
3. **Single GPU**: No multi-GPU support (MLX uses unified memory)
4. **Model size**: Limited by available RAM (use quantization for larger models)

### Known Issues

- **First request slow**: Model loading happens on first request (~10-30 seconds)
- **Memory growth**: Long-running processes may gradually use more memory (restart server periodically)
- **PDF rendering**: Complex PDFs with many layers may be slow

### Workarounds

**For guided decoding:**
- Use 8-bit models for better response quality
- Enable `--guided_decoding` flag (triggers stricter post-validation)
- Increase `--max_page_retries` if needed

**For memory:**
- Process in batches
- Restart pipeline periodically for very large jobs
- Use 4-bit quantization

## Performance Comparison

Approximate throughput on different Mac models:

| Mac Model | Quantization | Pages/min | Notes |
|-----------|--------------|-----------|-------|
| M1 (8GB) | 4-bit | 5-8 | Reduce workers to 5 |
| M1 Pro (16GB) | 4-bit | 10-15 | Balanced |
| M1 Pro (16GB) | 8-bit | 8-12 | Better quality |
| M2 Max (32GB) | 8-bit | 15-20 | Recommended |
| M3 Max (64GB) | 8-bit | 20-30 | Best performance |

*Actual performance varies based on PDF complexity, image resolution, and concurrent workers.*

## Next Steps

- **Production deployment**: Consider cloud GPUs with vLLM for high-volume processing
- **Fine-tuning**: Train custom models for domain-specific documents
- **Evaluation**: Use olmOCR's built-in benchmarking tools to compare vLLM vs MLX-VLM
- **Integration**: Use the programmatic API to embed olmOCR in your applications

## Related Documentation

- [Main README](../README.md)
- [Pipeline Configuration](https://github.com/allenai/olmocr)
- [MLX Framework](https://ml-explore.github.io/mlx/)
- [MLX-VLM Repository](https://github.com/Blaizzy/mlx-vlm)

## Support

For issues specific to:
- **olmOCR MLX backend**: [GitHub Issues](https://github.com/allenai/olmocr/issues)
- **MLX-VLM**: [MLX-VLM GitHub](https://github.com/Blaizzy/mlx-vlm/issues)
- **MLX framework**: [MLX GitHub](https://github.com/ml-explore/mlx/issues)