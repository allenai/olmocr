"""
Tests for enhanced error handling system.

This module tests the comprehensive error handling, structured logging,
and recovery mechanisms implemented for the OLMoCR pipeline.
"""

import asyncio
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

import pytest

from olmocr.error_handling import (
    StructuredLogger, LogContext, create_logger,
    ErrorCategory, ErrorSeverity, OLMoCRError, NetworkError, ProcessingError,
    RetryConfig, BackoffType, create_recovery_manager,
    ErrorReport, create_error_aggregator,
    create_performance_monitor
)


class TestStructuredLogging(unittest.TestCase):
    """Test structured logging functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.logger = create_logger("test_logger", structured=True)
    
    def test_logger_creation(self):
        """Test logger creation."""
        self.assertIsInstance(self.logger, StructuredLogger)
        self.assertIsNotNone(self.logger.logger)
    
    def test_log_context(self):
        """Test log context functionality."""
        context = LogContext(
            correlation_id="test-123",
            document_id="doc-456",
            page_number=1,
            processing_stage="test_stage"
        )
        
        self.assertEqual(context.correlation_id, "test-123")
        self.assertEqual(context.document_id, "doc-456")
        self.assertEqual(context.page_number, 1)
        self.assertEqual(context.processing_stage, "test_stage")
    
    def test_context_manager(self):
        """Test context manager functionality."""
        with self.logger.context(document_id="test-doc", page_number=1):
            # Context should be applied to all log messages in this block
            self.logger.info("Test message")
    
    def test_operation_timing(self):
        """Test operation timing context manager."""
        with self.logger.operation("test_operation", document_id="test-doc"):
            # Simulate some work
            import time
            time.sleep(0.1)


class TestErrorCategories(unittest.TestCase):
    """Test error categorization and custom exceptions."""
    
    def test_olmocr_error_creation(self):
        """Test OLMoCR error creation."""
        error = OLMoCRError(
            "Test error",
            ErrorCategory.PROCESSING,
            ErrorSeverity.MEDIUM
        )
        
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.category, ErrorCategory.PROCESSING)
        self.assertEqual(error.severity, ErrorSeverity.MEDIUM)
        self.assertTrue(error.recoverable)
    
    def test_network_error(self):
        """Test network error specifics."""
        error = NetworkError("Connection failed")
        
        self.assertEqual(error.category, ErrorCategory.NETWORK)
        self.assertEqual(error.severity, ErrorSeverity.HIGH)
        self.assertTrue(error.recoverable)
        self.assertIsNotNone(error.retry_after)
    
    def test_processing_error(self):
        """Test processing error specifics."""
        error = ProcessingError("Processing failed")
        
        self.assertEqual(error.category, ErrorCategory.PROCESSING)
        self.assertEqual(error.severity, ErrorSeverity.MEDIUM)
        self.assertTrue(error.recoverable)
    
    def test_error_to_dict(self):
        """Test error serialization."""
        error = NetworkError("Test error")
        error_dict = error.to_dict()
        
        self.assertIn('type', error_dict)
        self.assertIn('message', error_dict)
        self.assertIn('category', error_dict)
        self.assertIn('severity', error_dict)


class TestRecoveryStrategies(unittest.TestCase):
    """Test retry and recovery strategies."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.logger = create_logger("test_recovery")
        self.recovery_manager = create_recovery_manager(
            max_attempts=3,
            base_delay=0.1,
            logger=self.logger
        )
    
    async def test_successful_operation(self):
        """Test successful operation without retries."""
        async def successful_operation():
            return "success"
        
        result = await self.recovery_manager.execute_with_retry(
            successful_operation,
            operation_name="test_success"
        )
        
        self.assertEqual(result, "success")
    
    async def test_retry_on_failure(self):
        """Test retry behavior on failures."""
        call_count = 0
        
        async def failing_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise NetworkError("Temporary failure")
            return "success"
        
        result = await self.recovery_manager.execute_with_retry(
            failing_operation,
            operation_name="test_retry"
        )
        
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)
    
    async def test_max_retries_exceeded(self):
        """Test behavior when max retries are exceeded."""
        async def always_failing_operation():
            raise NetworkError("Permanent failure")
        
        with self.assertRaises(NetworkError):
            await self.recovery_manager.execute_with_retry(
                always_failing_operation,
                operation_name="test_max_retries"
            )
    
    async def test_non_recoverable_error(self):
        """Test that non-recoverable errors are not retried."""
        call_count = 0
        
        async def non_recoverable_operation():
            nonlocal call_count
            call_count += 1
            raise OLMoCRError(
                "Non-recoverable error",
                ErrorCategory.VALIDATION,
                recoverable=False
            )
        
        with self.assertRaises(OLMoCRError):
            await self.recovery_manager.execute_with_retry(
                non_recoverable_operation,
                operation_name="test_non_recoverable"
            )
        
        self.assertEqual(call_count, 1)  # Should not retry


class TestErrorReporting(unittest.TestCase):
    """Test error reporting and aggregation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.logger = create_logger("test_reporting")
        self.aggregator = create_error_aggregator(self.logger)
    
    def test_error_report_creation(self):
        """Test error report creation."""
        error = NetworkError("Test error")
        report = ErrorReport.from_error(error)
        
        self.assertEqual(report.error_type, "NetworkError")
        self.assertEqual(report.message, "Test error")
        self.assertEqual(report.category, ErrorCategory.NETWORK)
        self.assertEqual(report.severity, ErrorSeverity.HIGH)
    
    def test_error_aggregation(self):
        """Test error aggregation."""
        # Record multiple errors
        errors = [
            NetworkError("Network error 1"),
            NetworkError("Network error 2"),
            ProcessingError("Processing error 1"),
        ]
        
        for error in errors:
            self.aggregator.record_error(error)
        
        summary = self.aggregator.get_summary()
        
        self.assertEqual(summary.total_errors, 3)
        self.assertEqual(summary.errors_by_category[ErrorCategory.NETWORK], 2)
        self.assertEqual(summary.errors_by_category[ErrorCategory.PROCESSING], 1)
    
    def test_error_patterns(self):
        """Test error pattern analysis."""
        # Record errors with patterns
        for i in range(5):
            self.aggregator.record_error(NetworkError(f"Network error {i}"))
        
        for i in range(3):
            self.aggregator.record_error(ProcessingError(f"Processing error {i}"))
        
        patterns = self.aggregator.get_error_patterns()
        
        self.assertIn('most_common_errors', patterns)
        self.assertIn('error_rate_by_hour', patterns)
    
    def test_report_generation(self):
        """Test comprehensive report generation."""
        # Record some errors
        self.aggregator.record_error(NetworkError("Test error"))
        
        report = self.aggregator.generate_report(include_diagnostics=True)
        
        self.assertIn('summary', report)
        self.assertIn('patterns', report)
        self.assertIn('recent_errors', report)
        self.assertIn('diagnostics', report)
    
    def test_report_export(self):
        """Test report export to file."""
        self.aggregator.record_error(NetworkError("Test error"))
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            self.aggregator.export_report(f.name)
            
            # Verify file was created and contains valid JSON
            with open(f.name, 'r') as read_f:
                report_data = json.load(read_f)
                self.assertIn('summary', report_data)


class TestPerformanceMonitoring(unittest.TestCase):
    """Test performance monitoring functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.logger = create_logger("test_performance")
        self.monitor = create_performance_monitor(self.logger)
    
    def test_operation_timing(self):
        """Test operation timing."""
        with self.monitor.time_operation("test_operation"):
            import time
            time.sleep(0.1)
        
        stats = self.monitor.get_stats("test_operation")
        self.assertIn("test_operation", stats)
        
        operation_stats = stats["test_operation"]
        self.assertEqual(operation_stats.total_count, 1)
        self.assertEqual(operation_stats.success_count, 1)
        self.assertGreater(operation_stats.average_duration, 0.1)
    
    def test_failed_operation_timing(self):
        """Test timing of failed operations."""
        try:
            with self.monitor.time_operation("failing_operation"):
                raise ValueError("Test failure")
        except ValueError:
            pass
        
        stats = self.monitor.get_stats("failing_operation")
        operation_stats = stats["failing_operation"]
        
        self.assertEqual(operation_stats.total_count, 1)
        self.assertEqual(operation_stats.success_count, 0)
        self.assertEqual(operation_stats.failure_count, 1)
    
    def test_custom_metrics(self):
        """Test custom metric recording."""
        self.monitor.record_custom_metric(
            "custom_operation",
            duration=0.5,
            success=True
        )
        
        stats = self.monitor.get_stats("custom_operation")
        operation_stats = stats["custom_operation"]
        
        self.assertEqual(operation_stats.total_count, 1)
        self.assertEqual(operation_stats.success_count, 1)
        self.assertAlmostEqual(operation_stats.average_duration, 0.5, places=2)
    
    def test_performance_summary(self):
        """Test performance summary generation."""
        # Record some operations
        with self.monitor.time_operation("op1"):
            pass
        
        with self.monitor.time_operation("op2"):
            pass
        
        summary = self.monitor.get_summary()
        
        self.assertEqual(summary['total_operations'], 2)
        self.assertEqual(summary['successful_operations'], 2)
        self.assertEqual(summary['overall_success_rate'], 1.0)


class TestAsyncErrorHandling(unittest.TestCase):
    """Test async error handling functionality."""
    
    def test_async_operations(self):
        """Run async error handling tests."""
        async def run_tests():
            # Test recovery manager
            logger = create_logger("async_test")
            recovery_manager = create_recovery_manager(logger=logger)
            
            # Test successful async operation
            async def async_success():
                return "async_result"
            
            result = await recovery_manager.execute_with_retry(
                async_success,
                operation_name="async_test"
            )
            assert result == "async_result"
            
            # Test async operation with retries
            call_count = 0
            async def async_retry():
                nonlocal call_count
                call_count += 1
                if call_count < 2:
                    raise NetworkError("Temporary async failure")
                return "async_success"
            
            result = await recovery_manager.execute_with_retry(
                async_retry,
                operation_name="async_retry_test"
            )
            assert result == "async_success"
            assert call_count == 2
        
        # Run the async tests
        asyncio.run(run_tests())


if __name__ == "__main__":
    unittest.main()
