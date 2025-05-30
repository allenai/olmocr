<div align="center">
  <!-- <img src="https://github.com/allenai/OLMo/assets/8812459/774ac485-a535-4768-8f7c-db7be20f5cc3" width="300"/> -->
<img src="https://github.com/user-attachments/assets/d70c8644-3e64-4230-98c3-c52fddaeccb6" alt="olmOCR Logo" width="300"/>
<hr/>
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
</p>

A toolkit for converting PDFs and other image-based document formats into clean, readable, plain text format.

Try the online demo: [https://olmocr.allenai.org/](https://olmocr.allenai.org/)

Features:
 - Convert PDF, PNG, JPEG, and other image formats into clean Markdown
 - **Enhanced Image Support**: Handles RGBA (transparency), 16-bit, grayscale with alpha, and palette images
 - Support for equations, tables, handwriting, and complex formatting
 - Automatically removes headers and footers
 - Convert into text with a natural reading order, even in the presence of
   figures, multi-column layouts, and insets
 - Efficient, less than $200 USD per million pages converted
 - (Based on a 7B parameter VLM, so it requires a GPU)

### News
 - **NEW** - Enhanced Image Processing - Fixed RGBA, 16-bit, and palette image handling issues. All image formats now supported with automatic preprocessing.
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
      <th align="left"><strong>Model</strong></th>
      <th align="center">AR</th>
      <th align="center">OSM</th>
      <th align="center">TA</th>
      <th align="center">OS</th>
      <th align="center">HF</th>
      <th align="center">MC</th>
      <th align="center">LTT</th>
      <th align="center">Base</th>
      <th align="center">Overall Score</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td align="left">Marker v1.6.2</td>
      <td align="center">24.3</td>
      <td align="center">22.1</td>
      <td align="center">69.8</td>
      <td align="center">24.3</td>
      <td align="center">87.1</td>
      <td align="center">71.0</td>
      <td align="center">76.9</td>
      <td align="center"><strong>99.5</strong></td>
      <td align="center">59.4 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">MinerU v1.3.10</td>
      <td align="center">75.4</td>
      <td align="center">47.4</td>
      <td align="center">60.9</td>
      <td align="center">17.3</td>
      <td align="center"><strong>96.6</strong></td>
      <td align="center">59.0</td>
      <td align="center">39.1</td>
      <td align="center">96.6</td>
      <td align="center">61.5 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">Mistral OCR API</td>
      <td align="center"><strong>77.2</strong></td>
      <td align="center">67.5</td>
      <td align="center">60.6</td>
      <td align="center">29.3</td>
      <td align="center">93.6</td>
      <td align="center">71.3</td>
      <td align="center">77.1</td>
      <td align="center">99.4</td>
      <td align="center">72.0 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">olmOCR v0.1.68 (pipeline.py)</td>
      <td align="center">75.6</td>
      <td align="center">75.1</td>
      <td align="center">70.2</td>
      <td align="center"><strong>44.5</strong></td>
      <td align="center">93.4</td>
      <td align="center"><strong>79.4</strong></td>
      <td align="center">81.7</td>
      <td align="center">99.0</td>
      <td align="center"><strong>77.4 ± 1.0</strong></td>
    </tr>
  </tbody>
</table>

### Installation

Requirements:
 - Recent NVIDIA GPU (tested on RTX 4090, L40S, A100, H100) with at least 20 GB of GPU RAM
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
pip install olmocr[gpu] --find-links https://flashinfer.ai/whl/cu124/torch2.4/flashinfer/
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

### Troubleshooting

#### Image Processing Issues

**Supported Image Formats:**
- ✅ **PDF** - Primary format, fully supported
- ✅ **PNG** - All variants including RGBA (transparency), 16-bit, grayscale with alpha
- ✅ **JPEG** - Standard RGB and grayscale formats
- ✅ **Other formats** - Most PIL-supported formats with automatic preprocessing

**Common Issues and Solutions:**

1. **"Image with transparency and a bit depth of 16" Error**
   - **Fixed!** This error has been resolved with automatic image preprocessing
   - RGBA and 16-bit images are now automatically converted to compatible formats

2. **Palette/Indexed Color Images**
   - **Fixed!** Palette images are automatically converted to RGB format
   - No manual conversion needed

3. **Grayscale with Alpha (LA) Images**
   - **Fixed!** LA images are automatically converted to standard grayscale
   - Transparency information is preserved where possible

4. **Performance with Large Images**
   - Large images are processed efficiently with temporary file cleanup
   - Compatible images (RGB, L) use fast-path processing without conversion

5. **Memory Issues**
   - Image preprocessing uses temporary files that are automatically cleaned up
   - For very large batches, consider processing in smaller groups

**If you encounter image processing issues:**
1. Verify the image can be opened with PIL: `python -c "from PIL import Image; Image.open('your_image.png')"`
2. Check the image mode: `python -c "from PIL import Image; print(Image.open('your_image.png').mode)"`
3. Enable debug logging to see preprocessing details: `export PYTHONPATH=. && python -c "import logging; logging.basicConfig(level=logging.DEBUG)"`

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
  --markdown            Also write natural text to markdown files preserving the folder structure of the input pdfs
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

## Code overview

There are some nice reusable pieces of the code that may be useful for your own projects:
 - A prompting strategy to get really good natural text parsing using ChatGPT 4o - [buildsilver.py](https://github.com/allenai/olmocr/blob/main/olmocr/data/buildsilver.py)
 - An side-by-side eval toolkit for comparing different pipeline versions - [runeval.py](https://github.com/allenai/olmocr/blob/main/olmocr/eval/runeval.py)
 - Basic filtering by language and SEO spam removal - [filter.py](https://github.com/allenai/olmocr/blob/main/olmocr/filter/filter.py)
 - Finetuning code for Qwen2-VL and Molmo-O - [train.py](https://github.com/allenai/olmocr/blob/main/olmocr/train/train.py)
 - Processing millions of PDFs through a finetuned model using Sglang - [pipeline.py](https://github.com/allenai/olmocr/blob/main/olmocr/pipeline.py)
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

```bibtex
@misc{olmocr,
      title={{olmOCR: Unlocking Trillions of Tokens in PDFs with Vision Language Models}},
      author={Jake Poznanski and Jon Borchardt and Jason Dunkelberger and Regan Huff and Daniel Lin and Aman Rangapur and Christopher Wilhelm and Kyle Lo and Luca Soldaini},
      year={2025},
      eprint={2502.18443},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2502.18443},
}
```
