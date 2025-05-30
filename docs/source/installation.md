Installation
============

**olmocr** supports Python >= 3.8.

## Installing with `pip`

**olmocr** is available [on PyPI](https://pypi.org/project/olmocr/). Just run

```bash
pip install olmocr
```

## Installing from source

To install **olmocr** from source, first clone [the repository](https://github.com/allenai/olmocr):

```bash
git clone https://github.com/allenai/olmocr.git
cd olmocr
```

Then run

```bash
pip install -e .
```

## Image Format Support

**olmocr** now supports a wide range of image formats with automatic preprocessing:

- **PDF** - Primary format, fully supported
- **PNG** - All variants including RGBA (transparency), 16-bit, grayscale with alpha, and palette images
- **JPEG** - Standard RGB and grayscale formats
- **Other formats** - Most PIL-supported formats are automatically converted to compatible formats

The image processing system automatically detects and converts problematic formats (RGBA, 16-bit, palette) to ensure compatibility with the OCR pipeline while maintaining image quality.
