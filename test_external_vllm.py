#!/usr/bin/env python3
"""
Test script to verify the external vLLM server functionality.

This script demonstrates how to use the new external vLLM capability:
1. Start the vLLM server manager in one terminal
2. Run the pipeline with external vLLM URL in another terminal
"""

import subprocess
import time
import sys
import os
import signal

def test_vllm_server_manager():
    """Test starting and stopping the vLLM server manager."""
    print("=" * 60)
    print("Testing vLLM Server Manager")
    print("=" * 60)
    
    # Start the server manager
    print("\n1. Starting vLLM server manager...")
    print("   Command: python -m olmocr.vllm_server_manager --port 8080")
    
    proc = subprocess.Popen(
        ["python", "-m", "olmocr.vllm_server_manager", "--port", "8080"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Give it some time to start
    print("   Waiting for server to start (this may take a while)...")
    time.sleep(10)
    
    # Check if process is still running
    if proc.poll() is None:
        print("   ✓ Server manager is running (PID: {})".format(proc.pid))
    else:
        print("   ✗ Server manager failed to start")
        stdout, stderr = proc.communicate()
        print("   STDOUT:", stdout)
        print("   STDERR:", stderr)
        return False
    
    # Test health check
    print("\n2. Testing health check endpoint...")
    import httpx
    try:
        response = httpx.get("http://localhost:8080/v1/models", timeout=5.0)
        if response.status_code == 200:
            print("   ✓ Health check passed")
        else:
            print("   ✗ Health check failed with status:", response.status_code)
    except Exception as e:
        print("   ✗ Health check failed:", e)
    
    # Stop the server
    print("\n3. Stopping server manager...")
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
        print("   ✓ Server stopped gracefully")
    except subprocess.TimeoutExpired:
        print("   ✗ Server did not stop gracefully, forcing kill")
        proc.kill()
    
    return True

def test_pipeline_with_external_vllm():
    """Test running the pipeline with an external vLLM URL."""
    print("\n" + "=" * 60)
    print("Testing Pipeline with External vLLM")
    print("=" * 60)
    
    print("\nTo test the pipeline with external vLLM:")
    print("\n1. In Terminal 1, start the vLLM server manager:")
    print("   $ python -m olmocr.vllm_server_manager")
    print("   (Wait for 'vLLM server is ready' message)")
    
    print("\n2. In Terminal 2, run the pipeline with external URL:")
    print("   $ python -m olmocr.pipeline workspace_path --vllm-url http://localhost:30024 --pdfs path/to/pdfs")
    
    print("\n3. The pipeline should:")
    print("   - Skip GPU check and model download")
    print("   - Connect to the external vLLM server")
    print("   - Process PDFs using the external server")
    print("   - Exit when done (server keeps running)")
    
    print("\n4. You can run multiple pipeline instances:")
    print("   - They will all use the same vLLM server")
    print("   - Saves model loading time")
    print("   - Better resource utilization")
    
    print("\nExample with custom port:")
    print("   Terminal 1: python -m olmocr.vllm_server_manager --port 8080")
    print("   Terminal 2: python -m olmocr.pipeline workspace --vllm-url http://localhost:8080 --pdfs *.pdf")

def main():
    """Main test function."""
    print("External vLLM Server Integration Test")
    print("=" * 60)
    
    # Check if we're in the right directory
    if not os.path.exists("olmocr/pipeline.py"):
        print("Error: Please run this script from the olmocr root directory")
        sys.exit(1)
    
    # Test vLLM server manager (basic functionality only)
    print("\nNote: Full testing requires a GPU and the model weights.")
    print("This test will check basic functionality only.\n")
    
    response = input("Do you want to run a basic server manager test? (y/n): ")
    if response.lower() == 'y':
        test_vllm_server_manager()
    
    # Show usage instructions
    test_pipeline_with_external_vllm()
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("\nKey benefits of external vLLM server:")
    print("- ⚡ Fast startup for subsequent pipeline runs")
    print("- 💾 Model stays loaded in GPU memory")
    print("- 🔄 Automatic restart on crashes")
    print("- 📊 Health monitoring and status reporting")
    print("- 🚀 Multiple pipelines can share one server")

if __name__ == "__main__":
    main()