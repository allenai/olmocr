#!/bin/bash

set -e
gantry run --gpus 1 --workspace ai2/olmocr --beaker-image ai2/pytorch2.5.1-cuda12.1-python3.11 --cluster ai2/jupiter --cluster ai2/ceres --cluster ai2/saturn --cluster ai2/neptune --budget ai2/oe-base --priority high --env-secret AWS_CREDENTIALS_FILE=jakep-AWS_CREDENTIALS_FILE --env-secret HF_TOKEN=jake-HF_TOKEN --allow-dirty -- /bin/bash -c "pip install -e .[gpu] --find-links https://flashinfer.ai/whl/cu124/torch2.4/flashinfer/ && pip install --upgrade sglang==0.4.5.post3 transformers==4.51.3 && python scripts/tagging_pipeline.py s3://ai2-llm/pretraining-data/sources/HuggingFaceFW_finepdfs/deduped_eng/ s3://ai2-llm/pretraining-data/sources/HuggingFaceFW_finepdfs/scratch/deduped_eng/pii_tag1"
