ARG VLLM_VERSION=v0.10.2
FROM --platform=linux/amd64 vllm/vllm-openai:${VLLM_VERSION}


# Set environment variable to prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# olmOCR Specific Installs - Install fonts BEFORE changing Python version
RUN echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections && \
    apt-get update -y && \
    apt-get install -y --no-install-recommends poppler-utils fonts-crosextra-caladea fonts-crosextra-carlito gsfonts lcdf-typetools ttf-mscorefonts-installer


# Install uv for faster pip installs
RUN --mount=type=cache,target=/root/.cache/uv python3 -m pip install uv

# Install some helper utilities for things like the benchmark
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    git \
    git-lfs \
    curl \
    wget \
    unzip

ENV PYTHONUNBUFFERED=1

# keep the build context clean
WORKDIR /build          
COPY . /build


# Needed to resolve setuptools dependencies
ENV UV_INDEX_STRATEGY="unsafe-best-match"
RUN uv pip install --system --no-cache ".[bench]"

RUN playwright install-deps
RUN playwright install chromium

RUN python3 -m olmocr.pipeline --help