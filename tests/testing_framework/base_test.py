"""
Base test classes for OLMoCR testing infrastructure.

This module provides base test classes that include common setup, teardown,
and utility methods for all OLMoCR tests.
"""

import os
import tempfile
import unittest
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

try:
    from olmocr.error_handling import create_logger, LogContext
except ImportError:
    # Fallback logger
    import logging
    def create_logger(name):
        return logging.getLogger(name)
    
    class LogContext:
        def __init__(self, correlation_id="", document_id=None, page_number=None,
                     processing_stage=None, worker_id=None):
            self.correlation_id = correlation_id
            self.document_id = document_id
            self.page_number = page_number
            self.processing_stage = processing_stage
            self.worker_id = worker_id

        def to_dict(self):
            return {k: v for k, v in self.__dict__.items() if v is not None}


class BaseOLMoCRTest(unittest.TestCase):
    """
    Base test class for all OLMoCR tests.
    
    Provides common setup, teardown, and utility methods for testing
    OLMoCR components with proper isolation and cleanup.
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up class-level test fixtures."""
        cls.logger = create_logger(f"test.{cls.__name__}")
        cls.test_data_dir = os.path.join(os.path.dirname(__file__), "..", "test_data")
        
        # Create test data directory if it doesn't exist
        os.makedirs(cls.test_data_dir, exist_ok=True)
    
    def setUp(self):
        """Set up test fixtures for each test method."""
        # Create temporary directory for test isolation
        self.temp_dir = tempfile.mkdtemp(prefix=f"olmocr_test_{self.__class__.__name__}_")
        self.test_workspace = os.path.join(self.temp_dir, "workspace")
        self.test_output = os.path.join(self.temp_dir, "output")
        
        # Create test directories
        os.makedirs(self.test_workspace, exist_ok=True)
        os.makedirs(self.test_output, exist_ok=True)
        
        # Set up test context
        self.test_context = LogContext(
            correlation_id=f"test_{self._testMethodName}_{int(time.time())}",
            processing_stage=f"test_{self._testMethodName}"
        )
        
        # Initialize test state
        self.test_start_time = time.time()
        self.test_artifacts = []
        self.mock_objects = []
    
    def tearDown(self):
        """Clean up test fixtures after each test method."""
        # Calculate test duration
        if self.test_start_time:
            duration = time.time() - self.test_start_time
            self.logger.info(f"Test {self._testMethodName} completed in {duration:.3f}s")
        
        # Clean up mock objects
        for mock_obj in self.mock_objects:
            if hasattr(mock_obj, 'stop'):
                mock_obj.stop()
        
        # Clean up temporary files
        import shutil
        try:
            shutil.rmtree(self.temp_dir)
        except Exception as e:
            self.logger.warning(f"Failed to clean up temp directory {self.temp_dir}: {e}")
    
    def create_test_file(self, filename: str, content: str = "test content") -> str:
        """
        Create a test file in the temporary directory.
        
        Args:
            filename: Name of the file to create
            content: Content to write to the file
            
        Returns:
            Full path to the created file
        """
        file_path = os.path.join(self.temp_dir, filename)
        
        # Create directory if needed
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w') as f:
            f.write(content)
        
        self.test_artifacts.append(file_path)
        return file_path
    
    def assert_file_exists(self, file_path: str, message: str = None):
        """Assert that a file exists."""
        if not os.path.exists(file_path):
            msg = message or f"File does not exist: {file_path}"
            self.fail(msg)
    
    def assert_file_contains(self, file_path: str, expected_content: str, message: str = None):
        """Assert that a file contains specific content."""
        self.assert_file_exists(file_path)
        
        with open(file_path, 'r') as f:
            content = f.read()
        
        if expected_content not in content:
            msg = message or f"File {file_path} does not contain expected content: {expected_content}"
            self.fail(msg)
    
    def create_mock_config(self, **kwargs) -> Dict[str, Any]:
        """Create a mock configuration for testing."""
        default_config = {
            'workspace': self.test_workspace,
            'output_dir': self.test_output,
            'workers': 1,
            'max_retries': 3,
            'timeout': 30.0,
            'debug': True,
        }
        default_config.update(kwargs)
        return default_config


class AsyncBaseOLMoCRTest(BaseOLMoCRTest):
    """
    Base test class for asynchronous OLMoCR tests.
    
    Extends BaseOLMoCRTest with async/await support and async utilities.
    """
    
    def setUp(self):
        """Set up async test fixtures."""
        super().setUp()
        
        # Create event loop for async tests
        import asyncio
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Track async tasks for cleanup
        self.async_tasks = []
    
    def tearDown(self):
        """Clean up async test fixtures."""
        # Cancel any remaining async tasks
        for task in self.async_tasks:
            if not task.done():
                task.cancel()
        
        # Clean up event loop
        try:
            # Wait for any remaining tasks to complete
            if self.async_tasks:
                import asyncio
                self.loop.run_until_complete(
                    asyncio.gather(*self.async_tasks, return_exceptions=True)
                )
        except Exception:
            pass  # Best effort cleanup
        finally:
            self.loop.close()
        
        super().tearDown()
    
    def run_async(self, coro, timeout: float = 30.0):
        """
        Run an async coroutine with timeout.
        
        Args:
            coro: Coroutine to run
            timeout: Timeout in seconds
            
        Returns:
            Coroutine result
        """
        import asyncio
        return self.loop.run_until_complete(
            asyncio.wait_for(coro, timeout=timeout)
        )


class ParameterizedTestMixin:
    """
    Mixin for parameterized tests.
    
    Provides utilities for running the same test with different parameters.
    """
    
    def run_parameterized_test(self, test_func, parameters: List[Dict[str, Any]]):
        """
        Run a test function with multiple parameter sets.
        
        Args:
            test_func: Test function to run
            parameters: List of parameter dictionaries
        """
        for i, params in enumerate(parameters):
            with self.subTest(f"params_{i}", **params):
                test_func(**params)
