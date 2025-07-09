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

echo "📦 Installing vllm and core dependencies..."
# First, install vllm and its dependencies, which brings in torch
uv pip install "vllm~=0.9.1" --torch-backend=auto huggingface-hub openai PyMuPDF Pillow


# --- Optional: Install flashinfer for performance ---
# Uncomment the line below to install flashinfer.
# echo "🚀 (Optional) Installing flashinfer for faster inference..."
# uv pip install https://download.pytorch.org/whl/cu128/flashinfer/flashinfer_python-0.2.5%2Bcu128torch2.7-cp38-abi3-linux_x86_64.whl 

# --- Hugging Face Login ---
echo "🔑 Checking Hugging Face login status..."

# Use 'whoami' to check login. If the command fails, then prompt for login.
# The >/dev/null 2>&1 part suppresses command output so it's not noisy.
if ! huggingface-cli whoami >/dev/null 2>&1; then
  echo "⚠️ Not logged in. Please provide your Hugging Face token."
  # Use an environment variable if it exists, otherwise prompt interactively.
  if [ -n "$HUGGING_FACE_HUB_TOKEN" ]; then
    huggingface-cli login --token $HUGGING_FACE_HUB_TOKEN
  else
    huggingface-cli login
  fi
else
  echo "✅ Already logged in to Hugging Face."
fi


# --- Run VLLM Server ---
echo "Starting VLLM server..."
uv run --with vllm vllm serve "$MODEL" \
  --port 6900 \
  --max-num-batched-tokens 4096 \
  --gpu-memory-utilization 0.90
