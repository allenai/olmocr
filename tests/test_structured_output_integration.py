"""
Integration tests for structured output functionality.

This module provides comprehensive integration tests for the structured output
system, testing end-to-end workflows and integration with the pipeline.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from tests.testing_framework import (
    BaseOLMoCRTest, IntegrationTestHelper, PipelineTestRunner,
    TestFixtures, create_test_structured_document,
    PropertyTestGenerator, StructuredOutputPropertyTests,
    PerformanceTestRunner
)


class TestStructuredOutputIntegration(BaseOLMoCRTest):
    """Integration tests for structured output with pipeline."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        super().setUp()
        self.integration_helper = IntegrationTestHelper("structured_output_integration")
        
        try:
            from olmocr.structured_output import (
                create_structured_output_config, create_structured_output_processor,
                create_structured_output_formatter, DocumentType, FieldType
            )
            from olmocr.pipeline.document_builder import create_document_builder
            
            self.create_structured_output_config = create_structured_output_config
            self.create_structured_output_processor = create_structured_output_processor
            self.create_structured_output_formatter = create_structured_output_formatter
            self.create_document_builder = create_document_builder
            self.DocumentType = DocumentType
            self.FieldType = FieldType
            
        except ImportError:
            self.skipTest("Structured output or document builder modules not available")
    
    def tearDown(self):
        """Clean up integration test fixtures."""
        self.integration_helper.cleanup()
        super().tearDown()
    
    def test_end_to_end_form_processing(self):
        """Test end-to-end form processing with structured output."""
        # Set up test environment
        env = self.integration_helper.setup_test_environment()
        
        # Create structured output configuration
        config = self.create_structured_output_config(
            extract_forms=True,
            extract_tables=False,
            min_confidence=0.5
        )
        
        # Create document builder with structured output
        builder = self.create_document_builder(config)
        
        # Create test form content
        form_content = TestFixtures.create_sample_form_content()
        
        # Mock page results
        from tests.testing_framework.fixtures import MockPageResult
        page_results = [MockPageResult(page_num=1, text=form_content)]
        
        # Build document with structured output
        document = builder.build_document("test_form.pdf", page_results)
        
        # Verify document structure
        self.assertIn("structured_data", document)
        self.assertTrue(document["metadata"]["has_structured_data"])
        self.assertEqual(document["metadata"]["document_type"], "form")
        self.assertGreater(document["metadata"]["structured_fields_count"], 0)
        
        # Verify structured data content
        structured_data = document["structured_data"]
        self.assertEqual(structured_data["document_type"], "form")
        self.assertGreater(len(structured_data["fields"]), 0)
        
        # Check for expected fields
        field_names = [field["name"] for field in structured_data["fields"]]
        expected_fields = ["First Name", "Last Name", "Email Address"]
        for expected_field in expected_fields:
            self.assertIn(expected_field, field_names)
    
    def test_end_to_end_invoice_processing(self):
        """Test end-to-end invoice processing with structured output."""
        # Set up test environment
        env = self.integration_helper.setup_test_environment()
        
        # Create structured output configuration
        config = self.create_structured_output_config(
            extract_forms=True,
            extract_tables=True,
            min_confidence=0.4
        )
        
        # Create document builder with structured output
        builder = self.create_document_builder(config)
        
        # Create test invoice content
        invoice_content = TestFixtures.create_sample_invoice_content()
        
        # Mock page results
        from tests.testing_framework.fixtures import MockPageResult
        page_results = [MockPageResult(page_num=1, text=invoice_content)]
        
        # Build document with structured output
        document = builder.build_document("test_invoice.pdf", page_results)
        
        # Verify document structure
        self.assertIn("structured_data", document)
        self.assertTrue(document["metadata"]["has_structured_data"])
        self.assertEqual(document["metadata"]["document_type"], "invoice")
        self.assertGreater(document["metadata"]["structured_fields_count"], 0)
        self.assertGreater(document["metadata"]["structured_tables_count"], 0)
        
        # Verify structured data content
        structured_data = document["structured_data"]
        self.assertEqual(structured_data["document_type"], "invoice")
        self.assertGreater(len(structured_data["fields"]), 0)
        self.assertGreater(len(structured_data["tables"]), 0)
        
        # Check for expected invoice fields
        field_names = [field["name"] for field in structured_data["fields"]]
        expected_fields = ["Invoice Date", "Due Date", "Total Amount Due"]
        for expected_field in expected_fields:
            self.assertIn(expected_field, field_names)
        
        # Check table structure
        table = structured_data["tables"][0]
        self.assertIn("headers", table)
        self.assertIn("rows", table)
        self.assertGreater(len(table["headers"]), 0)
        self.assertGreater(len(table["rows"]), 0)
    
    def test_combined_output_format(self):
        """Test combined output format with both text and structured data."""
        # Set up test environment
        env = self.integration_helper.setup_test_environment()
        
        # Create structured output configuration
        config = self.create_structured_output_config()
        
        # Create processor and formatter
        processor = self.create_structured_output_processor(config)
        formatter = self.create_structured_output_formatter()
        
        # Create test content
        test_content = TestFixtures.create_sample_pdf_content()
        
        # Process document
        structured_doc = processor.process_document("test-combined", test_content)
        
        # Create mock Dolma document
        dolma_doc = {
            "id": "test-combined-123",
            "text": test_content,
            "source": "olmocr",
            "added": "2023-12-01",
            "created": "2023-12-01",
            "metadata": {},
            "attributes": {}
        }
        
        # Format as combined output
        combined_doc = formatter.format_combined_output(dolma_doc, structured_doc)
        
        # Verify combined document structure
        self.assertEqual(combined_doc["id"], "test-combined-123")
        self.assertEqual(combined_doc["text"], test_content)
        self.assertIn("structured_data", combined_doc)
        
        # Verify metadata updates
        self.assertTrue(combined_doc["metadata"]["has_structured_data"])
        self.assertGreater(combined_doc["metadata"]["structured_fields_count"], 0)
        
        # Verify structured data is properly embedded
        structured_data = combined_doc["structured_data"]
        self.assertEqual(structured_data["document_id"], "test-combined")
        self.assertGreater(len(structured_data["fields"]), 0)
    
    def test_json_output_validation(self):
        """Test JSON output validation and schema compliance."""
        try:
            from olmocr.structured_output.schema import create_structured_output_validator
            
            # Create validator
            validator = create_structured_output_validator()
            
            # Create test structured document
            test_doc = create_test_structured_document("form")
            
            # Convert to dictionary and validate
            doc_dict = test_doc.to_dict()
            is_valid = validator.validate_document(doc_dict)
            
            self.assertTrue(is_valid, "Structured document should be valid")
            
            # Test with invalid data
            invalid_doc = {
                "document_id": "",  # Invalid: empty ID
                "document_type": "invalid_type",  # Invalid: not in enum
                "fields": [],
                "tables": []
            }
            
            is_invalid = validator.validate_document(invalid_doc)
            self.assertFalse(is_invalid, "Invalid document should fail validation")
            
        except ImportError:
            self.skipTest("Schema validation module not available")
    
    def test_cli_argument_integration(self):
        """Test CLI argument integration with structured output."""
        # Mock command line arguments
        mock_args = MagicMock()
        mock_args.structured_output = True
        mock_args.extract_forms = True
        mock_args.extract_tables = True
        mock_args.extract_key_value_pairs = True
        mock_args.structured_min_confidence = 0.7
        mock_args.structured_output_format = "combined"
        
        # Create configuration from arguments
        config = self.create_structured_output_config(
            extract_forms=getattr(mock_args, 'extract_forms', True),
            extract_tables=getattr(mock_args, 'extract_tables', True),
            extract_key_value_pairs=getattr(mock_args, 'extract_key_value_pairs', True),
            min_confidence=getattr(mock_args, 'structured_min_confidence', 0.5)
        )
        
        # Verify configuration
        self.assertTrue(config.extract_forms)
        self.assertTrue(config.extract_tables)
        self.assertTrue(config.extract_key_value_pairs)
        self.assertEqual(config.min_confidence, 0.7)
    
    def test_performance_with_structured_output(self):
        """Test performance impact of structured output processing."""
        performance_runner = PerformanceTestRunner(self.logger)
        
        # Test without structured output
        def process_without_structured():
            from olmocr.pipeline.document_builder import build_dolma_document
            from tests.testing_framework.fixtures import MockPageResult
            
            page_results = [MockPageResult(page_num=1, text=TestFixtures.create_sample_pdf_content())]
            return build_dolma_document("test.pdf", page_results)
        
        # Test with structured output
        def process_with_structured():
            config = self.create_structured_output_config()
            builder = self.create_document_builder(config)
            from tests.testing_framework.fixtures import MockPageResult
            
            page_results = [MockPageResult(page_num=1, text=TestFixtures.create_sample_pdf_content())]
            return builder.build_document("test.pdf", page_results)
        
        # Benchmark both approaches
        metrics_without = performance_runner.run_performance_test(
            "process_without_structured", process_without_structured, iterations=10
        )
        
        metrics_with = performance_runner.run_performance_test(
            "process_with_structured", process_with_structured, iterations=10
        )
        
        # Compare performance
        overhead = (metrics_with.duration - metrics_without.duration) / metrics_without.duration
        
        # Overhead should be reasonable (less than 50% for this test)
        self.assertLess(overhead, 0.5, f"Structured output overhead too high: {overhead:.1%}")
        
        # Both should complete successfully
        self.assertEqual(metrics_without.error_rate, 0.0)
        self.assertEqual(metrics_with.error_rate, 0.0)


class TestStructuredOutputPropertyBased(BaseOLMoCRTest):
    """Property-based tests for structured output functionality."""
    
    def setUp(self):
        """Set up property test fixtures."""
        super().setUp()
        self.property_generator = PropertyTestGenerator(seed=123)
        
        try:
            from olmocr.structured_output import (
                create_structured_output_config, create_structured_output_processor,
                DocumentType, FieldType
            )
            
            self.create_structured_output_config = create_structured_output_config
            self.create_structured_output_processor = create_structured_output_processor
            self.DocumentType = DocumentType
            self.FieldType = FieldType
            
        except ImportError:
            self.skipTest("Structured output module not available")
    
    def test_field_extraction_consistency(self):
        """Test that field extraction is consistent across runs."""
        config = self.create_structured_output_config()
        processor = self.create_structured_output_processor(config)
        
        # Generate test data
        for i in range(5):
            with self.subTest(iteration=i):
                # Generate key-value pairs
                key, value = self.property_generator.generate_key_value_pair()
                test_content = f"{key}: {value}"
                
                # Process multiple times
                results = []
                for _ in range(3):
                    structured_doc = processor.process_document(f"consistency_test_{i}", test_content)
                    results.append(len(structured_doc.fields))
                
                # Results should be consistent
                self.assertEqual(len(set(results)), 1, f"Inconsistent field extraction for '{test_content}'")
    
    def test_table_structure_preservation(self):
        """Test that table structure is preserved during extraction."""
        config = self.create_structured_output_config(extract_tables=True)
        processor = self.create_structured_output_processor(config)
        
        # Generate test tables
        for i in range(3):
            with self.subTest(iteration=i):
                headers, rows = self.property_generator.generate_table_data(
                    min_rows=2, max_rows=5, min_cols=2, max_cols=4
                )
                
                # Create table content
                table_content = "| " + " | ".join(headers) + " |\n"
                table_content += "|" + "|".join(["-" * (len(h) + 2) for h in headers]) + "|\n"
                
                for row in rows:
                    table_content += "| " + " | ".join(row) + " |\n"
                
                # Process table
                structured_doc = processor.process_document(f"table_test_{i}", table_content)
                
                # Verify table structure preservation
                if structured_doc.tables:
                    extracted_table = structured_doc.tables[0]
                    
                    # Number of columns should match
                    self.assertEqual(len(extracted_table.headers), len(headers))
                    
                    # All rows should have same number of columns as headers
                    for row in extracted_table.rows:
                        self.assertEqual(len(row), len(headers))
    
    def test_document_type_classification_stability(self):
        """Test that document type classification is stable."""
        config = self.create_structured_output_config()
        processor = self.create_structured_output_processor(config)
        
        # Test with different document types
        document_types = [self.DocumentType.FORM, self.DocumentType.INVOICE, self.DocumentType.TABLE]
        
        for doc_type in document_types:
            with self.subTest(document_type=doc_type):
                # Generate content for this document type
                content = self.property_generator.generate_document_content(doc_type)
                
                # Process multiple times
                classifications = []
                for _ in range(3):
                    structured_doc = processor.process_document(f"classification_test_{doc_type.value}", content)
                    classifications.append(structured_doc.document_type)
                
                # Classifications should be consistent
                self.assertEqual(len(set(classifications)), 1, 
                               f"Inconsistent classification for {doc_type.value} document")


class TestStructuredOutputErrorHandling(BaseOLMoCRTest):
    """Test error handling in structured output processing."""
    
    def setUp(self):
        """Set up error handling test fixtures."""
        super().setUp()
        
        try:
            from olmocr.structured_output import (
                create_structured_output_config, create_structured_output_processor
            )
            
            self.create_structured_output_config = create_structured_output_config
            self.create_structured_output_processor = create_structured_output_processor
            
        except ImportError:
            self.skipTest("Structured output module not available")
    
    def test_empty_content_handling(self):
        """Test handling of empty or whitespace-only content."""
        config = self.create_structured_output_config()
        processor = self.create_structured_output_processor(config)
        
        # Test with empty content
        empty_doc = processor.process_document("empty_test", "")
        self.assertIsNotNone(empty_doc)
        self.assertEqual(len(empty_doc.fields), 0)
        self.assertEqual(len(empty_doc.tables), 0)
        
        # Test with whitespace-only content
        whitespace_doc = processor.process_document("whitespace_test", "   \n\t  \n  ")
        self.assertIsNotNone(whitespace_doc)
        self.assertEqual(len(whitespace_doc.fields), 0)
        self.assertEqual(len(whitespace_doc.tables), 0)
    
    def test_malformed_table_handling(self):
        """Test handling of malformed table content."""
        config = self.create_structured_output_config(extract_tables=True)
        processor = self.create_structured_output_processor(config)
        
        # Test with malformed table
        malformed_table = """
        | Header1 | Header2 |
        |---------|
        | Row1Col1 | Row1Col2 | Row1Col3 |  # Too many columns
        | Row2Col1 |  # Too few columns
        """
        
        # Should not crash, but may not extract the malformed table
        structured_doc = processor.process_document("malformed_table_test", malformed_table)
        self.assertIsNotNone(structured_doc)
        # The exact behavior depends on implementation - it might extract 0 tables or try to fix the table
    
    def test_invalid_configuration_handling(self):
        """Test handling of invalid configuration."""
        # Test with invalid confidence threshold
        config = self.create_structured_output_config(min_confidence=1.5)  # Invalid: > 1.0
        
        # Should handle gracefully (clamp to valid range or use default)
        processor = self.create_structured_output_processor(config)
        self.assertIsNotNone(processor)
        
        # Test processing still works
        test_content = "Name: Test User"
        structured_doc = processor.process_document("invalid_config_test", test_content)
        self.assertIsNotNone(structured_doc)


if __name__ == "__main__":
    unittest.main()
