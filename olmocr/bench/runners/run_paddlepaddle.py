from threading import Lock

from paddleocr import PPStructureV3

# Run's paddle paddle as in the docs here: https://huggingface.co/PaddlePaddle/PP-OCRv5_server_det
#  text_detection_model_name="PP-OCRv5_server_det",
# and using the PP-StructureV3 pipeline to create markdown
paddle_pipeline = None
paddle_pipeline_lock = Lock()


def run_paddlepaddle(pdf_path: str, page_num: int = 1, **kwargs) -> str:
    global paddle_pipeline

    with paddle_pipeline_lock:
        if paddle_pipeline is None:
            paddle_pipeline = PPStructureV3(
                text_detection_model_name="PP-OCRv5_server_det",
                use_doc_orientation_classify=False,  # Use use_doc_orientation_classify to enable/disable document orientation classification model
                use_doc_unwarping=False,  # Use use_doc_unwarping to enable/disable document unwarping module
                use_textline_orientation=False,  # Use use_textline_orientation to enable/disable textline orientation classification model
                device="gpu:0",  # Use device to specify GPU for model inference
            )

    output = paddle_pipeline.predict(pdf_path)
    result = ""
    for cur_page_0_indexed, res in enumerate(output):
        if cur_page_0_indexed == page_num - 1:
            result = res.markdown["markdown_texts"]

    return result
