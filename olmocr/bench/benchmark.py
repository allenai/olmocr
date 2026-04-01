#!/usr/bin/env python3
"""
This script runs olmocr bench.
It will take as an argument a folder, and scan it for .jsonl files which contain the various rules and properties that we will check.
It will then validate the JSON files to make sure they are all valid.
Then, each other folder in there (besides /pdfs) represents a pipeline tool that we will evaluate.
We will validate that each one of those contains at least one .md file (or repeated generations, e.g. _pg{page}_repeat{repeat}.md)
corresponding to its parse for every .pdf in the /pdfs folder.
Then, we will read each one, and check if they pass against all the rules.
If a rule fails on some of the repeats, a short explanation is printed.
The final score is the average of per-JSONL file scores, where each JSONL file's score is the proportion of tests from that file that pass.
Statistical analysis including bootstrap confidence intervals are provided for the results.
Pairwise permutation tests are conducted between specific candidate pairs.
"""

import argparse
import glob
import json
import os
import random
import re
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

from pypdf import PdfReader
from tqdm import tqdm

from .report import generate_html_report
from .tests import BaselineTest, BasePDFTest, load_tests, save_tests
from .utils import calculate_bootstrap_ci


def evaluate_candidate(
    candidate_folder: str, all_tests: List[BasePDFTest], pdf_basenames: List[str], force: bool = False
) -> Tuple[float, int, List[str], List[str], Dict[str, List[float]], List[float], Dict[str, Dict[int, List[Tuple[BasePDFTest, bool, str]]]]]:
    """
    For the candidate folder (pipeline tool output), validate that it contains at least one .md file
    (i.e. repeated generations like _pg{page}_repeat{repeat}.md) for every PDF in the pdf folder.
    Then, run each rule against all corresponding .md files concurrently and average the results.

    Returns a tuple:
      (overall_score, total_tests, candidate_errors, test_failures, test_type_breakdown, all_test_scores, test_results)

      - overall_score: Average fraction of tests passed (averaged over repeats and tests).
        Note: This is now updated at reporting time to be the average of per-JSONL file scores.
      - total_tests: Total number of tests evaluated.
      - candidate_errors: List of candidate errors (e.g. missing files).
      - test_failures: List of failure messages for tests not passing on all repeats.
      - test_type_breakdown: Dictionary mapping test type to list of average pass ratios for tests of that type.
      - all_test_scores: List of all individual test scores (used for bootstrapping).
      - test_results: Dictionary mapping PDF name to dictionary mapping page number to list of (test, passed, explanation) tuples.
    """
    candidate_errors = []
    test_failures = []
    test_type_breakdown = {}  # key: test type, value: list of average pass ratios
    all_test_scores = []  # Store all individual test scores for bootstrapping
    test_results = {}  # Store detailed test results for reporting
    candidate_name = os.path.basename(candidate_folder)

    # Map each PDF to its corresponding MD repeats (e.g., doc1_pg1_repeat1.md, doc1_pg2_repeat2.md, etc.)
    pdf_to_md_files = {}
    all_files = list(glob.glob(os.path.join(candidate_folder, "**/*.md"), recursive=True))

    for pdf_name in pdf_basenames:
        md_base = os.path.splitext(pdf_name)[0]
        md_regex = re.compile(rf"^{re.escape(md_base)}_pg\d+_repeat\d+\.md$")
        md_files = [f for f in all_files if md_regex.match(os.path.relpath(f, candidate_folder))]

        if not md_files and not force:
            candidate_errors.append(
                f"Candidate '{candidate_name}' is missing MD repeats for {pdf_name} " f"(expected files matching {md_base}_pg{{page}}_repeat*.md)."
            )
        else:
            pdf_to_md_files[pdf_name] = md_files

    if candidate_errors:
        return (0.0, len(all_tests), candidate_errors, test_failures, test_type_breakdown, all_test_scores, test_results)

    # Define an inner function to evaluate a single test
    def process_test(test: BasePDFTest) -> Tuple[float, str, str, List[str], Tuple[bool, str]]:
        local_errors = []
        test_failure = None
        pdf_name = test.pdf

        # Initialize the test_results structure if needed
        if pdf_name not in test_results:
            test_results[pdf_name] = {}
        if test.page not in test_results[pdf_name]:
            test_results[pdf_name][test.page] = []

        md_base = os.path.splitext(pdf_name)[0]
        md_files = pdf_to_md_files.get(pdf_name, [])
        # Filter MD files for the specific page corresponding to the test
        page_md_files = [f for f in md_files if re.search(rf"_pg{test.page}_", os.path.basename(f))]
        if not page_md_files:
            local_errors.append(
                f"Candidate '{candidate_name}' is missing MD repeats for {pdf_name} page {test.page} "
                f"(expected files matching {md_base}_pg{test.page}_repeat*.md)."
            )
            test_results[pdf_name][test.page].append((test, False, "Missing MD files"))
            return (0.0, None, test.type, local_errors, (False, "Missing MD files"))

        repeat_passes = 0
        num_repeats = 0
        explanations = []
        for md_path in page_md_files:
            num_repeats += 1
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    md_content = f.read()
            except Exception as e:
                local_errors.append(f"Error reading {md_path}: {e}")
                continue

            try:
                passed, explanation = test.run(md_content)
                if passed:
                    repeat_passes += 1
                else:
                    explanations.append(explanation)
            except Exception as e:
                local_errors.append(f"Error running test {test.id} on {md_path}: {e}")
                explanations.append(str(e))

        test_avg = repeat_passes / num_repeats if num_repeats > 0 else 0.0
        final_passed = test_avg > 0.5  # Consider test passed if majority of repeats pass
        final_explanation = explanations[0] if explanations else "All repeats passed"

        # Store the test result for reporting
        test_results[pdf_name][test.page].append((test, final_passed, final_explanation))

        if test_avg < 1.0:
            test_failure = (
                f"Test {test.id} on {md_base} page {test.page} average pass ratio: {test_avg:.3f} "
                f"({repeat_passes}/{num_repeats} repeats passed). Ex: {explanations[0] if explanations else 'No explanation'}"
            )
        return (test_avg, test_failure, test.type, local_errors, (final_passed, final_explanation))

    total_test_score = 0.0
    futures = []
    # Use a thread pool to evaluate each test concurrently.
    with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 1, 64)) as executor:
        futures = [executor.submit(process_test, test) for test in all_tests]
        # tqdm progress bar for this candidate's tests
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Evaluating tests for {candidate_name}", unit="test"):
            test_avg, test_failure, test_type, errors, _ = future.result()
            all_test_scores.append(test_avg)
            total_test_score += test_avg
            if test_failure:
                test_failures.append(test_failure)
            if test_type not in test_type_breakdown:
                test_type_breakdown[test_type] = []
            test_type_breakdown[test_type].append(test_avg)
            local_errors = errors
            if local_errors:
                candidate_errors.extend(local_errors)

    overall_score = total_test_score / len(all_tests) if all_tests else 0.0
    return (overall_score, len(all_tests), candidate_errors, test_failures, test_type_breakdown, all_test_scores, test_results)


def main():
    parser = argparse.ArgumentParser(description="Run OLMOCR Bench.")
    parser.add_argument(
        "--dir",
        default=os.path.join(os.path.dirname(__file__), "sample_data"),
        help="Path to the folder containing .jsonl files, /pdfs folder, and pipeline tool subfolders.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run benchmark even if some files are missing",
    )
    parser.add_argument("--candidate", type=str, default=None, help="Run test only for a single candidate")
    parser.add_argument("--skip_baseline", action="store_true", help="Skip running baseline tests (ex. that check that basic content is present on each page)")
    parser.add_argument(
        "--bootstrap_samples",
        type=int,
        default=1000,
        help="Number of bootstrap samples for confidence interval calculation (default: 1000).",
    )
    parser.add_argument(
        "--confidence_level",
        type=float,
        default=0.95,
        help="Confidence level for interval calculation (default: 0.95 for 95% CI).",
    )
    # New arguments
    parser.add_argument("--sample", type=int, default=None, help="Randomly sample N tests to run instead of all tests.")
    parser.add_argument("--test_report", type=str, default=None, help="Generate an HTML report of test results. Provide a filename (e.g., results.html).")
    parser.add_argument("--json_summary", type=str, default=None, help="Generate a JSON summary of test results. Provide a filename (e.g., summary.json).")
    parser.add_argument(
        "--output_failed", type=str, default=None, help="Output a JSONL file containing tests that failed across all candidates. Provide a filename."
    )
    parser.add_argument("--max_reports", type=int, default=None, help="Limit the HTML report to at most N unique PDFs per .jsonl file.")
    args = parser.parse_args()

    input_folder = args.dir if os.path.isdir(args.dir) else os.path.dirname(args.dir)
    n_bootstrap = args.bootstrap_samples
    ci_level = args.confidence_level
    pdf_folder = os.path.join(input_folder, "pdfs")

    if not os.path.exists(pdf_folder):
        print("Error: /pdfs folder must exist in your data directory.", file=sys.stderr)
        sys.exit(1)

    all_pdf_files = list(glob.glob(os.path.join(pdf_folder, "**/*.pdf"), recursive=True))

    if not all_pdf_files:
        print(f"Error: No PDF files found in {pdf_folder}", file=sys.stderr)
        sys.exit(1)

    pdf_basenames = [os.path.relpath(p, pdf_folder) for p in all_pdf_files]

    if os.path.isfile(args.dir):
        jsonl_files = [args.dir]
    else:
        jsonl_files = glob.glob(os.path.join(input_folder, "*.jsonl"))

    if not jsonl_files:
        print(f"Error: No .jsonl files found in {input_folder}.", file=sys.stderr)
        sys.exit(1)

    all_tests = []
    test_to_jsonl = {}  # Map test IDs to their source jsonl files
    for jsonl_path in jsonl_files:
        jsonl_basename = os.path.basename(jsonl_path)
        tests = load_tests(jsonl_path)
        for test in tests:
            test_to_jsonl[test.id] = jsonl_basename
        all_tests.extend(tests)

    if not all_tests:
        print("No valid tests found. Exiting.", file=sys.stderr)
        sys.exit(1)

    # When a single .jsonl file is passed, only consider PDFs referenced by its tests
    if os.path.isfile(args.dir):
        referenced_pdfs = {t.pdf for t in all_tests}
        pdf_basenames = [p for p in pdf_basenames if p in referenced_pdfs]

    for pdf in pdf_basenames:
        if not any(t.type == "baseline" for t in all_tests if t.pdf == pdf):
            all_tests.append(BaselineTest(id=f"{pdf}_baseline", pdf=pdf, page=1, type="baseline"))
            test_to_jsonl[all_tests[-1].id] = "baseline"

    for pdf in pdf_basenames:
        pdf_doc = PdfReader(os.path.join(pdf_folder, pdf))
        for page in range(1, len(pdf_doc.pages) + 1):
            if not any(test for test in all_tests if test.pdf == pdf and test.page == page) and not args.force:
                print(f"No dataset entry found for pdf {pdf} page {page}")
                sys.exit(1)

    if args.skip_baseline:
        all_tests = [test for test in all_tests if test.type != "baseline"]

    # Sample tests if requested
    if args.sample is not None and args.sample > 0:
        if args.sample >= len(all_tests):
            print(f"Sample size {args.sample} is greater than or equal to the total number of tests ({len(all_tests)}). Using all tests.")
        else:
            print(f"Randomly sampling {args.sample} tests out of {len(all_tests)} total tests.")
            all_tests = random.sample(all_tests, args.sample)

    candidate_folders = []
    for entry in os.listdir(input_folder):
        full_path = os.path.join(input_folder, entry)
        if args.candidate is not None:
            if entry == args.candidate:
                candidate_folders.append(full_path)
        else:
            if os.path.isdir(full_path) and entry != "pdfs":
                candidate_folders.append(full_path)

    if not candidate_folders:
        print("Error: No candidate pipeline folders found (subdirectories besides 'pdfs').", file=sys.stderr)
        sys.exit(1)

    candidate_folders.sort()

    summary = []
    test_results_by_candidate = {}
    print("\nRunning tests for each candidate:")
    # Process candidates sequentially so that each candidate's progress bar is distinct.
    for candidate in candidate_folders:
        candidate_name = os.path.basename(candidate)
        print(f"\nEvaluating candidate: {candidate_name}")
        overall_score, total_tests, candidate_errors, test_failures, test_type_breakdown, all_test_scores, test_results = evaluate_candidate(
            candidate, all_tests, pdf_basenames, args.force
        )

        # Always store test results for displaying jsonl file groupings
        test_results_by_candidate[candidate_name] = test_results

        # Group results by jsonl file for more accurate CI calculation
        jsonl_results = {}
        jsonl_scores = []  # List to store scores by jsonl file for CI calculation
        jsonl_file_sizes = []  # List to store the number of tests per jsonl file

        for test in all_tests:
            # Get the jsonl file this test came from
            jsonl_file = test_to_jsonl.get(test.id, "unknown")

            if jsonl_file not in jsonl_results:
                jsonl_results[jsonl_file] = {"total": 0, "passed": 0, "scores": []}

            jsonl_results[jsonl_file]["total"] += 1

            # Get the test result for this candidate if it exists
            if not candidate_errors and hasattr(test, "pdf") and hasattr(test, "page"):
                pdf_name = test.pdf
                page = test.page
                if pdf_name in test_results and page in test_results.get(pdf_name, {}):
                    for t, passed, _ in test_results[pdf_name][page]:
                        if t.id == test.id:
                            # Store the test score in its jsonl group
                            result_score = 1.0 if passed else 0.0
                            jsonl_results[jsonl_file]["scores"].append(result_score)
                            if passed:
                                jsonl_results[jsonl_file]["passed"] += 1
                            break

        # Gather all the scores by jsonl file for CI calculation
        for jsonl_file, results in jsonl_results.items():
            if results["scores"]:
                jsonl_file_sizes.append(len(results["scores"]))
                jsonl_scores.extend(results["scores"])

        # Calculate CI using the updated function with splits
        if jsonl_scores:
            ci = calculate_bootstrap_ci(jsonl_scores, n_bootstrap=n_bootstrap, ci_level=ci_level, splits=jsonl_file_sizes)
        else:
            ci = (0.0, 0.0)
        summary.append((candidate_name, overall_score, total_tests, candidate_errors, test_failures, test_type_breakdown, ci, all_test_scores))
        print(f"\nCandidate: {candidate_name}")
        if candidate_errors:
            for err in candidate_errors:
                print(f"  [ERROR] {err}")
        else:
            if test_failures:
                for fail in test_failures:
                    print(f"  [FAIL] {fail}")
            # Calculate and show the per-category average score
            jsonl_pass_rates = []
            for _, results in jsonl_results.items():
                if results["total"] > 0:
                    pass_rate = results["passed"] / results["total"]
                    jsonl_pass_rates.append(pass_rate)

            per_category_score = sum(jsonl_pass_rates) / len(jsonl_pass_rates) if jsonl_pass_rates else 0.0
            print(f"  Average Score: {per_category_score * 100:.1f}% (95% CI: [{ci[0] * 100:.1f}%, {ci[1] * 100:.1f}%]) over {total_tests} tests.")

    print("\n" + "=" * 60)
    print("Final Summary with 95% Confidence Intervals:")
    for idx, (candidate_name, _, total_tests, candidate_errors, _, test_type_breakdown, ci, _) in enumerate(summary):
        # Group results by jsonl file
        jsonl_results = {}
        for test in all_tests:
            # Get the jsonl file this test came from
            jsonl_file = test_to_jsonl.get(test.id, "unknown")

            if jsonl_file not in jsonl_results:
                jsonl_results[jsonl_file] = {"total": 0, "passed": 0}

            jsonl_results[jsonl_file]["total"] += 1

            # Get the test result for this candidate if it exists
            test_result = None
            if not candidate_errors and hasattr(test, "pdf") and hasattr(test, "page"):
                pdf_name = test.pdf
                page = test.page
                if pdf_name in test_results_by_candidate.get(candidate_name, {}) and page in test_results_by_candidate[candidate_name].get(pdf_name, {}):
                    for t, passed, _ in test_results_by_candidate[candidate_name][pdf_name][page]:
                        if t.id == test.id:
                            test_result = passed
                            break

            if test_result:
                jsonl_results[jsonl_file]["passed"] += 1

        # Calculate new overall score as average of per-JSONL pass rates
        jsonl_pass_rates = []
        for jsonl_file, results in jsonl_results.items():
            if results["total"] > 0:
                pass_rate = results["passed"] / results["total"]
                jsonl_pass_rates.append(pass_rate)

        # New overall score is average of per-JSONL pass rates
        new_overall_score = sum(jsonl_pass_rates) / len(jsonl_pass_rates) if jsonl_pass_rates else 0.0

        # Update the overall_score in the summary list for later use (e.g., in permutation tests)
        summary[idx] = (candidate_name, new_overall_score, total_tests, candidate_errors, summary[idx][4], test_type_breakdown, ci, summary[idx][7])

        if candidate_errors:
            status = "FAILED (errors)"
            ciw_str = ""
        else:
            status = f"{new_overall_score * 100:0.1f}%"
            # Use the CI that was calculated with proper category-based bootstrap
            half_width = ((ci[1] - ci[0]) / 2) * 100
            ciw_str = f"± {half_width:0.1f}%"
        print(f"{candidate_name:20s} : Average Score: {status} {ciw_str} (average of per-JSONL scores)")

        # Sort the test types alphabetically
        for ttype in sorted(test_type_breakdown.keys()):
            scores = test_type_breakdown[ttype]
            avg = sum(scores) / len(scores) * 100 if scores else 0.0
            print(f"    {ttype:8s}: {avg:0.1f}% average pass rate over {len(scores)} tests")

        print("\n    Results by JSONL file:")
        for jsonl_file, results in sorted(jsonl_results.items()):
            if results["total"] > 0:
                pass_rate = (results["passed"] / results["total"]) * 100
                print(f"        {jsonl_file:30s}: {pass_rate:0.1f}% ({results['passed']}/{results['total']} tests)")
        print("")

    # Generate HTML report if requested
    if args.test_report:
        generate_html_report(test_results_by_candidate, pdf_folder, args.test_report, max_reports=args.max_reports, test_to_jsonl=test_to_jsonl)

    # Output tests that failed across all candidates if requested
    if args.output_failed:
        # Identify tests that failed across all candidates
        all_failed_tests = []
        valid_candidates = [c for c in summary if not c[3]]  # Skip candidates with errors

        for test in all_tests:
            # Track whether this test has any results
            has_results = False
            any_passed = False

            for candidate_name, _, _, _, _, _, _, _ in valid_candidates:
                # Get the test result for this candidate
                test_result = None
                if hasattr(test, "pdf") and hasattr(test, "page"):
                    pdf_name = test.pdf
                    page = test.page
                    if pdf_name in test_results_by_candidate.get(candidate_name, {}) and page in test_results_by_candidate[candidate_name].get(pdf_name, {}):
                        for t, passed, explanation in test_results_by_candidate[candidate_name][pdf_name][page]:
                            if t.id == test.id:
                                has_results = True
                                test_result = passed
                                if passed:
                                    any_passed = True
                                break

            # If we have results for this test and it never passed for any candidate, add it to the failed list
            if has_results and not any_passed:
                # Add to the list
                all_failed_tests.append(test)

        # If we have any failed tests, write them to the specified JSONL file
        output_path = os.path.join(input_folder, args.output_failed) if not os.path.isabs(args.output_failed) else args.output_failed

        if all_failed_tests:
            save_tests(all_failed_tests, output_path)

            print(f"\nOutput {len(all_failed_tests)} tests that failed across all candidates to {output_path}")
        else:
            print("\nNo tests failed across all candidates. No output file created.")

    if args.json_summary:
        summary_entries = []
        for candidate_name, overall_score, total_tests, candidate_errors, test_failures, test_type_breakdown, ci, all_test_scores in summary:
            type_stats = {}
            for ttype, scores in test_type_breakdown.items():
                count = len(scores)
                avg_pass_rate = sum(scores) / count if count else 0.0
                type_stats[ttype] = {"average_pass_rate": avg_pass_rate, "num_tests": count}

            jsonl_results = {}
            for test in all_tests:
                jsonl_file = test_to_jsonl.get(test.id, "unknown")
                if jsonl_file not in jsonl_results:
                    jsonl_results[jsonl_file] = {"total": 0, "passed": 0}

                jsonl_results[jsonl_file]["total"] += 1
                test_result = None
                if not candidate_errors and hasattr(test, "pdf") and hasattr(test, "page"):
                    pdf_name = test.pdf
                    page = test.page
                    if pdf_name in test_results_by_candidate.get(candidate_name, {}) and page in test_results_by_candidate[candidate_name].get(pdf_name, {}):
                        for t, passed, _ in test_results_by_candidate[candidate_name][pdf_name][page]:
                            if t.id == test.id:
                                test_result = passed
                                break

                if test_result:
                    jsonl_results[jsonl_file]["passed"] += 1

            jsonl_stats = {
                jsonl_file: {
                    "pass_rate": (results["passed"] / results["total"]) if results["total"] else 0.0,
                    "passed": results["passed"],
                    "total": results["total"],
                }
                for jsonl_file, results in jsonl_results.items()
            }

            summary_entries.append(
                {
                    "candidate": candidate_name,
                    "overall_score": overall_score,
                    "total_tests": total_tests,
                    "test_type_stats": type_stats,
                    "confidence_interval": {"low": ci[0], "high": ci[1]},
                    "jsonl_breakdown": jsonl_stats,
                }
            )

        payload = {
            "input_folder": input_folder,
            "jsonl_files": jsonl_files,
            "params": {
                "force": args.force,
                "skip_baseline": args.skip_baseline,
                "bootstrap_samples": n_bootstrap,
                "confidence_level": ci_level,
                "sample": args.sample,
            },
            "summary": summary_entries,
        }

        base_path = Path(args.json_summary)
        if not base_path.is_absolute():
            base_path = Path(input_folder) / base_path
        output_path = base_path
        if output_path.parent:
            output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.exists():
            original_path = output_path
            suffix = 1
            while output_path.exists():
                output_path = original_path.with_name(
                    f"{original_path.stem}_{suffix}{original_path.suffix}"
                )
                suffix += 1
            print(
                f"Warning: JSON summary already exists at {original_path}. Writing to {output_path} instead."
            )

        try:
            with output_path.open("w", encoding="utf-8") as summary_file:
                json.dump(payload, summary_file, indent=2)
            print(f"\nJSON summary written to {output_path}")
        except Exception as e:
            print(f"Error writing JSON summary to {output_path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
