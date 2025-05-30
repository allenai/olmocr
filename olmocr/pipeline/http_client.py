"""
HTTP client module for SGLang communication.

This module provides a lightweight HTTP client implementation optimized for
high-volume requests to the SGLang inference server.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SGLangHTTPClient:
    """
    Lightweight HTTP client for SGLang server communication.
    
    Uses raw asyncio sockets instead of httpx/aiohttp to avoid complex
    session pooling issues at scale (100M+ requests).
    """
    
    def __init__(self, base_url: str):
        """
        Initialize the HTTP client.
        
        Args:
            base_url: Base URL of the SGLang server (e.g., "http://localhost:30024")
        """
        self.base_url = base_url.rstrip('/')
        parsed = urlparse(base_url)
        self.host = parsed.hostname
        self.port = parsed.port or 80
        
    async def post_completion(self, json_data: Dict[str, Any]) -> Tuple[int, bytes]:
        """
        Send a POST request to the /v1/chat/completions endpoint.
        
        Args:
            json_data: JSON payload for the completion request
            
        Returns:
            Tuple of (status_code, response_body)
            
        Raises:
            ConnectionError: If connection fails
            ValueError: If response is malformed
        """
        path = "/v1/chat/completions"
        return await self._post(path, json_data)
    
    async def _post(self, path: str, json_data: Dict[str, Any]) -> Tuple[int, bytes]:
        """
        Send a raw HTTP POST request using asyncio sockets.
        
        Args:
            path: URL path for the request
            json_data: JSON payload
            
        Returns:
            Tuple of (status_code, response_body)
            
        Raises:
            ConnectionError: If connection fails
            ValueError: If response is malformed
        """
        writer = None
        try:
            reader, writer = await asyncio.open_connection(self.host, self.port)

            json_payload = json.dumps(json_data)
            request = (
                f"POST {path} HTTP/1.1\r\n"
                f"Host: {self.host}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(json_payload)}\r\n"
                f"Connection: close\r\n\r\n"
                f"{json_payload}"
            )
            writer.write(request.encode())
            await writer.drain()

            # Read status line
            status_line = await reader.readline()
            if not status_line:
                raise ConnectionError("No response from server")
            status_parts = status_line.decode().strip().split(" ", 2)
            if len(status_parts) < 2:
                raise ValueError(f"Malformed status line: {status_line.decode().strip()}")
            status_code = int(status_parts[1])

            # Read headers
            headers = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                key, _, value = line.decode().partition(":")
                headers[key.strip().lower()] = value.strip()

            # Read response body
            if "content-length" in headers:
                body_length = int(headers["content-length"])
                response_body = await reader.readexactly(body_length)
            else:
                raise ConnectionError("Anything other than fixed content length responses are not implemented yet")

            return status_code, response_body
        except Exception as e:
            logger.debug(f"HTTP request failed: {e}")
            raise e
        finally:
            # Ensure socket is closed
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass


async def create_sglang_client(port: int = 30024) -> SGLangHTTPClient:
    """
    Create an SGLang HTTP client instance.
    
    Args:
        port: Port number for the SGLang server
        
    Returns:
        Configured SGLangHTTPClient instance
    """
    base_url = f"http://localhost:{port}"
    return SGLangHTTPClient(base_url)


# Legacy function for backward compatibility
async def apost(url: str, json_data: Dict[str, Any]) -> Tuple[int, bytes]:
    """
    Legacy function for backward compatibility.
    
    Args:
        url: Full URL for the request
        json_data: JSON payload
        
    Returns:
        Tuple of (status_code, response_body)
    """
    client = SGLangHTTPClient(url.rsplit('/', 1)[0])  # Extract base URL
    path = '/' + url.rsplit('/', 1)[1]  # Extract path
    return await client._post(path, json_data)
