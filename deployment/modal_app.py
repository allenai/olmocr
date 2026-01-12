"""
Modal deployment for olmOCR API with vLLM backend.

This deploys the full olmOCR service on Modal, including:
- vLLM server for the olmOCR-2-7B model (protected with API key)
- FastAPI wrapper for PDF-to-markdown conversion (protected with Bearer token)

Setup:
1. Create a Modal Secret named "olmocr-api-key" with content: {OLMOCR_API_KEY: "your-secret-token"}
   Visit: https://modal.com/secrets
   This key protects both the vLLM server and the FastAPI endpoints.
   
Deploy with:
    modal deploy deployment/modal_app.py

Test with:
    modal run deployment/modal_app.py

Use the deployed API:
    curl -X POST "https://your-workspace--olmocr-api-convert.modal.run" \
        -H "Authorization: Bearer your-secret-token" \
        -F "file=@document.pdf"

Security:
- The same API key protects both the vLLM server and FastAPI endpoints
- The FastAPI layer passes the key to vLLM automatically
- Only the /health endpoint is public (no auth required)
"""

import subprocess

import modal

# Modal app
app = modal.App("olmocr-api")

# Model configuration
MODEL_NAME = "allenai/olmOCR-2-7B-1025-FP8"
MODEL_REVISION = "19133a8e683f7203f37c49000377c11a896c8d9b"
VLLM_PORT = 12345

# Single image with vLLM + olmOCR
image = (
    modal.Image.from_registry("nvidia/cuda:12.8.0-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .apt_install(
        "poppler-utils",  # for pdftotext (used in fallback)
        "fonts-crosextra-caladea",
        "fonts-crosextra-carlito",
        "gsfonts",
        "lcdf-typetools",
    )
    .uv_pip_install(
        "vllm==0.11.2",
        "huggingface-hub==0.36.0",
        "flashinfer-python==0.5.2",
    )
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})  # faster model transfers
    .add_local_dir(".", remote_path="/build", copy=True)
    .workdir("/build")
    .env({"UV_INDEX_STRATEGY": "unsafe-best-match"})
    .uv_pip_install(
        ".",
        "fastapi",
        "uvicorn",
        "python-multipart",
    )
)

# Cache volumes for model weights and compilation artifacts
hf_cache_vol = modal.Volume.from_name("olmocr-huggingface-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("olmocr-vllm-cache", create_if_missing=True)

# Configuration
N_GPU = 1
MINUTES = 60
FAST_BOOT = True  # Set to False for better performance with persistent replicas


@app.function(
    image=image,
    gpu=f"L40S:{N_GPU}",
    scaledown_window=10 * MINUTES,
    timeout=10 * MINUTES,
    volumes={
        "/root/.cache/huggingface": hf_cache_vol,
        "/root/.cache/vllm": vllm_cache_vol,
    },
    secrets=[modal.Secret.from_name("olmocr-api-key")],
)
@modal.concurrent(
    max_inputs=16,
)
@modal.web_server(port=VLLM_PORT, startup_timeout=10 * MINUTES)
def serve_vllm():
    """Start the vLLM server for the olmOCR model."""
    import os

    cmd = [
        "vllm",
        "serve",
        "--uvicorn-log-level=info",
        MODEL_NAME,
        "--revision",
        MODEL_REVISION,
        "--served-model-name",
        MODEL_NAME,
        "--host",
        "0.0.0.0",
        "--port",
        str(VLLM_PORT),
        "--gpu-memory-utilization",
        "0.80",
        "--max-model-len",
        "16384",
        "--disable-log-requests",
    ]

    # Add API key protection if configured
    vllm_api_key = os.environ.get("OLMOCR_API_KEY")
    if vllm_api_key:
        cmd.extend(["--api-key", vllm_api_key])

    if FAST_BOOT:
        cmd.append("--enforce-eager")
    else:
        cmd.append("--no-enforce-eager")

    cmd += ["--tensor-parallel-size", str(N_GPU)]

    print("Starting vLLM server with command:", " ".join(cmd))
    subprocess.Popen(" ".join(cmd), shell=True)


@app.function(
    image=image,
    scaledown_window=15 * MINUTES,
    timeout=20 * MINUTES,
    secrets=[modal.Secret.from_name("olmocr-api-key")],
)
@modal.concurrent(
    max_inputs=16,
)
@modal.asgi_app()
def convert():
    """
    FastAPI endpoint for PDF-to-markdown conversion.

    This wraps the vLLM server with the olmOCR pipeline.
    """
    import asyncio
    import os
    import tempfile
    from typing import Optional
    from urllib.parse import urlparse

    from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
    from fastapi.responses import JSONResponse
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    from olmocr.api import (
        APIArgs,
        ServerConfig,
        download_from_url,
        get_filename_from_url,
        process_pdf_file,
    )
    from olmocr.image_utils import convert_image_to_pdf_bytes, is_jpeg, is_png
    from olmocr.version import VERSION

    # Get the vLLM server URL from Modal
    vllm_url = serve_vllm.web_url

    # Get API key for vLLM server
    vllm_api_key = os.environ.get("OLMOCR_API_KEY")

    # Configure the API to use the vLLM server
    config = ServerConfig(
        server=f"{vllm_url}/v1",
        model=MODEL_NAME,
        api_key=vllm_api_key,
        guided_decoding=False,
        target_longest_image_dim=1288,
        max_page_retries=8,
    )

    api = FastAPI(
        title="olmOCR API",
        description="Convert PDF documents to structured text using olmOCR on Modal",
        version=VERSION,
    )

    # Set up auth
    auth_scheme = HTTPBearer()
    EXPECTED_TOKEN = os.environ.get("OLMOCR_API_KEY")

    async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(auth_scheme)):
        if not EXPECTED_TOKEN:
            return  # Auth disabled if no token configured
        if credentials.credentials != EXPECTED_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return credentials

    @api.get("/health")
    async def health():
        """Health check endpoint (public)."""
        return {"status": "ok", "version": VERSION}

    @api.get("/config")
    async def get_config(token: HTTPAuthorizationCredentials = Depends(verify_token)):
        """Get current server configuration (requires auth)."""
        return {
            "server": config.server,
            "model": config.model,
            "guided_decoding": config.guided_decoding,
            "has_api_key": config.api_key is not None,
        }

    @api.post("/convert")
    async def convert_pdf(
        file: Optional[UploadFile] = File(None),
        url: Optional[str] = Query(None, description="URL to download PDF from"),
        token: HTTPAuthorizationCredentials = Depends(verify_token),
    ):
        """
        Convert a PDF file to structured text using olmOCR.

        Provide either:
        - file: Upload a PDF file
        - url: URL to download the PDF from

        Returns a Dolma-format JSON document containing:
        - id: Document hash
        - text: Extracted markdown text
        - metadata: Processing metadata
        - attributes: Per-page attributes
        """
        # Determine input source
        has_file = file is not None and file.filename
        has_url = url is not None
        if not has_file and not has_url:
            raise HTTPException(status_code=400, detail="Must provide either 'file' or 'url'")
        if has_file and has_url:
            raise HTTPException(status_code=400, detail="Provide only one of 'file' or 'url'")

        temp_path = None
        try:
            if has_file:
                source_name = file.filename
                suffix = os.path.splitext(source_name)[1].lower() or ".pdf"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                    content = await file.read()
                    tf.write(content)
                    tf.flush()
                    temp_path = tf.name
            else:
                source_name = get_filename_from_url(url)
                suffix = os.path.splitext(source_name)[1].lower() or ".pdf"
                content = await download_from_url(url)
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
                    tf.write(content)
                    tf.flush()
                    temp_path = tf.name

            # Convert images to PDF if needed
            if is_png(temp_path) or is_jpeg(temp_path):
                pdf_bytes = convert_image_to_pdf_bytes(temp_path)
                with open(temp_path, "wb") as f:
                    f.write(pdf_bytes)

            args = APIArgs(
                server=config.server,
                model=config.model,
                api_key=config.api_key,
                guided_decoding=config.guided_decoding,
                target_longest_image_dim=config.target_longest_image_dim,
                max_page_retries=config.max_page_retries,
            )

            result = await process_pdf_file(temp_path, args)

            if result is None:
                raise HTTPException(status_code=422, detail="Could not extract text from PDF")

            result["metadata"]["Source-File"] = source_name

            return JSONResponse(content=result)

        except Exception as e:
            import traceback

            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    return api
