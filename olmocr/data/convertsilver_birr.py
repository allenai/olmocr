
import os
import re
import sys
import json
import boto3
import logging
import argparse
import tempfile
import smart_open

from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed


# Import Plotly for plotting
import plotly.express as px


from olmocr.prompts import build_finetuning_prompt
from olmocr.prompts.anchor import get_anchor_text
from olmocr.data.renderpdf import render_pdf_to_base64png

def setup_logging():
    """Configure logging for the script."""
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s", handlers=[logging.StreamHandler(sys.stdout)])


def is_s3_path(path):
    """Check if the given path is an S3 path."""
    return str(path).startswith("s3://")


def download_pdf_from_s3(s3_path: str, pdf_profile: str) -> str:
    """
    Downloads a PDF file from S3 to a temporary local file and returns the local file path.

    Args:
        s3_path (str): S3 path in the format s3://bucket/key
        pdf_profile (str): The name of the boto3 profile to use.

    Returns:
        str: Path to the downloaded PDF file in the local filesystem.
    """
    # Parse the bucket and key from the s3_path
    # s3_path format: s3://bucket_name/some/folder/file.pdf
    path_without_scheme = s3_path.split("s3://", 1)[1]
    bucket_name, key    = path_without_scheme.split("/", 1)

    # Create a session with the specified profile or default
    session   = boto3.Session(profile_name=pdf_profile) if pdf_profile else boto3.Session()
    s3_client = session.client("s3")

    # Create a temporary local file
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp_file.close()  # We only want the path and not keep it locked

    local_path = tmp_file.name

    logging.info(f"Downloading PDF from {s3_path} to {local_path} using profile {pdf_profile}")
    s3_client.download_file(bucket_name, key, local_path)

    return local_path


def transform_json_object(obj):
    """
    Transform a single JSON object by extracting and renaming specific fields.

    Args:
        obj (dict): Original JSON object.

    Returns:
        dict or None: Transformed JSON object, or None if there's an error.
    """
    try:
        transformed = {
            "custom_id": obj["custom_id"],
            "chat_messages": obj["body"]["messages"],
            "temperature": obj["body"]["temperature"],
            "max_tokens": obj["body"]["max_tokens"],
        }
        return transformed
    except KeyError as e:
        logging.error(f"Missing key {e} in object: {obj.get('custom_id', 'unknown')}")
        return None


def process_file(input_file: str, output_file: str, rewrite_prompt_str: bool, pdf_profile: str):
    """
    Process a single JSONL file: read, transform, and write to output.

    Args:
        input_file (str): Path or URL to the input JSONL file.
        output_file (str): Path or URL to the output JSONL file.
        rewrite_prompt_str (bool): Flag to rewrite the prompt string.
        pdf_profile (str): Boto3 profile to use when fetching PDFs from S3.
    """
    processed_count = 0
    error_count     = 0
    prompt_lengths  = []

    try:
        with smart_open.open(input_file, "r", encoding="utf-8") as infile, smart_open.open(output_file, "w", encoding="utf-8") as outfile:
            for line_number, line in enumerate(infile, 1):
                line = line.strip()
                if not line:
                    continue  # Skip empty lines
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    logging.error(f"JSON decode error in file {input_file} at line {line_number}: {e}")
                    error_count += 1
                    continue

                transformed = transform_json_object(obj)

                if transformed is not None and rewrite_prompt_str:
                    # We look for RAW_TEXT_START ... RAW_TEXT_END in the existing content
                    pattern = r"RAW_TEXT_START\s*\n(.*?)\nRAW_TEXT_END"
                    match = re.search(pattern, transformed["chat_messages"][0]["content"][0]["text"], re.DOTALL)

                    if match:
                        # We found raw page text, but we'll attempt to regenerate it
                        goldkey = obj["custom_id"]
                        # goldkey might look like: "s3://bucket/path/to/file.pdf-23"
                        # s3_path = everything up to the last dash
                        # page = everything after the dash
                        try:
                            s3_path = goldkey[: goldkey.rindex("-")]
                            page    = int(goldkey[goldkey.rindex("-") + 1 :])
                        except (ValueError, IndexError) as e:
                            logging.error(f"Could not parse the page number from custom_id {goldkey}: {e}")
                            error_count += 1
                            continue

                        # If the path is an S3 path, download to a local temp file; else assume local
                        if is_s3_path(s3_path):
                            local_pdf_path = download_pdf_from_s3(s3_path, pdf_profile)
                        else:
                            local_pdf_path = s3_path

                        # Recalculate the anchor text
                        raw_page_text = get_anchor_text(local_pdf_path, page, pdf_engine="pdfreport", target_length=6000)

                        image_base64 = render_pdf_to_base64png(local_pdf_path, page, 1024)

                        transformed["chat_messages"][0]["content"][0]["text"] = build_finetuning_prompt(raw_page_text)
                        transformed["chat_messages"][0]["content"][1]["image_url"]["url"] = f"data:image/png;base64,{image_base64}"

                        # Clean up the temp PDF file if it was downloaded
                        if is_s3_path(s3_path):
                            try:
                                os.remove(local_pdf_path)
                            except OSError as remove_err:
                                logging.error(f"Failed to remove temporary PDF file {local_pdf_path}: {remove_err}")

                if transformed is not None:
                    prompt_text   = transformed["chat_messages"][0]["content"][0]["text"]
                    prompt_length = len(prompt_text)

                    if prompt_length > 6000:
                        print(transformed["custom_id"], "length ", prompt_length)

                    prompt_lengths.append(prompt_length)

                    outfile.write(json.dumps(transformed) + "\n")
                    processed_count += 1
                else:
                    error_count += 1

        logging.info(f"Processed '{input_file}': {processed_count} records transformed, {error_count} errors.")
        return prompt_lengths
    except Exception as e:
        logging.exception(e)
        logging.error(f"Failed to process file {input_file}: {e}")
        return []


def construct_output_file_path(input_file_path, input_dir, output_dir):
    """
    Given an input file path, input directory, and output directory,
    construct the corresponding output file path.

    Args:
        input_file_path (str): Path to the input file.
        input_dir (str): Path to the input directory.
        output_dir (str): Path to the output directory.

    Returns:
        str: Path to the output file.
    """
    input_file = Path(input_file_path)

    if is_s3_path(input_dir):
        # For S3 paths, manually construct the relative path based on the input S3 path
        input_prefix = input_dir.split("s3://")[1]
        input_prefix = input_prefix.rstrip("*")  # Remove any glob patterns like *.jsonl

        # Remove the 's3://' part from input_file_path and extract the relative part
        input_file_key = input_file_path.split("s3://")[1]
        relative_path  = input_file_key[len(input_prefix) :].lstrip("/")

        # Construct the output S3 path by appending the relative part to the output S3 directory
        output_file_path = output_dir.rstrip("/") + "/" + relative_path

    else:
        # For local paths, use the existing relative path logic
        input_dir_path   = Path(input_dir)
        relative_path    = input_file.relative_to(input_dir_path)
        output_file_path = str(Path(output_dir) / relative_path)

    return output_file_path


def list_input_files(input_dir):
    """
    List all JSONL files in the input directory. If input_dir is an S3 path, handle
    globbing manually by listing objects and filtering based on patterns.

    Args:
        input_dir (str): Path to the input directory or S3 URL.

    Returns:
        list: List of input file paths.
    """
    if is_s3_path(input_dir):
        import fnmatch

        # Parse bucket and prefix
        bucket_name = input_dir.split("s3://")[1].split("/")[0]
        path_and_pattern = "/".join(input_dir.split("s3://")[1].split("/")[1:])

        # Separate the prefix and pattern
        if "/" in path_and_pattern:
            prefix  = path_and_pattern.rsplit("/", 1)[0] + "/"
            pattern = path_and_pattern.rsplit("/", 1)[1]
        else:
            prefix  = ""
            pattern = path_and_pattern

        # Use a Boto3 session (no specific PDF profile needed here if only listing)
        session = boto3.Session()
        s3 = session.resource("s3")
        bucket = s3.Bucket(bucket_name)

        files = []
        for obj in bucket.objects.filter(Prefix=prefix):
            if fnmatch.fnmatch(obj.key, f"{prefix}{pattern}"):
                files.append(f"s3://{bucket_name}/{obj.key}")

        return files
    else:
        input_dir_path = Path(input_dir)
        return [str(p) for p in input_dir_path.glob("*.jsonl")]


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Transform JSONL files by extracting and renaming specific fields.")
    parser.add_argument(
        "--rewrite_finetuning_prompt",
        action="store_true",
        default=True,
        help="Rewrite the input prompt from a standard OPENAI instruction format into a finetuned format.",
    )
    parser.add_argument("input_dir", type=str, help="Path to the input directory containing JSONL files. Can be a local path or S3 URL.")
    parser.add_argument("output_dir", type=str, help="Path to the output directory where transformed JSONL files will be saved. Can be a local path or S3 URL.")
    parser.add_argument("--jobs", "-j", type=int, default=20, help="Number of parallel jobs to run (default: 20).")
    parser.add_argument("--pdf_profile", type=str, default=None, help="Boto3 profile to use for downloading PDFs from S3. Defaults to the default session.")

    args = parser.parse_args()

    input_dir  = args.input_dir.rstrip("/")
    output_dir = args.output_dir.rstrip("/")
    max_jobs   = args.jobs

    # List input files
    input_files = list_input_files(input_dir)

    if not input_files:
        logging.warning(f"No JSONL files found in '{input_dir}'. Exiting.")
        sys.exit(0)

    logging.info(f"Found {len(input_files)} JSONL files to process.")

    # Prepare tasks for parallel processing
    tasks = []
    for input_file in input_files:
        output_file = construct_output_file_path(input_file, input_dir, output_dir)
        tasks.append((input_file, output_file))

    # Process files in parallel
    all_prompt_lengths = []
    with ProcessPoolExecutor(max_workers=max_jobs) as executor:
        future_to_file = {
            executor.submit(process_file, input_file, output_file, args.rewrite_finetuning_prompt, args.pdf_profile): input_file
            for input_file, output_file in tasks
        }

        for future in as_completed(future_to_file):
            input_file = future_to_file[future]
            try:
                prompt_lengths = future.result()
                all_prompt_lengths.extend(prompt_lengths)
            except Exception as exc:
                logging.error(f"File {input_file} generated an exception: {exc}")

    logging.info("All files have been processed.")

    # Plot histogram of prompt lengths
    if all_prompt_lengths:
        fig = px.histogram(all_prompt_lengths, nbins=50, title="Histogram of Prompt Lengths")
        fig.update_xaxes(title="Prompt Length")
        fig.update_yaxes(title="Frequency")
        try:
            fig.write_image("prompt_lengths_histogram.png")
            logging.info("Histogram of prompt lengths has been saved to 'prompt_lengths_histogram.png'.")
        except Exception as e:
            logging.error(f"Failed to save the histogram image: {e}")
            logging.error("Please make sure that the 'kaleido' package is installed (pip install -U kaleido).")
            fig.write_html("prompt_lengths_histogram.html")
            logging.info("Histogram of prompt lengths has been saved to 'prompt_lengths_histogram.html'.")
    else:
        logging.warning("No prompt lengths were collected; histogram will not be generated.")


if __name__ == "__main__":
    main()
