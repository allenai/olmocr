"""
Test fixtures and data generators for OLMoCR testing.

This module provides reusable test fixtures, mock objects, and data generators
for consistent testing across all OLMoCR components.
"""

import os
import random
import string
import tempfile
from typing import Any, Dict, List, Optional, Union


class TestFixtures:
    """Central repository for test fixtures and data."""
    
    @staticmethod
    def create_sample_pdf_content() -> str:
        """Create sample PDF text content for testing."""
        return """
        Sample Document Title
        
        This is a sample document for testing purposes.
        
        Name: John Doe
        Email: john.doe@example.com
        Phone: (555) 123-4567
        Address: 123 Main Street, Anytown, ST 12345
        
        Product Information:
        | Product | Quantity | Price |
        |---------|----------|-------|
        | Widget A| 2        | $10.99|
        | Widget B| 1        | $15.99|
        | Widget C| 3        | $8.99 |
        
        Total: $56.94
        
        Thank you for your business!
        """
    
    @staticmethod
    def create_sample_form_content() -> str:
        """Create sample form content for testing."""
        return """
        APPLICATION FORM
        
        Personal Information:
        First Name: Alice
        Last Name: Smith
        Date of Birth: 01/15/1990
        Social Security Number: 123-45-6789
        
        Contact Information:
        Email Address: alice.smith@email.com
        Phone Number: (555) 987-6543
        Home Address: 456 Oak Avenue, Springfield, IL 62701
        
        Employment Information:
        Employer: Tech Solutions Inc.
        Job Title: Software Engineer
        Annual Salary: $75,000
        Years of Experience: 5
        
        Emergency Contact:
        Name: Bob Smith
        Relationship: Spouse
        Phone: (555) 987-6544
        
        Signature: Alice Smith
        Date: 12/01/2023
        """
    
    @staticmethod
    def create_sample_invoice_content() -> str:
        """Create sample invoice content for testing."""
        return """
        INVOICE #INV-2023-001
        
        Bill To:
        Acme Corporation
        123 Business Street
        Corporate City, ST 54321
        
        Ship To:
        Acme Warehouse
        456 Storage Lane
        Warehouse City, ST 54322
        
        Invoice Date: 11/15/2023
        Due Date: 12/15/2023
        Terms: Net 30
        
        Description                 Qty    Unit Price    Total
        Professional Services       40     $125.00       $5,000.00
        Software License            1      $500.00       $500.00
        Support Package             12     $50.00        $600.00
        
        Subtotal:                                        $6,100.00
        Tax (8.5%):                                      $518.50
        Total Amount Due:                                $6,618.50
        
        Payment Instructions:
        Please remit payment within 30 days.
        """
    
    @staticmethod
    def create_sample_table_content() -> str:
        """Create sample table content for testing."""
        return """
        QUARTERLY SALES REPORT
        
        Regional Performance:
        
        | Region    | Q1 Sales | Q2 Sales | Q3 Sales | Q4 Sales | Total     |
        |-----------|----------|----------|----------|----------|-----------|
        | North     | $125,000 | $135,000 | $142,000 | $158,000 | $560,000  |
        | South     | $98,000  | $105,000 | $112,000 | $125,000 | $440,000  |
        | East      | $156,000 | $162,000 | $171,000 | $185,000 | $674,000  |
        | West      | $134,000 | $141,000 | $148,000 | $165,000 | $588,000  |
        | Total     | $513,000 | $543,000 | $573,000 | $633,000 | $2,262,000|
        
        Top Performers:
        1. Sarah Johnson - $45,000
        2. Mike Chen - $42,500
        3. Lisa Rodriguez - $38,750
        """


class MockPageResponse:
    """Mock page response for testing."""
    
    def __init__(self, natural_text: str = None, structured_data: Dict = None):
        self.natural_text = natural_text or "Sample page text content"
        self.structured_data = structured_data or {}
        self.confidence = 0.95
        self.processing_time = 1.5


class MockPageResult:
    """Mock page result for testing."""
    
    def __init__(self, page_num: int = 1, text: str = None, is_fallback: bool = False):
        self.page_num = page_num
        self.response = MockPageResponse(text)
        self.is_fallback = is_fallback
        self.input_tokens = 100
        self.output_tokens = 50
        self.processing_time = 2.0
        self.error = None


class MockStructuredDocument:
    """Mock structured document for testing."""
    
    def __init__(self, document_id: str = "test-doc", document_type: str = "form"):
        self.document_id = document_id
        self.document_type = document_type
        self.fields = []
        self.tables = []
        self.metadata = {}
        self.confidence = 0.9
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'document_id': self.document_id,
            'document_type': self.document_type,
            'fields': [field.to_dict() if hasattr(field, 'to_dict') else field for field in self.fields],
            'tables': [table.to_dict() if hasattr(table, 'to_dict') else table for table in self.tables],
            'metadata': self.metadata,
            'confidence': self.confidence
        }


def create_test_pdf_data(num_pages: int = 3, content_type: str = "mixed") -> List[MockPageResult]:
    """
    Create test PDF data with multiple pages.
    
    Args:
        num_pages: Number of pages to create
        content_type: Type of content ('form', 'invoice', 'table', 'mixed')
        
    Returns:
        List of MockPageResult objects
    """
    content_generators = {
        'form': TestFixtures.create_sample_form_content,
        'invoice': TestFixtures.create_sample_invoice_content,
        'table': TestFixtures.create_sample_table_content,
        'mixed': TestFixtures.create_sample_pdf_content,
    }
    
    generator = content_generators.get(content_type, TestFixtures.create_sample_pdf_content)
    
    pages = []
    for i in range(num_pages):
        content = generator()
        # Add page-specific content
        content += f"\n\nPage {i + 1} of {num_pages}"
        
        page_result = MockPageResult(
            page_num=i + 1,
            text=content,
            is_fallback=random.choice([True, False]) if i > 0 else False
        )
        pages.append(page_result)
    
    return pages


def create_test_image_data(width: int = 800, height: int = 600, format: str = "RGB") -> bytes:
    """
    Create test image data.
    
    Args:
        width: Image width
        height: Image height
        format: Image format ('RGB', 'RGBA', 'L')
        
    Returns:
        Image data as bytes
    """
    # Fallback: create minimal PNG data
    # This is a minimal valid PNG file (1x1 pixel)
    png_data = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13'
        b'\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDATx\x9cc```'
        b'\x00\x00\x00\x02\x00\x01\xe5\'\xde\xfc\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    return png_data


def create_test_config(**overrides) -> Dict[str, Any]:
    """
    Create a test configuration with sensible defaults.
    
    Args:
        **overrides: Configuration overrides
        
    Returns:
        Test configuration dictionary
    """
    default_config = {
        'workspace': tempfile.mkdtemp(prefix="test_workspace_"),
        'output_dir': tempfile.mkdtemp(prefix="test_output_"),
        'workers': 1,
        'max_retries': 2,
        'timeout': 10.0,
        'debug': True,
        'model': 'test-model',
        'model_chat_template': 'test-template',
        'model_max_context': 4096,
        'pages_per_group': 10,
        'max_page_retries': 3,
        'max_page_error_rate': 0.1,
        'apply_filter': False,
        'markdown': False,
        'structured_output': False,
        'extract_forms': False,
        'extract_tables': False,
        'extract_key_value_pairs': False,
        'structured_min_confidence': 0.5,
        'structured_output_format': 'combined',
    }
    
    default_config.update(overrides)
    return default_config


def create_test_structured_document(doc_type: str = "form") -> MockStructuredDocument:
    """
    Create a test structured document with sample data.
    
    Args:
        doc_type: Type of document to create
        
    Returns:
        MockStructuredDocument with sample data
    """
    doc = MockStructuredDocument(f"test-{doc_type}-001", doc_type)
    
    # Add some mock fields
    if doc_type == "form":
        doc.fields = [
            {"name": "Name", "value": "John Doe", "type": "text", "confidence": 0.95},
            {"name": "Email", "value": "john.doe@example.com", "type": "email", "confidence": 0.98},
            {"name": "Phone", "value": "(555) 123-4567", "type": "phone", "confidence": 0.92},
        ]
    elif doc_type == "invoice":
        doc.fields = [
            {"name": "Invoice Number", "value": "INV-2023-001", "type": "text", "confidence": 0.99},
            {"name": "Total Amount", "value": "$6,618.50", "type": "currency", "confidence": 0.97},
        ]
        doc.tables = [
            {
                "headers": ["Description", "Qty", "Unit Price", "Total"],
                "rows": [
                    ["Professional Services", "40", "$125.00", "$5,000.00"],
                    ["Software License", "1", "$500.00", "$500.00"]
                ],
                "confidence": 0.91
            }
        ]
    
    return doc


def generate_random_text(length: int = 100, include_special: bool = False) -> str:
    """
    Generate random text for testing.
    
    Args:
        length: Length of text to generate
        include_special: Include special characters
        
    Returns:
        Random text string
    """
    chars = string.ascii_letters + string.digits + ' '
    if include_special:
        chars += string.punctuation
    
    return ''.join(random.choice(chars) for _ in range(length))
