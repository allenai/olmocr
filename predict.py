from cog import BasePredictor, Input, Path
import os
import time
import torch
import base64
import subprocess
from PIL import Image
from io import BytesIO
from olmocr.data.renderpdf import render_pdf_to_base64png
from olmocr.prompts import build_finetuning_prompt
from olmocr.prompts.anchor import get_anchor_text
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

MODEL_CACHE = "checkpoints"
MODEL_URL = "https://weights.replicate.delivery/default/allenai/olmOCR-7B-0225-preview/model.tar"
VISION_URL = "https://weights.replicate.delivery/default/qwen/Qwen2-VL-7B-Instruct/model.tar"

def download_weights(url, dest):
    start = time.time()
    print("downloading url: ", url)
    print("downloading to: ", dest)
    subprocess.check_call(["pget", "-xf", url, dest], close_fds=False)
    print("downloading took: ", time.time() - start)

class Predictor(BasePredictor):
    def setup(self) -> None:
        """Load the model into memory to make running multiple predictions efficient"""
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        t1 = time.time()

        # make directory checkpoints if it doesn't exist
        if not os.path.exists(MODEL_CACHE):
            os.makedirs(MODEL_CACHE)
            
        # Download the model weights if they don't exist
        if not os.path.exists(MODEL_CACHE + "/olmOCR-7B-0225-preview"):
            download_weights(MODEL_URL, MODEL_CACHE + "/olmOCR-7B-0225-preview")
        # Initialize model and processor
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            MODEL_CACHE+"/olmOCR-7B-0225-preview", 
            torch_dtype=torch.bfloat16
        ).eval().to(self.device)
        
        # Download the vision model weights if they don't exist
        if not os.path.exists(MODEL_CACHE + "/Qwen2-VL-7B-Instruct"):
            download_weights(VISION_URL, MODEL_CACHE + "/Qwen2-VL-7B-Instruct")
        self.processor = AutoProcessor.from_pretrained(MODEL_CACHE+"/Qwen2-VL-7B-Instruct")
        print("Setup took: ", time.time() - t1)

    def predict(
        self,
        pdf: Path = Input(description="Input PDF file"),
        page_number: int = Input(description="Page number to process", default=1),
        temperature: float = Input(description="Sampling temperature", default=0.8),
        max_new_tokens: int = Input(description="Maximum number of tokens to generate", default=100),
    ) -> str:
        """Run a single prediction on the model"""
        # Save uploaded PDF temporarily and render to image
        pdf_path = str(pdf)
        image_base64 = render_pdf_to_base64png(
            pdf_path, 
            page_number, 
            target_longest_image_dim=1024
        )

        # Build the prompt using document metadata
        anchor_text = get_anchor_text(
            pdf_path, 
            page_number, 
            pdf_engine="pdfreport", 
            target_length=4000
        )
        prompt = build_finetuning_prompt(anchor_text)

        # Build the full prompt with image
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                ],
            }
        ]

        # Process inputs
        text = self.processor.apply_chat_template(
            messages, 
            tokenize=False, 
            add_generation_prompt=True
        )
        main_image = Image.open(BytesIO(base64.b64decode(image_base64)))
        inputs = self.processor(
            text=[text],
            images=[main_image],
            padding=True,
            return_tensors="pt",
        )
        inputs = {key: value.to(self.device) for (key, value) in inputs.items()}

        # Generate output
        output = self.model.generate(
            **inputs,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
            num_return_sequences=1,
            do_sample=True,
        )

        # Decode output
        prompt_length = inputs["input_ids"].shape[1]
        new_tokens = output[:, prompt_length:]
        text_output = self.processor.tokenizer.batch_decode(
            new_tokens, 
            skip_special_tokens=True
        )

        return str(text_output)
