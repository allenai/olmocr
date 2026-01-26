import unittest
from unittest.mock import MagicMock, Mock

from botocore.exceptions import ClientError

from olmocr.cloud_utils import expand_s3_glob


class TestExpandS3Glob(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.s3_client = Mock()

    def _mock_paginator(self, contents):
        """Helper to mock S3 paginator responses."""
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": contents}]
        self.s3_client.get_paginator.return_value = paginator
        return paginator

    def test_wildcard_at_end_of_filename(self):
        """Test glob with wildcard at end: s3://bucket/path/prefix_*"""
        contents = [
            {"Key": "data/files/report_001.pdf", "ETag": '"abc123"'},
            {"Key": "data/files/report_002.pdf", "ETag": '"def456"'},
            {"Key": "data/files/other.pdf", "ETag": '"ghi789"'},
        ]
        self._mock_paginator(contents)

        result = expand_s3_glob(self.s3_client, "s3://test-bucket/data/files/report_*")

        # Should use prefix "data/files/report_" (everything before the *)
        self.s3_client.get_paginator.assert_called_once_with("list_objects_v2")
        call_args = self.s3_client.get_paginator.return_value.paginate.call_args
        self.assertEqual(call_args[1]["Prefix"], "data/files/report_")

        # Should match only report_* files
        self.assertEqual(len(result), 2)
        self.assertIn("s3://test-bucket/data/files/report_001.pdf", result)
        self.assertIn("s3://test-bucket/data/files/report_002.pdf", result)
        self.assertNotIn("s3://test-bucket/data/files/other.pdf", result)

    def test_wildcard_extension(self):
        """Test glob with wildcard extension: s3://bucket/path/*.pdf"""
        contents = [
            {"Key": "data/docs/file1.pdf", "ETag": '"abc123"'},
            {"Key": "data/docs/file2.pdf", "ETag": '"def456"'},
            {"Key": "data/docs/file3.txt", "ETag": '"ghi789"'},
        ]
        self._mock_paginator(contents)

        result = expand_s3_glob(self.s3_client, "s3://test-bucket/data/docs/*.pdf")

        # Should use prefix "data/docs/" (up to the *)
        call_args = self.s3_client.get_paginator.return_value.paginate.call_args
        self.assertEqual(call_args[1]["Prefix"], "data/docs/")

        # Should match only .pdf files
        self.assertEqual(len(result), 2)
        self.assertIn("s3://test-bucket/data/docs/file1.pdf", result)
        self.assertIn("s3://test-bucket/data/docs/file2.pdf", result)

    def test_wildcard_in_middle_of_path(self):
        """Test glob with wildcard in middle: s3://bucket/data/*/files/*.pdf"""
        contents = [
            {"Key": "data/2024/files/report.pdf", "ETag": '"abc123"'},
            {"Key": "data/2023/files/report.pdf", "ETag": '"def456"'},
            {"Key": "data/2024/other/report.pdf", "ETag": '"ghi789"'},
        ]
        self._mock_paginator(contents)

        result = expand_s3_glob(self.s3_client, "s3://test-bucket/data/*/files/*.pdf")

        # Should use prefix "data/" (up to the first *)
        call_args = self.s3_client.get_paginator.return_value.paginate.call_args
        self.assertEqual(call_args[1]["Prefix"], "data/")

        # Should match files in any year's files/ subdirectory
        self.assertEqual(len(result), 2)
        self.assertIn("s3://test-bucket/data/2024/files/report.pdf", result)
        self.assertIn("s3://test-bucket/data/2023/files/report.pdf", result)
        self.assertNotIn("s3://test-bucket/data/2024/other/report.pdf", result)

    def test_wildcard_at_root(self):
        """Test glob with wildcard at root: s3://bucket/*.pdf"""
        contents = [
            {"Key": "file1.pdf", "ETag": '"abc123"'},
            {"Key": "file2.pdf", "ETag": '"def456"'},
            {"Key": "subdir/file3.pdf", "ETag": '"ghi789"'},
        ]
        self._mock_paginator(contents)

        result = expand_s3_glob(self.s3_client, "s3://test-bucket/*.pdf")

        # Should use empty prefix
        call_args = self.s3_client.get_paginator.return_value.paginate.call_args
        self.assertEqual(call_args[1]["Prefix"], "")

        # fnmatch *.pdf matches all .pdf files including in subdirs (fnmatch * matches /)
        self.assertEqual(len(result), 3)
        self.assertIn("s3://test-bucket/file1.pdf", result)
        self.assertIn("s3://test-bucket/file2.pdf", result)
        self.assertIn("s3://test-bucket/subdir/file3.pdf", result)

    def test_bracket_wildcard(self):
        """Test glob with bracket wildcard: s3://bucket/data/file[123].pdf"""
        contents = [
            {"Key": "data/file1.pdf", "ETag": '"abc123"'},
            {"Key": "data/file2.pdf", "ETag": '"def456"'},
            {"Key": "data/file4.pdf", "ETag": '"ghi789"'},
        ]
        self._mock_paginator(contents)

        result = expand_s3_glob(self.s3_client, "s3://test-bucket/data/file[123].pdf")

        # Should use prefix "data/file" (up to the [)
        call_args = self.s3_client.get_paginator.return_value.paginate.call_args
        self.assertEqual(call_args[1]["Prefix"], "data/file")

        # [123] matches 1, 2, or 3
        self.assertEqual(len(result), 2)
        self.assertIn("s3://test-bucket/data/file1.pdf", result)
        self.assertIn("s3://test-bucket/data/file2.pdf", result)
        self.assertNotIn("s3://test-bucket/data/file4.pdf", result)

    def test_real_world_worker_pattern(self):
        """Test real-world pattern: s3://bucket/path/prefix_worker62_*"""
        contents = [
            {"Key": "jakep/dolma/olmo-crawled-pdfs_worker62_001.tar", "ETag": '"abc123"'},
            {"Key": "jakep/dolma/olmo-crawled-pdfs_worker62_002.tar", "ETag": '"def456"'},
            {"Key": "jakep/dolma/olmo-crawled-pdfs_worker63_001.tar", "ETag": '"ghi789"'},
        ]
        self._mock_paginator(contents)

        result = expand_s3_glob(self.s3_client, "s3://ai2-oe-data/jakep/dolma/olmo-crawled-pdfs_worker62_*")

        # Should use prefix up to the * (the entire fixed part)
        call_args = self.s3_client.get_paginator.return_value.paginate.call_args
        self.assertEqual(call_args[1]["Prefix"], "jakep/dolma/olmo-crawled-pdfs_worker62_")

        # Should only match worker62 files
        self.assertEqual(len(result), 2)
        self.assertIn("s3://ai2-oe-data/jakep/dolma/olmo-crawled-pdfs_worker62_001.tar", result)
        self.assertIn("s3://ai2-oe-data/jakep/dolma/olmo-crawled-pdfs_worker62_002.tar", result)
        self.assertNotIn("s3://ai2-oe-data/jakep/dolma/olmo-crawled-pdfs_worker63_001.tar", result)

    def test_no_wildcard_single_file(self):
        """Test path without wildcard returns single file."""
        self.s3_client.head_object.return_value = {"ContentType": "application/pdf", "ETag": '"abc123"'}

        result = expand_s3_glob(self.s3_client, "s3://test-bucket/data/file.pdf")

        self.s3_client.head_object.assert_called_once_with(Bucket="test-bucket", Key="data/file.pdf")
        self.assertEqual(result, {"s3://test-bucket/data/file.pdf": "abc123"})

    def test_no_wildcard_directory_error(self):
        """Test that bare directory path raises helpful error."""
        self.s3_client.head_object.return_value = {"ContentType": "application/x-directory", "ETag": '"abc123"'}

        with self.assertRaises(ValueError) as ctx:
            expand_s3_glob(self.s3_client, "s3://test-bucket/data/folder")

        self.assertIn("appears to be a folder", str(ctx.exception))
        self.assertIn("*.pdf", str(ctx.exception))

    def test_no_wildcard_not_found_but_is_folder(self):
        """Test 404 on path that's actually a folder with contents."""
        self.s3_client.head_object.side_effect = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        # Simulate folder with contents
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": [{"Key": "data/folder/file.pdf"}]}]
        self.s3_client.get_paginator.return_value = paginator

        with self.assertRaises(ValueError) as ctx:
            expand_s3_glob(self.s3_client, "s3://test-bucket/data/folder")

        self.assertIn("appears to be a folder", str(ctx.exception))

    def test_no_wildcard_not_found(self):
        """Test 404 on path that doesn't exist."""
        self.s3_client.head_object.side_effect = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        # No contents under this prefix
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        self.s3_client.get_paginator.return_value = paginator

        with self.assertRaises(ValueError) as ctx:
            expand_s3_glob(self.s3_client, "s3://test-bucket/data/nonexistent.pdf")

        self.assertIn("No object or prefix found", str(ctx.exception))

    def test_invalid_scheme(self):
        """Test that non-s3 paths raise error."""
        with self.assertRaises(ValueError) as ctx:
            expand_s3_glob(self.s3_client, "gs://bucket/path/*.pdf")

        self.assertIn("must start with s3://", str(ctx.exception))

    def test_etag_quotes_stripped(self):
        """Test that ETags have quotes stripped correctly."""
        contents = [
            {"Key": "data/file.pdf", "ETag": '"abc123"'},
        ]
        self._mock_paginator(contents)

        result = expand_s3_glob(self.s3_client, "s3://test-bucket/data/*.pdf")

        # ETag should not have quotes
        self.assertEqual(result["s3://test-bucket/data/file.pdf"], "abc123")

    def test_empty_results(self):
        """Test glob that matches nothing returns empty dict."""
        self._mock_paginator([])

        result = expand_s3_glob(self.s3_client, "s3://test-bucket/data/*.pdf")

        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
