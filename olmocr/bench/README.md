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
  <img src="https://github.com/allenai/olmocr/blob/main/scripts/pareto/ocr_pareto.png?raw=true" width=800/>
</div>

## Results

<table>
  <thead>
    <tr>
      <th align="left"><strong>Model</strong></th>
      <th align="center">ArXiv</th>
      <th align="center">Old Scans Math</th>
      <th align="center">Tables</th>
      <th align="center">Old Scans</th>
      <th align="center">Headers and Footers</th>
      <th align="center">Multi column</th>
      <th align="center">Long tiny text</th>
      <th align="center">Base</th>
      <th align="center">Overall</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td align="left">GOT OCR</td>
      <td align="center">52.7</td>
      <td align="center">52.0</td>
      <td align="center">0.20</td>
      <td align="center">22.1</td>
      <td align="center">93.6</td>
      <td align="center">42.0</td>
      <td align="center">29.9</td>
      <td align="center">94.0</td>
      <td align="center">48.3 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">Marker v1.7.5 (base, force_ocr)</td>
      <td align="center">76.0</td>
      <td align="center">57.9</td>
      <td align="center">57.6</td>
      <td align="center">27.8</td>
      <td align="center">84.9</td>
      <td align="center">72.9</td>
      <td align="center">84.6</td>
      <td align="center">99.1</td>
      <td align="center">70.1 ± 1.1</td>
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
      <td align="center">77.2</td>
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
      <td align="left">Nanonets OCR</td>
      <td align="center">67.0</td>
      <td align="center">68.6</td>
      <td align="center">77.7</td>
      <td align="center">39.5</td>
      <td align="center">40.7</td>
      <td align="center">69.9</td>
      <td align="center">53.4</td>
      <td align="center">99.3</td>
      <td align="center">64.5 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">GPT-4o (No Anchor)</td>
      <td align="center">51.5</td>
      <td align="center">75.5</td>
      <td align="center">69.1</td>
      <td align="center">40.9</td>
      <td align="center">94.2</td>
      <td align="center">68.9</td>
      <td align="center">54.1</td>
      <td align="center">96.7</td>
      <td align="center">68.9 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">GPT-4o (Anchored)</td>
      <td align="center">53.5</td>
      <td align="center">74.5</td>
      <td align="center">70.0</td>
      <td align="center">40.7</td>
      <td align="center">93.8</td>
      <td align="center">69.3</td>
      <td align="center">60.6</td>
      <td align="center">96.8</td>
      <td align="center">69.9 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">Gemini Flash 2 (No Anchor)</td>
      <td align="center">32.1</td>
      <td align="center">56.3</td>
      <td align="center">61.4</td>
      <td align="center">27.8</td>
      <td align="center">48.0</td>
      <td align="center">58.7</td>
      <td align="center">84.4</td>
      <td align="center">94.0</td>
      <td align="center">57.8 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">Gemini Flash 2 (Anchored)</td>
      <td align="center">54.5</td>
      <td align="center">56.1</td>
      <td align="center">72.1</td>
      <td align="center">34.2</td>
      <td align="center">64.7</td>
      <td align="center">61.5</td>
      <td align="center">71.5</td>
      <td align="center">95.6</td>
      <td align="center">63.8 ± 1.2</td>
    </tr>
    <tr>
      <td align="left">Qwen 2 VL (No Anchor)</td>
      <td align="center">19.7</td>
      <td align="center">31.7</td>
      <td align="center">24.2</td>
      <td align="center">17.1</td>
      <td align="center">88.9</td>
      <td align="center">8.3</td>
      <td align="center">6.8</td>
      <td align="center">55.5</td>
      <td align="center">31.5 ± 0.9</td>
    </tr>
    <tr>
      <td align="left">Qwen 2.5 VL (No Anchor)</td>
      <td align="center">63.1</td>
      <td align="center">65.7</td>
      <td align="center">67.3</td>
      <td align="center">38.6</td>
      <td align="center">73.6</td>
      <td align="center">68.3</td>
      <td align="center">49.1</td>
      <td align="center">98.3</td>
      <td align="center">65.5 ± 1.2</td>
    </tr>
    <tr>
      <td align="left">olmOCR v0.1.75 (No Anchor)</td>
      <td align="center">71.5</td>
      <td align="center">71.4</td>
      <td align="center">71.4</td>
      <td align="center">42.8</td>
      <td align="center">94.1</td>
      <td align="center">77.7</td>
      <td align="center">71.0</td>
      <td align="center">97.8</td>
      <td align="center">74.7 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">olmOCR v0.1.75 (Anchored)</td>
      <td align="center">74.9</td>
      <td align="center">71.2</td>
      <td align="center">71.0</td>
      <td align="center">42.2</td>
      <td align="center">94.5</td>
      <td align="center">78.3</td>
      <td align="center">73.3</td>
      <td align="center">98.3</td>
      <td align="center">75.5 ± 1.0</td>
    </tr>
    <tr>
      <td align="left">olmOCR v0.2.0</td>
      <td align="center">78.8</td>
      <td align="center">77.5</td>
      <td align="center">71.9</td>
      <td align="center">45.4</td>
      <td align="center">94.2</td>
      <td align="center">78.6</td>
      <td align="center">81.4</td>
      <td align="center">99.8</td>
      <td align="center">78.5 ± 1.1</td>
    </tr>
    <tr>
      <td align="left">olmOCR v0.3.0</td>
      <td align="center">78.6</td>
      <td align="center">79.9</td>
      <td align="center">72.9</td>
      <td align="center">43.9</td>
      <td align="center">95.1</td>
      <td align="center">77.3</td>
      <td align="center">81.2</td>
      <td align="center">98.9</td>
      <td align="center">78.5 ± 1.1</td>
    </tr>   
    <tr>
      <td align="left">olmOCR pipeline v0.4.0</td>
      <td align="center">83.0</td>
      <td align="center">82.3</td>
      <td align="center">84.9</td>
      <td align="center">47.7</td>
      <td align="center">96.1</td>
      <td align="center">83.7</td>
      <td align="center">81.9</td>
      <td align="center">99.7</td>
      <td align="center">82.4 ± 1.1</td>
    </tr>  
  </tbody>
</table>

<sup><sub>There was a small drop in scores from olmOCR v0.1.68 (77.4), which is due to two factors. One, is that we have adjusted our benchmark code to not include
any "fallback" mechanism when measuring benchmark scores (though it still exists when you run olmocr.pipeline). Second, there is a small drop in scores as we have updated
from sglang 0.4.2 to vllm 0.9.1. In net, we think the upgrade to vllm is the right choice, given that sglang 0.4.6 had even lower scores by one point, and vllm comes with a 
small performance boost, and great support for quantization.
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
pip install -e .[bench]

# Configure playwright headless browser to run the math rendering tests
playwright install chromium

# Now clone the benchmark data from hugging face, this includes the PDFs and JSON annotation data
huggingface-cli download --repo-type dataset --resume-download allenai/olmOCR-bench --local-dir ./olmOCR-bench
```

Convert your documents
```bash
# You will need to install the [gpu] subset of olmocr dependencies to run gpu inference
pip install olmocr[gpu] --find-links https://flashinfer.ai/whl/cu124/torch2.4/flashinfer/

# convert using the same engine as olmOCR pipeline.py uses, see the olmocr/bench/runners directory for options
python -m olmocr.bench.convert olmocr_pipeline --dir ./olmOCR-bench/bench_data

# or use convert_all.sh to run OCR with many common frameworks all at once, API keys will be required
./olmocr/bench/scripts/convert_all.sh
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
