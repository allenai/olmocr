<div align="center">
  <img width="350" alt="olmocr-2-full@2x" src="https://github.com/user-attachments/assets/24f1b596-4059-46f1-8130-5d72dcc0b02e" />
<hr/>
</div>
<p align="center">
  <a href="https://github.com/allenai/OLMo/blob/main/LICENSE">
    <img alt="GitHub License" src="https://img.shields.io/github/license/allenai/OLMo">
  </a>
  <a href="https://github.com/allenai/olmocr/releases">
    <img alt="GitHub release" src="https://img.shields.io/github/release/allenai/olmocr.svg">
  </a>
  <a href="https://arxiv.org/abs/2502.18443">
    <img alt="Tech Report v1" src="https://img.shields.io/badge/Paper_v1-olmOCR-blue">
  </a>
  <a href="https://arxiv.org/abs/2510.19817">
    <img alt="Tech Report v2" src="https://img.shields.io/badge/Paper_v2-olmOCR-blue">
  </a>
  <a href="https://olmocr.allenai.org">
    <img alt="Demo" src="https://img.shields.io/badge/Ai2-Demo-F0529C">
  </a>
  <a href="https://discord.gg/sZq3jTNVNG">
    <img alt="Discord" src="https://img.shields.io/badge/Discord%20-%20blue?style=flat&logo=discord&label=Ai2&color=%235B65E9">
  </a>
</p>

A toolkit for converting PDFs and other image-based document formats into clean, readable, plain text format.

Try the online demo: [https://olmocr.allenai.org/](https://olmocr.allenai.org/)

Features:
 - Convert PDF, PNG, and JPEG based documents into clean Markdown
 - Support for equations, tables, handwriting, and complex formatting
 - Automatically removes headers and footers
 - Convert into text with a natural reading order, even in the presence of
   figures, multi-column layouts, and insets
 - Efficient, less than $200 USD per million pages converted
 - (Based on a 7B parameter VLM, so it requires a GPU)

### News
 - October 21, 2025 - v0.4.0 - [New model release](https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8), boosts olmOCR-bench score by ~4 points using synthetic data and introduces RL training.
 - August 13, 2025 - v0.3.0 - [New model release](https://huggingface.co/allenai/olmOCR-7B-0825-FP8), fixes auto-rotation detection, and hallucinations on blank documents.
 - July 24, 2025 - v0.2.1 - [New model release](https://huggingface.co/allenai/olmOCR-7B-0725-FP8), scores 3 points higher on [olmOCR-Bench](https://github.com/allenai/olmocr/tree/main/olmocr/bench), also runs significantly faster because it's default FP8, and needs much fewer retries per document.
 - July 23, 2025 - v0.2.0 - New cleaned up [trainer code](https://github.com/allenai/olmocr/tree/main/olmocr/train), makes it much simpler to train olmOCR models yourself.
 - June 17, 2025 - v0.1.75 - Switch from sglang to vllm based inference pipeline, updated docker image to CUDA 12.8.
 - May 23, 2025 - v0.1.70 - Official docker support and images are now available! [See Docker usage](#using-docker)
 - May 19, 2025 - v0.1.68 - [olmOCR-Bench](https://github.com/allenai/olmocr/tree/main/olmocr/bench) launch, scoring 77.4. Launch includes 2 point performance boost in olmOCR pipeline due to bug fixes with prompts.
 - Mar 17, 2025 - v0.1.60 - Performance improvements due to better temperature selection in sampling.
 - Feb 25, 2025 - v0.1.58 -  Initial public launch and demo.

### Benchmark

[**olmOCR-Bench**](https://github.com/allenai/olmocr/tree/main/olmocr/bench):
We also ship a comprehensive benchmark suite covering over 7,000 test cases across 1,400 documents to help measure performance of OCR systems. 

<table>
    <thead>
        <tr>
            <th></th>
            <th>ArXiv</th>
            <th>Old<br>scans<br>math</th>
            <th>Tables</th>
            <th>Old<br>scans</th>
            <th>Headers<br>&<br>footers</th>
            <th>Multi<br>column</th>
            <th>Long<br>tiny<br>text</th>
            <th>Base</th>
            <th>Overall</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>Mistral OCR API</td>
            <td>77.2</td>
            <td>67.5</td>
            <td>60.6</td>
            <td>29.3</td>
            <td>93.6</td>
            <td>71.3</td>
            <td>77.1</td>
            <td>99.4</td>
            <td>72.0±1.1</td>
        </tr>
        <tr>
            <td>Marker 1.10.1</td>
            <td>83.8</td>
            <td>66.8</td>
            <td>72.9</td>
            <td>33.5</td>
            <td>86.6</td>
            <td>80.0</td>
            <td>85.7</td>
            <td>99.3</td>
            <td>76.1±1.1</td>
        </tr>
        <tr>
            <td>MinerU 2.5.4*</td>
            <td>76.6</td>
            <td>54.6</td>
            <td>84.9</td>
            <td>33.7</td>
            <td>96.6</td>
            <td>78.2</td>
            <td>83.5</td>
            <td>93.7</td>
            <td>75.2±1.1</td>
        </tr>
        <tr>
            <td>DeepSeek-OCR</td>
            <td>77.2</td>
            <td>73.6</td>
            <td>80.2</td>
            <td>33.3</td>
            <td>96.1</td>
            <td>66.4</td>
            <td>79.4</td>
            <td>99.8</td>
            <td>75.7±1.0</td>
        </tr>
        <tr>
            <td>Nanonets-OCR2-3B</td>
            <td>75.4</td>
            <td>46.1</td>
            <td>86.8</td>
            <td>40.9</td>
            <td>32.1</td>
            <td>81.9</td>
            <td>93.0</td>
            <td>99.6</td>
            <td>69.5±1.1</td>
        </tr>
        <tr>
            <td>PaddleOCR-VL*</td>
            <td>85.7</td>
            <td>71.0</td>
            <td>84.1</td>
            <td>37.8</td>
            <td>97.0</td>
            <td>79.9</td>
            <td>85.7</td>
            <td>98.5</td>
            <td>80.0±1.0</td>
        </tr>
        <tr>
            <td>Infinity-Parser 7B*</td>
            <td>84.4</td>
            <td>83.8</td>
            <td>85.0</td>
            <td>47.9</td>
            <td>88.7</td>
            <td>84.2</td>
            <td>86.4</td>
            <td>99.8</td>
            <td>82.5±?</td>
        </tr>
        <tr>
            <td>Chandra OCR 0.1.0*</td>
            <td>82.2</td>
            <td>80.3</td>
            <td>88.0</td>
            <td>50.4</td>
            <td>90.8</td>
            <td>81.2</td>
            <td>92.3</td>
            <td>99.9</td>
            <td>83.1±0.9</td>
        </tr>
        <tr>
            <td colspan="10"><hr></td>
        </tr>
        <tr>
            <td><strong>olmOCR v0.4.0</strong></td>
            <td>83.0</td>
            <td>82.3</td>
            <td>84.9</td>
            <td>47.7</td>
            <td>96.1</td>
            <td>83.7</td>
            <td>81.9</td>
            <td>99.7</td>
            <td>82.4±1.1</td>
        </tr>
    </tbody>
</table>


### Installation

Requirements:
 - Recent NVIDIA GPU (tested on RTX 4090, L40S, A100, H100) with at least 15 GB of GPU RAM
 - 30GB of free disk space

You will need to install poppler-utils and additional fonts for rendering PDF images.

Install dependencies (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install poppler-utils ttf-mscorefonts-installer msttcorefonts fonts-crosextra-caladea fonts-crosextra-carlito gsfonts lcdf-typetools
```

Set up a conda environment and install olmocr. The requirements for running olmOCR
are difficult to install in an existing python environment, so please do make a clean python environment to install into.
```bash
conda create -n olmocr python=3.11
conda activate olmocr

# For CPU-only operations, ex running the benchmark
pip install olmocr[bench]

# For actually converting the files with your own GPU
pip install olmocr[gpu]  --extra-index-url https://download.pytorch.org/whl/cu128

# Recommended: Install flash infer for faster inference on GPU
pip install https://download.pytorch.org/whl/cu128/flashinfer/flashinfer_python-0.2.5%2Bcu128torch2.7-cp38-abi3-linux_x86_64.whl
```

### Local Usage Example

For quick testing, try the [web demo](https://olmocr.allen.ai/). To run locally, a GPU is required, as inference is powered by [sglang](https://github.com/sgl-project/sglang) under the hood.

Convert a Single PDF:
```bash
# Download a sample PDF
curl -o olmocr-sample.pdf https://olmocr.allenai.org/papers/olmocr_3pg_sample.pdf

# Convert it to markdown
python -m olmocr.pipeline ./localworkspace --markdown --pdfs olmocr-sample.pdf
```

Convert an Image file:
```bash
python -m olmocr.pipeline ./localworkspace --markdown --pdfs random_page.png
```

Convert Multiple PDFs:
```bash
python -m olmocr.pipeline ./localworkspace --markdown --pdfs tests/gnarly_pdfs/*.pdf
```

With the addition of the `--markdown` flag, results will be stored as markdown files inside of `./localworkspace/markdown/`. 

#### Viewing Results

The `./localworkspace/` workspace folder will then have both [Dolma](https://github.com/allenai/dolma) and markdown files (if using `--markdown`).


```bash
cat localworkspace/markdown/olmocr-sample.md 
```

```
olmOCR: Unlocking Trillions of Tokens in PDFs with Vision Language Models
...
```

### Using an Inference Provider or External Server

If you have a vLLM server already running elsewhere (or any inference platform implementing the OpenAI API), you can point olmOCR to use it instead of spawning a local instance:

```bash
# Use external vLLM server instead of local one
python -m olmocr.pipeline ./localworkspace --server http://remote-server:8000/v1 --markdown --pdfs tests/gnarly_pdfs/*.pdf
```

The served model name should be `olmocr`. An example vLLM launch command would be:
```bash
vllm serve allenai/olmOCR-2-7B-1025-FP8 --served-model-name olmocr --max-model-len 16384
```

#### Verified External Providers

We have tested `olmOCR-2-7B-1025-FP8` on these external model providers and confirmed that they work

|                                                                             | $/1M Input tokens | $/1M Output tokens | Example Command                                                                                                                                                                |
|-----------------------------------------------------------------------------|-------------------|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [Cirrascale](https://ai2endpoints.cirrascale.ai/models/overview)            | $0.07             | $0.15              | `python -m olmocr.pipeline ./localworkspace1 --server https://ai2endpoints.cirrascale.ai/api --api_key sk-XXXXXXX --model olmOCR-2-7B-1025 --pdfs tests/gnarly_pdfs/*.pdf`     |
| [DeepInfra](https://deepinfra.com/)                                         | $0.09             | $0.19              | `python -m olmocr.pipeline ./localworkspace1 --server https://api.deepinfra.com/v1/openai --api_key DfXXXXXXX --model allenai/olmOCR-2-7B-1025 --pdfs tests/gnarly_pdfs/*.pdf` |
| [Parasail](https://www.saas.parasail.io/serverless?name=olmocr-7b-1025-fp8) | $0.10             | $0.20              | `python -m olmocr.pipeline ./localworkspace1 --server https://api.parasail.io/v1 --api_key psk-XXXXX --model allenai/olmOCR-2-7B-1025 --pdfs tests/gnarly_pdfs/*.pdf`          |


Notes on arguments
- `--server`: Defines the OpenAI-compatible endpoint: ex `https://api.deepinfra.com/v1/openai`
- `--api_key`: Your API key, passed in via Authorization Bearer HTTP header
- `--pages_per_group`: You may want a smaller number of pages per group as many external provides have lower concurrent request limits
- `--model`: The model identifier, ex. `allenai/olmOCR-2-7B-1025`, different providers have different names, and if you run locally, you can use `olmocr`
- Other arguments work the same as with local inference


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


### Using Docker

Pull the Docker image.
```bash
docker pull alleninstituteforai/olmocr:latest
```

To run the container interactively:
```bash
docker run -it --gpus all --name olmocr_container alleninstituteforai/olmocr:latest /bin/bash
```

If you want to access your local files inside the container, use volume mounting:
```bash
docker run -it --gpus all \
  -v /path/to/your/local/files:/local_files \
  --name olmocr_container \
  alleninstituteforai/olmocr:latest /bin/bash
```

All dependencies are already installed. Once you’re inside the container, you can run olmOCR commands. For example:

```bash
curl -o olmocr-sample.pdf https://olmocr.allenai.org/papers/olmocr_3pg_sample.pdf

python -m olmocr.pipeline ./localworkspace --markdown --pdfs olmocr-sample.pdf
```
> You can also visit our Docker repository on [Docker Hub](https://hub.docker.com/r/alleninstituteforai/olmocr).

### Full documentation for the pipeline

```bash
python -m olmocr.pipeline --help
usage: pipeline.py [-h] [--pdfs [PDFS ...]] [--model MODEL] [--workspace_profile WORKSPACE_PROFILE] [--pdf_profile PDF_PROFILE] [--pages_per_group PAGES_PER_GROUP] [--max_page_retries MAX_PAGE_RETRIES] [--max_page_error_rate MAX_PAGE_ERROR_RATE] [--workers WORKERS]
                   [--apply_filter] [--stats] [--markdown] [--target_longest_image_dim TARGET_LONGEST_IMAGE_DIM] [--target_anchor_text_len TARGET_ANCHOR_TEXT_LEN] [--guided_decoding] [--gpu-memory-utilization GPU_MEMORY_UTILIZATION] [--max_model_len MAX_MODEL_LEN]
                   [--tensor-parallel-size TENSOR_PARALLEL_SIZE] [--data-parallel-size DATA_PARALLEL_SIZE] [--port PORT] [--server SERVER] [--beaker] [--beaker_workspace BEAKER_WORKSPACE] [--beaker_cluster BEAKER_CLUSTER] [--beaker_gpus BEAKER_GPUS] [--beaker_priority BEAKER_PRIORITY]
                   workspace

Manager for running millions of PDFs through a batch inference pipeline

positional arguments:
  workspace             The filesystem path where work will be stored, can be a local folder, or an s3 path if coordinating work with many workers, s3://bucket/prefix/

options:
  -h, --help            show this help message and exit
  --pdfs [PDFS ...]     Path to add pdfs stored in s3 to the workspace, can be a glob path s3://bucket/prefix/*.pdf or path to file containing list of pdf paths
  --model MODEL         Path where the model is located, allenai/olmOCR-7B-0725-FP8 is the default, can be local, s3, or hugging face.
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
  --markdown            Also write natural text to markdown files preserving the folder structure of the input pdfs
  --target_longest_image_dim TARGET_LONGEST_IMAGE_DIM
                        Dimension on longest side to use for rendering the pdf pages
  --target_anchor_text_len TARGET_ANCHOR_TEXT_LEN
                        Maximum amount of anchor text to use (characters), not used for new models
  --guided_decoding     Enable guided decoding for model YAML type outputs

VLLM arguments:
  --gpu-memory-utilization GPU_MEMORY_UTILIZATION
                        Fraction of VRAM vLLM may pre-allocate for KV-cache (passed through to vllm serve).
  --max_model_len MAX_MODEL_LEN
                        Upper bound (tokens) vLLM will allocate KV-cache for, lower if VLLM won't start
  --tensor-parallel-size TENSOR_PARALLEL_SIZE, -tp TENSOR_PARALLEL_SIZE
                        Tensor parallel size for vLLM
  --data-parallel-size DATA_PARALLEL_SIZE, -dp DATA_PARALLEL_SIZE
                        Data parallel size for vLLM
  --port PORT           Port to use for the VLLM server
  --server SERVER       URL of external vLLM (or other compatible provider)
                        server (e.g., http://hostname:port). If provided,
                        skips spawning local vLLM instance

beaker/cluster execution:
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

## Code overview

There are some nice reusable pieces of the code that may be useful for your own projects:
 - A prompting strategy to get really good natural text parsing using ChatGPT 4o - [buildsilver.py](https://github.com/allenai/olmocr/blob/main/olmocr/data/buildsilver.py)
 - Basic filtering by language and SEO spam removal - [filter.py](https://github.com/allenai/olmocr/blob/main/olmocr/filter/filter.py)
 - SFT Finetuning code for Qwen2.5-VL - [train.py](https://github.com/allenai/olmocr/blob/main/olmocr/train/train.py)
 - GRPO RL Trainer - [grpo_train.py](https://github.com/allenai/olmocr/blob/main/olmocr/train/grpo_train.py)
 - Synthetic data generation - [mine_html_templates.py](https://github.com/allenai/olmocr/blob/main/olmocr/bench/synth/mine_html_templates.py)
 - Processing millions of PDFs through a finetuned model using VLLM - [pipeline.py](https://github.com/allenai/olmocr/blob/main/olmocr/pipeline.py)
 - Viewing [Dolma docs](https://github.com/allenai/dolma) created from PDFs - [dolmaviewer.py](https://github.com/allenai/olmocr/blob/main/olmocr/viewer/dolmaviewer.py)



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

## Citing

For olmOCR v1 and OlmOCR-bench:
```bibtex
@misc{olmocrbench,
      title={{olmOCR: Unlocking Trillions of Tokens in PDFs with Vision Language Models}},
      author={Jake Poznanski and Jon Borchardt and Jason Dunkelberger and Regan Huff and Daniel Lin and Aman Rangapur and Christopher Wilhelm and Kyle Lo and Luca Soldaini},
      year={2025},
      eprint={2502.18443},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2502.18443},
}
```

For olmOCR v2 Unit Testing Rewards with RL:
```bibtex
@misc{olmocr2,
      title={olmOCR 2: Unit Test Rewards for Document OCR}, 
      author={Jake Poznanski and Luca Soldaini and Kyle Lo},
      year={2025},
      eprint={2510.19817},
      archivePrefix={arXiv},
      primaryClass={cs.CV},
      url={https://arxiv.org/abs/2510.19817}, 
}
```
