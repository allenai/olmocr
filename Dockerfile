FROM vllm/vllm-openai:v0.12.0

ENV PYTHON_VERSION=3.12
ENV CUSTOM_PY="/usr/bin/python${PYTHON_VERSION}"

# Workaround for installing fonts, which are needed for good rendering of documents
RUN DIST_PY=$(ls /usr/bin/python3.[0-9]* | sort -V | head -n1) && \
    # If a python alternative scheme already exists, remember its value so we \
    # can restore it later; otherwise, we will restore to CUSTOM_PY when we \
    # are done. \
    if update-alternatives --query python3 >/dev/null 2>&1; then \
        ORIGINAL_PY=$(update-alternatives --query python3 | awk -F": " '/Value:/ {print $2}'); \
    else \
        ORIGINAL_PY=$CUSTOM_PY; \
    fi && \
    # ---- APT operations that require the distro python3 ------------------- \
    echo "Temporarily switching python3 alternative to ${DIST_PY} so that APT scripts use the distro‑built Python runtime." && \
    update-alternatives --install /usr/bin/python3 python3 ${DIST_PY} 1 && \
    update-alternatives --set python3 ${DIST_PY} && \
    update-alternatives --install /usr/bin/python python ${DIST_PY} 1 && \
    update-alternatives --set python ${DIST_PY} && \
    apt-get update -y && \
    apt-get remove -y python3-blinker || true && \
    # Pre‑seed the Microsoft Core Fonts EULA so the build is non‑interactive \
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3-apt \
        update-notifier-common \
        poppler-utils \
        fonts-crosextra-caladea \
        fonts-crosextra-carlito \
        gsfonts \
        lcdf-typetools \
        ttf-mscorefonts-installer \
        git git-lfs curl wget unzip && \
    # ---- Restore the original / custom Python alternative ----------------- \
    echo "Restoring python3 alternative to ${ORIGINAL_PY}" && \
    update-alternatives --install /usr/bin/python3 python3 ${ORIGINAL_PY} 1 && \
    update-alternatives --set python3 ${ORIGINAL_PY} && \
    update-alternatives --install /usr/bin/python python ${ORIGINAL_PY} 1 || true && \
    update-alternatives --set python ${ORIGINAL_PY} || true && \
    # Ensure pip is available for the restored Python \
    curl -sS https://bootstrap.pypa.io/get-pip.py | ${ORIGINAL_PY}

# keep the build context clean
WORKDIR /build          
COPY . /build

# Needed to resolve setuptools dependencies
ENV UV_INDEX_STRATEGY="unsafe-best-match"
RUN uv pip install --system --no-cache ".[bench]"

RUN playwright install-deps
RUN playwright install chromium

RUN python3 -m olmocr.pipeline --help

# Override the vLLM base image's entrypoint to allow interactive bash access
ENTRYPOINT ["/bin/bash"]