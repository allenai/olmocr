# olmOCR Training Guide

This guide provides comprehensive instructions for training olmOCR models, including what you need to reproduce https://huggingface.co/allenai/olmOCR-7B-1025-FP8 on your own hardware.

## Environment setup

The first step is to setup your python/conda environment, and set things up the same way as for running olmocr.

Then, add in some extra training requirements:

```bash
pip install .[train]
pip install transformers==4.52.4
pip install flash-attn==2.8.0.post2 --no-build-isolation
```


### Dataset Format

The training data should be organized as pairs of PDF files and their corresponding markdown annotations:

**Important: Each PDF needs to be a single page only!** 

```
data/
├── document1.pdf
├── document1.md
├── document2.pdf
├── document2.md
└── ...
```

Each markdown file should contain:
1. YAML front matter with metadata
2. The extracted text content

Example markdown format:
```markdown
---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---
Document text goes here...
```

The easiest way to grab a lot of files in this format is to use `prepare_olmocrmix.py` which will automatically download and prepare 
[olmOCR-mix-1025](https://huggingface.co/datasets/allenai/olmOCR-mix-1025) for your environment.

```bash
# Caution, requires ~200GB of disk space

# You can pick a specific split and subset to download, or just run all these commands in order to get everything
python -m olmocr.data.prepare_olmocrmix --dataset-path allenai/olmOCR-mix-1025 --destination ~/olmOCR-mix-1025-extracted --subset 00_documents --split train                       
python -m olmocr.data.prepare_olmocrmix --dataset-path allenai/olmOCR-mix-1025 --destination ~/olmOCR-mix-1025-extracted --subset 00_documents --split eval

python -m olmocr.data.prepare_olmocrmix --dataset-path allenai/olmOCR-mix-1025 --destination ~/olmOCR-mix-1025-extracted --subset 01_books --split train                       
python -m olmocr.data.prepare_olmocrmix --dataset-path allenai/olmOCR-mix-1025 --destination ~/olmOCR-mix-1025-extracted --subset 01_books --split eval

python -m olmocr.data.prepare_olmocrmix --dataset-path allenai/olmOCR-mix-1025 --destination ~/olmOCR-mix-1025-extracted --subset 02_loc_transcripts --split train                       
python -m olmocr.data.prepare_olmocrmix --dataset-path allenai/olmOCR-mix-1025 --destination ~/olmOCR-mix-1025-extracted --subset 02_loc_transcripts --split eval

python -m olmocr.data.prepare_olmocrmix --dataset-path allenai/olmOCR-mix-1025 --destination ~/olmOCR-mix-1025-extracted --subset 03_national_archives --split train                       
python -m olmocr.data.prepare_olmocrmix --dataset-path allenai/olmOCR-mix-1025 --destination ~/olmOCR-mix-1025-extracted --subset 03_national_archives --split eval

```

### Setup your config

[olmOCR-7B-0725-FP8](https://huggingface.co/allenai/olmOCR-7B-0725-FP8) was trained with [qwen25_vl_olmocrv2_2epoch.yaml](/olmcr/train/configs/v0.2.0/qwen25_vl_olmocrv2_2epoch.yaml)

[olmOCR-7B-0825-FP8](https://huggingface.co/allenai/olmOCR-7B-0825-FP8) was trained with [qwen25_vl_olmocrv3_rotation_1epoch.yaml](/olmocr/train/configs/v0.3.0/qwen25_vl_olmocrv3_rotation_1epoch.yaml)

[olmOCR-7B-1025-FP8](https://huggingface.co/allenai/olmOCR-7B-1025-FP8) was trained with [qwen25_vl_olmocrv4_rotation_1epoch_mix_1025_filtered.yaml](/olmocr/train/configs/v0.4.0/qwen25_vl_olmocrv4_rotation_1epoch_mix_1025_filtered.yaml)


This is setup to train on a single B200 GPU, and training will take around 24-48 hours (~$300 if renting). 

But this is training for ~270,000 pages per epoch, so it's quite a big endeavour. We hope to add more options to make further finetuning your own small model more simple and easy.

### Launch training

```bash
python -m olmocr.train.train --config olmocr/train/configs/v0.4.0/qwen25_vl_olmocrv4_rotation_1epoch_mix_1025_filtered.yaml
```

### Prepare Checkpoints and Quantize

After training is done, you will need to call `prepare_checkpoint.py` to take the saved checkpoints
and get them ready for use with VLLM.

```bash
python -m olmocr.train.prepare_olmocr_checkpoint [source dir]/checkpoint-xxxx [destination]
```

And finally, we recommend doing an FP8 quantization step, whose performance is solidly in the error bars of the raw
bfloat16 model, but uses less memory and inferences around 12% faster.

```bash
python -m olmocr.train.compress_checkpoint --config olmocr/train/quantization_configs/qwen2_5vl_w8a8_fp8.yaml [destination] [destination-FP8]
```

### GRPO Training

[olmOCR-7B-1025-FP8](https://huggingface.co/allenai/olmOCR-7B-1025-FP8) adds an additional training step with GRPO RL based training
occuring on a synthetic version of olmOCR-bench.

[olmOCR-synthmix-1025](https://huggingface.co/datasets/allenai/olmOCR-synthmix-1025) was created by having Claude Sonnet take real PDF documents,
then convert them into HTML templates. Those HTML templates were then rendered, and converted into synthetic olmOCR-bench style benchmarks.
We then ran a GPRO based training process with a reward based on the benchmark score on this synthetic benchmark.

```bash
./scripts/train/grpotrainer-beaker-multi-gpu-augusta.sh --num-gpus 8      --model_name s3://ai2-oe-data/jakep/olmocr/qwen2.5-vl-7b-olmocrv4_1epoch_promptv4_mix102
5_more_rotation_filtered-8372 --train_bench_data_folder /data/jakep/grpo_data_mixes/olmocr-synthmix-1025-v2-rotate10p/bench_data --reward_bench 1.0 --reward_front_matter 1.0 --reward_eos 1
.0 --beta 0.01 --name promptv4_mix1025_more_rotation_multigpu_v1_beta_01_lr2e-6_frontmatter1_0_eos_28gen_synthmix-1025_rotate10p_importanceseq_finalrun_filtered_0 --seed 0 --importance_sampling_level sequence --gradient_accumulation_steps 28 --learning_rate 2e-6 --preemptible
```

6 seeds were run, and then merged into a final checkpoint.

### Notes for AI2
If you are a collaborator of AI2, you can use the following scripts to run training and inference

```bash
# Run training using Beaker
scripts/train/newtrainer-beaker.sh --config [config file]

# Prepare checkpoint from an interactive session with WEKA
python -m olmocr.train.prepare_olmocr_checkpoint [source] [destination]

# Compress the prepared model checkpoint to FP8
scripts/train/compress_model.sh <recipe_path> <input_model_path> <output_model_path>[--calibration-pdfs PATTERN]

# Run olmOCR bench
scripts/run_benchmark.sh --model [destination]
```
