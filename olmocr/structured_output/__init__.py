"""
Structured Output Support for OLMoCR Pipeline

This module provides comprehensive structured output capabilities for extracting
key-value pairs, forms, tables, and other structured data from documents.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Union, Tuple
from enum import Enum

from olmocr.error_handling import (
    StructuredLogger, LogContext, create_logger,
    ValidationError, ProcessingError, ErrorContext
)


class DocumentType(Enum):
    """Types of documents that can be processed for structured output."""
    FORM = "form"
    TABLE = "table"
    INVOICE = "invoice"
    RECEIPT = "receipt"
    CONTRACT = "contract"
    REPORT = "report"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class FieldType(Enum):
    """Types of fields that can be extracted."""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    BOOLEAN = "boolean"
    LIST = "list"
    TABLE = "table"


@dataclass
class StructuredField:
    """Represents a structured field extracted from a document."""
    name: str
    value: Any
    field_type: FieldType
    confidence: float = 1.0
    page_number: Optional[int] = None
    bounding_box: Optional[Tuple[float, float, float, float]] = None  # (x1, y1, x2, y2)
    raw_text: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            'name': self.name,
            'value': self.value,
            'type': self.field_type.value,
            'confidence': self.confidence
        }
        
        if self.page_number is not None:
            result['page_number'] = self.page_number
        if self.bounding_box is not None:
            result['bounding_box'] = self.bounding_box
        if self.raw_text is not None:
            result['raw_text'] = self.raw_text
            
        return result


@dataclass
class StructuredTable:
    """Represents a structured table extracted from a document."""
    headers: List[str]
    rows: List[List[Any]]
    page_number: Optional[int] = None
    bounding_box: Optional[Tuple[float, float, float, float]] = None
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            'headers': self.headers,
            'rows': self.rows,
            'confidence': self.confidence
        }
        
        if self.page_number is not None:
            result['page_number'] = self.page_number
        if self.bounding_box is not None:
            result['bounding_box'] = self.bounding_box
            
        return result


@dataclass
class StructuredDocument:
    """Represents a document with extracted structured data."""
    document_id: str
    document_type: DocumentType
    fields: List[StructuredField] = field(default_factory=list)
    tables: List[StructuredTable] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    
    def add_field(self, field: StructuredField):
        """Add a structured field to the document."""
        self.fields.append(field)
    
    def add_table(self, table: StructuredTable):
        """Add a structured table to the document."""
        self.tables.append(table)
    
    def get_field(self, name: str) -> Optional[StructuredField]:
        """Get a field by name."""
        for field in self.fields:
            if field.name == name:
                return field
        return None
    
    def get_fields_by_type(self, field_type: FieldType) -> List[StructuredField]:
        """Get all fields of a specific type."""
        return [field for field in self.fields if field.field_type == field_type]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'document_id': self.document_id,
            'document_type': self.document_type.value,
            'fields': [field.to_dict() for field in self.fields],
            'tables': [table.to_dict() for table in self.tables],
            'metadata': self.metadata,
            'confidence': self.confidence
        }


class StructuredOutputConfig:
    """Configuration for structured output extraction."""
    
    def __init__(self,
                 extract_forms: bool = True,
                 extract_tables: bool = True,
                 extract_key_value_pairs: bool = True,
                 min_confidence: float = 0.5,
                 enable_field_validation: bool = True,
                 custom_patterns: Optional[Dict[str, str]] = None):
        """
        Initialize structured output configuration.
        
        Args:
            extract_forms: Whether to extract form fields
            extract_tables: Whether to extract tables
            extract_key_value_pairs: Whether to extract key-value pairs
            min_confidence: Minimum confidence threshold for extraction
            enable_field_validation: Whether to validate extracted fields
            custom_patterns: Custom regex patterns for field extraction
        """
        self.extract_forms = extract_forms
        self.extract_tables = extract_tables
        self.extract_key_value_pairs = extract_key_value_pairs
        self.min_confidence = min_confidence
        self.enable_field_validation = enable_field_validation
        self.custom_patterns = custom_patterns or {}


class DocumentTypeClassifier:
    """Classifies document types for structured extraction."""
    
    def __init__(self, logger: Optional[StructuredLogger] = None):
        """Initialize the document type classifier."""
        self.logger = logger or create_logger(f"{__name__}.DocumentTypeClassifier")
        
        # Patterns for document type classification
        self.type_patterns = {
            DocumentType.FORM: [
                r'\b(application|form|questionnaire|survey)\b',
                r'\b(name|address|phone|email):\s*[_\s]*$',
                r'\[\s*\]\s*(yes|no|check|select)',
                r'signature:\s*[_\s]*$'
            ],
            DocumentType.INVOICE: [
                r'\b(invoice|bill|billing|payment)\b',
                r'\b(total|subtotal|tax|amount due)\b',
                r'\b(invoice\s*#|bill\s*#|reference\s*#)\b',
                r'\b(due\s*date|payment\s*terms)\b'
            ],
            DocumentType.RECEIPT: [
                r'\b(receipt|transaction|purchase)\b',
                r'\b(total|subtotal|tax|change)\b',
                r'\b(card\s*#|transaction\s*#)\b',
                r'\b(thank\s*you|visit\s*again)\b'
            ],
            DocumentType.TABLE: [
                r'\|.*\|.*\|',  # Table separators
                r'^\s*\w+\s+\w+\s+\w+\s*$',  # Column-like data
                r'\b(table|chart|data|results)\b'
            ],
            DocumentType.CONTRACT: [
                r'\b(contract|agreement|terms|conditions)\b',
                r'\b(party|parties|whereas|therefore)\b',
                r'\b(signature|witness|notary)\b'
            ]
        }
    
    def classify_document(self, text: str, context: Optional[LogContext] = None) -> DocumentType:
        """
        Classify the document type based on text content.
        
        Args:
            text: Document text content
            context: Optional log context
            
        Returns:
            Classified document type
        """
        if not text or not text.strip():
            return DocumentType.UNKNOWN
        
        text_lower = text.lower()
        type_scores = {}
        
        # Score each document type based on pattern matches
        for doc_type, patterns in self.type_patterns.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, text_lower, re.IGNORECASE | re.MULTILINE))
                score += matches
            type_scores[doc_type] = score
        
        # Find the type with the highest score
        if type_scores:
            best_type = max(type_scores, key=type_scores.get)
            best_score = type_scores[best_type]
            
            if best_score > 0:
                self.logger.debug(
                    f"Classified document as {best_type.value} with score {best_score}",
                    context=context
                )
                return best_type
        
        # Check for mixed content (multiple types with similar scores)
        high_scores = [t for t, s in type_scores.items() if s > 0]
        if len(high_scores) > 1:
            return DocumentType.MIXED
        
        return DocumentType.UNKNOWN


class FieldExtractor:
    """Extracts structured fields from document text."""

    def __init__(self, config: StructuredOutputConfig, logger: Optional[StructuredLogger] = None):
        """Initialize the field extractor."""
        self.config = config
        self.logger = logger or create_logger(f"{__name__}.FieldExtractor")

        # Common field patterns
        self.field_patterns = {
            FieldType.EMAIL: r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            FieldType.PHONE: r'\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b',
            FieldType.DATE: r'\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b',
            FieldType.CURRENCY: r'\$\s*\d+(?:,\d{3})*(?:\.\d{2})?',
            FieldType.PERCENTAGE: r'\d+(?:\.\d+)?%',
            FieldType.NUMBER: r'\b\d+(?:,\d{3})*(?:\.\d+)?\b'
        }

        # Add custom patterns from config
        self.field_patterns.update(self.config.custom_patterns)

    def extract_key_value_pairs(self, text: str, page_number: Optional[int] = None,
                               context: Optional[LogContext] = None) -> List[StructuredField]:
        """Extract key-value pairs from text."""
        fields = []

        if not self.config.extract_key_value_pairs:
            return fields

        # Pattern for key-value pairs (key: value, key = value, etc.)
        kv_patterns = [
            r'([A-Za-z][A-Za-z0-9\s]+?):\s*([^\n\r]+)',
            r'([A-Za-z][A-Za-z0-9\s]+?)\s*=\s*([^\n\r]+)',
            r'([A-Za-z][A-Za-z0-9\s]+?)\s*-\s*([^\n\r]+)'
        ]

        for pattern in kv_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                key = match.group(1).strip()
                value = match.group(2).strip()

                if len(key) > 2 and len(value) > 0 and len(value) < 200:
                    # Determine field type based on value
                    field_type = self._classify_field_type(value)

                    field = StructuredField(
                        name=key,
                        value=value,
                        field_type=field_type,
                        page_number=page_number,
                        raw_text=match.group(0)
                    )

                    fields.append(field)

        self.logger.debug(f"Extracted {len(fields)} key-value pairs", context=context)
        return fields

    def extract_typed_fields(self, text: str, page_number: Optional[int] = None,
                           context: Optional[LogContext] = None) -> List[StructuredField]:
        """Extract fields of specific types (email, phone, etc.)."""
        fields = []

        for field_type, pattern in self.field_patterns.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for i, match in enumerate(matches):
                value = match.group(0).strip()

                field = StructuredField(
                    name=f"{field_type.value}_{i+1}",
                    value=value,
                    field_type=field_type,
                    page_number=page_number,
                    raw_text=value
                )

                fields.append(field)

        self.logger.debug(f"Extracted {len(fields)} typed fields", context=context)
        return fields

    def _classify_field_type(self, value: str) -> FieldType:
        """Classify the type of a field value."""
        value_lower = value.lower().strip()

        # Check specific patterns
        for field_type, pattern in self.field_patterns.items():
            if re.match(pattern, value, re.IGNORECASE):
                return field_type

        # Check for boolean values
        if value_lower in ['yes', 'no', 'true', 'false', 'y', 'n']:
            return FieldType.BOOLEAN

        # Default to text
        return FieldType.TEXT


class TableExtractor:
    """Extracts structured tables from document text."""

    def __init__(self, config: StructuredOutputConfig, logger: Optional[StructuredLogger] = None):
        """Initialize the table extractor."""
        self.config = config
        self.logger = logger or create_logger(f"{__name__}.TableExtractor")

    def extract_tables(self, text: str, page_number: Optional[int] = None,
                      context: Optional[LogContext] = None) -> List[StructuredTable]:
        """Extract tables from text content."""
        tables = []

        if not self.config.extract_tables:
            return tables

        # Look for markdown-style tables
        markdown_tables = self._extract_markdown_tables(text, page_number)
        tables.extend(markdown_tables)

        # Look for pipe-separated tables
        pipe_tables = self._extract_pipe_tables(text, page_number)
        tables.extend(pipe_tables)

        self.logger.debug(f"Extracted {len(tables)} tables", context=context)
        return tables

    def _extract_markdown_tables(self, text: str, page_number: Optional[int] = None) -> List[StructuredTable]:
        """Extract markdown-style tables."""
        tables = []

        # Pattern for markdown tables
        table_pattern = r'(\|[^\n]+\|\n\|[-\s|:]+\|\n(?:\|[^\n]+\|\n?)+)'

        matches = re.finditer(table_pattern, text, re.MULTILINE)
        for match in matches:
            table_text = match.group(1)
            table = self._parse_markdown_table(table_text, page_number)
            if table:
                tables.append(table)

        return tables

    def _extract_pipe_tables(self, text: str, page_number: Optional[int] = None) -> List[StructuredTable]:
        """Extract pipe-separated tables."""
        tables = []

        lines = text.split('\n')
        current_table_lines = []

        for line in lines:
            if '|' in line and len(line.split('|')) >= 3:
                current_table_lines.append(line)
            else:
                if len(current_table_lines) >= 2:  # At least header + one row
                    table = self._parse_pipe_table(current_table_lines, page_number)
                    if table:
                        tables.append(table)
                current_table_lines = []

        # Check for table at end of text
        if len(current_table_lines) >= 2:
            table = self._parse_pipe_table(current_table_lines, page_number)
            if table:
                tables.append(table)

        return tables

    def _parse_markdown_table(self, table_text: str, page_number: Optional[int] = None) -> Optional[StructuredTable]:
        """Parse a markdown table."""
        lines = [line.strip() for line in table_text.split('\n') if line.strip()]

        if len(lines) < 3:  # Need header, separator, and at least one row
            return None

        # Parse header
        header_line = lines[0]
        headers = [cell.strip() for cell in header_line.split('|')[1:-1]]

        # Skip separator line (lines[1])

        # Parse rows
        rows = []
        for line in lines[2:]:
            if '|' in line:
                row = [cell.strip() for cell in line.split('|')[1:-1]]
                if len(row) == len(headers):
                    rows.append(row)

        if not rows:
            return None

        return StructuredTable(
            headers=headers,
            rows=rows,
            page_number=page_number
        )

    def _parse_pipe_table(self, lines: List[str], page_number: Optional[int] = None) -> Optional[StructuredTable]:
        """Parse a pipe-separated table."""
        if not lines:
            return None

        # Use first line as headers
        header_line = lines[0]
        headers = [cell.strip() for cell in header_line.split('|') if cell.strip()]

        if not headers:
            return None

        # Parse remaining lines as rows
        rows = []
        for line in lines[1:]:
            row = [cell.strip() for cell in line.split('|') if cell.strip()]
            if len(row) == len(headers):
                rows.append(row)

        if not rows:
            return None

        return StructuredTable(
            headers=headers,
            rows=rows,
            page_number=page_number
        )


# Factory functions for basic components
def create_structured_output_config(**kwargs) -> StructuredOutputConfig:
    """Create a structured output configuration."""
    return StructuredOutputConfig(**kwargs)


def create_document_type_classifier(logger: Optional[StructuredLogger] = None) -> DocumentTypeClassifier:
    """Create a document type classifier."""
    return DocumentTypeClassifier(logger)


def create_field_extractor(config: StructuredOutputConfig,
                          logger: Optional[StructuredLogger] = None) -> FieldExtractor:
    """Create a field extractor."""
    return FieldExtractor(config, logger)


def create_table_extractor(config: StructuredOutputConfig,
                          logger: Optional[StructuredLogger] = None) -> TableExtractor:
    """Create a table extractor."""
    return TableExtractor(config, logger)


# Import processor and formatter from submodules
try:
    from .processor import (
        StructuredOutputProcessor, StructuredOutputFormatter,
        create_structured_output_processor, create_structured_output_formatter
    )
except ImportError:
    # Fallback if processor module is not available
    def create_structured_output_processor(config: StructuredOutputConfig,
                                         logger: Optional[StructuredLogger] = None):
        """Create a structured output processor (fallback)."""
        raise ImportError("Processor module not available")

    def create_structured_output_formatter(logger: Optional[StructuredLogger] = None):
        """Create a structured output formatter (fallback)."""
        raise ImportError("Formatter module not available")
