#!/usr/bin/env python3
"""
Demonstration script for structured output capabilities.

This script demonstrates the structured output extraction features including
form field extraction, table parsing, and JSON schema validation.
"""

import json
import tempfile
from typing import Dict, Any

from olmocr.structured_output import (
    create_structured_output_config, create_structured_output_processor,
    create_structured_output_formatter, DocumentType, FieldType
)
from olmocr.structured_output.schema import create_structured_output_validator
from olmocr.error_handling import create_logger


def demo_form_extraction():
    """Demonstrate form field extraction."""
    print("📋 Demonstrating Form Field Extraction...")
    
    form_text = """
    CUSTOMER REGISTRATION FORM
    
    Personal Information:
    Name: John Smith
    Email: john.smith@email.com
    Phone: (555) 123-4567
    Date of Birth: 03/15/1985
    Address: 123 Main Street, Anytown, ST 12345
    
    Account Details:
    Username: jsmith123
    Password: ********
    Security Question: What is your mother's maiden name?
    Answer: Johnson
    
    Preferences:
    Newsletter: [ X ] Yes [ ] No
    Marketing Emails: [ ] Yes [ X ] No
    Account Type: Premium
    Monthly Budget: $500.00
    Discount Rate: 15%
    
    Agreement:
    I agree to the terms and conditions: [X] Yes
    
    Signature: John Smith
    Date: 12/01/2023
    """
    
    # Create configuration for form extraction
    config = create_structured_output_config(
        extract_forms=True,
        extract_tables=False,
        extract_key_value_pairs=True,
        min_confidence=0.5
    )
    
    # Create processor
    logger = create_logger("demo.form_extraction")
    processor = create_structured_output_processor(config, logger)
    
    # Process the form
    structured_doc = processor.process_document(
        document_id="customer-form-001",
        text_content=form_text
    )
    
    print(f"   📄 Document Type: {structured_doc.document_type.value}")
    print(f"   📊 Fields Extracted: {len(structured_doc.fields)}")
    
    # Show extracted fields by type
    field_types = {}
    for field in structured_doc.fields:
        field_type = field.field_type.value
        if field_type not in field_types:
            field_types[field_type] = []
        field_types[field_type].append(f"{field.name}: {field.value}")
    
    for field_type, fields in field_types.items():
        print(f"   🏷️ {field_type.upper()} fields:")
        for field in fields[:3]:  # Show first 3 fields of each type
            print(f"      {field}")
        if len(fields) > 3:
            print(f"      ... and {len(fields) - 3} more")
    
    print("   ✅ Form extraction completed")
    print()
    return structured_doc


def demo_table_extraction():
    """Demonstrate table extraction."""
    print("📊 Demonstrating Table Extraction...")
    
    table_text = """
    QUARTERLY SALES REPORT
    
    Regional Performance Summary:
    
    | Region    | Q1 Sales | Q2 Sales | Q3 Sales | Q4 Sales | Total    |
    |-----------|----------|----------|----------|----------|----------|
    | North     | $125,000 | $135,000 | $142,000 | $158,000 | $560,000 |
    | South     | $98,000  | $105,000 | $112,000 | $125,000 | $440,000 |
    | East      | $156,000 | $162,000 | $171,000 | $185,000 | $674,000 |
    | West      | $134,000 | $141,000 | $148,000 | $165,000 | $588,000 |
    | Total     | $513,000 | $543,000 | $573,000 | $633,000 | $2,262,000|
    
    Product Performance:
    
    Product A | 1,250 units | $62,500
    Product B | 2,100 units | $105,000
    Product C | 875 units   | $43,750
    Product D | 1,650 units | $82,500
    
    Top Performers:
    1. Sarah Johnson - $45,000
    2. Mike Chen - $42,500
    3. Lisa Rodriguez - $38,750
    """
    
    # Create configuration for table extraction
    config = create_structured_output_config(
        extract_forms=False,
        extract_tables=True,
        extract_key_value_pairs=False,
        min_confidence=0.5
    )
    
    # Create processor
    logger = create_logger("demo.table_extraction")
    processor = create_structured_output_processor(config, logger)
    
    # Process the document
    structured_doc = processor.process_document(
        document_id="sales-report-q4",
        text_content=table_text
    )
    
    print(f"   📄 Document Type: {structured_doc.document_type.value}")
    print(f"   📊 Tables Extracted: {len(structured_doc.tables)}")
    
    # Show extracted tables
    for i, table in enumerate(structured_doc.tables):
        print(f"   📋 Table {i+1}:")
        print(f"      Headers: {', '.join(table.headers)}")
        print(f"      Rows: {len(table.rows)}")
        print(f"      Sample data: {table.rows[0] if table.rows else 'No data'}")
        print(f"      Confidence: {table.confidence:.2f}")
    
    print("   ✅ Table extraction completed")
    print()
    return structured_doc


def demo_mixed_document():
    """Demonstrate mixed document processing."""
    print("📄 Demonstrating Mixed Document Processing...")
    
    mixed_text = """
    INVOICE #INV-2023-001
    
    Bill To:
    Company: Acme Corporation
    Contact: Jane Doe
    Email: jane.doe@acme.com
    Phone: (555) 987-6543
    Address: 456 Business Ave, Corporate City, ST 54321
    
    Invoice Details:
    Invoice Date: 12/01/2023
    Due Date: 12/31/2023
    Payment Terms: Net 30
    Reference: PO-2023-456
    
    Items:
    | Description        | Qty | Unit Price | Total    |
    |--------------------|-----|------------|----------|
    | Web Development    | 40  | $125.00    | $5,000   |
    | Database Setup     | 8   | $150.00    | $1,200   |
    | Testing & QA       | 16  | $100.00    | $1,600   |
    | Project Management | 12  | $175.00    | $2,100   |
    
    Summary:
    Subtotal: $9,900.00
    Tax (8.5%): $841.50
    Total Amount Due: $10,741.50
    
    Payment Information:
    Method: Check or Bank Transfer
    Account: 123-456-7890
    Routing: 987654321
    
    Thank you for your business!
    """
    
    # Create configuration for mixed extraction
    config = create_structured_output_config(
        extract_forms=True,
        extract_tables=True,
        extract_key_value_pairs=True,
        min_confidence=0.4  # Lower threshold for mixed content
    )
    
    # Create processor
    logger = create_logger("demo.mixed_document")
    processor = create_structured_output_processor(config, logger)
    
    # Process the document
    structured_doc = processor.process_document(
        document_id="invoice-2023-001",
        text_content=mixed_text
    )
    
    print(f"   📄 Document Type: {structured_doc.document_type.value}")
    print(f"   📊 Fields Extracted: {len(structured_doc.fields)}")
    print(f"   📋 Tables Extracted: {len(structured_doc.tables)}")
    
    # Show field breakdown
    field_counts = {}
    for field in structured_doc.fields:
        field_type = field.field_type.value
        field_counts[field_type] = field_counts.get(field_type, 0) + 1
    
    print("   🏷️ Field breakdown:")
    for field_type, count in field_counts.items():
        print(f"      {field_type}: {count}")
    
    # Show table info
    if structured_doc.tables:
        table = structured_doc.tables[0]
        print(f"   📋 Main table: {len(table.headers)} columns, {len(table.rows)} rows")
    
    print("   ✅ Mixed document processing completed")
    print()
    return structured_doc


def demo_json_output_formatting():
    """Demonstrate JSON output formatting and validation."""
    print("🔧 Demonstrating JSON Output Formatting...")
    
    # Use the form document from earlier demo
    form_doc = demo_form_extraction()
    
    # Create formatter
    logger = create_logger("demo.json_formatting")
    formatter = create_structured_output_formatter(logger)
    
    # Format as JSON
    json_output = formatter.format_as_json(form_doc, pretty=True)
    
    print("   📝 JSON Output Sample:")
    # Show first few lines of JSON
    lines = json_output.split('\n')
    for line in lines[:15]:
        print(f"      {line}")
    if len(lines) > 15:
        print(f"      ... ({len(lines) - 15} more lines)")
    
    # Validate JSON schema
    validator = create_structured_output_validator(logger)
    is_valid = validator.validate_json_string(json_output, "document")
    
    print(f"   ✅ JSON Schema Validation: {'PASSED' if is_valid else 'FAILED'}")
    
    if not is_valid:
        errors = validator.get_validation_errors(json.loads(json_output), "document")
        print("   ❌ Validation Errors:")
        for error in errors[:3]:  # Show first 3 errors
            print(f"      {error}")
    
    print("   ✅ JSON formatting completed")
    print()


def demo_combined_output():
    """Demonstrate combined Dolma + structured output."""
    print("🔗 Demonstrating Combined Output Format...")
    
    # Create a sample Dolma document
    dolma_doc = {
        "id": "demo-doc-12345",
        "text": "Sample document text content...",
        "source": "olmocr",
        "added": "2023-12-01",
        "created": "2023-12-01",
        "metadata": {
            "Source-File": "/path/to/document.pdf",
            "olmocr-version": "1.0.0",
            "pdf-total-pages": 3
        },
        "attributes": {
            "pdf_page_numbers": [[0, 100, 1], [100, 200, 2], [200, 300, 3]]
        }
    }
    
    # Get structured document from table demo
    structured_doc = demo_table_extraction()
    
    # Create formatter and combine
    logger = create_logger("demo.combined_output")
    formatter = create_structured_output_formatter(logger)
    
    combined_doc = formatter.format_combined_output(dolma_doc, structured_doc)
    
    print("   📄 Combined Document Structure:")
    print(f"      Original Dolma fields: {len([k for k in dolma_doc.keys() if k != 'structured_data'])}")
    print(f"      Has structured data: {combined_doc['metadata']['has_structured_data']}")
    print(f"      Structured fields: {combined_doc['metadata']['structured_fields_count']}")
    print(f"      Structured tables: {combined_doc['metadata']['structured_tables_count']}")
    print(f"      Document type: {combined_doc['metadata']['document_type']}")
    
    # Validate combined document
    validator = create_structured_output_validator(logger)
    is_valid = validator.validate_combined_document(combined_doc)
    
    print(f"   ✅ Combined Document Validation: {'PASSED' if is_valid else 'FAILED'}")
    
    # Export to file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(combined_doc, f, indent=2)
        print(f"   💾 Combined document exported to: {f.name}")
    
    print("   ✅ Combined output demonstration completed")
    print()


def demo_cli_integration():
    """Demonstrate CLI integration examples."""
    print("💻 Demonstrating CLI Integration...")
    
    print("   📝 Example CLI commands:")
    print()
    
    print("   🔹 Basic structured output:")
    print("      python -m olmocr.pipeline /workspace --structured-output")
    print()
    
    print("   🔹 Extract only forms:")
    print("      python -m olmocr.pipeline /workspace --structured-output --extract-forms")
    print()
    
    print("   🔹 Extract only tables:")
    print("      python -m olmocr.pipeline /workspace --structured-output --extract-tables")
    print()
    
    print("   🔹 High confidence extraction:")
    print("      python -m olmocr.pipeline /workspace --structured-output --structured-min-confidence 0.8")
    print()
    
    print("   🔹 JSON-only output:")
    print("      python -m olmocr.pipeline /workspace --structured-output --structured-output-format json")
    print()
    
    print("   📋 Available structured output options:")
    print("      --structured-output              Enable structured output extraction")
    print("      --extract-forms                  Extract form fields and key-value pairs")
    print("      --extract-tables                 Extract tables in structured format")
    print("      --extract-key-value-pairs        Extract key-value pairs from documents")
    print("      --structured-min-confidence      Minimum confidence threshold (default: 0.5)")
    print("      --structured-output-format       Output format: 'json' or 'combined' (default: combined)")
    
    print("   ✅ CLI integration examples completed")
    print()


async def main():
    """Run all structured output demonstrations."""
    print("=" * 70)
    print("🚀 Structured Output Capabilities Demonstration")
    print("=" * 70)
    print()
    
    print("This demonstration shows the comprehensive structured output")
    print("extraction capabilities implemented for the OLMoCR pipeline:")
    print()
    
    # Run all demonstrations
    demo_form_extraction()
    demo_table_extraction()
    demo_mixed_document()
    demo_json_output_formatting()
    demo_combined_output()
    demo_cli_integration()
    
    print("=" * 70)
    print("✅ STRUCTURED OUTPUT DEMONSTRATION COMPLETE!")
    print("=" * 70)
    print()
    print("Key features demonstrated:")
    print("  📋 Form field extraction with type classification")
    print("  📊 Table parsing for markdown and pipe-separated formats")
    print("  🏷️ Automatic document type classification")
    print("  🔧 JSON schema validation for output consistency")
    print("  🔗 Combined Dolma + structured data output")
    print("  💻 CLI integration with flexible configuration options")
    print()
    print("Benefits achieved:")
    print("  ✅ Extract structured data from forms, invoices, and reports")
    print("  ✅ Maintain backward compatibility with existing text output")
    print("  ✅ Provide JSON schema validation for data quality")
    print("  ✅ Support flexible extraction configurations")
    print("  ✅ Enable easy integration with downstream processing")
    print()
    print("Ready for production use with forms and structured documents! 🎉")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
