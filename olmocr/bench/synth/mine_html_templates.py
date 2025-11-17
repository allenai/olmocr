import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import subprocess
import uuid
import glob
import base64
import tempfile
import io
from collections import defaultdict
from typing import Dict, List

import pypdf
from anthropic import AsyncAnthropic
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter, SPACES
from PIL import Image
from playwright.async_api import async_playwright
from syntok.segmenter import process
from tqdm import tqdm

from olmocr.bench.tests import TableTest, TestType, parse_html_tables, load_single_test
from olmocr.data.renderpdf import (
    get_png_dimensions_from_base64,
    render_pdf_to_base64png,
)
from olmocr.filter.filter import PdfFilter, Language

from olmocr.bench.synth.figure_bounding_boxes_claude import detect_figures_with_claude

# Global variables for tracking Claude API costs
total_input_tokens = 0
total_output_tokens = 0


# Unicode mappings for superscript characters
SUPERSCRIPT_MAP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "n": "ⁿ", "i": "ⁱ"
}

# Unicode mappings for subscript characters
SUBSCRIPT_MAP = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
    "a": "ₐ", "e": "ₑ", "o": "ₒ", "x": "ₓ", "h": "ₕ",
    "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "p": "ₚ",
    "s": "ₛ", "t": "ₜ"
}

async def call_claude(
    client: AsyncAnthropic,
    *,
    max_retries: int = 10,
    initial_backoff: float = 10,
    **kwargs,
):
    """Call Claude with exponential backoff when the service is overloaded."""
    delay = initial_backoff
    for attempt in range(1, max_retries + 1):
        try:
            return await client.messages.create(**kwargs)
        except Exception as error:
            if not _is_overloaded_error(error) or attempt == max_retries:
                raise

            await asyncio.sleep(delay)
            delay *= 2


async def claude_stream(
    client: AsyncAnthropic,
    *,
    max_retries: int = 10,
    initial_backoff: float = 10,
    **kwargs,
):
    """Call Claude streaming endpoint and return final message with overload retries."""
    delay = initial_backoff
    for attempt in range(1, max_retries + 1):
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for _ in stream:
                    pass
                return await stream.get_final_message()
        except Exception as error:
            if not _is_overloaded_error(error) or attempt == max_retries:
                raise

            await asyncio.sleep(delay)
            delay *= 2


def convert_superscripts_subscripts(element):
    """
    Convert HTML superscript and subscript tags to Unicode equivalents.
    
    This function finds all <sup> and <sub> tags in the given element and
    replaces them with their Unicode character equivalents. Characters not
    in the mapping are left unchanged.
    
    Args:
        element: A BeautifulSoup element to process
        
    Returns:
        The element with sup/sub tags converted to Unicode
    """
    if not element:
        return element
    
    # Process all superscript tags
    for sup in element.find_all("sup"):
        sup_text = sup.get_text()
        unicode_text = "".join(
            SUPERSCRIPT_MAP.get(char, char) for char in sup_text
        )
        sup.replace_with(unicode_text)
    
    # Process all subscript tags
    for sub in element.find_all("sub"):
        sub_text = sub.get_text()
        unicode_text = "".join(
            SUBSCRIPT_MAP.get(char, char) for char in sub_text
        )
        sub.replace_with(unicode_text)
    
    return element


def download_s3_pdf(path, local_path):
    """Download a PDF from S3 or copy from local path."""
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    # Check if it's a local path
    if os.path.exists(path):
        # It's a local file, just copy it
        import shutil
        try:
            shutil.copy2(path, local_path)
            return True
        except Exception as e:
            print(f"Failed to copy local file {path}: {e}")
            return False
    elif path.startswith("s3://"):
        # It's an S3 path, download it
        result = subprocess.run(["aws", "s3", "cp", path, local_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.returncode == 0
    else:
        # Assume it's a relative local path that doesn't exist yet
        print(f"Path not found and doesn't appear to be S3: {path}")
        return False


class PreserveTablesConverter(MarkdownConverter):
    """
    Custom MarkdownConverter that preserves HTML tables unchanged
    """
    def convert_table(self, el, text, parent_tags):
        # Get the outer HTML of the table element
        # BeautifulSoup's prettify or str() should give us the full HTML
        from bs4 import BeautifulSoup
        # Create a temporary soup with just this element to get its HTML
        temp_soup = BeautifulSoup(str(el), 'html.parser')
        return str(temp_soup.table) if temp_soup.table else str(el)


def extract_html_metadata(html_content):
    """Extract metadata from HTML content for FrontMatter."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract language from html tag
    html_tag = soup.find('html')
    language = 'en'  # default
    if html_tag and html_tag.get('lang'):
        language = str(html_tag.get('lang'))
        # Convert pt-BR to pt for now
        if len(language) == 5 and language[2] == "-":
            language = language[:2]
    
    # Calculate content statistics
    body = soup.find('body')
    if not body:
        body = soup
    
    # First, create a version without headers and footers for all calculations
    main_content_soup = BeautifulSoup(str(body), 'html.parser')
    # Remove headers and footers from main content
    for element in main_content_soup.find_all(['header', 'footer']):
        element.decompose()
    
    # Get text content length (excluding tables and images)
    text_soup = BeautifulSoup(str(main_content_soup), 'html.parser')
    # Remove tables
    for element in text_soup.find_all('table'):
        element.decompose()
    # Remove images (div.image)
    for element in text_soup.find_all('div', class_='image'):
        element.decompose()
    text_content = text_soup.get_text().strip()
    text_length = len(text_content)
    
    # Count table content (from main content, excluding headers/footers)
    tables = main_content_soup.find_all('table')
    table_text_length = 0
    for table in tables:
        table_text_length += len(table.get_text().strip())
    
    # Count images (div.image elements) (from main content, excluding headers/footers)
    images = main_content_soup.find_all('div', class_='image')
    # Rough estimate: each image takes up about 500 characters worth of "space"
    image_content_estimate = len(images) * 500
    
    # Calculate total content "length"
    total_content_length = text_length + table_text_length + image_content_estimate
    
    # Determine if mostly tables or images
    is_table = False
    is_diagram = False
    
    if total_content_length > 0:
        table_ratio = table_text_length / total_content_length
        image_ratio = image_content_estimate / total_content_length
        
        is_table = table_ratio > 0.5
        is_diagram = image_ratio > 0.5
    
    return {
        'primary_language': language,
        'is_rotation_valid': True,
        'rotation_correction': 0,
        'is_table': is_table,
        'is_diagram': is_diagram
    }


def html_to_markdown_with_frontmatter(html_content):
    """Convert HTML to markdown with FrontMatter metadata."""
    # Extract metadata
    metadata = extract_html_metadata(html_content)
    
    # Parse HTML and extract only body content for markdown conversion
    soup = BeautifulSoup(html_content, 'html.parser')
    body = soup.find('body')
    
    # If no body tag, use the whole soup as fallback
    if body:
        # Create a new soup with just the body content
        body_soup = BeautifulSoup(str(body), 'html.parser')
    else:
        body_soup = soup
    
    # First, remove all header and footer elements from the body
    for header in body_soup.find_all('header'):
        header.decompose()
    for footer in body_soup.find_all('footer'):
        footer.decompose()
    
    # Also remove divs with page-header or page-footer classes (in case they weren't converted to header/footer tags)
    for div in body_soup.find_all('div', class_='page-header'):
        div.decompose()
    for div in body_soup.find_all('div', class_='page-footer'):
        div.decompose()
    
    # Handle image placeholders - replace div.image with actual img tags for proper markdown conversion
    for img_div in body_soup.find_all('div', class_='image'):
        alt_text = "Image Placeholder" # For now, in the render it's all just a placeholder
        # Create an img tag with placeholder src and appropriate alt text
        img_tag = body_soup.new_tag('img', src='page.png', alt=alt_text)
        img_div.replace_with(img_tag)
    
    # Convert superscripts and subscripts to Unicode before markdown conversion
    convert_superscripts_subscripts(body_soup)
    
    # Get the modified HTML (only body content)
    modified_html = str(body_soup)
    
    # Create custom converter instance
    converter = PreserveTablesConverter(
        heading_style="ATX",  # Use # style headings
        bullets="-",  # Use - for unordered lists
        strip=['a'],  # Remove links but keep text
        newline_style=SPACES,  # Use backslash for line breaks
        code_language="",  # Don't add language to code blocks
        escape_asterisks=False,  # Don't escape asterisks
        escape_underscores=False  # Don't escape underscores
    )
    
    # Convert to markdown
    markdown = converter.convert(modified_html)
    
    # Clean up excessive newlines
    while '\n\n\n' in markdown:
        markdown = markdown.replace('\n\n\n', '\n\n')
    
    # Strip and clean up markdown content
    markdown_content = markdown.strip()
    
    # Remove leading or trailing --- if present
    while markdown_content.startswith('---'):
        markdown_content = markdown_content[3:].strip()
    while markdown_content.endswith('---'):
        markdown_content = markdown_content[:-3].strip()
    
    # Create FrontMatter
    frontmatter = f"""---
primary_language: {metadata['primary_language']}
is_rotation_valid: {metadata['is_rotation_valid']}
rotation_correction: {metadata['rotation_correction']}
is_table: {metadata['is_table']}
is_diagram: {metadata['is_diagram']}
---"""
    
    # Combine FrontMatter with markdown content
    if markdown_content:
        return f"{frontmatter}\n{markdown_content}"
    else:
        return frontmatter


def extract_code_block(initial_response):
    # Use regex to find the last instance of a code block
    # First try to find HTML specific code blocks
    html_blocks = re.findall(r"```html\n(.*?)```", initial_response, re.DOTALL)

    # If HTML blocks found, return the last one
    if html_blocks:
        return html_blocks[-1].strip()

    # Otherwise, try to find any code blocks
    code_blocks = re.findall(r"```\n(.*?)```", initial_response, re.DOTALL)

    # If code blocks found, return the last one
    if code_blocks:
        return code_blocks[-1].strip()

    # If no code blocks found with newlines after backticks, try without newlines
    html_blocks_no_newline = re.findall(r"```html(.*?)```", initial_response, re.DOTALL)
    if html_blocks_no_newline:
        return html_blocks_no_newline[-1].strip()

    code_blocks_no_newline = re.findall(r"```(.*?)```", initial_response, re.DOTALL)
    if code_blocks_no_newline:
        return code_blocks_no_newline[-1].strip()

    # Return empty string if no code blocks found
    return None


def extract_image_region(base64_png, x1, y1, x2, y2):
    """
    Extract a rectangular region from a base64-encoded PNG image and return it as base64.
    
    Args:
        base64_png: Base64-encoded PNG image
        x1, y1: Top-left coordinates of the region
        x2, y2: Bottom-right coordinates of the region
    
    Returns:
        Base64-encoded PNG of the extracted region
    """
    try:
        # Decode the base64 image
        img_data = base64.b64decode(base64_png)
        img = Image.open(io.BytesIO(img_data))
        
        # Ensure coordinates are integers and in the right order
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        
        # Clamp coordinates to image bounds
        img_width, img_height = img.size
        x1 = max(0, min(x1, img_width))
        x2 = max(0, min(x2, img_width))
        y1 = max(0, min(y1, img_height))
        y2 = max(0, min(y2, img_height))
        
        # Crop the image
        cropped = img.crop((x1, y1, x2, y2))
        
        # Save to bytes buffer as PNG
        buffer = io.BytesIO()
        cropped.save(buffer, format='PNG')
        buffer.seek(0)
        
        # Encode to base64
        return base64.b64encode(buffer.read()).decode('utf-8')
    except Exception as e:
        print(f"Error extracting image region: {e}")
        return None


def embed_image_regions_in_html(html_content, base64_png):
    """
    Process HTML to find <div class="image"> tags with bounding box attributes
    and embed the extracted image regions as base64 PNGs.
    
    Args:
        html_content: HTML string with image placeholder divs
        base64_png: Base64-encoded source PNG image
    
    Returns:
        Modified HTML with embedded image regions
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all image divs with bounding box coordinates
        image_divs = soup.find_all('div', class_='image')
        
        for div in image_divs:
            # Get bounding box coordinates
            x1 = div.get('data-x1')
            y1 = div.get('data-y1')
            x2 = div.get('data-x2')
            y2 = div.get('data-y2')
            
            if x1 and y1 and x2 and y2:
                try:
                    # Extract the image region
                    region_base64 = extract_image_region(base64_png, x1, y1, x2, y2)
                    
                    if region_base64:
                        # Create an img tag with the extracted region
                        img_tag = soup.new_tag('img')
                        img_tag['src'] = f'data:image/png;base64,{region_base64}'
                        
                        # Add alt text from data-description if available
                        description = div.get('data-description')
                        if description:
                            img_tag['alt'] = description
                        else:
                            img_tag['alt'] = 'Extracted image'
                        
                        # Set the image to fill the div completely
                        img_tag['style'] = 'width: 100%; height: 100%; object-fit: fill;'
                        
                        # Add the img tag inside the div
                        div.append(img_tag)
                        
                except Exception as e:
                    print(f"Error processing image div: {e}")
                    continue
        
        return str(soup)
    except Exception as e:
        print(f"Error embedding image regions in HTML: {e}")
        return html_content


async def generate_html_from_image(client, image_base64):
    """Call Claude API to generate HTML from an image using a multi-step prompting strategy."""
    global total_input_tokens, total_output_tokens
    png_width, png_height = get_png_dimensions_from_base64(image_base64)

    try:
        # Step 0: Check that the orientation of the original document is right-side-up. If not, we will
        # skip this page, to keep the code simple
        orientation_response = await call_claude(
            client,
            model="claude-sonnet-4-5-20250929",
            max_tokens=1000,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_base64}},
                        {
                            "type": "text",
                            "text": "Please analyze this document image and determine its orientation.\n\n"
                            "Is this document right-side-up (correctly oriented), or is it rotated?\n\n"
                            "Make your decision based on the main document contents that takes up most of the page area.\n\n"
                            "Respond with ONLY one of the following:\n"
                            "- RIGHT_SIDE_UP: The document is correctly oriented and readable\n"
                            "- ROTATED_90: The document is rotated 90 degrees clockwise\n"
                            "- ROTATED_180: The document is upside down (rotated 180 degrees)\n"
                            "- ROTATED_270: The document is rotated 270 degrees clockwise (90 degrees counter-clockwise)\n"
                            "- UNCLEAR: Cannot determine orientation (e.g., blank page, purely graphical content)\n\n"
                            "Important: Only respond with one of these exact terms, nothing else.",
                        },
                    ],
                }
            ],
        )

        # Extract orientation from response
        orientation_text = ""
        for content in orientation_response.content:
            if content.type == "text":
                orientation_text += content.text.strip()

        # Track token usage from orientation check
        if hasattr(orientation_response, "usage"):
            total_input_tokens += orientation_response.usage.input_tokens
            total_output_tokens += orientation_response.usage.output_tokens

        # Check orientation result
        if "RIGHT_SIDE_UP" not in orientation_text:
            print(f"Skipping page due to orientation: {orientation_text}")
            return None

        # Step 1: Initial analysis and column detection
        analysis_response = await call_claude(
            client,
            model="claude-sonnet-4-5-20250929",
            max_tokens=20000,
            temperature=0.1,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_base64}},
                        {
                            "type": "text",
                            "text": "Analyze this document and provide a detailed assessment of its structure. Focus specifically on:\n"
                            "1. How many columns does the document have? Is it single-column, two-column, three-column, or a mixed layout?\n"
                            "2. What are the main sections and content types (headings, paragraphs, lists, tables, images, etc.)?\n"
                            "3. Does it have headers, footers, page numbers, or other special elements?\n"
                            "4. Is there any complex formatting that would be challenging to reproduce in HTML?\n\n"
                            "Please be very precise about the number of columns and how they're arranged.",
                        },
                    ],
                }
            ],
        )

        # Check if response was complete
        if hasattr(analysis_response, "stop_reason") and analysis_response.stop_reason != "end_turn":
            print(f"Warning: Analysis response incomplete (stop_reason: {analysis_response.stop_reason})")
            return None

        analysis_text = ""
        for content in analysis_response.content:
            if content.type == "text":
                analysis_text += content.text

        # Track token usage from first API call
        if hasattr(analysis_response, "usage"):
            total_input_tokens += analysis_response.usage.input_tokens
            total_output_tokens += analysis_response.usage.output_tokens

        # Step 2: Initial HTML generation with detailed layout instructions
        initial_response = await call_claude(
            client,
            model="claude-sonnet-4-5-20250929",
            max_tokens=20000,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_base64}},
                        {
                            "type": "text",
                            "text": "Render this document as clean, semantic HTML. Here's my analysis of the document structure:\n\n"
                            f"{analysis_text}\n\n"
                            "Important requirements:\n"
                            "1. Use appropriate HTML tags for elements like headings, paragraphs, lists, tables, etc.\n"
                            "2. Use the <header> and <footer> tags to represent content at the top/bottom which would not normally be part of the main content, such as page numbers, etc.\n"
                            "3. Use a placeholder <div> tag with class 'image' which will render as a grey box with black outline to make sure images have their original size, shape, and position on the page. Include an alt-text of the original image as a 'data-description' attribute on the tag. Include 'data-x', 'data-y', 'data-width', 'data-height' attributes which specify where the image was found in the original document.\n"
                            "4. Render any math equations and Latex inline using either \\[ \\] or \\( \\) delimeters.\n"
                            "5. CRITICAL: If the document has a multi-column layout, you MUST preserve the exact same number of columns in your HTML. Use CSS flexbox or grid to create the columns.\n"
                            "6. Focus on creating valid, accessible HTML that preserves the appearance and formatting of the original page as closely as possible.\n"
                            f"7. The webpage will be viewed with a fixed viewport size of {png_width} pixels wide by {png_height} pixels tall.\n"
                            "8. For multi-column layouts, use explicit CSS. The most important aspect is preserving the column structure of the original document - this is critical.\n\n"
                            "Enclose your HTML in a ```html code block.",
                        },
                    ],
                }
            ],
        )

        # Check if response was complete
        if hasattr(initial_response, "stop_reason") and initial_response.stop_reason != "end_turn":
            print(f"Warning: Initial HTML response incomplete (stop_reason: {initial_response.stop_reason})")
            return None

        # Extract initial HTML
        initial_html_text = ""
        for content in initial_response.content:
            if content.type == "text":
                initial_html_text += content.text

        # Track token usage from second API call
        if hasattr(initial_response, "usage"):
            total_input_tokens += initial_response.usage.input_tokens
            total_output_tokens += initial_response.usage.output_tokens

        initial_html = extract_code_block(initial_html_text)
        if not initial_html:
            print("Warning: No HTML code block found in initial response")
            return None

        # Step 3: Render the initial HTML to PDF and then back to PNG for comparison
        # Create a temporary PDF file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            tmp_pdf_path = tmp_pdf.name

        try:
            # Render HTML to PDF using existing function
            render_success = await render_pdf_with_playwright(initial_html, tmp_pdf_path, png_width, png_height)

            if not render_success:
                print("Warning: Failed to render initial HTML to PDF for refinement")
                return None

            # Convert PDF back to PNG
            rendered_image_base64 = render_pdf_to_base64png(tmp_pdf_path, 1, max(png_width, png_height))

            if not rendered_image_base64:
                print("Warning: Failed to convert rendered PDF to PNG for refinement")
                return None

            # We are going to add some stuff to the prompt conditioned on if tables need to be corrected or not
            extra_table_fixing_instructions = ""

            # Check the tables, if they are non-rectangular, we can apply one more correction pass on them
            table_data = parse_html_tables(initial_html)

            # if any(not table.is_rectangular for table in table_data):
            #     extra_table_fixing_instructions = (
            #         "Important: I've noticed that in the HTML table code, some of the columns/rows are not aligned right. "
            #         "Please work extra hard to make sure the table columns are correctly lined up as in the original document. "
            #         "You can add HTML comments as you output the table to help keep track of the current row and column if needed.\n"
            #     )

            # Step 4: Refinement - Show both images to Claude and ask for corrections
            refinement_response = await claude_stream(
                client,
                model="claude-sonnet-4-5-20250929",
                max_tokens=40000,
                temperature=1.0,
                thinking={"type": "enabled", "budget_tokens": 12000},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "I'm going to show you two images:\n1. The original document\n2. How the HTML I generated renders\n\nPlease compare them carefully and provide a revised version of the HTML that better matches the original.",
                            },
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_base64}},
                            {"type": "text", "text": "Above is the ORIGINAL document."},
                            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": rendered_image_base64}},
                            {"type": "text", "text": "Above is how my HTML currently renders."},
                            {
                                "type": "text",
                                "text": f"Here is the current HTML code:\n\n```html\n{initial_html}\n```\n\n"
                                "Please analyze the differences between the original document and the rendered version. Focus on:\n"
                                "1. Layout issues - are columns preserved correctly?\n"
                                "2. Positioning - are elements in the right place?\n"
                                "3. Spacing - are margins, padding, and spacing between elements correct?\n"
                                "4. Occlusion - is any important content hidden or overlapping?\n"
                                "5. Text formatting - are fonts, sizes, and styles appropriate?\n"
                                "6. Tables - are the headers on tables are aligned with the correct corresponding columns?\n"
                                f"{extra_table_fixing_instructions}"
                                f"The webpage will be viewed at {png_width}x{png_height} pixels.\n\n"
                                "Provide a REVISED version of the HTML that corrects any issues you identified. "
                                "Make sure all important elements are visible and the layout matches the original as closely as possible.\n"
                                "Output the complete revised HTML in a ```html code block.",
                            },
                        ],
                    }
                ],
            )

            # Check if refinement response was complete
            if hasattr(refinement_response, "stop_reason") and refinement_response.stop_reason != "end_turn":
                print(f"Warning: Refinement response incomplete (stop_reason: {refinement_response.stop_reason})")
                # Return initial HTML as fallback since it was complete
                return initial_html

            # Extract refined HTML
            refined_html_text = ""
            for content in refinement_response.content:
                if content.type == "text":
                    refined_html_text += content.text

            # Track token usage from refinement API call
            if hasattr(refinement_response, "usage"):
                total_input_tokens += refinement_response.usage.input_tokens
                total_output_tokens += refinement_response.usage.output_tokens

            refined_html = extract_code_block(refined_html_text)
            final_html = refined_html if refined_html else initial_html

            # Check the tables, if they are non-rectangular, we can apply one more correction pass on them
            # table_data = parse_html_tables(final_html)

            # if any(not table.is_rectangular for table in table_data):
            #     print("Table not rectangular, aborting")
            #     return None

            # Return refined HTML if available, otherwise return initial HTML
            return final_html

        finally:
            # Clean up temporary PDF file
            if os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)

    except Exception as e:
        print(f"Error calling Claude API: {e}")
        return None

def extract_page_from_pdf(input_path, output_path, page_num):
    """
    Extract a specific page from a PDF and save it as a new PDF.

    Args:
        input_path: Path to the input PDF
        output_path: Path to save the extracted page
        page_num: The page number to extract (1-indexed, converted to 0-indexed for pypdf)

    Returns:
        bool: True if extraction was successful, False otherwise
    """
    try:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Read the input PDF
        reader = pypdf.PdfReader(input_path)

        # Convert to 0-indexed for pypdf
        zero_idx_page = page_num - 1

        # Check if page number is valid
        if zero_idx_page >= len(reader.pages) or zero_idx_page < 0:
            print(f"Page number {page_num} out of range for {input_path} with {len(reader.pages)} pages")
            return False

        # Create a new PDF with just the selected page
        writer = pypdf.PdfWriter()
        writer.add_page(reader.pages[zero_idx_page])

        # Write the output PDF
        with open(output_path, "wb") as output_file:
            writer.write(output_file)

        return True
    except Exception as e:
        print(f"Error extracting page {page_num} from {input_path}: {str(e)}")
        return False


async def render_pdf_with_playwright(html_content, output_pdf_path, png_width, png_height):
    """
    Render HTML content using Playwright and save it as PDF.
    Try different scale factors if needed to ensure the output is exactly one page.

    Args:
        html_content: HTML content to render
        output_pdf_path: Path to save the rendered PDF
        png_width: Width of the viewport
        png_height: Height of the viewport

    Returns:
        bool: True if rendering was successful with exactly one page, False otherwise
    """
    scale_factors = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]  # Try these scale factors in order
    
    # Determine page format based on PNG dimensions
    # Define thresholds with some tolerance (±5%)
    aspect_ratio = png_width / png_height
    
    # Letter Portrait: 8.5" x 11" (aspect ratio ~0.77)
    # Letter Landscape: 11" x 8.5" (aspect ratio ~1.29)
    # A4 Portrait: 210mm x 297mm (aspect ratio ~0.71)
    # A4 Landscape: 297mm x 210mm (aspect ratio ~1.41)
    
    pdf_options = {
        'path': output_pdf_path,
        'print_background': True,
    }
    
    if 0.73 <= aspect_ratio <= 0.81:  # Letter Portrait (8.5/11 = 0.77)
        pdf_options['width'] = '8.5in'
        pdf_options['height'] = '11in'
    elif 1.23 <= aspect_ratio <= 1.35:  # Letter Landscape (11/8.5 = 1.29)
        pdf_options['width'] = '11in'
        pdf_options['height'] = '8.5in'
    elif 0.67 <= aspect_ratio <= 0.73:  # A4 Portrait (210/297 = 0.71)
        pdf_options['width'] = '210mm'
        pdf_options['height'] = '297mm'
    elif 1.36 <= aspect_ratio <= 1.47:  # A4 Landscape (297/210 = 1.41)
        pdf_options['width'] = '297mm'
        pdf_options['height'] = '210mm'
    # else: Other - leave width and height unset

    for scale in scale_factors:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page(viewport={"width": int(png_width * scale), "height": int(png_height * scale)})

                # Set the HTML content
                await page.set_content(html_content)

                # Add in katex and setup auto rendering
                katex_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "katex")
                katex_css_path = os.path.join(katex_dir, "katex.min.css")
                katex_js_path = os.path.join(katex_dir, "katex.min.js")
                katex_autorender_js_path = os.path.join(katex_dir, "auto-render.min.js")

                await page.add_style_tag(path=katex_css_path)
                await page.add_script_tag(path=katex_js_path)
                await page.add_script_tag(path=katex_autorender_js_path)

                # Run the KaTeX auto-renderer immediately rather than waiting for DOMContentLoaded
                await page.evaluate(
                    """
                    renderMathInElement(document.body, {
                        // customised options
                        // • auto-render specific keys, e.g.:
                        delimiters: [
                            {left: '\\\\(', right: '\\\\)', display: false},
                            {left: '\\\\[', right: '\\\\]', display: true}
                        ],
                        // • rendering keys, e.g.:
                        throwOnError: false
                    });
                """
                )

                # Save as PDF with formatting options
                # Add scale to the options
                pdf_options['scale'] = scale
                await page.pdf(**pdf_options)

                await browser.close()

                # Check if the output PDF has exactly one page
                try:
                    reader = pypdf.PdfReader(output_pdf_path)
                    if len(reader.pages) == 1:
                        print(f"Successfully rendered as a single page PDF with scale factor {scale}")
                        return True
                    else:
                        print(f"PDF has {len(reader.pages)} pages with scale factor {scale}, trying a smaller scale...")
                        # Continue to the next scale factor
                except Exception as pdf_check_error:
                    print(f"Error checking PDF page count: {pdf_check_error}")
                    return False

        except Exception as e:
            print(f"Error rendering PDF with Playwright at scale {scale}: {str(e)}")
            # Try the next scale factor

    print("Failed to render PDF as a single page with any scale factor")
    return False


def generate_tests_from_html(html_content: str, pdf_id: str, page_num: int, random_gen: random.Random, verbose_table_testing: bool = False) -> List[Dict]:
    """
    Generate tests from HTML content parsed from the PDF.

    Args:
        html_content: The HTML content of the page
        pdf_id: The unique identifier for the PDF
        page_num: The page number
        verbose_table_testing: Whether to print table test verification details

    Returns:
        A list of test dictionaries that can be saved as JSONL
    """

    # Use the module-level conversion function

    tests = []
    pdf_filename = f"{pdf_id}_page{page_num}.pdf"
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove any divs or spans with class "line-number"
    for element in soup.find_all(["div", "span"], class_="line-number"):
        element.extract()

    # Rewrite any page-header and page-footer divs to be normalized to headers
    # Convert div.page-footer to footer in one line
    for div in soup.find_all("div", class_="page-header"):
        div.name = "header"

    for div in soup.find_all("div", class_="page-footer"):
        div.name = "footer"

    # Remove elements in the body that appear before the header or after the footer
    body = soup.find("body")
    if body:
        header = soup.find("header")
        footer = soup.find("footer")

        if header:
            # Remove elements before the header
            current = body.contents[0]
            while current and current != header:
                next_elem = current.next_sibling
                current.extract()
                current = next_elem

        if footer:
            # Remove elements after the footer
            current = footer.next_sibling
            while current:
                next_elem = current.next_sibling
                current.extract()
                current = next_elem

    # Step 1: Process headers, footers, and page numbers for TextAbsenceTests
    headers = soup.find_all("header")
    footers = soup.find_all("footer")
    page_numbers = soup.find_all("div", class_="page-number")

    # Function to create absence tests from text elements
    def create_absence_tests_from_elements(parent_element, element_type):
        mini_soup = BeautifulSoup(str(parent_element), "html.parser")

        # Convert superscripts and subscripts in the mini soup
        convert_superscripts_subscripts(mini_soup)

        # Remove headers, footers, and tables from the main_soup
        for element in mini_soup.find_all(["h1", "h2"]):
            element.extract()

        # Find all text-containing leaf elements within the parent
        text_elements = []

        # Get all target elements
        target_tags = mini_soup.find_all(["span", "div", "p", "h3", "h4", "h5", "h6"])

        # Filter to only include leaf nodes (elements that don't contain other target elements)
        for tag in target_tags:
            # Check if this element has no children from our target tags
            is_leaf = not tag.find(["span", "div", "p", "h3", "h4", "h5", "h6"])

            if is_leaf:
                text = tag.get_text().strip()
                if text:
                    text_elements.append(text)

        # If no elements found, use the parent's text as a fallback, but only if
        if not text_elements:
            parent_text = mini_soup.get_text().strip()
            if parent_text:
                text_elements.append(parent_text)

        # Create tests for each text element
        for text in text_elements:
            if "\n" in text:
                text = text.split("\n")[0]

            if len(text) > 3 or len([c for c in text if c.isdigit()]):  # Only create tests for meaningful text
                tests.append(
                    {
                        "pdf": pdf_filename,
                        "page": 1,
                        "id": f"{pdf_id}_{element_type}_{uuid.uuid4().hex[:8]}",
                        "type": TestType.ABSENT.value,
                        "text": text,
                        "max_diffs": round(len(text) * 0.05),
                    }
                )

    # Create TextAbsenceTests for headers
    for header in headers:
        create_absence_tests_from_elements(header, "header")

    # Create TextAbsenceTests for footers
    for footer in footers:
        create_absence_tests_from_elements(footer, "footer")

    # Create TextAbsenceTests for page numbers
    for page_number in page_numbers:
        # Convert any superscripts/subscripts in the page number
        page_number_soup = BeautifulSoup(str(page_number), "html.parser")
        convert_superscripts_subscripts(page_number_soup)
        page_number_text = page_number_soup.get_text().strip()

        if page_number_text:
            tests.append(
                {
                    "pdf": pdf_filename,
                    "page": 1,
                    "id": f"{pdf_id}_page_number_{uuid.uuid4().hex[:8]}",
                    "type": TestType.ABSENT.value,
                    "text": page_number_text,
                    "max_diffs": 0,
                }
            )

    # Step 2: Generate tests from tables using parse_html_tables
    # Convert superscripts and subscripts to Unicode equivalents in tables
    table_soup = BeautifulSoup(html_content, "html.parser")

    # Convert superscripts and subscripts in the table HTML
    convert_superscripts_subscripts(table_soup)
    html_content_with_unicode = str(table_soup)

    table_data_list = parse_html_tables(html_content_with_unicode)

    for table_idx, table_data in enumerate(table_data_list):
        # Get the table data as a numpy array
        table_array = table_data.data

        # Skip tables that are too small
        if table_array.shape[0] < 2 or table_array.shape[1] < 2:
            continue

        # Get a limited number of cells to create tests for
        # Select random rows and columns, excluding header rows/columns
        non_header_rows = [i for i in range(table_array.shape[0]) if i not in table_data.header_rows]
        non_header_cols = [j for j in range(table_array.shape[1]) if j not in table_data.header_cols]

        # If we don't have enough non-header cells, use all cells
        if len(non_header_rows) < 2 or len(non_header_cols) < 2:
            cell_positions = [(i, j) for i in range(table_array.shape[0]) for j in range(table_array.shape[1])]
        else:
            cell_positions = [
                (i, j)
                for i in random_gen.sample(non_header_rows, min(3, len(non_header_rows)))
                for j in random_gen.sample(non_header_cols, min(2, len(non_header_cols)))
            ]

        random_gen.shuffle(cell_positions)

        # Create tests for each selected cell
        for row_idx, col_idx in cell_positions:
            cell_text = str(table_array[row_idx, col_idx]).strip()

            # Skip cells with minimal text
            if not cell_text or len(cell_text) < 3:
                continue

            # Create a TableTest with relevant relationships
            test_data = {
                "pdf": pdf_filename,
                "page": 1,
                "id": f"{pdf_id}_table{table_idx}_{uuid.uuid4().hex[:8]}",
                "type": TestType.TABLE.value,
                "cell": cell_text,
                "max_diffs": 0,
            }

            # Check cell up
            if row_idx > 0:
                up_text = str(table_array[row_idx - 1, col_idx]).strip()
                if up_text and "\n" not in up_text:
                    test_data["up"] = up_text

            # Check cell down
            if row_idx < table_array.shape[0] - 1:
                down_text = str(table_array[row_idx + 1, col_idx]).strip()
                if down_text and "\n" not in down_text:
                    test_data["down"] = down_text

            # Check cell left
            if col_idx > 0:
                left_text = str(table_array[row_idx, col_idx - 1]).strip()
                if left_text and "\n" not in left_text:
                    test_data["left"] = left_text

            # Check cell right
            if col_idx < table_array.shape[1] - 1:
                right_text = str(table_array[row_idx, col_idx + 1]).strip()
                if right_text and "\n" not in right_text:
                    test_data["right"] = right_text

            # Check if current cell is a heading cell
            is_header_cell = row_idx in table_data.header_rows or col_idx in table_data.header_cols

            # Check for top heading using header information (skip if current cell is a heading)
            if not is_header_cell and col_idx in table_data.col_headers:
                # Get the headers for this column
                col_headers = table_data.col_headers[col_idx]
                if col_headers:
                    # Use the first header as the top heading
                    _, top_heading = col_headers[0]
                    if top_heading and "\n" not in top_heading:
                        test_data["top_heading"] = top_heading

            # Check for left heading using header information (skip if current cell is a heading)
            if not is_header_cell and row_idx in table_data.row_headers:
                # Get the headers for this row
                row_headers = table_data.row_headers[row_idx]
                if row_headers:
                    # Use the first header as the left heading
                    _, left_heading = row_headers[0]
                    if left_heading and "\n" not in left_heading:
                        test_data["left_heading"] = left_heading

            # Only add the test if we have at least one relation
            if len(test_data) > 6:  # 6 is the number of required fields
                # Verify that the test passes with the current table HTML
                # Create the actual test object
                test_obj = TableTest(
                    pdf=test_data["pdf"],
                    page=test_data["page"],
                    id=test_data["id"],
                    type=test_data["type"],
                    cell=test_data["cell"],
                    max_diffs=test_data["max_diffs"],
                    up=test_data.get("up", ""),
                    down=test_data.get("down", ""),
                    left=test_data.get("left", ""),
                    right=test_data.get("right", ""),
                    top_heading=test_data.get("top_heading", ""),
                    left_heading=test_data.get("left_heading", ""),
                )

                # Extract just the relevant table HTML
                tables = soup.find_all("table")
                if table_idx < len(tables):
                    table_html = str(tables[table_idx])

                    # Run the test against the original HTML
                    passed, explanation = test_obj.run(table_html)
                else:
                    # Shouldn't happen, but handle it gracefully
                    passed = False

                # Only add tests that pass
                if passed:
                    tests.append(test_data)

            if len(tests) > 25:
                break

    # Step 3: Generate TextPresenceTests and OrderingTests from markdown content
    # Convert HTML to markdown to get cleaner text for presence and ordering tests
    markdown_content = html_to_markdown_with_frontmatter(html_content)
    
    # Remove any HTML tables from the markdown content
    # Tables can persist in markdown as raw HTML and we want to exclude them
    markdown_content = re.sub(r'<table[^>]*>.*?</table>', '', markdown_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Extract just the content part (after frontmatter)
    markdown_lines = markdown_content.split('\n')
    content_start_idx = 0
    
    # Skip frontmatter if present
    if markdown_lines[0] == '---':
        for idx, line in enumerate(markdown_lines[1:], 1):
            if line == '---':
                content_start_idx = idx + 1
                break
    
    # Get markdown content without frontmatter
    markdown_text = '\n'.join(markdown_lines[content_start_idx:]).strip()
    
    # Parse sentences from markdown content
    sentences = []
    if markdown_text:
        for paragraph in process(markdown_text):
            for sentence in paragraph:
                # Convert token sequence to string and clean it
                sentence_str = ""
                for token in sentence:
                    sentence_str += token.spacing + token.value

                sentence_str = sentence_str.strip()

                if sentence_str:
                    # Skip HTML content that might still be in markdown
                    if not sentence_str.startswith('<') and not sentence_str.endswith('>'):
                        # Skip image placeholders - match any markdown image syntax ![...](...)
                        if re.search(r'!\[.*?\]\(.*?\)', sentence_str):
                            continue
                        
                        # Remove leading # marks (markdown headers)
                        while sentence_str.startswith('#'):
                            sentence_str = sentence_str[1:]
                        sentence_str = sentence_str.strip()
                        
                        # Remove leading "- " for unordered lists
                        if sentence_str.startswith('- '):
                            sentence_str = sentence_str[2:]
                        
                        sentence_str = sentence_str.strip()
                        
                        if sentence_str:  # Only add if there's still content after cleaning
                            sentences.append(sentence_str)

    # Add a few random ordering tests
    all_indexes = list(range(len(sentences)))
    random_gen.shuffle(all_indexes)
    random_pairs = [(all_indexes[i * 2], all_indexes[i * 2 + 1]) for i in range(len(all_indexes) // 2)]
    random_pairs = [(min(i, j), max(i, j)) for (i, j) in random_pairs]

    num_order_tests = 0
    for i, j in random_pairs:
        first_sentence = sentences[i]
        second_sentence = sentences[j]

        if len(first_sentence) < 5 or len(second_sentence) < 5:
            continue

        if "\n" in first_sentence:
            first_sentence = first_sentence.split("\n")[0].strip()
        if "\n" in second_sentence:
            second_sentence = second_sentence.split("\n")[0].strip()

        max_diffs = round(max(len(first_sentence), len(second_sentence)) * 0.02)

        # Too big of a length discrepancy causes issues
        if max_diffs > len(first_sentence) // 4 or max_diffs > len(second_sentence) // 4:
            continue

        tests.append(
            {
                "pdf": pdf_filename,
                "page": 1,
                "id": f"{pdf_id}_order_{uuid.uuid4().hex[:8]}",
                "type": TestType.ORDER.value,
                "before": first_sentence,
                "after": second_sentence,
                "max_diffs": max_diffs,
            }
        )
        num_order_tests += 1

        if num_order_tests > 5:
            break

    # Step 4: Generate Math tests for LaTeX equations from the markdown
    
    # Define math patterns to search for
    math_patterns = [
        (r"\$\$(.+?)\$\$", re.DOTALL),  # $$...$$ (multiline)
        (r"\\\((.+?)\\\)", re.DOTALL),  # \(...\) (multiline)
        (r"\\\[(.+?)\\\]", re.DOTALL),  # \[...\] (multiline)
    ]
    
    math_equations = []
    for pattern, flags in math_patterns:
        matches = re.findall(pattern, markdown_content, flags)
        for match in matches:
            # Clean up the match - remove extra whitespace and newlines
            equation = match.strip()
            # Skip empty or very short equations
            if len(equation) > 2:
                math_equations.append(equation)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_equations = []
    for eq in math_equations:
        if eq not in seen:
            seen.add(eq)
            unique_equations.append(eq)
    
    # Create math tests for up to 50 unique equations
    for i, equation in enumerate(unique_equations[:50]):
        tests.append(
            {
                "pdf": pdf_filename,
                "page": 1,
                "id": f"{pdf_id}_math_{uuid.uuid4().hex[:8]}",
                "type": "math",
                "math": equation,
                "max_diffs": 0,
            }
        )

    # Final test filtering out stage

    # Now double check that the absent tests don't find any matches in the markdown_text
    # If they do, filter them out
    tests = [t for t in tests if t["type"] != "absent" or t["text"] not in markdown_text]

    # Remove any tests where text-based fields have no alphanumeric characters, contain LaTeX, or contain Unicode super/subscripts
    text_fields = ["text", "cell", "before", "after", "up", "down", "left", "right", "top_heading", "left_heading"]

    def contains_alphanumeric(value):
        return any(c.isalnum() for c in value) if isinstance(value, str) else False

    def contains_latex(value):
        if not isinstance(value, str):
            return False
        # Check for LaTeX delimiters
        latex_patterns = [r"\(", r"\)", r"\[", r"\]"]
        return any(pattern in value for pattern in latex_patterns)

    def contains_unicode_super_or_subscripts(value):
        if not isinstance(value, str):
            return False

        # Unicode ranges for superscripts and subscripts
        superscript_chars = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ"
        subscript_chars = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₕₖₗₘₙₚₛₜ"

        return any(c in superscript_chars or c in subscript_chars for c in value)

    filtered_tests = []
    for test in tests:
        # Math tests should not be filtered for LaTeX content
        if test.get("type") == "math":
            filtered_tests.append(test)
            continue
            
        # Check all text fields in the test for alphanumeric content, LaTeX, and Unicode super/subscripts
        all_valid = True
        for field in text_fields:
            if field in test:
                # Skip test if field has no alphanumeric characters
                if not contains_alphanumeric(test[field]):
                    all_valid = False
                    break
                # Skip test if field contains LaTeX delimiters
                if contains_latex(test[field]):
                    all_valid = False
                    break
                # Skip test if field contains Unicode super or subscripts
                if contains_unicode_super_or_subscripts(test[field]):
                    all_valid = False
                    break
        if all_valid:
            filtered_tests.append(test)

    tests = filtered_tests

    # Remove duplicate tests (identical on everything but the id field)
    unique_tests = []
    test_signatures = set()

    for test in tests:
        # Create a signature for the test by using all fields except 'id'
        test_dict = test.copy()
        test_dict.pop("id")

        # Convert dict to a sorted tuple of items for hashability
        test_signature = tuple(sorted((k, str(v)) for k, v in test_dict.items()))

        # Only add the test if we haven't seen an identical one
        if test_signature not in test_signatures:
            test_signatures.add(test_signature)
            unique_tests.append(test)

    
    return unique_tests


async def process_pdf(pdf_info, args, client, pdf_filter=None):
    """Process a single PDF, render a random page, and create an HTML template."""
    pdf_path, index = pdf_info

    # Create a unique folder for each PDF in the temp directory
    pdf_id = f"pdf_{index:05d}"
    temp_pdf_dir = os.path.join(args.temp_dir, pdf_id)
    os.makedirs(temp_pdf_dir, exist_ok=True)

    # Determine if we should log table test verification
    verbose_table_testing = args.verbose

    # Download PDF to local temp directory (or copy if local)
    local_pdf_path = os.path.join(temp_pdf_dir, "document.pdf")
    if not download_s3_pdf(pdf_path, local_pdf_path):
        print(f"Failed to download/copy PDF from {pdf_path}")
        return None
    
    # Apply filter if enabled
    if pdf_filter and pdf_filter.filter_out_pdf(local_pdf_path):
        print(f"PDF filtered out: {pdf_path}")
        return None
    
    # Seed with SHA1 hash of PDF contents for reproducibility
    with open(local_pdf_path, 'rb') as f:
        pdf_content = f.read()
        pdf_hash = hashlib.sha1(pdf_content).hexdigest()
    
    # Use the first 8 characters of the hash as an integer seed
    seed = int(pdf_hash[:8], 16)
    random_generator = random.Random(seed)

    try:
        # Get page count using pypdf
        reader = pypdf.PdfReader(local_pdf_path)
        num_pages = len(reader.pages)

        if num_pages == 0:
            print(f"PDF has no pages: {pdf_path}")
            return None

        # Select a random page
        page_num = random_generator.randint(1, num_pages)

        # Render the page as a base64 PNG (run in thread pool since it's blocking I/O)
        loop = asyncio.get_event_loop()
        image_base64 = await loop.run_in_executor(None, render_pdf_to_base64png, local_pdf_path, page_num, 1024)

        # Generate HTML from the image
        html_content = await generate_html_from_image(client, image_base64)
        if not html_content:
            print(f"Failed to generate HTML for {pdf_path}, page {page_num}")
            return None

        # Create output directories
        html_dir = os.path.join(args.output_dir, "html", args.name)
        pdfs_dir = os.path.join(args.output_dir, "pdfs", args.name)
        training_dir = os.path.join(args.output_dir, "training", args.name)
        bench_data_dir = os.path.join(args.output_dir, "bench_data")
        bench_synthetic_dir = os.path.join(bench_data_dir, "pdfs", args.name)
        claude_original_dir = os.path.join(bench_data_dir, "claude_original", args.name)
        os.makedirs(html_dir, exist_ok=True)
        os.makedirs(pdfs_dir, exist_ok=True)
        os.makedirs(training_dir, exist_ok=True)
        os.makedirs(bench_data_dir, exist_ok=True)
        os.makedirs(bench_synthetic_dir, exist_ok=True)
        os.makedirs(claude_original_dir, exist_ok=True)

        # Save HTML to output directory
        html_path = os.path.join(html_dir, f"{pdf_id}_page{page_num}.html")
        with open(html_path, "w") as f:
            f.write(html_content)
        
        # Convert HTML to markdown with FrontMatter and save
        markdown_content = html_to_markdown_with_frontmatter(html_content)
        markdown_filename = f"{pdf_id}_page{page_num}.md"
        markdown_path = os.path.join(training_dir, markdown_filename)
        with open(markdown_path, "w") as f:
            f.write(markdown_content)
        
        # Create soft link to PDF in training directory
        pdf_link_name = f"{pdf_id}_page{page_num}.pdf"
        pdf_link_path = os.path.join(training_dir, pdf_link_name)
        # Remove existing link if it exists
        if os.path.exists(pdf_link_path) or os.path.islink(pdf_link_path):
            os.remove(pdf_link_path)
        # Create relative symlink from training to pdfs directory
        os.symlink(os.path.relpath(os.path.join(pdfs_dir, f"{pdf_id}_page{page_num}.pdf"), training_dir), pdf_link_path)
        
        # Create soft link to markdown in claude_original/synthetic with new naming scheme
        claude_md_link_name = f"{pdf_id}_page{page_num}_pg1_repeat1.md"
        claude_md_link_path = os.path.join(claude_original_dir, claude_md_link_name)
        # Remove existing link if it exists
        if os.path.exists(claude_md_link_path) or os.path.islink(claude_md_link_path):
            os.remove(claude_md_link_path)
        # Create relative symlink from claude_original/synthetic to training directory
        os.symlink(os.path.relpath(markdown_path, claude_original_dir), claude_md_link_path)

        # Extract the page and save as PDF
        original_pdf_path = os.path.join(pdfs_dir, f"{pdf_id}_page{page_num}_original.pdf")
        if not extract_page_from_pdf(local_pdf_path, original_pdf_path, page_num):
            print(f"Failed to extract page {page_num} from {local_pdf_path}")

        # Render PDF using Playwright if not skipped
        playwright_pdf_path = None
        render_success = False
        playwright_pdf_filename = f"{pdf_id}_page{page_num}.pdf"  # This will be used in the tests

        if not args.skip_playwright:
            playwright_pdf_path = os.path.join(pdfs_dir, playwright_pdf_filename)

            try:
                # Get PNG dimensions
                png_width, png_height = get_png_dimensions_from_base64(image_base64)

                # Run the async function directly since we're already in an async context
                render_success = await render_pdf_with_playwright(html_content, playwright_pdf_path, png_width, png_height)

                if render_success:
                    print(f"Successfully rendered with Playwright: {playwright_pdf_path}")
                else:
                    print(f"Failed to render as a single page PDF: {playwright_pdf_path}")
                    playwright_pdf_path = None
            except Exception as e:
                print(f"Failed to render with Playwright: {e}")
                playwright_pdf_path = None
                render_success = False

        # If playwright rendering failed and was required, return None to skip this test
        if not args.skip_playwright and not render_success:
            return None
        
        # Create soft link in bench_data/synthetic/ directory
        if playwright_pdf_path:
            synthetic_link_path = os.path.join(bench_synthetic_dir, playwright_pdf_filename)
            # Remove existing link if it exists
            if os.path.exists(synthetic_link_path) or os.path.islink(synthetic_link_path):
                os.remove(synthetic_link_path)
            # Create relative symlink from bench_data/synthetic to pdfs directory
            os.symlink(os.path.relpath(playwright_pdf_path, bench_synthetic_dir), synthetic_link_path)

        # Generate tests from the HTML content
        # Use the playwright rendered PDF path for tests
        tests = generate_tests_from_html(html_content, pdf_id, page_num, random_generator, verbose_table_testing)

        # Update the PDF path in all tests to use the playwright rendered PDF with the specified name prefix
        for test in tests:
            test["pdf"] = f"{args.name}/{playwright_pdf_filename}"

        # Log table test stats if verbose
        if verbose_table_testing:
            table_tests = [t for t in tests if t["type"] == TestType.TABLE.value]
            print(f"Generated {len(table_tests)} table tests for {pdf_id}, page {page_num} (passed verification)")

        return {
            "pdf_id": pdf_id,
            "pdf_path": pdf_path,
            "page_number": page_num,
            "html_path": html_path,
            "markdown_path": markdown_path,
            "original_pdf_path": original_pdf_path,
            "playwright_pdf_path": playwright_pdf_path,
            "tests": tests,
            "num_tests": len(tests),
        }
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}")
        return None
    finally:
        # Clean up temp directory for this PDF
        if os.path.exists(temp_pdf_dir):
            subprocess.run(["rm", "-rf", temp_pdf_dir])


async def main():
    # Configure logging to suppress httpx messages
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    parser = argparse.ArgumentParser(description="Convert PDFs to HTML templates and render with Playwright")
    parser.add_argument("--input_list", required=True, help="Path to a file containing S3 paths or local paths to PDFs")
    parser.add_argument("--output_dir", required=True, help="Directory to store extracted pages and tests")
    parser.add_argument("--temp_dir", default="/tmp/mine_tables", help="Directory for temporary files")
    parser.add_argument("--max_tests", type=int, default=100, help="Maximum number of tests to generate")
    parser.add_argument("--parallel", type=int, default=1, help="Number of parallel tasks to use")
    parser.add_argument("--api_key", help="Claude API key (or set ANTHROPIC_API_KEY environment variable)")
    parser.add_argument("--skip_playwright", action="store_true", help="Skip Playwright PDF rendering")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output including table test verification")
    parser.add_argument("--filter", action="store_true", help="Apply PDF filtering to remove forms, spam, and non-English content")
    parser.add_argument("--name", default="synthetic", help="Name for the output JSONL file and subfolder (default: synthetic)")
    args = parser.parse_args()

    # Ensure output and temp directories exist
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.temp_dir, exist_ok=True)

    # Get API key
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: API key not provided. Use --api_key or set ANTHROPIC_API_KEY environment variable.")
        return

    # Initialize async Claude client
    client = AsyncAnthropic(api_key=api_key)
    
    # Initialize PDF filter if enabled
    pdf_filter = None
    if args.filter:
        pdf_filter = PdfFilter(
            languages_to_keep={Language.ENGLISH, None},  # None means could not detect language, that's okay keep it, might be an OCR
            apply_download_spam_check=True,
            apply_form_check=True,
        )
        print("PDF filtering enabled")

    # Reservoir sampling implementation
    random_gen = random.Random(42)
    pdf_paths = []

    if os.path.isdir(args.input_list):
        pdf_paths = list(glob.glob(os.path.join(args.input_list, "*.pdf"), recursive=True))
    else:
        with open(args.input_list, "r") as f:
            for i, line in enumerate(tqdm(f)):
                line = line.strip()
                if not line:
                    continue

                if i < 100000:
                    pdf_paths.append(line)
                else:
                    # Randomly replace elements with decreasing probability
                    j = random_gen.randint(0, i)
                    if j < 100000:
                        pdf_paths[j] = line

    print(f"Found {len(pdf_paths)} PDF paths in input list")

    # Shuffle and limit to max_tests
    random_gen.shuffle(pdf_paths)
    pdf_paths = pdf_paths[: args.max_tests]

    # Initialize the JSONL file in bench_data folder with the specified name
    bench_data_dir = os.path.join(args.output_dir, "bench_data")
    os.makedirs(bench_data_dir, exist_ok=True)
    synthetic_json_path = os.path.join(bench_data_dir, f"{args.name}.jsonl")
    open(synthetic_json_path, "w").close()  # Create empty file
    
    # Initialize the metadata JSONL file
    metadata_dir = os.path.join(args.output_dir, "metadata")
    os.makedirs(metadata_dir, exist_ok=True)
    metadata_json_path = os.path.join(metadata_dir, f"{args.name}.jsonl")
    open(metadata_json_path, "w").close()  # Create empty file

    # Counter for test statistics
    test_counter = 0
    test_types = defaultdict(int)  # Automatically handles any test type
    results = []

    # Initialize an asyncio lock for file access
    file_lock = asyncio.Lock()

    # Process PDFs in parallel using asyncio
    async def process_with_progress(pdf_info):
        pdf_path = pdf_info[0]
        try:
            result = await process_pdf(pdf_info, args, client, pdf_filter)
            if result and result.get("tests"):
                # Append tests to synthetic.json as they're created (JSONL format)
                async with file_lock:
                    # Append each test as a separate JSON line
                    with open(synthetic_json_path, "a") as f:
                        for test in result["tests"]:
                            f.write(json.dumps(test) + "\n")
                    
                    # Write metadata mapping (pdf_id to source URL)
                    with open(metadata_json_path, "a") as f:
                        metadata = {
                            "pdf_id": result["pdf_id"],
                            "source_url": result["pdf_path"],
                            "page_number": result["page_number"]
                        }
                        f.write(json.dumps(metadata) + "\n")
                    
                    # Update counters
                    nonlocal test_counter
                    test_counter += len(result["tests"])
                    for test in result["tests"]:
                        test_type = test.get("type", "unknown")
                        test_types[test_type] += 1
                    
                    print(f"Added {len(result['tests'])} tests from {result['pdf_id']}, total: {test_counter}")
                
                return result
        except Exception as e:
            print(f"Error processing {pdf_path}: {e}")
            return None

    # Create tasks for all PDFs
    tasks = []
    for i, pdf_path in enumerate(pdf_paths):
        tasks.append(process_with_progress((pdf_path, i)))
    
    # Run tasks with limited concurrency
    semaphore = asyncio.Semaphore(args.parallel)
    
    async def bounded_task(task_coro):
        async with semaphore:
            return await task_coro
    
    bounded_tasks = [bounded_task(task) for task in tasks]
    
    # Process all tasks with progress bar
    pbar = tqdm(asyncio.as_completed(bounded_tasks), total=len(bounded_tasks), desc="Processing PDFs")
    for coro in pbar:
        result = await coro
        if result:
            results.append(result)
        
        # Update progress bar with cost information
        cost_input = (total_input_tokens / 1_000_000) * 3.0  # $3 per million input tokens
        cost_output = (total_output_tokens / 1_000_000) * 15.0  # $15 per million output tokens
        total_cost = cost_input + cost_output
        pbar.set_postfix({
            'in_tokens': f'{total_input_tokens:,}',
            'out_tokens': f'{total_output_tokens:,}', 
            'cost': f'${total_cost:.2f}'
        })

    print(f"Generated {len(results)} HTML templates")

    # Print summary of Playwright rendering results
    playwright_success = sum(1 for r in results if r and r.get("playwright_pdf_path"))
    if not args.skip_playwright:
        print(f"Playwright PDF rendering: {playwright_success}/{len(results)} successful")

    print(f"Saved {test_counter} tests to {synthetic_json_path}")

    # Print summary of generated tests
    print(f"Generated a total of {test_counter} tests across {len(results)} templates")

    # Print test type distribution
    if test_counter > 0:
        print("Test type distribution:")
        for test_type, count in test_types.items():
            print(f"  - {test_type}: {count} tests")
    
    # Print final Claude API cost summary
    print("\nClaude Sonnet API Usage Summary:")
    print(f"  Total input tokens: {total_input_tokens:,}")
    print(f"  Total output tokens: {total_output_tokens:,}")
    cost_input = (total_input_tokens / 1_000_000) * 3.0
    cost_output = (total_output_tokens / 1_000_000) * 15.0
    total_cost = cost_input + cost_output
    print(f"  Input cost: ${cost_input:.2f} ($3/MTok)")
    print(f"  Output cost: ${cost_output:.2f} ($15/MTok)")
    print(f"  Total cost: ${total_cost:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
