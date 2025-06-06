"""
Plot for OCR performance vs cost Pareto frontier figure for NeurIPS paper.

Invocation:
    python scripts/pareto_plot.py .
"""

import argparse
import os

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd
from matplotlib import font_manager

# Parse arguments
ap = argparse.ArgumentParser()
ap.add_argument("output_dir", type=str, help="Path to the output directory")
ap.add_argument(
    "--font-path",
    type=str,
    help="Path to the font file",
    default=None,
)
args = ap.parse_args()

# Add custom font if provided
if args.font_path:
    font_manager.fontManager.addfont(args.font_path)
    plt.rcParams["font.family"] = "Manrope"
    plt.rcParams["font.weight"] = "medium"

# Ensure output directory exists
os.makedirs(args.output_dir, exist_ok=True)
OUTPUT_PATHS = [f"{args.output_dir}/ocr_pareto.pdf", f"{args.output_dir}/ocr_pareto.png"]
# Define column names
MODEL_COLUMN_NAME = "Model"
CATEGORY_COLUMN_NAME = "Category"
COST_COLUMN_NAME = "Cost_Per_Million"
PERF_COLUMN_NAME = "Performance"
COLOR_COLUMN_NAME = "Color"
OFFSET_COLUMN_NAME = "Label_Offset"
MARKER_COLUMN_NAME = "Marker"
# Define colors
DARK_BLUE = "#093235"
DARK_GREEN = "#255457"
LIGHT_GREEN = "#6FE0BA"
LIGHT_PINK = "#F697C4"
DARK_PINK = "#F0529C"
YELLOW = "#fff500"
ORANGE = "#f65834"
DARK_TEAL = "#0a3235"
OFF_WHITE = "#faf2e9"
TEAL = "#105257"
PURPLE = "#b11be8"
GREEN = "#0fcb8c"

# Create dataframe with OCR model data
data = {
    MODEL_COLUMN_NAME: [
        "GPT-4o",
        "GPT-4o (Batch)",
        "Mistral OCR",
        "MinerU",
        "Gemini Flash 2",
        "Gemini Flash 2 (Batch)",
        "Marker v1.7.4",
        "Ours",
        "Qwen 2 VL",
        "Qwen 2.5 VL",
    ],
    COST_COLUMN_NAME: [12480, 6240, 1000, 596, 499, 249, 75, 178, 178, 178],  # Same cost as Ours  # Same cost as Ours
    PERF_COLUMN_NAME: [
        69.9,  # GPT-4o (Anchored)
        69.9,  # Same performance for batch
        72.0,  # Mistral OCR API
        61.5,  # MinerU
        63.8,  # Gemini Flash 2 (Anchored)
        63.8,  # Same performance for batch
        70.0,  # marker v1.7.4 base
        77.4,  # Ours (performance is the same across hardware)
        31.5,  # Qwen2VL
        65.5,  # Qwen2.5VL
    ],
}

df = pd.DataFrame(data)

# Add category information
model_categories = {
    "GPT-4o": "Commercial VLM",
    "GPT-4o (Batch)": "Commercial VLM",
    "Mistral OCR": "Commercial API Tool",
    "MinerU": "Open Source Tool",
    "Gemini Flash 2": "Commercial VLM",
    "Gemini Flash 2 (Batch)": "Commercial VLM",
    "Marker v1.7.4": "Open Source Tool",
    "Ours": "Ours",
    "Qwen 2 VL": "Open VLM",
    "Qwen 2.5 VL": "Open VLM",
}

df[CATEGORY_COLUMN_NAME] = df[MODEL_COLUMN_NAME].map(model_categories)

# Category colors
category_colors = {"Commercial API Tool": DARK_GREEN, "Commercial VLM": DARK_GREEN, "Open Source Tool": PURPLE, "Ours": DARK_PINK, "Open VLM": PURPLE}

df[COLOR_COLUMN_NAME] = df[CATEGORY_COLUMN_NAME].map(category_colors)

# Define marker types
category_markers = {"Commercial API Tool": "o", "Commercial VLM": "^", "Open Source Tool": "o", "Ours": "*", "Open VLM": "^"}

df[MARKER_COLUMN_NAME] = df[CATEGORY_COLUMN_NAME].map(category_markers)

# Define marker sizes - increased sizes
category_marker_sizes = {"Commercial API Tool": 120, "Commercial VLM": 120, "Open Source Tool": 140, "Ours": 300, "Open VLM": 140}

# Define text colors
category_text_colors = {
    "Commercial API Tool": DARK_GREEN,
    "Commercial VLM": DARK_GREEN,
    "Open Source Tool": PURPLE,  # darker purple
    "Ours": DARK_PINK,  # darker pink
    "Open VLM": PURPLE,  # darker purple
}

# Label offsets for better readability
model_label_offsets = {
    "GPT-4o": [-35, 10],
    "GPT-4o (Batch)": [-50, 10],
    "Mistral OCR": [-20, 10],
    "MinerU": [-15, -20],
    "Gemini Flash 2": [-10, 10],
    "Gemini Flash 2 (Batch)": [-50, -15],
    "Marker v1.7.4": [-35, -20],
    "Ours": [-20, 10],
    "Qwen 2 VL": [-35, 10],
    "Qwen 2.5 VL": [-35, 10],
}

df[OFFSET_COLUMN_NAME] = df[MODEL_COLUMN_NAME].map(model_label_offsets)

# Create the plot
plt.figure(figsize=(10, 6))

# Plot each category
categories = df[CATEGORY_COLUMN_NAME].unique()
for category in categories:
    mask = df[CATEGORY_COLUMN_NAME] == category
    data = df[mask]
    plt.scatter(
        data[COST_COLUMN_NAME],
        data[PERF_COLUMN_NAME],
        label=category,
        c=data[COLOR_COLUMN_NAME],
        marker=category_markers[category],
        alpha=1.0,
        s=category_marker_sizes[category],
    )

# Add labels for each point with increased font size
FONTSIZE = 12  # Increased from 9
for idx, row in df.iterrows():
    plt.annotate(
        row[MODEL_COLUMN_NAME],
        (row[COST_COLUMN_NAME], row[PERF_COLUMN_NAME]),
        xytext=row[OFFSET_COLUMN_NAME],
        textcoords="offset points",
        fontsize=FONTSIZE,
        alpha=1.0,
        weight="medium",
        color=category_text_colors[row[CATEGORY_COLUMN_NAME]],
    )

# Set up axes
plt.ylim(25, 85)  # Set y-axis limits from 25 to 85 to include Qwen2VL
plt.xlim(100, 15000)
plt.xscale("log")  # Use log scale for cost
plt.grid(True, which="both", ls=":", color=TEAL, alpha=0.2)


# Format y-axis to show percentages without scientific notation
def percent_formatter(y, pos):
    return f"{y:.1f}%"


plt.gca().yaxis.set_major_formatter(ticker.FuncFormatter(percent_formatter))


# Format x-axis to show dollar amounts
def dollar_formatter(x, pos):
    return f"${x:,.0f}"


# Set specific x-axis ticks with increased font size
plt.gca().xaxis.set_major_formatter(ticker.FuncFormatter(dollar_formatter))
plt.gca().set_xticks([100, 200, 300, 500, 1000, 2000, 3000, 5000, 10000])
plt.xticks(fontsize=12)  # Increased tick font size
plt.yticks(fontsize=12)  # Increased tick font size

# Add labels and title with increased font size
plt.xlabel("Cost per Million Pages (USD, log scale)", fontsize=16, weight="medium")
plt.ylabel("Overall Performance (Pass Rate %)", fontsize=16, weight="medium")
# plt.title("OCR Engines: Performance vs. Cost", fontsize=12, weight="medium")

# Remove spines
plt.gca().spines["top"].set_visible(False)
plt.gca().spines["right"].set_visible(False)

# Add the legend with custom ordering and increased font size
handles, labels = plt.gca().get_legend_handles_labels()
desired_order = ["Ours", "Open Source Tool", "Open VLM", "Commercial API Tool", "Commercial VLM"]
label_to_handle = dict(zip(labels, handles))
ordered_handles = [label_to_handle[label] for label in desired_order if label in label_to_handle]
ordered_labels = [label for label in desired_order if label in labels]

plt.legend(
    ordered_handles, ordered_labels, loc="lower right", fontsize=12, frameon=True, framealpha=0.9, edgecolor=TEAL, facecolor="white"  # Increased from 10
)

# Adjust layout
plt.tight_layout()

# Save the figure
for output_path in OUTPUT_PATHS:
    plt.savefig(output_path, dpi=300, bbox_inches="tight")

print(f"Plot saved to {', '.join(OUTPUT_PATHS)}")
