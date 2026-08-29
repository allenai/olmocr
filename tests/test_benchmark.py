import argparse
import ast
import unittest
from pathlib import Path

BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "olmocr" / "bench" / "benchmark.py"


def _help_string_for_option(option: str) -> str:
    tree = ast.parse(BENCHMARK_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        option_args = [arg for arg in node.args if isinstance(arg, ast.Constant) and arg.value == option]
        if not option_args:
            continue
        for keyword in node.keywords:
            if keyword.arg == "help" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                return keyword.value.value
    raise AssertionError(f"{option} help string not found in {BENCHMARK_PATH}")


class TestBenchmarkArgparseHelp(unittest.TestCase):
    def test_confidence_level_help_is_valid_argparse_format(self):
        """argparse %-formats help text, so a literal '%' in '95% CI' raises ValueError."""
        help_text = _help_string_for_option("--confidence_level")
        parser = argparse.ArgumentParser()
        parser.add_argument("--confidence_level", type=float, default=0.95, help=help_text)
        formatted = parser.format_help()
        self.assertIn("95% CI", formatted)
