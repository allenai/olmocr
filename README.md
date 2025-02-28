<div align="center">
  <!-- <img src="https://github.com/allenai/OLMo/assets/8812459/774ac485-a535-4768-8f7c-db7be20f5cc3" width="300"/> -->
<img src="https://github.com/user-attachments/assets/d70c8644-3e64-4230-98c3-c52fddaeccb6" alt="olmOCR Logo" width="300"/>
<br/>
  <br>
  <h1>olmOCR</h1>
</div>
<p align="center">
  <a href="https://github.com/allenai/OLMo/blob/main/LICENSE">
    <img alt="GitHub License" src="https://img.shields.io/github/license/allenai/OLMo">
  </a>
  <a href="https://github.com/allenai/olmocr/releases">
    <img alt="GitHub release" src="https://img.shields.io/github/release/allenai/olmocr.svg">
  </a>
  <a href="https://olmocr.allenai.org/papers/olmocr.pdf">
    <img alt="Tech Report" src="https://img.shields.io/badge/Paper-olmOCR-blue">
  </a>
  <a href="https://olmocr.allenai.org">
    <img alt="Demo" src="https://img.shields.io/badge/Ai2-Demo-F0529C">
  </a>
  <a href="https://discord.gg/sZq3jTNVNG">
    <img alt="Discord" src="https://img.shields.io/badge/Discord%20-%20blue?style=flat&logo=discord&label=Ai2&color=%235B65E9">
  </a>
  <a href="https://replicate.com/lucataco/olmocr-7b">
    <img alt="Replicate" src="https://replicate.com/lucataco/olmocr-7b/badge">
  </a>
</p>

A toolkit for training language models to work with PDF documents in the wild.

Try the online demo: [https://olmocr.allenai.org/](https://olmocr.allenai.org/)

What is included:
 - A prompting strategy to get really good natural text parsing using ChatGPT 4o - [buildsilver.py](https://github.com/allenai/olmocr/blob/main/olmocr/data/buildsilver.py)
 - An side-by-side eval toolkit for comparing different pipeline versions - [runeval.py](https://github.com/allenai/olmocr/blob/main/olmocr/eval/runeval.py)
 - Basic filtering by language and SEO spam removal - [filter.py](https://github.com/allenai/olmocr/blob/main/olmocr/filter/filter.py)
 - Finetuning code for Qwen2-VL and Molmo-O - [train.py](https://github.com/allenai/olmocr/blob/main/olmocr/train/train.py)
 - Processing millions of PDFs through a finetuned model using Sglang - [pipeline.py](https://github.com/allenai/olmocr/blob/main/olmocr/pipeline.py)
 - Viewing [Dolma docs](https://github.com/allenai/dolma) created from PDFs - [dolmaviewer.py](https://github.com/allenai/olmocr/blob/main/olmocr/viewer/dolmaviewer.py)

### Installation

Requirements:
 - Recent NVIDIA GPU (tested on RTX 4090, L40S, A100, H100)
 - 30GB of free disk space
 
You will need to install poppler-utils and additional fonts for rendering PDF images.

Install dependencies (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install poppler-utils ttf-mscorefonts-installer msttcorefonts fonts-crosextra-caladea fonts-crosextra-carlito gsfonts lcdf-typetools
```

Set up a conda environment and install olmocr
```bash
conda create -n olmocr python=3.11
conda activate olmocr

git clone https://github.com/allenai/olmocr.git
cd olmocr
pip install -e .
```

Install sglang with [flashinfer](https://github.com/flashinfer-ai/flashinfer) if you want to run inference on GPU.
```bash
pip install sgl-kernel==0.0.3.post1 --force-reinstall --no-deps
pip install "sglang[all]==0.4.2" --find-links https://flashinfer.ai/whl/cu124/torch2.4/flashinfer/
```

### Local Usage Example

For quick testing, try the [web demo](https://olmocr.allen.ai/). To run locally, a GPU is required, as inference is powered by [sglang](https://github.com/sgl-project/sglang) under the hood.
Convert a Single PDF:
```bash
python -m olmocr.pipeline ./localworkspace --pdfs tests/gnarly_pdfs/horribleocr.pdf
```

Convert Multiple PDFs:
```bash
python -m olmocr.pipeline ./localworkspace --pdfs tests/gnarly_pdfs/*.pdf
```
Results will be stored as JSON in `./localworkspace`.

#### Viewing Results

Extracted text is stored as [Dolma](https://github.com/allenai/dolma)-style JSONL inside of the `./localworkspace/results` directory.

```bash
cat localworkspace/results/output_*.jsonl  
```

View results side-by-side with the original PDFs (uses `dolmaviewer` command):

```bash
python -m olmocr.viewer.dolmaviewer localworkspace/results/output_*.jsonl
```

Now open `./dolma_previews/tests_gnarly_pdfs_horribleocr_pdf.html` in your favorite browser.

![image](https://github.com/user-attachments/assets/128922d1-63e6-4d34-84f2-d7901237da1f)


### Multi-node / Cluster Usage

If you want to convert millions of PDFs, using multiple nodes running in parallel, then olmOCR supports
reading your PDFs from AWS S3, and coordinating work using an AWS S3 output bucket.

For example, you can start this command on your first worker node, and it will set up
a simple work queue in your AWS bucket and start converting PDFs.

```bash
python -m olmocr.pipeline s3://my_s3_bucket/pdfworkspaces/exampleworkspace --pdfs s3://my_s3_bucket/jakep/gnarly_pdfs/*.pdf
```

Now on any subsequent nodes, just run this and they will start grabbing items from the same workspace queue. 
```bash
python -m olmocr.pipeline s3://my_s3_bucket/pdfworkspaces/exampleworkspace
```

If you are at Ai2 and want to linearize millions of PDFs efficiently using [beaker](https://www.beaker.org), just add the `--beaker`
flag. This will prepare the workspace on your local machine, and then launch N GPU workers in the cluster to start
converting PDFs.

For example:
```bash
python -m olmocr.pipeline s3://my_s3_bucket/pdfworkspaces/exampleworkspace --pdfs s3://my_s3_bucket/jakep/gnarly_pdfs/*.pdf --beaker --beaker_gpus 4
```

### Full documentation for the pipeline

```bash
python -m olmocr.pipeline --help
usage: pipeline.py [-h] [--pdfs PDFS] [--workspace_profile WORKSPACE_PROFILE] [--pdf_profile PDF_PROFILE] [--pages_per_group PAGES_PER_GROUP]
                   [--max_page_retries MAX_PAGE_RETRIES] [--max_page_error_rate MAX_PAGE_ERROR_RATE] [--workers WORKERS] [--apply_filter] [--stats] [--model MODEL]
                   [--model_max_context MODEL_MAX_CONTEXT] [--model_chat_template MODEL_CHAT_TEMPLATE] [--target_longest_image_dim TARGET_LONGEST_IMAGE_DIM]
                   [--target_anchor_text_len TARGET_ANCHOR_TEXT_LEN] [--beaker] [--beaker_workspace BEAKER_WORKSPACE] [--beaker_cluster BEAKER_CLUSTER]
                   [--beaker_gpus BEAKER_GPUS] [--beaker_priority BEAKER_PRIORITY]
                   workspace

Manager for running millions of PDFs through a batch inference pipeline

positional arguments:
  workspace             The filesystem path where work will be stored, can be a local folder, or an s3 path if coordinating work with many workers, s3://bucket/prefix/

options:
  -h, --help            show this help message and exit
  --pdfs PDFS           Path to add pdfs stored in s3 to the workspace, can be a glob path s3://bucket/prefix/*.pdf or path to file containing list of pdf paths
  --workspace_profile WORKSPACE_PROFILE
                        S3 configuration profile for accessing the workspace
  --pdf_profile PDF_PROFILE
                        S3 configuration profile for accessing the raw pdf documents
  --pages_per_group PAGES_PER_GROUP
                        Aiming for this many pdf pages per work item group
  --max_page_retries MAX_PAGE_RETRIES
                        Max number of times we will retry rendering a page
  --max_page_error_rate MAX_PAGE_ERROR_RATE
                        Rate of allowable failed pages in a document, 1/250 by default
  --workers WORKERS     Number of workers to run at a time
  --apply_filter        Apply basic filtering to English pdfs which are not forms, and not likely seo spam
  --stats               Instead of running any job, reports some statistics about the current workspace
  --model MODEL         List of paths where you can find the model to convert this pdf. You can specify several different paths here, and the script will try to use the
                        one which is fastest to access
  --model_max_context MODEL_MAX_CONTEXT
                        Maximum context length that the model was fine tuned under
  --model_chat_template MODEL_CHAT_TEMPLATE
                        Chat template to pass to sglang server
  --target_longest_image_dim TARGET_LONGEST_IMAGE_DIM
                        Dimension on longest side to use for rendering the pdf pages
  --target_anchor_text_len TARGET_ANCHOR_TEXT_LEN
                        Maximum amount of anchor text to use (characters)
  --beaker              Submit this job to beaker instead of running locally
  --beaker_workspace BEAKER_WORKSPACE
                        Beaker workspace to submit to
  --beaker_cluster BEAKER_CLUSTER
                        Beaker clusters you want to run on
  --beaker_gpus BEAKER_GPUS
                        Number of gpu replicas to run
  --beaker_priority BEAKER_PRIORITY
                        Beaker priority level for the job
```


## Team

<!-- start team -->

**olmOCR** is developed and maintained by the AllenNLP team, backed by [the Allen Institute for Artificial Intelligence (AI2)](https://allenai.org/).
AI2 is a non-profit institute with the mission to contribute to humanity through high-impact AI research and engineering.
To learn more about who specifically contributed to this codebase, see [our contributors](https://github.com/allenai/olmocr/graphs/contributors) page.

<!-- end team -->

## License

<!-- start license -->

**olmOCR** is licensed under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0).
A full copy of the license can be found [on GitHub](https://github.com/allenai/olmocr/blob/main/LICENSE).

<!-- end license -->
