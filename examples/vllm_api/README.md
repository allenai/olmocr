# olmOCR VLLM Server Automation

This project contains scripts to automate the setup and execution of a [VLLM](https://github.com/vllm-project/vllm) server for running the `allenai/olmOCR` models. It simplifies the process of logging into Hugging Face, creating a Python environment, and launching the server with a specified model.

-----

## Prerequisites

Before you begin, ensure you have the following installed and configured:

  * **uv**: A fast Python package installer and resolver.
  * **CUDA**: Ensure you have the appropriate CUDA version installed for your GPU.
  * **Hugging Face Account**: You need an account and a [User Access Token](https://huggingface.co/settings/tokens) with `write` permissions.

-----

## 🚀 Setup

1. **Clone the Repository:**
    ```bash
    git clone git@github.com:allenai/olmocr.git
    cd olmocr/examples/vllm_api
    ```

2.  **Make Scripts Executable:**
    ```bash
    chmod +x start_vllm_api.sh
    ```
-----

## ▶️ Usage

### Running the VLLM Server

The `start_vllm.sh` script handles everything from login to server launch. You can choose which model to run by passing an optional argument.

  * **To run the standard `olmOCR-7B` model:**
    ```bash
    ./start_vllm_api.sh
    ```
  * **To run the `FP8` quantized model:**
    ```bash
    ./start_vllm_api.sh fp8
    ```

The script will first handle the Hugging Face login, set up the virtual environment with `uv`, and then start the server with your chosen model.

-----
## 🛠️ Test the Server

To test that the server is working correctly, open a new, separate terminal window and follow these steps:

1. **Activate the virtual environment:**
   ```bash
   source .venv/bin/activate
   ```

2. **Run the test client:**
   ```bash
   python main.py
   ```

3. **Deactivate the virtual environment when done:**
   ```bash
   deactivate
   ```
The script will pick a random PDF from the tests/gnarly_pdfs folder, send it to your running server, and print the OCR transcription.

## 📜 Scripts Overview

  * `start_vllm.sh`: The main script that automates environment setup and starts the VLLM server. It defaults to the standard `olmOCR` model but can switch to the `FP8` version if `fp8` is passed as an argument.
  * `main.py`: A test client script to interact with the running VLLM server.

## 🖥️ Tested Environment
This setup has been tested and confirmed to work on the following configuration:
  * **Ubuntu 24.04**
  * **GPU: NVIDIA RTX 3090 Ti**
  * **CUDA Version: 12.2**
  * **uv 0.7.10**
