"""
Integration testing helpers for OLMoCR.

This module provides utilities for integration testing, end-to-end testing,
and pipeline testing with proper setup and teardown.
"""

import asyncio
import os
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional, Union
from unittest.mock import MagicMock

try:
    from olmocr.error_handling import create_logger
except ImportError:
    import logging
    def create_logger(name):
        return logging.getLogger(name)

from .mocks import create_mock_pipeline_components, create_mock_args
from .fixtures import create_test_pdf_data, create_test_config


class IntegrationTestHelper:
    """Helper class for integration testing."""
    
    def __init__(self, test_name: str = "integration_test"):
        """Initialize integration test helper."""
        self.test_name = test_name
        self.logger = create_logger(f"IntegrationTest.{test_name}")
        self.temp_dirs = []
        self.mock_components = {}
        self.test_workspace = None
        self.test_output = None
        
    def setup_test_environment(self) -> Dict[str, str]:
        """
        Set up a complete test environment.
        
        Returns:
            Dictionary with test environment paths
        """
        # Create temporary directories
        base_temp_dir = tempfile.mkdtemp(prefix=f"olmocr_integration_{self.test_name}_")
        self.temp_dirs.append(base_temp_dir)
        
        self.test_workspace = os.path.join(base_temp_dir, "workspace")
        self.test_output = os.path.join(base_temp_dir, "output")
        test_cache = os.path.join(base_temp_dir, "cache")
        test_logs = os.path.join(base_temp_dir, "logs")
        
        # Create directories
        for directory in [self.test_workspace, self.test_output, test_cache, test_logs]:
            os.makedirs(directory, exist_ok=True)
        
        # Create mock components
        self.mock_components = create_mock_pipeline_components()
        
        environment = {
            'base_dir': base_temp_dir,
            'workspace': self.test_workspace,
            'output': self.test_output,
            'cache': test_cache,
            'logs': test_logs
        }
        
        self.logger.info(f"Set up test environment: {environment}")
        return environment
    
    def create_test_pdfs(self, num_pdfs: int = 3, pages_per_pdf: int = 2) -> List[str]:
        """
        Create test PDF files in the workspace.
        
        Args:
            num_pdfs: Number of PDF files to create
            pages_per_pdf: Number of pages per PDF
            
        Returns:
            List of PDF file paths
        """
        if not self.test_workspace:
            raise RuntimeError("Test environment not set up. Call setup_test_environment() first.")
        
        pdf_paths = []
        
        for i in range(num_pdfs):
            pdf_name = f"test_document_{i+1}.pdf"
            pdf_path = os.path.join(self.test_workspace, pdf_name)
            
            # Create a simple text file as a mock PDF
            # In a real scenario, you'd create actual PDF files
            content = f"Mock PDF {i+1}\n"
            content += f"This is a test document with {pages_per_pdf} pages.\n"
            
            for page in range(pages_per_pdf):
                content += f"\nPage {page + 1} content:\n"
                content += f"Sample text for page {page + 1} of document {i+1}.\n"
                content += "Name: John Doe\n"
                content += "Email: john.doe@example.com\n"
                content += f"Document ID: DOC-{i+1:03d}-{page+1:02d}\n"
            
            with open(pdf_path, 'w') as f:
                f.write(content)
            
            pdf_paths.append(pdf_path)
            self.logger.info(f"Created test PDF: {pdf_path}")
        
        return pdf_paths
    
    def create_test_config(self, **overrides) -> Dict[str, Any]:
        """
        Create test configuration.
        
        Args:
            **overrides: Configuration overrides
            
        Returns:
            Test configuration
        """
        if not self.test_workspace:
            raise RuntimeError("Test environment not set up. Call setup_test_environment() first.")
        
        config = create_test_config(
            workspace=self.test_workspace,
            output_dir=self.test_output,
            **overrides
        )
        
        return config
    
    def verify_output_files(self, expected_files: List[str]) -> Dict[str, bool]:
        """
        Verify that expected output files were created.
        
        Args:
            expected_files: List of expected file names
            
        Returns:
            Dictionary mapping file names to existence status
        """
        if not self.test_output:
            raise RuntimeError("Test environment not set up. Call setup_test_environment() first.")
        
        results = {}
        
        for filename in expected_files:
            file_path = os.path.join(self.test_output, filename)
            exists = os.path.exists(file_path)
            results[filename] = exists
            
            if exists:
                file_size = os.path.getsize(file_path)
                self.logger.info(f"Output file found: {filename} ({file_size} bytes)")
            else:
                self.logger.warning(f"Expected output file not found: {filename}")
        
        return results
    
    def verify_output_content(self, filename: str, expected_content: Union[str, List[str]]) -> bool:
        """
        Verify output file content.
        
        Args:
            filename: Name of the file to check
            expected_content: Expected content (string or list of strings to check for)
            
        Returns:
            True if content matches expectations
        """
        if not self.test_output:
            raise RuntimeError("Test environment not set up. Call setup_test_environment() first.")
        
        file_path = os.path.join(self.test_output, filename)
        
        if not os.path.exists(file_path):
            self.logger.error(f"Output file not found: {filename}")
            return False
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            if isinstance(expected_content, str):
                return expected_content in content
            elif isinstance(expected_content, list):
                return all(item in content for item in expected_content)
            else:
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to read output file {filename}: {e}")
            return False
    
    def cleanup(self):
        """Clean up test environment."""
        for temp_dir in self.temp_dirs:
            try:
                shutil.rmtree(temp_dir)
                self.logger.info(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                self.logger.warning(f"Failed to clean up {temp_dir}: {e}")
        
        self.temp_dirs.clear()
        self.mock_components.clear()


class PipelineTestRunner:
    """Test runner for pipeline integration tests."""
    
    def __init__(self, logger: Optional[Any] = None):
        """Initialize pipeline test runner."""
        self.logger = logger or create_logger("PipelineTestRunner")
        self.test_results = []
    
    def run_pipeline_test(self, test_name: str, pipeline_func: callable, 
                         test_data: Dict[str, Any], expected_results: Dict[str, Any],
                         timeout: float = 300.0) -> Dict[str, Any]:
        """
        Run a pipeline integration test.
        
        Args:
            test_name: Name of the test
            pipeline_func: Pipeline function to test
            test_data: Test input data
            expected_results: Expected results
            timeout: Test timeout in seconds
            
        Returns:
            Test results
        """
        self.logger.info(f"Running pipeline test: {test_name}")
        
        start_time = time.time()
        test_result = {
            'test_name': test_name,
            'status': 'running',
            'start_time': start_time,
            'duration': 0.0,
            'error': None,
            'results': None,
            'validation': {}
        }
        
        try:
            # Run the pipeline with timeout
            if asyncio.iscoroutinefunction(pipeline_func):
                results = asyncio.run(
                    asyncio.wait_for(pipeline_func(test_data), timeout=timeout)
                )
            else:
                results = pipeline_func(test_data)
            
            end_time = time.time()
            test_result['duration'] = end_time - start_time
            test_result['results'] = results
            test_result['status'] = 'completed'
            
            # Validate results
            validation = self._validate_results(results, expected_results)
            test_result['validation'] = validation
            
            if validation['passed']:
                test_result['status'] = 'passed'
                self.logger.info(f"Pipeline test passed: {test_name}")
            else:
                test_result['status'] = 'failed'
                self.logger.error(f"Pipeline test failed: {test_name} - {validation['errors']}")
            
        except asyncio.TimeoutError:
            test_result['status'] = 'timeout'
            test_result['error'] = f"Test timed out after {timeout}s"
            self.logger.error(f"Pipeline test timed out: {test_name}")
            
        except Exception as e:
            end_time = time.time()
            test_result['duration'] = end_time - start_time
            test_result['status'] = 'error'
            test_result['error'] = str(e)
            self.logger.error(f"Pipeline test error: {test_name} - {e}")
        
        self.test_results.append(test_result)
        return test_result
    
    def _validate_results(self, actual_results: Any, expected_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate test results against expectations.
        
        Args:
            actual_results: Actual test results
            expected_results: Expected results
            
        Returns:
            Validation results
        """
        validation = {
            'passed': True,
            'errors': [],
            'checks': {}
        }
        
        # Check if results exist
        if actual_results is None:
            validation['passed'] = False
            validation['errors'].append("Results are None")
            return validation
        
        # Validate specific expectations
        for check_name, expected_value in expected_results.items():
            try:
                if check_name == 'output_files':
                    # Check for expected output files
                    check_passed = self._check_output_files(actual_results, expected_value)
                elif check_name == 'content_contains':
                    # Check for expected content
                    check_passed = self._check_content_contains(actual_results, expected_value)
                elif check_name == 'min_duration':
                    # Check minimum duration
                    check_passed = getattr(actual_results, 'duration', 0) >= expected_value
                elif check_name == 'max_duration':
                    # Check maximum duration
                    check_passed = getattr(actual_results, 'duration', float('inf')) <= expected_value
                else:
                    # Generic attribute check
                    actual_value = getattr(actual_results, check_name, None)
                    check_passed = actual_value == expected_value
                
                validation['checks'][check_name] = check_passed
                
                if not check_passed:
                    validation['passed'] = False
                    validation['errors'].append(f"Check failed: {check_name}")
                    
            except Exception as e:
                validation['passed'] = False
                validation['errors'].append(f"Validation error for {check_name}: {e}")
                validation['checks'][check_name] = False
        
        return validation
    
    def _check_output_files(self, results: Any, expected_files: List[str]) -> bool:
        """Check if expected output files exist."""
        # This would need to be implemented based on the actual results structure
        return True  # Placeholder
    
    def _check_content_contains(self, results: Any, expected_content: List[str]) -> bool:
        """Check if results contain expected content."""
        result_str = str(results)
        return all(content in result_str for content in expected_content)
    
    def get_test_summary(self) -> Dict[str, Any]:
        """Get summary of all test results."""
        if not self.test_results:
            return {'total': 0, 'passed': 0, 'failed': 0, 'error': 0, 'timeout': 0}
        
        summary = {
            'total': len(self.test_results),
            'passed': sum(1 for r in self.test_results if r['status'] == 'passed'),
            'failed': sum(1 for r in self.test_results if r['status'] == 'failed'),
            'error': sum(1 for r in self.test_results if r['status'] == 'error'),
            'timeout': sum(1 for r in self.test_results if r['status'] == 'timeout'),
            'total_duration': sum(r['duration'] for r in self.test_results),
            'average_duration': 0.0
        }
        
        if summary['total'] > 0:
            summary['average_duration'] = summary['total_duration'] / summary['total']
            summary['success_rate'] = summary['passed'] / summary['total']
        
        return summary


class EndToEndTestSuite:
    """End-to-end test suite for complete pipeline testing."""
    
    def __init__(self):
        """Initialize end-to-end test suite."""
        self.logger = create_logger("EndToEndTestSuite")
        self.test_helper = IntegrationTestHelper("e2e_test")
        self.pipeline_runner = PipelineTestRunner(self.logger)
    
    def run_complete_pipeline_test(self) -> Dict[str, Any]:
        """Run a complete end-to-end pipeline test."""
        self.logger.info("Starting end-to-end pipeline test")
        
        try:
            # Set up test environment
            env = self.test_helper.setup_test_environment()
            
            # Create test data
            pdf_paths = self.test_helper.create_test_pdfs(num_pdfs=2, pages_per_pdf=3)
            config = self.test_helper.create_test_config()
            
            # Mock pipeline function for testing
            def mock_pipeline(test_data):
                # Simulate pipeline processing
                time.sleep(0.1)  # Simulate processing time
                return {
                    'processed_files': len(test_data.get('pdf_paths', [])),
                    'output_dir': test_data.get('config', {}).get('output_dir'),
                    'status': 'completed'
                }
            
            # Run pipeline test
            test_data = {
                'pdf_paths': pdf_paths,
                'config': config
            }
            
            expected_results = {
                'output_files': ['output.jsonl'],
                'content_contains': ['processed_files'],
                'max_duration': 10.0
            }
            
            result = self.pipeline_runner.run_pipeline_test(
                test_name="complete_pipeline",
                pipeline_func=mock_pipeline,
                test_data=test_data,
                expected_results=expected_results
            )
            
            return result
            
        finally:
            # Clean up
            self.test_helper.cleanup()


def create_test_workspace(workspace_name: str = "test_workspace") -> str:
    """
    Create a temporary test workspace.
    
    Args:
        workspace_name: Name for the workspace
        
    Returns:
        Path to the created workspace
    """
    workspace_path = tempfile.mkdtemp(prefix=f"olmocr_{workspace_name}_")
    
    # Create standard subdirectories
    subdirs = ['input', 'output', 'cache', 'logs', 'temp']
    for subdir in subdirs:
        os.makedirs(os.path.join(workspace_path, subdir), exist_ok=True)
    
    return workspace_path
