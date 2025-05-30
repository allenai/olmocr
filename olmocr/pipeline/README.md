# OLMoCR Pipeline - Modular Architecture

This directory contains the refactored, modular implementation of the OLMoCR document processing pipeline. The original monolithic `pipeline.py` (1,181 lines) has been broken down into focused, maintainable modules while preserving 100% backward compatibility.

## 🏗️ Architecture Overview

The pipeline is now organized into six focused modules, each with a single responsibility:

```
olmocr/pipeline/
├── __init__.py              # Package interface & factory functions
├── core.py                  # Pipeline orchestration & lifecycle management
├── processing.py            # Page & document processing logic
├── workers.py               # Parallel worker management
├── http_client.py           # SGLang HTTP communication
└── document_builder.py      # Dolma document creation & validation
```

## 📦 Module Responsibilities

### `core.py` - Pipeline Orchestration
- **Purpose**: Main pipeline coordination and lifecycle management
- **Key Classes**: `PipelineOrchestrator`
- **Responsibilities**:
  - Component initialization and dependency injection
  - SGLang server management and monitoring
  - Resource cleanup and lifecycle management
  - Configuration management

### `processing.py` - Core Processing Logic
- **Purpose**: Page and document processing workflows
- **Key Classes**: `PageProcessor`, `DocumentProcessor`
- **Responsibilities**:
  - PDF page query building with image rendering
  - Model inference coordination and retry logic
  - Error handling and fallback processing
  - Document-level processing orchestration

### `workers.py` - Worker Management
- **Purpose**: Parallel processing coordination
- **Key Classes**: `WorkerManager`
- **Responsibilities**:
  - Work queue management and distribution
  - Result collection and aggregation
  - Output writing (JSONL and Markdown)
  - S3 and local storage operations

### `http_client.py` - HTTP Communication
- **Purpose**: SGLang server communication
- **Key Classes**: `SGLangHTTPClient`
- **Responsibilities**:
  - Lightweight asyncio-based HTTP client
  - Connection management and cleanup
  - Request/response handling
  - Error handling and retry logic

### `document_builder.py` - Document Creation
- **Purpose**: Dolma document construction and validation
- **Key Classes**: `DolmaDocumentBuilder`, `PageResult`
- **Responsibilities**:
  - Document assembly from page results
  - Metadata generation and validation
  - Text span tracking for page boundaries
  - Document ID generation and validation

### `__init__.py` - Package Interface
- **Purpose**: Clean API and backward compatibility
- **Responsibilities**:
  - Factory functions for all components
  - Legacy function re-exports
  - Package-level documentation

## 🔄 Backward Compatibility

The refactoring maintains 100% backward compatibility. Existing code continues to work unchanged:

```python
# Original usage (still works)
from olmocr.pipeline import PageResult, build_dolma_document, apost, main

# New modular usage (for new development)
from olmocr.pipeline.core import create_pipeline_orchestrator
from olmocr.pipeline.document_builder import DolmaDocumentBuilder
from olmocr.pipeline.http_client import SGLangHTTPClient
```

## 🚀 Usage Examples

### Using the Original Interface
```python
# Existing code works unchanged
from olmocr.pipeline import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
```

### Using the New Modular Interface
```python
from olmocr.pipeline.core import create_pipeline_orchestrator
from olmocr.pipeline.document_builder import create_document_builder
from olmocr.pipeline.http_client import create_sglang_client

async def main():
    # Create components
    orchestrator = create_pipeline_orchestrator()
    await orchestrator.initialize(args)
    
    # Use individual components as needed
    http_client = await create_sglang_client(port=30024)
    document_builder = create_document_builder()
    
    # ... rest of pipeline logic
```

### Factory Functions
Each module provides factory functions for clean component creation:

```python
# HTTP Client
http_client = await create_sglang_client(port=30024)

# Document Builder
document_builder = create_document_builder()

# Page Processor
page_processor = create_page_processor(http_client, process_pool, metrics, tracker)

# Document Processor
document_processor = create_document_processor(page_processor, document_builder)

# Worker Manager
worker_manager = create_worker_manager(document_processor, metrics, tracker, s3_clients)

# Pipeline Orchestrator
orchestrator = create_pipeline_orchestrator()
```

## 🧪 Testing

The modular architecture enables comprehensive testing:

- **Unit Tests**: Each module can be tested in isolation
- **Integration Tests**: Component interactions are verified
- **Backward Compatibility Tests**: Original API is validated
- **Performance Tests**: No regression in processing speed

Run the test suite:
```bash
pytest tests/test_pipeline_*.py -v
```

## 📊 Benefits

### Maintainability
- **Single Responsibility**: Each module has one clear purpose
- **Reduced Complexity**: Smaller, focused code units (150-400 lines each)
- **Clear Interfaces**: Well-defined APIs between components
- **Better Documentation**: Module-level docs and type hints

### Testability
- **Unit Testing**: Individual components tested in isolation
- **Mocking**: Clean interfaces enable easy test mocking
- **Integration Testing**: Component interactions verified
- **Regression Testing**: Changes tested without full system setup

### Extensibility
- **Plugin Architecture**: New components added easily
- **Dependency Injection**: Components swapped or configured
- **Factory Pattern**: Consistent component creation
- **Interface Segregation**: Minimal dependencies between modules

### Performance
- **No Impact**: All optimizations preserved
- **Same Patterns**: Async/await and process pool maintained
- **Memory Efficiency**: Identical resource usage
- **Zero Regression**: Performance benchmarks unchanged

## 🔧 Development

### Adding New Features
1. Create new module in `olmocr/pipeline/`
2. Implement with single responsibility
3. Add factory function to `__init__.py`
4. Write comprehensive tests
5. Update documentation

### Modifying Existing Components
1. Identify the responsible module
2. Make focused changes within module boundaries
3. Update tests for the specific module
4. Verify integration tests still pass
5. Update documentation if interfaces change

## 📈 Migration Path

For teams wanting to adopt the new modular architecture:

1. **Phase 1**: Continue using original interface (no changes needed)
2. **Phase 2**: Start using factory functions for new components
3. **Phase 3**: Gradually migrate to modular interfaces
4. **Phase 4**: Fully adopt modular architecture for new development

The modular architecture is production-ready and provides a solid foundation for future development while maintaining full compatibility with existing systems.
