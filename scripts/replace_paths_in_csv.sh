#!/bin/bash
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <s3://path/to/file.csv.zstd>"
    exit 1
fi

S3_PATH="$1"
BACKUP_PATH="${S3_PATH}.bak"
TEMP_DIR=$(mktemp -d)
LOCAL_FILE="${TEMP_DIR}/file.csv.zstd"
LOCAL_CSV="${TEMP_DIR}/file.csv"

trap "rm -rf ${TEMP_DIR}" EXIT

echo "Downloading ${S3_PATH}..."
aws s3 cp "${S3_PATH}" "${LOCAL_FILE}"

echo "Creating backup at ${BACKUP_PATH}..."
aws s3 cp "${S3_PATH}" "${BACKUP_PATH}"

echo "Decompressing..."
zstd -d "${LOCAL_FILE}" -o "${LOCAL_CSV}"

echo "Replacing paths..."
sed -i -E 's|/lustre/orion/csc652/scratch/jakep/dolma4pdfs/olmo-crawled-pdfs_split[0-9]+/|s3://ai2-oe-data/jakep/dolma4pdfs_frontier/olmo-crawled-pdfs/|g' "${LOCAL_CSV}"

echo "Compressing..."
zstd -f "${LOCAL_CSV}" -o "${LOCAL_FILE}"

echo "Uploading to ${S3_PATH}..."
aws s3 cp "${LOCAL_FILE}" "${S3_PATH}"

echo "Done!"
