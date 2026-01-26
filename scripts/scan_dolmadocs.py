import argparse
import base64
import csv
import datetime
import json
import os
import random
import re
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3
import requests
import tinyhost
from tqdm import tqdm

from olmocr.data.renderpdf import render_pdf_to_base64webp
from olmocr.cloud_utils import get_s3_bytes, parse_s3_path


def parse_args():
    parser = argparse.ArgumentParser(description="Scan OLMO OCR workspace results and create visual samples")
    parser.add_argument("workspace", help="OLMO OCR workspace path (s3://bucket/workspace)")
    parser.add_argument("--pages_per_output", type=int, default=30, help="Number of pages per output file")
    parser.add_argument("--repeats", type=int, default=1, help="Number of output files to generate")
    parser.add_argument("--pdf_profile", help="AWS profile for accessing PDFs")
    parser.add_argument("--output_dir", default="dolma_samples", help="Directory to save output HTML files")
    parser.add_argument("--max_workers", type=int, default=4, help="Maximum number of worker threads")
    parser.add_argument(
        "--db_path",
        default="~/s2pdf_url_data/d65142df-6588-4b68-a12c-d468b3761189.csv.db",
        help="Path to the SQLite database containing PDF hash to URL mapping",
    )
    parser.add_argument(
        "--prolific_code",
        required=True,
        help="Fixed completion code to use for all outputs",
    )
    parser.add_argument(
        "--prolific_csv",
        default="prolific_codes.csv",
        help="Path to save the file with tinyhost links (one URL per line)",
    )
    parser.add_argument(
        "--read_results",
        help="Path to a CSV file containing previously generated tinyhost links to extract annotations",
    )
    return parser.parse_args()


# Fixed prolific code is now passed in as a command line argument


def obfuscate_code(code):
    """Gently obfuscate the Prolific code so it's not immediately visible in source."""
    # Convert to base64 and reverse
    encoded = base64.b64encode(code.encode()).decode()
    return encoded[::-1]


def deobfuscate_code(obfuscated_code):
    """Deobfuscate the code - this will be done in JavaScript."""
    # Reverse and decode from base64
    reversed_encoded = obfuscated_code[::-1]
    try:
        return base64.b64decode(reversed_encoded).decode()
    except:
        return "ERROR_DECODING"


def parse_pdf_hash(pretty_pdf_path: str) -> Optional[str]:
    pattern = r"s3://ai2-s2-pdfs/([a-f0-9]{4})/([a-f0-9]+)\.pdf"
    match = re.match(pattern, pretty_pdf_path)
    if match:
        return match.group(1) + match.group(2)
    return None


def get_original_url(pdf_hash: str, db_path: str) -> Optional[str]:
    """Look up the original URL for a PDF hash in the SQLite database."""
    if not pdf_hash:
        return None

    try:
        sqlite_db_path = os.path.expanduser(db_path)
        if not os.path.exists(sqlite_db_path):
            print(f"SQLite database not found at {sqlite_db_path}")
            return None

        conn = sqlite3.connect(sqlite_db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT uri FROM pdf_mapping WHERE pdf_hash = ?", (pdf_hash,))
        result = cursor.fetchone()

        conn.close()

        if result:
            return result[0]
        return None
    except Exception as e:
        print(f"Error looking up URL for PDF hash {pdf_hash}: {e}")
        return None


def list_result_files(s3_client, workspace_path):
    """List all JSON result files in the workspace results directory."""
    bucket, prefix = parse_s3_path(workspace_path)
    results_prefix = os.path.join(prefix, "results").rstrip("/") + "/"

    all_files = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=results_prefix):
        if "Contents" in page:
            all_files.extend([f"s3://{bucket}/{obj['Key']}" for obj in page["Contents"] if obj["Key"].endswith(".jsonl") or obj["Key"].endswith(".json")])

        # if len(all_files) > 1000:
        #     break

    return all_files


def get_random_pages(s3_client, result_files, count=30):
    """Get random pages from the result files."""
    random_pages = []

    # Try to collect the requested number of pages
    attempts = 0
    max_attempts = count * 3  # Allow extra attempts to handle potential failures

    while len(random_pages) < count and attempts < max_attempts:
        attempts += 1

        # Pick a random result file
        if not result_files:
            print("No result files found!")
            break

        result_file = random.choice(result_files)

        try:
            # Get the content of the file
            content = get_s3_bytes(s3_client, result_file)
            lines = content.decode("utf-8").strip().split("\n")

            if not lines:
                continue

            # Pick a random line (which contains a complete document)
            line = random.choice(lines)
            doc = json.loads(line)

            # A Dolma document has "text", "metadata", and "attributes" fields
            if "text" not in doc or "metadata" not in doc or "attributes" not in doc:
                print(f"Document in {result_file} is not a valid Dolma document")
                continue

            # Get the original PDF path from metadata
            pdf_path = doc["metadata"].get("Source-File")
            if not pdf_path:
                continue

            # Get page spans from attributes
            page_spans = doc["attributes"].get("pdf_page_numbers", [])
            if not page_spans:
                continue

            # Pick a random page span
            page_span = random.choice(page_spans)
            if len(page_span) >= 3:
                # Page spans are [start_pos, end_pos, page_num]
                page_num = page_span[2]

                # Extract text for this page
                start_pos, end_pos = page_span[0], page_span[1]
                page_text = doc["text"][start_pos:end_pos].strip()

                # Include the text snippet with the page info
                random_pages.append((pdf_path, page_num, page_text, result_file))

                if len(random_pages) >= count:
                    break

        except Exception as e:
            print(f"Error processing {result_file}: {e}")
            continue

    print(f"Found {len(random_pages)} random pages from Dolma documents")
    return random_pages


def create_presigned_url(s3_client, pdf_path, expiration=3600 * 24 * 7):
    """Create a presigned URL for the given S3 path."""
    try:
        bucket, key = parse_s3_path(pdf_path)
        url = s3_client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expiration)
        return url
    except Exception as e:
        print(f"Error creating presigned URL for {pdf_path}: {e}")
        return None


def create_html_output(random_pages, pdf_s3_client, output_path, workspace_path, db_path, prolific_code, resolution=2048):
    """Create an HTML file with rendered PDF pages."""
    # Obfuscate the provided Prolific code
    obfuscated_code = obfuscate_code(prolific_code)

    # Get current date and time for the report
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OLMO OCR Samples</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {{
                --primary-color: #2563eb;
                --secondary-color: #4b5563;
                --border-color: #e5e7eb;
                --bg-color: #f9fafb;
                --text-color: #111827;
                --text-light: #6b7280;
                --card-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                --success-color: #10b981;
                --overlay-bg: rgba(0, 0, 0, 0.7);
            }}
            
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            
            body {{
                font-family: 'Inter', sans-serif;
                line-height: 1.6;
                color: var(--text-color);
                background-color: var(--bg-color);
                padding: 2rem;
                display: flex;
                flex-direction: row;
                gap: 2rem;
            }}
            
            ul {{
                margin-left: 2em;
            }}

            ol {{
                margin-left: 2em;
            }}

            .highlight {{
                background-color: #f8f9fa;
                border-left: 3px solid #3498db;
                padding: 10px 15px;
                margin: 15px 0;
            }}

            .container {{
                flex: 2;
                max-width: 750px;
            }}
            
            header {{
                position: sticky;
                top: 2rem;
                flex: 1;
                min-width: 380px;
                max-width: 420px;
                max-height: calc(100vh - 4rem);
                overflow-y: auto;
                padding: 1.5rem;
                background-color: white;
                border-radius: 0.5rem;
                box-shadow: var(--card-shadow);
                align-self: flex-start;
                font-size: small;
            }}

            header h2 {{
                margin-top: 1em;
            }}
        
             .important {{
                font-weight: bold;
             }}

            .info-bar {{
                background-color: white;
                padding: 1rem;
                border-radius: 0.5rem;
                margin-bottom: 2rem;
                box-shadow: var(--card-shadow);
                display: flex;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 1rem;
            }}
            
            .info-item {{
                flex: 1;
                min-width: 200px;
            }}
            
            .info-item h3 {{
                font-size: 0.6rem;
                color: var(--text-light);
                margin-bottom: 0.25rem;
            }}
            
            .info-item p {{
                font-size: 0.6rem;
            }}
            
            .page-grid {{
                display: grid;
                grid-template-columns: 1fr;
                gap: 2rem;
            }}
            
            .page-container {{
                background-color: white;
                border-radius: 0.5rem;
                overflow: hidden;
                box-shadow: var(--card-shadow);
                transition: all 0.3s ease;
            }}
            
            .page-container.editing {{
                box-shadow: 0 0 0 3px var(--primary-color), var(--card-shadow);
            }}
            
            .page-info {{
                padding: 1rem;
                border-bottom: 1px solid var(--border-color);
            }}
            
            .page-info h2 {{
                font-size: 1rem;
                margin-bottom: 0.5rem;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            
            .page-info p {{
                font-size: 0.875rem;
                color: var(--text-light);
            }}
            
            .page-image-wrapper {{
                padding: 1rem;
                display: flex;
                justify-content: center;
                align-items: center;
                background-color: #f3f4f6;
            }}
            
            .page-image {{
                max-width: 100%;
                height: auto;
                border: 1px solid var(--border-color);
            }}
            
            .s3-link {{
                padding: 1rem;
                background-color: #f8fafc;
                border-top: 1px solid var(--border-color);
                font-size: 0.875rem;
                color: var(--secondary-color);
                word-break: break-all;
            }}
            
            .s3-link a {{
                color: var(--primary-color);
                text-decoration: none;
                font-weight: 500;
            }}
            
            .s3-link a:hover {{
                text-decoration: underline;
            }}
            
            /* Annotation elements */
            .annotation-interface {{
                display: none; /* Hide annotation interface by default */
                margin-top: 1rem;
                padding: 0.5rem;
                border-top: 1px solid var(--border-color);
                border-radius: 0.25rem;
                background-color: #f8fafc;
            }}
            
            .annotation-interface.active {{
                display: block; /* Show only the active annotation interface */
            }}
            
            .question-container {{
                margin-bottom: 1rem;
            }}
            
            .question-text {{
                font-weight: 500;
                margin-bottom: 0.5rem;
            }}
            
            /* Button group styling for connected buttons */
            .btn-group {{
                display: inline-flex;
                margin-bottom: 0.5rem;
            }}
            
            .btn-group .toggle-button {{
                padding: 0.5rem 1rem;
                border: 1px solid var(--border-color);
                background-color: #f8fafc;
                cursor: pointer;
                margin: 0;
                /* Remove individual border radius so we can set unified ones */
                border-radius: 0;
            }}
            
            .btn-group .toggle-button:first-child {{
                border-right: none;
                border-top-left-radius: 0.25rem;
                border-bottom-left-radius: 0.25rem;
            }}
            
            .btn-group .toggle-button:last-child {{
                border-top-right-radius: 0.25rem;
                border-bottom-right-radius: 0.25rem;
            }}
            
            .btn-group .toggle-button:not(:first-child):not(:last-child) {{
                border-right: none;
            }}
            
            .toggle-button.active {{
                background-color: var(--primary-color);
                color: white;
            }}
            
            .checkbox-group {{
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
                margin-bottom: 1rem;
            }}
            
            .checkbox-group label {{
                display: flex;
                align-items: center;
                padding: 0.25rem 0.5rem;
                background-color: #f1f5f9;
                border-radius: 0.25rem;
                cursor: pointer;
                font-size: 0.875rem;
                border-left: 3px solid transparent;
            }}
            
            .checkbox-group label:hover {{
                background-color: #e2e8f0;
            }}
            
            .checkbox-group input[type="checkbox"] {{
                margin-right: 0.5rem;
            }}
            
            /* Styling for checkbox groups with headings */
            .question-container h4 {{
                margin-bottom: 0.5rem;
                font-weight: 600;
                font-size: 0.9rem;
                border-bottom: 1px solid #e5e7eb;
                padding-bottom: 0.25rem;
            }}
            
            /* Slightly different styling for each group */
            .question-container h4:nth-of-type(1) + .checkbox-group label {{
                border-left-color: #3b82f6;  /* Blue for identifiers */
            }}
            
            .question-container h4:nth-of-type(2) + .checkbox-group label {{
                border-left-color: #10b981;  /* Green for PII with identifier */
            }}
            
            .question-container h4:nth-of-type(3) + .checkbox-group label {{
                border-left-color: #f59e0b;  /* Amber for always-PII */
            }}
            
            .continue-button {{
                padding: 0.5rem 1rem;
                background-color: var(--primary-color);
                color: white;
                border: none;
                border-radius: 0.25rem;
                cursor: pointer;
                font-weight: 500;
            }}
            
            .continue-button:hover {{
                background-color: #1d4ed8;
            }}
            
            .annotation-interface textarea {{
                display: none; /* Hide textarea by default */
                width: 100%;
                margin-top: 0.5rem;
                margin-bottom: 1rem;
                padding: 0.5rem;
                font-size: 0.875rem;
                border: 1px solid var(--border-color);
                border-radius: 0.25rem;
            }}
            
            .annotation-status {{
                display: inline-block;
                margin-left: 1rem;
                padding: 0.25rem 0.5rem;
                border-radius: 0.25rem;
                font-size: 0.75rem;
                font-weight: 600;
            }}
            
            .status-complete {{
                background-color: #ecfdf5;
                color: var(--success-color);
                cursor: pointer;
                transition: all 0.2s ease;
            }}
            
            .status-complete:hover {{
                background-color: #d1fae5;
                box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.3);
            }}
            
            .status-pending {{
                background-color: #fff7ed;
                color: #ea580c;
            }}
            
            .status-current {{
                background-color: #eff6ff;
                color: var(--primary-color);
                animation: pulse 2s infinite;
            }}
            
            @keyframes pulse {{
                0% {{ opacity: 0.6; }}
                50% {{ opacity: 1; }}
                100% {{ opacity: 0.6; }}
            }}
            
            .error {{
                color: #dc2626;
                padding: 1rem;
                background-color: #fee2e2;
                border-radius: 0.25rem;
            }}
        
            
            .completion-message {{
                display: none;
                margin: 2rem auto;
                padding: 1.5rem;
                background-color: #ecfdf5;
                border: 1px solid #A7F3D0;
                border-radius: 0.5rem;
                text-align: center;
                color: var(--success-color);
                font-weight: 600;
                max-width: 500px;
            }}
            
            footer {{
                margin-top: 3rem;
                text-align: center;
                color: var(--text-light);
                font-size: 0.875rem;
                border-top: 1px solid var(--border-color);
                padding-top: 1rem;
            }}
            
            /* Instructions Modal */
            .instructions-modal-overlay {{
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background-color: var(--overlay-bg);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1000;
                opacity: 0;
                visibility: hidden;
                transition: opacity 0.3s ease, visibility 0.3s ease;
                backdrop-filter: blur(3px);
            }}
            
            .instructions-modal-overlay.visible {{
                opacity: 1;
                visibility: visible;
            }}
            
            .instructions-modal {{
                background-color: white;
                border-radius: 8px;
                width: 90%;
                max-width: 1000px;
                max-height: 90vh;
                overflow-y: auto;
                padding: 2rem;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
                position: relative;
                animation: modalAppear 0.3s ease;
            }}
            
            @keyframes modalAppear {{
                from {{ 
                    opacity: 0;
                    transform: translateY(-20px);
                }}
                to {{ 
                    opacity: 1;
                    transform: translateY(0);
                }}
            }}
            
            .instructions-modal-header {{
                margin-bottom: 1.5rem;
                text-align: center;
            }}
            
            .instructions-modal-header h2 {{
                font-size: 1.5rem;
                color: var(--primary-color);
                margin-bottom: 0.5rem;
            }}
            
            .instructions-modal-content {{
                margin-bottom: 2rem;
                overflow-y: auto;
                max-height: 60vh;
                padding-right: 10px;
                border-radius: 4px;
                scrollbar-width: thin;
            }}
            
            /* Scrollbar styling for webkit browsers */
            .instructions-modal-content::-webkit-scrollbar {{
                width: 8px;
            }}
            
            .instructions-modal-content::-webkit-scrollbar-track {{
                background: #f1f1f1;
                border-radius: 10px;
            }}
            
            .instructions-modal-content::-webkit-scrollbar-thumb {{
                background: #c0c0c0;
                border-radius: 10px;
            }}
            
            .instructions-modal-content::-webkit-scrollbar-thumb:hover {{
                background: #a0a0a0;
            }}
            
            /* Styling for the cloned sidebar content in the modal */
            .instructions-modal-content header {{
                position: static;
                min-width: unset;
                max-width: unset;
                max-height: unset;
                overflow-y: visible;
                padding: 0;
                background-color: transparent;
                border-radius: 0;
                box-shadow: none;
                align-self: auto;
                font-size: inherit;
            }}
            
            .instructions-modal-footer {{
                text-align: center;
            }}
            
            .instructions-modal-button {{
                padding: 0.75rem 2rem;
                background-color: var(--primary-color);
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 1rem;
                font-weight: 600;
                cursor: pointer;
                transition: background-color 0.2s ease;
            }}
            
            .instructions-modal-button:hover {{
                background-color: #1d4ed8;
            }}
            
            .instructions-modal-button:disabled {{
                background-color: #9cb3f0;
                cursor: not-allowed;
                opacity: 0.7;
            }}
            
            @media (max-width: 768px) {{
                body {{
                    padding: 1rem;
                    flex-direction: column;
                }}
                
                header {{
                    position: static;
                    max-width: 100%;
                    margin-left: 0;
                    margin-bottom: 2rem;
                }}
                
                .container {{
                    max-width: 100%;
                }}
                
                .instructions-modal {{
                    padding: 1.5rem;
                    width: 95%;
                }}
            }}
        </style>
    </head>
    <body>
        <header>
            <h2>Task Overview</h2>
            <p>In this task, you will review {len(random_pages)} document pages and determine whether they contain any <span class="important">Personally Identifiable Information (PII)</span>. For each page, please follow the decision flow outlined in the "How to Annotate" section below.</p>
            <p>Carefully but efficiently inspect each page and select the appropriate response. You do <span class="important">not</span> need to read every word. Instead, focus on ascertaining the document's intended use and spotting information that would qualify as PII.</p>
            <p>The entire task should take about <span class="important">20-25 minutes</span>.</p>
            
            <button id="view-instructions-button" style="background-color: var(--primary-color); color: white; border: none; border-radius: 4px; padding: 0.5rem 1rem; margin: 1rem 0; cursor: pointer;">View Instructions Popup</button>
            
            <h2>How to Annotate</h2>
            <p>The current annotation will be highlighted with a blue outline and a set of response buttons will be displayed directly below the page preview. If you are having trouble viewing the displayed page, click the “View Cached PDF” link for a better look. However, <span class="important">DO NOT</span> examine the entire document; <span class="important">ONLY</span> review the single page being previewed (also indicated in the parentheses after “Viewed Cached PDF”).</p>
            <p>For each page, complete the following steps:</p>
            
            <ol>
                <li>
                    <p><span class="important">Determine if the document is intended for public release.</span></p>
                    <p>Inspect the page and answer: "Is this document intended for public release or dissemination?"</p>
                    <ul>
                        <li><strong>Yes</strong> - If the document appears to be a publication, research paper, public information, etc.</li>
                        <li><strong>No</strong> - If the document appears to be private, personal, or not intended for public release</li>
                        <li><strong>Cannot Read</strong> - If you are unable to read the page (e.g., foreign language, no text, etc.)</li>
                        <li><strong>Report Content</strong> - If the content is inappropriate or disturbing</li>
                    </ul>
                    <p>If you selected "Yes," "Cannot Read," or "Report Content," you will automatically move to the next document. If you selected "No," proceed to Step 2.</p>
                </li>
                
                <li>
                    <p><span class="important">Identify the kind of PII found in the private document (if any).</span></p>
                    <p>You will be shown a checklist with a set of PII options.</p>
                    <ul>
                        <li>Refer to the "How to Identify PII" section below and mark all options that apply.</li>
                        <li>If you select "Other," describe the kind of other PII in the expanded text box.</li>
                    </ul>
                </li>
                
                <li>
                    <p><span class="important">Press the blue Continue button to complete your annotation.</span></p>
                    <p>You will automatically be moved to the next annotation.</p>
                </li>
            </ol>
            
            <p><span class="important">Note</span>: If you cannot confidently tell that a page is private, treat it as public and do not mark any PII you are unsure about. We anticipate very few private pages or instances of PII in these documents, so erring towards public and no PII minimizes false positives and keeps the review process consistent.</p>
            
            <p>You may review and edit your previous annotations at any time. To do so, press the green Edit button directly above the page preview for the annotation you want to edit.</p>
            <p>After completing all {len(random_pages)} document pages, you will receive a Prolific completion code.</p>
            
            <h2>How to Identify PII</h2>
            
            <h3 style="color: #3b82f6;">Identifiers for PII</h3>
            <p>Some personal information needs to be accompanied by an <span class="important">identifier</span> to be considered PII. Identifiers that trigger PII include:</p>
            <ul>
                <li>Names (full names, first/last names, maiden names, nicknames, aliases)</li>
                <li>Email Addresses</li>
                <li>Phone Numbers</li>
            </ul>
            <p>Note that the reverse is also true - an identifier must be accompanied by additional personal information or another identifier (e.g., name + email address) to be considered PII.</p>
            <br/>
            
            <h3 style="color: #10b981;">PII that must co-occur with an Identifier</h3>
            <div class="highlight">
                <p>The following types of information should <span class="important">only</span> be marked as PII if they occur <span class="important">alongside an identifier</span> (commonly, a person's name):</p>
                <ul>
                    <li>Addresses (street address, postal code, etc.)</li>
                    <li>Biographical Information (date of birth, place of birth, gender, sexual orientation, race, ethnicity, citizenship/immigration status, religion)</li>
                    <li>Location Information (geolocations, specific coordinates)</li>
                    <li>Employment Information (job titles, workplace names, employment history)</li>
                    <li>Education Information (school names, degrees, transcripts)</li>
                    <li>Medical Information (health records, diagnoses, genetic or neural data)</li>
                </ul>
            </div>
            <p>For example, a street address might be personal information, but is not PII by itself; however, a street address associated with a name <span class="important">is</span> regulated PII.</p>
            
            <br/>
            <h3 style="color: #f59e0b;">PII that occurs even without an Identifier</h3>
            <div class="highlight">
                <p>Certain types of sensitive information should always be classified as PII because the information is inherently self-identifying. The following should <span class="important">always be marked as PII</span> even if they do not occur alongside an identifier:</p>
                <ul>
                    <li>Government IDs (SSNs, passport numbers, driver's license numbers, tax IDs)</li>
                    <li>Financial Information (credit card numbers, bank account/routing numbers)</li>
                    <li>Biometric Data (fingerprints, retina scans, facial recognition data, voice signatures)</li>
                    <li>Login information (<span class="important">only</span> mark as PII when a <span class="important">username, password, and login location</span> are present together)</li>
                </ul>
            </div>
        </header>
        <div class="container">
            
            <div class="info-bar">
                <div class="info-item">
                    <h3>Generated On</h3>
                    <p>{current_time}</p>
                </div>
                <div class="info-item">
                    <h3>Workspace</h3>
                    <p title="{workspace_path}">{workspace_path}</p>
                </div>
                <div class="info-item">
                    <h3>Sample Size</h3>
                    <p>{len(random_pages)} pages</p>
                </div>
            </div>
            
            <div class="page-grid">
    """

    for i, (pdf_path, page_num, page_text, result_file) in enumerate(tqdm(random_pages, desc="Rendering pages")):
        # Get original URL from PDF hash
        pdf_hash = parse_pdf_hash(pdf_path)
        _original_url = get_original_url(pdf_hash, db_path) if pdf_hash else None

        # Create a truncated path for display
        display_path = pdf_path
        if len(display_path) > 60:
            display_path = "..." + display_path[-57:]

        # Generate presigned URL
        presigned_url = create_presigned_url(pdf_s3_client, pdf_path)

        try:
            # Download PDF to temp file
            bucket, key = parse_s3_path(pdf_path)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                pdf_data = pdf_s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
                temp_file.write(pdf_data)
                temp_file_path = temp_file.name

            # Render PDF to base64 webp
            base64_image = render_pdf_to_base64webp(temp_file_path, page_num, resolution)

            # Add CSS class for the first annotation interface to be active by default
            active_class = " active" if i == 0 else ""

            # Add to HTML with the annotation interface
            html_content += f"""
            <div class="page-container" data-index="{i}">
                <div class="page-info">
                    <p>{f'<a href="{presigned_url}#page={page_num}" target="_blank">View Cached PDF (page {page_num})</a>' if presigned_url else pdf_path}</p>
                    <p>
                        Status: <span class="annotation-status status-pending" id="status-{i}">Pending</span>
                    </p>
                </div>
                <div class="page-image-wrapper">
                    <img class="page-image" src="data:image/webp;base64,{base64_image}" alt="PDF Page {page_num}" loading="lazy" />
                </div>
                <div class="annotation-interface{active_class}" data-id="page-{i}" data-pdf-path="{pdf_path}" data-pdf-page="{page_num}">
                    <div class="question-container" id="question1-{i}">
                        <p class="question-text">Is this document meant for public dissemination? (ex. news article, research paper, etc.)</p>
                        <span class="btn-group">
                            <button type="button" class="toggle-button primary-option" data-value="yes-public" onclick="togglePrimaryOption(this, {i})">Yes</button>
                            <button type="button" class="toggle-button primary-option" data-value="no-public" onclick="togglePrimaryOption(this, {i})">No</button>
                            <button type="button" class="toggle-button primary-option" data-value="cannot-read" onclick="togglePrimaryOption(this, {i})">Cannot Read</button>
                            <button type="button" class="toggle-button primary-option" data-value="report-content" onclick="togglePrimaryOption(this, {i})">Report Content</button>
                        </span>
                    </div>
                    
                    <div class="question-container" id="public-pii-options-{i}" style="display: none; margin-top: 1rem;">
                        <p class="question-text">Select any PII found in this public document:</p>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="pii-checkbox" data-value="ssn" onchange="saveCheckboxes(this)"> SSN</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="bank-info" onchange="saveCheckboxes(this)"> Bank Info</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="credit-card" onchange="saveCheckboxes(this)"> Credit Card Info</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="usernames-passwords" onchange="saveCheckboxes(this)"> Usernames/Passwords</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="other" onchange="toggleOtherTextarea(this)"> Other</label>
                        </div>
                        <textarea id="other-pii-public-{i}" placeholder="Describe other PII found in the document" style="display: none;" onchange="saveFeedback(this)" onkeydown="handleTextareaKeydown(event, this)"></textarea>
                        <button type="button" class="continue-button" onclick="saveThenNext(this)">Continue</button>
                    </div>
                    
                    <div class="question-container" id="private-pii-options-{i}" style="display: none; margin-top: 1rem;">
                        <p class="question-text">Select any PII found in this private document:</p>
                        
                        <h4 style="margin-top: 1rem; font-size: 0.9rem; color: #3b82f6;">Identifiers for PII (Select these if found)</h4>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="pii-checkbox" data-value="names" onchange="saveCheckboxes(this)"> Names (full, first, last, nicknames)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="email" onchange="saveCheckboxes(this)"> Email Addresses</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="phone" onchange="saveCheckboxes(this)"> Phone Numbers</label>
                        </div>
                        
                        <h4 style="margin-top: 1rem; font-size: 0.9rem; color: #10b981;">PII that must co-occur with an Identifier</h4>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="pii-checkbox" data-value="addresses" onchange="saveCheckboxes(this)"> Addresses</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="biographical" onchange="saveCheckboxes(this)"> Biographical Info (DOB, gender, etc.)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="location" onchange="saveCheckboxes(this)"> Location Information</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="employment" onchange="saveCheckboxes(this)"> Employment Information</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="education" onchange="saveCheckboxes(this)"> Education Information</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="medical" onchange="saveCheckboxes(this)"> Medical Information</label>
                        </div>
                        
                        <h4 style="margin-top: 1rem; font-size: 0.9rem; color: #f59e0b;">PII that occurs even without an Identifier</h4>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="pii-checkbox" data-value="government-id" onchange="saveCheckboxes(this)"> Government IDs (SSN, passport, etc.)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="financial" onchange="saveCheckboxes(this)"> Financial Information (credit card, bank)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="biometric" onchange="saveCheckboxes(this)"> Biometric Data</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="login-info" onchange="saveCheckboxes(this)"> Login Information (username + password)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="other" onchange="toggleOtherTextarea(this)"> Other</label>
                        </div>
                        
                        <textarea id="other-pii-private-{i}" placeholder="Describe other PII found in the document" style="display: none;" onchange="saveFeedback(this)" onkeydown="handleTextareaKeydown(event, this)"></textarea>
                        <button type="button" class="continue-button" onclick="saveThenNext(this)">Continue</button>
                    </div>
                </div>
            </div>
            """

            # Clean up temp file
            os.unlink(temp_file_path)

        except Exception as e:
            # Add CSS class for the first annotation interface to be active by default
            active_class = " active" if i == 0 else ""

            html_content += f"""
            <div class="page-container" data-index="{i}">
                <div class="page-info">
                    <p>{f'<a href="{presigned_url}#page={page_num}" target="_blank">View Cached PDF (page {page_num})</a>' if presigned_url else pdf_path}</p>
                    <p>
                        Status: <span class="annotation-status status-pending" id="status-{i}">Pending</span>
                    </p>
                </div>
                <div class="error">Error: {str(e)}</div>
                <div class="annotation-interface{active_class}" data-id="page-{i}" data-pdf-path="{pdf_path}" data-pdf-page="{page_num}">
                    <div class="question-container" id="question1-{i}">
                        <p class="question-text">Is this document intended for public release or dissemination?</p>
                        <span class="btn-group">
                            <button type="button" class="toggle-button primary-option" data-value="yes-public" onclick="togglePrimaryOption(this, {i})">Yes</button>
                            <button type="button" class="toggle-button primary-option" data-value="no-public" onclick="togglePrimaryOption(this, {i})">No</button>
                            <button type="button" class="toggle-button primary-option" data-value="cannot-read" onclick="togglePrimaryOption(this, {i})">Cannot Read</button>
                            <button type="button" class="toggle-button primary-option" data-value="report-content" onclick="togglePrimaryOption(this, {i})">Report Content</button>
                        </span>
                    </div>
                    
                    <div class="question-container" id="public-pii-options-{i}" style="display: none; margin-top: 1rem;">
                        <p class="question-text">Select any PII found in this public document:</p>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="pii-checkbox" data-value="ssn" onchange="saveCheckboxes(this)"> SSN</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="bank-info" onchange="saveCheckboxes(this)"> Bank Info</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="credit-card" onchange="saveCheckboxes(this)"> Credit Card Info</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="usernames-passwords" onchange="saveCheckboxes(this)"> Usernames/Passwords</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="other" onchange="toggleOtherTextarea(this)"> Other</label>
                        </div>
                        <textarea id="other-pii-public-{i}" placeholder="Describe other PII found in the document" style="display: none;" onchange="saveFeedback(this)" onkeydown="handleTextareaKeydown(event, this)"></textarea>
                        <button type="button" class="continue-button" onclick="saveThenNext(this)">Continue</button>
                    </div>
                    
                    <div class="question-container" id="private-pii-options-{i}" style="display: none; margin-top: 1rem;">
                        <p class="question-text">Select any PII found in this private document:</p>
                        
                        <h4 style="margin-top: 1rem; font-size: 0.9rem; color: #3b82f6;">Identifiers (Select these if found)</h4>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="pii-checkbox" data-value="names" onchange="saveCheckboxes(this)"> Names (full, first, last, nicknames)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="email" onchange="saveCheckboxes(this)"> Email Addresses</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="phone" onchange="saveCheckboxes(this)"> Phone Numbers</label>
                        </div>
                        
                        <h4 style="margin-top: 1rem; font-size: 0.9rem; color: #10b981;">PII that requires an identifier above</h4>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="pii-checkbox" data-value="addresses" onchange="saveCheckboxes(this)"> Addresses</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="biographical" onchange="saveCheckboxes(this)"> Biographical Info (DOB, gender, etc.)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="location" onchange="saveCheckboxes(this)"> Location Information</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="employment" onchange="saveCheckboxes(this)"> Employment Information</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="education" onchange="saveCheckboxes(this)"> Education Information</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="medical" onchange="saveCheckboxes(this)"> Medical Information</label>
                        </div>
                        
                        <h4 style="margin-top: 1rem; font-size: 0.9rem; color: #f59e0b;">PII that is always sensitive (even without an identifier)</h4>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="pii-checkbox" data-value="government-id" onchange="saveCheckboxes(this)"> Government IDs (SSN, passport, etc.)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="financial" onchange="saveCheckboxes(this)"> Financial Information (credit card, bank)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="biometric" onchange="saveCheckboxes(this)"> Biometric Data</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="login-info" onchange="saveCheckboxes(this)"> Login Information (username + password)</label>
                            <label><input type="checkbox" class="pii-checkbox" data-value="other" onchange="toggleOtherTextarea(this)"> Other</label>
                        </div>
                        
                        <textarea id="other-pii-private-{i}" placeholder="Describe other PII found in the document" style="display: none;" onchange="saveFeedback(this)" onkeydown="handleTextareaKeydown(event, this)"></textarea>
                        <button type="button" class="continue-button" onclick="saveThenNext(this)">Continue</button>
                    </div>
                </div>
            </div>
            """

    html_content += (
        """
            </div>
            
            <div class="completion-message" id="completion-message">
                Thank you! All annotations are complete.<br>
                Your Prolific completion code is: <strong id="prolific-code">Loading...</strong>
            </div>
            <!-- Store the obfuscated code in a hidden element -->
            <div id="obfuscated-code" style="display:none;">"""
        + obfuscated_code
        + """</div>
            
        </div>
        <script>
            // Using externally injected async functions: fetchDatastore() and putDatastore()
            
            // Track annotation progress
            let currentIndex = 0;
            const totalPages = document.querySelectorAll('.page-container').length;
     
            // Update progress bar
            function updateProgressBar() {
                // Check if all annotations are complete
                if (currentIndex >= totalPages) {
                    document.getElementById('completion-message').style.display = 'block';
                }
            }
            
            // Update status indicators
            function updateStatusIndicators() {
                // Reset all status indicators
                document.querySelectorAll('.annotation-status').forEach(function(status) {
                    status.className = 'annotation-status status-pending';
                    status.textContent = 'Pending';
                    // Remove any click handlers
                    status.onclick = null;
                });
                
                // Set current item status
                const currentStatus = document.getElementById(`status-${currentIndex}`);
                if (currentStatus) {
                    currentStatus.className = 'annotation-status status-current';
                    currentStatus.textContent = 'Current';
                }
                
                // Update completed statuses
                for (let i = 0; i < currentIndex; i++) {
                    const status = document.getElementById(`status-${i}`);
                    if (status) {
                        status.className = 'annotation-status status-complete';
                        status.textContent = 'Edit ✎';
                        // Add click handler to edit this annotation
                        status.onclick = function() { editAnnotation(i); };
                    }
                }
            }
            
            // Function to enable editing a previously completed annotation
            function editAnnotation(index) {
                // Hide current annotation interface
                document.querySelector(`.annotation-interface[data-id="page-${currentIndex}"]`).classList.remove('active');
                
                // Remove editing class from all containers
                document.querySelectorAll('.page-container').forEach(container => {
                    container.classList.remove('editing');
                });
                
                // Show the selected annotation interface
                document.querySelector(`.annotation-interface[data-id="page-${index}"]`).classList.add('active');
                
                // Add editing class to the container being edited
                const activeContainer = document.querySelector(`.page-container[data-index="${index}"]`);
                if (activeContainer) {
                    activeContainer.classList.add('editing');
                    activeContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                
                // Update current index
                currentIndex = index;
                updateProgressBar();
                updateStatusIndicators();
            }
            
            // Navigate to the next document
            function goToNextDocument() {
                // Hide current annotation interface
                document.querySelector(`.annotation-interface[data-id="page-${currentIndex}"]`).classList.remove('active');
                
                // Remove editing class from all containers
                document.querySelectorAll('.page-container').forEach(container => {
                    container.classList.remove('editing');
                });
                
                // Move to next document if not at the end
                if (currentIndex < totalPages - 1) {
                    currentIndex++;
                    document.querySelector(`.annotation-interface[data-id="page-${currentIndex}"]`).classList.add('active');
                    
                    // Add editing class to current container
                    const activeContainer = document.querySelector(`.page-container[data-index="${currentIndex}"]`);
                    if (activeContainer) {
                        activeContainer.classList.add('editing');
                        activeContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                    
                    updateProgressBar();
                    updateStatusIndicators();
                }
                else {
                    // This was the last document, mark as complete
                    currentIndex = totalPages;
                    updateProgressBar();
                    updateStatusIndicators();
                    
                    // Show completion message and scroll to it
                    document.getElementById('completion-message').style.display = 'block';
                    document.getElementById('completion-message').scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
            
            // Handle text area keydown for Enter key
            function handleTextareaKeydown(event, textarea) {
                // If Enter key is pressed and not with Shift key, move to next document
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    saveFeedback(textarea).then(() => {
                        goToNextDocument();
                    });
                }
            }
            
            async function saveFeedback(source) {
                const interfaceDiv = source.closest('.annotation-interface');
                const id = interfaceDiv.getAttribute('data-id');
                
                // Get the selected primary option
                const activePrimaryButton = interfaceDiv.querySelector('button.primary-option.active');
                const primaryOption = activePrimaryButton ? activePrimaryButton.getAttribute('data-value') : null;
                
                // Get checkbox selections for public document
                const publicPiiOptions = [];
                interfaceDiv.querySelectorAll('#public-pii-options-' + id.split('-')[1] + ' input[type="checkbox"]:checked').forEach(checkbox => {
                    publicPiiOptions.push(checkbox.getAttribute('data-value'));
                });
                
                // Get checkbox selections for private document
                const privatePiiOptions = [];
                interfaceDiv.querySelectorAll('#private-pii-options-' + id.split('-')[1] + ' input[type="checkbox"]:checked').forEach(checkbox => {
                    privatePiiOptions.push(checkbox.getAttribute('data-value'));
                });
                
                // Get any "Other" descriptions
                const otherPublicDesc = interfaceDiv.querySelector('#other-pii-public-' + id.split('-')[1])?.value || '';
                const otherPrivateDesc = interfaceDiv.querySelector('#other-pii-private-' + id.split('-')[1])?.value || '';
                
                const pdfPath = interfaceDiv.getAttribute('data-pdf-path');
                const pdfPage = interfaceDiv.getAttribute('data-pdf-page');

                const datastore = await fetchDatastore() || {};
                datastore[id] = {
                    primaryOption: primaryOption,
                    publicPiiOptions: publicPiiOptions,
                    privatePiiOptions: privatePiiOptions,
                    otherPublicDesc: otherPublicDesc,
                    otherPrivateDesc: otherPrivateDesc,
                    pdfPath: pdfPath,
                    pdfPage: pdfPage
                };

                await putDatastore(datastore);
            }

            function saveThenNext(btn) {
                const interfaceDiv = btn.closest('.annotation-interface');
                saveFeedback(interfaceDiv).then(() => {
                    goToNextDocument();
                });
            }
            
            function togglePrimaryOption(btn, index) {
                const interfaceDiv = btn.closest('.annotation-interface');
                // Remove active class from all primary option buttons in this group
                interfaceDiv.querySelectorAll('button.primary-option').forEach(function(b) {
                    b.classList.remove('active');
                });
                
                // Toggle on the clicked button
                btn.classList.add('active');
                
                // Get the selected option
                const option = btn.getAttribute('data-value');
                
                // If user selected Yes, Cannot Read, or Report Content, clear any checkboxes
                // from "No" option that might have been selected before
                if (option === 'yes-public' || option === 'cannot-read' || option === 'report-content') {
                    // Clear all checkboxes
                    interfaceDiv.querySelectorAll('.pii-checkbox').forEach(checkbox => {
                        checkbox.checked = false;
                    });
                    
                    // Hide/clear any textareas
                    interfaceDiv.querySelectorAll('textarea').forEach(textarea => {
                        textarea.value = '';
                        textarea.style.display = 'none';
                    });
                }
                
                // Hide all secondary option containers
                document.querySelector(`#public-pii-options-${index}`).style.display = 'none';
                document.querySelector(`#private-pii-options-${index}`).style.display = 'none';
                
                // Immediately save the primary option selection
                saveFeedback(interfaceDiv);
                
                // Show the appropriate secondary options based on the selected primary option
                if (option === 'yes-public') {
                    // If "Yes" for public document, immediately go to next without asking for PII
                    goToNextDocument();
                } else if (option === 'no-public') {
                    document.querySelector(`#private-pii-options-${index}`).style.display = 'block';
                } else {
                    // For "cannot-read" or "report-content", just save and move to next
                    goToNextDocument();
                }
            }
            
            function toggleOtherTextarea(checkbox) {
                const container = checkbox.closest('.question-container');
                const textareaId = container.querySelector('textarea').id;
                const textarea = document.getElementById(textareaId);
                
                if (checkbox.checked) {
                    textarea.style.display = 'block';
                    textarea.focus();
                } else {
                    textarea.style.display = 'none';
                }
                
                saveCheckboxes(checkbox);
            }
            
            function saveCheckboxes(input) {
                const interfaceDiv = input.closest('.annotation-interface');
                return saveFeedback(interfaceDiv);
            }

            // Function to deobfuscate the Prolific code
            function deobfuscateCode(obfuscatedCode) {
                // Reverse the string
                const reversed = obfuscatedCode.split('').reverse().join('');
                // Decode from base64
                try {
                    return atob(reversed);
                } catch (e) {
                    return "ERROR_DECODING";
                }
            }
            
            function getQueryParam(name) {
                const urlParams = new URLSearchParams(window.location.search);
                return urlParams.get(name);
            }
            
            document.addEventListener("DOMContentLoaded", async function() {
                // Get the datastore
                const datastore = await fetchDatastore() || {};
                
                // Check for PROLIFIC_PID in the URL query parameters
                const prolificPid = getQueryParam('PROLIFIC_PID');
                if (prolificPid) {
                    // If it exists, update the datastore with this value
                    datastore.prolific_pid = prolificPid;
                    await putDatastore(datastore);
                }
                
                // Track if instructions have been seen before
                if (!datastore.hasOwnProperty('instructions_seen')) {
                    datastore.instructions_seen = false;
                    await putDatastore(datastore);
                }
                
                // Add editing class to the first container by default
                const firstContainer = document.querySelector(`.page-container[data-index="0"]`);
                if (firstContainer) {
                    firstContainer.classList.add('editing');
                }
                
                updateProgressBar();
                updateStatusIndicators();
                
                // Get and deobfuscate the Prolific code
                const obfuscatedCode = document.getElementById('obfuscated-code').textContent;
                const prolificCode = deobfuscateCode(obfuscatedCode);
                document.getElementById('prolific-code').textContent = prolificCode;
                
                document.querySelectorAll('.annotation-interface').forEach(function(interfaceDiv) {
                    const id = interfaceDiv.getAttribute('data-id');
                    const pageIndex = id.split('-')[1];
                    
                    if (datastore[id]) {
                        const data = datastore[id];
                        
                        // Set active state for primary option buttons
                        interfaceDiv.querySelectorAll('button.primary-option').forEach(function(btn) {
                            if (btn.getAttribute('data-value') === data.primaryOption) {
                                btn.classList.add('active');
                                
                                // Show the appropriate secondary options
                                const option = btn.getAttribute('data-value');
                                if (option === 'yes-public') {
                                    // No action needed for public documents - PII options remain hidden
                                } else if (option === 'no-public') {
                                    document.querySelector(`#private-pii-options-${pageIndex}`).style.display = 'block';
                                }
                            } else {
                                btn.classList.remove('active');
                            }
                        });
                        
                        // Restore public PII checkboxes
                        if (data.publicPiiOptions && data.publicPiiOptions.length > 0) {
                            const publicContainer = document.querySelector(`#public-pii-options-${pageIndex}`);
                            data.publicPiiOptions.forEach(option => {
                                const checkbox = publicContainer.querySelector(`input[data-value="${option}"]`);
                                if (checkbox) {
                                    checkbox.checked = true;
                                    if (option === 'other') {
                                        document.getElementById(`other-pii-public-${pageIndex}`).style.display = 'block';
                                    }
                                }
                            });
                        }
                        
                        // Restore private PII checkboxes
                        if (data.privatePiiOptions && data.privatePiiOptions.length > 0) {
                            const privateContainer = document.querySelector(`#private-pii-options-${pageIndex}`);
                            data.privatePiiOptions.forEach(option => {
                                const checkbox = privateContainer.querySelector(`input[data-value="${option}"]`);
                                if (checkbox) {
                                    checkbox.checked = true;
                                    if (option === 'other') {
                                        document.getElementById(`other-pii-private-${pageIndex}`).style.display = 'block';
                                    }
                                }
                            });
                        }
                        
                        // Set the textarea values
                        if (data.otherPublicDesc) {
                            document.getElementById(`other-pii-public-${pageIndex}`).value = data.otherPublicDesc;
                        }
                        
                        if (data.otherPrivateDesc) {
                            document.getElementById(`other-pii-private-${pageIndex}`).value = data.otherPrivateDesc;
                        }
                    }
                });
                
                // If we have stored data, restore the current position
                let lastAnnotatedIndex = -1;
                for (let i = 0; i < totalPages; i++) {
                    const pageId = `page-${i}`;
                    if (datastore[pageId] && datastore[pageId].primaryOption) {
                        lastAnnotatedIndex = i;
                    }
                }
                
                // If we have annotated pages, go to the first unannotated page
                if (lastAnnotatedIndex >= 0) {
                    document.querySelector(`.annotation-interface.active`).classList.remove('active');
                    
                    // Check if all pages are annotated
                    if (lastAnnotatedIndex === totalPages - 1) {
                        // All pages are annotated, set currentIndex to totalPages to trigger completion
                        currentIndex = totalPages;
                        
                        // Show completion message and scroll to it
                        document.getElementById('completion-message').style.display = 'block';
                        document.getElementById('completion-message').scrollIntoView({ behavior: 'smooth', block: 'center' });
                    } else {
                        // Go to the next unannotated page
                        currentIndex = lastAnnotatedIndex + 1;
                        document.querySelector(`.annotation-interface[data-id="page-${currentIndex}"]`).classList.add('active');
                        
                        // Add editing class and scroll to the active annotation
                        const activeContainer = document.querySelector(`.page-container[data-index="${currentIndex}"]`);
                        if (activeContainer) {
                            // Remove editing class from all containers first
                            document.querySelectorAll('.page-container').forEach(container => {
                                container.classList.remove('editing');
                            });
                            // Add editing class to current container
                            activeContainer.classList.add('editing');
                            activeContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }
                    }
                    
                    updateProgressBar();
                    updateStatusIndicators();
                }
            });
            
            // Instructions modal functionality
            // Create modal container
            const instructionsModal = document.createElement('div');
            instructionsModal.className = 'instructions-modal-overlay';
            instructionsModal.id = 'instructions-modal';
            
            // Create modal content container
            const modalContent = document.createElement('div');
            modalContent.className = 'instructions-modal';
            
            // Create header
            const modalHeader = document.createElement('div');
            modalHeader.className = 'instructions-modal-header';
            modalHeader.innerHTML = `
                <h2>Welcome to the OLMO OCR Annotation Task</h2>
                <p>Please read these instructions carefully before you begin.</p>
            `;
            
            // Create content section - will be populated with sidebar content
            const modalContentSection = document.createElement('div');
            modalContentSection.className = 'instructions-modal-content';
            
            // Clone the sidebar content to reuse in the modal
            const sidebarContent = document.querySelector('header').cloneNode(true);
            
            // Remove the "View Instructions Popup" button from the cloned content
            const viewInstructionsButton = sidebarContent.querySelector('#view-instructions-button');
            if (viewInstructionsButton) {
                viewInstructionsButton.remove();
            }
            
            // Style the sidebar content for use in the modal
            sidebarContent.style.fontSize = '14px';
            sidebarContent.style.lineHeight = '1.5';
            
            // Append the cloned sidebar content to the modal content section
            modalContentSection.appendChild(sidebarContent);
            
            // Create footer with start button (initially disabled)
            const modalFooter = document.createElement('div');
            modalFooter.className = 'instructions-modal-footer';
            modalFooter.innerHTML = `<button id="start-button" class="instructions-modal-button" disabled>I Understand, Begin Task</button>
                <p id="scroll-notice" style="margin-top: 10px; font-size: 0.85rem; color: #6b7280;">Please scroll to the bottom to continue</p>`;
            
            // Assemble the modal
            modalContent.appendChild(modalHeader);
            modalContent.appendChild(modalContentSection);
            modalContent.appendChild(modalFooter);
            instructionsModal.appendChild(modalContent);
            
            // Track scroll position in instructions and enable button when scrolled to bottom
            let hasReachedBottom = false;
            
            // Function to check if user has scrolled to the bottom of instructions
            function checkScrollPosition() {
                const contentSection = modalContentSection;
                const scrollableContent = contentSection;
                
                // Calculate if the user is at the bottom (allowing for small differences)
                // We consider "bottom" when user has scrolled to at least 90% of the content
                const scrollPosition = scrollableContent.scrollTop + scrollableContent.clientHeight;
                const scrollHeight = scrollableContent.scrollHeight;
                const scrollPercentage = (scrollPosition / scrollHeight) * 100;
                
                if (scrollPercentage >= 90 && !hasReachedBottom) {
                    // User has scrolled to the bottom, enable the button
                    hasReachedBottom = true;
                    const startButton = document.getElementById('start-button');
                    if (startButton) {
                        startButton.disabled = false;
                        
                        // Change the notice text
                        const scrollNotice = document.getElementById('scroll-notice');
                        if (scrollNotice) {
                            scrollNotice.textContent = 'You may now proceed';
                            scrollNotice.style.color = '#10b981'; // Success color
                        }
                    }
                }
            }
            
            // Add scroll event listener to the modal content
            modalContentSection.addEventListener('scroll', checkScrollPosition);
            
            document.body.appendChild(instructionsModal);
            
            // Show the instructions modal when the page loads
            async function showInstructionsModal() {
                const datastore = await fetchDatastore() || {};
                
                // Check if the task is already completed or instructions have been seen
                const isTaskCompleted = currentIndex >= totalPages;
                const instructionsSeen = datastore.instructions_seen === true;
                
                // Only show instructions if task is not completed and instructions haven't been seen
                if (!isTaskCompleted && !instructionsSeen) {
                    instructionsModal.classList.add('visible');
                }
            }
            
            // Handle button clicks for instructions modal
            document.addEventListener('click', async function(event) {
                // Start button closes the modal and marks instructions as seen
                if (event.target && event.target.id === 'start-button') {
                    // Hide the modal
                    instructionsModal.classList.remove('visible');
                    
                    // Update datastore to remember that instructions have been seen
                    const datastore = await fetchDatastore() || {};
                    datastore.instructions_seen = true;
                    await putDatastore(datastore);
                }
                
                // View instructions button shows the modal
                if (event.target && event.target.id === 'view-instructions-button') {
                    instructionsModal.classList.add('visible');
                }
            });
            
            // Show the instructions modal when page loads (after a slight delay)
            setTimeout(showInstructionsModal, 500);
        </script>
    </body>
    </html>
    """
    )

    with open(output_path, "w") as f:
        f.write(html_content)

    print(f"Created HTML output at {output_path}")


def generate_sample_set(args, i, s3_client, pdf_s3_client, result_files):
    """Generate a single sample set."""
    output_filename = Path(args.output_dir) / f"dolma_samples_{i+1}.html"

    print(f"\nGenerating sample set {i+1} of {args.repeats}")

    # Get random pages
    random_pages = get_random_pages(s3_client, result_files, args.pages_per_output)

    # Use the fixed prolific code from command line arguments
    prolific_code = args.prolific_code

    # Create HTML output with the Prolific code
    create_html_output(random_pages, pdf_s3_client, output_filename, args.workspace, args.db_path, prolific_code)

    return output_filename


def extract_datastore_url(html_content: str) -> Optional[str]:
    """Extract the presigned datastore URL from HTML content."""
    match = re.search(r'const\s+presignedGetUrl\s*=\s*"([^"]+)"', html_content)
    if match:
        return match.group(1)
    return None


def extract_page_number_from_html(html_content: str, page_id: str) -> Optional[int]:
    """Extract PDF page number from HTML content for a specific page_id.

    This is a fallback mechanism for older versions of the annotation page
    that didn't store the page number in a data attribute.
    """
    # Try to find the page number in the "View Cached PDF (page X)" text
    # Look for section with this page_id
    page_section_pattern = '<div class="page-container"[^>]*data-index="([^"]*)"[^>]*>.*?<div class="page-info">.*?<a href="[^"]*#page=([0-9]+)"[^>]*>View Cached PDF \\(page ([0-9]+)\\)</a>'
    matches = re.finditer(page_section_pattern, html_content, re.DOTALL)

    for match in matches:
        container_index = match.group(1)
        pdf_page_from_url = match.group(2)
        pdf_page_from_text = match.group(3)

        # Check if this container index matches our page_id (page-X)
        if f"page-{container_index}" == page_id:
            # Both numbers should be the same, but prefer the one from the URL fragment
            try:
                return int(pdf_page_from_url)
            except (ValueError, TypeError):
                try:
                    return int(pdf_page_from_text)
                except (ValueError, TypeError):
                    pass

    return None


def fetch_annotations(tinyhost_link: str) -> Tuple[Dict[str, Any], str, str]:
    """Fetch and parse annotations from a tinyhost link."""
    # Request the HTML content
    print(f"Fetching annotations from {tinyhost_link}")
    response = requests.get(tinyhost_link)
    response.raise_for_status()
    html_content = response.text

    # Extract the datastore URL
    datastore_url = extract_datastore_url(html_content)
    if not datastore_url:
        print(f"Could not find datastore URL in {tinyhost_link}")
        return {}, tinyhost_link, html_content

    # Fetch the datastore content
    print(f"Found datastore URL: {datastore_url}")
    try:
        datastore_response = requests.get(datastore_url)
        datastore_response.raise_for_status()
        annotations = datastore_response.json()
        return annotations, tinyhost_link, html_content
    except Exception as e:
        print(f"Error fetching datastore from {datastore_url}: {e}")
        return {}, tinyhost_link, html_content


def process_annotations(annotations_by_link: List[Tuple[Dict[str, Any], str, str]]) -> Dict[str, List[Dict[str, Any]]]:
    """Process and categorize annotations by feedback type."""
    results = {
        "public_document": [],
        "private_document": [],
        "cannot_read": [],
        "report_content": [],
        "no_annotation": [],
    }

    # Process each annotation
    for annotations, link, html_content in annotations_by_link:
        # Extract Prolific PID from datastore if available
        prolific_pid = annotations.get("prolific_pid", None)

        for page_id, annotation in annotations.items():
            # Skip non-page entries like prolific_pid
            if page_id == "prolific_pid":
                continue

            # Handle case where annotation might be a boolean or non-dict value
            if not isinstance(annotation, dict) or "primaryOption" not in annotation:
                continue

            primary_option = annotation["primaryOption"]
            pdf_path = annotation.get("pdfPath", "Unknown")

            # Get PDF page number from annotation data
            # This is the actual page number in the PDF that was annotated
            pdf_page = None

            # First try to get it from the annotation data (for new format)
            if annotation.get("pdfPage"):
                try:
                    pdf_page = int(annotation.get("pdfPage"))
                except (ValueError, TypeError):
                    pass

            # Fallback: try to extract page number from HTML content (for older format)
            if pdf_page is None:
                pdf_page = extract_page_number_from_html(html_content, page_id)

            # Build a result item based on the new annotation structure
            if primary_option == "yes-public":
                # Public document - no PII info collected with new flow
                results["public_document"].append(
                    {
                        "page_id": page_id,
                        "link": link,
                        "pdf_path": pdf_path,
                        "pdf_page": pdf_page,
                        "pii_types": [],
                        "has_pii": False,
                        "description": "",
                        "prolific_pid": prolific_pid,
                    }
                )

            elif primary_option == "no-public":
                # Private document with potential PII
                private_pii_options = annotation.get("privatePiiOptions", [])
                other_desc = annotation.get("otherPrivateDesc", "")

                if not private_pii_options:
                    # No PII selected in a private document
                    results["private_document"].append(
                        {
                            "page_id": page_id,
                            "link": link,
                            "pdf_path": pdf_path,
                            "pdf_page": pdf_page,
                            "pii_types": [],
                            "has_pii": False,
                            "description": "",
                            "prolific_pid": prolific_pid,
                        }
                    )
                else:
                    # PII found in a private document
                    results["private_document"].append(
                        {
                            "page_id": page_id,
                            "link": link,
                            "pdf_path": pdf_path,
                            "pdf_page": pdf_page,
                            "pii_types": private_pii_options,
                            "has_pii": True,
                            "description": other_desc if "other" in private_pii_options else "",
                            "prolific_pid": prolific_pid,
                        }
                    )

            elif primary_option == "cannot-read":
                results["cannot_read"].append({"page_id": page_id, "link": link, "pdf_path": pdf_path, "pdf_page": pdf_page, "prolific_pid": prolific_pid})

            elif primary_option == "report-content":
                results["report_content"].append({"page_id": page_id, "link": link, "pdf_path": pdf_path, "pdf_page": pdf_page, "prolific_pid": prolific_pid})

            else:
                results["no_annotation"].append({"page_id": page_id, "link": link, "pdf_path": pdf_path, "pdf_page": pdf_page, "prolific_pid": prolific_pid})

    return results


def print_annotation_report(annotation_results: Dict[str, List[Dict[str, Any]]], pdf_s3_client=None):
    """Print a summary report of annotations."""
    total_pages = sum(len(items) for items in annotation_results.values())

    print("\n" + "=" * 80)
    print(f"ANNOTATION REPORT - Total Pages: {total_pages}")
    print("=" * 80)

    # Count pages with PII in public documents
    public_with_pii = [page for page in annotation_results["public_document"] if page.get("has_pii", False)]
    public_without_pii = [page for page in annotation_results["public_document"] if not page.get("has_pii", False)]

    # Count pages with PII in private documents
    private_with_pii = [page for page in annotation_results["private_document"] if page.get("has_pii", False)]
    private_without_pii = [page for page in annotation_results["private_document"] if not page.get("has_pii", False)]

    # Print summary statistics
    print("\nSummary:")
    print(
        f"  Public documents (total): {len(annotation_results['public_document'])} ({len(annotation_results['public_document'])/total_pages*100:.1f}% of all pages)"
    )
    print(f"    - With PII: {len(public_with_pii)} ({len(public_with_pii)/max(1, len(annotation_results['public_document']))*100:.1f}% of public docs)")
    print(
        f"    - Without PII: {len(public_without_pii)} ({len(public_without_pii)/max(1, len(annotation_results['public_document']))*100:.1f}% of public docs)"
    )

    print(
        f"  Private documents (total): {len(annotation_results['private_document'])} ({len(annotation_results['private_document'])/total_pages*100:.1f}% of all pages)"
    )
    print(f"    - With PII: {len(private_with_pii)} ({len(private_with_pii)/max(1, len(annotation_results['private_document']))*100:.1f}% of private docs)")
    print(
        f"    - Without PII: {len(private_without_pii)} ({len(private_without_pii)/max(1, len(annotation_results['private_document']))*100:.1f}% of private docs)"
    )

    print(f"  Unreadable pages: {len(annotation_results['cannot_read'])} ({len(annotation_results['cannot_read'])/total_pages*100:.1f}%)")
    print(f"  Pages with reported content: {len(annotation_results['report_content'])} ({len(annotation_results['report_content'])/total_pages*100:.1f}%)")
    print(f"  Pages without annotation: {len(annotation_results['no_annotation'])} ({len(annotation_results['no_annotation'])/total_pages*100:.1f}%)")

    # With the updated flow, there should be no public documents with PII flags
    # as we don't collect PII information for public documents anymore
    if public_with_pii:
        print("\nNote: With the current annotation flow, public documents should not have PII flags.")
        print(f"Found {len(public_with_pii)} public documents incorrectly marked with PII.")

    # Analyze PII types in private documents
    if private_with_pii:
        # Categorize the PII types for clearer reporting
        pii_categories = {
            "Identifiers": ["names", "email", "phone"],
            "PII requiring identifiers": ["addresses", "biographical", "location", "employment", "education", "medical"],
            "Always sensitive PII": ["government-id", "financial", "biometric", "login-info"],
        }

        # Dictionary to track all PII counts
        pii_counts_private = {}
        for page in private_with_pii:
            for pii_type in page.get("pii_types", []):
                pii_counts_private[pii_type] = pii_counts_private.get(pii_type, 0) + 1

        # Print categorized PII counts
        print("\nPII Types in Private Documents:")

        # Print each category
        for category, pii_types in pii_categories.items():
            print(f"\n  {category}:")
            for pii_type in pii_types:
                count = pii_counts_private.get(pii_type, 0)
                if count > 0:
                    print(f"    - {pii_type}: {count} ({count/len(private_with_pii)*100:.1f}%)")

        # Print any other PII types not in our categories (like "other")
        other_pii = [pii_type for pii_type in pii_counts_private.keys() if not any(pii_type in types for types in pii_categories.values())]
        if other_pii:
            print("\n  Other PII types:")
            for pii_type in other_pii:
                count = pii_counts_private.get(pii_type, 0)
                print(f"    - {pii_type}: {count} ({count/len(private_with_pii)*100:.1f}%)")

    # With the updated flow, there should be no public documents with PII flags
    # so we can remove this section
    if public_with_pii:
        print("\nNote: Public documents with PII flags found in old annotation results.")
        print("These are from annotation sessions before the workflow change and should be disregarded.")

    # Print detailed report for private documents with PII
    if private_with_pii:
        print("\nDetailed Report - Private Documents with PII:")
        print("-" * 80)
        for i, item in enumerate(private_with_pii, 1):
            pdf_path = item["pdf_path"]
            page_id = item["page_id"]

            # Get the actual PDF page number
            pdf_page = item.get("pdf_page")

            # Generate presigned URL with PDF page number if client is available
            presigned_url = None
            if pdf_s3_client and pdf_path.startswith("s3://"):
                presigned_url = create_presigned_url(pdf_s3_client, pdf_path)
                if presigned_url and pdf_page is not None:
                    presigned_url += f"#page={pdf_page}"

            print(f"{i}. PDF: {pdf_path}")
            print(f"   Page ID: {page_id}")
            print(f"   Link: {item['link']}#{page_id}")
            if presigned_url:
                print(f"   Presigned URL: {presigned_url}")
            print(f"   PII Types: {', '.join(item['pii_types'])}")
            if item.get("description"):
                print(f"   Description: {item['description']}")
            if item.get("prolific_pid"):
                print(f"   Prolific PID: {item['prolific_pid']}")
            print("-" * 80)

    print("\nReport complete.")


def read_and_process_results(args):
    """Read and process results from a previously generated CSV file."""
    try:
        # Read the CSV file
        links = []
        with open(args.read_results, "r") as f:
            for line in f:
                if line.strip():
                    links.append(line.strip())

        if not links:
            print(f"No tinyhost links found in {args.read_results}")
            return

        print(f"Found {len(links)} tinyhost links in {args.read_results}")

        # Set up PDF S3 client with profile if specified
        if args.pdf_profile:
            pdf_session = boto3.Session(profile_name=args.pdf_profile)
            pdf_s3_client = pdf_session.client("s3")
        else:
            pdf_s3_client = boto3.client("s3")

        # Fetch and process annotations
        annotations_by_link = []
        for link in tqdm(links, desc="Fetching annotations"):
            try:
                annotations, link_url, html_content = fetch_annotations(link)
                annotations_by_link.append((annotations, link_url, html_content))
            except Exception as e:
                print(f"Error processing {link}: {e}")

        # Process and categorize annotations
        annotation_results = process_annotations(annotations_by_link)

        # Print report with presigned URLs
        print_annotation_report(annotation_results, pdf_s3_client)

        # Save detailed report to file
        output_file = Path(args.output_dir) / "annotation_report.csv"
        print(f"\nSaving detailed report to {output_file}")

        with open(output_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Category", "PDF Path", "Page ID", "Link", "Presigned URL", "Document Type", "PII Types", "Description", "Prolific PID"])

            for category, items in annotation_results.items():
                for item in items:
                    pdf_path = item["pdf_path"]

                    # Get the actual PDF page number
                    pdf_page = item.get("pdf_page")

                    # Generate presigned URL with the PDF page number
                    presigned_url = ""
                    if pdf_path.startswith("s3://"):
                        url = create_presigned_url(pdf_s3_client, pdf_path)
                        if url and pdf_page is not None:
                            presigned_url = f"{url}#page={pdf_page}"
                        elif url:
                            presigned_url = url

                    if category == "public_document":
                        doc_type = "Public"
                        pii_types = ", ".join(item.get("pii_types", []))
                        description = item.get("description", "")
                    elif category == "private_document":
                        doc_type = "Private"
                        pii_types = ", ".join(item.get("pii_types", []))
                        description = item.get("description", "")
                    else:
                        doc_type = ""
                        pii_types = ""
                        description = ""

                    # Extract Prolific PID from the item if available
                    prolific_pid = item.get("prolific_pid", "")

                    writer.writerow(
                        [
                            category,
                            item["pdf_path"],
                            item["page_id"],
                            f"{item['link']}#{item['page_id']}",
                            presigned_url,
                            doc_type,
                            pii_types,
                            description,
                            prolific_pid,
                        ]
                    )

        print(f"Report saved to {output_file}")

    except Exception as e:
        print(f"Error processing results: {e}")
        raise


def main():
    args = parse_args()

    # Check if we're reading results from a previous run
    if args.read_results:
        read_and_process_results(args)
        return

    # Set up S3 clients
    s3_client = boto3.client("s3")

    # Set up PDF S3 client with profile if specified
    if args.pdf_profile:
        pdf_session = boto3.Session(profile_name=args.pdf_profile)
        pdf_s3_client = pdf_session.client("s3")
    else:
        pdf_s3_client = s3_client

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # List all result files
    print(f"Listing result files in {args.workspace}/results...")
    result_files = list_result_files(s3_client, args.workspace)
    print(f"Found {len(result_files)} result files")

    # Use ThreadPoolExecutor to parallelize the generation of sample sets
    output_files = []

    if args.repeats > 1:
        print(f"Using ThreadPoolExecutor with {min(args.max_workers, args.repeats)} workers")
        with ThreadPoolExecutor(max_workers=min(args.max_workers, args.repeats)) as executor:
            futures = []
            for i in range(args.repeats):
                future = executor.submit(generate_sample_set, args, i, s3_client, pdf_s3_client, result_files)
                futures.append(future)

            # Wait for all futures to complete and collect results
            for future in futures:
                try:
                    output_filename = future.result()
                    output_files.append(output_filename)
                    print(f"Completed generation of {output_filename}")
                except Exception as e:
                    print(f"Error generating sample set: {e}")
    else:
        # If only one repeat, just run it directly
        output_filename = generate_sample_set(args, 0, s3_client, pdf_s3_client, result_files)
        output_files.append(output_filename)

    # Now upload each resulting file into tinyhost
    print("Generated all files, uploading tinyhost links now")
    links = []
    for output_filename in output_files:
        link = tinyhost.tinyhost([str(output_filename)])[0]
        links.append(link)
        print(link)

    # Create CSV file with just the tinyhost links, one per line
    csv_path = args.prolific_csv
    print(f"Writing tinyhost links to {csv_path}")
    with open(csv_path, "w", newline="") as csvfile:
        for link in links:
            csvfile.write(f"{link}\n")

    print(f"Tinyhost links written to {csv_path}")


if __name__ == "__main__":
    main()
