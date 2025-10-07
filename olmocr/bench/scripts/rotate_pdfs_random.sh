#!/bin/bash

# Directory containing PDFs to rotate
PDF_DIR="/home/ubuntu/olmocr/olmOCR-bench-0825/bench_data/pdfs/rotated"

# Check if directory exists
if [ ! -d "$PDF_DIR" ]; then
    echo "Error: Directory $PDF_DIR does not exist"
    exit 1
fi

# Check if qpdf is installed (preferred for PDF rotation)
if ! command -v qpdf &> /dev/null; then
    echo "qpdf is not installed. Installing..."
    sudo apt-get update && sudo apt-get install -y qpdf
fi

# Counter for processed files
total=0
success=0
failed=0

echo "Processing PDFs in $PDF_DIR"
echo "----------------------------------------"

# Process each PDF file
for pdf_file in "$PDF_DIR"/*.pdf; do
    # Check if any PDF files exist
    if [ ! -f "$pdf_file" ]; then
        echo "No PDF files found in $PDF_DIR"
        exit 1
    fi
    
    # Get filename
    filename=$(basename "$pdf_file")
    
    # Randomly select rotation angle (90, 180, or 270)
    angles=(90 180 270)
    rotation=${angles[$RANDOM % ${#angles[@]}]}
    
    echo "Rotating $filename by $rotation degrees..."
    
    # Create temporary file for rotated PDF
    temp_file="${pdf_file}.tmp"
    
    # Rotate the PDF using qpdf
    if qpdf "$pdf_file" "$temp_file" --rotate=+$rotation; then
        # Replace original with rotated version
        mv "$temp_file" "$pdf_file"
        echo "  ✓ Successfully rotated $filename by $rotation degrees"
        ((success++))
    else
        echo "  ✗ Failed to rotate $filename"
        rm -f "$temp_file"
        ((failed++))
    fi
    
    ((total++))
done

echo "----------------------------------------"
echo "Summary:"
echo "  Total PDFs processed: $total"
echo "  Successfully rotated: $success"
if [ $failed -gt 0 ]; then
    echo "  Failed: $failed"
fi