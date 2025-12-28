"""
FastAPI service for olmOCR PDF processing.

Usage:
    python -m olmocr.api --server http://localhost:12345/v1 --model allenai/olmOCR-2-7B-1025-FP8

Then POST to /convert with either:
  - file: uploaded PDF file
  - url: URL to download PDF from
"""

import argparse
import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pypdf import PdfReader

from olmocr.image_utils import convert_image_to_pdf_bytes, is_jpeg, is_png
from olmocr.pipeline import PageResult, apost, build_dolma_document, build_page_query
from olmocr.prompts import PageResponse
from olmocr.train.dataloader import FrontMatterParser
from olmocr.version import VERSION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Server-wide configuration set at startup."""

    server: Optional[str] = None
    model: str = "allenai/olmOCR-2-7B-1025-FP8"
    api_key: Optional[str] = None
    guided_decoding: bool = False
    target_longest_image_dim: int = 1288
    max_page_retries: int = 8


# Global config - set when server starts
config = ServerConfig()

app = FastAPI(
    title="olmOCR API",
    description="Convert PDF documents to structured text using olmOCR",
    version=VERSION,
)


@dataclass
class APIArgs:
    """Args object for processing requests."""

    server: str
    model: str
    target_longest_image_dim: int = 1288
    max_page_retries: int = 8
    guided_decoding: bool = False
    api_key: Optional[str] = None


async def process_page_simple(
    args: APIArgs,
    pdf_local_path: str,
    page_num: int,
) -> PageResult:
    """Simplified page processing for API use."""
    COMPLETION_URL = f"{args.server.rstrip('/')}/chat/completions"
    MAX_RETRIES = args.max_page_retries
    MODEL_MAX_CONTEXT = 16384
    TEMPERATURE_BY_ATTEMPT = [0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 0.9, 1.0]

    attempt = 0
    cumulative_rotation = 0

    while attempt < MAX_RETRIES:
        lookup_attempt = min(attempt, len(TEMPERATURE_BY_ATTEMPT) - 1)

        query = await build_page_query(
            pdf_local_path,
            page_num,
            args.target_longest_image_dim,
            image_rotation=cumulative_rotation,
            model_name=args.model,
        )
        query["temperature"] = TEMPERATURE_BY_ATTEMPT[lookup_attempt]

        if args.guided_decoding:
            query["guided_regex"] = (
                r"---\nprimary_language: (?:[a-z]{2}|null)\nis_rotation_valid: (?:True|False|true|false)\nrotation_correction: (?:0|90|180|270)\nis_table: (?:True|False|true|false)\nis_diagram: (?:True|False|true|false)\n(?:---|---\n[\s\S]+)"
            )

        try:
            status_code, response_body = await apost(COMPLETION_URL, json_data=query, api_key=args.api_key)

            if status_code == 400:
                raise ValueError(f"BadRequestError: {response_body}")
            elif status_code == 429:
                await asyncio.sleep(10 * (2**attempt))
                attempt += 1
                continue
            elif status_code == 500:
                raise ValueError(f"InternalServerError: {response_body}")
            elif status_code != 200:
                raise ValueError(f"HTTP error {status_code}")

            import json

            base_response_data = json.loads(response_body)

            if base_response_data["usage"]["total_tokens"] > MODEL_MAX_CONTEXT:
                raise ValueError(f"Response exceeded max context of {MODEL_MAX_CONTEXT}")

            finish_reason = base_response_data["choices"][0]["finish_reason"]
            if finish_reason != "stop":
                raise ValueError(f"Finish reason was '{finish_reason}' instead of 'stop'")

            model_response = base_response_data["choices"][0]["message"]["content"]

            parser = FrontMatterParser(front_matter_class=PageResponse)
            front_matter, text = parser._extract_front_matter_and_text(model_response)
            page_response = parser._parse_front_matter(front_matter, text)

            if not page_response.is_rotation_valid and attempt < MAX_RETRIES - 1:
                cumulative_rotation = (cumulative_rotation + page_response.rotation_correction) % 360
                attempt += 1
                continue

            return PageResult(
                pdf_local_path,
                page_num,
                page_response,
                input_tokens=base_response_data["usage"].get("prompt_tokens", 0),
                output_tokens=base_response_data["usage"].get("completion_tokens", 0),
                is_fallback=False,
            )

        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            logger.warning(f"Connection error on attempt {attempt}: {e}")
            await asyncio.sleep(10 * (2**attempt))
            attempt += 1
        except ValueError as e:
            logger.warning(f"ValueError on attempt {attempt}: {e}")
            attempt += 1

    # Fallback - return empty response
    logger.error(f"Failed to process page {page_num} after {MAX_RETRIES} attempts")
    from olmocr.prompts.anchor import get_anchor_text

    return PageResult(
        pdf_local_path,
        page_num,
        PageResponse(
            natural_text=get_anchor_text(pdf_local_path, page_num, pdf_engine="pdftotext"),
            primary_language=None,
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        ),
        input_tokens=0,
        output_tokens=0,
        is_fallback=True,
    )


async def process_pdf_file(pdf_path: str, args: APIArgs) -> Optional[dict]:
    """Process a PDF file and return a Dolma document."""
    reader = PdfReader(pdf_path)
    num_pages = reader.get_num_pages()

    if num_pages == 0:
        return None

    tasks = [process_page_simple(args, pdf_path, page_num) for page_num in range(1, num_pages + 1)]
    page_results = await asyncio.gather(*tasks)

    return build_dolma_document(pdf_path, page_results)


async def download_from_url(url: str) -> bytes:
    """Download file content from URL."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def get_filename_from_url(url: str) -> str:
    """Extract filename from URL."""
    parsed = urlparse(url)
    name = os.path.basename(parsed.path)
    return name if name else "document.pdf"


@app.get("/config")
async def get_config():
    """Get current server configuration."""
    return {
        "server": config.server,
        "model": config.model,
        "guided_decoding": config.guided_decoding,
        "has_api_key": config.api_key is not None,
    }


@app.post("/convert")
async def convert_pdf(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Query(None, description="URL to download PDF from"),
    server: Optional[str] = Query(None, description="VLLM server URL (overrides server config)"),
    model: Optional[str] = Query(None, description="Model name (overrides server config)"),
    api_key: Optional[str] = Query(None, description="API key (overrides server config)"),
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
    effective_server = server or config.server
    effective_model = model or config.model
    effective_api_key = api_key or config.api_key

    if not effective_server:
        raise HTTPException(status_code=400, detail="No server configured. Either pass 'server' parameter or start the API with --server")

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

        if is_png(temp_path) or is_jpeg(temp_path):
            pdf_bytes = convert_image_to_pdf_bytes(temp_path)
            with open(temp_path, "wb") as f:
                f.write(pdf_bytes)

        args = APIArgs(
            server=effective_server,
            model=effective_model,
            api_key=effective_api_key,
            guided_decoding=config.guided_decoding,
            target_longest_image_dim=config.target_longest_image_dim,
            max_page_retries=config.max_page_retries,
        )

        result = await process_pdf_file(temp_path, args)

        if result is None:
            raise HTTPException(status_code=422, detail="Could not extract text from PDF")

        result["metadata"]["Source-File"] = source_name

        return JSONResponse(content=result)

    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download from URL: {e}")

    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": VERSION}


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="olmOCR API Server")
    parser.add_argument("--server", type=str, help="VLLM server URL, e.g. http://localhost:12345/v1")
    parser.add_argument("--model", type=str, default="allenai/olmOCR-2-7B-1025-FP8", help="Model name")
    parser.add_argument("--api_key", type=str, help="API key for authenticated servers")
    parser.add_argument("--guided_decoding", action="store_true", help="Enable guided decoding")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")

    args = parser.parse_args()

    # Set global config from CLI args
    config.server = args.server
    config.model = args.model
    config.api_key = args.api_key
    config.guided_decoding = args.guided_decoding

    logger.info(f"Starting olmOCR API server on {args.host}:{args.port}")
    if config.server:
        logger.info(f"Configured VLLM server: {config.server}")
        logger.info(f"Configured model: {config.model}")
    else:
        logger.info("No VLLM server configured - clients must pass 'server' parameter")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
