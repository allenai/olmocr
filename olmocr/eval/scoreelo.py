import os
import csv
import re
from collections import defaultdict
from typing import Any, DefaultDict
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import requests  # type: ignore


def fetch_review_page_html(url):
    """
    Fetch the HTML from the Tinyhost URL.
    """
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.text


def extract_presigned_url(html):
    """
    Given the HTML of the page, extract the `presignedGetUrl`.
    Returns None if not found.
    """
    match = re.search(r"const presignedGetUrl = \"(.*?)\";", html)
    if not match:
        return None
    return match.group(1)


def fetch_presigned_datastore(presigned_url):
    """
    Fetch the JSON datastore from the presigned URL.
    Returns a dict. If any error or no content, returns {}.
    """
    try:
        # Clean up the presigned URL (sometimes the signature may need re-encoding)
        url_parts = urlsplit(presigned_url)
        query_params = parse_qs(url_parts.query)
        encoded_query = urlencode(query_params, doseq=True)
        cleaned_url = urlunsplit((url_parts.scheme, url_parts.netloc, url_parts.path, encoded_query, url_parts.fragment))

        resp = requests.get(cleaned_url, headers={"Host": url_parts.netloc, "User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error fetching datastore from {presigned_url}: {e}")
        return {}


def sanitize_key(key):
    return re.sub(r"[^a-zA-Z0-9-_]", "_", key)


def parse_entry_metadata(html):
    """
    Parse each .entry block from the HTML to figure out:
      - data-entry-id
      - left-metadata
      - right-metadata
      - classes that might indicate 'gold', 'eval', etc.
    Returns a dict:
      {
        entry_id_1: {
          'left_metadata': str,
          'right_metadata': str,
          'class_str': str,
        },
        ...
      }

    Note: This uses a regex that looks for something like:
        <div class="entry gold eval" data-entry-id="..."
             data-left-metadata="..." data-right-metadata="...">
    """
    pattern = re.compile(
        r'<div\s+class="entry([^"]*)"\s+data-entry-id="([^"]+)"\s+data-left-metadata="([^"]+)"\s+data-right-metadata="([^"]+)"', re.DOTALL | re.MULTILINE
    )

    entries = {}
    for m in pattern.finditer(html):
        class_str = m.group(1).strip()  # e.g. " gold eval"
        entry_id = m.group(2).strip()
        left_md = m.group(3).strip()
        right_md = m.group(4).strip()

        # Transform the HTML's data-entry-id to match the JS datastore keys:
        entry_id = sanitize_key(entry_id)

        entries[entry_id] = {
            "class_str": class_str,
            "left_metadata": left_md,
            "right_metadata": right_md,
        }
    return entries


def build_comparison_report(entries_dict, datastore):
    """
    Build a comparison report showing how often each type of method
    beats each other type of method, based on user votes in the datastore.

    We assume:
      - If user vote is 'left', then left_metadata's method "wins".
      - If user vote is 'right', then right_metadata's method "wins".
      - If user vote is 'both_good', 'both_bad', or 'invalid_pdf',
        we do not count it as a direct matchup.

    Returns a structure:
      comparisons[(A, B)] = [A_wins, B_wins],
        where A < B lexicographically in that tuple.
    """
    comparisons: DefaultDict[Any, list[int]] = defaultdict(lambda: [0, 0])

    for entry_id, vote in datastore.items():
        if entry_id not in entries_dict:
            # No matching <div> found for this key in the HTML
            continue

        left_method = entries_dict[entry_id]["left_metadata"]
        right_method = entries_dict[entry_id]["right_metadata"]

        if left_method == right_method:
            # Same "method" on both sides => skip
            continue

        if vote == "left":
            # left_method beats right_method
            pair = tuple(sorted([left_method, right_method]))
            if pair[0] == left_method:
                comparisons[pair][0] += 1
            else:
                comparisons[pair][1] += 1

        elif vote == "right":
            # right_method beats left_method
            pair = tuple(sorted([left_method, right_method]))
            if pair[0] == right_method:
                comparisons[pair][0] += 1
            else:
                comparisons[pair][1] += 1

        else:
            # "both_good", "both_bad", "invalid_pdf", etc. -> not counted
            pass

    return comparisons


def elo_update(ratingA, ratingB, scoreA, scoreB, k=32):
    """
    Perform a single ELO update for a match between A and B.
      - ratingA, ratingB are current ELO ratings of A and B.
      - scoreA, scoreB in {0 or 1} (1 if the player is the winner, 0 if loser).
      - Returns (new_ratingA, new_ratingB).
    """
    # Expected scores for each player
    expectedA = 1 / (1 + 10 ** ((ratingB - ratingA) / 400))
    expectedB = 1 / (1 + 10 ** ((ratingA - ratingB) / 400))

    new_ratingA = ratingA + k * (scoreA - expectedA)
    new_ratingB = ratingB + k * (scoreB - expectedB)
    return new_ratingA, new_ratingB


def compute_elo_arena(comparisons, k=32, initial_rating=1500):
    """
    Given the aggregated comparisons dict:
      comparisons[(A, B)] = [A_wins, B_wins]

    1) Collect all unique methods.
    2) Initialize them to initial_rating (1500).
    3) For each pair (A, B), apply A_wins times the scenario
       "A beats B" -> ELO update
       B_wins times the scenario "B beats A" -> ELO update

    Because we don't have a strict order of matches, we just
    apply them in some consistent but arbitrary order.

    Returns a dict { method_name: final_elo_rating }
    """
    # 1) Collect all unique methods
    methods = set()
    for A, B in comparisons.keys():
        methods.add(A)
        methods.add(B)

    # 2) Initialize ratings
    ratings = {m: float(initial_rating) for m in methods}

    # 3) Walk through each pair
    for (A, B), (A_wins, B_wins) in comparisons.items():
        for _ in range(A_wins):
            # A beats B
            oldA = ratings[A]
            oldB = ratings[B]
            newA, newB = elo_update(oldA, oldB, 1, 0, k=k)
            ratings[A] = newA
            ratings[B] = newB

        for _ in range(B_wins):
            # B beats A
            oldA = ratings[A]
            oldB = ratings[B]
            newA, newB = elo_update(oldA, oldB, 0, 1, k=k)
            ratings[A] = newA
            ratings[B] = newB

    return ratings


def make_report(urls):
    """
    Main function that:
      - Fetches each HTML page
      - Extracts presignedGetUrl
      - Fetches the JSON datastore
      - Parses .entry blocks for metadata
      - Produces an overall "win rate" report for each method vs method
      - Produces an ELO arena result for each method
    """
    # Aggregate all entries from all URLs into a single dict
    # so each entry_id is unique across all pages (they usually are).
    master_entries_dict = {}
    master_datastore = {}

    for url in urls:
        try:
            html = fetch_review_page_html(url)
        except Exception as e:
            print(f"Error fetching HTML from {url}: {e}")
            continue

        # Extract the presignedGetUrl
        presigned_url = extract_presigned_url(html)
        if not presigned_url:
            print(f"Warning: Could not find presignedGetUrl in {url}")
            continue

        # Fetch the datastore
        datastore = fetch_presigned_datastore(presigned_url)

        # Parse the HTML for entry metadata
        entries_dict = parse_entry_metadata(html)

        # Merge into master
        for k, v in entries_dict.items():
            master_entries_dict[k] = v
        for k, v in datastore.items():
            master_datastore[k] = v

    # Now build the comparison report
    comparisons = build_comparison_report(master_entries_dict, master_datastore)

    print("=== Pairwise Win/Loss Report ===")
    if not comparisons:
        print("No head-to-head comparisons found (did not find left/right votes).")
        return

    # Print out each matchup
    for (A, B), (A_wins, B_wins) in comparisons.items():
        total = A_wins + B_wins
        A_rate = A_wins / total * 100 if total else 0
        B_rate = B_wins / total * 100 if total else 0
        print(f"{A} vs {B}: " f"{A} wins={A_wins} ({A_rate:.1f}%), " f"{B} wins={B_wins} ({B_rate:.1f}%)")

    # -- ADDED: Write the same data to scoreelo.csv
    with open("scoreelo.csv", "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["MethodA", "MethodB", "A_wins", "B_wins", "A_rate(%)", "B_rate(%)"])
        for (A, B), (A_wins, B_wins) in comparisons.items():
            total = A_wins + B_wins
            A_rate = A_wins / total * 100 if total else 0
            B_rate = B_wins / total * 100 if total else 0
            writer.writerow([A, B, A_wins, B_wins, f"{A_rate:.1f}", f"{B_rate:.1f}"])

    # ==== ELO Arena ====
    elo_ratings = compute_elo_arena(comparisons, k=32, initial_rating=1500)

    # Sort methods by final rating descending
    sorted_ratings = sorted(elo_ratings.items(), key=lambda x: x[1], reverse=True)

    print("\n=== ELO Arena Results ===")
    for method, rating in sorted_ratings:
        print(f"{method}: {rating:.2f}")


if __name__ == "__main__":
    # Example usage
    # AWS credentials should be provided via environment variables
    urls = [
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_0-ff70abb8f517.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=NarEyyCfvusCh%2FHdB47VfHOnnBs%3D&Expires=1738359221",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_1-0800f9af46cf.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=ncTWAu5rSndBJJsU26HRYDaK6i8%3D&Expires=1738359222",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_10-f7081f6ca6f9.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=gYX8yjGyYshRqXGgdsX17%2Fdi9Ig%3D&Expires=1738359223",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_11-355dc69335bc.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=7%2Bc5qoa8Tbk06z0VcvJiIIVAz9M%3D&Expires=1738359224",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_12-95fce9bf0c18.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=fw4PBo0LnxikmLZ8xH%2BGD%2F%2BhXMU%3D&Expires=1738359225",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_13-f88f7d7482bf.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=yXkQp9oFDtroKgiO50EwpYdGLcA%3D&Expires=1738359226",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_14-8ac0b974bfd5.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=EgZTpj1%2FdzMBUgd%2BX4pVZ1Sp%2FrA%3D&Expires=1738359226",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_15-e3136188de5c.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=YKhAv4unNIlRcerQAaHN4kjc4qI%3D&Expires=1738359227",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_16-2c5abde50d49.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=Mj8%2BK5ISKzAYQFeYvmzTgCPcRwA%3D&Expires=1738359228",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_17-f13132a4cdcc.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=%2FHuzw2cjJ4oFm91UXojPnGzYi8Q%3D&Expires=1738359229",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_18-25070f2aa05e.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=ctd%2BUIM%2FxryJm%2FcwA%2BRZ%2FbRzBp8%3D&Expires=1738359230",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_19-d436ee434162.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=jVdFKobIoHlbTQ7zziG%2BXiIQ0Fo%3D&Expires=1738359230",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_2-a5ece743fd31.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=K8hIrjWtvo4SLVQrOB8TiXLgNJk%3D&Expires=1738359231",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_3-9ce03af05f51.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=T0fLGSH%2Bv%2F19veqbxnLxoSf7gVA%3D&Expires=1738359232",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_4-94eec18f8027.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=u2R1LundKpfnAUCcD%2BdGHA6uIR0%3D&Expires=1738359233",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_5-377d0a7d8f5a.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=5R38ZQAR9ew5x%2BRmMVQbTqbfVh0%3D&Expires=1738359234",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_6-537b22646a26.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=PLOELum1qzOXW8Cm5rfZphlFeMw%3D&Expires=1738359235",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_7-a4a7dcb08f20.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=DxPHukGXEpPrEPL6TF9QBKPE1Xg%3D&Expires=1738359236",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_8-48a71c829863.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=TjEINKj69HdmXsKY59k4f3PieeM%3D&Expires=1738359237",
        "https://jakep-tinyhost.s3.amazonaws.com/review_page_9-8557438928c3.html?AWSAccessKeyId=AKIASHLPW4FEVZOPGK46&Signature=F7sQxw5A%2FDOcOaa%2FQSeqepH0PQc%3D&Expires=1738359238",
    ]
    # import tinyhost

    # print(tinyhost.tinyhost(urls))

    make_report(urls)
