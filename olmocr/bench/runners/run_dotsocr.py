import base64
from io import BytesIO

import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoProcessor
from qwen_vl_utils import process_vision_info

from olmocr.data.renderpdf import render_pdf_to_base64png

# Global cache for the model and processor.
_device = "cuda" if torch.cuda.is_available() else "cpu"
_model = None
_processor = None


def load_model(model_name: str = "rednote-hilab/dots.ocr"):
    """
    Load the DotsOCR model and processor if they haven't been loaded already.

    Args:
        model_name: Hugging Face model name for DotsOCR

    Returns:
        model: The DotsOCR model loaded on the appropriate device.
        processor: The corresponding processor.
    """
    global _model, _processor
    if _model is None or _processor is None:
        _model = AutoModelForCausalLM.from_pretrained(
            model_name,
            attn_implementation="flash_attention_2",
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True
        )
        _processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
    return _model, _processor


def run_dotsocr(
    pdf_path: str,
    page_num: int = 1,
    model_name: str = "rednote-hilab/dots.ocr",
    target_longest_image_dim: int = 1024
) -> str:
    """
    Convert page of a PDF file to structured layout information using DotsOCR.

    This function renders the specified page of the PDF to an image, runs DotsOCR on that image,
    and returns the structured layout information as JSON.

    Args:
        pdf_path (str): The local path to the PDF file.
        page_num (int): The page number to process (default: 1).
        model_name (str): Hugging Face model name (default: "rednote-hilab/dots.ocr").
        target_longest_image_dim (int): Target dimension for the longest side of the image (default: 1024).

    Returns:
        str: The structured layout information in JSON format.
    """
    # Ensure the model is loaded (cached across calls)
    model, processor = load_model(model_name)

    # Convert the specified page of the PDF to a base64-encoded PNG image.
    image_base64 = render_pdf_to_base64png(pdf_path, page_num=page_num, target_longest_image_dim=target_longest_image_dim)

    # Create PIL Image from base64
    image = Image.open(BytesIO(base64.b64decode(image_base64)))

    # Define the prompt for layout extraction
    prompt = """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text content within the bbox.

1. Bbox format: [x1, y1, x2, y2]

2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].

3. Text Extraction & Formatting Rules:
    - Picture: For the 'Picture' category, the text field should be omitted.
    - Formula: Format its text as LaTeX.
    - Table: Format its text as HTML.
    - All Others (Text, Title, etc.): Format their text as Markdown.

4. Constraints:
    - The output text must be the original text from the image, with no translation.
    - All layout elements must be sorted according to human reading order.

5. Final Output: The entire output must be a single JSON object.
"""

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": image
                },
                {"type": "text", "text": prompt}
            ]
        }
    ]

    # Preparation for inference
    text = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )

    inputs = inputs.to(_device)

    # Inference: Generation of the output
    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=24000)

    generated_ids_trimmed = [
        out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]

    output_text = processor.batch_decode(
        generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )

    return output_text[0] if output_text else ""