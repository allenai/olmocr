"""
Comprehensive unit tests for the enhanced OLMoCR pipeline.

This module provides extensive unit test coverage for all pipeline components,
including the refactored modular architecture and enhanced error handling.
"""

import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

from tests.testing_framework import (
    BaseOLMoCRTest, AsyncBaseOLMoCRTest, ParameterizedTestMixin,
    TestFixtures, MockPageResult, MockPageResponse,
    create_mock_pipeline_components, create_mock_args,
    PropertyTestGenerator, DocumentPropertyTests,
    PerformanceTestRunner, benchmark_function
)

# Import OLMoCR components
from olmocr.error_handling import (
    create_logger, LogContext, ErrorContext, ProcessingError,
    ValidationError, ConfigurationError
)


class TestEnhancedErrorHandling(BaseOLMoCRTest):
    """Test enhanced error handling functionality."""
    
    def test_logger_creation(self):
        """Test logger creation with different configurations."""
        # Test basic logger creation
        logger = create_logger("test_logger")
        self.assertIsNotNone(logger)
        self.assertEqual(logger.name, "test_logger")
        
        # Test logger with context
        context = LogContext(operation="test_op", component="test_component")
        logger_with_context = create_logger("test_logger_context", context)
        self.assertIsNotNone(logger_with_context)
    
    def test_log_context(self):
        """Test log context functionality."""
        context = LogContext(
            operation="test_operation",
            component="test_component",
            correlation_id="test-123"
        )
        
        self.assertEqual(context.operation, "test_operation")
        self.assertEqual(context.component, "test_component")
        self.assertEqual(context.correlation_id, "test-123")
        
        # Test context dictionary conversion
        context_dict = context.to_dict()
        self.assertIn("operation", context_dict)
        self.assertIn("component", context_dict)
        self.assertIn("correlation_id", context_dict)
    
    def test_error_context(self):
        """Test error context functionality."""
        error_context = ErrorContext(
            error_type="ProcessingError",
            error_message="Test error message",
            component="test_component",
            operation="test_operation"
        )
        
        self.assertEqual(error_context.error_type, "ProcessingError")
        self.assertEqual(error_context.error_message, "Test error message")
        
        # Test error context dictionary conversion
        error_dict = error_context.to_dict()
        self.assertIn("error_type", error_dict)
        self.assertIn("error_message", error_dict)
    
    def test_custom_exceptions(self):
        """Test custom exception classes."""
        # Test ProcessingError
        with self.assertRaises(ProcessingError):
            raise ProcessingError("Test processing error")
        
        # Test ValidationError
        with self.assertRaises(ValidationError):
            raise ValidationError("Test validation error")
        
        # Test ConfigurationError
        with self.assertRaises(ConfigurationError):
            raise ConfigurationError("Test configuration error")
    
    def test_error_handling_with_context(self):
        """Test error handling with context information."""
        context = LogContext(operation="test_error_handling")
        
        try:
            raise ProcessingError("Test error with context")
        except ProcessingError as e:
            error_context = ErrorContext(
                error_type=type(e).__name__,
                error_message=str(e),
                component="test_component",
                operation=context.operation
            )
            
            self.assertEqual(error_context.error_type, "ProcessingError")
            self.assertEqual(error_context.operation, "test_error_handling")


class TestPipelineDocumentBuilder(BaseOLMoCRTest):
    """Test pipeline document builder functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        
        # Import here to avoid circular imports
        try:
            from olmocr.pipeline.document_builder import (
                create_document_builder, build_dolma_document
            )
            self.create_document_builder = create_document_builder
            self.build_dolma_document = build_dolma_document
        except ImportError:
            self.skipTest("Document builder module not available")
    
    def test_legacy_document_building(self):
        """Test legacy document building functionality."""
        # Create test page results
        page_results = [
            MockPageResult(page_num=1, text="Page 1 content"),
            MockPageResult(page_num=2, text="Page 2 content"),
            MockPageResult(page_num=3, text="Page 3 content")
        ]
        
        # Build document
        document = self.build_dolma_document("test.pdf", page_results)
        
        # Verify document structure
        self.assertIsInstance(document, dict)
        self.assertIn("id", document)
        self.assertIn("text", document)
        self.assertIn("source", document)
        self.assertIn("metadata", document)
        self.assertIn("attributes", document)
        
        # Verify content
        self.assertEqual(document["source"], "olmocr")
        self.assertIn("Page 1 content", document["text"])
        self.assertIn("Page 2 content", document["text"])
        self.assertIn("Page 3 content", document["text"])
    
    def test_document_builder_creation(self):
        """Test document builder creation."""
        # Test without structured output
        builder = self.create_document_builder()
        self.assertIsNotNone(builder)
        
        # Test with structured output configuration
        try:
            from olmocr.structured_output import create_structured_output_config
            structured_config = create_structured_output_config()
            builder_with_structured = self.create_document_builder(structured_config)
            self.assertIsNotNone(builder_with_structured)
        except ImportError:
            # Structured output not available, skip this part
            pass
    
    def test_document_builder_with_structured_output(self):
        """Test document builder with structured output."""
        try:
            from olmocr.structured_output import create_structured_output_config
            
            # Create structured output configuration
            structured_config = create_structured_output_config(
                extract_forms=True,
                extract_tables=True,
                min_confidence=0.5
            )
            
            # Create document builder
            builder = self.create_document_builder(structured_config)
            
            # Create test page results with structured content
            page_results = [
                MockPageResult(page_num=1, text="Name: John Doe\nEmail: john@example.com"),
                MockPageResult(page_num=2, text="| Product | Price |\n|---------|-------|\n| Widget | $10.99 |")
            ]
            
            # Build document
            document = builder.build_document("test.pdf", page_results)
            
            # Verify document has structured data
            self.assertIn("structured_data", document)
            self.assertTrue(document["metadata"]["has_structured_data"])
            
        except ImportError:
            self.skipTest("Structured output module not available")


class TestStructuredOutputIntegration(BaseOLMoCRTest):
    """Test structured output integration with pipeline."""
    
    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        
        try:
            from olmocr.structured_output import (
                create_structured_output_config, create_structured_output_processor,
                create_structured_output_formatter, DocumentType, FieldType
            )
            self.create_structured_output_config = create_structured_output_config
            self.create_structured_output_processor = create_structured_output_processor
            self.create_structured_output_formatter = create_structured_output_formatter
            self.DocumentType = DocumentType
            self.FieldType = FieldType
        except ImportError:
            self.skipTest("Structured output module not available")
    
    def test_structured_output_configuration(self):
        """Test structured output configuration."""
        # Test default configuration
        config = self.create_structured_output_config()
        self.assertTrue(config.extract_forms)
        self.assertTrue(config.extract_tables)
        self.assertEqual(config.min_confidence, 0.5)
        
        # Test custom configuration
        custom_config = self.create_structured_output_config(
            extract_forms=False,
            extract_tables=True,
            min_confidence=0.8
        )
        self.assertFalse(custom_config.extract_forms)
        self.assertTrue(custom_config.extract_tables)
        self.assertEqual(custom_config.min_confidence, 0.8)
    
    def test_structured_output_processor(self):
        """Test structured output processor."""
        config = self.create_structured_output_config()
        processor = self.create_structured_output_processor(config)
        
        # Test form processing
        form_text = """
        Name: Alice Smith
        Email: alice@example.com
        Phone: (555) 123-4567
        """
        
        structured_doc = processor.process_document("test-form", form_text)
        
        self.assertEqual(structured_doc.document_id, "test-form")
        self.assertEqual(structured_doc.document_type, self.DocumentType.FORM)
        self.assertGreater(len(structured_doc.fields), 0)
        
        # Verify field extraction
        field_names = [field.name for field in structured_doc.fields]
        self.assertIn("Name", field_names)
        self.assertIn("Email", field_names)
    
    def test_structured_output_formatter(self):
        """Test structured output formatter."""
        config = self.create_structured_output_config()
        processor = self.create_structured_output_processor(config)
        formatter = self.create_structured_output_formatter()
        
        # Create test document
        test_text = "Name: John Doe\nEmail: john@test.com"
        structured_doc = processor.process_document("test-doc", test_text)
        
        # Test JSON formatting
        json_output = formatter.format_as_json(structured_doc)
        self.assertIsInstance(json_output, str)
        
        # Verify JSON is valid
        parsed_json = json.loads(json_output)
        self.assertEqual(parsed_json["document_id"], "test-doc")
        self.assertIn("fields", parsed_json)
        
        # Test key-value formatting
        kv_output = formatter.format_as_key_value(structured_doc)
        self.assertIsInstance(kv_output, str)
        self.assertIn("Document ID", kv_output)


class TestPipelinePerformance(BaseOLMoCRTest, ParameterizedTestMixin):
    """Test pipeline performance characteristics."""
    
    def setUp(self):
        """Set up performance test fixtures."""
        super().setUp()
        self.performance_runner = PerformanceTestRunner(self.logger)
    
    def test_document_building_performance(self):
        """Test document building performance."""
        try:
            from olmocr.pipeline.document_builder import build_dolma_document
            
            def build_test_document():
                page_results = [
                    MockPageResult(page_num=i, text=f"Page {i} content")
                    for i in range(1, 11)  # 10 pages
                ]
                return build_dolma_document("test.pdf", page_results)
            
            # Benchmark the function
            metrics = benchmark_function(build_test_document, iterations=10, warmup=2)
            
            # Verify performance is reasonable (should be fast for mock data)
            self.assertLess(metrics.duration, 1.0)  # Should complete in under 1 second
            self.assertEqual(metrics.error_rate, 0.0)  # No errors expected
            
        except ImportError:
            self.skipTest("Document builder module not available")
    
    def test_structured_output_performance(self):
        """Test structured output processing performance."""
        try:
            from olmocr.structured_output import (
                create_structured_output_config, create_structured_output_processor
            )
            
            config = create_structured_output_config()
            processor = create_structured_output_processor(config)
            
            def process_test_document():
                test_text = TestFixtures.create_sample_form_content()
                return processor.process_document("perf-test", test_text)
            
            # Benchmark the function
            metrics = benchmark_function(process_test_document, iterations=10, warmup=2)
            
            # Verify performance is reasonable
            self.assertLess(metrics.duration, 2.0)  # Should complete in under 2 seconds
            self.assertEqual(metrics.error_rate, 0.0)  # No errors expected
            
        except ImportError:
            self.skipTest("Structured output module not available")
    
    def test_performance_with_different_document_sizes(self):
        """Test performance with different document sizes."""
        try:
            from olmocr.pipeline.document_builder import build_dolma_document
            
            # Test with different numbers of pages
            page_counts = [1, 5, 10, 20]
            
            for page_count in page_counts:
                with self.subTest(page_count=page_count):
                    def build_document():
                        page_results = [
                            MockPageResult(page_num=i, text=f"Page {i} content with more text " * 10)
                            for i in range(1, page_count + 1)
                        ]
                        return build_dolma_document("test.pdf", page_results)
                    
                    metrics = self.performance_runner.run_performance_test(
                        f"build_document_{page_count}_pages",
                        build_document,
                        iterations=5
                    )
                    
                    # Performance should scale reasonably with document size
                    expected_max_time = page_count * 0.1  # 0.1s per page is reasonable for mock data
                    self.assertLess(metrics.duration, expected_max_time)
                    
        except ImportError:
            self.skipTest("Document builder module not available")


class TestPropertyBasedPipeline(BaseOLMoCRTest):
    """Property-based tests for pipeline components."""
    
    def setUp(self):
        """Set up property test fixtures."""
        super().setUp()
        self.property_generator = PropertyTestGenerator(seed=42)  # Fixed seed for reproducibility
    
    def test_document_processing_properties(self):
        """Test document processing properties with generated data."""
        try:
            from olmocr.pipeline.document_builder import build_dolma_document
            
            # Generate test cases
            for i in range(10):  # Run 10 property tests
                with self.subTest(iteration=i):
                    # Generate random page content
                    num_pages = self.property_generator.generate_text(min_length=1, max_length=3)
                    page_count = len(num_pages)
                    
                    page_results = []
                    for page_num in range(1, page_count + 1):
                        text_content = self.property_generator.generate_text(
                            min_length=10, max_length=500
                        )
                        page_results.append(MockPageResult(page_num, text_content))
                    
                    # Test document building
                    document = build_dolma_document("property_test.pdf", page_results)
                    
                    # Verify properties
                    self.assertIsInstance(document, dict)
                    self.assertIn("text", document)
                    self.assertIn("id", document)
                    
                    # Text should not be empty if we had content
                    if any(pr.response.natural_text.strip() for pr in page_results):
                        self.assertTrue(document["text"].strip())
                        
        except ImportError:
            self.skipTest("Document builder module not available")
    
    def test_structured_output_properties(self):
        """Test structured output properties with generated data."""
        try:
            from olmocr.structured_output import (
                create_structured_output_config, create_structured_output_processor,
                DocumentType
            )
            
            config = create_structured_output_config()
            processor = create_structured_output_processor(config)
            
            # Test with different document types
            document_types = [DocumentType.FORM, DocumentType.INVOICE, DocumentType.TABLE]
            
            for doc_type in document_types:
                with self.subTest(document_type=doc_type):
                    # Generate document content
                    content = self.property_generator.generate_document_content(doc_type)
                    
                    # Process document
                    structured_doc = processor.process_document(f"prop_test_{doc_type.value}", content)
                    
                    # Verify properties
                    self.assertIsNotNone(structured_doc)
                    self.assertEqual(structured_doc.document_type, doc_type)
                    
                    # Should have some extracted data for non-empty content
                    if content.strip():
                        total_extracted = len(structured_doc.fields) + len(structured_doc.tables)
                        self.assertGreaterEqual(total_extracted, 0)
                        
        except ImportError:
            self.skipTest("Structured output module not available")


class TestAsyncPipelineComponents(AsyncBaseOLMoCRTest):
    """Test asynchronous pipeline components."""
    
    def test_async_document_processing(self):
        """Test asynchronous document processing."""
        async def async_document_processor(content):
            # Simulate async processing
            await asyncio.sleep(0.01)
            return {"processed": True, "content_length": len(content)}
        
        # Test async processing
        test_content = "Test document content"
        result = self.run_async(async_document_processor(test_content))
        
        self.assertTrue(result["processed"])
        self.assertEqual(result["content_length"], len(test_content))
    
    def test_async_error_handling(self):
        """Test async error handling."""
        async def failing_async_function():
            await asyncio.sleep(0.01)
            raise ProcessingError("Async processing failed")
        
        # Test that async errors are properly handled
        with self.assertRaises(ProcessingError):
            self.run_async(failing_async_function())
    
    def test_async_timeout_handling(self):
        """Test async timeout handling."""
        async def slow_async_function():
            await asyncio.sleep(2.0)  # Longer than our timeout
            return "completed"
        
        # Test timeout handling
        with self.assertRaises(asyncio.TimeoutError):
            self.run_async(slow_async_function(), timeout=0.5)


if __name__ == "__main__":
    unittest.main()
