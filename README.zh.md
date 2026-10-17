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

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

一款用于将 PDF 及其他基于图像的文档格式转换为干净、易读的纯文本格式的工具包。

在线体验演示：[https://olmocr.allenai.org/](https://olmocr.allenai.org/)

核心特性：
 - 将基于 PDF、PNG 和 JPEG 的文档转换为干净的 Markdown 格式
 - 支持数学公式、表格、手写体以及复杂排版格式
 - 自动移除页眉与页脚
 - 即使文档中包含插图、多栏排版和嵌入式文本框，也能按照自然的阅读顺序将其转换为文本
 - 高效低成本，每转换一百万页文档的成本低于 200 美元
 - （基于 7B 参数量的视觉语言模型 VLM，因此本地运行需要配备 GPU）

### 最新动态
 - 2025 年 10 月 21 日 - v0.4.0 - [发布新模型](https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8)，利用合成数据并引入强化学习（RL）训练，将 olmOCR-bench 基准得分提升了约 4 分。
 - 2025 年 8 月 13 日 - v0.3.0 - [发布新模型](https://huggingface.co/allenai/olmOCR-7B-0825-FP8)，修复了自动旋转检测问题以及在空白文档上的幻觉现象。
 - 2025 年 7 月 24 日 - v0.2.1 - [发布新模型](https://huggingface.co/allenai/olmOCR-7B-0725-FP8)，在 [olmOCR-Bench](https://github.com/allenai/olmocr/tree/main/olmocr/bench) 上得分提升了 3 分，默认采用 FP8 精度因而运行速度显著提升，且单篇文档所需的重试次数大幅减少。
 - 2025 年 7 月 23 日 - v0.2.0 - 全新整理的[训练器代码](https://github.com/allenai/olmocr/tree/main/olmocr/train)，让您能够更轻松地自行训练 olmOCR 模型。
 - 2025 年 6 月 17 日 - v0.1.75 - 推理流水线从基于 sglang 切换至基于 vllm，并将 Docker 镜像升级至 CUDA 12.8。
 - 2025 年 5 月 23 日 - v0.1.70 - 现已提供官方 Docker 支持与镜像！[参见 Docker 使用指南](#使用-docker)
 - 2025 年 5 月 19 日 - v0.1.68 - 正式发布 [olmOCR-Bench](https://github.com/allenai/olmocr/tree/main/olmocr/bench)，得分达 77.4。得益于提示词（Prompt）相关问题的修复，本次发布使 olmOCR 流水线性能提升了 2 分。
 - 2025 年 3 月 17 日 - v0.1.60 - 通过优化采样温度（temperature）选择策略提升了整体性能。
 - 2025 年 2 月 25 日 - v0.1.58 - 首次公开发布并上线在线演示。

### 基准评测（Benchmark）

[**olmOCR-Bench**](https://github.com/allenai/olmocr/tree/main/olmocr/bench)：
我们还随附了一套全面的基准测试套件，涵盖跨越 1,400 篇文档的 7,000 多个测试用例，用于衡量各 OCR 系统的性能表现。

<table>
    <thead>
        <tr>
            <th></th>
            <th>ArXiv</th>
            <th>早期扫描件<br>数学公式</th>
            <th>表格</th>
            <th>早期<br>扫描件</th>
            <th>页眉<br>与<br>页脚</th>
            <th>多栏<br>排版</th>
            <th>长篇<br>微小<br>文本</th>
            <th>基础<br>文档</th>
            <th>总分<br>(Overall)</th>
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


### 安装指南

#### 系统级依赖

您需要安装 `poppler-utils` 以及额外的字体包，用于将 PDF 页面渲染为图像。

安装系统依赖（Ubuntu/Debian）：
```bash
sudo apt-get update
sudo apt-get install poppler-utils ttf-mscorefonts-installer msttcorefonts fonts-crosextra-caladea fonts-crosextra-carlito gsfonts lcdf-typetools
```

#### Python 环境安装

建议创建一个全新的 Conda 环境并安装 `olmocr`。由于运行 olmOCR 所需的依赖项在已有 Python 环境中较难解决冲突，请务必创建一个干净的 Python 环境进行安装。

```bash
conda create -n olmocr python=3.11
conda activate olmocr
```

请根据您的实际使用场景选择对应的安装选项：

**选项 1：远程推理（轻量级安装）**

如果您计划通过 `--server` 参数调用远程 vLLM 服务器，只需安装基础包即可：
```bash
pip install olmocr
```
这样可以避免安装诸如 PyTorch（约 2GB 以上）等庞大的本地 GPU 依赖。

**选项 2：本地 GPU 推理**

硬件要求：
 - 较新的 NVIDIA GPU（已在 RTX 4090、L40S、A100、H100 上完成测试），至少具备 12 GB 显存
 - 30GB 可用磁盘空间

使用本地 GPU 运行推理时：
```bash
pip install olmocr[gpu] --extra-index-url https://download.pytorch.org/whl/cu128

# 推荐：安装 FlashInfer 以加速 GPU 推理
pip install https://download.pytorch.org/whl/cu128/flashinfer/flashinfer_python-0.2.5%2Bcu128torch2.7-cp38-abi3-linux_x86_64.whl
```

**选项 3：Beaker 集群执行**

如需通过 `--beaker` 参数向 Beaker 集群提交作业：
```bash
pip install olmocr[beaker]
```

**选项 4：基准评测套件**

如需运行 olmOCR 基准评测套件：
```bash
pip install olmocr[bench]
```

**组合安装**

您也可以同时组合多个安装选项：
```bash
# GPU + Beaker 支持
pip install olmocr[gpu,beaker] --extra-index-url https://download.pytorch.org/whl/cu128

# GPU + 基准评测（Benchmark）支持
pip install olmocr[gpu,bench] --extra-index-url https://download.pytorch.org/whl/cu128
```

**故障排查（Troubleshooting）**

如果运行过程中遇到 `too many open files`（打开文件数过多）错误，请调高系统的 `ulimit` 限制：
```bash
ulimit -n 65536
```

### 使用示例

如需快速测试，欢迎直接体验[在线网页演示](https://olmocr.allen.ai/)。

**转换单个 PDF（本地 GPU）：**
```bash
# 下载示例 PDF
curl -o olmocr-sample.pdf https://olmocr.allenai.org/papers/olmocr_3pg_sample.pdf

# 将其转换为 Markdown
olmocr ./localworkspace --markdown --pdfs olmocr-sample.pdf
```

**转换图像文件：**
```bash
olmocr ./localworkspace --markdown --pdfs random_page.png
```

**批量转换多个 PDF：**
```bash
olmocr ./localworkspace --markdown --pdfs tests/gnarly_pdfs/*.pdf
```

**使用远程推理服务器：**
```bash
olmocr ./localworkspace --server http://remote-server:8000/v1 --model allenai/olmOCR-2-7B-1025-FP8 --markdown --pdfs *.pdf
```

附加 `--markdown` 参数后，转换结果将以 Markdown 文件的形式保存在 `./localworkspace/markdown/` 目录下。

> **注意：** 如果您习惯模块调用方式，也可以使用 `python -m olmocr.pipeline` 来代替 `olmocr` 命令。

#### 查看转换结果

运行完成后，`./localworkspace/` 工作区文件夹内会同时生成 [Dolma](https://github.com/allenai/dolma) 格式文件以及 Markdown 文件（若启用了 `--markdown`）。


```bash
cat localworkspace/markdown/olmocr-sample.md
```

```
olmOCR: Unlocking Trillions of Tokens in PDFs with Vision Language Models
...
```

### 使用推理服务商或外部服务器

如果您已经在其他机器上运行了 vLLM 服务器（或任何兼容 OpenAI API 的推理平台），可以直接让 olmOCR 指向该服务，而无需在本地启动实例。

**面向远程推理的安装：**
```bash
# 轻量级安装——无需本地 GPU 依赖
pip install olmocr
```

**调用外部服务器：**
```bash
# 使用外部 vLLM 服务器替代本地实例
olmocr ./localworkspace --server http://remote-server:8000/v1 --model allenai/olmOCR-2-7B-1025-FP8 --markdown --pdfs tests/gnarly_pdfs/*.pdf
```

注意：vLLM 中托管的模型名称必须与 `--model` 参数传入的值保持一致。

**vLLM 服务器启动示例：**
```bash
vllm serve allenai/olmOCR-2-7B-1025-FP8 --max-model-len 16384
```

#### 已验证的外部推理服务商

我们已在以下外部模型服务商平台上测试了 `olmOCR-2-7B-1025-FP8`，并确认其可正常工作：

|                                                                             | 每百万输入 Token 价格 | 每百万输出 Token 价格 | 示例命令                                                                                                                                                                |
|-----------------------------------------------------------------------------|-------------------|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [Cirrascale](https://ai2endpoints.cirrascale.ai/models/overview)            | $0.07             | $0.15              | `olmocr ./workspace --server https://ai2endpoints.cirrascale.ai/api --api_key sk-XXXXXXX --workers 1 --max_concurrent_requests 20 --model olmOCR-2-7B-1025 --pdfs tests/gnarly_pdfs/*.pdf`     |
| [DeepInfra](https://deepinfra.com/)                                         | $0.09             | $0.19              | `olmocr ./workspace --server https://api.deepinfra.com/v1/openai --api_key DfXXXXXXX --workers 1 --max_concurrent_requests 20 --model allenai/olmOCR-2-7B-1025 --pdfs tests/gnarly_pdfs/*.pdf` |
| [Parasail](https://www.saas.parasail.io/serverless?name=olmocr-7b-1025-fp8) | $0.10             | $0.20              | `olmocr ./workspace --server https://api.parasail.io/v1 --api_key psk-XXXXX --workers 1 --max_concurrent_requests 20 --model allenai/olmOCR-2-7B-1025 --pdfs tests/gnarly_pdfs/*.pdf`          |


参数说明：
- `--server`：指定兼容 OpenAI 协议的接口地址，例如 `https://api.deepinfra.com/v1/openai`
- `--api_key`：您的 API 密钥，将通过 HTTP 请求头 `Authorization: Bearer` 传递
- `--max_concurrent_requests`：同时向推理服务商发起的最大并发请求数
- `--workers`：同时处理的页面分组（page group）最大工作协程/线程数。建议将其设为 `1`，以便先完成一组任务再继续处理下一组。
- `--pages_per_group`：由于许多外部服务商对并发请求数有限制，您可能需要调小每个分组包含的页面数量
- `--model`：模型标识符，例如 `allenai/olmOCR-2-7B-1025`。不同服务商的命名可能有所差异；若在本地运行，可使用 `olmocr`
- 其余参数的作用与本地推理完全一致


### 多节点 / 集群并行使用

如果您希望利用多台节点并行转换数百万份 PDF 文档，olmOCR 支持直接从 AWS S3 读取 PDF，并通过同一个 AWS S3 输出存储桶（Bucket）协调多节点工作。

**启动第一个工作节点（Worker）：**
```bash
olmocr s3://my_s3_bucket/pdfworkspaces/exampleworkspace --pdfs s3://my_s3_bucket/jakep/gnarly_pdfs/*.pdf
```

该命令会在您的 AWS 存储桶中创建一个简单的工作队列，并开始转换 PDF。

**在后续工作节点上运行：**
```bash
olmocr s3://my_s3_bucket/pdfworkspaces/exampleworkspace
```

后续节点会自动从同一个工作区队列中领取待处理任务并协同执行。

#### 使用 Beaker 进行集群执行

如果您在 Ai2 内部，并希望使用 [Beaker](https://www.beaker.org) 高效地对数百万份 PDF 进行线性化转换，请安装带 Beaker 支持的版本：

```bash
pip install olmocr[gpu,beaker] --extra-index-url https://download.pytorch.org/whl/cu128
```

随后加上 `--beaker` 参数，即可在本地准备好工作区并在集群中启动 N 个 GPU 工作节点：

```bash
olmocr s3://my_s3_bucket/pdfworkspaces/exampleworkspace --pdfs s3://my_s3_bucket/jakep/gnarly_pdfs/*.pdf --beaker --beaker_gpus 4
```


### 使用 Docker

拉取完整版 Docker 镜像（体积较大，内置模型权重，约 30GB）：
```bash
docker pull alleninstituteforai/olmocr:latest-with-model
```

对于希望自行管理模型下载的高级用户，我们也提供了不包含模型权重的基础镜像：
```bash
docker pull alleninstituteforai/olmocr:latest
```

#### 快速上手 - 处理 PDF 文档

处理当前目录下的单个 PDF 文件：
```bash
docker run --gpus all \
  -v $(pwd):/workspace \
  alleninstituteforai/olmocr:latest-with-model \
  -c "olmocr /workspace/output --markdown --pdfs /workspace/sample.pdf"
```

批量处理多个 PDF 文件：
```bash
docker run --gpus all \
  -v /path/to/pdfs:/input \
  -v /path/to/output:/output \
  alleninstituteforai/olmocr:latest-with-model \
  -c "olmocr /output --markdown --pdfs /input/*.pdf"
```

#### 交互式模式

以交互式模式启动容器，便于探索和调试：
```bash
docker run -it --gpus all alleninstituteforai/olmocr:latest-with-model
```

> 更多详情请访问我们在 [Docker Hub](https://hub.docker.com/r/alleninstituteforai/olmocr) 上的镜像仓库。

### 完整命令行文档

查看所有可用命令行选项：
```bash
olmocr --help
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

## 代码结构概览

本仓库中包含许多可复用的模块，可能对您自己的项目同样有帮助：
 - 使用 ChatGPT 4o 获取高质量自然文本解析结果的提示词（Prompting）策略 - [buildsilver.py](https://github.com/allenai/olmocr/blob/main/olmocr/data/buildsilver.py)
 - 按语种进行基础过滤及 SEO 垃圾内容剔除 - [filter.py](https://github.com/allenai/olmocr/blob/main/olmocr/filter/filter.py)
 - 面向 Qwen2.5-VL 的监督微调（SFT）代码 - [train.py](https://github.com/allenai/olmocr/blob/main/olmocr/train/train.py)
 - GRPO 强化学习（RL）训练器 - [grpo_train.py](https://github.com/allenai/olmocr/blob/main/olmocr/train/grpo_train.py)
 - 合成数据生成工具 - [mine_html_templates.py](https://github.com/allenai/olmocr/blob/main/olmocr/synth/mine_html_templates.py)
 - 使用 vLLM 与微调后模型并行处理数百万份 PDF 的流水线 - [pipeline.py](https://github.com/allenai/olmocr/blob/main/olmocr/pipeline.py)
 - 查看由 PDF 生成的 [Dolma 文档](https://github.com/allenai/dolma)的可视化工具 - [dolmaviewer.py](https://github.com/allenai/olmocr/blob/main/olmocr/viewer/dolmaviewer.py)



## 开发团队

<!-- start team -->

**olmOCR** 由 AllenNLP 团队开发并维护，由[艾伦人工智能研究所（Allen Institute for Artificial Intelligence, AI2）](https://allenai.org/)提供支持。
AI2 是一家非营利性研究机构，致力于通过具有深远影响力的 AI 研究与工程创新造福全人类。
如需了解本代码库的具体贡献者名单，请访问[贡献者页面](https://github.com/allenai/olmocr/graphs/contributors)。

<!-- end team -->

## 开源许可证

<!-- start license -->

**olmOCR** 基于 [Apache 2.0 许可证](https://www.apache.org/licenses/LICENSE-2.0)开源。
完整的许可证文本可在 [GitHub](https://github.com/allenai/olmocr/blob/main/LICENSE) 上查阅。

<!-- end license -->

## 引用（Citing）

如果您使用了 olmOCR v1 及 olmOCR-Bench：
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

如果您使用了采用强化学习单元测试奖励的 olmOCR v2：
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

---

> **翻译说明（Translation Disclaimer）**
> 本文档由社区志愿者（[@JasonYeYuhe](https://github.com/JasonYeYuhe)）人工翻译并维护，旨在降低中文开发者的阅读门槛。最后同步日期：2026年10月17日。若译文与英文原版存在任何出入或滞后，请以 [英文原版 (README.md)](README.md) 为准。欢迎通过 PR 协助改进译文！
