#!/usr/bin/env bash
#
# Filter JSONL files to exclude documents with PII based on model annotations.
#
# Usage:
#   ./filter_pii_jq.sh --input-folder /path/to/input --output-folder /path/to/output [--workers 8]
#
# The script expects input files at: input_folder/documents/*.jsonl.zst
# Output will be written to: output_folder/documents/*.jsonl.zst
#

set -euo pipefail

# Default values
WORKERS=8
INPUT_FOLDER=""
OUTPUT_FOLDER=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --input-folder)
            INPUT_FOLDER="$2"
            shift 2
            ;;
        --output-folder)
            OUTPUT_FOLDER="$2"
            shift 2
            ;;
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 --input-folder PATH --output-folder PATH [--workers N]"
            echo ""
            echo "Filter JSONL files to exclude documents with PII."
            echo ""
            echo "Options:"
            echo "  --input-folder   Path to folder containing documents/*.jsonl.zst"
            echo "  --output-folder  Path to output folder"
            echo "  --workers        Number of parallel workers (default: 8)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate arguments
if [[ -z "$INPUT_FOLDER" ]]; then
    echo "Error: --input-folder is required"
    exit 1
fi

if [[ -z "$OUTPUT_FOLDER" ]]; then
    echo "Error: --output-folder is required"
    exit 1
fi

INPUT_DOCS="$INPUT_FOLDER/"
OUTPUT_DOCS="$OUTPUT_FOLDER/"

if [[ ! -d "$INPUT_DOCS" ]]; then
    echo "Error: documents folder not found at $INPUT_DOCS"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DOCS"

# The jq filter - KEEP documents that do NOT match the exclude criteria
# Attributes are at root level (from merge_attributes.py output)
JQ_FILTER='
select(
  (
    (
      (.attributes["google_gemma-3-12b-it_contains_pii"] | map(.[2]) | any(. == true)) and
      ((.attributes["google_gemma-3-12b-it_is_public_document"] | map(.[2]) | any(. == true)) | not) and
      ((.attributes["google_gemma-3-4b-it_v2tag__is_academic_paper"] | map(.[2]) | any(. == true)) | not) and
      ((.attributes["google_gemma-3-4b-it_v2tag__is_textbook"] | map(.[2]) | any(. == true)) | not) and
      ((.attributes["google_gemma-3-4b-it_v2tag__is_homework_assignment"] | map(.[2]) | any(. == true)) | not) and
      ((.attributes["google_gemma-3-4b-it_v2tag__is_test_or_quiz"] | map(.[2]) | any(. == true)) | not) and
      ((.attributes["google_gemma-3-4b-it_v2tag__is_class_syllabus"] | map(.[2]) | any(. == true)) | not) and
      ((.attributes["google_gemma-3-4b-it_v2tag__is_public_order"] | map(.[2]) | any(. == true)) | not) and
      ((.attributes["google_gemma-3-4b-it_v2tag__is_news_article"] | map(.[2]) | any(. == true)) | not)
    ) or
    (
      (.attributes["google_gemma-3-4b-it_v2tag__is_resume_cv"] | map(.[2]) | any(. == true))
    ) or
    (
      (.attributes["google_gemma-3-4b-it_v2tag__is_court_notice"] | map(.[2]) | any(. == true))
    ) or
    (
      (.attributes["google_gemma-3-4b-it_v2tag__is_completion_certificate"] | map(.[2]) | any(. == true)) and
      ((.attributes["google_gemma-3-4b-it_v2tag__is_academic_paper"] | map(.[2]) | any(. == true)) | not)
    )
  ) | not
)
'

# Function to process a single file
process_file() {
    local input_file="$1"
    local output_dir="$2"
    local jq_filter="$3"

    local filename
    filename=$(basename "$input_file")
    local output_file="$output_dir/$filename"

    # Decompress, filter, recompress
    zstd -d -c "$input_file" | jq -c "$jq_filter" | zstd -c -3 > "$output_file"
}

export -f process_file

# Count total files
mapfile -t FILES < <(find "$INPUT_DOCS" -name '*.jsonl.zst' -type f | sort)
TOTAL=${#FILES[@]}

if [[ $TOTAL -eq 0 ]]; then
    echo "Error: No .jsonl.zst files found in $INPUT_DOCS"
    exit 1
fi

echo "Input folder: $INPUT_DOCS"
echo "Output folder: $OUTPUT_DOCS"
echo "Total files: $TOTAL"
echo "Workers: $WORKERS"
echo ""
echo "Starting PII filtering..."
echo ""

START_TIME=$(date +%s)

# Process files in parallel with progress bar
printf '%s\n' "${FILES[@]}" | parallel --bar -j "$WORKERS" process_file {} "$OUTPUT_DOCS" "'$JQ_FILTER'"

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "============================================================"
echo "COMPLETE"
echo "============================================================"
echo "Files processed: $TOTAL"
echo "Duration: ${DURATION}s"
echo "Output: $OUTPUT_DOCS"
