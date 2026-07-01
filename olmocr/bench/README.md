# olmOCR-Bench

Dataset Link: https://huggingface.co/datasets/allenai/olmOCR-bench

We develop olmOCR-Bench in order to automatically and effectively evaluate document-level OCR of various tools.

olmOCR-Bench works by testing various "facts" about document pages at the PDF-level.
Our intention is that each "fact" is very simple, unambiguous, and machine-checkable, similar to a unit test. For example, once your document has been OCRed, we may check that a particular sentence appears exactly somewhere on the page.

We stay away from soft metrics like edit distance comparisons, because they may assign lower scores for parses of the document that differ from the reference, but may in fact still be correct. For example, on a document containing multiple distinct articles: you want the text of each article to be grouped together, but the relative order of the two articles may not be critical. Also, some documents may have critical details, like switching x and y in an equation that can make all the difference in understanding, but would appear as just a single character edit in an edit-distance metric.

olmOCR-bench operates on single page PDFs directly. We make this choice because PDFs do preserve some digital metadata and information which may be helpful to some OCR systems. Almost any other format can be converted to a PDF, but not the reverse, so we try to preserve these original documents where possible.

We have run the benchmark against some contemporary OCR pipelines, but it is really easy 
to run it against your own OCR tools. Your tool just needs to support Markdown or plain text output.

<div align="center">
  <img src="https://github.com/allenai/olmocr/blob/main/scripts/plots/ocr_pareto.png?raw=true" width=800/>
</div>

## Results

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
            <td>olmOCR (first release)</td>
            <td>63.3</td>
            <td>67.5</td>
            <td>62.3</td>
            <td>38.6</td>
            <td>93.4</td>
            <td>67.6</td>
            <td>54.8</td>
            <td>97.9</td>
            <td>68.2±1.1</td>
        </tr>
        <tr>
            <td>v0.1.60 + Dynamic temp scaling</td>
            <td>71.4</td>
            <td>73.1</td>
            <td>65.6</td>
            <td>40.5</td>
            <td>93.2</td>
            <td>76.6</td>
            <td>64.9</td>
            <td>96.7</td>
            <td>72.8±1.2</td>
        </tr>
        <tr>
            <td>v0.1.68 + Better prompting</td>
            <td>76.3</td>
            <td>76.0</td>
            <td>70.2</td>
            <td>43.2</td>
            <td>94.1</td>
            <td>77.5</td>
            <td>71.9</td>
            <td>96.8</td>
            <td>75.8±1.0</td>
        </tr>
        <tr>
            <td>v0.2.0 + New trainer, YAML, img resize, Qwen 2.5 VL</td>
            <td>78.8</td>
            <td>77.5</td>
            <td>71.9</td>
            <td>45.4</td>
            <td>94.2</td>
            <td>78.6</td>
            <td>81.4</td>
            <td>99.8</td>
            <td>78.5±1.1</td>
        </tr>
        <tr>
            <td>v0.3.0 + Handle blank pages</td>
            <td>78.6</td>
            <td>79.9</td>
            <td>72.9</td>
            <td>43.9</td>
            <td>95.1</td>
            <td>77.3</td>
            <td>81.2</td>
            <td>98.9</td>
            <td>78.5±1.1</td>
        </tr>
        <tr>
            <td>v0.4.0 + Synth data, RLVR, souping</td>
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

<sup><sub>Results are reproduced in-house, except those marked with *, which are reported by model authors.
</sub></sup>

## Sourcing Documents and Tests

We define 7 distinct document types that we found olmOCR (or its earlier iterations) often struggled to process and defined custom acquisition strategies for each (described below). We removed documents that both contained PII and were not meant for public dissemination. We also decontaminate against documents that appear in olmOCR-Mix via URL level deduplication. To scale creation of test cases over these documents, we combined manual design and review with prompting GPT-4o.

### Document Types

- **arXiv Math (AR)**: We downloaded a recent set of papers from the math subset of arXiv, selecting manuscripts with a single TeX source file and corresponding rendered PDF. To select a candidate LATEX expression from a page to use in a test, we (1) ran olmOCR to identify candidate pages with TeX, (2) match pages back to original TeX source, and (3) validate matched TeX rendering compatibility with KaTeX. We manually verify the final set of test cases to exclude instances where custom macros produce renderings that deviate from standard LATEX and to split multi-part equations into smaller test cases.

- **Old Scans Math (OSM)**: We crawl old, public domain math textbooks from the Internet Archive, extracting random pages from these documents. We similarly use olmOCR to find candidate pages with formulas, but this time manually annotate each formula on the page to use as test cases.

- **Tables (TA)**: We sampled more documents from the same internal crawled PDF repository used to create olmOCR-Mix and filtered to those which had tables using a simple prompt with Gemini-Flash-2.0. On pages with tables, we prompted Gemini-Flash-2.0 for the relationships between randomly chosen cells. We manually reviewed those tests for accuracy.

- **Old Scans (OS)**: We sampled historical letters and typewritten documents with existing human transcriptions from the Library of Congress digital archives. We then wrote a small script to generate Natural Reading Order cases consisting of sentences that were naturally before or after one another in the original human transcriptions. We manually added test cases to cover some headers/footers which should have been excluded from any OCR version of these documents. All of the test cases then underwent a second pass of human review for accuracy.

- **Headers Footers (HF)**: We sampled documents from the same internally crawled PDF repository as olmOCR-Mix. We used DocLayout-YOLO to identify page regions labeled as headers or footers using the abandon category. To extract the text from these header/footer regions, we visually mask out the rest of the document and prompt Gemini-Flash-2.0 for the content. These extracted snippets are added as test cases that should be absent in linearized output. We manually reviewed to remove mistakenly filtered text and to set conditions such as limiting the search area to the first N or last N characters.

- **Multi Column (MC)**: We visually sample documents from our internal crawled PDF repository to find documents with multi-column layouts and multiple articles on one page. We use Claude-Sonnet-3.7 to render those pages to HTML, and from that HTML, we extract text segments before/after one another. We manually review each entry for accuracy. We purposely select simple text blocks from coherent regions of the document, and avoid including any math formulas, superscripts, or subscripts in these tests.

- **Long Tiny Text (LTT)**: We crawled documents from the Internet Archive containing a large amount of dense, small print on a single page. Such documents include pages from a dictionary or pages of references from academic papers. We then generate test cases using Gemini-Flash-2.0 and verify them manually.

## Benchmark Principles

As we created olmOCR-bench, we also kept a few general rules in mind:

- We expect your OCR system to output a plain-text Unicode document in a reading order that would be considered natural.
- Documents from the benchmark should fit on a standard A4 piece of paper and still be readable to a human.
- Markdown syntax is allowed, but ignored. Ex. if we are looking for the word "enlightenment" to appear on a page, and your system outputs "**\*\*enlightenment\*\***" in Markdown bold, that still counts. 
- olmOCR-bench is not position sensitive, ex. we check that a sentence or math equation appears anywhere on a page. The exception to this is header/footer tests where we want to find simple page numbers appearing in the first or last few characters of a page.
- Tables can be in either Markdown syntax, or as an html `<table>`.
- Math equations must render with [Katex](https://katex.org/) and be delimeted with $, $$, \\(, or \\[. 
- Math equations are not position sensitive either, so if we are checking for 
$ 3x^2 $ to appear on a page, then outputting $ \int_a^b{ 3x ^ 2dx} $ counts.
- We normalize all Unicode to NFC before running the benchmark, so if your OCR model outputs é vs e + ◌́ then either way should not affect your benchmark score.
- We normalize all the different variants of hyphens to the ascii -, all the variants of double quoets to ascii " and all variants of single quotes/apostrophes to ascii '. You should score the same on the benchmark if you output - vs —
- All facts checked about documents are either pass/fail. We want it to be very clear if your OCR system fails a test, and if so, what output would make it pass.


## olmOCR-Bench Test classes

- Text presence
  - This task makes sure that a given small piece of text (ex. 1-3 sentence level) is present within
    a parsed document. Soft/fuzzy matching is allowed, as well as specifying if the text must be in the first N or last N characters of the document. Case sensitive by default.
- Text absense
  - This task makes sure that a given piece of next does NOT appear in the OCR'ed version of a document. We generally want our OCR systems to filter out content like headers/footers/page numbers from documents. The same fuzzy matching as in Text Presence tests is allowed.
- Natural Reading Order
  - This task ensures that blocks of text which are present have a defined order relative to one another. For example,
  on a document that contains multiple news articles on one page, you'd want to see that the first sentence of the 
  first article appears after the heading of that article. But, you may be okay with swapping the order of those 
  two articles.
- Table Accuracy
  - Both Markdown and HTML based tables are supported. These tests check that a cell with a given text exists somewhere in the table, and that its neighbors have certain properties. Ex. A cell exists on this page with text "4.5%" and above that is a cell with the text "2.4%". However, it's important to note that some tests depend on rowspan and colspan information being present in the table, which is only available with HTML based tables. This means that a model outputting only markdown tables cannot achieve a max score on this section.
- Math Formula Accuracy
  - We render a given Latex style equation using Katex in a headless browser. And then see if it exists anywhere in the final OCRed document. Matching is performed on a relative symbol level, ex. in "\f\relax{x} = \int_{-\infty}^\infty
    x^2dx" we check that a ∫ appears to the left of a x, x appears to the left of dx, etc...
  


## Downloading and running the benchmark

Currently the full benchmark data is located here:
https://huggingface.co/datasets/allenai/olmOCR-bench

To run a benchmark, first install the bench requirements
```bash
conda create -n olmocr python=3.11
conda activate olmocr

git clone https://github.com/allenai/olmocr.git
cd olmocr

# Install olmocr and the requirements needed to run the benchmark
pip install -e '.[bench]'

# Configure playwright headless browser to run the math rendering tests
playwright install chromium

# Now clone the benchmark data from hugging face, this includes the PDFs and JSON annotation data
huggingface-cli download --repo-type dataset --resume-download allenai/olmOCR-bench --local-dir ./olmOCR-bench
```

Convert your documents
```bash
# You will need to install the [gpu] subset of olmocr dependencies to run gpu inference
# Then convert using using olmocr.bench.convert, see the olmocr/bench/runners directory for options
pip install 'olmocr[gpu]' --find-links https://flashinfer.ai/whl/cu124/torch2.4/flashinfer/
python -m olmocr.bench.convert olmocr_pipeline --dir ./olmOCR-bench/bench_data

# OR, you can use the pipeline to convert the benchmark PDFs and move them into the final format
python -m olmocr.pipeline ./localworkspace --markdown --pdfs ./olmOCR-bench/bench_data/pdfs/**/*.pdf 
python olmocr/bench/scripts/workspace_to_bench.py localworkspace/ olmOCR-bench/bench_data/olmocr --bench-path ./olmOCR-bench/
```

Now run the benchmark
```bash
python -m olmocr.bench.benchmark --dir ./olmOCR-bench/bench_data
```

## Previewing the benchmark questions

We have an internal data annotation tool that can be used to review the questions in the benchmark, and make edits.

<img width="700" alt="image" src="https://github.com/user-attachments/assets/dd24fd88-a642-4379-b5a1-9911717bf5b1" />


```bash
python -m olmocr.bench.review_app --port 5000 --debug ./olmOCR-bench/bench_data/multi_column.jsonl --force
```
