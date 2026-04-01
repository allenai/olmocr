import sys
import types

pypdf = types.ModuleType("pypdf")
pypdf.PdfReader = object
sys.modules.setdefault("pypdf", pypdf)

tqdm_module = types.ModuleType("tqdm")
tqdm_module.tqdm = lambda iterable, *args, **kwargs: iterable
sys.modules.setdefault("tqdm", tqdm_module)

renderpdf_module = types.ModuleType("olmocr.data.renderpdf")
renderpdf_module.render_pdf_to_base64png = lambda *args, **kwargs: None
sys.modules.setdefault("olmocr.data.renderpdf", renderpdf_module)

image_utils_module = types.ModuleType("olmocr.image_utils")
image_utils_module.convert_image_to_pdf_bytes = lambda *args, **kwargs: b""
sys.modules.setdefault("olmocr.image_utils", image_utils_module)

from olmocr.bench.convert import parse_method_arg


def test_parse_method_arg_allows_colons_in_value():
    name, kwargs, folder = parse_method_arg("server:model=gemma-3-27b:endpoint=localhost:8080/v1")

    assert name == "server"
    assert kwargs["model"] == "gemma-3-27b"
    assert kwargs["endpoint"] == "localhost:8080/v1"
    assert folder == "server"


def test_parse_method_arg_preserves_numeric_casting():
    name, kwargs, folder = parse_method_arg("mock:temperature=0.1:max_tokens=128:name=trial")

    assert name == "mock"
    assert kwargs["temperature"] == 0.1
    assert kwargs["max_tokens"] == 128
    assert folder == "trial"
