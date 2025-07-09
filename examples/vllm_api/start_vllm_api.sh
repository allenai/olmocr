#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Model Selection ---
MODEL="allenai/olmOCR-7B-0225-preview"
if [[ "$1" == "fp8" ]]; then
  MODEL="allenai/olmOCR-7B-0225-preview-FP8"
  echo "🚀 Using the FP8 model: $MODEL"
else
  echo "✅ Using the default model: $MODEL"
fi

# --- Environment and Dependency Setup ---
echo "🛠️  Setting up Python environment..."

# Only initialize the project if pyproject.toml doesn't exist
if [ ! -f pyproject.toml ]; then
    echo "📄 'pyproject.toml' not found. Initializing uv project..."
    uv init .
else
    echo "📄 Project is already initialized."
fi

# Only create the virtual environment if the .venv directory doesn't exist
if [ ! -d .venv ]; then
    echo "🐍 Virtual environment not found. Creating..."
    uv venv --python 3.12 --seed
else
    echo "🐍 Virtual environment already exists."
fi

# Activate the virtual environment
source .venv/bin/activate

echo "📦 Installing/updating dependencies (vllm, huggingface_hub)..."
uv pip install vllm --torch-backend=auto huggingface-hub

# --- Hugging Face Login ---
echo "🔑 Logging into Hugging Face..."
if [ -z "$HUGGING_FACE_HUB_TOKEN" ]; then
  huggingface-cli login
else
  huggingface-cli login --token $HUGGING_FACE_HUB_TOKEN
fi

# --- Run VLLM Server ---
echo "Starting VLLM server..."
uv run --with vllm vllm serve "$MODEL" \
  --port 6900 \
  --max-num-batched-tokens 4096 \
  --gpu-memory-utilization 0.90
