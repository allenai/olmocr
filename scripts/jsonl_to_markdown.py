#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


# This is a simple script to convert JSONL files to Markdown format.
# It reads each line of the JSONL file, extracts the 'text' field,
# and saves it as a Markdown file with the line number as the filename.
# The script also handles potential JSON decoding errors and prints relevant messages.
def jsonl_to_markdown(input_file: str, output_dir: str) -> None:
    """
    Reads a JSONL file, extracts the 'text' field from each line, and saves it as a Markdown file.

    Args:
        input_file (str): Path to the input JSONL file.
        output_dir (str): Directory to save the Markdown files.
    """
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file, "r", encoding="utf-8") as file:
        for i, line in enumerate(file, 1):
            try:
                # Parse the JSON line
                data = json.loads(line)
                text_content = data.get("text", "")

                # Convert to Markdown format
                markdown_content = f"# Extracted Content (Line {i})\n\n{text_content}"

                # Save to a Markdown file
                output_file = output_path / f"line_{i}.md"
                with open(output_file, "w", encoding="utf-8") as md_file:
                    md_file.write(markdown_content)

                print(f"Extracted and saved line {i} to {output_file}")
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON on line {i}: {e}")
            except Exception as e:
                print(f"Unexpected error on line {i}: {e}")


# Example usage
# input_jsonl_file = "/path/to/test.jsonl"  # Replace with the actual path to your JSONL file
# output_directory = "/path/to/output_markdown"  # Replace with the desired output directory
# jsonl_to_markdown(input_jsonl_file, output_directory)

# This is the main entrypoint to use the script from the command line.
# It takes two arguments: the input JSONL file and the output directory.
# The script will create the output directory if it does not exist.
if __name__ == "__main__":

    if len(sys.argv) != 3:
        print("Usage: python jsonl_to_markdown.py <input_file> <output_dir>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2]

    jsonl_to_markdown(input_file, output_dir)
