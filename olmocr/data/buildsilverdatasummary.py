
import os
import re
import csv
import json
import random
import sqlite3
import argparse

from tqdm import tqdm
from typing import Optional
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

from urllib.parse import urlparse


def parse_pdf_hash(pretty_pdf_path: str) -> Optional[str]:
    pattern = r"s3://ai2-s2-pdfs/([a-f0-9]{4})/([a-f0-9]+)\.pdf-\d+"
    match = re.match(pattern, pretty_pdf_path)
    if match:
        return match.group(1) + match.group(2)
    return None


def cache_athena_csv_to_db(athena_csv_path: str) -> str:
    db_path = athena_csv_path + ".db"

    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA synchronous = OFF;")
        cursor.execute("PRAGMA journal_mode = MEMORY;")

        cursor.execute(
            """
            CREATE TABLE pdf_mapping (
                pdf_hash TEXT PRIMARY KEY,
                uri TEXT
            )
            """
        )

        with open(athena_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            batch = []
            for row in tqdm(reader):
                batch.append((row["distinct_pdf_hash"], row["uri"]))
                if len(batch) == 1000:
                    cursor.executemany("INSERT INTO pdf_mapping (pdf_hash, uri) VALUES (?, ?)", batch)
                    conn.commit()
                    batch = []

            if batch:
                cursor.executemany("INSERT INTO pdf_mapping (pdf_hash, uri) VALUES (?, ?)", batch)
                conn.commit()

        conn.close()

    return db_path


def get_uri_from_db(db_path: str, pdf_hash: str) -> Optional[str]:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT uri FROM pdf_mapping WHERE pdf_hash = ?", (pdf_hash,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def process_file(filepath, db_path):
    results = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            custom_id = data.get("custom_id")
            if not custom_id:
                continue

            pdf_hash = parse_pdf_hash(custom_id)
            if not pdf_hash:
                continue

            uri = get_uri_from_db(db_path, pdf_hash)

            domain = None
            if uri:
                parsed = urlparse(uri)
                domain = parsed.netloc

            results.append((custom_id, uri, domain))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Review silver dataset and provide summary statistics based on source URL and also provide a few data samples for review."
    )
    parser.add_argument(
        "--input",
        type=str,
        default="openai_batch_data",
        help="Input folder, which is the output of the buildsilver.py script",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="openai_batch_data_summary",
        help="Output destination (folder)",
    )
    parser.add_argument(
        "--athena-csv",
        type=str,
        default="/home/ubuntu/s2pdf_url_data/c974870d-3b06-4793-9a62-d46d38e2c8b2.csv",
        help="CSV file that maps pdf_hash to uri",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=20,
        help="How many sample rows to include in the sample CSV",
    )

    args    = parser.parse_args()

    db_path = cache_athena_csv_to_db(args.athena_csv)

    all_rows  = []
    filepaths = [os.path.join(args.input, filename) for filename in os.listdir(args.input) if filename.endswith(".jsonl")]

    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(process_file, filepath, db_path): filepath for filepath in filepaths}

        for future in tqdm(as_completed(future_to_file), total=len(filepaths)):
            try:
                results = future.result()
                all_rows.extend(results)
            except Exception as e:
                print(f"Error processing file: {future_to_file[future]}\n{e}")

    os.makedirs(args.output, exist_ok=True)

    output_csv_path = os.path.join(args.output, "custom_id_to_url.csv")
    with open(output_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["custom_id", "uri", "domain"])
        for cid, uri, domain in all_rows:
            writer.writerow([cid, uri if uri else "", domain if domain else ""])

    domain_counter: Counter[str] = Counter()
    for _, _, domain in all_rows:
        if domain:
            domain_counter[domain] += 1

    most_common_domains = domain_counter.most_common(1000)
    domain_csv_path = os.path.join(args.output, "top_1000_domains.csv")
    with open(domain_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["domain", "count"])
        for domain, count in most_common_domains:
            writer.writerow([domain, count])

    sample_size = min(args.sample_size, len(all_rows))
    sample_rows = random.sample(all_rows, sample_size) if all_rows else []
    sample_csv_path = os.path.join(args.output, "data_samples.csv")
    with open(sample_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["custom_id", "uri", "domain"])
        for cid, uri, domain in sample_rows:
            writer.writerow([cid, uri if uri else "", domain if domain else ""])

    print(f"Summary files written to: {args.output}")
    print(f" - Full mapping: {output_csv_path}")
    print(f" - Top domains: {domain_csv_path}")
    print(f" - Samples: {sample_csv_path}")


if __name__ == "__main__":
    main()
