import os
import boto3
import random
import tempfile

from tqdm import tqdm
from jinja2 import Template
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

from urllib.parse import urlparse
from olmocr.data.renderpdf import render_pdf_to_base64png

session   = boto3.Session(profile_name="s2")
s3_client = session.client("s3")


def generate_diff_html(a, b):
    """
    Generates HTML with differences between strings a and b.
    Additions in 'b' are highlighted in green, deletions from 'a' are highlighted in red.
    """
    seq_matcher = SequenceMatcher(None, a, b)
    output_html = ""
    for opcode, a0, a1, b0, b1 in seq_matcher.get_opcodes():
        if opcode == "equal":
            output_html += a[a0:a1]
        elif opcode == "insert":
            output_html += f"<span class='added'>{b[b0:b1]}</span>"
        elif opcode == "delete":
            output_html += f"<span class='removed'>{a[a0:a1]}</span>"
        elif opcode == "replace":
            output_html += f"<span class='removed'>{a[a0:a1]}</span><span class='added'>{b[b0:b1]}</span>"
    return output_html


def process_entry(i, entry):
    # Randomly decide whether to display gold on the left or right
    if random.choice([True, False]):
        left_text, right_text = entry["gold_text"], entry["eval_text"]
        left_class, right_class = "gold", "eval"
        left_metadata, right_metadata = entry.get("gold_metadata", ""), entry.get("eval_metadata", "")
    else:
        left_text, right_text = entry["eval_text"], entry["gold_text"]
        left_class, right_class = "eval", "gold"
        left_metadata, right_metadata = entry.get("eval_metadata", ""), entry.get("gold_metadata", "")

    # Generate diff for right_text compared to left_text
    diff_html = generate_diff_html(left_text, right_text)

    left_text = "<p>" + left_text.replace("\n", "</p><p>") + "</p>"
    right_text = "<p>" + right_text.replace("\n", "</p><p>") + "</p>"
    diff_html = "<p>" + diff_html.replace("\n", "</p><p>") + "</p>"

    parsed_url = urlparse(entry["s3_path"])
    bucket = parsed_url.netloc
    s3_key = parsed_url.path.lstrip("/")
    signed_pdf_link = s3_client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": s3_key}, ExpiresIn=604800)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        pdf_path = tmp_pdf.name
        bucket, key = entry["s3_path"].replace("s3://", "").split("/", 1)
        s3_client.download_file(bucket, key, pdf_path)
        page_image_base64 = render_pdf_to_base64png(tmp_pdf.name, entry["page"], target_longest_image_dim=1024)

    return {
        "entry_id": i,
        "page_image": page_image_base64,
        "s3_path": entry["s3_path"],
        "page": entry["page"],
        "key": entry.get("entry_key", entry["s3_path"] + "_" + str(entry["page"])),
        "alignment": entry["alignment"],
        "signed_pdf_link": signed_pdf_link,
        "left_metadata": left_metadata,
        "right_metadata": right_metadata,
        "left_text": left_text,
        "right_text": right_text,
        "diff_text": diff_html,
        "left_class": left_class,
        "right_class": right_class,
        "gold_class": "gold" if left_class == "gold" else "eval",
        "eval_class": "eval" if right_class == "eval" else "gold",
    }


def create_review_html(data, filename="review_page.html"):
    # Load the Jinja2 template from the file
    template_path = os.path.join(os.path.dirname(__file__), "evalhtml_template.html")
    with open(template_path, "r") as f:
        template = Template(f.read())

    entries = []
    with ThreadPoolExecutor() as executor:
        # Submit tasks to the executor
        futures = [executor.submit(process_entry, i, entry) for i, entry in enumerate(data)]

        # Process the results as they are completed
        for future in tqdm(futures):
            entries.append(future.result())

    # Render the template with the entries
    final_html = template.render(entries=entries)

    # Write the HTML content to the specified file
    with open(filename, "w") as f:
        f.write(final_html)

    print(f"HTML file '{filename}' created successfully!")
