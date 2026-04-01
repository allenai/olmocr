#!/usr/bin/env python3
"""Create a reproducible subset of the olmOCR benchmark dataset.

The script samples PDFs proportionally across category folders, copies the selected
PDFs into a new output directory, and rewrites JSONL metadata files to only include
rows referencing sampled PDFs.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path


def parse_ratio(raw_ratio: float) -> float:
    """Parse ratio from either fraction (0.1) or percent style (10)."""
    if raw_ratio <= 0:
        raise ValueError("ratio must be > 0")
    if raw_ratio <= 1:
        return raw_ratio
    if raw_ratio <= 100:
        return raw_ratio / 100.0
    raise ValueError("ratio must be in (0, 1] or (0, 100]")


def get_category_pdfs(pdfs_root: Path) -> dict[str, list[str]]:
    """Return a mapping from category name to sorted relative PDF paths."""
    categories: dict[str, list[str]] = {}
    for category_dir in sorted(pdfs_root.iterdir()):
        if not category_dir.is_dir():
            continue
        pdfs = sorted(p.name for p in category_dir.glob("*.pdf"))
        categories[category_dir.name] = [f"{category_dir.name}/{pdf_name}" for pdf_name in pdfs]
    if not categories:
        raise ValueError(f"No category folders found under: {pdfs_root}")
    return categories


def allocate_counts(
    category_counts: dict[str, int],
    ratio: float,
    require_all_categories: bool,
) -> dict[str, int]:
    """Allocate sample counts per category while preserving proportions."""
    total = sum(category_counts.values())
    if total == 0:
        raise ValueError("No PDFs found to sample from")

    target_total = max(1, round(total * ratio))
    min_per_category = {
        category: 1 if require_all_categories and count > 0 else 0
        for category, count in category_counts.items()
    }

    min_required = sum(min_per_category.values())
    if target_total < min_required:
        raise ValueError(
            f"ratio too small for --require-all-categories: target {target_total} PDFs "
            f"but need at least {min_required} (one per category)"
        )

    exact = {category: category_counts[category] * ratio for category in category_counts}
    allocation = {
        category: max(min_per_category[category], math.floor(exact[category]))
        for category in category_counts
    }

    current = sum(allocation.values())
    if current < target_total:
        remainder_order = sorted(
            category_counts,
            key=lambda c: (exact[c] - math.floor(exact[c]), -category_counts[c], c),
            reverse=True,
        )
        while current < target_total:
            progressed = False
            for category in remainder_order:
                if allocation[category] < category_counts[category]:
                    allocation[category] += 1
                    current += 1
                    progressed = True
                    if current == target_total:
                        break
            if not progressed:
                break

    if current > target_total:
        remainder_order = sorted(
            category_counts,
            key=lambda c: (exact[c] - math.floor(exact[c]), category_counts[c], c),
        )
        while current > target_total:
            progressed = False
            for category in remainder_order:
                if allocation[category] > min_per_category[category]:
                    allocation[category] -= 1
                    current -= 1
                    progressed = True
                    if current == target_total:
                        break
            if not progressed:
                break

    if sum(allocation.values()) != target_total:
        raise RuntimeError("Could not satisfy target allocation constraints")

    return allocation


def sample_selected_pdfs(
    category_to_pdfs: dict[str, list[str]],
    allocation: dict[str, int],
    seed: int,
) -> set[str]:
    """Sample PDFs from each category using a deterministic RNG."""
    rng = random.Random(seed)
    selected: set[str] = set()

    for category, pdfs in sorted(category_to_pdfs.items()):
        k = allocation[category]
        if k > len(pdfs):
            raise ValueError(f"Requested {k} samples from {category}, but only {len(pdfs)} PDFs exist")
        selected.update(rng.sample(pdfs, k))

    return selected


def copy_selected_pdfs(input_pdfs_root: Path, output_pdfs_root: Path, selected_pdfs: set[str]) -> None:
    """Copy sampled PDFs into output directory preserving category folders."""
    for rel_pdf in sorted(selected_pdfs):
        src = input_pdfs_root / rel_pdf
        dst = output_pdfs_root / rel_pdf
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def filter_jsonl_files(
    input_bench_dir: Path,
    output_bench_dir: Path,
    selected_pdfs: set[str],
) -> tuple[int, int, dict[str, dict[str, int]]]:
    """Filter JSONL files so they only contain rows from selected PDFs."""
    total_in = 0
    total_out = 0
    jsonl_stats: dict[str, dict[str, int]] = {}

    output_bench_dir.mkdir(parents=True, exist_ok=True)

    for jsonl_file in sorted(input_bench_dir.glob("*.jsonl")):
        output_file = output_bench_dir / jsonl_file.name
        file_in = 0
        kept = 0

        with jsonl_file.open("r", encoding="utf-8") as src, output_file.open("w", encoding="utf-8") as dst:
            for line in src:
                raw = line.strip()
                if not raw:
                    continue
                file_in += 1
                total_in += 1
                record = json.loads(raw)
                pdf_rel = record.get("pdf")
                if pdf_rel in selected_pdfs:
                    dst.write(json.dumps(record, ensure_ascii=False) + "\n")
                    kept += 1
                    total_out += 1

        print(f"Filtered {jsonl_file.name}: kept {kept} records")
        jsonl_stats[jsonl_file.name] = {"input_records": file_in, "kept_records": kept}

    # Replace derived values with exact per-file counts.
    for jsonl_name, stats in jsonl_stats.items():
        stats["dropped_records"] = stats["input_records"] - stats["kept_records"]

    return total_in, total_out, jsonl_stats


def write_manifest(
    output_dir: Path,
    input_bench_dir: Path,
    ratio: float,
    seed: int,
    require_all_categories: bool,
    category_counts: dict[str, int],
    allocation: dict[str, int],
    selected_pdfs: set[str],
    jsonl_stats: dict[str, dict[str, int]],
) -> Path:
    """Write a JSON manifest that records subset composition and provenance."""
    manifest_path = output_dir / "subset_manifest.json"

    category_entries = {}
    for category in sorted(category_counts):
        input_count = category_counts[category]
        sampled_count = allocation[category]
        category_entries[category] = {
            "input_pdfs": input_count,
            "sampled_pdfs": sampled_count,
            "sample_ratio": (sampled_count / input_count) if input_count else 0.0,
        }

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_bench_dir": str(input_bench_dir),
        "subset_ratio_requested": ratio,
        "seed": seed,
        "require_all_categories": require_all_categories,
        "totals": {
            "input_pdfs": sum(category_counts.values()),
            "sampled_pdfs": len(selected_pdfs),
            "input_tests": sum(stats["input_records"] for stats in jsonl_stats.values()),
            "sampled_tests": sum(stats["kept_records"] for stats in jsonl_stats.values()),
        },
        "categories": category_entries,
        "jsonl_files": {name: jsonl_stats[name] for name in sorted(jsonl_stats)},
        "selected_pdfs": sorted(selected_pdfs),
    }

    with manifest_path.open("w", encoding="utf-8") as out:
        json.dump(manifest, out, indent=2, ensure_ascii=False)
        out.write("\n")

    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a random but reproducible subset of the olmOCR benchmark while "
            "preserving per-category PDF ratios"
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Path to benchmark bench_data directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output subset directory to create",
    )
    parser.add_argument(
        "--ratio",
        type=float,
        required=True,
        help="Subset ratio as fraction (0.1) or percent (10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=14,
        help="Random seed for reproducibility (default: 14)",
    )
    parser.add_argument(
        "--require-all-categories",
        action="store_true",
        help="Require at least one PDF from every category",
    )
    args = parser.parse_args()

    ratio = parse_ratio(args.ratio)
    input_bench_dir = args.input_dir
    input_pdfs_root = input_bench_dir / "pdfs"
    output_bench_dir = args.output_dir / "bench_data"
    output_pdfs_root = output_bench_dir / "pdfs"

    if not input_bench_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_bench_dir}")
    if not input_pdfs_root.exists():
        raise FileNotFoundError(f"Input PDF directory not found: {input_pdfs_root}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {args.output_dir}")

    category_to_pdfs = get_category_pdfs(input_pdfs_root)
    category_counts = {category: len(pdfs) for category, pdfs in category_to_pdfs.items()}
    allocation = allocate_counts(category_counts, ratio, args.require_all_categories)
    selected_pdfs = sample_selected_pdfs(category_to_pdfs, allocation, args.seed)

    copy_selected_pdfs(input_pdfs_root, output_pdfs_root, selected_pdfs)
    total_in, total_out, jsonl_stats = filter_jsonl_files(input_bench_dir, output_bench_dir, selected_pdfs)
    manifest_path = write_manifest(
        output_dir=args.output_dir,
        input_bench_dir=input_bench_dir,
        ratio=ratio,
        seed=args.seed,
        require_all_categories=args.require_all_categories,
        category_counts=category_counts,
        allocation=allocation,
        selected_pdfs=selected_pdfs,
        jsonl_stats=jsonl_stats,
    )

    print("\nSubset creation complete")
    print(f"Ratio requested: {ratio:.4f}")
    print(f"Seed: {args.seed}")
    print(f"Input PDFs: {sum(category_counts.values())}")
    print(f"Output PDFs: {len(selected_pdfs)}")
    print(f"Input tests: {total_in}")
    print(f"Output tests: {total_out}")
    print(f"Manifest: {manifest_path}")
    print("Per-category PDF counts:")
    for category in sorted(category_counts):
        print(f"  {category}: {allocation[category]} / {category_counts[category]}")


if __name__ == "__main__":
    main()
