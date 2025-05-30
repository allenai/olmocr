"""
Main structured output processor and formatter classes.

This module contains the main processor that orchestrates structured data extraction
and the formatter that converts structured data to various output formats.
"""

import json
from typing import Dict, Any, List, Optional

from olmocr.error_handling import (
    StructuredLogger, LogContext, create_logger,
    ProcessingError, ErrorContext
)

from . import (
    StructuredDocument, StructuredOutputConfig, DocumentTypeClassifier,
    FieldExtractor, TableExtractor, create_document_type_classifier,
    create_field_extractor, create_table_extractor
)


class StructuredOutputProcessor:
    """Main processor for extracting structured data from documents."""
    
    def __init__(self, config: StructuredOutputConfig, logger: Optional[StructuredLogger] = None):
        """Initialize the structured output processor."""
        self.config = config
        self.logger = logger or create_logger(f"{__name__}.StructuredOutputProcessor")
        
        # Initialize components
        self.classifier = create_document_type_classifier(logger)
        self.field_extractor = create_field_extractor(config, logger)
        self.table_extractor = create_table_extractor(config, logger)
    
    def process_document(self, document_id: str, text_content: str, 
                        page_numbers: Optional[List[int]] = None,
                        context: Optional[LogContext] = None) -> StructuredDocument:
        """
        Process a document to extract structured data.
        
        Args:
            document_id: Unique identifier for the document
            text_content: Full text content of the document
            page_numbers: List of page numbers corresponding to text sections
            context: Optional log context
            
        Returns:
            StructuredDocument with extracted data
        """
        with self.logger.context(document_id=document_id, processing_stage="structured_extraction"):
            self.logger.info(f"Processing document for structured output: {document_id}")
            
            try:
                # Classify document type
                doc_type = self.classifier.classify_document(text_content, context)
                
                # Create structured document
                structured_doc = StructuredDocument(
                    document_id=document_id,
                    document_type=doc_type
                )
                
                # Extract fields and tables from the full document
                if self.config.extract_key_value_pairs or self.config.extract_forms:
                    fields = self.field_extractor.extract_key_value_pairs(text_content, context=context)
                    typed_fields = self.field_extractor.extract_typed_fields(text_content, context=context)
                    
                    for field in fields + typed_fields:
                        if field.confidence >= self.config.min_confidence:
                            structured_doc.add_field(field)
                
                if self.config.extract_tables:
                    tables = self.table_extractor.extract_tables(text_content, context=context)
                    for table in tables:
                        if table.confidence >= self.config.min_confidence:
                            structured_doc.add_table(table)
                
                # Add metadata
                structured_doc.metadata.update({
                    'extraction_config': {
                        'extract_forms': self.config.extract_forms,
                        'extract_tables': self.config.extract_tables,
                        'extract_key_value_pairs': self.config.extract_key_value_pairs,
                        'min_confidence': self.config.min_confidence
                    },
                    'total_fields': len(structured_doc.fields),
                    'total_tables': len(structured_doc.tables),
                    'document_length': len(text_content)
                })
                
                self.logger.info(
                    f"Structured extraction completed for {document_id}",
                    context=context,
                    metrics={
                        'document_type': doc_type.value,
                        'fields_extracted': len(structured_doc.fields),
                        'tables_extracted': len(structured_doc.tables)
                    }
                )
                
                return structured_doc
                
            except Exception as e:
                self.logger.exception(f"Error processing document {document_id} for structured output")
                raise ProcessingError(
                    f"Failed to extract structured data from document {document_id}",
                    context=ErrorContext(document_id=document_id, processing_stage="structured_extraction"),
                    original_exception=e
                )
    
    def validate_structured_document(self, structured_doc: StructuredDocument) -> bool:
        """
        Validate a structured document.
        
        Args:
            structured_doc: Document to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not self.config.enable_field_validation:
            return True
        
        try:
            # Basic validation
            if not structured_doc.document_id:
                return False
            
            # Validate fields
            for field in structured_doc.fields:
                if not field.name or field.value is None:
                    return False
                if field.confidence < 0 or field.confidence > 1:
                    return False
            
            # Validate tables
            for table in structured_doc.tables:
                if not table.headers or not table.rows:
                    return False
                if table.confidence < 0 or table.confidence > 1:
                    return False
                
                # Check that all rows have the same number of columns as headers
                for row in table.rows:
                    if len(row) != len(table.headers):
                        return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Error validating structured document: {e}")
            return False


class StructuredOutputFormatter:
    """Formats structured output in various formats."""
    
    def __init__(self, logger: Optional[StructuredLogger] = None):
        """Initialize the formatter."""
        self.logger = logger or create_logger(f"{__name__}.StructuredOutputFormatter")
    
    def format_as_json(self, structured_doc: StructuredDocument, 
                      pretty: bool = True) -> str:
        """
        Format structured document as JSON.
        
        Args:
            structured_doc: Document to format
            pretty: Whether to pretty-print the JSON
            
        Returns:
            JSON string representation
        """
        doc_dict = structured_doc.to_dict()
        
        if pretty:
            return json.dumps(doc_dict, indent=2, ensure_ascii=False)
        else:
            return json.dumps(doc_dict, ensure_ascii=False)
    
    def format_as_key_value(self, structured_doc: StructuredDocument) -> str:
        """
        Format structured document as key-value pairs.
        
        Args:
            structured_doc: Document to format
            
        Returns:
            Key-value string representation
        """
        lines = []
        lines.append(f"Document ID: {structured_doc.document_id}")
        lines.append(f"Document Type: {structured_doc.document_type.value}")
        lines.append("")
        
        if structured_doc.fields:
            lines.append("FIELDS:")
            for field in structured_doc.fields:
                lines.append(f"  {field.name}: {field.value} ({field.field_type.value})")
            lines.append("")
        
        if structured_doc.tables:
            lines.append("TABLES:")
            for i, table in enumerate(structured_doc.tables):
                lines.append(f"  Table {i+1}:")
                lines.append(f"    Headers: {', '.join(table.headers)}")
                lines.append(f"    Rows: {len(table.rows)}")
            lines.append("")
        
        return '\n'.join(lines)
    
    def format_as_csv_tables(self, structured_doc: StructuredDocument) -> Dict[str, str]:
        """
        Format tables as CSV strings.
        
        Args:
            structured_doc: Document to format
            
        Returns:
            Dictionary mapping table names to CSV strings
        """
        csv_tables = {}
        
        for i, table in enumerate(structured_doc.tables):
            csv_lines = []
            
            # Add headers
            csv_lines.append(','.join(f'"{header}"' for header in table.headers))
            
            # Add rows
            for row in table.rows:
                csv_lines.append(','.join(f'"{cell}"' for cell in row))
            
            csv_tables[f"table_{i+1}"] = '\n'.join(csv_lines)
        
        return csv_tables
    
    def format_combined_output(self, dolma_doc: Dict[str, Any], 
                             structured_doc: StructuredDocument) -> Dict[str, Any]:
        """
        Combine traditional Dolma output with structured data.
        
        Args:
            dolma_doc: Original Dolma document
            structured_doc: Structured document data
            
        Returns:
            Combined document with both text and structured data
        """
        combined_doc = dolma_doc.copy()
        
        # Add structured data to the document
        combined_doc["structured_data"] = structured_doc.to_dict()
        
        # Update metadata to include structured extraction info
        if "metadata" not in combined_doc:
            combined_doc["metadata"] = {}
        
        combined_doc["metadata"].update({
            "has_structured_data": True,
            "structured_fields_count": len(structured_doc.fields),
            "structured_tables_count": len(structured_doc.tables),
            "document_type": structured_doc.document_type.value
        })
        
        return combined_doc


# Factory functions
def create_structured_output_processor(config: StructuredOutputConfig,
                                     logger: Optional[StructuredLogger] = None) -> StructuredOutputProcessor:
    """Create a structured output processor."""
    return StructuredOutputProcessor(config, logger)


def create_structured_output_formatter(logger: Optional[StructuredLogger] = None) -> StructuredOutputFormatter:
    """Create a structured output formatter."""
    return StructuredOutputFormatter(logger)
