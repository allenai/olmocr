# Tencent Cloud Batch Compute Optimization

This directory contains optimizations for running olmOCR on Tencent Cloud Batch Compute, addressing key performance and compatibility issues.

## Problems Solved

### 1. Cloud-init Compatibility
- **Issue**: Official olmOCR Docker image lacks cloud-init service required by Tencent Cloud Batch Compute
- **Solution**: Added cloud-init installation and configuration in `Dockerfile.tencent`

### 2. Model Download Performance
- **Issue**: Models (~15GB) download on first use, causing slow batch job startup
- **Solution**: Pre-download models during image build:
  - `allenai/olmOCR-7B-0825-FP8` (main model)
  - `allenai/olmOCR-bench` (benchmark dataset)

## Usage

### Building the Image

```bash
# Build with default tag (latest)
./docker-build-tencent.sh

# Build with specific tag
./docker-build-tencent.sh v1.0
```

### Testing Locally

```bash
# Test the image
docker run -it --gpus all olmocr-tencent:latest /bin/bash

# Inside container, verify models are pre-downloaded
ls -la /root/.cache/huggingface/hub/
python3 -m olmocr.pipeline --help
```

### Deploying to Tencent Cloud

1. **Push to Registry**:
```bash
# Tag for your registry
docker tag olmocr-tencent:latest your-registry.com/olmocr-tencent:latest

# Push to registry
docker push your-registry.com/olmocr-tencent:latest
```

2. **Configure Batch Compute Job**:
```json
{
  "JobName": "olmocr-batch-job",
  "JobQueue": "your-queue",
  "JobDefinition": {
    "JobDefinitionName": "olmocr-job-def",
    "Type": "container",
    "Parameters": {},
    "ContainerProperties": {
      "Image": "your-registry.com/olmocr-tencent:latest",
      "Vcpus": 4,
      "Memory": 32768,
      "JobRoleArn": "your-job-role",
      "Environment": [
        {
          "Name": "CUDA_VISIBLE_DEVICES",
          "Value": "0"
        }
      ],
      "MountPoints": [
        {
          "SourceVolume": "input-data",
          "ContainerPath": "/input",
          "ReadOnly": true
        },
        {
          "SourceVolume": "output-data",
          "ContainerPath": "/output",
          "ReadOnly": false
        }
      ]
    }
  }
}
```

3. **Example Batch Job Command**:
```bash
python3 -m olmocr.pipeline /output --markdown --pdfs /input/*.pdf
```

## Key Optimizations

### Pre-downloaded Models
Models are cached at `/root/.cache/huggingface/` during image build:
- **Hub cache**: `/root/.cache/huggingface/hub/`
- **Datasets cache**: `/root/.cache/huggingface/datasets/`

### Cloud-init Services
The following cloud-init services are enabled:
- `cloud-init-local.service`
- `cloud-init.service`
- `cloud-config.service`
- `cloud-final.service`

### Environment Variables
- `HF_HOME=/root/.cache/huggingface`
- `HF_HUB_CACHE=/root/.cache/huggingface/hub`
- `HF_DATASETS_CACHE=/root/.cache/huggingface/datasets`

## Performance Benefits

- **Faster Job Startup**: No model downloads during job execution
- **Reduced Network Usage**: Models downloaded once during image build
- **Improved Reliability**: No dependency on internet connectivity during batch jobs
- **Cost Efficiency**: Faster job completion reduces compute costs

## Size Considerations

The optimized image will be significantly larger (~20-25GB) due to pre-downloaded models, but this trade-off provides:
- Faster batch job execution
- More predictable performance
- Reduced failure rates from network issues

## Troubleshooting

### Cloud-init Issues
```bash
# Check cloud-init status
cloud-init status

# View cloud-init logs
journalctl -u cloud-init
```

### Model Cache Issues
```bash
# Verify model cache
ls -la /root/.cache/huggingface/hub/
python3 -c "from huggingface_hub import cached_assets_path; print(cached_assets_path())"
```

### GPU Access
```bash
# Check GPU availability
nvidia-smi
python3 -c "import torch; print(torch.cuda.is_available())"
```