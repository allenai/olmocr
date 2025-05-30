# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Fixed
- Enhanced image processing to handle RGBA, 16-bit, grayscale with alpha (LA), and palette images
- Automatic image format detection and preprocessing for problematic formats
- Resolved "Image with transparency and a bit depth of 16" errors from img2pdf
- Added comprehensive test coverage for image format handling

### Added
- Smart image preprocessing pipeline with automatic format conversion
- Support for all PIL-compatible image formats
- Structured logging for image processing operations
- Temporary file cleanup and memory-efficient processing
- Backward compatibility maintained for existing image processing workflows

## [v0.1.70](https://github.com/allenai/olmocr/releases/tag/v0.1.70) - 2025-05-23

## [v0.1.69](https://github.com/allenai/olmocr/releases/tag/v0.1.69) - 2025-05-20

## [v0.1.68](https://github.com/allenai/olmocr/releases/tag/v0.1.68) - 2025-05-19

## [v0.1.60](https://github.com/allenai/olmocr/releases/tag/v0.1.60) - 2025-03-17

## [v0.1.58](https://github.com/allenai/olmocr/releases/tag/v0.1.58) - 2025-02-15

## [v0.1.53](https://github.com/allenai/olmocr/releases/tag/v0.1.53) - 2025-02-14

- Fixed git checks

- Added gemini and claude runners and a viewer.