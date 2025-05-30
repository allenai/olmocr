# Enhanced Error Handling Framework

This directory contains the comprehensive enhanced error handling framework for the OLMoCR pipeline, providing enterprise-grade error management, structured logging, and recovery capabilities.

## 🏗️ Architecture Overview

The enhanced error handling framework consists of several integrated components:

```
olmocr/error_handling/
└── __init__.py              # Complete error handling framework
    ├── Structured Logging   # Correlation IDs, context tracking, performance metrics
    ├── Error Categorization # Custom exceptions with rich context
    ├── Recovery Strategies  # Retry mechanisms with exponential backoff
    ├── Error Reporting     # Aggregation and pattern analysis
    └── Performance Monitor # Operation timing and metrics collection
```

## 🔍 Structured Logging System

### Features
- **Correlation ID tracking** across distributed operations
- **Contextual information** (document ID, page number, processing stage)
- **JSON-structured output** for easy parsing and analysis
- **Performance metrics logging** with timing and resource usage
- **Configurable log levels** (DEBUG, INFO, WARNING, ERROR, CRITICAL, PERFORMANCE)

### Usage Examples

#### Basic Structured Logging
```python
from olmocr.error_handling import create_logger, LogContext

logger = create_logger("my_module", structured=True)

# Basic logging with context
context = LogContext(
    correlation_id="req-123",
    document_id="doc-456", 
    page_number=1,
    processing_stage="text_extraction"
)

logger.info("Starting text extraction", context=context)
logger.error("Extraction failed", context=context)
```

#### Context Managers
```python
# Automatic context application
with logger.context(document_id="doc-123", processing_stage="preprocessing"):
    logger.info("Starting preprocessing")  # Context automatically included
    logger.debug("Loading document metadata")
    logger.warning("Document has unusual formatting")

# Operation timing with automatic performance metrics
with logger.operation("document_analysis", document_id="doc-123"):
    # Simulate work
    analyze_document()
    # Automatically logs start, completion, duration, and success/failure
```

#### Performance Metrics
```python
# Manual performance logging
logger.performance(
    "Document processing completed",
    metrics={
        'pages_processed': 10,
        'processing_time_seconds': 5.2,
        'memory_usage_mb': 150.5,
        'success_rate': 0.95
    },
    context=context
)
```

## 🏷️ Error Categorization

### Error Categories
- **NETWORK** - Network connectivity and communication issues
- **PROCESSING** - Document and page processing errors
- **VALIDATION** - Data validation and format errors
- **CONFIGURATION** - Configuration and setup errors
- **RESOURCE** - Resource availability errors (memory, disk, etc.)
- **TIMEOUT** - Timeout-related errors

### Error Severity Levels
- **LOW** - Minor issues, processing can continue
- **MEDIUM** - Moderate issues, may affect quality
- **HIGH** - Serious issues, may cause failures
- **CRITICAL** - Critical issues, immediate attention required

### Custom Exception Classes

#### Base Exception
```python
from olmocr.error_handling import OLMoCRError, ErrorCategory, ErrorSeverity, ErrorContext

# Create rich error with context
error = OLMoCRError(
    "Processing failed",
    category=ErrorCategory.PROCESSING,
    severity=ErrorSeverity.HIGH,
    context=ErrorContext(
        document_id="doc-123",
        page_number=5,
        processing_stage="text_extraction"
    ),
    recoverable=True,
    retry_after=5.0
)
```

#### Specialized Exceptions
```python
from olmocr.error_handling import NetworkError, ProcessingError, ValidationError

# Network errors with automatic retry configuration
try:
    connect_to_server()
except ConnectionError as e:
    raise NetworkError(
        "Failed to connect to SGLang server",
        context=ErrorContext(processing_stage="model_inference"),
        original_exception=e
    )

# Processing errors with document context
try:
    extract_text_from_page()
except Exception as e:
    raise ProcessingError(
        "Text extraction failed",
        context=ErrorContext(document_id="doc-123", page_number=5),
        original_exception=e
    )

# Validation errors (non-recoverable)
if not is_valid_pdf(document):
    raise ValidationError(
        "Invalid PDF format",
        context=ErrorContext(document_id="doc-123"),
        recoverable=False
    )
```

## 🔄 Recovery Strategies

### Automatic Retry with Exponential Backoff
```python
from olmocr.error_handling import create_recovery_manager

# Create recovery manager with configuration
recovery_manager = create_recovery_manager(
    max_attempts=3,
    base_delay=1.0,
    max_delay=60.0,
    logger=logger
)

# Automatic retry for async operations
async def risky_operation():
    # Operation that might fail
    return await call_external_service()

result = await recovery_manager.execute_with_retry(
    risky_operation,
    context=LogContext(document_id="doc-123"),
    operation_name="external_service_call"
)

# Automatic retry for sync operations  
def sync_risky_operation():
    return call_external_api()

result = recovery_manager.execute_with_retry_sync(
    sync_risky_operation,
    context=LogContext(document_id="doc-123"),
    operation_name="external_api_call"
)
```

### Recovery Behavior
- **Recoverable errors** are automatically retried with exponential backoff
- **Non-recoverable errors** (validation, configuration) fail immediately
- **Category-specific retry policies** (network vs. processing errors)
- **Jitter** added to prevent thundering herd problems
- **Circuit breaker patterns** for consistently failing operations

## ⚡ Performance Monitoring

### Operation Timing
```python
from olmocr.error_handling import create_performance_monitor

monitor = create_performance_monitor(logger)

# Automatic timing with context manager
with monitor.time_operation("document_processing", 
                           context={'document_type': 'pdf', 'pages': 10}):
    process_document()
    # Automatically logs duration, success/failure, memory usage

# Manual metric recording
monitor.record_custom_metric(
    operation_name="batch_processing",
    duration=45.2,
    success=True,
    context={'batch_size': 100, 'worker_id': 1}
)
```

### Performance Statistics
```python
# Get operation statistics
stats = monitor.get_stats("document_processing")
print(f"Success rate: {stats['document_processing'].success_rate:.2%}")
print(f"Average duration: {stats['document_processing'].average_duration:.2f}s")

# Get overall performance summary
summary = monitor.get_summary()
print(f"Total operations: {summary['total_operations']}")
print(f"Overall success rate: {summary['overall_success_rate']:.2%}")
```

## 📊 Error Reporting & Aggregation

### Error Aggregation
```python
from olmocr.error_handling import create_error_aggregator

aggregator = create_error_aggregator(logger)

# Record errors as they occur
try:
    risky_operation()
except NetworkError as e:
    aggregator.record_error(e, retry_count=2)

# Get error summary
summary = aggregator.get_summary()
print(f"Total errors: {summary.total_errors}")
print(f"Network errors: {summary.errors_by_category[ErrorCategory.NETWORK]}")
print(f"Success rate: {(1 - summary.total_errors/total_operations):.2%}")
```

### Comprehensive Error Reports
```python
# Generate detailed error report
report = aggregator.generate_report(include_diagnostics=True)

# Export to file for analysis
aggregator.export_report("error_report.json", include_diagnostics=True)
```

## 🔗 Correlation Tracking

### Cross-Operation Correlation
```python
from olmocr.error_handling import correlation_context

# All operations within this context share the same correlation ID
with correlation_context("batch-job-123") as correlation_id:
    logger.info("Starting batch processing")
    
    for document in documents:
        with logger.context(document_id=document.id):
            process_document(document)
    
    logger.info("Batch processing completed")
```

## 🔧 Integration with Pipeline Modules

### Standard Integration Pattern
```python
from olmocr.error_handling import (
    StructuredLogger, LogContext, create_logger,
    create_recovery_manager, create_performance_monitor,
    create_error_aggregator
)

class PipelineModule:
    def __init__(self, ..., logger: Optional[StructuredLogger] = None):
        # Initialize enhanced error handling components
        self.logger = logger or create_logger(f"{__name__}.{self.__class__.__name__}")
        self.recovery_manager = create_recovery_manager(logger=self.logger)
        self.performance_monitor = create_performance_monitor(self.logger)
        self.error_aggregator = create_error_aggregator(self.logger)
    
    async def process_operation(self, document_id: str, **kwargs):
        context = LogContext(
            document_id=document_id,
            processing_stage="operation_name",
            worker_id=kwargs.get('worker_id')
        )
        
        with self.logger.context(**context.to_dict()):
            with self.performance_monitor.time_operation("process_operation"):
                return await self.recovery_manager.execute_with_retry(
                    self._process_operation_internal,
                    context=context,
                    operation_name="process_operation",
                    document_id=document_id,
                    **kwargs
                )
```

## 📈 Benefits

### Debugging & Troubleshooting
- **Correlation tracking** across distributed operations
- **Structured logs** with searchable JSON format
- **Rich context** in every log message
- **Performance bottleneck** identification

### Reliability & Recovery
- **Automatic retry** for transient failures
- **Exponential backoff** with jitter
- **Graceful degradation** for non-critical errors
- **Circuit breaker patterns** for failing services

### Monitoring & Observability
- **Real-time error aggregation** with pattern analysis
- **Performance metrics** with success rates and timing
- **System health monitoring** with resource usage
- **Operational insights** through comprehensive reporting

### Developer Experience
- **Clear error categorization** for faster issue resolution
- **Consistent patterns** across all modules
- **Easy integration** with existing code
- **Rich documentation** and examples

## 🔄 Backward Compatibility

The enhanced error handling framework maintains 100% backward compatibility:

- ✅ **All existing function signatures** unchanged
- ✅ **Optional logger parameters** added (default to None)
- ✅ **Existing error handling behavior** maintained
- ✅ **No breaking changes** to public APIs

Existing code continues to work unchanged, while new code can opt into enhanced error handling capabilities.
