"""
Unit tests for the document builder module.
"""

import unittest
from unittest.mock import patch

from olmocr.pipeline.document_builder import (
    DolmaDocumentBuilder,
    PageResult,
    create_document_builder,
    build_dolma_document,
)
from olmocr.prompts import PageResponse


class TestPageResult(unittest.TestCase):
    """Test cases for PageResult dataclass."""
    
    def test_page_result_creation(self):
        """Test PageResult creation."""
        response = PageResponse(
            natural_text="Test content",
            primary_language="en",
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        )
        
        page_result = PageResult(
            s3_path="s3://bucket/test.pdf",
            page_num=1,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=False,
        )
        
        self.assertEqual(page_result.s3_path, "s3://bucket/test.pdf")
        self.assertEqual(page_result.page_num, 1)
        self.assertEqual(page_result.response, response)
        self.assertEqual(page_result.input_tokens, 100)
        self.assertEqual(page_result.output_tokens, 50)
        self.assertFalse(page_result.is_fallback)
    
    def test_page_result_frozen(self):
        """Test that PageResult is frozen (immutable)."""
        response = PageResponse(
            natural_text="Test content",
            primary_language="en",
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        )
        
        page_result = PageResult(
            s3_path="s3://bucket/test.pdf",
            page_num=1,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=False,
        )
        
        # Should not be able to modify frozen dataclass
        with self.assertRaises(AttributeError):
            page_result.page_num = 2


class TestDolmaDocumentBuilder(unittest.TestCase):
    """Test cases for DolmaDocumentBuilder."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.builder = DolmaDocumentBuilder()
    
    def _create_test_page_result(self, page_num: int, text: str, is_fallback: bool = False) -> PageResult:
        """Helper to create test PageResult."""
        response = PageResponse(
            natural_text=text,
            primary_language="en",
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        )
        
        return PageResult(
            s3_path="s3://bucket/test.pdf",
            page_num=page_num,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=is_fallback,
        )
    
    def test_build_document_single_page(self):
        """Test building document with single page."""
        page_result = self._create_test_page_result(1, "This is page 1 content.")
        
        doc = self.builder.build_document("test.pdf", [page_result])
        
        self.assertIsNotNone(doc)
        self.assertEqual(doc["text"], "This is page 1 content.")
        self.assertEqual(doc["source"], "olmocr")
        self.assertEqual(doc["metadata"]["Source-File"], "test.pdf")
        self.assertEqual(doc["metadata"]["pdf-total-pages"], 1)
        self.assertEqual(doc["metadata"]["total-input-tokens"], 100)
        self.assertEqual(doc["metadata"]["total-output-tokens"], 50)
        self.assertEqual(doc["metadata"]["total-fallback-pages"], 0)
        
        # Check page spans
        page_spans = doc["attributes"]["pdf_page_numbers"]
        self.assertEqual(len(page_spans), 1)
        self.assertEqual(page_spans[0], [0, 23, 1])  # [start, end, page_num]
    
    def test_build_document_multiple_pages(self):
        """Test building document with multiple pages."""
        page_results = [
            self._create_test_page_result(1, "Page 1 content."),
            self._create_test_page_result(2, "Page 2 content."),
            self._create_test_page_result(3, "Page 3 content."),
        ]
        
        doc = self.builder.build_document("test.pdf", page_results)
        
        self.assertIsNotNone(doc)
        expected_text = "Page 1 content.\nPage 2 content.\nPage 3 content."
        self.assertEqual(doc["text"], expected_text)
        self.assertEqual(doc["metadata"]["pdf-total-pages"], 3)
        self.assertEqual(doc["metadata"]["total-input-tokens"], 300)
        self.assertEqual(doc["metadata"]["total-output-tokens"], 150)
        
        # Check page spans
        page_spans = doc["attributes"]["pdf_page_numbers"]
        self.assertEqual(len(page_spans), 3)
        self.assertEqual(page_spans[0], [0, 17, 1])   # "Page 1 content.\n"
        self.assertEqual(page_spans[1], [17, 34, 2])  # "Page 2 content.\n"
        self.assertEqual(page_spans[2], [34, 50, 3])  # "Page 3 content."
    
    def test_build_document_with_fallback_pages(self):
        """Test building document with fallback pages."""
        page_results = [
            self._create_test_page_result(1, "Page 1 content.", is_fallback=False),
            self._create_test_page_result(2, "Page 2 fallback.", is_fallback=True),
        ]
        
        doc = self.builder.build_document("test.pdf", page_results)
        
        self.assertIsNotNone(doc)
        self.assertEqual(doc["metadata"]["total-fallback-pages"], 1)
    
    def test_build_document_empty_pages(self):
        """Test building document with empty page results."""
        doc = self.builder.build_document("test.pdf", [])
        self.assertIsNone(doc)
    
    def test_build_document_no_text(self):
        """Test building document with pages that have no text."""
        response = PageResponse(
            natural_text=None,  # No text
            primary_language="en",
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        )
        
        page_result = PageResult(
            s3_path="s3://bucket/test.pdf",
            page_num=1,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=False,
        )
        
        doc = self.builder.build_document("test.pdf", [page_result])
        self.assertIsNone(doc)
    
    def test_generate_document_id(self):
        """Test document ID generation."""
        text1 = "This is test content."
        text2 = "This is different content."
        
        id1 = self.builder._generate_document_id(text1)
        id2 = self.builder._generate_document_id(text2)
        id3 = self.builder._generate_document_id(text1)  # Same as text1
        
        # IDs should be different for different content
        self.assertNotEqual(id1, id2)
        # IDs should be same for same content
        self.assertEqual(id1, id3)
        # IDs should be valid SHA1 hashes (40 hex characters)
        self.assertEqual(len(id1), 40)
        self.assertTrue(all(c in "0123456789abcdef" for c in id1))
    
    def test_validate_document_valid(self):
        """Test document validation with valid document."""
        page_result = self._create_test_page_result(1, "Test content.")
        doc = self.builder.build_document("test.pdf", [page_result])
        
        self.assertTrue(self.builder.validate_document(doc))
    
    def test_validate_document_missing_fields(self):
        """Test document validation with missing fields."""
        invalid_doc = {
            "id": "test",
            "text": "content",
            # Missing required fields
        }
        
        self.assertFalse(self.builder.validate_document(invalid_doc))
    
    def test_validate_document_missing_metadata(self):
        """Test document validation with missing metadata."""
        invalid_doc = {
            "id": "test",
            "text": "content",
            "source": "olmocr",
            "added": "2023-01-01",
            "created": "2023-01-01",
            "metadata": {
                # Missing required metadata fields
            },
            "attributes": {"pdf_page_numbers": []},
        }
        
        self.assertFalse(self.builder.validate_document(invalid_doc))
    
    def test_validate_document_missing_attributes(self):
        """Test document validation with missing attributes."""
        invalid_doc = {
            "id": "test",
            "text": "content",
            "source": "olmocr",
            "added": "2023-01-01",
            "created": "2023-01-01",
            "metadata": {
                "Source-File": "test.pdf",
                "olmocr-version": "1.0.0",
                "pdf-total-pages": 1,
            },
            "attributes": {
                # Missing pdf_page_numbers
            },
        }
        
        self.assertFalse(self.builder.validate_document(invalid_doc))


class TestFactoryFunctions(unittest.TestCase):
    """Test cases for factory functions."""
    
    def test_create_document_builder(self):
        """Test create_document_builder factory function."""
        builder = create_document_builder()
        self.assertIsInstance(builder, DolmaDocumentBuilder)
    
    def test_build_dolma_document_legacy(self):
        """Test legacy build_dolma_document function."""
        response = PageResponse(
            natural_text="Test content",
            primary_language="en",
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        )
        
        page_result = PageResult(
            s3_path="s3://bucket/test.pdf",
            page_num=1,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=False,
        )
        
        doc = build_dolma_document("test.pdf", [page_result])
        
        self.assertIsNotNone(doc)
        self.assertEqual(doc["text"], "Test content")
        self.assertEqual(doc["metadata"]["Source-File"], "test.pdf")


if __name__ == "__main__":
    unittest.main()
