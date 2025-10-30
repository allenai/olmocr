"""Backend abstraction layer for inference servers.

This module provides a unified interface for different inference backends,
allowing olmocr to work with both vLLM (NVIDIA GPUs) and MLX-VLM (Apple Silicon).
"""

import asyncio
import logging
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class BackendConfig:
    """Common configuration for all inference backends."""

    model_path: str
    port: int
    gpu_memory_utilization: Optional[float] = None
    max_model_len: int = 16384
    tensor_parallel_size: int = 1
    data_parallel_size: int = 1
    # MLX-specific
    mlx_quantization: Optional[str] = None
    mlx_kv_bits: Optional[int] = None


class InferenceBackend(ABC):
    """Abstract base class for inference backends."""

    @abstractmethod
    async def start_server(self, config: BackendConfig, semaphore: asyncio.Semaphore) -> asyncio.subprocess.Process:
        """Start the inference server subprocess.

        Args:
            config: Backend configuration
            semaphore: Asyncio semaphore for load balancing

        Returns:
            The subprocess handle
        """
        pass

    @abstractmethod
    async def check_health(self, server_url: str, api_key: Optional[str] = None) -> bool:
        """Check if server is ready to accept requests.

        Args:
            server_url: Full server URL
            api_key: Optional API key for authentication

        Returns:
            True if server is healthy
        """
        pass

    @abstractmethod
    def build_request(
        self,
        prompt: str,
        base64_image: str,
        temperature: float,
        max_tokens: int = 8000,
        guided_decoding: bool = False,
        model: str = "olmocr",
    ) -> Dict[str, Any]:
        """Build model-specific request format.

        Args:
            prompt: Text prompt
            base64_image: Base64-encoded PNG image
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            guided_decoding: Whether to enable regex-guided decoding
            model: Model name or path

        Returns:
            Request dictionary ready for JSON serialization
        """
        pass

    @abstractmethod
    def parse_response(self, response_data: Dict[str, Any]) -> tuple[str, int, int]:
        """Parse model-specific response format.

        Args:
            response_data: Response JSON from server

        Returns:
            Tuple of (content_text, input_tokens, output_tokens)
        """
        pass

    @abstractmethod
    def validate_response_format(self, content: str) -> bool:
        """Validate response format (for backends without guided decoding).

        Args:
            content: Response text to validate

        Returns:
            True if response has valid format
        """
        pass

    @abstractmethod
    def get_endpoint_path(self) -> str:
        """Return API endpoint path.

        Returns:
            Endpoint path (e.g., "/v1/chat/completions")
        """
        pass

    @abstractmethod
    def get_default_port(self) -> int:
        """Return default server port.

        Returns:
            Default port number
        """
        pass


class VLLMBackend(InferenceBackend):
    """vLLM backend for NVIDIA GPUs and Linux servers."""

    async def start_server(self, config: BackendConfig, semaphore: asyncio.Semaphore) -> asyncio.subprocess.Process:
        """Start vLLM server subprocess with monitoring."""
        cmd = [
            "vllm",
            "serve",
            config.model_path,
            "--port",
            str(config.port),
            "--disable-log-requests",
            "--uvicorn-log-level",
            "warning",
            "--served-model-name",
            "olmocr",
            "--tensor-parallel-size",
            str(config.tensor_parallel_size),
            "--data-parallel-size",
            str(config.data_parallel_size),
            "--limit-mm-per-prompt",
            '{"video": 0}',  # Disable video encoder for RAM savings
        ]

        if config.gpu_memory_utilization is not None:
            cmd.extend(["--gpu-memory-utilization", str(config.gpu_memory_utilization)])

        if config.max_model_len is not None:
            cmd.extend(["--max-model-len", str(config.max_model_len)])

        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = "1"  # Prevent GPU contention

        logger.info(f"Starting vLLM server: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )

        # Monitor server logs and manage semaphore
        peak_running_reqs = 0
        last_release_time = 0

        async def monitor_logs():
            nonlocal peak_running_reqs, last_release_time

            async for line in process.stdout:
                line_str = line.decode().strip()
                logger.info(f"vLLM: {line_str}")

                # Check for startup ready message
                if "The server is fired up and ready to roll!" in line_str or "Starting vLLM API server" in line_str:
                    logger.info("vLLM server is ready")

                # Parse request queue metrics
                import re

                running_match = re.search(r"Running: (\d+)", line_str)
                if running_match:
                    running_reqs = int(running_match.group(1))
                    peak_running_reqs = max(peak_running_reqs, running_reqs)

                waiting_match = re.search(r"(?:Waiting|Pending): (\d+)", line_str)
                if waiting_match:
                    waiting_reqs = int(waiting_match.group(1))
                    current_time = asyncio.get_event_loop().time()

                    # Release semaphore if queue is low
                    if waiting_reqs <= peak_running_reqs * 0.2 and current_time - last_release_time > 30:
                        logger.info(f"Queue decreased, releasing worker (running={running_reqs}, waiting={waiting_reqs})")
                        semaphore.release()
                        last_release_time = current_time

                # Check for errors
                if "Detected errors during sampling" in line_str:
                    logger.error("vLLM detected sampling errors - model may be corrupted")
                    sys.exit(1)

        asyncio.create_task(monitor_logs())
        return process

    async def check_health(self, server_url: str, api_key: Optional[str] = None) -> bool:
        """Poll /models endpoint until vLLM responds."""
        url = f"{server_url.rstrip('/')}/models"
        max_attempts = 300
        delay_sec = 1

        for attempt in range(1, max_attempts + 1):
            try:
                headers = {}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                async with httpx.AsyncClient() as client:
                    response = await client.get(url, headers=headers)

                    if response.status_code == 200:
                        logger.info("vLLM server is ready")
                        return True
            except Exception:
                if attempt % 10 == 0:
                    logger.warning(f"Attempt {attempt}/{max_attempts}: Waiting for vLLM server to become ready...")

            await asyncio.sleep(delay_sec)

        raise Exception("vLLM server did not become ready after 5 minutes")

    def build_request(
        self,
        prompt: str,
        base64_image: str,
        temperature: float,
        max_tokens: int = 8000,
        guided_decoding: bool = False,
        model: str = "olmocr",
    ) -> Dict[str, Any]:
        """Build vLLM chat completions format request."""
        request = {
            "model": model,  # Use the provided model name (important for external APIs)
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if guided_decoding:
            request["guided_regex"] = (
                r"---\nprimary_language: (?:[a-z]{2}|null)\nis_rotation_valid: (?:True|False|true|false)\n"
                r"rotation_correction: (?:0|90|180|270)\nis_table: (?:True|False|true|false)\n"
                r"is_diagram: (?:True|False|true|false)\n(?:---|---\n[\s\S]+)"
            )

        return request

    def parse_response(self, response_data: Dict[str, Any]) -> tuple[str, int, int]:
        """Parse vLLM chat completions response."""
        try:
            content = response_data["choices"][0]["message"]["content"]
            usage = response_data["usage"]
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            return content, input_tokens, output_tokens
        except (KeyError, IndexError) as e:
            raise ValueError(f"Invalid vLLM response structure: {e}")

    def validate_response_format(self, content: str) -> bool:
        """vLLM supports guided decoding, so always return True."""
        return True

    def get_endpoint_path(self) -> str:
        return "/chat/completions"

    def get_default_port(self) -> int:
        return 30024


class MLXVLMBackend(InferenceBackend):
    """MLX-VLM backend for Apple Silicon Macs."""

    async def start_server(self, config: BackendConfig, semaphore: asyncio.Semaphore) -> asyncio.subprocess.Process:
        """Start mlx_vlm.server on specified port."""
        cmd = [
            sys.executable,
            "-m",
            "mlx_vlm.server",
            "--port",
            str(config.port),
        ]

        logger.info(f"Starting MLX-VLM server: {' '.join(cmd)}")
        logger.info(f"Model will be loaded on first request: {config.model_path}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Monitor for startup message
        async def monitor_startup():
            async for line in process.stdout:
                line_str = line.decode().strip()
                logger.info(f"MLX-VLM: {line_str}")

                if "Application startup complete" in line_str:
                    logger.info("MLX-VLM server ready, releasing workers")
                    semaphore.release()
                    break

        asyncio.create_task(monitor_startup())
        return process

    async def check_health(self, server_url: str, api_key: Optional[str] = None) -> bool:
        """Poll /health endpoint until MLX-VLM responds."""
        url = f"{server_url.rstrip('/')}/health"
        max_attempts = 300
        delay_sec = 1

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url)

                    if response.status_code == 200:
                        logger.info("MLX-VLM server is ready")
                        return True
            except Exception:
                if attempt % 10 == 0:
                    logger.warning(f"Attempt {attempt}/{max_attempts}: Waiting for MLX-VLM server to become ready...")

            await asyncio.sleep(delay_sec)

        raise Exception("MLX-VLM server did not become ready after 5 minutes")

    def build_request(
        self,
        prompt: str,
        base64_image: str,
        temperature: float,
        max_tokens: int = 8000,
        guided_decoding: bool = False,
        model: str = "olmocr",
    ) -> Dict[str, Any]:
        """Build MLX-VLM OpenAI Responses API format request.

        Note: MLX-VLM uses OpenAI's Responses API format, which differs from
        Chat Completions API used by vLLM. Key differences:
        - "input" instead of "messages"
        - "input_text" and "input_image" instead of "text" and "image_url"
        - "max_output_tokens" instead of "max_tokens"
        """
        request = {
            "model": model,  # Use the provided model path
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:image/png;base64,{base64_image}"},
                    ],
                }
            ],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }

        # Note: MLX-VLM doesn't support guided_regex
        # Validation will be done in validate_response_format()

        return request

    def parse_response(self, response_data: Dict[str, Any]) -> tuple[str, int, int]:
        """Parse MLX-VLM OpenAI Responses API format response.

        MLX-VLM response structure:
        {
            "output": [{"content": [{"text": "..."}]}],
            "usage": {"input_tokens": ..., "output_tokens": ...}
        }
        """
        try:
            # Extract text from nested structure
            content = response_data["output"][0]["content"][0]["text"]

            # MLX-VLM uses different token field names
            usage = response_data["usage"]
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            return content, input_tokens, output_tokens
        except (KeyError, IndexError) as e:
            raise ValueError(f"Invalid MLX-VLM response structure: {e}")

    def validate_response_format(self, content: str) -> bool:
        """Validate YAML front matter format since guided_regex not supported.

        Returns True if response has valid PageResponse structure with YAML front matter.
        """
        try:
            from olmocr.train.dataloader import FrontMatterParser
            from olmocr.prompts import PageResponse

            parser = FrontMatterParser(front_matter_class=PageResponse)
            parser._extract_front_matter_and_text(content)
            return True
        except Exception:
            return False

    def get_endpoint_path(self) -> str:
        return "/responses"

    def get_default_port(self) -> int:
        return 8000


def get_backend(backend_name: str) -> InferenceBackend:
    """Factory function to get backend implementation by name.

    Args:
        backend_name: Name of backend ("vllm" or "mlx-vlm")

    Returns:
        Backend instance

    Raises:
        ValueError: If backend_name is not recognized
    """
    backends = {
        "vllm": VLLMBackend,
        "mlx-vlm": MLXVLMBackend,
    }

    if backend_name not in backends:
        raise ValueError(f"Unknown backend: {backend_name}. Available: {list(backends.keys())}")

    return backends[backend_name]()
