import re
import logging
import subprocess

from typing import List
from pypdf import PdfReader
from collections import Counter
from lingua import Language, LanguageDetectorBuilder


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class PdfFilter:
    def __init__(
        self,
        languages_to_keep=None,
        apply_form_check=True,
        apply_download_spam_check=True,
        download_spam_threshold=0.004,
    ):
        super().__init__()
        self.language_detector = LanguageDetectorBuilder.from_all_languages().with_preloaded_language_models().build()
        self.languages_to_keep = languages_to_keep if languages_to_keep is not None else [Language.ENGLISH]
        self.apply_form_check = apply_form_check
        self.apply_download_spam_check = apply_download_spam_check
        self.download_spam_threshold = download_spam_threshold

    def _is_form(self, pdf_reader) -> bool:
        # Check if the PDF is a form
        if pdf_reader.get_form_text_fields():
            return True
        return False  # Not a form

    def _is_download_spam(self, base_text: str) -> bool:
        seo_words = {
            "download",
            "pdf",
            "epub",
            "mobi",
            "free",
            "ebook",
            "file",
            "save",
            "casino",
            "viagra",
            "cialis",
            "ciprofloxacin",
        }

        base_text   = base_text.strip().lower()
        clean_text  = re.sub(r"\W+", " ", base_text)

        word_counts = Counter(clean_text.split())
        total_words = len(clean_text.split())

        if total_words == 0:
            return False

        seo_score = sum(word_counts[word] for word in seo_words if word in word_counts)

        return (seo_score / total_words) > self.download_spam_threshold

    # Returns True if there is something wrong with this PDF
    def filter_out_pdf(self, local_pdf_path: str) -> bool:
        try:
            # Attempt to read the PDF at the beginning
            pdf_reader = PdfReader(local_pdf_path)

            # Form check
            if self.apply_form_check and self._is_form(pdf_reader):
                logger.info(f"Filtering out {local_pdf_path} because it's a form")
                return True  # Filter out
        except Exception as e:
            logger.warning(f"Error reading PDF {local_pdf_path}: {e}")
            return True  # Filter out the PDF if an exception occurs

        # Read the first five pages of text for language calculation
        pdftotext_result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "5", local_pdf_path, "-"],
            timeout=60,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if pdftotext_result.returncode != 0:
            logger.warning(f"pdftotext returned {pdftotext_result.returncode} on {local_pdf_path}")
            return True  # Filter out

        base_text = pdftotext_result.stdout.decode("utf-8")

        alpha_count = sum(c.isalpha() for c in base_text)

        if len(base_text) < 200:
            logger.info(f"Keeping {local_pdf_path} on the safe side because not enough text exists in it to analyze")
            return False  # keep the pdf

        if alpha_count / len(base_text) < 0.50:
            logger.info(f"Keeping {local_pdf_path} on the safe side because it's text does not contain many letters so it might be OCRed badly")
            return False  # keep the pdf

        # Language check
        language = self.language_detector.detect_language_of(base_text)
        if language not in self.languages_to_keep:
            logger.info(f"Filtering out {local_pdf_path} because language was {language}")
            return True  # Filter out

        # Download spam check
        if self.apply_download_spam_check and self._is_download_spam(base_text):
            logger.info(f"Filtering out {local_pdf_path} because of SEO/download spam")
            return True  # Filter out

        return False  # Keep the PDF


if __name__ == "__main__":
    import tempfile
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

    import boto3
    from tqdm import tqdm

    from olmocr.s3_utils import parse_s3_path

    # Quiet logs from pypdf
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    def process_pdf(s3_path):
        """
        Process a single PDF file to determine if it should be kept or removed.
        """
        s3_bucket, s3_key = parse_s3_path(s3_path)
        pdf_s3 = boto3.client("s3")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp_file:
            pdf_s3.download_fileobj(s3_bucket, s3_key, tmp_file)
            tmp_file.flush()

            # Perform filtering logic
            if filter.filter_out_pdf(tmp_file.name):
                return s3_path, "remove"
            else:
                return s3_path, "keep"

    # Load the list of S3 paths with a progress bar
    with open("/home/ubuntu/s2pdf_paths_1M.txt", "r") as f:
        s3_work_paths: List[str] = list(filter(None, (line.strip() for line in tqdm(f, desc="Loading paths"))))

    # Initialize the PDF filter
    filter = PdfFilter(
        languages_to_keep={Language.ENGLISH, None},  # none means could not detect language, that's okay keep it, might be an OCR
        apply_download_spam_check=True,
        apply_form_check=True,
    )

    # Output files
    keep_path   = "/home/ubuntu/s2pdf_paths_filter_keep.txt"
    remove_path = "/home/ubuntu/s2pdf_paths_filter_remove.txt"

    max_pending = 20  # Limit on the number of concurrent futures
    total_pdfs  = len(s3_work_paths)
    pdf_iter    = iter(s3_work_paths)  # Iterator for PDFs

    # Process the PDFs with limited concurrent futures
    with open(keep_path, "w") as fkeep, open(remove_path, "w") as fremove:
        with ProcessPoolExecutor(max_workers=max_pending) as executor:
            pending_futures = {}

            with tqdm(total=total_pdfs, desc="Processing PDFs") as pbar:
                # Submit initial batch of futures
                for _ in range(min(max_pending, total_pdfs)):
                    s3_path = next(pdf_iter)
                    future  = executor.submit(process_pdf, s3_path)
                    pending_futures[future] = s3_path

                while pending_futures:
                    # Wait for the next future to complete
                    done, _ = wait(  # type: ignore
                        pending_futures.keys(),
                        timeout=0.1,
                        return_when=FIRST_COMPLETED,
                    )

                    for future in done:
                        s3_path = pending_futures.pop(future)
                        try:
                            s3_path, result = future.result()
                            if result == "keep":
                                fkeep.write(s3_path + "\n")
                            elif result == "remove":
                                fremove.write(s3_path + "\n")
                        except Exception as e:
                            print(f"Error processing {s3_path}: {e}")

                        # Update the progress bar
                        pbar.update(1)

                        # Submit a new future if there are more PDFs
                        try:
                            s3_path = next(pdf_iter)
                            future = executor.submit(process_pdf, s3_path)
                            pending_futures[future] = s3_path
                        except StopIteration:
                            pass  # No more PDFs to process
