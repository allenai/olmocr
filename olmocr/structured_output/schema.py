"""
JSON Schema validation for structured output.

This module provides JSON schema definitions and validation for structured
output formats to ensure consistency and data quality.
"""

import json
from typing import Dict, Any, Optional, List
from jsonschema import validate, ValidationError, Draft7Validator

from olmocr.error_handling import (
    StructuredLogger, LogContext, create_logger,
    ValidationError as OLMoCRValidationError, ErrorContext
)


# JSON Schema for structured field
STRUCTURED_FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "value": {"type": ["string", "number", "boolean", "null"]},
        "type": {
            "type": "string",
            "enum": ["text", "number", "date", "email", "phone", "address", 
                    "currency", "percentage", "boolean", "list", "table"]
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "page_number": {"type": ["integer", "null"], "minimum": 1},
        "bounding_box": {
            "type": ["array", "null"],
            "items": {"type": "number"},
            "minItems": 4,
            "maxItems": 4
        },
        "raw_text": {"type": ["string", "null"]}
    },
    "required": ["name", "value", "type", "confidence"],
    "additionalProperties": False
}

# JSON Schema for structured table
STRUCTURED_TABLE_SCHEMA = {
    "type": "object",
    "properties": {
        "headers": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1
        },
        "rows": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": ["string", "number", "boolean", "null"]}
            },
            "minItems": 1
        },
        "page_number": {"type": ["integer", "null"], "minimum": 1},
        "bounding_box": {
            "type": ["array", "null"],
            "items": {"type": "number"},
            "minItems": 4,
            "maxItems": 4
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": ["headers", "rows", "confidence"],
    "additionalProperties": False
}

# JSON Schema for structured document
STRUCTURED_DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "document_id": {"type": "string", "minLength": 1},
        "document_type": {
            "type": "string",
            "enum": ["form", "table", "invoice", "receipt", "contract", "report", "mixed", "unknown"]
        },
        "fields": {
            "type": "array",
            "items": STRUCTURED_FIELD_SCHEMA
        },
        "tables": {
            "type": "array",
            "items": STRUCTURED_TABLE_SCHEMA
        },
        "metadata": {"type": "object"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": ["document_id", "document_type", "fields", "tables", "metadata", "confidence"],
    "additionalProperties": False
}

# JSON Schema for combined Dolma + structured document
COMBINED_DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "text": {"type": "string"},
        "source": {"type": "string"},
        "added": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "created": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "metadata": {
            "type": "object",
            "properties": {
                "has_structured_data": {"type": "boolean"},
                "structured_fields_count": {"type": "integer", "minimum": 0},
                "structured_tables_count": {"type": "integer", "minimum": 0},
                "document_type": {"type": "string"}
            }
        },
        "attributes": {"type": "object"},
        "structured_data": STRUCTURED_DOCUMENT_SCHEMA
    },
    "required": ["id", "text", "source", "added", "created", "metadata", "attributes"],
    "additionalProperties": False
}


class StructuredOutputValidator:
    """Validates structured output against JSON schemas."""
    
    def __init__(self, logger: Optional[StructuredLogger] = None):
        """Initialize the validator."""
        self.logger = logger or create_logger(f"{__name__}.StructuredOutputValidator")
        
        # Create validators for each schema
        self.field_validator = Draft7Validator(STRUCTURED_FIELD_SCHEMA)
        self.table_validator = Draft7Validator(STRUCTURED_TABLE_SCHEMA)
        self.document_validator = Draft7Validator(STRUCTURED_DOCUMENT_SCHEMA)
        self.combined_validator = Draft7Validator(COMBINED_DOCUMENT_SCHEMA)
    
    def validate_field(self, field_data: Dict[str, Any], 
                      context: Optional[LogContext] = None) -> bool:
        """
        Validate a structured field against the schema.
        
        Args:
            field_data: Field data to validate
            context: Optional log context
            
        Returns:
            True if valid, False otherwise
        """
        try:
            self.field_validator.validate(field_data)
            return True
        except ValidationError as e:
            self.logger.warning(
                f"Field validation failed: {e.message}",
                context=context
            )
            return False
    
    def validate_table(self, table_data: Dict[str, Any],
                      context: Optional[LogContext] = None) -> bool:
        """
        Validate a structured table against the schema.
        
        Args:
            table_data: Table data to validate
            context: Optional log context
            
        Returns:
            True if valid, False otherwise
        """
        try:
            self.table_validator.validate(table_data)
            
            # Additional validation: check that all rows have same number of columns as headers
            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])
            
            for i, row in enumerate(rows):
                if len(row) != len(headers):
                    self.logger.warning(
                        f"Table validation failed: Row {i} has {len(row)} columns but headers have {len(headers)}",
                        context=context
                    )
                    return False
            
            return True
        except ValidationError as e:
            self.logger.warning(
                f"Table validation failed: {e.message}",
                context=context
            )
            return False
    
    def validate_document(self, document_data: Dict[str, Any],
                         context: Optional[LogContext] = None) -> bool:
        """
        Validate a structured document against the schema.
        
        Args:
            document_data: Document data to validate
            context: Optional log context
            
        Returns:
            True if valid, False otherwise
        """
        try:
            self.document_validator.validate(document_data)
            
            # Additional validation for fields and tables
            fields = document_data.get("fields", [])
            for i, field in enumerate(fields):
                if not self.validate_field(field, context):
                    self.logger.warning(f"Document validation failed: Invalid field at index {i}", context=context)
                    return False
            
            tables = document_data.get("tables", [])
            for i, table in enumerate(tables):
                if not self.validate_table(table, context):
                    self.logger.warning(f"Document validation failed: Invalid table at index {i}", context=context)
                    return False
            
            return True
        except ValidationError as e:
            self.logger.warning(
                f"Document validation failed: {e.message}",
                context=context
            )
            return False
    
    def validate_combined_document(self, combined_data: Dict[str, Any],
                                  context: Optional[LogContext] = None) -> bool:
        """
        Validate a combined Dolma + structured document against the schema.
        
        Args:
            combined_data: Combined document data to validate
            context: Optional log context
            
        Returns:
            True if valid, False otherwise
        """
        try:
            # First validate the overall structure
            self.combined_validator.validate(combined_data)
            
            # If structured data is present, validate it separately
            structured_data = combined_data.get("structured_data")
            if structured_data:
                if not self.validate_document(structured_data, context):
                    self.logger.warning("Combined document validation failed: Invalid structured data", context=context)
                    return False
            
            return True
        except ValidationError as e:
            self.logger.warning(
                f"Combined document validation failed: {e.message}",
                context=context
            )
            return False
    
    def get_validation_errors(self, data: Dict[str, Any], 
                            schema_type: str = "document") -> List[str]:
        """
        Get detailed validation errors for debugging.
        
        Args:
            data: Data to validate
            schema_type: Type of schema to validate against ("field", "table", "document", "combined")
            
        Returns:
            List of validation error messages
        """
        validator_map = {
            "field": self.field_validator,
            "table": self.table_validator,
            "document": self.document_validator,
            "combined": self.combined_validator
        }
        
        validator = validator_map.get(schema_type, self.document_validator)
        errors = []
        
        for error in validator.iter_errors(data):
            error_path = " -> ".join(str(p) for p in error.absolute_path)
            error_msg = f"Path: {error_path}, Error: {error.message}"
            errors.append(error_msg)
        
        return errors
    
    def validate_json_string(self, json_string: str, 
                           schema_type: str = "document",
                           context: Optional[LogContext] = None) -> bool:
        """
        Validate a JSON string against the specified schema.
        
        Args:
            json_string: JSON string to validate
            schema_type: Type of schema to validate against
            context: Optional log context
            
        Returns:
            True if valid, False otherwise
        """
        try:
            data = json.loads(json_string)
        except json.JSONDecodeError as e:
            self.logger.warning(f"Invalid JSON: {e}", context=context)
            return False
        
        validation_methods = {
            "field": self.validate_field,
            "table": self.validate_table,
            "document": self.validate_document,
            "combined": self.validate_combined_document
        }
        
        validate_method = validation_methods.get(schema_type, self.validate_document)
        return validate_method(data, context)


class SchemaGenerator:
    """Generates JSON schemas for custom structured output formats."""
    
    def __init__(self, logger: Optional[StructuredLogger] = None):
        """Initialize the schema generator."""
        self.logger = logger or create_logger(f"{__name__}.SchemaGenerator")
    
    def generate_custom_field_schema(self, field_types: List[str],
                                   required_fields: List[str] = None) -> Dict[str, Any]:
        """
        Generate a custom schema for specific field types.
        
        Args:
            field_types: List of allowed field types
            required_fields: List of required field names
            
        Returns:
            Custom JSON schema
        """
        schema = STRUCTURED_FIELD_SCHEMA.copy()
        
        # Update allowed field types
        schema["properties"]["type"]["enum"] = field_types
        
        # Add required field names if specified
        if required_fields:
            schema["properties"]["name"]["enum"] = required_fields
        
        return schema
    
    def generate_form_schema(self, form_fields: Dict[str, str]) -> Dict[str, Any]:
        """
        Generate a schema for a specific form structure.
        
        Args:
            form_fields: Dictionary mapping field names to field types
            
        Returns:
            Form-specific JSON schema
        """
        properties = {}
        required = []
        
        for field_name, field_type in form_fields.items():
            properties[field_name] = {
                "type": "object",
                "properties": {
                    "value": {"type": ["string", "number", "boolean", "null"]},
                    "type": {"type": "string", "const": field_type},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                },
                "required": ["value", "type", "confidence"]
            }
            required.append(field_name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False
        }
    
    def generate_table_schema(self, column_names: List[str],
                            column_types: List[str] = None) -> Dict[str, Any]:
        """
        Generate a schema for a specific table structure.
        
        Args:
            column_names: List of expected column names
            column_types: Optional list of column data types
            
        Returns:
            Table-specific JSON schema
        """
        schema = STRUCTURED_TABLE_SCHEMA.copy()
        
        # Set specific headers
        schema["properties"]["headers"] = {
            "type": "array",
            "items": {"type": "string", "enum": column_names},
            "minItems": len(column_names),
            "maxItems": len(column_names)
        }
        
        # Set column types if specified
        if column_types:
            row_schema = {
                "type": "array",
                "items": [{"type": col_type} for col_type in column_types],
                "minItems": len(column_types),
                "maxItems": len(column_types)
            }
            schema["properties"]["rows"]["items"] = row_schema
        
        return schema


# Factory functions
def create_structured_output_validator(logger: Optional[StructuredLogger] = None) -> StructuredOutputValidator:
    """Create a structured output validator."""
    return StructuredOutputValidator(logger)


def create_schema_generator(logger: Optional[StructuredLogger] = None) -> SchemaGenerator:
    """Create a schema generator."""
    return SchemaGenerator(logger)
