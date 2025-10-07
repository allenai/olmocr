#!/usr/bin/env python3
"""
Test suite for GRPO training dataloader.
Tests the OlmOCRBenchDataset class and its functionality with Olmocr-bench format.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from olmocr.train.grpo_train import (
    OlmOCRBenchDataset,
    load_specific_tests_cached,
    olmocr_bench_reward,
    reward_front_matter,
)


class TestGRPODataloader(unittest.TestCase):
    """Test cases for the GRPO dataloader."""

    @classmethod
    def setUpClass(cls):
        """Create a temporary bench_data folder with test data."""
        cls.temp_dir = tempfile.mkdtemp()
        cls.bench_data_folder = cls.temp_dir
        cls.pdfs_folder = os.path.join(cls.bench_data_folder, "pdfs")

        # Create folder structure
        os.makedirs(os.path.join(cls.pdfs_folder, "test_pdfs"), exist_ok=True)

        # Create dummy PDF files
        cls.pdf_files = []
        for i in range(3):
            pdf_path = os.path.join(cls.pdfs_folder, "test_pdfs", f"test_{i}.pdf")
            # Create a minimal valid PDF
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4\n%%EOF")
            cls.pdf_files.append(pdf_path)

        # Create test JSONL files
        cls.jsonl_file1 = os.path.join(cls.bench_data_folder, "test1.jsonl")
        cls.jsonl_file2 = os.path.join(cls.bench_data_folder, "test2.jsonl")

        # Write test data to JSONL files
        test_data1 = [
            {"pdf": "test_pdfs/test_0.pdf", "page": 0, "id": "test_0_001", "type": "math", "math": "x + y = z"},
            {"pdf": "test_pdfs/test_0.pdf", "page": 0, "id": "test_0_002", "type": "text", "text": "Sample text"},
            {"pdf": "test_pdfs/test_1.pdf", "page": 0, "id": "test_1_001", "type": "math", "math": "a^2 + b^2 = c^2"},
            {"pdf": "test_pdfs/test_1.pdf", "page": 1, "id": "test_1_002", "type": "text", "text": "Another sample"},
        ]

        test_data2 = [
            {"pdf": "test_pdfs/test_2.pdf", "page": 0, "id": "test_2_001", "type": "table", "table": "col1,col2"},
            {"pdf": "test_pdfs/test_0.pdf", "page": 0, "id": "test_0_003", "type": "text", "text": "More text"},
            {"pdf": "test_pdfs/test_2.pdf", "page": 0, "id": "test_2_002", "type": "math", "math": "\\int_0^1 x dx"},
        ]

        with open(cls.jsonl_file1, "w") as f:
            for entry in test_data1:
                f.write(json.dumps(entry) + "\n")

        with open(cls.jsonl_file2, "w") as f:
            for entry in test_data2:
                f.write(json.dumps(entry) + "\n")

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary files."""
        shutil.rmtree(cls.temp_dir)

    def test_dataset_initialization(self):
        """Test that dataset initializes correctly."""
        dataset = OlmOCRBenchDataset(
            bench_data_folder=self.bench_data_folder,
            processor=None,
            max_samples=None,
            target_longest_image_dim=1024,
        )

        self.assertIsNotNone(dataset)
        self.assertEqual(dataset.bench_data_folder, self.bench_data_folder)
        self.assertEqual(dataset.pdf_folder, self.pdfs_folder)
        self.assertTrue(len(dataset) > 0)

    def test_unique_pdf_loading(self):
        """Test that unique PDFs are loaded correctly."""
        dataset = OlmOCRBenchDataset(
            bench_data_folder=self.bench_data_folder,
            processor=None,
            max_samples=None,
            target_longest_image_dim=1024,
        )

        # Should have 4 unique PDF+page combinations:
        # test_0.pdf page 0, test_1.pdf page 0, test_1.pdf page 1, test_2.pdf page 0
        self.assertEqual(len(dataset), 4)

        # Check that samples have correct structure
        for sample in dataset.samples:
            self.assertIn("pdf_path", sample)
            self.assertIn("pdf_name", sample)
            self.assertIn("page", sample)
            self.assertIn("jsonl_file", sample)
            self.assertIn("test_ids", sample)
            self.assertIn("entries", sample)

    def test_test_id_aggregation(self):
        """Test that test IDs are correctly aggregated per PDF+page."""
        dataset = OlmOCRBenchDataset(
            bench_data_folder=self.bench_data_folder,
            processor=None,
            max_samples=None,
            target_longest_image_dim=1024,
        )

        # Find the sample for test_0.pdf page 0
        test_0_sample = None
        for sample in dataset.samples:
            if "test_0.pdf" in sample["pdf_name"] and sample["page"] == 0:
                test_0_sample = sample
                break

        self.assertIsNotNone(test_0_sample)
        # Should have 3 test IDs for test_0.pdf page 0
        self.assertEqual(len(test_0_sample["test_ids"]), 3)
        self.assertIn("test_0_001", test_0_sample["test_ids"])
        self.assertIn("test_0_002", test_0_sample["test_ids"])
        self.assertIn("test_0_003", test_0_sample["test_ids"])

    def test_max_samples_limit(self):
        """Test that max_samples correctly limits the dataset size."""
        dataset = OlmOCRBenchDataset(
            bench_data_folder=self.bench_data_folder,
            processor=None,
            max_samples=2,
            target_longest_image_dim=1024,
        )

        self.assertEqual(len(dataset), 2)

    @patch("olmocr.train.grpo_train.render_pdf_to_base64png")
    @patch("olmocr.train.grpo_train.build_no_anchoring_v4_yaml_prompt")
    def test_getitem_format(self, mock_prompt, mock_render):
        """Test that __getitem__ returns the correct format."""
        # Mock the rendering and prompt functions
        mock_render.return_value = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="  # 1x1 white pixel PNG
        mock_prompt.return_value = "Test prompt"

        dataset = OlmOCRBenchDataset(
            bench_data_folder=self.bench_data_folder,
            processor=None,
            max_samples=1,
            target_longest_image_dim=1024,
        )

        item = dataset[0]

        self.assertIsNotNone(item)
        self.assertIn("prompt", item)
        self.assertIn("pdf_path", item)
        self.assertIn("jsonl_file", item)
        self.assertIn("test_ids", item)
        self.assertIn("image", item)

        # Check prompt structure
        self.assertIsInstance(item["prompt"], list)
        self.assertEqual(len(item["prompt"]), 1)
        self.assertEqual(item["prompt"][0]["role"], "user")
        self.assertIsInstance(item["prompt"][0]["content"], list)
        self.assertEqual(len(item["prompt"][0]["content"]), 2)

        # Check other fields
        self.assertIsInstance(item["pdf_path"], str)
        self.assertIsInstance(item["jsonl_file"], str)
        self.assertIsInstance(item["test_ids"], list)
        self.assertTrue(len(item["test_ids"]) > 0)

    def test_empty_jsonl_handling(self):
        """Test handling of empty JSONL files."""
        # Create an empty JSONL file
        empty_jsonl = os.path.join(self.bench_data_folder, "empty.jsonl")
        open(empty_jsonl, "w").close()

        # Should still work with other non-empty files
        dataset = OlmOCRBenchDataset(
            bench_data_folder=self.bench_data_folder,
            processor=None,
            max_samples=None,
            target_longest_image_dim=1024,
        )

        self.assertTrue(len(dataset) > 0)

        # Clean up
        os.remove(empty_jsonl)

    def test_malformed_jsonl_handling(self):
        """Test handling of malformed JSONL entries."""
        # Create a JSONL with some malformed entries
        malformed_jsonl = os.path.join(self.bench_data_folder, "malformed.jsonl")
        with open(malformed_jsonl, "w") as f:
            f.write('{"pdf": "test.pdf", "id": "valid_1"}\n')
            f.write("not valid json\n")
            f.write('{"pdf": "test2.pdf", "id": "valid_2"}\n')

        # Should skip malformed entries but process valid ones
        dataset = OlmOCRBenchDataset(
            bench_data_folder=self.bench_data_folder,
            processor=None,
            max_samples=None,
            target_longest_image_dim=1024,
        )

        # Should still have entries from valid files
        self.assertTrue(len(dataset) > 0)

        # Clean up
        os.remove(malformed_jsonl)

    def test_missing_pdf_folder(self):
        """Test error handling when pdfs folder is missing."""
        temp_bad_folder = tempfile.mkdtemp()

        with self.assertRaises(ValueError) as context:
            dataset = OlmOCRBenchDataset(
                bench_data_folder=temp_bad_folder,
                processor=None,
                max_samples=None,
                target_longest_image_dim=1024,
            )

        self.assertIn("PDFs folder not found", str(context.exception))

        # Clean up
        shutil.rmtree(temp_bad_folder)

    def test_no_jsonl_files(self):
        """Test error handling when no JSONL files are present."""
        temp_folder = tempfile.mkdtemp()
        os.makedirs(os.path.join(temp_folder, "pdfs"))

        with self.assertRaises(ValueError) as context:
            dataset = OlmOCRBenchDataset(
                bench_data_folder=temp_folder,
                processor=None,
                max_samples=None,
                target_longest_image_dim=1024,
            )

        self.assertIn("No JSONL files found", str(context.exception))

        # Clean up
        shutil.rmtree(temp_folder)


class TestOlmOCRBenchReward(unittest.TestCase):
    """Test cases for the olmocr_bench_reward function."""

    @classmethod
    def setUpClass(cls):
        """Create temporary test files."""
        # Clear any cached tests from previous runs
        load_specific_tests_cached.cache_clear()
        cls.temp_dir = tempfile.mkdtemp()

        # Create a sample JSONL test file with different test types
        cls.jsonl_path = os.path.join(cls.temp_dir, "test.jsonl")
        test_data = [
            {"pdf": "test.pdf", "page": 0, "id": "test1", "type": "present", "text": "Hello World", "max_diffs": 0},
            {"pdf": "test.pdf", "page": 0, "id": "test2", "type": "absent", "text": "Bad Text", "max_diffs": 0},
            {"pdf": "test.pdf", "page": 0, "id": "test3", "type": "baseline", "max_repeats": 30},
            {"pdf": "test.pdf", "page": 0, "id": "test4", "type": "order", "before": "First", "after": "Second", "max_diffs": 0},
        ]

        with open(cls.jsonl_path, "w") as f:
            for test in test_data:
                f.write(json.dumps(test) + "\n")

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary files."""
        # Clear the LRU cache before removing temp dir
        load_specific_tests_cached.cache_clear()
        shutil.rmtree(cls.temp_dir)

    def setUp(self):
        """Clear cache before each test method."""
        load_specific_tests_cached.cache_clear()

    def test_perfect_completion(self):
        """Test reward calculation for a completion that passes all tests."""
        completions = ["Hello World\n\nFirst paragraph.\n\nSecond paragraph.\n\nThis is a good document with no bad text."]
        test_ids_list = [["test1", "test2", "test3", "test4"]]

        rewards = olmocr_bench_reward(
            prompts=["prompt"], completions=completions, completion_ids=[[]], pdf_path=["test.pdf"], jsonl_file=[self.jsonl_path], test_ids=test_ids_list
        )

        self.assertEqual(len(rewards), 1)
        self.assertEqual(rewards[0], 1.0)  # All 4 tests should pass

    def test_partial_completion(self):
        """Test reward calculation for a completion that passes some tests."""
        completions = ["This document contains Bad Text but nothing else of note."]
        test_ids_list = [["test1", "test2", "test3"]]

        rewards = olmocr_bench_reward(
            prompts=["prompt"], completions=completions, completion_ids=[[]], pdf_path=["test.pdf"], jsonl_file=[self.jsonl_path], test_ids=test_ids_list
        )

        self.assertEqual(len(rewards), 1)
        # Should pass only baseline test (1/3)
        self.assertAlmostEqual(rewards[0], 1 / 3, places=2)

    def test_multiple_completions(self):
        """Test reward calculation for multiple completions."""
        completions = [
            "Hello World with good content. First then Second.",
            "Bad Text only",
            "",  # Empty completion
        ]
        test_ids_list = [["test1", "test2", "test3", "test4"]] * 3

        rewards = olmocr_bench_reward(
            prompts=["prompt"] * 3,
            completions=completions,
            completion_ids=[[]] * 3,
            pdf_path=["test.pdf"] * 3,
            jsonl_file=[self.jsonl_path] * 3,
            test_ids=test_ids_list,
        )

        self.assertEqual(len(rewards), 3)
        # First should pass all 4 tests
        self.assertEqual(rewards[0], 1.0)
        # Second should pass only baseline (1/4)
        self.assertEqual(rewards[1], 0.25)
        # Third (empty string) passes only the "absent" test (1/4)
        self.assertEqual(rewards[2], 0.25)

    def test_no_relevant_tests(self):
        """Test behavior when no relevant tests are found."""
        completions = ["Some content"]
        test_ids_list = [["nonexistent_test"]]

        rewards = olmocr_bench_reward(
            prompts=["prompt"], completions=completions, completion_ids=[[]], pdf_path=["test.pdf"], jsonl_file=[self.jsonl_path], test_ids=test_ids_list
        )

        self.assertEqual(len(rewards), 1)
        self.assertIsNone(rewards[0])  # Should return None when no tests found

    def test_invalid_completion(self):
        """Test handling of invalid completions."""
        completions = [None, "", "Valid content with Hello World"]
        test_ids_list = [["test1"]] * 3

        rewards = olmocr_bench_reward(
            prompts=["prompt"] * 3,
            completions=completions,
            completion_ids=[[]] * 3,
            pdf_path=["test.pdf"] * 3,
            jsonl_file=[self.jsonl_path] * 3,
            test_ids=test_ids_list,
        )

        self.assertEqual(len(rewards), 3)
        # First should be None (invalid completion)
        self.assertIsNone(rewards[0])
        # Second should fail the test (empty string doesn't contain "Hello World")
        self.assertEqual(rewards[1], 0.0)
        # Last should pass the test
        self.assertEqual(rewards[2], 1.0)

    def test_cache_functionality(self):
        """Test that load_specific_tests_cached properly caches results."""
        # Clear cache first
        load_specific_tests_cached.cache_clear()

        # Test that the cache works by calling the function twice
        test_ids = ("test1", "test2")

        # First call loads from file
        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = iter(
                [
                    '{"id": "test1", "type": "present", "text": "hello", "pdf": "test.pdf", "page": 0}\n',
                    '{"id": "test2", "type": "absent", "text": "world", "pdf": "test.pdf", "page": 0}\n',
                    '{"id": "test3", "type": "present", "text": "foo", "pdf": "test.pdf", "page": 0}\n',
                ]
            )
            mock_open.return_value = mock_file

            result1 = load_specific_tests_cached(self.jsonl_path, test_ids)
            self.assertEqual(mock_open.call_count, 1)

            # Second call should use cache, not open file again
            result2 = load_specific_tests_cached(self.jsonl_path, test_ids)
            self.assertEqual(mock_open.call_count, 1)  # Should not increase

            # Results should be the same
            self.assertEqual(result1, result2)
            self.assertEqual(len(result1), 2)  # Should have loaded 2 tests

    def test_error_handling(self):
        """Test error handling in reward function."""
        # Test with non-existent file
        rewards = olmocr_bench_reward(
            prompts=["prompt"],
            completions=["content"],
            completion_ids=[[]],
            pdf_path=["test.pdf"],
            jsonl_file=["/nonexistent/file.jsonl"],
            test_ids=[["test1"]],
        )

        # Should return None on error
        self.assertEqual(len(rewards), 1)
        self.assertIsNone(rewards[0])


class TestRewardFrontMatter(unittest.TestCase):
    """Test cases for the reward_front_matter function."""

    def test_no_frontmatter(self):
        """Test that completions without frontmatter get 0.0 reward."""
        completions = ["This is just text without any frontmatter", "Another completion with no YAML", "# A markdown header but no frontmatter"]

        rewards = reward_front_matter(prompts=["prompt"] * 3, completions=completions, claude_original=None)

        self.assertEqual(len(rewards), 3)
        for reward in rewards:
            self.assertEqual(reward, 0.0)

    def test_valid_frontmatter_no_claude(self):
        """Test that valid frontmatter gets 0.5 reward when no claude_original."""
        completions = [
            """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---

# Document content here""",
            """---
primary_language: fr
is_rotation_valid: False
rotation_correction: 90
is_table: True
is_diagram: False
---

Some other content""",
        ]

        rewards = reward_front_matter(prompts=["prompt"] * 2, completions=completions, claude_original=None)

        self.assertEqual(len(rewards), 2)
        for reward in rewards:
            self.assertEqual(reward, 0.5)

    def test_perfect_match_with_claude(self):
        """Test perfect match with claude_original gets 1.0 reward."""
        claude_original_content = """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---

Original content"""

        completion = """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---

Different content but same frontmatter"""

        rewards = reward_front_matter(prompts=["prompt"], completions=[completion], claude_original=[claude_original_content])

        self.assertEqual(len(rewards), 1)
        self.assertAlmostEqual(rewards[0], 1.0, places=5)

    def test_partial_match_with_claude(self):
        """Test partial match with claude_original gets intermediate reward."""
        claude_original_content = """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---

Original content"""

        # 3 out of 5 fields match
        completion = """---
primary_language: en
is_rotation_valid: False
rotation_correction: 90
is_table: False
is_diagram: False
---

Different values for rotation fields"""

        rewards = reward_front_matter(prompts=["prompt"], completions=[completion], claude_original=[claude_original_content])

        self.assertEqual(len(rewards), 1)
        # 0.5 base + 3 * 0.1 = 0.8
        self.assertAlmostEqual(rewards[0], 0.8, places=2)

    def test_invalid_frontmatter_format(self):
        """Test that invalid YAML frontmatter gets 0.0 reward."""
        completions = [
            """---
this is not: valid yaml
  because of: : bad formatting
---
content""",
            """---
primary_language: en
unclosed_string: "this is not closed
---""",
            """---
primary_language:
  nested: "should not be nested"
---""",
        ]

        rewards = reward_front_matter(prompts=["prompt"] * 3, completions=completions, claude_original=None)

        self.assertEqual(len(rewards), 3)
        for reward in rewards:
            self.assertEqual(reward, 0.0)

    def test_mixed_completions_with_claude(self):
        """Test mixed completions with claude_original comparisons."""
        claude_originals = [
            """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---
Content 1""",
            None,  # No claude_original for this one
            """---
primary_language: fr
is_rotation_valid: False
rotation_correction: 180
is_table: True
is_diagram: True
---
Content 3""",
        ]

        completions = [
            # Perfect match with first claude
            """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---
Model output 1""",
            # Valid frontmatter but no claude to compare
            """---
primary_language: de
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---
Model output 2""",
            # No frontmatter at all
            "Just plain text without frontmatter",
        ]

        rewards = reward_front_matter(prompts=["prompt"] * 3, completions=completions, claude_original=claude_originals)

        self.assertEqual(len(rewards), 3)
        self.assertAlmostEqual(rewards[0], 1.0, places=5)  # Perfect match
        self.assertEqual(rewards[1], 0.5)  # Valid but no claude
        self.assertEqual(rewards[2], 0.0)  # No frontmatter

    def test_list_format_completions(self):
        """Test handling of completions in list format."""
        completion_content = """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---
Content"""

        completions = [
            # List format (as from model output)
            [{"content": completion_content}],
            # String format
            completion_content,
            # Empty list
            [],
            # Invalid format
            [{}],
        ]

        rewards = reward_front_matter(prompts=["prompt"] * 4, completions=completions, claude_original=None)

        self.assertEqual(len(rewards), 4)
        self.assertEqual(rewards[0], 0.5)  # Valid from list
        self.assertEqual(rewards[1], 0.5)  # Valid from string
        self.assertEqual(rewards[2], 0.0)  # Empty list
        self.assertEqual(rewards[3], 0.0)  # Invalid list format

    def test_field_type_matching(self):
        """Test that field types are correctly compared."""
        claude_original = """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---"""

        completions = [
            # Correct types
            """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---""",
            # String instead of boolean (might still parse correctly)
            """---
primary_language: en
is_rotation_valid: "True"
rotation_correction: "0"
is_table: "False"
is_diagram: "False"
---""",
        ]

        rewards = reward_front_matter(prompts=["prompt"] * 2, completions=completions, claude_original=[claude_original] * 2)

        self.assertEqual(len(rewards), 2)
        # First should be perfect match
        self.assertAlmostEqual(rewards[0], 1.0, places=5)
        # Second: YAML parses string "True" as True boolean, so both should match
        self.assertAlmostEqual(rewards[1], 1.0, places=5)

    def test_none_values_in_fields(self):
        """Test handling of None values in frontmatter fields."""
        claude_original = """---
primary_language: en
is_rotation_valid: True
rotation_correction: 0
is_table: False
is_diagram: False
---"""

        # rotation_correction null will fail validation (must be 0, 90, 180, or 270)
        completion = """---
primary_language: en
is_rotation_valid: True
rotation_correction: null
is_table: False
is_diagram: False
---"""

        rewards = reward_front_matter(prompts=["prompt"], completions=[completion], claude_original=[claude_original])

        self.assertEqual(len(rewards), 1)
        # Should fail to parse due to invalid rotation_correction
        self.assertEqual(rewards[0], 0.0)


class TestIntegrationWithRealData(unittest.TestCase):
    """Integration tests with real bench data if available."""

    @unittest.skipUnless(os.path.exists("/home/ubuntu/olmocr/olmOCR-bench/bench_data"), "Real bench data not available")
    def test_with_real_bench_data(self):
        """Test with real bench data if available."""
        bench_data_folder = "/home/ubuntu/olmocr/olmOCR-bench/bench_data"

        dataset = OlmOCRBenchDataset(
            bench_data_folder=bench_data_folder,
            processor=None,
            max_samples=5,
            target_longest_image_dim=1024,
        )

        self.assertEqual(len(dataset), 5)

        # Test that we can iterate through the dataset
        for i in range(len(dataset)):
            item = dataset[i]
            if item is not None:  # Some PDFs might fail to render
                self.assertIn("prompt", item)
                self.assertIn("pdf_path", item)
                self.assertIn("jsonl_file", item)
                self.assertIn("test_ids", item)

                # Verify paths exist
                self.assertTrue(os.path.exists(item["pdf_path"]))
                self.assertTrue(os.path.exists(item["jsonl_file"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
