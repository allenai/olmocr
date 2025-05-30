"""
Unit tests for the HTTP client module.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from olmocr.pipeline.http_client import SGLangHTTPClient, create_sglang_client, apost


class TestSGLangHTTPClient(unittest.TestCase):
    """Test cases for SGLangHTTPClient."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = SGLangHTTPClient("http://localhost:30024")
    
    def test_init(self):
        """Test client initialization."""
        self.assertEqual(self.client.host, "localhost")
        self.assertEqual(self.client.port, 30024)
        self.assertEqual(self.client.base_url, "http://localhost:30024")
    
    def test_init_with_port_in_url(self):
        """Test client initialization with port in URL."""
        client = SGLangHTTPClient("http://example.com:8080")
        self.assertEqual(client.host, "example.com")
        self.assertEqual(client.port, 8080)
    
    def test_init_default_port(self):
        """Test client initialization with default port."""
        client = SGLangHTTPClient("http://example.com")
        self.assertEqual(client.host, "example.com")
        self.assertEqual(client.port, 80)
    
    @patch('olmocr.pipeline.http_client.asyncio.open_connection')
    async def test_post_completion_success(self, mock_open_connection):
        """Test successful POST completion request."""
        # Mock the reader and writer
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)
        
        # Mock the response
        mock_reader.readline.side_effect = [
            b"HTTP/1.1 200 OK\r\n",
            b"Content-Type: application/json\r\n",
            b"Content-Length: 25\r\n",
            b"\r\n"
        ]
        mock_reader.readexactly.return_value = b'{"status": "success"}'
        
        # Test data
        test_data = {"model": "test", "messages": []}
        
        # Make the request
        status_code, response_body = await self.client.post_completion(test_data)
        
        # Verify results
        self.assertEqual(status_code, 200)
        self.assertEqual(response_body, b'{"status": "success"}')
        
        # Verify the request was made correctly
        mock_open_connection.assert_called_once_with("localhost", 30024)
        mock_writer.write.assert_called_once()
        mock_writer.close.assert_called_once()
    
    @patch('olmocr.pipeline.http_client.asyncio.open_connection')
    async def test_post_completion_error_status(self, mock_open_connection):
        """Test POST completion request with error status."""
        # Mock the reader and writer
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)
        
        # Mock error response
        mock_reader.readline.side_effect = [
            b"HTTP/1.1 500 Internal Server Error\r\n",
            b"Content-Type: application/json\r\n",
            b"Content-Length: 23\r\n",
            b"\r\n"
        ]
        mock_reader.readexactly.return_value = b'{"error": "server error"}'
        
        # Test data
        test_data = {"model": "test", "messages": []}
        
        # Make the request
        status_code, response_body = await self.client.post_completion(test_data)
        
        # Verify results
        self.assertEqual(status_code, 500)
        self.assertEqual(response_body, b'{"error": "server error"}')
    
    @patch('olmocr.pipeline.http_client.asyncio.open_connection')
    async def test_post_completion_connection_error(self, mock_open_connection):
        """Test POST completion request with connection error."""
        # Mock connection failure
        mock_open_connection.side_effect = ConnectionError("Connection failed")
        
        # Test data
        test_data = {"model": "test", "messages": []}
        
        # Make the request and expect exception
        with self.assertRaises(ConnectionError):
            await self.client.post_completion(test_data)
    
    @patch('olmocr.pipeline.http_client.asyncio.open_connection')
    async def test_post_completion_malformed_response(self, mock_open_connection):
        """Test POST completion request with malformed response."""
        # Mock the reader and writer
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)
        
        # Mock malformed response
        mock_reader.readline.return_value = b"INVALID\r\n"
        
        # Test data
        test_data = {"model": "test", "messages": []}
        
        # Make the request and expect exception
        with self.assertRaises(ValueError):
            await self.client.post_completion(test_data)
    
    @patch('olmocr.pipeline.http_client.asyncio.open_connection')
    async def test_post_completion_no_content_length(self, mock_open_connection):
        """Test POST completion request without content-length header."""
        # Mock the reader and writer
        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_open_connection.return_value = (mock_reader, mock_writer)
        
        # Mock response without content-length
        mock_reader.readline.side_effect = [
            b"HTTP/1.1 200 OK\r\n",
            b"Content-Type: application/json\r\n",
            b"\r\n"
        ]
        
        # Test data
        test_data = {"model": "test", "messages": []}
        
        # Make the request and expect exception
        with self.assertRaises(ConnectionError):
            await self.client.post_completion(test_data)


class TestFactoryFunctions(unittest.TestCase):
    """Test cases for factory functions."""
    
    async def test_create_sglang_client(self):
        """Test create_sglang_client factory function."""
        client = await create_sglang_client(8080)
        self.assertIsInstance(client, SGLangHTTPClient)
        self.assertEqual(client.port, 8080)
        self.assertEqual(client.host, "localhost")
    
    async def test_create_sglang_client_default_port(self):
        """Test create_sglang_client with default port."""
        client = await create_sglang_client()
        self.assertIsInstance(client, SGLangHTTPClient)
        self.assertEqual(client.port, 30024)
    
    @patch('olmocr.pipeline.http_client.SGLangHTTPClient._post')
    async def test_apost_legacy_function(self, mock_post):
        """Test legacy apost function."""
        # Mock the _post method
        mock_post.return_value = (200, b'{"result": "success"}')
        
        # Test the legacy function
        url = "http://localhost:30024/v1/chat/completions"
        data = {"test": "data"}
        
        status_code, response_body = await apost(url, data)
        
        # Verify results
        self.assertEqual(status_code, 200)
        self.assertEqual(response_body, b'{"result": "success"}')
        
        # Verify the underlying method was called
        mock_post.assert_called_once_with("/v1/chat/completions", data)


class TestAsyncMethods(unittest.TestCase):
    """Test cases that require async test runner."""
    
    def test_async_methods(self):
        """Run async tests."""
        async def run_tests():
            # Test create_sglang_client
            client = await create_sglang_client(8080)
            assert isinstance(client, SGLangHTTPClient)
            assert client.port == 8080
            
            # Test create_sglang_client with default port
            client_default = await create_sglang_client()
            assert isinstance(client_default, SGLangHTTPClient)
            assert client_default.port == 30024
        
        # Run the async tests
        asyncio.run(run_tests())


if __name__ == "__main__":
    unittest.main()
