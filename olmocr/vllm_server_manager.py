#!/usr/bin/env python3
"""
vLLM Server Manager - Manages a persistent vLLM server instance with health monitoring and auto-restart.

Usage:
    python -m olmocr.vllm_server_manager [model] [options]
    
Examples:
    # Start with default model
    python -m olmocr.vllm_server_manager
    
    # Start with specific model and options
    python -m olmocr.vllm_server_manager allenai/olmOCR-7B-0825-FP8 --port 8000 --tensor-parallel-size 2
    
    # Start with custom GPU memory utilization
    python -m olmocr.vllm_server_manager --gpu-memory-utilization 0.8
"""

import argparse
import asyncio
import atexit
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from typing import Optional

import httpx

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(console_handler)

# Also create a file handler for persistent logs
file_handler = logging.FileHandler("vllm-server-manager.log", mode="a")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(file_handler)


class VLLMServerManager:
    def __init__(
        self,
        model_name_or_path: str,
        port: int = 30024,
        tensor_parallel_size: int = 1,
        data_parallel_size: int = 1,
        gpu_memory_utilization: Optional[float] = None,
        max_model_len: Optional[int] = 16384,
        health_check_interval: int = 10,
        max_restart_attempts: int = 10,
        restart_delay: int = 10,
        extra_args: Optional[list] = None,
    ):
        self.model_name_or_path = model_name_or_path
        self.port = port
        self.tensor_parallel_size = tensor_parallel_size
        self.data_parallel_size = data_parallel_size
        self.gpu_memory_utilization = gpu_memory_utilization
        self.max_model_len = max_model_len
        self.health_check_interval = health_check_interval
        self.max_restart_attempts = max_restart_attempts
        self.restart_delay = restart_delay
        self.extra_args = extra_args or []
        
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.restart_count = 0
        self.last_health_check_success = None
        self.server_start_time = None
        self.total_requests_served = 0
        self.shutdown_requested = False
        
    def build_vllm_command(self) -> list:
        """Build the vLLM serve command with all parameters."""
        cmd = [
            "vllm",
            "serve",
            self.model_name_or_path,
            "--port",
            str(self.port),
            "--disable-log-requests",
            "--uvicorn-log-level",
            "warning",
            "--served-model-name",
            "olmocr",
            "--tensor-parallel-size",
            str(self.tensor_parallel_size),
            "--data-parallel-size",
            str(self.data_parallel_size),
        ]
        
        if self.gpu_memory_utilization is not None:
            cmd.extend(["--gpu-memory-utilization", str(self.gpu_memory_utilization)])
        
        if self.max_model_len is not None:
            cmd.extend(["--max-model-len", str(self.max_model_len)])
        
        # Add any extra arguments passed through
        cmd.extend(self.extra_args)
        
        return cmd
    
    async def start_server(self) -> bool:
        """Start the vLLM server process."""
        if self.proc and self.proc.returncode is None:
            logger.warning("Server is already running")
            return True
        
        cmd = self.build_vllm_command()
        logger.info(f"Starting vLLM server with command: {' '.join(cmd)}")
        
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            self.server_start_time = datetime.now()
            logger.info(f"vLLM server process started with PID {self.proc.pid}")
            
            # Register cleanup on exit
            def _kill_proc():
                if self.proc and self.proc.returncode is None:
                    try:
                        self.proc.terminate()
                        logger.info("vLLM process terminated on exit")
                    except:
                        pass
            
            atexit.register(_kill_proc)
            
            # Start log reader tasks
            asyncio.create_task(self._read_server_logs(self.proc.stdout, "stdout"))
            asyncio.create_task(self._read_server_logs(self.proc.stderr, "stderr"))
            
            # Wait for server to be ready
            if await self.wait_for_server_ready():
                logger.info("vLLM server is ready and accepting requests")
                return True
            else:
                logger.error("vLLM server failed to become ready")
                await self.stop_server()
                return False
                
        except Exception as e:
            logger.error(f"Failed to start vLLM server: {e}")
            return False
    
    async def stop_server(self):
        """Stop the vLLM server process."""
        if self.proc and self.proc.returncode is None:
            logger.info("Stopping vLLM server...")
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=10.0)
                logger.info("vLLM server stopped gracefully")
            except asyncio.TimeoutError:
                logger.warning("vLLM server did not stop gracefully, forcing kill")
                self.proc.kill()
                await self.proc.wait()
        
        self.proc = None
        self.server_start_time = None
    
    async def _read_server_logs(self, stream, stream_name):
        """Read and log server output."""
        while True:
            try:
                line = await stream.readline()
                if not line:
                    break
                
                line = line.decode("utf-8").rstrip()
                
                # Log to file at debug level, important lines to console
                logger.debug(f"[{stream_name}] {line}")
                
                # Check for important messages
                if "ERROR" in line or "CRITICAL" in line:
                    logger.error(f"[{stream_name}] {line}")
                elif "WARNING" in line:
                    logger.warning(f"[{stream_name}] {line}")
                elif any(msg in line for msg in [
                    "The server is fired up and ready to roll!",
                    "Starting vLLM API server",
                    "Uvicorn running on",
                ]):
                    logger.info(f"[{stream_name}] {line}")
                    
            except Exception as e:
                logger.error(f"Error reading {stream_name}: {e}")
                break
    
    async def check_health(self) -> bool:
        """Check if the vLLM server is healthy."""
        url = f"http://localhost:{self.port}/v1/models"
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                
                if response.status_code == 200:
                    # Try to parse the response to ensure it's valid
                    data = response.json()
                    if "data" in data:
                        self.last_health_check_success = datetime.now()
                        return True
                        
        except (httpx.RequestError, httpx.TimeoutException, json.JSONDecodeError) as e:
            logger.debug(f"Health check failed: {e}")
        
        return False
    
    async def wait_for_server_ready(self, max_wait_seconds: int = 300) -> bool:
        """Wait for the server to become ready."""
        start_time = time.time()
        
        while time.time() - start_time < max_wait_seconds:
            if await self.check_health():
                return True
            
            # Check if process has died
            if self.proc and self.proc.returncode is not None:
                logger.error(f"vLLM process died with return code {self.proc.returncode}")
                return False
            
            await asyncio.sleep(2)
        
        return False
    
    async def monitor_and_restart(self):
        """Main monitoring loop that checks health and restarts if needed."""
        consecutive_failures = 0
        max_consecutive_failures = 3
        
        while not self.shutdown_requested:
            await asyncio.sleep(self.health_check_interval)
            
            # Check if process is still alive
            if self.proc and self.proc.returncode is not None:
                logger.error(f"vLLM process died unexpectedly with return code {self.proc.returncode}")
                await self.handle_restart()
                consecutive_failures = 0
                continue
            
            # Perform health check
            if await self.check_health():
                if consecutive_failures > 0:
                    logger.info("Health check passed, server recovered")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.warning(f"Health check failed ({consecutive_failures}/{max_consecutive_failures})")
                
                if consecutive_failures >= max_consecutive_failures:
                    logger.error("Multiple consecutive health check failures, restarting server")
                    await self.handle_restart()
                    consecutive_failures = 0
    
    async def handle_restart(self):
        """Handle server restart with retry logic."""
        if self.shutdown_requested:
            return
        
        self.restart_count += 1
        
        if self.restart_count > self.max_restart_attempts:
            logger.critical(f"Maximum restart attempts ({self.max_restart_attempts}) exceeded, giving up")
            sys.exit(1)
        
        logger.info(f"Attempting restart {self.restart_count}/{self.max_restart_attempts}")
        
        # Stop the current server
        await self.stop_server()
        
        # Wait before restarting
        await asyncio.sleep(self.restart_delay)
        
        # Try to start the server again
        if not await self.start_server():
            logger.error("Failed to restart server")
            await asyncio.sleep(self.restart_delay * 2)  # Wait longer before next attempt
    
    async def get_status(self) -> dict:
        """Get current server status."""
        is_healthy = await self.check_health()
        
        status = {
            "healthy": is_healthy,
            "pid": self.proc.pid if self.proc else None,
            "port": self.port,
            "model": self.model_name_or_path,
            "restart_count": self.restart_count,
            "uptime_seconds": (
                (datetime.now() - self.server_start_time).total_seconds()
                if self.server_start_time
                else 0
            ),
            "last_health_check": (
                self.last_health_check_success.isoformat()
                if self.last_health_check_success
                else None
            ),
        }
        
        return status
    
    async def run(self):
        """Main entry point to run the server manager."""
        logger.info("=" * 60)
        logger.info("vLLM Server Manager Starting")
        logger.info("=" * 60)
        logger.info(f"Model: {self.model_name_or_path}")
        logger.info(f"Port: {self.port}")
        logger.info(f"Tensor Parallel Size: {self.tensor_parallel_size}")
        logger.info(f"Data Parallel Size: {self.data_parallel_size}")
        if self.gpu_memory_utilization:
            logger.info(f"GPU Memory Utilization: {self.gpu_memory_utilization}")
        logger.info(f"Max Model Length: {self.max_model_len}")
        logger.info(f"Health Check Interval: {self.health_check_interval}s")
        logger.info("=" * 60)
        
        # Start the server
        if not await self.start_server():
            logger.critical("Failed to start vLLM server on initial attempt")
            sys.exit(1)
        
        # Start monitoring
        monitor_task = asyncio.create_task(self.monitor_and_restart())
        
        # Setup signal handlers for graceful shutdown
        def signal_handler(sig, frame):
            logger.info(f"Received signal {sig}, initiating shutdown...")
            self.shutdown_requested = True
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Status reporting loop
        last_status_report = time.time()
        status_report_interval = 60  # Report status every minute
        
        try:
            while not self.shutdown_requested:
                await asyncio.sleep(1)
                
                # Periodic status report
                if time.time() - last_status_report > status_report_interval:
                    status = await self.get_status()
                    logger.info(f"Status: {json.dumps(status, indent=2)}")
                    last_status_report = time.time()
        
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        
        finally:
            logger.info("Shutting down...")
            self.shutdown_requested = True
            monitor_task.cancel()
            
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            
            await self.stop_server()
            logger.info("Shutdown complete")


async def main():
    parser = argparse.ArgumentParser(
        description="vLLM Server Manager - Manages a persistent vLLM server with health monitoring and auto-restart"
    )
    
    parser.add_argument(
        "model",
        nargs="?",
        default="allenai/olmOCR-7B-0825-FP8",
        help="Model name or path (default: allenai/olmOCR-7B-0825-FP8)",
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=30024,
        help="Port to run the vLLM server on (default: 30024)",
    )
    
    parser.add_argument(
        "--tensor-parallel-size",
        "-tp",
        type=int,
        default=1,
        help="Tensor parallel size for vLLM (default: 1)",
    )
    
    parser.add_argument(
        "--data-parallel-size",
        "-dp",
        type=int,
        default=1,
        help="Data parallel size for vLLM (default: 1)",
    )
    
    parser.add_argument(
        "--gpu-memory-utilization",
        type=float,
        default=None,
        help="GPU memory utilization for vLLM (0.0-1.0)",
    )
    
    parser.add_argument(
        "--max-model-len",
        type=int,
        default=16384,
        help="Maximum model context length (default: 16384)",
    )
    
    parser.add_argument(
        "--health-check-interval",
        type=int,
        default=10,
        help="Health check interval in seconds (default: 10)",
    )
    
    parser.add_argument(
        "--max-restart-attempts",
        type=int,
        default=10,
        help="Maximum number of restart attempts (default: 10)",
    )
    
    parser.add_argument(
        "--restart-delay",
        type=int,
        default=10,
        help="Delay between restart attempts in seconds (default: 10)",
    )
    
    # Parse known args and collect the rest for vLLM
    args, unknown_args = parser.parse_known_args()
    
    # Create and run the server manager
    manager = VLLMServerManager(
        model_name_or_path=args.model,
        port=args.port,
        tensor_parallel_size=args.tensor_parallel_size,
        data_parallel_size=args.data_parallel_size,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_model_len=args.max_model_len,
        health_check_interval=args.health_check_interval,
        max_restart_attempts=args.max_restart_attempts,
        restart_delay=args.restart_delay,
        extra_args=unknown_args,
    )
    
    await manager.run()


if __name__ == "__main__":
    asyncio.run(main())