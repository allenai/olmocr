#/usr/bin/bash

set -ex

python -m olmocr.pipeline ./localworkspace --pdfs tests/gnarly_pdfs/ambiguous.pdf tests/gnarly_pdfs/edgar.pdf tests/gnarly_pdfs/dolma-page-1.pdf \
  && pytest -m "" tests/test_integration.py
