# External vLLM Server Support

This document describes how to use the new external vLLM server functionality with the OlmOCR pipeline.

## Overview

The pipeline now supports using an external vLLM server instead of starting one internally. This provides several benefits:

- **Faster startup**: No need to reload the model for each pipeline run
- **Resource efficiency**: Model stays loaded in GPU memory between runs
- **Multiple pipelines**: Several pipeline instances can share the same server
- **Better stability**: Server automatically restarts on crashes
- **Easier debugging**: Server logs are separate from pipeline logs

## Components

### 1. vLLM Server Manager (`vllm_server_manager.py`)

A standalone script that manages a persistent vLLM server with:
- Health monitoring every 10 seconds
- Automatic restart on crashes (up to 10 attempts)
- Status reporting
- Graceful shutdown handling

### 2. Pipeline External URL Support

The pipeline now accepts a `--vllm-url` flag to use an external server instead of starting its own.

## Usage

### Starting the vLLM Server Manager

In Terminal 1, start the server manager:

```bash
# With default settings (port 30024, default model)
python -m olmocr.vllm_server_manager

# With custom port
python -m olmocr.vllm_server_manager --port 8080

# With specific model
python -m olmocr.vllm_server_manager allenai/olmOCR-7B-0825-FP8

# With custom GPU memory utilization
python -m olmocr.vllm_server_manager --gpu-memory-utilization 0.8

# With tensor parallelism
python -m olmocr.vllm_server_manager --tensor-parallel-size 2

# Full example with multiple options
python -m olmocr.vllm_server_manager \
    allenai/olmOCR-7B-0825-FP8 \
    --port 8080 \
    --tensor-parallel-size 2 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 16384 \
    --health-check-interval 5
```

Wait for the message: `vLLM server is ready and accepting requests`

### Running the Pipeline with External vLLM

In Terminal 2, run the pipeline with the external server:

```bash
# Basic usage
python -m olmocr.pipeline workspace_path \
    --vllm-url http://localhost:30024 \
    --pdfs path/to/pdfs/*.pdf

# With custom port
python -m olmocr.pipeline workspace_path \
    --vllm-url http://localhost:8080 \
    --pdfs s3://bucket/pdfs/*.pdf

# Multiple workers
python -m olmocr.pipeline workspace_path \
    --vllm-url http://localhost:30024 \
    --pdfs document_list.txt \
    --workers 40
```

### Running Multiple Pipeline Instances

You can run multiple pipeline instances against the same server:

```bash
# Terminal 2
python -m olmocr.pipeline workspace1 --vllm-url http://localhost:30024 --pdfs batch1/*.pdf

# Terminal 3
python -m olmocr.pipeline workspace2 --vllm-url http://localhost:30024 --pdfs batch2/*.pdf

# Terminal 4
python -m olmocr.pipeline workspace3 --vllm-url http://localhost:30024 --pdfs batch3/*.pdf
```

## Server Manager Options

| Option | Default | Description |
|--------|---------|-------------|
| `model` | allenai/olmOCR-7B-0825-FP8 | Model name or path |
| `--port` | 30024 | Port for the vLLM server |
| `--tensor-parallel-size` | 1 | Tensor parallel size |
| `--data-parallel-size` | 1 | Data parallel size |
| `--gpu-memory-utilization` | None | GPU memory fraction (0.0-1.0) |
| `--max-model-len` | 16384 | Maximum model context length |
| `--health-check-interval` | 10 | Health check interval (seconds) |
| `--max-restart-attempts` | 10 | Maximum restart attempts |
| `--restart-delay` | 10 | Delay between restarts (seconds) |

## Monitoring

### Server Logs

The server manager creates two log destinations:
- **Console**: INFO level messages
- **File**: `vllm-server-manager.log` with DEBUG level

### Status Reports

The server manager prints status reports every minute:
```json
{
  "healthy": true,
  "pid": 12345,
  "port": 30024,
  "model": "allenai/olmOCR-7B-0825-FP8",
  "restart_count": 0,
  "uptime_seconds": 3600.5,
  "last_health_check": "2024-01-15T10:30:45"
}
```

### Health Check Endpoint

You can manually check server health:
```bash
curl http://localhost:30024/v1/models
```

## Error Handling

### Model Verification

The pipeline verifies that the external vLLM server has the correct model loaded:
- Checks for model with name "olmocr" (the served-model-name)
- Fails fast if wrong model is loaded
- Ensures compatibility before processing

### Connection Failures

The pipeline will retry connecting to the external server:
- Initial connection: 10 attempts with exponential backoff
- Per-request failures: Automatic retry with health check
- Maximum 60-second delay between retries
- Verifies model availability on each health check

### Server Crashes

The server manager will:
1. Detect the crash within 10 seconds (configurable)
2. Wait for the restart delay (default 10 seconds)
3. Attempt to restart the server
4. Give up after max attempts (default 10)

### Graceful Shutdown

To stop the server manager:
- Press Ctrl+C (SIGINT)
- Send SIGTERM signal
- The server will shut down gracefully

## Comparison with Internal Server

| Aspect | Internal Server | External Server |
|--------|----------------|-----------------|
| Startup time | Slow (model loading) | Fast (already loaded) |
| Memory usage | Released on exit | Persistent |
| Multiple pipelines | Not supported | Supported |
| Crash recovery | Limited (5 retries) | Robust (configurable) |
| Monitoring | Mixed with pipeline logs | Separate logs |
| Configuration | Per pipeline run | Once at server start |

## Best Practices

1. **Production Use**: Run the server manager with systemd or supervisor for automatic restart
2. **Resource Planning**: Account for persistent GPU memory usage
3. **Port Selection**: Use non-standard ports to avoid conflicts
4. **Health Monitoring**: Set up external monitoring for the health endpoint
5. **Log Rotation**: Configure log rotation for the server manager log file

## Troubleshooting

### Server won't start
- Check GPU availability: `nvidia-smi`
- Verify model path/name
- Check port availability: `lsof -i :30024`
- Review logs in `vllm-server-manager.log`

### Pipeline can't connect
- Verify server is running: `ps aux | grep vllm_server_manager`
- Check health endpoint: `curl http://localhost:30024/v1/models`
- Verify model is loaded: Check that response includes "olmocr" in model list
- Ensure firewall allows connection
- Check URL format in `--vllm-url`

### Model mismatch error
If you see "External vLLM server is running but doesn't have the 'olmocr' model":
- The server must be started with `--served-model-name olmocr`
- This is automatically done by vllm_server_manager.py
- If using a custom vLLM server, add this flag

### Poor performance
- Monitor GPU utilization: `nvidia-smi -l 1`
- Adjust `--gpu-memory-utilization`
- Consider `--tensor-parallel-size` for large models
- Check server logs for warnings

## Example Workflow

```bash
# 1. Start server (Terminal 1)
python -m olmocr.vllm_server_manager --gpu-memory-utilization 0.9

# 2. Wait for ready message
# "vLLM server is ready and accepting requests"

# 3. Process first batch (Terminal 2)
python -m olmocr.pipeline workspace1 \
    --vllm-url http://localhost:30024 \
    --pdfs batch1/*.pdf \
    --workers 30

# 4. Process second batch (Terminal 3) - no model reload!
python -m olmocr.pipeline workspace2 \
    --vllm-url http://localhost:30024 \
    --pdfs batch2/*.pdf \
    --workers 30

# 5. Stop server when done (Terminal 1)
# Press Ctrl+C
```

## Future Enhancements

Potential improvements for consideration:
- Remote server support (not just localhost)
- Load balancing across multiple servers
- Authentication/authorization
- Metrics endpoint for Prometheus
- WebSocket for real-time status updates
- Queue management for request prioritization