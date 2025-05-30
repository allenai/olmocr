#!/usr/bin/env python3
"""
Integration test for the image processing fix (Issue #219).

This test creates actual problematic images and verifies they can be processed
without errors.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from olmocr.image_utils import convert_image_to_pdf_bytes


class TestImageFixIntegration(unittest.TestCase):
    """Integration tests for the image processing fix."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_problematic_image(self, image_type: str) -> str:
        """Create images that would fail with the old implementation."""
        if image_type == "rgba":
            # RGBA image with transparency
            img = Image.new("RGBA", (200, 300), (255, 0, 0, 128))
            # Add some content
            for x in range(0, 200, 20):
                for y in range(0, 300, 20):
                    img.putpixel((x, y), (0, 255, 0, 255))
            filename = "rgba_test.png"
            
        elif image_type == "la":
            # Grayscale with alpha
            img = Image.new("LA", (150, 200), (128, 200))
            filename = "la_test.png"
            
        elif image_type == "palette":
            # Palette mode image
            img = Image.new("P", (100, 150))
            # Create a simple palette
            palette = []
            for i in range(256):
                palette.extend([i, i, i])  # Grayscale palette
            img.putpalette(palette)
            filename = "palette_test.png"
            
        else:
            raise ValueError(f"Unknown image type: {image_type}")
        
        filepath = os.path.join(self.temp_dir, filename)
        img.save(filepath, "PNG")
        return filepath

    @patch('olmocr.image_utils.subprocess.run')
    def test_rgba_image_processing(self, mock_run):
        """Test that RGBA images are processed correctly."""
        # Store processed file info for verification
        processed_files = []

        def capture_subprocess_call(*args, **kwargs):
            # Capture the processed file before it gets cleaned up
            cmd_args = args[0]
            if len(cmd_args) > 1 and cmd_args[1].endswith("_processed.png"):
                processed_file = cmd_args[1]
                if os.path.exists(processed_file):
                    with Image.open(processed_file) as img:
                        processed_files.append({
                            'path': processed_file,
                            'mode': img.mode,
                            'size': img.size
                        })

            # Return mock result
            mock_result = type('MockResult', (), {})()
            mock_result.stdout = b"%PDF-1.4\nfake pdf content"
            return mock_result

        mock_run.side_effect = capture_subprocess_call

        # Create RGBA image that would fail with old implementation
        rgba_path = self._create_problematic_image("rgba")

        # This should work without errors
        result = convert_image_to_pdf_bytes(rgba_path)

        # Verify we got PDF content
        self.assertEqual(result, b"%PDF-1.4\nfake pdf content")

        # Verify img2pdf was called
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "img2pdf")

        # Verify the processed file was used (not the original RGBA)
        processed_file = args[1]
        self.assertTrue(processed_file.endswith("_processed.png"))

        # Verify the processed file was RGB (not RGBA)
        self.assertEqual(len(processed_files), 1)
        self.assertEqual(processed_files[0]['mode'], "RGB")
        self.assertEqual(processed_files[0]['size'], (200, 300))

    @patch('olmocr.image_utils.subprocess.run')
    def test_la_image_processing(self, mock_run):
        """Test that LA (grayscale with alpha) images are processed correctly."""
        processed_files = []

        def capture_subprocess_call(*args, **kwargs):
            cmd_args = args[0]
            if len(cmd_args) > 1 and cmd_args[1].endswith("_processed.png"):
                processed_file = cmd_args[1]
                if os.path.exists(processed_file):
                    with Image.open(processed_file) as img:
                        processed_files.append({'mode': img.mode, 'size': img.size})

            mock_result = type('MockResult', (), {})()
            mock_result.stdout = b"%PDF-1.4\nfake pdf content"
            return mock_result

        mock_run.side_effect = capture_subprocess_call

        la_path = self._create_problematic_image("la")

        result = convert_image_to_pdf_bytes(la_path)

        self.assertEqual(result, b"%PDF-1.4\nfake pdf content")
        mock_run.assert_called_once()

        # Verify processed file is grayscale (not LA)
        self.assertEqual(len(processed_files), 1)
        self.assertEqual(processed_files[0]['mode'], "L")

    @patch('olmocr.image_utils.subprocess.run')
    def test_palette_image_processing(self, mock_run):
        """Test that palette images are processed correctly."""
        processed_files = []

        def capture_subprocess_call(*args, **kwargs):
            cmd_args = args[0]
            if len(cmd_args) > 1 and cmd_args[1].endswith("_processed.png"):
                processed_file = cmd_args[1]
                if os.path.exists(processed_file):
                    with Image.open(processed_file) as img:
                        processed_files.append({'mode': img.mode, 'size': img.size})

            mock_result = type('MockResult', (), {})()
            mock_result.stdout = b"%PDF-1.4\nfake pdf content"
            return mock_result

        mock_run.side_effect = capture_subprocess_call

        palette_path = self._create_problematic_image("palette")

        result = convert_image_to_pdf_bytes(palette_path)

        self.assertEqual(result, b"%PDF-1.4\nfake pdf content")
        mock_run.assert_called_once()

        # Verify processed file is RGB (not palette)
        self.assertEqual(len(processed_files), 1)
        self.assertEqual(processed_files[0]['mode'], "RGB")

    @patch('olmocr.image_utils.subprocess.run')
    def test_mixed_image_types(self, mock_run):
        """Test processing multiple images with different problematic formats."""
        processed_files = []

        def capture_subprocess_call(*args, **kwargs):
            cmd_args = args[0]
            for i in range(1, len(cmd_args)):
                if cmd_args[i].endswith("_processed.png"):
                    processed_file = cmd_args[i]
                    if os.path.exists(processed_file):
                        with Image.open(processed_file) as img:
                            processed_files.append({'mode': img.mode, 'size': img.size})

            mock_result = type('MockResult', (), {})()
            mock_result.stdout = b"%PDF-1.4\nfake pdf content"
            return mock_result

        mock_run.side_effect = capture_subprocess_call

        # Create multiple problematic images
        rgba_path = self._create_problematic_image("rgba")
        la_path = self._create_problematic_image("la")
        palette_path = self._create_problematic_image("palette")

        # Process all together
        result = convert_image_to_pdf_bytes([rgba_path, la_path, palette_path])

        self.assertEqual(result, b"%PDF-1.4\nfake pdf content")
        mock_run.assert_called_once()

        # Verify all files were processed
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "img2pdf")
        self.assertEqual(len(args), 4)  # img2pdf + 3 processed files

        # Verify all processed files have correct modes
        self.assertEqual(len(processed_files), 3)
        modes = [f['mode'] for f in processed_files]
        for mode in modes:
            self.assertIn(mode, ["RGB", "L"])  # Should be RGB or L, not RGBA/LA/P

    @patch('olmocr.image_utils.subprocess.run')
    def test_normal_rgb_image_unchanged(self, mock_run):
        """Test that normal RGB images still work and use direct conversion."""
        mock_run.return_value.stdout = b"%PDF-1.4\nfake pdf content"
        
        # Create normal RGB image
        rgb_path = os.path.join(self.temp_dir, "normal_rgb.png")
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        img.save(rgb_path, "PNG")
        
        result = convert_image_to_pdf_bytes(rgb_path)
        
        self.assertEqual(result, b"%PDF-1.4\nfake pdf content")
        mock_run.assert_called_once()
        
        # Verify original file was used (direct conversion, no preprocessing)
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "img2pdf")
        self.assertEqual(args[1], rgb_path)  # Original file, not processed


if __name__ == "__main__":
    unittest.main()
