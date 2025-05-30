"""
HTTP client module for SGLang communication.

This module provides a lightweight HTTP client implementation optimized for
high-volume requests to the SGLang inference server with enhanced error handling.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlparse

from olmocr.error_handling import (
    StructuredLogger, LogContext, create_logger,
    NetworkError, TimeoutError, ValidationError, ErrorContext, ErrorSeverity,
    create_recovery_manager, create_performance_monitor
)

logger = create_logger(__name__, structured=True)


class SGLangHTTPClient:
    """
    Lightweight HTTP client for SGLang server communication.

    Uses raw asyncio sockets instead of httpx/aiohttp to avoid complex
    session pooling issues at scale (100M+ requests). Enhanced with structured
    logging, error categorization, and performance monitoring.
    """

    def __init__(self, base_url: str, logger: Optional[StructuredLogger] = None):
        """
        Initialize the HTTP client.

        Args:
            base_url: Base URL of the SGLang server (e.g., "http://localhost:30024")
            logger: Optional structured logger instance
        """
        self.base_url = base_url.rstrip('/')
        parsed = urlparse(base_url)
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.logger = logger or create_logger(f"{__name__}.SGLangHTTPClient")
        self.recovery_manager = create_recovery_manager(max_attempts=3, logger=self.logger)
        self.performance_monitor = create_performance_monitor(self.logger)
        
    async def post_completion(self, json_data: Dict[str, Any],
                             context: Optional[LogContext] = None) -> Tuple[int, bytes]:
        """
        Send a POST request to the /v1/chat/completions endpoint.

        Args:
            json_data: JSON payload for the completion request
            context: Optional log context for tracking

        Returns:
            Tuple of (status_code, response_body)

        Raises:
            NetworkError: If connection fails
            ValidationError: If response is malformed
        """
        path = "/v1/chat/completions"

        with self.performance_monitor.time_operation(
            "sglang_completion_request",
            context={'endpoint': path, 'host': self.host, 'port': self.port},
            log_context=context
        ):
            return await self.recovery_manager.execute_with_retry(
                self._post,
                context=context,
                operation_name="sglang_http_request",
                path=path,
                json_data=json_data,
                request_context=context
            )
    
    async def _post(self, path: str, json_data: Dict[str, Any],
                   request_context: Optional[LogContext] = None) -> Tuple[int, bytes]:
        """
        Send a raw HTTP POST request using asyncio sockets.

        Args:
            path: URL path for the request
            json_data: JSON payload
            request_context: Optional context for logging

        Returns:
            Tuple of (status_code, response_body)

        Raises:
            NetworkError: If connection fails
            ValidationError: If response is malformed
        """
        writer = None
        error_context = ErrorContext(
            processing_stage="http_request",
            additional_data={
                'host': self.host,
                'port': self.port,
                'path': path,
                'payload_size': len(json.dumps(json_data))
            }
        )

        try:
            self.logger.debug(
                f"Sending HTTP POST to {self.host}:{self.port}{path}",
                context=request_context
            )

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=30.0
            )

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
            status_line = await asyncio.wait_for(reader.readline(), timeout=60.0)
            if not status_line:
                raise NetworkError(
                    "No response from server",
                    context=error_context,
                    severity=ErrorSeverity.HIGH
                )

            status_parts = status_line.decode().strip().split(" ", 2)
            if len(status_parts) < 2:
                raise ValidationError(
                    f"Malformed status line: {status_line.decode().strip()}",
                    context=error_context
                )

            try:
                status_code = int(status_parts[1])
            except ValueError as e:
                raise ValidationError(
                    f"Invalid status code: {status_parts[1]}",
                    context=error_context,
                    original_exception=e
                )

            # Read headers
            headers = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                if line in (b"\r\n", b"\n", b""):
                    break
                key, _, value = line.decode().partition(":")
                headers[key.strip().lower()] = value.strip()

            # Read response body
            if "content-length" in headers:
                try:
                    body_length = int(headers["content-length"])
                    response_body = await asyncio.wait_for(
                        reader.readexactly(body_length),
                        timeout=120.0
                    )
                except ValueError as e:
                    raise ValidationError(
                        f"Invalid content-length header: {headers['content-length']}",
                        context=error_context,
                        original_exception=e
                    )
            else:
                raise NetworkError(
                    "Missing content-length header - chunked encoding not supported",
                    context=error_context
                )

            self.logger.debug(
                f"HTTP request completed: {status_code}",
                context=request_context,
                metrics={'status_code': status_code, 'response_size': len(response_body)}
            )

            return status_code, response_body

        except asyncio.TimeoutError as e:
            raise TimeoutError(
                f"HTTP request timeout to {self.host}:{self.port}{path}",
                context=error_context,
                original_exception=e
            )
        except (ConnectionRefusedError, OSError) as e:
            raise NetworkError(
                f"Connection failed to {self.host}:{self.port}: {e}",
                context=error_context,
                original_exception=e
            )
        except Exception as e:
            # Re-raise our custom errors
            if isinstance(e, (NetworkError, ValidationError, TimeoutError)):
                raise

            # Categorize unknown errors
            self.logger.exception(
                f"Unexpected error in HTTP request",
                context=request_context
            )
            raise NetworkError(
                f"Unexpected HTTP error: {e}",
                context=error_context,
                original_exception=e
            )
        finally:
            # Ensure socket is closed
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass


async def create_sglang_client(port: int = 30024,
                              logger: Optional[StructuredLogger] = None) -> SGLangHTTPClient:
    """
    Create an SGLang HTTP client instance.

    Args:
        port: Port number for the SGLang server
        logger: Optional structured logger instance

    Returns:
        Configured SGLangHTTPClient instance
    """
    base_url = f"http://localhost:{port}"
    client_logger = logger or create_logger(f"{__name__}.client")

    client_logger.info(
        f"Creating SGLang HTTP client for {base_url}",
        context=LogContext(
            correlation_id="",
            processing_stage="client_initialization"
        )
    )

    return SGLangHTTPClient(base_url, client_logger)


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
    base_url = url.rsplit('/', 1)[0]  # Extract base URL
    path = '/' + url.rsplit('/', 1)[1]  # Extract path

    # Create client with legacy logger
    legacy_logger = create_logger(f"{__name__}.legacy")
    client = SGLangHTTPClient(base_url, legacy_logger)

    # Create legacy context
    context = LogContext(
        correlation_id="",
        processing_stage="legacy_request"
    )

    return await client._post(path, json_data, context)
