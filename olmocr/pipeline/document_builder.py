"""
Document builder module for creating Dolma documents from page results.

This module handles the construction of Dolma-format documents from processed
PDF page results, including metadata generation, text assembly, and optional
structured output extraction.
"""

import datetime
import hashlib
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from olmocr.prompts import PageResponse
from olmocr.version import VERSION
from olmocr.error_handling import StructuredLogger, LogContext, create_logger
from olmocr.structured_output import (
    create_structured_output_config, create_structured_output_processor,
    create_structured_output_formatter, StructuredOutputConfig
)

logger = create_logger(__name__, structured=True)


@dataclass(frozen=True)
class PageResult:
    """Result from processing a single PDF page."""
    s3_path: str
    page_num: int
    response: PageResponse
    input_tokens: int
    output_tokens: int
    is_fallback: bool


class DolmaDocumentBuilder:
    """
    Builder for creating Dolma-format documents from page processing results.

    Handles text assembly, metadata generation, document structure creation
    according to the Dolma specification, and optional structured output extraction.
    """

    def __init__(self,
                 structured_output_config: Optional[StructuredOutputConfig] = None,
                 logger: Optional[StructuredLogger] = None):
        """
        Initialize the document builder.

        Args:
            structured_output_config: Optional configuration for structured output extraction
            logger: Optional structured logger instance
        """
        self.logger = logger or create_logger(f"{__name__}.DolmaDocumentBuilder")
        self.structured_output_config = structured_output_config

        # Initialize structured output components if enabled
        if self.structured_output_config:
            self.structured_processor = create_structured_output_processor(
                self.structured_output_config, self.logger
            )
            self.structured_formatter = create_structured_output_formatter(self.logger)
        else:
            self.structured_processor = None
            self.structured_formatter = None
    
    def build_document(self, pdf_orig_path: str, page_results: List[PageResult]) -> Optional[Dict[str, Any]]:
        """
        Build a Dolma document from page processing results.

        Args:
            pdf_orig_path: Original path to the PDF file
            page_results: List of PageResult objects from page processing

        Returns:
            Dolma document dictionary with optional structured data, or None if document is empty
        """
        context = LogContext(
            document_id=pdf_orig_path,
            processing_stage="document_building"
        )

        with self.logger.context(**context.to_dict()):
            if not page_results:
                self.logger.warning(f"No page results provided for {pdf_orig_path}")
                return None

            # Build the document text and page spans
            document_text = ""
            pdf_page_spans = []
            current_char_pos = 0

            for index, page_result in enumerate(page_results):
                if page_result.response.natural_text is not None:
                    content = page_result.response.natural_text + ("\n" if index < len(page_results) - 1 else "")
                else:
                    content = ""

                start_pos = current_char_pos
                document_text += content
                current_char_pos = len(document_text)
                pdf_page_spans.append([start_pos, current_char_pos, page_result.page_num])

            if not document_text:
                self.logger.info(f"No document text for {pdf_orig_path}")
                return None  # Return None if the document text is empty

            # Build the metadata
            metadata = self._build_metadata(pdf_orig_path, page_results)

            # Generate document ID
            doc_id = self._generate_document_id(document_text)

            # Create the base Dolma document
            dolma_doc = {
                "id": doc_id,
                "text": document_text,
                "source": "olmocr",
                "added": datetime.datetime.now().strftime("%Y-%m-%d"),
                "created": datetime.datetime.now().strftime("%Y-%m-%d"),
                "metadata": metadata,
                "attributes": {"pdf_page_numbers": pdf_page_spans},
            }

            # Add structured output if enabled
            if self.structured_processor and self.structured_formatter:
                try:
                    self.logger.debug(f"Extracting structured data for {pdf_orig_path}")

                    # Extract structured data
                    structured_doc = self.structured_processor.process_document(
                        document_id=doc_id,
                        text_content=document_text,
                        page_numbers=[span[2] for span in pdf_page_spans],
                        context=context
                    )

                    # Validate structured document
                    if self.structured_processor.validate_structured_document(structured_doc):
                        # Combine with Dolma document
                        dolma_doc = self.structured_formatter.format_combined_output(
                            dolma_doc, structured_doc
                        )

                        self.logger.info(
                            f"Added structured data to document {pdf_orig_path}",
                            context=context,
                            metrics={
                                'fields_extracted': len(structured_doc.fields),
                                'tables_extracted': len(structured_doc.tables),
                                'document_type': structured_doc.document_type.value
                            }
                        )
                    else:
                        self.logger.warning(f"Structured document validation failed for {pdf_orig_path}")

                except Exception as e:
                    self.logger.warning(
                        f"Failed to extract structured data for {pdf_orig_path}: {e}",
                        context=context
                    )
                    # Continue with regular document if structured extraction fails

            self.logger.debug(
                f"Built Dolma document for {pdf_orig_path}: {len(document_text)} chars, {len(page_results)} pages",
                context=context
            )
            return dolma_doc
    
    def _build_metadata(self, pdf_orig_path: str, page_results: List[PageResult]) -> Dict[str, Any]:
        """
        Build metadata dictionary for the Dolma document.
        
        Args:
            pdf_orig_path: Original path to the PDF file
            page_results: List of PageResult objects
            
        Returns:
            Metadata dictionary
        """
        total_input_tokens = sum(page.input_tokens for page in page_results)
        total_output_tokens = sum(page.output_tokens for page in page_results)
        total_fallback_pages = sum(page.is_fallback for page in page_results)
        
        metadata = {
            "Source-File": pdf_orig_path,
            "olmocr-version": VERSION,
            "pdf-total-pages": len(page_results),
            "total-input-tokens": total_input_tokens,
            "total-output-tokens": total_output_tokens,
            "total-fallback-pages": total_fallback_pages,
        }
        
        return metadata
    
    def _generate_document_id(self, document_text: str) -> str:
        """
        Generate a unique document ID based on the document text.
        
        Args:
            document_text: The full text content of the document
            
        Returns:
            SHA1 hash of the document text as hexadecimal string
        """
        return hashlib.sha1(document_text.encode()).hexdigest()
    
    def validate_document(self, dolma_doc: Dict[str, Any]) -> bool:
        """
        Validate that a Dolma document has the required structure.
        
        Args:
            dolma_doc: Dolma document dictionary
            
        Returns:
            True if document is valid, False otherwise
        """
        required_fields = ["id", "text", "source", "added", "created", "metadata", "attributes"]
        
        for field in required_fields:
            if field not in dolma_doc:
                logger.error(f"Missing required field '{field}' in Dolma document")
                return False
        
        # Validate metadata structure
        metadata = dolma_doc["metadata"]
        required_metadata = ["Source-File", "olmocr-version", "pdf-total-pages"]
        
        for field in required_metadata:
            if field not in metadata:
                logger.error(f"Missing required metadata field '{field}'")
                return False
        
        # Validate attributes structure
        attributes = dolma_doc["attributes"]
        if "pdf_page_numbers" not in attributes:
            logger.error("Missing 'pdf_page_numbers' in attributes")
            return False
        
        return True


# Factory function for creating document builder
def create_document_builder(structured_output_config: Optional[StructuredOutputConfig] = None,
                           logger: Optional[StructuredLogger] = None) -> DolmaDocumentBuilder:
    """
    Create a new DolmaDocumentBuilder instance.

    Args:
        structured_output_config: Optional configuration for structured output extraction
        logger: Optional structured logger instance

    Returns:
        Configured DolmaDocumentBuilder
    """
    return DolmaDocumentBuilder(structured_output_config, logger)


# Legacy function for backward compatibility
def build_dolma_document(pdf_orig_path: str, page_results: List[PageResult]) -> Optional[Dict[str, Any]]:
    """
    Legacy function for backward compatibility.

    Args:
        pdf_orig_path: Original path to the PDF file
        page_results: List of PageResult objects

    Returns:
        Dolma document dictionary, or None if document is empty
    """
    builder = create_document_builder()
    return builder.build_document(pdf_orig_path, page_results)
