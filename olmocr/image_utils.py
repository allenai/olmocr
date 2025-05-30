import logging
import os
import shutil
import subprocess
import tempfile
from typing import List, Union

from PIL import Image

# Initialize logger
logger = logging.getLogger(__name__)


def convert_image_to_pdf_bytes(image_files: Union[str, List[str]]) -> bytes:
    """
    Convert one or multiple image files to PDF bytes.

    Handles various image formats including RGBA, 16-bit, and grayscale with alpha.
    Automatically preprocesses images that are incompatible with img2pdf.

    Args:
        image_files: A single image file path (str) or a list of image file paths

    Returns:
        bytes: The PDF content as bytes

    Raises:
        RuntimeError: If the conversion fails
        ValueError: If invalid input is provided
    """
    # Handle different input types
    if isinstance(image_files, str):
        # Single image case
        image_files = [image_files]
    elif not isinstance(image_files, list) or not image_files:
        raise ValueError("image_files must be a non-empty string or list of strings")

    # Validate files exist
    for image_file in image_files:
        if not os.path.exists(image_file):
            raise ValueError(f"File does not exist: {image_file}")

    # Check if any images need preprocessing
    needs_preprocessing = False
    for image_file in image_files:
        try:
            with Image.open(image_file) as img:
                # Check for problematic formats
                if (img.mode in ['RGBA', 'LA', 'P'] or
                    (hasattr(img, 'bits') and img.bits > 8) or
                    img.mode not in ['RGB', 'L']):
                    needs_preprocessing = True
                    break
        except Exception as e:
            logger.warning(f"Could not analyze image {image_file}: {e}")
            # If we can't analyze it, try preprocessing anyway
            needs_preprocessing = True
            break

    if needs_preprocessing:
        return _convert_with_preprocessing(image_files)
    else:
        return _convert_direct(image_files)


def _convert_direct(image_files: List[str]) -> bytes:
    """
    Convert images directly using img2pdf without preprocessing.

    Args:
        image_files: List of image file paths

    Returns:
        bytes: The PDF content as bytes

    Raises:
        RuntimeError: If the conversion fails
    """
    try:
        logger.debug(f"Converting {len(image_files)} images directly with img2pdf")
        result = subprocess.run(["img2pdf"] + image_files, check=True, capture_output=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8').strip()
        raise RuntimeError(f"Error converting image(s) to PDF: {error_msg}") from e


def _convert_with_preprocessing(image_files: List[str]) -> bytes:
    """
    Convert images to PDF with preprocessing to handle problematic formats.

    Handles RGBA, 16-bit, LA, and palette images by converting them to
    compatible formats before passing to img2pdf.

    Args:
        image_files: List of image file paths

    Returns:
        bytes: The PDF content as bytes

    Raises:
        RuntimeError: If the conversion fails
    """
    temp_dir = tempfile.mkdtemp(prefix="olmocr_image_")
    cleaned_files = []

    try:
        logger.debug(f"Preprocessing {len(image_files)} images for PDF conversion")

        for image_path in image_files:
            with Image.open(image_path) as img:
                logger.debug(f"Processing {image_path}: mode={img.mode}, size={img.size}")

                # Convert problematic formats to compatible ones
                processed_img = _preprocess_image(img)

                # Generate output filename
                base_name = os.path.splitext(os.path.basename(image_path))[0]
                clean_path = os.path.join(temp_dir, f"{base_name}_processed.png")

                # Save processed image
                processed_img.save(clean_path, format="PNG", optimize=True)
                cleaned_files.append(clean_path)

                logger.debug(f"Saved processed image to {clean_path}")

        # Convert processed images to PDF
        result = subprocess.run(["img2pdf"] + cleaned_files, check=True, capture_output=True)
        return result.stdout

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8').strip()
        raise RuntimeError(f"Error converting preprocessed image(s) to PDF: {error_msg}") from e
    except Exception as e:
        raise RuntimeError(f"Error during image preprocessing: {str(e)}") from e
    finally:
        # Clean up temporary files
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.debug(f"Cleaned up temporary directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to clean up temporary directory {temp_dir}: {e}")


def _preprocess_image(img: Image.Image) -> Image.Image:
    """
    Preprocess a PIL Image to make it compatible with img2pdf.

    Args:
        img: PIL Image object

    Returns:
        Image.Image: Processed image compatible with img2pdf
    """
    # Handle different image modes
    if img.mode == "RGBA":
        # Create white background and paste image with alpha
        logger.debug("Converting RGBA to RGB with white background")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])  # Use alpha channel as mask
        return background

    elif img.mode == "LA":
        # Convert grayscale with alpha to plain grayscale
        logger.debug("Converting LA to L (grayscale)")
        return img.convert("L")

    elif img.mode == "P":
        # Convert palette images to RGB
        logger.debug("Converting palette image to RGB")
        return img.convert("RGB")

    elif img.mode in ["CMYK", "YCbCr"]:
        # Convert other color spaces to RGB
        logger.debug(f"Converting {img.mode} to RGB")
        return img.convert("RGB")

    elif img.mode not in ["RGB", "L"]:
        # Convert any other mode to RGB as fallback
        logger.debug(f"Converting unknown mode {img.mode} to RGB")
        return img.convert("RGB")

    # Image is already in a compatible format
    return img


def is_png(file_path: str) -> bool:
    """
    Check if a file is a PNG image by examining its header.

    Args:
        file_path: Path to the file to check

    Returns:
        bool: True if the file is a PNG, False otherwise
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(8)
            return header == b"\x89PNG\r\n\x1a\n"
    except Exception as e:
        logger.debug(f"Error checking PNG header for {file_path}: {e}")
        return False


def is_jpeg(file_path: str) -> bool:
    """
    Check if a file is a JPEG image by examining its header.

    Args:
        file_path: Path to the file to check

    Returns:
        bool: True if the file is a JPEG, False otherwise
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(2)
            return header == b"\xff\xd8"
    except Exception as e:
        logger.debug(f"Error checking JPEG header for {file_path}: {e}")
        return False


def is_supported_image(file_path: str) -> bool:
    """
    Check if a file is a supported image format.

    Args:
        file_path: Path to the file to check

    Returns:
        bool: True if the file is a supported image format, False otherwise
    """
    try:
        with Image.open(file_path) as img:
            # PIL can open it, so it's a supported image format
            return True
    except Exception as e:
        logger.debug(f"File {file_path} is not a supported image format: {e}")
        return False
