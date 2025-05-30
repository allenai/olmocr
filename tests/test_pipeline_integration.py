"""
Integration tests for the refactored pipeline modules.

These tests verify that the refactored modules work together correctly
and maintain backward compatibility with the original implementation.
"""

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from olmocr.pipeline.core import create_pipeline_orchestrator
from olmocr.pipeline.document_builder import PageResult, create_document_builder
from olmocr.pipeline.http_client import create_sglang_client
from olmocr.pipeline.processing import create_page_processor, create_document_processor
from olmocr.pipeline.workers import create_worker_manager
from olmocr.prompts import PageResponse


class TestPipelineIntegration(unittest.TestCase):
    """Integration tests for pipeline components."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.orchestrator = None
    
    def tearDown(self):
        """Clean up test fixtures."""
        if self.orchestrator:
            self.orchestrator.cleanup()
    
    async def test_orchestrator_initialization(self):
        """Test pipeline orchestrator initialization."""
        # Create mock args
        args = MagicMock()
        args.workspace_profile = None
        args.pdf_profile = None
        args.port = 30024
        args.apply_filter = False
        args.stats = False
        args.beaker = False
        
        # Create orchestrator
        self.orchestrator = create_pipeline_orchestrator()
        
        # Test initialization (without actually starting servers)
        with patch('olmocr.pipeline.core.check_poppler_version'), \
             patch('olmocr.pipeline.core.check_sglang_version'), \
             patch('olmocr.pipeline.core.check_torch_gpu_available'), \
             patch('olmocr.pipeline.core.create_sglang_client') as mock_client:
            
            mock_client.return_value = AsyncMock()
            await self.orchestrator.initialize(args)
            
            # Verify components are initialized
            self.assertIsNotNone(self.orchestrator.metrics)
            self.assertIsNotNone(self.orchestrator.tracker)
            self.assertIsNotNone(self.orchestrator.process_pool)
    
    async def test_component_creation_chain(self):
        """Test that all components can be created and work together."""
        # Create HTTP client
        http_client = await create_sglang_client(30024)
        self.assertIsNotNone(http_client)
        
        # Create document builder
        document_builder = create_document_builder()
        self.assertIsNotNone(document_builder)
        
        # Create mock dependencies for page processor
        with patch('olmocr.pipeline.processing.ProcessPoolExecutor') as mock_pool, \
             patch('olmocr.pipeline.processing.MetricsKeeper') as mock_metrics, \
             patch('olmocr.pipeline.processing.WorkerTracker') as mock_tracker:
            
            mock_pool_instance = MagicMock()
            mock_metrics_instance = MagicMock()
            mock_tracker_instance = MagicMock()
            
            mock_pool.return_value = mock_pool_instance
            mock_metrics.return_value = mock_metrics_instance
            mock_tracker.return_value = mock_tracker_instance
            
            # Create page processor
            page_processor = create_page_processor(
                http_client, mock_pool_instance, mock_metrics_instance, mock_tracker_instance
            )
            self.assertIsNotNone(page_processor)
            
            # Create document processor
            document_processor = create_document_processor(
                page_processor, document_builder
            )
            self.assertIsNotNone(document_processor)
            
            # Create worker manager
            worker_manager = create_worker_manager(
                document_processor,
                mock_metrics_instance,
                mock_tracker_instance,
                MagicMock(),  # workspace_s3_client
                MagicMock(),  # pdf_s3_client
            )
            self.assertIsNotNone(worker_manager)
    
    def test_backward_compatibility_imports(self):
        """Test that backward compatibility imports work."""
        # Test that we can import from the main pipeline module
        from olmocr.pipeline import PageResult as OriginalPageResult
        from olmocr.pipeline import build_dolma_document as original_build_dolma_document
        from olmocr.pipeline import apost as original_apost
        
        # Test that we can also import the modular versions
        from olmocr.pipeline import ModularPageResult
        from olmocr.pipeline import modular_build_dolma_document
        from olmocr.pipeline import modular_apost
        
        # Verify they exist
        self.assertIsNotNone(OriginalPageResult)
        self.assertIsNotNone(original_build_dolma_document)
        self.assertIsNotNone(original_apost)
        self.assertIsNotNone(ModularPageResult)
        self.assertIsNotNone(modular_build_dolma_document)
        self.assertIsNotNone(modular_apost)
    
    def test_page_result_compatibility(self):
        """Test that PageResult works the same in both versions."""
        # Create a PageResponse
        response = PageResponse(
            natural_text="Test content",
            primary_language="en",
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        )
        
        # Import both versions
        from olmocr.pipeline import PageResult as OriginalPageResult
        from olmocr.pipeline import ModularPageResult
        
        # Create instances
        original = OriginalPageResult(
            s3_path="test.pdf",
            page_num=1,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=False,
        )
        
        modular = ModularPageResult(
            s3_path="test.pdf",
            page_num=1,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=False,
        )
        
        # Verify they have the same attributes
        self.assertEqual(original.s3_path, modular.s3_path)
        self.assertEqual(original.page_num, modular.page_num)
        self.assertEqual(original.response, modular.response)
        self.assertEqual(original.input_tokens, modular.input_tokens)
        self.assertEqual(original.output_tokens, modular.output_tokens)
        self.assertEqual(original.is_fallback, modular.is_fallback)
    
    def test_document_builder_compatibility(self):
        """Test that document building works the same in both versions."""
        # Create test data
        response = PageResponse(
            natural_text="Test content",
            primary_language="en",
            is_rotation_valid=True,
            rotation_correction=0,
            is_table=False,
            is_diagram=False,
        )
        
        from olmocr.pipeline import PageResult as OriginalPageResult
        from olmocr.pipeline import build_dolma_document as original_build_dolma_document
        from olmocr.pipeline import ModularPageResult
        from olmocr.pipeline import modular_build_dolma_document
        
        # Create page results
        original_page_result = OriginalPageResult(
            s3_path="test.pdf",
            page_num=1,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=False,
        )
        
        modular_page_result = ModularPageResult(
            s3_path="test.pdf",
            page_num=1,
            response=response,
            input_tokens=100,
            output_tokens=50,
            is_fallback=False,
        )
        
        # Build documents
        original_doc = original_build_dolma_document("test.pdf", [original_page_result])
        modular_doc = modular_build_dolma_document("test.pdf", [modular_page_result])
        
        # Verify they produce similar results
        self.assertEqual(original_doc["text"], modular_doc["text"])
        self.assertEqual(original_doc["source"], modular_doc["source"])
        self.assertEqual(original_doc["metadata"]["Source-File"], modular_doc["metadata"]["Source-File"])
        self.assertEqual(original_doc["metadata"]["pdf-total-pages"], modular_doc["metadata"]["pdf-total-pages"])


class TestAsyncIntegration(unittest.TestCase):
    """Test cases that require async test runner."""
    
    def test_async_integration(self):
        """Run async integration tests."""
        async def run_tests():
            # Test orchestrator initialization
            args = MagicMock()
            args.workspace_profile = None
            args.pdf_profile = None
            args.port = 30024
            args.apply_filter = False
            args.stats = False
            args.beaker = False
            
            orchestrator = create_pipeline_orchestrator()
            
            with patch('olmocr.pipeline.core.check_poppler_version'), \
                 patch('olmocr.pipeline.core.check_sglang_version'), \
                 patch('olmocr.pipeline.core.check_torch_gpu_available'), \
                 patch('olmocr.pipeline.core.create_sglang_client') as mock_client:
                
                mock_client.return_value = AsyncMock()
                await orchestrator.initialize(args)
                
                # Verify initialization worked
                assert orchestrator.metrics is not None
                assert orchestrator.tracker is not None
                
                # Clean up
                orchestrator.cleanup()
            
            # Test component creation
            http_client = await create_sglang_client(30024)
            assert http_client is not None
            
            document_builder = create_document_builder()
            assert document_builder is not None
        
        # Run the async tests
        asyncio.run(run_tests())


class TestModularArchitecture(unittest.TestCase):
    """Test the modular architecture design."""
    
    def test_module_separation(self):
        """Test that modules are properly separated."""
        # Test that each module can be imported independently
        from olmocr.pipeline import core
        from olmocr.pipeline import document_builder
        from olmocr.pipeline import http_client
        from olmocr.pipeline import processing
        from olmocr.pipeline import workers
        
        # Verify modules exist
        self.assertIsNotNone(core)
        self.assertIsNotNone(document_builder)
        self.assertIsNotNone(http_client)
        self.assertIsNotNone(processing)
        self.assertIsNotNone(workers)
    
    def test_factory_functions_exist(self):
        """Test that all factory functions exist."""
        from olmocr.pipeline.core import create_pipeline_orchestrator
        from olmocr.pipeline.document_builder import create_document_builder
        from olmocr.pipeline.http_client import create_sglang_client
        from olmocr.pipeline.processing import create_page_processor, create_document_processor
        from olmocr.pipeline.workers import create_worker_manager
        
        # Verify factory functions exist
        self.assertTrue(callable(create_pipeline_orchestrator))
        self.assertTrue(callable(create_document_builder))
        self.assertTrue(callable(create_sglang_client))
        self.assertTrue(callable(create_page_processor))
        self.assertTrue(callable(create_document_processor))
        self.assertTrue(callable(create_worker_manager))
    
    def test_class_interfaces(self):
        """Test that main classes have expected interfaces."""
        from olmocr.pipeline.core import PipelineOrchestrator
        from olmocr.pipeline.document_builder import DolmaDocumentBuilder
        from olmocr.pipeline.http_client import SGLangHTTPClient
        from olmocr.pipeline.processing import PageProcessor, DocumentProcessor
        from olmocr.pipeline.workers import WorkerManager
        
        # Verify classes exist and have expected methods
        self.assertTrue(hasattr(PipelineOrchestrator, 'initialize'))
        self.assertTrue(hasattr(DolmaDocumentBuilder, 'build_document'))
        self.assertTrue(hasattr(SGLangHTTPClient, 'post_completion'))
        self.assertTrue(hasattr(PageProcessor, 'process_page'))
        self.assertTrue(hasattr(DocumentProcessor, 'process_pdf'))
        self.assertTrue(hasattr(WorkerManager, 'worker'))


if __name__ == "__main__":
    unittest.main()
