"""
Validation tests for the enhanced testing framework.

This module validates that the enhanced testing infrastructure works correctly
and provides the expected functionality.
"""

import unittest
from tests.testing_framework import (
    BaseOLMoCRTest, TestFixtures, MockPageResult, PropertyTestGenerator,
    PerformanceTestRunner, create_test_config
)


class TestTestingFrameworkValidation(BaseOLMoCRTest):
    """Validate the enhanced testing framework functionality."""
    
    def test_base_test_class_functionality(self):
        """Test that the base test class provides expected functionality."""
        # Test temporary directory creation
        self.assertIsNotNone(self.temp_dir)
        self.assertTrue(self.temp_dir.startswith('/tmp/'))
        
        # Test workspace creation
        self.assertIsNotNone(self.test_workspace)
        self.assertIsNotNone(self.test_output)
        
        # Test context creation
        self.assertIsNotNone(self.test_context)
        self.assertIn('test_base_test_class_functionality', self.test_context.correlation_id)
    
    def test_file_operations(self):
        """Test file operation utilities."""
        # Create test file
        test_content = "This is test content for validation"
        test_file = self.create_test_file("validation.txt", test_content)
        
        # Verify file operations
        self.assert_file_exists(test_file)
        self.assert_file_contains(test_file, "test content")
        self.assert_file_contains(test_file, "validation")
    
    def test_mock_configuration(self):
        """Test mock configuration creation."""
        config = self.create_mock_config(
            workers=4,
            timeout=60.0,
            custom_setting="test_value"
        )
        
        self.assertEqual(config['workers'], 4)
        self.assertEqual(config['timeout'], 60.0)
        self.assertEqual(config['custom_setting'], "test_value")
        self.assertTrue(config['debug'])


class TestFixturesValidation(BaseOLMoCRTest):
    """Validate test fixtures functionality."""
    
    def test_sample_content_generation(self):
        """Test sample content generation."""
        # Test form content
        form_content = TestFixtures.create_sample_form_content()
        self.assertIn("APPLICATION FORM", form_content)
        self.assertIn("First Name", form_content)
        self.assertIn("Email Address", form_content)
        
        # Test invoice content
        invoice_content = TestFixtures.create_sample_invoice_content()
        self.assertIn("INVOICE", invoice_content)
        self.assertIn("Total Amount Due", invoice_content)
        
        # Test table content
        table_content = TestFixtures.create_sample_table_content()
        self.assertIn("QUARTERLY SALES REPORT", table_content)
        self.assertIn("Region", table_content)
    
    def test_mock_page_result(self):
        """Test mock page result functionality."""
        test_content = "Mock page content for testing"
        page_result = MockPageResult(page_num=1, text=test_content)
        
        self.assertEqual(page_result.page_num, 1)
        self.assertEqual(page_result.response.natural_text, test_content)
        self.assertEqual(page_result.input_tokens, 100)
        self.assertEqual(page_result.output_tokens, 50)
    
    def test_configuration_creation(self):
        """Test configuration creation utilities."""
        config = create_test_config(
            workers=2,
            timeout=30.0,
            custom_option=True
        )
        
        self.assertEqual(config['workers'], 2)
        self.assertEqual(config['timeout'], 30.0)
        self.assertEqual(config['custom_option'], True)
        self.assertTrue(config['debug'])


class TestPropertyTestingValidation(BaseOLMoCRTest):
    """Validate property-based testing functionality."""
    
    def test_property_test_generator(self):
        """Test property test generator functionality."""
        generator = PropertyTestGenerator(seed=42)
        
        # Test text generation
        text1 = generator.generate_text(min_length=10, max_length=20)
        text2 = generator.generate_text(min_length=10, max_length=20)
        
        self.assertGreaterEqual(len(text1), 10)
        self.assertLessEqual(len(text1), 20)
        self.assertGreaterEqual(len(text2), 10)
        self.assertLessEqual(len(text2), 20)
        
        # Test email generation
        email = generator.generate_email()
        self.assertIn("@", email)
        self.assertTrue(email.endswith((".com", ".org", ".net", ".edu")))
        
        # Test phone generation
        phone = generator.generate_phone()
        self.assertGreater(len(phone), 5)
        
        # Test currency generation
        currency = generator.generate_currency()
        self.assertTrue(currency.startswith(("$", "€", "£", "¥")))
    
    def test_document_content_generation(self):
        """Test document content generation."""
        generator = PropertyTestGenerator(seed=123)
        
        # Test form generation
        form_content = generator.generate_document_content("form")
        self.assertIn("APPLICATION FORM", form_content)
        
        # Test invoice generation
        invoice_content = generator.generate_document_content("invoice")
        self.assertIn("INVOICE", invoice_content)
        
        # Test table generation
        table_content = generator.generate_document_content("table")
        self.assertIn("|", table_content)  # Should contain table formatting


class TestPerformanceTestingValidation(BaseOLMoCRTest):
    """Validate performance testing functionality."""
    
    def test_performance_test_runner(self):
        """Test performance test runner functionality."""
        runner = PerformanceTestRunner(self.logger)
        
        def test_function():
            """Simple test function for performance testing."""
            return sum(range(100))
        
        # Run performance test
        metrics = runner.run_performance_test(
            "test_function_performance",
            test_function,
            iterations=5,
            warmup_iterations=1
        )
        
        # Validate metrics
        self.assertEqual(metrics.test_name, "test_function_performance")
        self.assertEqual(metrics.iterations, 5)
        self.assertGreaterEqual(metrics.duration, 0.0)
        self.assertGreaterEqual(metrics.throughput, 0.0)
        self.assertEqual(metrics.error_rate, 0.0)
    
    def test_performance_with_errors(self):
        """Test performance testing with errors."""
        runner = PerformanceTestRunner(self.logger)
        
        def failing_function():
            """Function that sometimes fails."""
            import random
            if random.random() < 0.3:  # 30% failure rate
                raise ValueError("Simulated failure")
            return "success"
        
        # Run performance test with failures
        metrics = runner.run_performance_test(
            "failing_function_performance",
            failing_function,
            iterations=10,
            warmup_iterations=1
        )
        
        # Validate metrics
        self.assertEqual(metrics.test_name, "failing_function_performance")
        self.assertEqual(metrics.iterations, 10)
        self.assertGreaterEqual(metrics.duration, 0.0)
        # Error rate should be > 0 due to simulated failures
        self.assertGreaterEqual(metrics.error_rate, 0.0)


class TestIntegrationValidation(BaseOLMoCRTest):
    """Validate integration testing functionality."""
    
    def test_testing_framework_integration(self):
        """Test that all testing framework components work together."""
        # Use fixtures
        content = TestFixtures.create_sample_form_content()
        
        # Create mock page result
        page_result = MockPageResult(1, content)
        
        # Use property testing
        generator = PropertyTestGenerator(seed=789)
        random_text = generator.generate_text(20, 50)
        
        # Use performance testing
        runner = PerformanceTestRunner(self.logger)
        
        def process_content(text):
            """Simple content processing function."""
            return text.upper()
        
        metrics = runner.run_performance_test(
            "content_processing",
            process_content,
            3,  # iterations
            1,  # warmup_iterations
            random_text
        )
        
        # Create test file
        output_file = self.create_test_file("integration_output.txt", 
                                          f"Processed: {process_content(content)}")
        
        # Validate integration
        self.assert_file_exists(output_file)
        self.assert_file_contains(output_file, "APPLICATION FORM")
        self.assertEqual(page_result.page_num, 1)
        self.assertGreater(len(random_text), 15)
        self.assertEqual(metrics.iterations, 3)
        self.assertEqual(metrics.error_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
