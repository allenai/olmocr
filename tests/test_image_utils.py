import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from olmocr.image_utils import (
    convert_image_to_pdf_bytes,
    is_jpeg,
    is_png,
    is_supported_image,
    _preprocess_image,
)


class TestImageUtils(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_image(self, mode: str, size: tuple = (100, 100), filename: str = None) -> str:
        """Create a test image with specified mode."""
        if filename is None:
            filename = f"test_{mode.lower()}.png"
        
        filepath = os.path.join(self.temp_dir, filename)
        
        if mode == "RGBA":
            img = Image.new("RGBA", size, (255, 0, 0, 128))  # Semi-transparent red
        elif mode == "LA":
            img = Image.new("LA", size, (128, 128))  # Gray with alpha
        elif mode == "P":
            img = Image.new("P", size, 0)  # Palette mode
        elif mode == "RGB":
            img = Image.new("RGB", size, (255, 0, 0))  # Red
        elif mode == "L":
            img = Image.new("L", size, 128)  # Gray
        else:
            img = Image.new(mode, size)
            
        img.save(filepath, "PNG")
        return filepath

    def test_is_png_valid(self):
        """Test PNG detection with valid PNG file."""
        png_path = self._create_test_image("RGB", filename="test.png")
        self.assertTrue(is_png(png_path))

    def test_is_png_invalid(self):
        """Test PNG detection with non-PNG file."""
        # Create a JPEG file
        jpeg_path = os.path.join(self.temp_dir, "test.jpg")
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        img.save(jpeg_path, "JPEG")
        
        self.assertFalse(is_png(jpeg_path))

    def test_is_jpeg_valid(self):
        """Test JPEG detection with valid JPEG file."""
        jpeg_path = os.path.join(self.temp_dir, "test.jpg")
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        img.save(jpeg_path, "JPEG")
        
        self.assertTrue(is_jpeg(jpeg_path))

    def test_is_jpeg_invalid(self):
        """Test JPEG detection with non-JPEG file."""
        png_path = self._create_test_image("RGB", filename="test.png")
        self.assertFalse(is_jpeg(png_path))

    def test_is_supported_image_valid(self):
        """Test supported image detection with valid image."""
        png_path = self._create_test_image("RGB")
        self.assertTrue(is_supported_image(png_path))

    def test_is_supported_image_invalid(self):
        """Test supported image detection with non-image file."""
        text_path = os.path.join(self.temp_dir, "test.txt")
        with open(text_path, "w") as f:
            f.write("This is not an image")
        
        self.assertFalse(is_supported_image(text_path))

    def test_preprocess_image_rgba(self):
        """Test RGBA image preprocessing."""
        # Create RGBA image
        rgba_img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        
        # Preprocess
        result = _preprocess_image(rgba_img)
        
        # Should be converted to RGB
        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.size, (100, 100))

    def test_preprocess_image_la(self):
        """Test LA (grayscale with alpha) image preprocessing."""
        # Create LA image
        la_img = Image.new("LA", (100, 100), (128, 128))
        
        # Preprocess
        result = _preprocess_image(la_img)
        
        # Should be converted to L (grayscale)
        self.assertEqual(result.mode, "L")
        self.assertEqual(result.size, (100, 100))

    def test_preprocess_image_palette(self):
        """Test palette image preprocessing."""
        # Create palette image
        p_img = Image.new("P", (100, 100), 0)
        
        # Preprocess
        result = _preprocess_image(p_img)
        
        # Should be converted to RGB
        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.size, (100, 100))

    def test_preprocess_image_rgb_unchanged(self):
        """Test that RGB images are not changed."""
        # Create RGB image
        rgb_img = Image.new("RGB", (100, 100), (255, 0, 0))
        
        # Preprocess
        result = _preprocess_image(rgb_img)
        
        # Should remain RGB
        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.size, (100, 100))
        # Should be the same object (no conversion needed)
        self.assertIs(result, rgb_img)

    @patch('olmocr.image_utils.subprocess.run')
    def test_convert_direct_success(self, mock_run):
        """Test direct conversion success."""
        # Mock successful subprocess call
        mock_run.return_value.stdout = b"PDF content"
        
        # Create test image
        img_path = self._create_test_image("RGB")
        
        # Test conversion
        result = convert_image_to_pdf_bytes(img_path)
        
        # Verify result
        self.assertEqual(result, b"PDF content")
        mock_run.assert_called_once()

    @patch('olmocr.image_utils.subprocess.run')
    def test_convert_with_preprocessing_rgba(self, mock_run):
        """Test conversion with RGBA preprocessing."""
        # Mock successful subprocess call
        mock_run.return_value.stdout = b"PDF content"
        
        # Create RGBA test image
        img_path = self._create_test_image("RGBA")
        
        # Test conversion
        result = convert_image_to_pdf_bytes(img_path)
        
        # Verify result
        self.assertEqual(result, b"PDF content")
        mock_run.assert_called_once()
        
        # Verify that img2pdf was called with processed files
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "img2pdf")
        self.assertTrue(args[1].endswith("_processed.png"))

    def test_convert_invalid_input(self):
        """Test conversion with invalid input."""
        # Test empty list
        with self.assertRaises(ValueError):
            convert_image_to_pdf_bytes([])
        
        # Test non-existent file
        with self.assertRaises(ValueError):
            convert_image_to_pdf_bytes("nonexistent.png")

    def test_convert_single_string_input(self):
        """Test conversion with single string input."""
        with patch('olmocr.image_utils.subprocess.run') as mock_run:
            mock_run.return_value.stdout = b"PDF content"
            
            img_path = self._create_test_image("RGB")
            result = convert_image_to_pdf_bytes(img_path)  # Single string, not list
            
            self.assertEqual(result, b"PDF content")

    def test_convert_multiple_images(self):
        """Test conversion with multiple images."""
        with patch('olmocr.image_utils.subprocess.run') as mock_run:
            mock_run.return_value.stdout = b"PDF content"

            img1 = self._create_test_image("RGB", filename="img1.png")
            img2 = self._create_test_image("RGB", filename="img2.png")

            result = convert_image_to_pdf_bytes([img1, img2])

            self.assertEqual(result, b"PDF content")
            # Verify both images were passed to img2pdf
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "img2pdf")
            self.assertEqual(len(args), 3)  # img2pdf + 2 image files

    def test_issue_219_rgba_16bit_fix(self):
        """Test that the fix for issue #219 works - RGBA and 16-bit images."""
        with patch('olmocr.image_utils.subprocess.run') as mock_run:
            mock_run.return_value.stdout = b"PDF content"

            # Create an RGBA image (the problematic case from issue #219)
            rgba_path = self._create_test_image("RGBA")

            # This should not raise an error anymore
            result = convert_image_to_pdf_bytes(rgba_path)

            # Verify it worked
            self.assertEqual(result, b"PDF content")

            # Verify preprocessing was used (img2pdf called with processed file)
            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "img2pdf")
            self.assertTrue(args[1].endswith("_processed.png"))

    @patch('olmocr.image_utils.subprocess.run')
    def test_subprocess_error_handling(self, mock_run):
        """Test proper error handling when subprocess fails."""
        # Mock subprocess failure
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(
            1, ["img2pdf"], stderr=b"Image with transparency and a bit depth of 16"
        )

        img_path = self._create_test_image("RGB")

        with self.assertRaises(RuntimeError) as cm:
            convert_image_to_pdf_bytes(img_path)

        self.assertIn("Error converting image(s) to PDF", str(cm.exception))
        self.assertIn("Image with transparency and a bit depth of 16", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
