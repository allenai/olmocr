import openai
import base64
import fitz  # PyMuPDF
from io import BytesIO
from PIL import Image
import os
import random

# --- Configuration ---
SERVER_URL = "http://192.168.8.233:6900/v1"
API_KEY = "EMPTY"  # VLLM doesn't require a real key
VLLM_MODEL = "allenai/olmOCR-7B-0225-preview"

# --- Parameters ---
PDF_FOLDER_PATH = r"../../tests/gnarly_pdfs"
MAX_IMAGE_DIMENSION = 1024

def get_random_pdf_path(folder_path):
    """Finds all PDFs in a folder and returns the full path to a random one."""
    try:
        pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
        if not pdf_files:
            raise FileNotFoundError(f"No PDF files found in '{folder_path}'")
        random_pdf_filename = random.choice(pdf_files)
        return os.path.join(folder_path, random_pdf_filename)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return None

def prepare_image_from_pdf(pdf_path, page_num=0, dpi=150, max_dim=1024):
    """
    Opens a PDF, converts a specific page to a resized image,
    and returns it as a base64 encoded string.
    """
    with fitz.open(pdf_path) as doc:
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    # Resize the image if it's too large
    if max(img.width, img.height) > max_dim:
        img.thumbnail((max_dim, max_dim))
        print(f" -> Image resized to fit within {max_dim}x{max_dim}")

    # Convert to base64
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def get_ocr_transcription(image_base64):
    """Sends the image to the VLLM server and returns the transcription."""
    client = openai.Client(base_url=SERVER_URL, api_key=API_KEY)
    print(" -> Sending request to VLLM server...")
    response = client.chat.completions.create(
        model=VLLM_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe the text from this image."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                ],
            }
        ],
        max_tokens=4096,
        temperature=0.0
    )
    return response.choices[0].message.content

# --- Main Script Execution ---
if __name__ == "__main__":
    # 1. Get a random PDF file
    pdf_path = get_random_pdf_path(PDF_FOLDER_PATH)
    
    if pdf_path:
        print(f"Processing a random PDF: {os.path.basename(pdf_path)}")
        try:
            # 2. Prepare the first page of the PDF as a base64 image
            b64_image = prepare_image_from_pdf(pdf_path, max_dim=MAX_IMAGE_DIMENSION)
            
            # 3. Get the OCR transcription from the server
            transcription = get_ocr_transcription(b64_image)
            
            # 4. Display the result
            print("\n" + "="*20 + " OCR Result " + "="*20)
            print(transcription)
            print("="*52 + "\n")

        except Exception as e:
            print(f"An unexpected error occurred: {e}")
