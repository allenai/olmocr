# olmOCR VLLM Server Automation

This project contains scripts to automate the setup and execution of a [VLLM](https://github.com/vllm-project/vllm) server for running the `allenai/olmOCR` models. It simplifies the process of logging into Hugging Face, creating a Python environment, and launching the server with a specified model.

-----

## Prerequisites

Before you begin, ensure you have the following installed and configured:

  * **Git**: For version control.
  * **uv**: A fast Python package installer and resolver.
  * **Hugging Face Account**: You need an account and a [User Access Token](https://huggingface.co/settings/tokens) with `write` permissions.

-----

## 🚀 Setup

1.  **Clone the Repository** (if applicable)
    ```bash
    git clone git@github.com:allenai/olmocr.git
    cd olmocr
    ```
2.  **Make Scripts Executable**
    Give execution permissions to the shell scripts in this directory.
    ```bash
    chmod +x *.sh
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

The script will first handle the Hugging Face login, configure git, set up the virtual environment with `uv`, and then start the server with your chosen model.


## 📜 Scripts Overview

  * `start_vllm.sh`: The main script that automates environment setup and starts the VLLM server. It defaults to the standard `olmOCR` model but can switch to the `FP8` version if `fp8` is passed as an argument.
