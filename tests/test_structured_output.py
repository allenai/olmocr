"""
Tests for structured output functionality.

This module tests the structured output extraction, validation, and formatting
capabilities of the OLMoCR pipeline.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from olmocr.structured_output import (
    DocumentType, FieldType, StructuredField, StructuredTable, StructuredDocument,
    StructuredOutputConfig, DocumentTypeClassifier, FieldExtractor, TableExtractor,
    create_structured_output_config, create_document_type_classifier,
    create_field_extractor, create_table_extractor
)
from olmocr.structured_output.processor import (
    StructuredOutputProcessor, StructuredOutputFormatter,
    create_structured_output_processor, create_structured_output_formatter
)
from olmocr.structured_output.schema import (
    StructuredOutputValidator, SchemaGenerator,
    create_structured_output_validator, create_schema_generator
)
from olmocr.error_handling import create_logger


class TestStructuredOutputConfig(unittest.TestCase):
    """Test structured output configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = create_structured_output_config()
        
        self.assertTrue(config.extract_forms)
        self.assertTrue(config.extract_tables)
        self.assertTrue(config.extract_key_value_pairs)
        self.assertEqual(config.min_confidence, 0.5)
        self.assertTrue(config.enable_field_validation)
        self.assertEqual(config.custom_patterns, {})
    
    def test_custom_config(self):
        """Test custom configuration values."""
        config = create_structured_output_config(
            extract_forms=False,
            extract_tables=True,
            min_confidence=0.8,
            custom_patterns={"test": r"\d+"}
        )
        
        self.assertFalse(config.extract_forms)
        self.assertTrue(config.extract_tables)
        self.assertEqual(config.min_confidence, 0.8)
        self.assertEqual(config.custom_patterns["test"], r"\d+")


class TestStructuredDataClasses(unittest.TestCase):
    """Test structured data classes."""
    
    def test_structured_field(self):
        """Test StructuredField class."""
        field = StructuredField(
            name="email",
            value="test@example.com",
            field_type=FieldType.EMAIL,
            confidence=0.9,
            page_number=1
        )
        
        self.assertEqual(field.name, "email")
        self.assertEqual(field.value, "test@example.com")
        self.assertEqual(field.field_type, FieldType.EMAIL)
        self.assertEqual(field.confidence, 0.9)
        self.assertEqual(field.page_number, 1)
        
        # Test to_dict method
        field_dict = field.to_dict()
        self.assertEqual(field_dict["name"], "email")
        self.assertEqual(field_dict["value"], "test@example.com")
        self.assertEqual(field_dict["type"], "email")
        self.assertEqual(field_dict["confidence"], 0.9)
        self.assertEqual(field_dict["page_number"], 1)
    
    def test_structured_table(self):
        """Test StructuredTable class."""
        table = StructuredTable(
            headers=["Name", "Age", "City"],
            rows=[
                ["John", "30", "New York"],
                ["Jane", "25", "Boston"]
            ],
            confidence=0.95
        )
        
        self.assertEqual(table.headers, ["Name", "Age", "City"])
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(table.confidence, 0.95)
        
        # Test to_dict method
        table_dict = table.to_dict()
        self.assertEqual(table_dict["headers"], ["Name", "Age", "City"])
        self.assertEqual(len(table_dict["rows"]), 2)
        self.assertEqual(table_dict["confidence"], 0.95)
    
    def test_structured_document(self):
        """Test StructuredDocument class."""
        doc = StructuredDocument(
            document_id="test-doc-123",
            document_type=DocumentType.FORM
        )
        
        # Add a field
        field = StructuredField("name", "John Doe", FieldType.TEXT)
        doc.add_field(field)
        
        # Add a table
        table = StructuredTable(["Col1", "Col2"], [["A", "B"]])
        doc.add_table(table)
        
        self.assertEqual(doc.document_id, "test-doc-123")
        self.assertEqual(doc.document_type, DocumentType.FORM)
        self.assertEqual(len(doc.fields), 1)
        self.assertEqual(len(doc.tables), 1)
        
        # Test field retrieval
        retrieved_field = doc.get_field("name")
        self.assertIsNotNone(retrieved_field)
        self.assertEqual(retrieved_field.value, "John Doe")
        
        # Test fields by type
        text_fields = doc.get_fields_by_type(FieldType.TEXT)
        self.assertEqual(len(text_fields), 1)


class TestDocumentTypeClassifier(unittest.TestCase):
    """Test document type classification."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.logger = create_logger("test_classifier")
        self.classifier = create_document_type_classifier(self.logger)
    
    def test_form_classification(self):
        """Test form document classification."""
        form_text = """
        Application Form
        
        Name: _______________
        Address: _______________
        Phone: _______________
        Email: _______________
        
        [ ] Yes [ ] No
        
        Signature: _______________
        """
        
        doc_type = self.classifier.classify_document(form_text)
        self.assertEqual(doc_type, DocumentType.FORM)
    
    def test_invoice_classification(self):
        """Test invoice document classification."""
        invoice_text = """
        INVOICE #12345
        
        Bill To: Customer Name
        
        Item                Qty    Price    Total
        Service A           1      $100     $100
        Service B           2      $50      $100
        
        Subtotal:                           $200
        Tax:                                $20
        Total Amount Due:                   $220
        
        Payment Terms: Net 30
        Due Date: 2024-01-15
        """
        
        doc_type = self.classifier.classify_document(invoice_text)
        self.assertEqual(doc_type, DocumentType.INVOICE)
    
    def test_table_classification(self):
        """Test table document classification."""
        table_text = """
        Data Results
        
        | Name    | Score | Grade |
        |---------|-------|-------|
        | Alice   | 95    | A     |
        | Bob     | 87    | B     |
        | Charlie | 92    | A     |
        """
        
        doc_type = self.classifier.classify_document(table_text)
        self.assertEqual(doc_type, DocumentType.TABLE)
    
    def test_unknown_classification(self):
        """Test unknown document classification."""
        unknown_text = "This is just some random text without any specific structure."
        
        doc_type = self.classifier.classify_document(unknown_text)
        self.assertEqual(doc_type, DocumentType.UNKNOWN)


class TestFieldExtractor(unittest.TestCase):
    """Test field extraction functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = create_structured_output_config()
        self.logger = create_logger("test_extractor")
        self.extractor = create_field_extractor(self.config, self.logger)
    
    def test_key_value_extraction(self):
        """Test key-value pair extraction."""
        text = """
        Name: John Doe
        Age: 30
        Email: john.doe@example.com
        Phone: (555) 123-4567
        Address: 123 Main St, Anytown, USA
        """
        
        fields = self.extractor.extract_key_value_pairs(text)
        
        # Should extract at least the basic key-value pairs
        self.assertGreater(len(fields), 0)
        
        # Check for specific fields
        field_names = [field.name for field in fields]
        self.assertIn("Name", field_names)
        self.assertIn("Age", field_names)
        self.assertIn("Email", field_names)
    
    def test_typed_field_extraction(self):
        """Test typed field extraction."""
        text = """
        Contact us at support@company.com or call (555) 123-4567.
        Our office is located at 123 Main Street.
        Prices start at $99.99 with a 15% discount available.
        Visit our website on 12/25/2023 for more information.
        """
        
        fields = self.extractor.extract_typed_fields(text)
        
        # Should extract typed fields
        self.assertGreater(len(fields), 0)
        
        # Check for specific field types
        field_types = [field.field_type for field in fields]
        self.assertIn(FieldType.EMAIL, field_types)
        self.assertIn(FieldType.PHONE, field_types)
        self.assertIn(FieldType.CURRENCY, field_types)
        self.assertIn(FieldType.PERCENTAGE, field_types)
        self.assertIn(FieldType.DATE, field_types)
    
    def test_field_type_classification(self):
        """Test field type classification."""
        # Test email classification
        self.assertEqual(
            self.extractor._classify_field_type("test@example.com"),
            FieldType.EMAIL
        )
        
        # Test currency classification
        self.assertEqual(
            self.extractor._classify_field_type("$123.45"),
            FieldType.CURRENCY
        )
        
        # Test boolean classification
        self.assertEqual(
            self.extractor._classify_field_type("yes"),
            FieldType.BOOLEAN
        )
        
        # Test default text classification
        self.assertEqual(
            self.extractor._classify_field_type("some random text"),
            FieldType.TEXT
        )


class TestTableExtractor(unittest.TestCase):
    """Test table extraction functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = create_structured_output_config()
        self.logger = create_logger("test_table_extractor")
        self.extractor = create_table_extractor(self.config, self.logger)
    
    def test_markdown_table_extraction(self):
        """Test markdown table extraction."""
        text = """
        Here is a data table:
        
        | Name    | Age | City      |
        |---------|-----|-----------|
        | Alice   | 25  | New York  |
        | Bob     | 30  | Boston    |
        | Charlie | 35  | Chicago   |
        
        End of table.
        """
        
        tables = self.extractor.extract_tables(text)
        
        self.assertEqual(len(tables), 1)
        table = tables[0]
        
        self.assertEqual(table.headers, ["Name", "Age", "City"])
        self.assertEqual(len(table.rows), 3)
        self.assertEqual(table.rows[0], ["Alice", "25", "New York"])
        self.assertEqual(table.rows[1], ["Bob", "30", "Boston"])
        self.assertEqual(table.rows[2], ["Charlie", "35", "Chicago"])
    
    def test_pipe_table_extraction(self):
        """Test pipe-separated table extraction."""
        text = """
        Product | Price | Stock
        Widget A | $10.99 | 50
        Widget B | $15.99 | 25
        Widget C | $20.99 | 10
        """
        
        tables = self.extractor.extract_tables(text)
        
        self.assertEqual(len(tables), 1)
        table = tables[0]
        
        self.assertEqual(table.headers, ["Product", "Price", "Stock"])
        self.assertEqual(len(table.rows), 3)
        self.assertEqual(table.rows[0], ["Widget A", "$10.99", "50"])
    
    def test_no_tables(self):
        """Test text with no tables."""
        text = "This is just regular text without any tables."
        
        tables = self.extractor.extract_tables(text)
        self.assertEqual(len(tables), 0)


class TestStructuredOutputProcessor(unittest.TestCase):
    """Test structured output processor."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = create_structured_output_config()
        self.logger = create_logger("test_processor")
        self.processor = create_structured_output_processor(self.config, self.logger)
    
    def test_document_processing(self):
        """Test complete document processing."""
        text = """
        Customer Information Form
        
        Name: John Doe
        Email: john.doe@example.com
        Phone: (555) 123-4567
        
        Order Details:
        | Item     | Quantity | Price  |
        |----------|----------|--------|
        | Widget A | 2        | $10.99 |
        | Widget B | 1        | $15.99 |
        
        Total: $37.97
        """
        
        structured_doc = self.processor.process_document(
            document_id="test-doc-123",
            text_content=text
        )
        
        self.assertEqual(structured_doc.document_id, "test-doc-123")
        self.assertEqual(structured_doc.document_type, DocumentType.FORM)
        
        # Should extract fields and tables
        self.assertGreater(len(structured_doc.fields), 0)
        self.assertGreater(len(structured_doc.tables), 0)
        
        # Check metadata
        self.assertIn("extraction_config", structured_doc.metadata)
        self.assertIn("total_fields", structured_doc.metadata)
        self.assertIn("total_tables", structured_doc.metadata)
    
    def test_document_validation(self):
        """Test document validation."""
        # Create a valid document
        valid_doc = StructuredDocument(
            document_id="test-doc",
            document_type=DocumentType.FORM
        )
        valid_doc.add_field(StructuredField("name", "John", FieldType.TEXT, confidence=0.9))
        
        self.assertTrue(self.processor.validate_structured_document(valid_doc))
        
        # Create an invalid document (empty document_id)
        invalid_doc = StructuredDocument(
            document_id="",
            document_type=DocumentType.FORM
        )
        
        self.assertFalse(self.processor.validate_structured_document(invalid_doc))


class TestStructuredOutputFormatter(unittest.TestCase):
    """Test structured output formatter."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.logger = create_logger("test_formatter")
        self.formatter = create_structured_output_formatter(self.logger)
        
        # Create a test document
        self.test_doc = StructuredDocument(
            document_id="test-doc-123",
            document_type=DocumentType.FORM
        )
        self.test_doc.add_field(StructuredField("name", "John Doe", FieldType.TEXT))
        self.test_doc.add_field(StructuredField("email", "john@example.com", FieldType.EMAIL))
        self.test_doc.add_table(StructuredTable(["Col1", "Col2"], [["A", "B"], ["C", "D"]]))
    
    def test_json_formatting(self):
        """Test JSON formatting."""
        json_output = self.formatter.format_as_json(self.test_doc)
        
        # Should be valid JSON
        parsed = json.loads(json_output)
        
        self.assertEqual(parsed["document_id"], "test-doc-123")
        self.assertEqual(parsed["document_type"], "form")
        self.assertEqual(len(parsed["fields"]), 2)
        self.assertEqual(len(parsed["tables"]), 1)
    
    def test_key_value_formatting(self):
        """Test key-value formatting."""
        kv_output = self.formatter.format_as_key_value(self.test_doc)
        
        self.assertIn("Document ID: test-doc-123", kv_output)
        self.assertIn("Document Type: form", kv_output)
        self.assertIn("FIELDS:", kv_output)
        self.assertIn("TABLES:", kv_output)
    
    def test_csv_table_formatting(self):
        """Test CSV table formatting."""
        csv_tables = self.formatter.format_as_csv_tables(self.test_doc)
        
        self.assertIn("table_1", csv_tables)
        csv_content = csv_tables["table_1"]
        
        lines = csv_content.split('\n')
        self.assertEqual(lines[0], '"Col1","Col2"')  # Headers
        self.assertEqual(lines[1], '"A","B"')        # First row
        self.assertEqual(lines[2], '"C","D"')        # Second row
    
    def test_combined_output_formatting(self):
        """Test combined output formatting."""
        dolma_doc = {
            "id": "test-id",
            "text": "Test document text",
            "source": "olmocr",
            "metadata": {},
            "attributes": {}
        }
        
        combined = self.formatter.format_combined_output(dolma_doc, self.test_doc)
        
        # Should have original Dolma fields
        self.assertEqual(combined["id"], "test-id")
        self.assertEqual(combined["text"], "Test document text")
        
        # Should have structured data
        self.assertIn("structured_data", combined)
        self.assertEqual(combined["structured_data"]["document_id"], "test-doc-123")
        
        # Should have updated metadata
        self.assertTrue(combined["metadata"]["has_structured_data"])
        self.assertEqual(combined["metadata"]["structured_fields_count"], 2)
        self.assertEqual(combined["metadata"]["structured_tables_count"], 1)


if __name__ == "__main__":
    unittest.main()
