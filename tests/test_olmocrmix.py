# Test that prepare_olmocrmix.py and repackage_olmocrmix.py work correctly
# by packaging the sample dataset, unpacking it, and verifying contents are preserved

import os
import subprocess
import tempfile
from pathlib import Path


def test_repackage_and_prepare_olmocrmix():
    """Test that repackaging and preparing preserves the dataset contents exactly."""

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        sample_dataset = Path("tests/sample_dataset")

        # Step 1: Repackage the sample dataset into parquet + tarballs
        packaged_dir = temp_path / "packaged"
        packaged_dir.mkdir(parents=True, exist_ok=True)

        repackage_result = subprocess.run(
            [
                "python",
                "olmocr/data/repackage_olmocrmix.py",
                "--processed-dir",
                str(sample_dataset),
                "--subset",
                "test_subset",
                "--split",
                "test_split",
                "--output-dir",
                str(packaged_dir),
            ],
            capture_output=True,
            text=True,
        )

        assert repackage_result.returncode == 0, f"Repackage script failed with stderr: {repackage_result.stderr}\nstdout: {repackage_result.stdout}"

        # Verify the packaged output exists
        parquet_file = packaged_dir / "test_subset_test_split.parquet"
        assert parquet_file.exists(), f"Expected parquet file not found: {parquet_file}"

        # Step 2: Repackage the sample dataset into parquet + tarballs
        unpackaged_dir = temp_path / "unpackaged"

        prepare_result = subprocess.run(
            [
                "python",
                "olmocr/data/prepare_olmocrmix.py",
                "--dataset-path",
                str(packaged_dir),
                "--subset",
                "test_subset",
                "--split",
                "test_split",
                "--destination",
                str(unpackaged_dir),
            ],
            capture_output=True,
            text=True,
        )

        assert prepare_result.returncode == 0

        for root, _, files in os.walk(temp_path):
            for file_name in files:
                print(Path(root) / file_name)

        unpacked_processed = unpackaged_dir / "processed_test_subset_test_split"
        assert unpacked_processed.exists(), f"Unpacked processed dir missing: {unpacked_processed}"

        def relative_files(root: Path):
            return sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file())

        sample_files = relative_files(sample_dataset)
        unpacked_files = relative_files(unpacked_processed)
        assert sample_files == unpacked_files, "Mismatch in files between sample dataset and unpacked output"

        for relative_path in sample_files:
            sample_file = sample_dataset / relative_path
            unpacked_file = unpacked_processed / relative_path

            if relative_path.suffix == ".jsonl":
                # For JSONL files, compare as sets of lines (order doesn't matter)
                # Filter out empty lines
                sample_lines = set(line for line in sample_file.read_text().strip().split("\n") if line.strip())
                unpacked_lines = set(line for line in unpacked_file.read_text().strip().split("\n") if line.strip())
                assert sample_lines == unpacked_lines, f"JSONL file contents differ for {relative_path}"
            else:
                # For other files, compare as bytes
                sample_contents = sample_file.read_bytes()
                unpacked_contents = unpacked_file.read_bytes()
                assert sample_contents == unpacked_contents, f"File contents differ for {relative_path}"
