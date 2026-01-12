"""
Example client for the Modal-deployed olmOCR API.

Usage:
    # Convert a local PDF (with API key)
    python deployment/modal_client.py --file document.pdf --url https://your-workspace--olmocr-api-convert.modal.run --api-key your-secret-token

    # Convert from URL (with API key from env)
    export OLMOCR_API_KEY=your-secret-token
    python deployment/modal_client.py --pdf-url https://example.com/doc.pdf --url https://your-workspace--olmocr-api-convert.modal.run
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx


async def convert_local_file(api_url: str, pdf_path: str, output_path: str = None, api_key: str = None):
    """Convert a local PDF file."""
    print(f"Converting local file: {pdf_path}")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=300) as client:
        with open(pdf_path, "rb") as f:
            files = {"file": (Path(pdf_path).name, f, "application/pdf")}
            resp = await client.post(f"{api_url}/convert", files=files, headers=headers)

        resp.raise_for_status()
        result = resp.json()

    if output_path:
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"✅ Saved to: {output_path}")
    else:
        print("✅ Result:")
        print(json.dumps(result, indent=2))

    return result


async def convert_from_url(api_url: str, pdf_url: str, output_path: str = None, api_key: str = None):
    """Convert a PDF from URL."""
    print(f"Converting from URL: {pdf_url}")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(f"{api_url}/convert", params={"url": pdf_url}, headers=headers)

        resp.raise_for_status()
        result = resp.json()

    if output_path:
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"✅ Saved to: {output_path}")
    else:
        print("✅ Result:")
        print(json.dumps(result, indent=2))

    return result


async def check_health(api_url: str):
    """Check API health."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{api_url}/health")
        resp.raise_for_status()
        return resp.json()


async def get_config(api_url: str, api_key: str = None):
    """Get API configuration."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{api_url}/config", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def main():
    parser = argparse.ArgumentParser(description="Client for Modal-deployed olmOCR API")
    parser.add_argument("--url", required=True, help="Modal API URL")
    parser.add_argument("--file", help="Local PDF file to convert")
    parser.add_argument("--pdf-url", help="URL of PDF to convert")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--api-key", help="API key (or set OLMOCR_API_KEY env var)")
    parser.add_argument("--health", action="store_true", help="Check API health")
    parser.add_argument("--config", action="store_true", help="Get API configuration")

    args = parser.parse_args()

    # Normalize API URL
    api_url = args.url.rstrip("/")

    # Get API key from args or environment
    api_key = args.api_key or os.environ.get("OLMOCR_API_KEY")

    if args.health:
        print("Checking health...")
        health = await check_health(api_url)
        print(json.dumps(health, indent=2))
        return

    if args.config:
        print("Getting configuration...")
        config = await get_config(api_url, api_key)
        print(json.dumps(config, indent=2))
        return

    if args.file:
        await convert_local_file(api_url, args.file, args.output, api_key)
    elif args.pdf_url:
        await convert_from_url(api_url, args.pdf_url, args.output, api_key)
    else:
        parser.error("Must provide either --file or --pdf-url")


if __name__ == "__main__":
    asyncio.run(main())
