import base64
import json
import os
from dataclasses import dataclass
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from olmocr.pipeline import PageResult, build_page_query, derive_markdown_relative_path, process_page


def create_test_image(width=100, height=150):
    """Create a simple test image with distinct features to verify rotation."""
    img = Image.new("RGB", (width, height), color="white")
    pixels = img.load()

    # Draw a red square in top-left corner
    for x in range(10, 30):
        for y in range(10, 30):
            if pixels is not None:
                pixels[x, y] = (255, 0, 0)

    # Draw a blue rectangle in bottom-right corner
    for x in range(width - 40, width - 10):
        for y in range(height - 30, height - 10):
            if pixels is not None:
                pixels[x, y] = (0, 0, 255)

    # Draw a green line near the top
    for x in range(20, 80):
        if pixels is not None:
            pixels[x, 5] = (0, 255, 0)

    return img


def image_to_base64(img):
    """Convert PIL Image to base64 string."""
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


def base64_to_image(base64_str):
    """Convert base64 string to PIL Image."""
    image_bytes = base64.b64decode(base64_str)
    return Image.open(BytesIO(image_bytes))


class TestImageRotation:
    @pytest.mark.asyncio
    async def test_no_rotation(self):
        """Test that image_rotation=0 returns the original image."""
        test_img = create_test_image()
        test_base64 = image_to_base64(test_img)

        with patch("olmocr.pipeline.render_pdf_to_base64png") as mock_render:
            mock_render.return_value = test_base64

            result = await build_page_query("fake_pdf.pdf", 1, 1000, image_rotation=0)

            # Extract the image from the result
            messages = result["messages"]
            content = messages[0]["content"]
            image_url = content[1]["image_url"]["url"]
            image_base64 = image_url.split(",")[1]
            result_img = base64_to_image(image_base64)

            # Should be the same size as original
            assert result_img.size == test_img.size

            # Check pixel at specific location (red square should be in top-left)
            assert result_img.getpixel((20, 20)) == (255, 0, 0)

    @pytest.mark.asyncio
    async def test_rotate_90_degrees(self):
        """Test that image_rotation=90 rotates the image 90 degrees counter-clockwise."""
        test_img = create_test_image(100, 150)
        test_base64 = image_to_base64(test_img)

        with patch("olmocr.pipeline.render_pdf_to_base64png") as mock_render:
            mock_render.return_value = test_base64

            result = await build_page_query("fake_pdf.pdf", 1, 1000, image_rotation=90)

            # Extract the image from the result
            messages = result["messages"]
            content = messages[0]["content"]
            image_url = content[1]["image_url"]["url"]
            image_base64 = image_url.split(",")[1]
            result_img = base64_to_image(image_base64)

            # After 90 degree counter-clockwise rotation, dimensions should be swapped
            assert result_img.size == (150, 100)

            # The red square that was at top-left should now be at bottom-left
            # Original (20, 20) -> After 90° CCW rotation -> (20, 80)
            assert result_img.getpixel((20, 80)) == (255, 0, 0)

    @pytest.mark.asyncio
    async def test_rotate_180_degrees(self):
        """Test that image_rotation=180 rotates the image 180 degrees."""
        test_img = create_test_image(100, 150)
        test_base64 = image_to_base64(test_img)

        with patch("olmocr.pipeline.render_pdf_to_base64png") as mock_render:
            mock_render.return_value = test_base64

            result = await build_page_query("fake_pdf.pdf", 1, 1000, image_rotation=180)

            # Extract the image from the result
            messages = result["messages"]
            content = messages[0]["content"]
            image_url = content[1]["image_url"]["url"]
            image_base64 = image_url.split(",")[1]
            result_img = base64_to_image(image_base64)

            # After 180 degree rotation, dimensions should be the same
            assert result_img.size == (100, 150)

            # The red square that was at top-left should now be at bottom-right
            # Original (20, 20) -> After 180° rotation -> (80, 130)
            assert result_img.getpixel((80, 130)) == (255, 0, 0)

    @pytest.mark.asyncio
    async def test_rotate_270_degrees(self):
        """Test that image_rotation=270 rotates the image 270 degrees counter-clockwise (90 clockwise)."""
        test_img = create_test_image(100, 150)
        test_base64 = image_to_base64(test_img)

        with patch("olmocr.pipeline.render_pdf_to_base64png") as mock_render:
            mock_render.return_value = test_base64

            result = await build_page_query("fake_pdf.pdf", 1, 1000, image_rotation=270)

            # Extract the image from the result
            messages = result["messages"]
            content = messages[0]["content"]
            image_url = content[1]["image_url"]["url"]
            image_base64 = image_url.split(",")[1]
            result_img = base64_to_image(image_base64)

            # After 270 degree counter-clockwise rotation, dimensions should be swapped
            assert result_img.size == (150, 100)

            # The red square that was at top-left should now be at top-right
            # Original (20, 20) -> After 270° CCW rotation -> (130, 20)
            assert result_img.getpixel((130, 20)) == (255, 0, 0)

    @pytest.mark.asyncio
    async def test_invalid_rotation_angle(self):
        """Test that invalid rotation angles raise an assertion error."""
        test_img = create_test_image()
        test_base64 = image_to_base64(test_img)

        with patch("olmocr.pipeline.render_pdf_to_base64png") as mock_render:
            mock_render.return_value = test_base64

            with pytest.raises(AssertionError, match="Invalid image rotation"):
                await build_page_query("fake_pdf.pdf", 1, 1000, image_rotation=45)

    @pytest.mark.asyncio
    async def test_rotation_preserves_image_quality(self):
        """Test that rotation preserves the image without distortion."""
        # Create a more complex test image
        test_img = create_test_image(200, 300)
        test_base64 = image_to_base64(test_img)

        with patch("olmocr.pipeline.render_pdf_to_base64png") as mock_render:
            mock_render.return_value = test_base64

            # Test all valid rotation angles
            for angle in [0, 90, 180, 270]:
                result = await build_page_query("fake_pdf.pdf", 1, 1000, image_rotation=angle)

                # Extract the image from the result
                messages = result["messages"]
                content = messages[0]["content"]
                image_url = content[1]["image_url"]["url"]
                image_base64 = image_url.split(",")[1]
                result_img = base64_to_image(image_base64)

                # Verify image format is preserved
                assert result_img.format == "PNG" or result_img.format is None
                assert result_img.mode == "RGB"


@dataclass
class MockArgs:
    max_page_retries: int = 8
    target_longest_image_dim: int = 1288
    guided_decoding: bool = False
    server: str = "http://localhost:30000/v1"
    model: str = "olmocr"


class TestRotationCorrection:
    @pytest.mark.asyncio
    async def test_process_page_with_rotation_correction(self):
        """Test that process_page correctly handles rotation correction from model response."""

        # Path to the test PDF that needs 90 degree rotation
        test_pdf_path = "tests/gnarly_pdfs/edgar-rotated90.pdf"

        # Mock arguments
        args = MockArgs()

        # Counter to track number of API calls
        call_count = 0

        async def mock_apost(url, json_data, api_key=None):
            nonlocal call_count
            call_count += 1

            # Check the rotation in the request
            messages = json_data.get("messages", [])
            if messages:
                content = messages[0].get("content", [])
                image_data = content[0].get("image_url", {}).get("url", "")

                # First call - model detects rotation is needed
                if call_count == 1:
                    response_content = """---
primary_language: en
is_rotation_valid: false
rotation_correction: 90
is_table: false
is_diagram: false
---

This document appears to be rotated and needs correction."""

                # Second call - after rotation, model says it's correct
                elif call_count == 2:
                    response_content = """---
primary_language: en
is_rotation_valid: true
rotation_correction: 0
is_table: false
is_diagram: false
---

UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549

This is the corrected text from the document."""

                else:
                    raise ValueError(f"Unexpected call count: {call_count}")

            # Mock response structure
            response_body = {
                "choices": [{"message": {"content": response_content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
            }

            return 200, json.dumps(response_body).encode()

        # Mock the worker tracker
        mock_tracker = AsyncMock()

        # Ensure the test PDF exists
        assert os.path.exists(test_pdf_path), f"Test PDF not found at {test_pdf_path}"

        # Track calls to build_page_query
        build_page_query_calls = []
        original_build_page_query = build_page_query

        async def mock_build_page_query(local_pdf_path, page, target_longest_image_dim, image_rotation=0, model_name="olmocr"):
            build_page_query_calls.append(image_rotation)
            return await original_build_page_query(local_pdf_path, page, target_longest_image_dim, image_rotation, model_name)

        with patch("olmocr.pipeline.apost", side_effect=mock_apost):
            with patch("olmocr.pipeline.tracker", mock_tracker):
                with patch("olmocr.pipeline.build_page_query", side_effect=mock_build_page_query):
                    result = await process_page(args=args, worker_id=0, pdf_orig_path="test-edgar-rotated90.pdf", pdf_local_path=test_pdf_path, page_num=1)

        # Verify the result
        assert isinstance(result, PageResult)
        assert result.page_num == 1
        assert result.is_fallback == False
        assert result.response.is_rotation_valid == True
        assert result.response.rotation_correction == 0
        assert result.response.natural_text is not None
        assert "SECURITIES AND EXCHANGE COMMISSION" in result.response.natural_text

        # Verify that exactly 2 API calls were made
        assert call_count == 2

        # Verify build_page_query was called with correct rotations
        assert len(build_page_query_calls) == 2
        assert build_page_query_calls[0] == 0  # First call with no rotation
        assert build_page_query_calls[1] == 90  # Second call with 90 degree rotation

        # Verify tracker was called correctly
        mock_tracker.track_work.assert_any_call(0, "test-edgar-rotated90.pdf-1", "started")
        mock_tracker.track_work.assert_any_call(0, "test-edgar-rotated90.pdf-1", "finished")

    @pytest.mark.asyncio
    async def test_process_page_with_cumulative_rotation(self):
        """Test that process_page correctly accumulates rotations across multiple attempts."""

        # Path to the test PDF (can use any test PDF)
        test_pdf_path = "tests/gnarly_pdfs/edgar-rotated90.pdf"

        # Mock arguments
        args = MockArgs()

        # Counter to track number of API calls
        call_count = 0

        async def mock_apost(url, json_data, api_key=None):
            nonlocal call_count
            call_count += 1

            # First call - model detects rotation is needed (90 degrees)
            if call_count == 1:
                response_content = """---
primary_language: en
is_rotation_valid: false
rotation_correction: 90
is_table: false
is_diagram: false
---

This document appears to be rotated and needs correction."""

            # Second call - model still detects rotation is needed (another 90 degrees)
            elif call_count == 2:
                response_content = """---
primary_language: en
is_rotation_valid: false
rotation_correction: 90
is_table: false
is_diagram: false
---

Document still needs rotation."""

            # Third call - after 180 total degrees of rotation, model says it's correct
            elif call_count == 3:
                response_content = """---
primary_language: en
is_rotation_valid: true
rotation_correction: 0
is_table: false
is_diagram: false
---

UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549

Document is now correctly oriented after 180 degree rotation."""

            else:
                raise ValueError(f"Unexpected call count: {call_count}")

            # Mock response structure
            response_body = {
                "choices": [{"message": {"content": response_content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
            }

            return 200, json.dumps(response_body).encode()

        # Mock the worker tracker
        mock_tracker = AsyncMock()

        # Ensure the test PDF exists
        assert os.path.exists(test_pdf_path), f"Test PDF not found at {test_pdf_path}"

        # Track calls to build_page_query
        build_page_query_calls = []
        original_build_page_query = build_page_query

        async def mock_build_page_query(local_pdf_path, page, target_longest_image_dim, image_rotation=0, model_name="olmocr"):
            build_page_query_calls.append(image_rotation)
            return await original_build_page_query(local_pdf_path, page, target_longest_image_dim, image_rotation, model_name)

        with patch("olmocr.pipeline.apost", side_effect=mock_apost):
            with patch("olmocr.pipeline.tracker", mock_tracker):
                with patch("olmocr.pipeline.build_page_query", side_effect=mock_build_page_query):
                    result = await process_page(args=args, worker_id=0, pdf_orig_path="test-cumulative-rotation.pdf", pdf_local_path=test_pdf_path, page_num=1)

        # Verify the result
        assert isinstance(result, PageResult)
        assert result.page_num == 1
        assert result.is_fallback == False
        assert result.response.is_rotation_valid == True
        assert result.response.rotation_correction == 0
        assert result.response.natural_text is not None
        assert "180 degree rotation" in result.response.natural_text

        # Verify that exactly 3 API calls were made
        assert call_count == 3

        # Verify build_page_query was called with correct cumulative rotations
        assert len(build_page_query_calls) == 3
        assert build_page_query_calls[0] == 0  # First call with no rotation
        assert build_page_query_calls[1] == 90  # Second call with 90 degree rotation
        assert build_page_query_calls[2] == 180  # Third call with cumulative 180 degree rotation

        # Verify tracker was called correctly
        mock_tracker.track_work.assert_any_call(0, "test-cumulative-rotation.pdf-1", "started")
        mock_tracker.track_work.assert_any_call(0, "test-cumulative-rotation.pdf-1", "finished")

    @pytest.mark.asyncio
    async def test_process_page_rotation_wraps_around(self):
        """Test that cumulative rotation correctly wraps around at 360 degrees."""

        # Path to the test PDF
        test_pdf_path = "tests/gnarly_pdfs/edgar-rotated90.pdf"

        # Mock arguments
        args = MockArgs()

        # Counter to track number of API calls
        call_count = 0

        async def mock_apost(url, json_data, api_key=None):
            nonlocal call_count
            call_count += 1

            # First call - model detects rotation is needed (270 degrees)
            if call_count == 1:
                response_content = """---
primary_language: en
is_rotation_valid: false
rotation_correction: 270
is_table: false
is_diagram: false
---

Document needs 270 degree rotation."""

            # Second call - model detects more rotation is needed (180 degrees)
            # Total would be 450, but should wrap to 90
            elif call_count == 2:
                response_content = """---
primary_language: en
is_rotation_valid: false
rotation_correction: 180
is_table: false
is_diagram: false
---

Document needs additional rotation."""

            # Third call - after wrapped rotation (90 degrees), model says it's correct
            elif call_count == 3:
                response_content = """---
primary_language: en
is_rotation_valid: true
rotation_correction: 0
is_table: false
is_diagram: false
---

Document correctly oriented at 90 degrees total rotation."""

            else:
                raise ValueError(f"Unexpected call count: {call_count}")

            # Mock response structure
            response_body = {
                "choices": [{"message": {"content": response_content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
            }

            return 200, json.dumps(response_body).encode()

        # Mock the worker tracker
        mock_tracker = AsyncMock()

        # Ensure the test PDF exists
        assert os.path.exists(test_pdf_path), f"Test PDF not found at {test_pdf_path}"

        # Track calls to build_page_query
        build_page_query_calls = []
        original_build_page_query = build_page_query

        async def mock_build_page_query(local_pdf_path, page, target_longest_image_dim, image_rotation=0, model_name="olmocr"):
            build_page_query_calls.append(image_rotation)
            return await original_build_page_query(local_pdf_path, page, target_longest_image_dim, image_rotation, model_name)

        with patch("olmocr.pipeline.apost", side_effect=mock_apost):
            with patch("olmocr.pipeline.tracker", mock_tracker):
                with patch("olmocr.pipeline.build_page_query", side_effect=mock_build_page_query):
                    result = await process_page(args=args, worker_id=0, pdf_orig_path="test-rotation-wrap.pdf", pdf_local_path=test_pdf_path, page_num=1)

        # Verify the result
        assert isinstance(result, PageResult)
        assert result.page_num == 1
        assert result.is_fallback == False
        assert result.response.is_rotation_valid == True

        # Verify that exactly 3 API calls were made
        assert call_count == 3

        # Verify build_page_query was called with correct cumulative rotations
        assert len(build_page_query_calls) == 3
        assert build_page_query_calls[0] == 0  # First call with no rotation
        assert build_page_query_calls[1] == 270  # Second call with 270 degree rotation
        assert build_page_query_calls[2] == 90  # Third call with wrapped rotation (270 + 180 = 450 % 360 = 90)


class TestMarkdownPathDerivation:
    def test_relative_path_preserved(self):
        result = derive_markdown_relative_path("tests/gnarly_pdfs/sample.pdf")
        assert result == os.path.join("tests", "gnarly_pdfs", "sample.pdf")

    def test_absolute_path_prefixed(self, tmp_path):
        absolute_pdf = tmp_path / "docs" / "example.pdf"
        absolute_pdf.parent.mkdir(parents=True, exist_ok=True)
        absolute_pdf.touch()

        result = derive_markdown_relative_path(str(absolute_pdf))
        assert result.startswith(os.path.join("absolute", "tmp"))
        assert result.endswith(os.path.join("docs", "example.pdf"))

    def test_windows_style_path(self):
        path = r"C:\data\reports\demo.pdf"
        result = derive_markdown_relative_path(path)
        assert result.startswith(os.path.join("absolute", "C"))
        assert result.endswith(os.path.join("data", "reports", "demo.pdf"))

    def test_parent_segments_removed(self):
        result = derive_markdown_relative_path("../outside/../doc.pdf")
        assert result == "doc.pdf"

    def test_s3_path_sanitised(self):
        result = derive_markdown_relative_path("s3://bucket/documents/input.pdf")
        assert result == os.path.join("documents", "input.pdf")
