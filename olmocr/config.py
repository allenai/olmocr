"""Configuration dataclass for the OlmoCR pipeline."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PipelineConfig:
    """
    Configuration for the OlmoCR pipeline.

    This provides a type-safe, programmatic interface to configure the pipeline
    instead of using CLI arguments and subprocess calls.

    Example:
        >>> import asyncio
        >>> from olmocr import run_pipeline, PipelineConfig
        >>>
        >>> config = PipelineConfig(
        ...     workspace="./workspace",
        ...     pdfs=["doc1.pdf", "doc2.pdf"],
        ...     custom_prompt="Extract text from this legal document...",
        ...     markdown=True
        ... )
        >>> asyncio.run(run_pipeline(config))
    """

    # Required arguments
    workspace: str
    """Filesystem path where work will be stored (local folder or s3://bucket/prefix/)"""

    # PDF inputs
    pdfs: Optional[list[str]] = None
    """List of PDF paths (can include globs like s3://bucket/*.pdf)"""

    # Model configuration
    model: str = "allenai/olmOCR-2-7B-1025-FP8"
    """Path to model (local, s3, or HuggingFace)"""

    custom_prompt: Optional[str] = None
    """
    Custom prompt to use for OCR extraction. If None, uses the default prompt.
    The prompt should instruct the model how to extract text from document pages.
    """

    # Server configuration
    server: Optional[str] = None
    """URL of external vLLM server (e.g., http://hostname:port/v1). If None, spawns local server."""

    api_key: Optional[str] = None
    """API key for authenticated remote servers (e.g., DeepInfra)"""

    # Processing options
    workers: int = 20
    """Number of concurrent workers"""

    max_concurrent_work_items: int = 1
    """Max work items to process concurrently (1 for local GPU, higher for external APIs)"""

    max_tokens: int = 8000
    """Maximum tokens to generate per page (increase for dense documents, e.g., 12000 or 16000)"""

    max_page_retries: int = 8
    """Max number of times to retry rendering a page"""

    max_page_error_rate: float = 0.004
    """Rate of allowable failed pages in a document (default: 1/250)"""

    target_longest_image_dim: int = 1288
    """Dimension on longest side for rendering PDF pages"""

    target_anchor_text_len: int = -1
    """Maximum amount of anchor text to use (characters), -1 for new models"""

    apply_filter: bool = False
    """Apply basic filtering to English PDFs (not forms, not SEO spam)"""

    markdown: bool = False
    """Also write natural text to markdown files preserving folder structure"""

    guided_decoding: bool = False
    """Enable guided decoding for model YAML type outputs"""

    stats: bool = False
    """Instead of running pipeline, report statistics about workspace"""

    # S3 profiles
    workspace_profile: Optional[str] = None
    """S3 configuration profile for accessing the workspace"""

    pdf_profile: Optional[str] = None
    """S3 configuration profile for accessing raw PDF documents"""

    pages_per_group: Optional[int] = None
    """Number of PDF pages per work item group (auto-calculated if None)"""

    # VLLM configuration
    gpu_memory_utilization: Optional[float] = None
    """Fraction of VRAM vLLM may pre-allocate for KV-cache"""

    max_model_len: int = 16384
    """Upper bound (tokens) vLLM will allocate KV-cache for"""

    tensor_parallel_size: int = 1
    """Tensor parallel size for vLLM"""

    data_parallel_size: int = 1
    """Data parallel size for vLLM"""

    port: int = 30024
    """Port to use for the VLLM server"""

    # Backend selection
    backend: str = "vllm"
    """Inference backend to use: "vllm" (NVIDIA GPUs) or "mlx-vlm" (Apple Silicon)"""

    # MLX-specific configuration
    mlx_quantization: Optional[str] = None
    """MLX model quantization: "4bit", "8bit", "mixed_4_8", etc."""

    mlx_kv_bits: Optional[int] = None
    """MLX KV-cache quantization bits (1, 2, 4, 8)"""

    # Beaker/cluster execution (usually not needed for programmatic use)
    beaker: bool = False
    """Submit this job to Beaker instead of running locally"""

    beaker_workspace: str = "ai2/olmocr"
    """Beaker workspace to submit to"""

    beaker_cluster: list[str] = field(
        default_factory=lambda: ["ai2/jupiter", "ai2/ceres", "ai2/neptune", "ai2/saturn"]
    )
    """Beaker clusters to run on"""

    beaker_gpus: int = 1
    """Number of GPU replicas to run"""

    beaker_priority: str = "normal"
    """Beaker priority level for the job"""

    def __post_init__(self):
        """Validate configuration after initialization."""
        # Auto-calculate pages_per_group if not set
        if self.pages_per_group is None:
            # Use smaller groups for external APIs to avoid wasting money
            self.pages_per_group = 50 if self.api_key is not None else 500

        # Validate workspace
        if not self.workspace:
            raise ValueError("workspace is required")

        # Validate that we have PDFs to process (unless running stats)
        if not self.stats and not self.pdfs:
            raise ValueError("pdfs list is required when not running stats")

        # Validate backend
        if self.backend not in ["vllm", "mlx-vlm"]:
            raise ValueError(f"Invalid backend: {self.backend}. Must be 'vllm' or 'mlx-vlm'")

        # Platform checks for mlx-vlm
        if self.backend == "mlx-vlm":
            import platform

            if platform.system() != "Darwin":
                raise ValueError(
                    f"mlx-vlm backend only supports macOS. "
                    f"Current platform: {platform.system()}. "
                    f"Use --backend vllm for Linux/Windows."
                )

            if platform.machine() not in ["arm64", "aarch64"]:
                raise ValueError(
                    f"mlx-vlm backend requires Apple Silicon (M-series chips). "
                    f"Detected architecture: {platform.machine()}"
                )

            # Check if mlx-vlm is installed
            try:
                import mlx_vlm
            except ImportError:
                raise ValueError(
                    "mlx-vlm not installed. Install with: pip install mlx-vlm\n"
                    "Or install olmocr with MLX support: pip install olmocr[mlx]"
                )
