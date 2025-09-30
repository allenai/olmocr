#!/bin/bash

# Build script for Tencent Cloud optimized olmOCR Docker image
# This script builds a Docker image with:
# 1. Pre-downloaded models to avoid runtime downloads
# 2. Cloud-init support for Tencent Cloud batch compute

set -e

# Configuration
IMAGE_NAME="olmocr-tencent"
IMAGE_TAG="${1:-latest}"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building Tencent Cloud optimized olmOCR Docker image..."
echo "Image name: ${FULL_IMAGE_NAME}"

# Build the image
docker build \
    -f Dockerfile.tencent \
    -t "${FULL_IMAGE_NAME}" \
    --progress=plain \
    .

echo "Build completed successfully!"
echo "Image: ${FULL_IMAGE_NAME}"

# Display image size
echo ""
echo "Image size:"
docker images "${IMAGE_NAME}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"

echo ""
echo "To test the image locally:"
echo "docker run -it --gpus all ${FULL_IMAGE_NAME} /bin/bash"

echo ""
echo "To push to a registry:"
echo "docker tag ${FULL_IMAGE_NAME} your-registry/${FULL_IMAGE_NAME}"
echo "docker push your-registry/${FULL_IMAGE_NAME}"