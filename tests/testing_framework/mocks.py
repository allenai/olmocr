"""
Mock objects for external dependencies in OLMoCR testing.

This module provides mock implementations of external services and dependencies
to enable isolated testing without requiring actual external resources.
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Union
from unittest.mock import MagicMock, AsyncMock

try:
    from olmocr.error_handling import create_logger
except ImportError:
    import logging
    def create_logger(name):
        return logging.getLogger(name)


class MockSGLangServer:
    """Mock SGLang server for testing pipeline components."""
    
    def __init__(self, response_delay: float = 0.1, failure_rate: float = 0.0):
        """
        Initialize mock SGLang server.
        
        Args:
            response_delay: Simulated response delay in seconds
            failure_rate: Rate of simulated failures (0.0 to 1.0)
        """
        self.response_delay = response_delay
        self.failure_rate = failure_rate
        self.request_count = 0
        self.is_running = False
        self.logger = create_logger("MockSGLangServer")
        
        # Track requests for testing
        self.requests = []
        self.responses = []
    
    async def start(self):
        """Start the mock server."""
        self.is_running = True
        self.logger.info("Mock SGLang server started")
    
    async def stop(self):
        """Stop the mock server."""
        self.is_running = False
        self.logger.info("Mock SGLang server stopped")
    
    async def process_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a mock request.
        
        Args:
            request_data: Request data
            
        Returns:
            Mock response data
        """
        if not self.is_running:
            raise RuntimeError("Mock server is not running")
        
        self.request_count += 1
        self.requests.append(request_data)
        
        # Simulate processing delay
        await asyncio.sleep(self.response_delay)
        
        # Simulate failures
        import random
        if random.random() < self.failure_rate:
            raise RuntimeError(f"Mock server failure (request {self.request_count})")
        
        # Generate mock response
        response = {
            'request_id': self.request_count,
            'text': self._generate_mock_text_response(request_data),
            'confidence': 0.95,
            'processing_time': self.response_delay,
            'model': 'mock-model',
            'tokens_used': 150
        }
        
        self.responses.append(response)
        return response
    
    def _generate_mock_text_response(self, request_data: Dict[str, Any]) -> str:
        """Generate mock text response based on request."""
        # Simple mock response generation
        if 'image' in request_data:
            return "This is mock OCR text extracted from the image."
        elif 'prompt' in request_data:
            return "This is a mock response to the prompt."
        else:
            return "This is a generic mock response."
    
    def get_stats(self) -> Dict[str, Any]:
        """Get server statistics."""
        return {
            'request_count': self.request_count,
            'is_running': self.is_running,
            'total_requests': len(self.requests),
            'total_responses': len(self.responses),
            'failure_rate': self.failure_rate,
            'response_delay': self.response_delay
        }
    
    def reset(self):
        """Reset server state."""
        self.request_count = 0
        self.requests.clear()
        self.responses.clear()


class MockS3Client:
    """Mock S3 client for testing file operations."""
    
    def __init__(self):
        """Initialize mock S3 client."""
        self.buckets = {}
        self.operations = []
        self.logger = create_logger("MockS3Client")
    
    def create_bucket(self, bucket_name: str):
        """Create a mock bucket."""
        self.buckets[bucket_name] = {}
        self.operations.append(('create_bucket', bucket_name))
        self.logger.info(f"Created mock bucket: {bucket_name}")
    
    def upload_file(self, local_path: str, bucket: str, key: str):
        """Mock file upload."""
        if bucket not in self.buckets:
            self.create_bucket(bucket)
        
        # Simulate reading file content
        try:
            with open(local_path, 'rb') as f:
                content = f.read()
            
            self.buckets[bucket][key] = {
                'content': content,
                'size': len(content),
                'upload_time': time.time()
            }
            
            self.operations.append(('upload_file', local_path, bucket, key))
            self.logger.info(f"Uploaded {local_path} to s3://{bucket}/{key}")
            
        except FileNotFoundError:
            raise FileNotFoundError(f"Local file not found: {local_path}")
    
    def download_file(self, bucket: str, key: str, local_path: str):
        """Mock file download."""
        if bucket not in self.buckets:
            raise Exception(f"Bucket not found: {bucket}")
        
        if key not in self.buckets[bucket]:
            raise Exception(f"Key not found: {key}")
        
        content = self.buckets[bucket][key]['content']
        
        with open(local_path, 'wb') as f:
            f.write(content)
        
        self.operations.append(('download_file', bucket, key, local_path))
        self.logger.info(f"Downloaded s3://{bucket}/{key} to {local_path}")
    
    def list_objects(self, bucket: str, prefix: str = "") -> List[str]:
        """List objects in mock bucket."""
        if bucket not in self.buckets:
            return []
        
        keys = [key for key in self.buckets[bucket].keys() if key.startswith(prefix)]
        self.operations.append(('list_objects', bucket, prefix))
        return keys
    
    def object_exists(self, bucket: str, key: str) -> bool:
        """Check if object exists."""
        return bucket in self.buckets and key in self.buckets[bucket]
    
    def get_operations(self) -> List[tuple]:
        """Get list of operations performed."""
        return self.operations.copy()
    
    def reset(self):
        """Reset mock S3 state."""
        self.buckets.clear()
        self.operations.clear()


class MockFileSystem:
    """Mock file system for testing file operations."""
    
    def __init__(self):
        """Initialize mock file system."""
        self.files = {}
        self.directories = set()
        self.operations = []
        self.logger = create_logger("MockFileSystem")
    
    def create_file(self, path: str, content: Union[str, bytes]):
        """Create a mock file."""
        # Create parent directories
        import os
        parent_dir = os.path.dirname(path)
        if parent_dir:
            self.create_directory(parent_dir)
        
        self.files[path] = {
            'content': content,
            'size': len(content) if content else 0,
            'created_time': time.time(),
            'modified_time': time.time()
        }
        
        self.operations.append(('create_file', path))
        self.logger.info(f"Created mock file: {path}")
    
    def create_directory(self, path: str):
        """Create a mock directory."""
        self.directories.add(path)
        
        # Create parent directories recursively
        import os
        parent = os.path.dirname(path)
        if parent and parent != path:
            self.create_directory(parent)
        
        self.operations.append(('create_directory', path))
    
    def read_file(self, path: str) -> Union[str, bytes]:
        """Read mock file content."""
        if path not in self.files:
            raise FileNotFoundError(f"File not found: {path}")
        
        self.operations.append(('read_file', path))
        return self.files[path]['content']
    
    def file_exists(self, path: str) -> bool:
        """Check if mock file exists."""
        return path in self.files
    
    def get_operations(self) -> List[tuple]:
        """Get list of operations performed."""
        return self.operations.copy()
    
    def reset(self):
        """Reset mock file system."""
        self.files.clear()
        self.directories.clear()
        self.operations.clear()


class MockLogger:
    """Mock logger for testing logging functionality."""
    
    def __init__(self, name: str = "mock_logger"):
        """Initialize mock logger."""
        self.name = name
        self.logs = []
        self.level = "INFO"
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log("DEBUG", message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log("INFO", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self._log("WARNING", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message."""
        self._log("ERROR", message, **kwargs)
    
    def _log(self, level: str, message: str, **kwargs):
        """Internal logging method."""
        log_entry = {
            'level': level,
            'message': message,
            'timestamp': time.time(),
            'logger': self.name,
            'kwargs': kwargs
        }
        self.logs.append(log_entry)
    
    def get_logs(self, level: str = None) -> List[Dict[str, Any]]:
        """Get logged messages."""
        if level:
            return [log for log in self.logs if log['level'] == level]
        return self.logs.copy()
    
    def clear_logs(self):
        """Clear logged messages."""
        self.logs.clear()


def create_mock_pipeline_components():
    """
    Create a set of mock pipeline components for testing.
    
    Returns:
        Dictionary of mock components
    """
    components = {
        'sglang_server': MockSGLangServer(),
        's3_client': MockS3Client(),
        'file_system': MockFileSystem(),
        'logger': MockLogger(),
        'http_client': MagicMock(),
        'work_queue': MagicMock(),
        'metrics': MagicMock(),
        'tracker': MagicMock(),
    }
    
    # Configure HTTP client mock
    components['http_client'].get = AsyncMock()
    components['http_client'].post = AsyncMock()
    
    # Configure work queue mock
    components['work_queue'].get_work = AsyncMock()
    components['work_queue'].mark_done = AsyncMock()
    components['work_queue'].size = 0
    
    # Configure metrics mock
    components['metrics'].add_metrics = MagicMock()
    components['metrics'].get_summary = MagicMock(return_value={})
    
    # Configure tracker mock
    components['tracker'].clear_work = AsyncMock()
    components['tracker'].get_status_table = AsyncMock(return_value="Mock status")
    
    return components


def create_mock_args(**overrides):
    """
    Create mock command line arguments for testing.
    
    Args:
        **overrides: Argument overrides
        
    Returns:
        Mock arguments object
    """
    default_args = {
        'workspace': '/tmp/test_workspace',
        'pdfs': [],
        'workers': 1,
        'model': 'test-model',
        'model_chat_template': 'test-template',
        'model_max_context': 4096,
        'pages_per_group': 10,
        'max_page_retries': 3,
        'max_page_error_rate': 0.1,
        'apply_filter': False,
        'stats': False,
        'markdown': False,
        'structured_output': False,
        'extract_forms': False,
        'extract_tables': False,
        'extract_key_value_pairs': False,
        'structured_min_confidence': 0.5,
        'structured_output_format': 'combined',
    }
    
    default_args.update(overrides)
    
    # Create mock object with attributes
    mock_args = MagicMock()
    for key, value in default_args.items():
        setattr(mock_args, key, value)
    
    return mock_args
