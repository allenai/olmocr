"""
Document builder module for creating Dolma documents from page results.

This module handles the construction of Dolma-format documents from processed
PDF page results, including metadata generation and text assembly.
"""

import datetime
import hashlib
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from olmocr.prompts import PageResponse
from olmocr.version import VERSION

logger = logging.getLogger(__name__)


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
    
    Handles text assembly, metadata generation, and document structure creation
    according to the Dolma specification.
    """
    
    def __init__(self):
        """Initialize the document builder."""
        pass
    
    def build_document(self, pdf_orig_path: str, page_results: List[PageResult]) -> Optional[Dict[str, Any]]:
        """
        Build a Dolma document from page processing results.
        
        Args:
            pdf_orig_path: Original path to the PDF file
            page_results: List of PageResult objects from page processing
            
        Returns:
            Dolma document dictionary, or None if document is empty
        """
        if not page_results:
            logger.warning(f"No page results provided for {pdf_orig_path}")
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
            logger.info(f"No document text for {pdf_orig_path}")
            return None  # Return None if the document text is empty

        # Build the metadata
        metadata = self._build_metadata(pdf_orig_path, page_results)
        
        # Generate document ID
        doc_id = self._generate_document_id(document_text)
        
        # Create the Dolma document
        dolma_doc = {
            "id": doc_id,
            "text": document_text,
            "source": "olmocr",
            "added": datetime.datetime.now().strftime("%Y-%m-%d"),
            "created": datetime.datetime.now().strftime("%Y-%m-%d"),
            "metadata": metadata,
            "attributes": {"pdf_page_numbers": pdf_page_spans},
        }
        
        logger.debug(f"Built Dolma document for {pdf_orig_path}: {len(document_text)} chars, {len(page_results)} pages")
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
def create_document_builder() -> DolmaDocumentBuilder:
    """
    Create a new DolmaDocumentBuilder instance.
    
    Returns:
        Configured DolmaDocumentBuilder
    """
    return DolmaDocumentBuilder()


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
