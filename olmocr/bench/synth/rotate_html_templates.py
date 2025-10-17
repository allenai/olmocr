#!/usr/bin/env python3
"""
Rotate HTML templates for data augmentation.

This script takes a synthetic data folder produced by mine_html_templates.py,
copies files to a new location, and applies rotation augmentation to a percentage
of PDFs for unit testing (not training data).

The script:
1. Copies all files from source to destination
2. Rotates a specified percentage of PDFs in bench_data/pdfs (90, 180, or 270 degrees)
3. Updates FrontMatter in corresponding claude_original markdown files
"""

import argparse
import os
import random
import shutil
from typing import List, Optional

import pypdf
from tqdm import tqdm


def copy_directory_structure(src_dir: str, dst_dir: str, exclude_dirs: Optional[List[str]] = None):
    """
    Copy entire directory structure from source to destination.

    Args:
        src_dir: Source directory path
        dst_dir: Destination directory path
        exclude_dirs: List of directory names to exclude from copying
    """
    exclude_dirs = exclude_dirs or []

    for root, dirs, files in os.walk(src_dir):
        # Remove excluded directories from the dirs list to prevent walking into them
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        # Calculate relative path and create corresponding directory in destination
        rel_path = os.path.relpath(root, src_dir)
        dst_root = os.path.join(dst_dir, rel_path)
        os.makedirs(dst_root, exist_ok=True)

        # Copy all files
        for file in files:
            src_file = os.path.join(root, file)
            dst_file = os.path.join(dst_root, file)

            # Check if it's a symlink
            if os.path.islink(src_file):
                # Get the link target
                link_target = os.readlink(src_file)
                # Create the same symlink in destination
                if os.path.exists(dst_file) or os.path.islink(dst_file):
                    os.remove(dst_file)
                os.symlink(link_target, dst_file)
            else:
                # Regular file, copy it
                shutil.copy2(src_file, dst_file)

    print(f"Copied directory structure from {src_dir} to {dst_dir}")


def rotate_pdf(input_path: str, output_path: str, angle: int) -> bool:
    """
    Rotate a PDF by the specified angle (counter-clockwise).

    Args:
        input_path: Path to input PDF
        output_path: Path to save rotated PDF
        angle: Rotation angle in counter-clockwise direction (90, 180, or 270 degrees)

    Returns:
        True if successful, False otherwise
    """
    try:
        reader = pypdf.PdfReader(input_path)
        writer = pypdf.PdfWriter()

        for page in reader.pages:
            # Convert counter-clockwise to clockwise for pypdf (which uses clockwise)
            # Counter-clockwise 90° = Clockwise 270°
            # Counter-clockwise 180° = Clockwise 180°
            # Counter-clockwise 270° = Clockwise 90°
            clockwise_angle = (360 - angle) % 360
            page.rotate(clockwise_angle)
            writer.add_page(page)

        # Write the rotated PDF
        with open(output_path, "wb") as output_file:
            writer.write(output_file)

        return True
    except Exception as e:
        print(f"Error rotating PDF {input_path}: {e}")
        return False


def update_frontmatter_rotation(markdown_path: str, rotation_angle: int) -> bool:
    """
    Update the FrontMatter in a markdown file to reflect rotation.

    Args:
        markdown_path: Path to the markdown file
        rotation_angle: The angle the PDF was rotated (90, 180, or 270)

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(markdown_path, "r") as f:
            content = f.read()

        lines = content.split("\n")

        # Check if file starts with FrontMatter
        if lines[0] != "---":
            print(f"No FrontMatter found in {markdown_path}")
            return False

        # Find the closing --- of FrontMatter
        end_idx = -1
        for i, line in enumerate(lines[1:], 1):
            if line == "---":
                end_idx = i
                break

        if end_idx == -1:
            print(f"Invalid FrontMatter in {markdown_path}")
            return False

        # Calculate the correction angle (inverse rotation)
        correction_angle = (360 - rotation_angle) % 360

        # Update FrontMatter lines
        updated_lines = []
        rotation_valid_updated = False
        rotation_correction_updated = False

        for line in lines[1:end_idx]:
            if line.startswith("is_rotation_valid:"):
                updated_lines.append("is_rotation_valid: false")
                rotation_valid_updated = True
            elif line.startswith("rotation_correction:"):
                updated_lines.append(f"rotation_correction: {correction_angle}")
                rotation_correction_updated = True
            else:
                updated_lines.append(line)

        # Add missing fields if they weren't present
        if not rotation_valid_updated:
            updated_lines.append("is_rotation_valid: false")
        if not rotation_correction_updated:
            updated_lines.append(f"rotation_correction: {correction_angle}")

        # Reconstruct the file content
        new_content = "\n".join(["---"] + updated_lines + ["---"] + lines[end_idx + 1 :])

        # Write back to file
        with open(markdown_path, "w") as f:
            f.write(new_content)

        return True

    except Exception as e:
        print(f"Error updating FrontMatter in {markdown_path}: {e}")
        return False


def find_corresponding_markdown(pdf_filename: str, claude_original_dir: str) -> Optional[str]:
    """
    Find the corresponding markdown file in claude_original directory.

    Args:
        pdf_filename: Name of the PDF file (e.g., "pdf_00001_page1.pdf")
        claude_original_dir: Path to claude_original directory

    Returns:
        Path to the corresponding markdown file, or None if not found
    """
    # Extract the base name without extension
    base_name = os.path.splitext(pdf_filename)[0]

    # Look for markdown files with pattern: base_name_pg1_repeat1.md
    pattern = f"{base_name}_pg1_repeat1.md"

    # Search in subdirectories of claude_original
    for root, dirs, files in os.walk(claude_original_dir):
        if pattern in files:
            return os.path.join(root, pattern)

    # Also try without the _pg1_repeat1 suffix
    pattern2 = f"{base_name}.md"
    for root, dirs, files in os.walk(claude_original_dir):
        if pattern2 in files:
            return os.path.join(root, pattern2)

    return None


def main():
    parser = argparse.ArgumentParser(description="Apply rotation augmentation to synthetic data from mine_html_templates.py")
    parser.add_argument("--input_dir", required=True, help="Input directory containing synthetic data from mine_html_templates.py")
    parser.add_argument("--output_dir", required=True, help="Output directory for augmented data")
    parser.add_argument("--rotation_percentage", type=float, default=5.0, help="Percentage of PDFs to rotate (default: 5%%)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--dry_run", action="store_true", help="Print what would be done without actually doing it")
    args = parser.parse_args()

    # Set random seed
    random.seed(args.seed)

    # Validate input directory
    if not os.path.exists(args.input_dir):
        print(f"Error: Input directory does not exist: {args.input_dir}")
        return 1

    # Check for required subdirectories
    bench_data_dir = os.path.join(args.input_dir, "bench_data")
    if not os.path.exists(bench_data_dir):
        print(f"Error: bench_data directory not found in {args.input_dir}")
        return 1

    pdfs_dir = os.path.join(bench_data_dir, "pdfs")
    claude_original_dir = os.path.join(bench_data_dir, "claude_original")

    if not os.path.exists(pdfs_dir):
        print(f"Warning: pdfs directory not found in {bench_data_dir}")

    if not os.path.exists(claude_original_dir):
        print(f"Warning: claude_original directory not found in {bench_data_dir}")

    # Step 1: Copy entire directory structure
    if not args.dry_run:
        print("Copying directory structure...")
        copy_directory_structure(args.input_dir, args.output_dir)
    else:
        print(f"[DRY RUN] Would copy {args.input_dir} to {args.output_dir}")

    # Step 2: Find all PDFs in the destination bench_data/pdfs directory
    dst_pdfs_dir = os.path.join(args.output_dir, "bench_data", "pdfs")
    dst_claude_dir = os.path.join(args.output_dir, "bench_data", "claude_original")

    if not os.path.exists(dst_pdfs_dir):
        print(f"No PDFs directory found at {dst_pdfs_dir}")
        return 0

    # Collect all PDF files recursively
    pdf_files = []
    for root, dirs, files in os.walk(dst_pdfs_dir):
        for file in files:
            if file.endswith(".pdf"):
                pdf_files.append(os.path.join(root, file))

    if not pdf_files:
        print("No PDF files found to rotate")
        return 0

    print(f"Found {len(pdf_files)} PDF files")

    # Step 3: Select PDFs to rotate based on percentage
    num_to_rotate = int(len(pdf_files) * args.rotation_percentage / 100.0)
    if num_to_rotate == 0 and args.rotation_percentage > 0:
        num_to_rotate = 1  # Rotate at least one if percentage > 0

    pdfs_to_rotate = random.sample(pdf_files, min(num_to_rotate, len(pdf_files)))

    print(f"Selected {len(pdfs_to_rotate)} PDFs to rotate ({args.rotation_percentage}%)")

    # Step 4: Rotate selected PDFs and update corresponding markdown files
    rotation_angles = [90, 180, 270]
    rotated_count = 0
    markdown_updated_count = 0

    for pdf_path in tqdm(pdfs_to_rotate, desc="Rotating PDFs"):
        # Choose random rotation angle
        angle = random.choice(rotation_angles)

        if args.dry_run:
            print(f"[DRY RUN] Would rotate {pdf_path} by {angle} degrees")
        else:
            # Create a temporary file for the rotated PDF
            temp_path = pdf_path + ".rotated"

            # Rotate the PDF
            if rotate_pdf(pdf_path, temp_path, angle):
                # Replace original with rotated version
                shutil.move(temp_path, pdf_path)
                rotated_count += 1

                # Find and update corresponding markdown file
                pdf_filename = os.path.basename(pdf_path)
                markdown_path = find_corresponding_markdown(pdf_filename, dst_claude_dir)

                if markdown_path:
                    if update_frontmatter_rotation(markdown_path, angle):
                        markdown_updated_count += 1
                else:
                    # Extract the subdirectory structure from PDF path
                    rel_pdf_path = os.path.relpath(pdf_path, dst_pdfs_dir)
                    pdf_subdir = os.path.dirname(rel_pdf_path)

                    # Try to find in the same subdirectory structure
                    if pdf_subdir:
                        specific_claude_dir = os.path.join(dst_claude_dir, pdf_subdir)
                        markdown_path = find_corresponding_markdown(pdf_filename, specific_claude_dir)
                        if markdown_path and update_frontmatter_rotation(markdown_path, angle):
                            markdown_updated_count += 1
            else:
                print(f"Failed to rotate {pdf_path}")

    # Print summary
    print(f"\nRotation augmentation complete!")
    print(f"  - Rotated {rotated_count}/{len(pdfs_to_rotate)} PDFs")
    print(f"  - Updated {markdown_updated_count}/{len(pdfs_to_rotate)} markdown files")

    if args.dry_run:
        print("\n[DRY RUN] No actual changes were made")

    return 0


if __name__ == "__main__":
    exit(main())
