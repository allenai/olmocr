import argparse
import asyncio
import base64
import glob
import importlib
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from pypdf import PdfReader
from tqdm import tqdm

from olmocr.data.renderpdf import render_pdf_to_base64png
from olmocr.image_utils import convert_image_to_pdf_bytes


def parse_method_arg(method_arg):
    """
    Parse a method configuration string of the form:
       method_name[:key=value[:key2=value2...]]
    Returns:
       (method_name, kwargs_dict, folder_name)
    """
    parts = method_arg.split(":")
    name = parts[0]
    kwargs = {}
    folder_name = name  # Default folder name is the method name

    for extra in parts[1:]:
        if "=" in extra:
            key, value = extra.split("=", 1)
            if key == "name":
                folder_name = value
                continue

            try:
                converted = int(value)
            except ValueError:
                try:
                    converted = float(value)
                except ValueError:
                    converted = value
            kwargs[key] = converted
        else:
            raise ValueError(f"Extra argument '{extra}' is not in key=value format")

    return name, kwargs, folder_name


# Wrapper to run synchronous functions in the event loop
async def run_sync_in_executor(func, executor, *args, **kwargs):
    """Run a synchronous function in the provided executor"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(func, *args, **kwargs))


async def process_pdf(pdf_path, page_num, method, kwargs, output_path, is_async, executor=None, use_executor=True):
    """Process a single PDF and save the result to output_path"""
    try:
        if is_async:
            # Run async function directly
            markdown = await method(pdf_path, page_num=page_num, **kwargs)
        elif use_executor:
            # Run synchronous function in the executor
            markdown = await run_sync_in_executor(method, executor, pdf_path, page_num=page_num, **kwargs)
        else:
            # Run synchronous function directly without executor (when parallel=0)
            markdown = method(pdf_path, page_num=page_num, **kwargs)

        if markdown is None:
            print(f"Warning, did not get output for {os.path.basename(output_path)}")
            # Write blank to this file, so that it's marked as an error and not just skipped in evals
            with open(output_path, "w") as out_f:
                out_f.write("")
            return False

        # Write the markdown to the output file
        with open(output_path, "w") as out_f:
            out_f.write(markdown)

        return True
    except Exception as ex:
        print(f"Exception {str(ex)} occurred while processing {os.path.basename(output_path)}")
        # Write blank to this file, so that it's marked as an error and not just skipped in evals
        with open(output_path, "w") as out_f:
            out_f.write("")
        return False


async def process_pdfs(config, pdf_directory, data_directory, repeats, remove_text, force, max_parallel=None):
    """
    Process PDFs using asyncio for both sync and async methods,
    limiting the number of concurrent tasks to max_parallel.
    """
    # When max_parallel is 0, run synchronously without any executor
    # When max_parallel is > 0, create a thread pool executor
    use_executor = max_parallel != 0
    executor = ThreadPoolExecutor(max_workers=max_parallel) if use_executor else None

    try:
        for candidate in config.keys():
            print(f"Starting conversion using {candidate} with kwargs: {config[candidate]['kwargs']}")
            folder_name = config[candidate]["folder_name"]
            candidate_output_dir = os.path.join(data_directory, folder_name)
            os.makedirs(candidate_output_dir, exist_ok=True)

            method = config[candidate]["method"]
            kwargs = config[candidate]["kwargs"]
            is_async = asyncio.iscoroutinefunction(method)

            # Use recursive glob to support nested PDFs
            all_pdfs = glob.glob(os.path.join(pdf_directory, "**/*.pdf"), recursive=True)
            all_pdfs.sort()

            # Prepare all tasks
            tasks = []
            task_descriptions = {}

            for pdf_path in all_pdfs:
                pdf = PdfReader(pdf_path)
                num_pages = len(pdf.pages)
                base_name = os.path.basename(pdf_path).replace(".pdf", "")
                # Determine the PDF's relative folder path (e.g. "arxiv_data") relative to pdf_directory
                relative_pdf_path = os.path.relpath(pdf_path, pdf_directory)
                pdf_relative_dir = os.path.dirname(relative_pdf_path)

                if remove_text:
                    print(f"Converting {pdf_path} into images to remove text-content...")

                    # Generate image files from each page
                    temp_image_files = []
                    try:
                        for page_num in range(1, num_pages + 1):
                            # Get base64 PNG data for the current page
                            base64_png = render_pdf_to_base64png(pdf_path, page_num, target_longest_image_dim=2048)

                            # Decode base64 and save to temporary file
                            temp_img = tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False)
                            temp_img.write(base64.b64decode(base64_png))
                            temp_img.close()
                            temp_image_files.append(temp_img.name)

                        # Convert all images to a single PDF using our enhanced function
                        pdf_bytes = convert_image_to_pdf_bytes(temp_image_files)

                        # Write the PDF bytes to a temporary file
                        temp_pdf = tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False)
                        temp_pdf.write(pdf_bytes)
                        temp_pdf.close()

                        # Update pdf_path to the new file
                        pdf_path = temp_pdf.name

                    finally:
                        # Clean up temporary image files
                        for temp_file in temp_image_files:
                            try:
                                os.remove(temp_file)
                            except Exception as e:
                                print(f"Warning: Failed to remove temporary file {temp_file}: {e}")

                for repeat in range(1, repeats + 1):
                    for page_num in range(1, num_pages + 1):
                        output_filename = f"{base_name}_pg{page_num}_repeat{repeat}.md"
                        # Preserve the relative folder structure in the output directory
                        candidate_pdf_dir = os.path.join(candidate_output_dir, pdf_relative_dir)
                        os.makedirs(candidate_pdf_dir, exist_ok=True)
                        output_path = os.path.join(candidate_pdf_dir, output_filename)

                        if os.path.exists(output_path) and not force:
                            print(f"Skipping {base_name}_pg{page_num}_repeat{repeat} for {candidate}, file already exists")
                            print("Rerun with --force flag to force regeneration")
                            continue

                        task = process_pdf(pdf_path, page_num, method, kwargs, output_path, is_async, executor, use_executor)
                        tasks.append(task)
                        task_descriptions[id(task)] = f"{base_name}_pg{page_num}_repeat{repeat} ({candidate})"

            # Process tasks with semaphore to limit concurrency
            # When max_parallel is 0, set semaphore to 1 to run sequentially
            semaphore = asyncio.Semaphore(max_parallel if max_parallel else 1)

            async def process_with_semaphore(task):
                async with semaphore:
                    return await task

            # Wrap each task with the semaphore
            limited_tasks = [process_with_semaphore(task) for task in tasks]

            # Process tasks with progress bar
            if limited_tasks:
                completed = 0
                with tqdm(total=len(limited_tasks), desc=f"Processing {candidate}") as pbar:
                    # When parallel=0, tasks complete synchronously and we need to handle them differently
                    if max_parallel == 0:
                        # Process tasks sequentially with immediate progress updates
                        for task in limited_tasks:
                            try:
                                result = await task
                                if result:
                                    completed += 1
                            except Exception as e:
                                print(f"Task failed: {e}")
                            finally:
                                pbar.update(1)
                    else:
                        # Use as_completed for parallel processing
                        for task in asyncio.as_completed(limited_tasks):
                            try:
                                result = await task
                                if result:
                                    completed += 1
                            except Exception as e:
                                print(f"Task failed: {e}")
                            finally:
                                pbar.update(1)

                print(f"Completed {completed} out of {len(limited_tasks)} tasks for {candidate}")
    finally:
        # Clean up the executor
        if executor:
            executor.shutdown(wait=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run PDF conversion using specified OCR methods and extra parameters.")
    parser.add_argument(
        "methods",
        nargs="+",
        help="Methods to run in the format method[:key=value ...]. "
        "Example: gotocr mineru:temperature=2 marker:u=3. "
        "Use 'name=folder_name' to specify a custom output folder name.",
    )
    parser.add_argument("--repeats", type=int, default=1, help="Number of times to repeat the conversion for each PDF.")
    parser.add_argument(
        "--dir",
        type=str,
        default=os.path.join(os.path.dirname(__file__), "sample_data"),
        help="Path to the data folder in which to save outputs, pdfs should be in /pdfs folder within it.",
    )
    parser.add_argument("--force", action="store_true", default=False, help="Force regenerating of output files, even if they already exist")
    parser.add_argument("--parallel", type=int, default=1, help="Maximum number of concurrent tasks")
    parser.add_argument(
        "--remove_text",
        action="store_true",
        help="When your PDF gets processed, we will take a screenshot of it first, to erase any text content in it. This would disable document-anchoring for olmocr.",
    )
    args = parser.parse_args()

    # Mapping of method names to a tuple: (module path, function name)
    available_methods = {
        "olmocr_pipeline": ("olmocr.bench.runners.run_olmocr_pipeline", "run_olmocr_pipeline"),
        "gotocr": ("olmocr.bench.runners.run_gotocr", "run_gotocr"),
        "nanonetsocr": ("olmocr.bench.runners.run_nanonetsocr", "run_nanonetsocr"),
        "marker": ("olmocr.bench.runners.run_marker", "run_marker"),
        "mineru": ("olmocr.bench.runners.run_mineru", "run_mineru"),
        "chatgpt": ("olmocr.bench.runners.run_chatgpt", "run_chatgpt"),
        "gemini": ("olmocr.bench.runners.run_gemini", "run_gemini"),
        "mistral": ("olmocr.bench.runners.run_mistral", "run_mistral"),
        "docling": ("olmocr.bench.runners.run_docling", "run_docling"),
        "rolmocr": ("olmocr.bench.runners.run_rolmocr", "run_rolmocr"),
        "paddlepaddle": ("olmocr.bench.runners.run_paddlepaddle", "run_paddlepaddle"),
        "dotsocr": ("olmocr.bench.runners.run_dotsocr", "run_dotsocr"),
        "transformers": ("olmocr.bench.runners.run_transformers", "run_transformers"),
        "server": ("olmocr.bench.runners.run_server", "run_server"),
    }

    # Build config by importing only requested methods.
    config = {}
    for method_arg in args.methods:
        method_name, extra_kwargs, folder_name = parse_method_arg(method_arg)
        if method_name not in available_methods:
            parser.error(f"Unknown method: {method_name}. " f"Available methods: {', '.join(available_methods.keys())}")
        module_path, function_name = available_methods[method_name]
        # Dynamically import the module and get the function.
        module = importlib.import_module(module_path)
        function = getattr(module, function_name)
        config[method_name] = {"method": function, "kwargs": extra_kwargs, "folder_name": folder_name}

    data_directory = args.dir
    pdf_directory = os.path.join(data_directory, "pdfs")

    # Run the async process function with the parallel argument
    asyncio.run(process_pdfs(config, pdf_directory, data_directory, args.repeats, args.remove_text, args.force, args.parallel))
