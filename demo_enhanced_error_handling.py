#!/usr/bin/env python3
"""
Demonstration script for enhanced error handling system.

This script demonstrates the comprehensive error handling, structured logging,
and recovery mechanisms implemented for the OLMoCR pipeline.
"""

import asyncio
import json
import tempfile
import time
from typing import Dict, Any

# Import the enhanced error handling system
from olmocr.error_handling import (
    StructuredLogger, LogContext, create_logger,
    ErrorCategory, ErrorSeverity, OLMoCRError, NetworkError, ProcessingError,
    create_recovery_manager, create_error_aggregator, create_performance_monitor,
    correlation_context
)


async def demo_structured_logging():
    """Demonstrate structured logging capabilities."""
    print("🔍 Demonstrating Structured Logging...")
    
    # Create a structured logger
    logger = create_logger("demo.structured_logging", structured=True)
    
    # Basic logging with context
    with logger.context(document_id="demo-doc-123", processing_stage="demo"):
        logger.info("Starting document processing")
        logger.debug("Loading document metadata")
        logger.warning("Document has unusual formatting")
    
    # Operation timing
    with logger.operation("document_analysis", document_id="demo-doc-123"):
        # Simulate some work
        await asyncio.sleep(0.1)
        logger.info("Analysis completed successfully")
    
    # Performance logging
    logger.performance(
        "Document processing completed",
        metrics={
            'pages_processed': 10,
            'processing_time_seconds': 5.2,
            'memory_usage_mb': 150.5
        }
    )
    
    print("   ✅ Structured logging demonstrated")
    print()


async def demo_error_categorization():
    """Demonstrate error categorization and custom exceptions."""
    print("🏷️ Demonstrating Error Categorization...")
    
    logger = create_logger("demo.error_categorization")
    
    # Create different types of errors
    errors = [
        NetworkError("Connection timeout to SGLang server"),
        ProcessingError("Failed to extract text from page 5"),
        OLMoCRError(
            "Invalid document format",
            ErrorCategory.VALIDATION,
            ErrorSeverity.HIGH,
            recoverable=False
        )
    ]
    
    for error in errors:
        logger.error(f"Error occurred: {error.message}")
        print(f"   📋 {error.__class__.__name__}: {error.category.value} ({error.severity.value})")
        print(f"      Recoverable: {error.recoverable}")
        if error.retry_after:
            print(f"      Retry after: {error.retry_after}s")
    
    print("   ✅ Error categorization demonstrated")
    print()


async def demo_retry_strategies():
    """Demonstrate retry strategies and recovery mechanisms."""
    print("🔄 Demonstrating Retry Strategies...")
    
    logger = create_logger("demo.retry_strategies")
    recovery_manager = create_recovery_manager(
        max_attempts=3,
        base_delay=0.1,
        logger=logger
    )
    
    # Simulate operation that succeeds after retries
    attempt_count = 0
    
    async def flaky_operation():
        nonlocal attempt_count
        attempt_count += 1
        print(f"   🔄 Attempt {attempt_count}")
        
        if attempt_count < 3:
            raise NetworkError("Temporary connection failure")
        return "Operation successful!"
    
    try:
        result = await recovery_manager.execute_with_retry(
            flaky_operation,
            operation_name="demo_flaky_operation"
        )
        print(f"   ✅ {result}")
    except Exception as e:
        print(f"   ❌ Operation failed: {e}")
    
    # Simulate non-recoverable error
    async def non_recoverable_operation():
        raise OLMoCRError(
            "Configuration error",
            ErrorCategory.CONFIGURATION,
            ErrorSeverity.CRITICAL,
            recoverable=False
        )
    
    try:
        await recovery_manager.execute_with_retry(
            non_recoverable_operation,
            operation_name="demo_non_recoverable"
        )
    except OLMoCRError as e:
        print(f"   ⚠️ Non-recoverable error (no retries): {e.message}")
    
    print("   ✅ Retry strategies demonstrated")
    print()


async def demo_error_aggregation():
    """Demonstrate error aggregation and reporting."""
    print("📊 Demonstrating Error Aggregation...")
    
    logger = create_logger("demo.error_aggregation")
    aggregator = create_error_aggregator(logger)
    
    # Simulate various errors occurring
    errors_to_simulate = [
        NetworkError("Connection timeout"),
        NetworkError("Server unavailable"),
        ProcessingError("PDF parsing failed"),
        ProcessingError("Image extraction failed"),
        OLMoCRError("Memory limit exceeded", ErrorCategory.RESOURCE, ErrorSeverity.HIGH),
    ]
    
    for i, error in enumerate(errors_to_simulate):
        aggregator.record_error(error, retry_count=i % 3)
        await asyncio.sleep(0.01)  # Small delay to show time progression
    
    # Get summary
    summary = aggregator.get_summary()
    print(f"   📈 Total errors: {summary.total_errors}")
    print(f"   📈 Recoverable errors: {summary.recoverable_errors}")
    print(f"   📈 Non-recoverable errors: {summary.non_recoverable_errors}")
    
    print("   📈 Errors by category:")
    for category, count in summary.errors_by_category.items():
        print(f"      {category.value}: {count}")
    
    print("   📈 Errors by severity:")
    for severity, count in summary.errors_by_severity.items():
        print(f"      {severity.value}: {count}")
    
    # Generate comprehensive report
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        aggregator.export_report(f.name, include_diagnostics=True)
        print(f"   💾 Detailed report exported to: {f.name}")
    
    print("   ✅ Error aggregation demonstrated")
    print()


async def demo_performance_monitoring():
    """Demonstrate performance monitoring capabilities."""
    print("⚡ Demonstrating Performance Monitoring...")
    
    logger = create_logger("demo.performance_monitoring")
    monitor = create_performance_monitor(logger)
    
    # Simulate various operations
    operations = [
        ("pdf_download", 0.5, True),
        ("page_rendering", 0.3, True),
        ("text_extraction", 0.2, True),
        ("model_inference", 1.2, True),
        ("pdf_download", 0.4, False),  # Failed operation
        ("page_rendering", 0.25, True),
    ]
    
    for op_name, duration, success in operations:
        if success:
            with monitor.time_operation(op_name):
                await asyncio.sleep(duration * 0.1)  # Scaled down for demo
        else:
            try:
                with monitor.time_operation(op_name):
                    await asyncio.sleep(duration * 0.1)
                    raise NetworkError("Simulated failure")
            except NetworkError:
                pass
    
    # Get performance summary
    summary = monitor.get_summary()
    print(f"   📊 Total operations: {summary['total_operations']}")
    print(f"   📊 Success rate: {summary['overall_success_rate']:.2%}")
    
    print("   📊 Operations breakdown:")
    for op_name, stats in summary['operations_by_type'].items():
        print(f"      {op_name}:")
        print(f"        Count: {stats['total_count']}")
        print(f"        Success rate: {stats['success_rate']:.2%}")
        print(f"        Avg duration: {stats['average_duration_seconds']:.3f}s")
    
    print("   ✅ Performance monitoring demonstrated")
    print()


async def demo_correlation_tracking():
    """Demonstrate correlation ID tracking across operations."""
    print("🔗 Demonstrating Correlation Tracking...")
    
    logger = create_logger("demo.correlation_tracking")
    
    # Use correlation context
    with correlation_context("demo-correlation-123") as correlation_id:
        print(f"   🆔 Correlation ID: {correlation_id}")
        
        # All operations within this context will share the correlation ID
        with logger.context(document_id="demo-doc", processing_stage="preprocessing"):
            logger.info("Starting document preprocessing")
            
            # Simulate nested operations
            with logger.operation("extract_metadata"):
                await asyncio.sleep(0.05)
                logger.info("Metadata extracted successfully")
            
            with logger.operation("validate_format"):
                await asyncio.sleep(0.03)
                logger.info("Format validation completed")
        
        logger.info("Document preprocessing completed")
    
    print("   ✅ Correlation tracking demonstrated")
    print()


async def demo_enhanced_http_client():
    """Demonstrate enhanced HTTP client with error handling."""
    print("🌐 Demonstrating Enhanced HTTP Client...")
    
    # Import the enhanced HTTP client
    from olmocr.pipeline.http_client import create_sglang_client, SGLangHTTPClient
    
    logger = create_logger("demo.http_client")
    
    # Create client with enhanced error handling
    try:
        client = await create_sglang_client(port=30024, logger=logger)
        print(f"   ✅ HTTP client created for {client.base_url}")
        
        # The client now has:
        print("   🔧 Enhanced features:")
        print("      - Structured logging with correlation IDs")
        print("      - Automatic retry with exponential backoff")
        print("      - Performance monitoring and metrics")
        print("      - Comprehensive error categorization")
        print("      - Graceful degradation on failures")
        
    except Exception as e:
        print(f"   ⚠️ Client creation demo (expected without server): {e}")
    
    print("   ✅ Enhanced HTTP client demonstrated")
    print()


async def main():
    """Run all demonstrations."""
    print("=" * 70)
    print("🚀 Enhanced Error Handling System Demonstration")
    print("=" * 70)
    print()
    
    print("This demonstration shows the comprehensive error handling")
    print("enhancements implemented for the OLMoCR pipeline:")
    print()
    
    # Run all demonstrations
    await demo_structured_logging()
    await demo_error_categorization()
    await demo_retry_strategies()
    await demo_error_aggregation()
    await demo_performance_monitoring()
    await demo_correlation_tracking()
    await demo_enhanced_http_client()
    
    print("=" * 70)
    print("✅ ENHANCED ERROR HANDLING DEMONSTRATION COMPLETE!")
    print("=" * 70)
    print()
    print("Key improvements implemented:")
    print("  🔍 Structured logging with correlation IDs and context")
    print("  🏷️ Comprehensive error categorization and severity levels")
    print("  🔄 Intelligent retry strategies with exponential backoff")
    print("  📊 Error aggregation and detailed reporting")
    print("  ⚡ Performance monitoring and metrics collection")
    print("  🔗 Correlation tracking across distributed operations")
    print("  🌐 Enhanced HTTP client with robust error handling")
    print()
    print("Benefits achieved:")
    print("  ✅ Better debugging and troubleshooting capabilities")
    print("  ✅ Improved reliability with automatic error recovery")
    print("  ✅ Comprehensive monitoring and observability")
    print("  ✅ Graceful degradation under failure conditions")
    print("  ✅ Detailed error reports for issue resolution")
    print()
    print("Ready for production use! 🎉")


if __name__ == "__main__":
    asyncio.run(main())
