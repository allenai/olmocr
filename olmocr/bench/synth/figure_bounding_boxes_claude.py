#!/usr/bin/env python3
"""
Script to detect figures in PDF pages and draw bounding boxes on them.
Uses Claude Sonnet Vision API for figure locations.
"""

import argparse
import base64
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import List, Tuple

import numpy as np
from anthropic import Anthropic
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field, field_validator

from olmocr.data.renderpdf import render_pdf_to_base64png


class BoundingBox(BaseModel):
    """Schema for a single bounding box using pixel coordinates."""
    x1: int = Field(
        description="Left edge x coordinate in pixels",
        ge=0
    )
    y1: int = Field(
        description="Top edge y coordinate in pixels",
        ge=0
    )
    x2: int = Field(
        description="Right edge x coordinate in pixels",
        gt=0
    )
    y2: int = Field(
        description="Bottom edge y coordinate in pixels",
        gt=0
    )
    label: str = Field(
        description="Description of the figure (e.g., 'Figure 1', 'Chart', 'Graph', 'Diagram')"
    )
    
    @field_validator('x2')
    @classmethod
    def validate_x2_greater_than_x1(cls, v: int, values) -> int:
        """Ensure x2 is greater than x1."""
        if 'x1' in values.data and v <= values.data['x1']:
            raise ValueError(f"x2 ({v}) must be greater than x1 ({values.data['x1']})")
        return v
    
    @field_validator('y2')
    @classmethod
    def validate_y2_greater_than_y1(cls, v: int, values) -> int:
        """Ensure y2 is greater than y1."""
        if 'y1' in values.data and v <= values.data['y1']:
            raise ValueError(f"y2 ({v}) must be greater than y1 ({values.data['y1']})")
        return v


class FigureDetectionResponse(BaseModel):
    """Schema for the complete figure detection response."""
    figures: List[BoundingBox] = Field(
        description="List of detected figures with their bounding boxes. Empty list if no figures found.",
        default_factory=list
    )


def decode_base64_to_image(base64_string: str) -> Image.Image:
    """Convert base64 string to PIL Image."""
    image_data = base64.b64decode(base64_string)
    return Image.open(BytesIO(image_data))


def encode_image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """Convert PIL Image to base64 string."""
    buffer = BytesIO()
    image.save(buffer, format=format)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def detect_figures_with_claude(base64_image: str, image_width: int, image_height: int) -> List[BoundingBox]:
    """
    Use Claude Sonnet Vision to detect figures in the image.
    Returns list of BoundingBox objects.
    """
    client = Anthropic()

    assert max(image_width, image_height) <= 1025, f"Going beyond 1025 is not going to work for claude, you passed in {max(image_width, image_height)}"
    assert image_width * image_height < 1_100_000, "More that 1.1 megapixels will also not work"
    
    prompt = f"""Analyze this PDF page image and identify all figures, charts, graphs, diagrams, and images.
    For each figure found, provide precise bounding box coordinates in pixels.
    Do NOT include tables or text boxes.
    
    The image dimensions are {image_width} x {image_height} pixels.
    
    Important:
    - Provide coordinates as absolute pixel values (x1, y1, x2, y2)
    - x1, y1 represents the top-left corner
    - x2, y2 represents the bottom-right corner
    - Only include actual figures/charts/images, not text blocks or tables
    - Be precise with the bounding boxes, fit the figure with a small 5 pixel margin, making sure no other elements get captured in the bounding box.
    - If no figures are found, return an empty list"""
    
    # Format prompt for JSON output
    json_prompt = prompt + """
    
    Return your response as a JSON object with this exact structure:
    {
        "figures": [
            {
                "x1": <left edge in pixels>,
                "y1": <top edge in pixels>,
                "x2": <right edge in pixels>,
                "y2": <bottom edge in pixels>,
                "label": "<description>"
            }
        ]
    }
    
    Return ONLY the JSON object, no other text."""
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            temperature=0,
            system="You are an expert at detecting and locating figures, charts, graphs, and diagrams in document images. Always respond with valid JSON.",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": json_prompt
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64_image
                            }
                        }
                    ]
                }
            ]
        )
        
        # Parse JSON response
        try:
            content = response.content[0].text
            # Extract JSON from the response
            start_idx = content.find('{')
            end_idx = content.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = content[start_idx:end_idx]
                result = json.loads(json_str)
                
                # Convert to BoundingBox objects
                bboxes = []
                for fig in result.get('figures', []):
                    try:
                        bbox = BoundingBox(
                            x1=fig['x1'],
                            y1=fig['y1'],
                            x2=fig['x2'],
                            y2=fig['y2'],
                            label=fig.get('label', 'Figure')
                        )

                        if "table" in bbox.label.lower():
                            continue

                        bboxes.append(bbox)
                    except Exception as e:
                        print(f"Error parsing bounding box: {e}")
                        print(f"Problematic bbox data: {fig}")
                return bboxes
            else:
                print(f"No JSON found in response: {content}")
                return []
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON from Claude response: {e}")
            print(f"Response content: {response.content[0].text}")
            return []
            
    except Exception as e:
        print(f"Error calling Claude API: {e}")
        return []


def draw_bounding_boxes(image: Image.Image, bboxes: List[BoundingBox], color: Tuple[int, int, int] = (255, 0, 0), width: int = 3) -> Image.Image:
    """
    Draw bounding boxes on the image.
    
    Args:
        image: PIL Image to draw on
        bboxes: List of BoundingBox objects with pixel coordinates
        color: RGB color for the boxes
        width: Line width for the boxes
    
    Returns:
        New image with bounding boxes drawn
    """
    # Create a copy to avoid modifying the original
    img_with_boxes = image.copy()
    draw = ImageDraw.Draw(img_with_boxes)
    
    for bbox in bboxes:
        # Draw rectangle using pixel coordinates directly
        draw.rectangle([bbox.x1, bbox.y1, bbox.x2, bbox.y2], outline=color, width=width)
        
        # Add label if present
        if bbox.label:
            # Simple text placement (top-left of box)
            draw.text((bbox.x1 + 5, bbox.y1 + 5), bbox.label, fill=color)
    
    return img_with_boxes


def process_pdf_page(pdf_path: str, page_num: int, output_path: str, api_key: str) -> bool:
    """
    Process a single PDF page: render, detect figures, and save with bounding boxes.
    
    Args:
        pdf_path: Path to the PDF file
        page_num: Page number to process (0-indexed)
        output_path: Path to save the output image
        api_key: OpenAI API key

    Returns:
        True if successful, False otherwise
    """
    try:
        # Render PDF page to base64 PNG
        print(f"Rendering page {page_num} of {pdf_path}...")
        base64_image = render_pdf_to_base64png(pdf_path, page_num, target_longest_image_dim=1024)
        
        # Convert to PIL Image
        image = decode_base64_to_image(base64_image)
        print(f"Image size: {image.size}")
        
        # Detect figures using Claude
        print("Detecting figures with Claude Sonnet...")
        bboxes = detect_figures_with_claude(base64_image, image.size[0], image.size[1])
        
        if not bboxes:
            print("No figures detected.")
        else:
            print(f"Detected {len(bboxes)} figure(s):")
            for bbox in bboxes:
                print(f"  - {bbox.label}: ({bbox.x1}, {bbox.y1}) to ({bbox.x2}, {bbox.y2})")
        
        # Draw bounding boxes
        result_image = draw_bounding_boxes(image, bboxes)
        
        # Save the result
        result_image.save(output_path)
        print(f"Saved result to {output_path}")
        
        # Also save the bounding box data as JSON
        json_path = Path(output_path).with_suffix('.json')
        with open(json_path, 'w') as f:
            json.dump({
                'pdf_path': pdf_path,
                'page_num': page_num,
                'image_size': list(image.size),
                'bounding_boxes': [bbox.model_dump() for bbox in bboxes],
                'coordinate_format': 'x1_y1_x2_y2_pixels'
            }, f, indent=2)
        print(f"Saved bounding box data to {json_path}")
        
        return True
        
    except Exception as e:
        print(f"Error processing PDF page: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Detect figures in PDF pages and draw bounding boxes using Claude')
    parser.add_argument('pdf_path', help='Path to the PDF file')
    parser.add_argument('-p', '--page', type=int, default=0, help='Page number to process (0-indexed, default: 0)')
    parser.add_argument('-o', '--output', help='Output image path (default: <pdf_name>_page<N>_figures_claude.png)')
    parser.add_argument('--api-key', help='Anthropic API key (or set ANTHROPIC_API_KEY environment variable)')
    parser.add_argument('--color', default='red', help='Color for bounding boxes (default: red)')
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.api_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("Error: Anthropic API key required. Set ANTHROPIC_API_KEY environment variable or use --api-key")
        sys.exit(1)
    
    # Check if PDF exists
    if not os.path.exists(args.pdf_path):
        print(f"Error: PDF file not found: {args.pdf_path}")
        sys.exit(1)
    
    # Generate output path if not provided
    if args.output:
        output_path = args.output
    else:
        pdf_name = Path(args.pdf_path).stem
        output_path = f"{pdf_name}_page{args.page}_figures_claude.png"
    
    # Process the PDF page
    success = process_pdf_page(
        args.pdf_path, 
        args.page, 
        output_path, 
        api_key,
    )
    
    if success:
        print("\nProcessing completed successfully!")
    else:
        print("\nProcessing failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()