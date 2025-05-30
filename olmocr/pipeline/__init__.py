"""
OLMoCR Pipeline Package

This package provides a modular, maintainable implementation of the olmOCR
document processing pipeline. The pipeline is broken down into focused modules:

- core: Main orchestration and workflow coordination
- processing: Page and document processing logic
- workers: Worker management and parallel processing
- http_client: HTTP communication with SGLang backend
- document_builder: Dolma document creation and formatting

The package maintains 100% backward compatibility with the original monolithic
pipeline.py implementation while providing better separation of concerns,
improved testability, and enhanced maintainability.
"""

# Import main classes and functions for easy access
from .core import PipelineOrchestrator, create_pipeline_orchestrator
from .document_builder import (
    DolmaDocumentBuilder, 
    PageResult, 
    create_document_builder,
    build_dolma_document  # Legacy compatibility
)
from .http_client import (
    SGLangHTTPClient, 
    create_sglang_client,
    apost  # Legacy compatibility
)
from .processing import (
    PageProcessor,
    DocumentProcessor,
    create_page_processor,
    create_document_processor
)
from .workers import (
    WorkerManager,
    create_worker_manager
)

# Version information
__version__ = "1.0.0"
__author__ = "OLMoCR Team"

# Public API
__all__ = [
    # Core orchestration
    "PipelineOrchestrator",
    "create_pipeline_orchestrator",
    
    # Document building
    "DolmaDocumentBuilder",
    "PageResult", 
    "create_document_builder",
    "build_dolma_document",  # Legacy
    
    # HTTP client
    "SGLangHTTPClient",
    "create_sglang_client", 
    "apost",  # Legacy
    
    # Processing
    "PageProcessor",
    "DocumentProcessor",
    "create_page_processor",
    "create_document_processor",
    
    # Workers
    "WorkerManager",
    "create_worker_manager",
]

# Legacy imports for backward compatibility
# These allow existing code to import from the package root
def _setup_legacy_imports():
    """Set up legacy imports for backward compatibility."""
    import sys
    current_module = sys.modules[__name__]
    
    # Make legacy functions available at package level
    current_module.apost = apost
    current_module.build_dolma_document = build_dolma_document
    current_module.PageResult = PageResult

_setup_legacy_imports()
