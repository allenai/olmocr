# olmOCR Modal Deployment

Deploy the full olmOCR service (vLLM + FastAPI) on Modal.

## Setup

1. Install Modal:
```bash
pip install modal
```

2. Authenticate with Modal:
```bash
modal setup
```

3. Create API Key Secret:

Visit https://modal.com/secrets and create a new secret named `olmocr-api-key` with:
```json
{
  "OLMOCR_API_KEY": "your-secret-token"
}
```

This key protects both the vLLM server and the FastAPI endpoints.

## Deploy

Deploy the service to Modal:
```bash
modal deploy deployment/modal_app.py
```

This will:
- Build container images with all dependencies
- Download and cache the olmOCR-2-7B model
- Deploy two endpoints:
  - vLLM server (internal, protected with API key)
  - FastAPI wrapper with `/convert` endpoint (public, protected with Bearer token)

After deployment, you'll see URLs like:
```
✓ Created web function convert => https://your-workspace--olmocr-api-convert.modal.run
```

See docs at: `https://your-workspace--olmocr-api-convert.modal.run/docs`

## Usage

The easiest way to use the API is with the included Python client:

```bash
# Install httpx if needed
pip install httpx

# Convert a local PDF
python deployment/modal_client.py \
    --url https://your-workspace--olmocr-api-convert.modal.run \
    --file document.pdf \
    --api-key your-secret-token \
    --output result.json

# Convert from URL (using env var for API key)
export OLMOCR_API_KEY=your-secret-token
python deployment/modal_client.py \
    --url https://your-workspace--olmocr-api-convert.modal.run \
    --pdf-url https://example.com/document.pdf \
    --output result.json

# Check health (no auth required)
python deployment/modal_client.py \
    --url https://your-workspace--olmocr-api-convert.modal.run \
    --health

# Get configuration (requires auth)
python deployment/modal_client.py \
    --url https://your-workspace--olmocr-api-convert.modal.run \
    --config \
    --api-key your-secret-token
```

## Response Format

The API returns a Dolma-format JSON document:

```json
{
    "id": "sha1_hash_of_content",
    "text": "# Extracted markdown content...",
    "source": "olmocr",
    "added": "2025-12-27",
    "created": "2025-12-27",
    "metadata": {
        "Source-File": "document.pdf",
        "olmocr-version": "0.4.0",
        "pdf-total-pages": 10,
        "total-input-tokens": 50000,
        "total-output-tokens": 8000,
        "total-fallback-pages": 0
    },
    "attributes": {
        "pdf_page_numbers": [[0, 500, 1], [500, 1200, 2]],
        "primary_language": ["en", "en"],
        "is_rotation_valid": [true, true],
        "rotation_correction": [0, 0],
        "is_table": [false, false],
        "is_diagram": [false, true]
    }
}
```

