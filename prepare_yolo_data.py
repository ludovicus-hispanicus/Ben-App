"""
Prepare YOLO dataset from PDF pages using existing layout detection or Docling.

Usage:
    python prepare_yolo_data.py <pdf_path> [first_page] [last_page] [--use-existing]

Example:
    python prepare_yolo_data.py "Q_II 886-931.pdf" 1 10
    python prepare_yolo_data.py "Q_II 886-931.pdf" 1 10 --use-existing

Options:
    --use-existing  Use existing layout_summary.json instead of running Docling (faster)

Classes:
    0: entry      - main dictionary entry block
    1: subentry   - sub-entry within an entry
    2: guidewords - running header at top of page
    3: page_number - page number
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from pdf2image import convert_from_path
from PIL import Image

# Check for --use-existing flag
USE_EXISTING = "--use-existing" in sys.argv
if USE_EXISTING:
    sys.argv.remove("--use-existing")

# Try to import docling for fresh layout detection
HAS_DOCLING = False
if not USE_EXISTING:
    try:
        from docling.document_converter import DocumentConverter
        HAS_DOCLING = True
    except ImportError:
        print("Warning: docling not available, will use existing layout_summary.json if present")


# YOLO class definitions
CLASSES = ["entry", "subentry", "guidewords", "page_number"]
CLASS_MAP = {name: idx for idx, name in enumerate(CLASSES)}

# Patterns for classification
HEADWORD_PATTERN = re.compile(
    r"^[a-zA-ZšṣṭḫāēīūŠṢṬḪĀĒĪŪ][a-zA-ZšṣṭḫāēīūŠṢṬḪĀĒĪŪ/]*"
    r"(?:\([mf]\))?"
    r"\s*(?:I{1,3}V?|IV|V)?"
    r"\s+"
)
SUB_ENTRY_PATTERN = re.compile(r"^\d+\)\s|^[a-z]\)\s")
PAGE_NUMBER_PATTERN = re.compile(r"^\d{1,4}$")


def compute_iou(box_a, box_b):
    """Compute IoU for two [x0, y0, x1, y1] boxes."""
    x0 = max(box_a[0], box_b[0])
    y0 = max(box_a[1], box_b[1])
    x1 = min(box_a[2], box_b[2])
    y1 = min(box_a[3], box_b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    if inter == 0:
        return 0.0
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def deduplicate_regions(regions, iou_threshold=0.9):
    """Remove duplicate regions with high IoU on the same page."""
    by_page = defaultdict(list)
    for r in regions:
        by_page[r["page"]].append(r)

    deduplicated = []
    for page, items in by_page.items():
        keep = []
        for item in items:
            is_dup = False
            for kept in keep:
                if compute_iou(item["bbox_topleft"], kept["bbox_topleft"]) > iou_threshold:
                    is_dup = True
                    break
            if not is_dup:
                keep.append(item)
        deduplicated.extend(keep)
    return deduplicated


def classify_to_yolo_class(entry, page_height=2075):
    """Map region to YOLO class index based on text/position."""
    text = entry.get("text", "").strip()
    label = entry.get("label", "")
    bbox = entry.get("bbox_topleft", [0, 0, 0, 0])
    y_top = bbox[1]

    # Page number: at top, very short numeric text
    if y_top < 100 and PAGE_NUMBER_PATTERN.match(text):
        return CLASS_MAP["page_number"]

    # Guidewords: at very top of page (running headers), short text
    if y_top < 165 and len(text) < 50 and not PAGE_NUMBER_PATTERN.match(text):
        return CLASS_MAP["guidewords"]

    # Sub-entry: starts with numbered or lettered pattern
    if SUB_ENTRY_PATTERN.match(text):
        return CLASS_MAP["subentry"]

    # Everything else is an entry (headword, table, text blocks, etc.)
    return CLASS_MAP["entry"]


def bbox_to_yolo(bbox, img_width, img_height):
    """
    Convert [x0, y0, x1, y1] bbox to YOLO format [x_center, y_center, width, height].
    All values normalized to 0-1.
    """
    x0, y0, x1, y1 = bbox
    x_center = (x0 + x1) / 2.0 / img_width
    y_center = (y0 + y1) / 2.0 / img_height
    width = (x1 - x0) / img_width
    height = (y1 - y0) / img_height

    # Clamp to valid range
    x_center = max(0, min(1, x_center))
    y_center = max(0, min(1, y_center))
    width = max(0, min(1, width))
    height = max(0, min(1, height))

    return x_center, y_center, width, height


def run_docling_detection(pdf_path, first_page, last_page):
    """Run Docling layout detection on PDF pages."""
    if not HAS_DOCLING:
        return None

    print(f"Running Docling layout detection on pages {first_page}-{last_page}...")
    converter = DocumentConverter()
    result = converter.convert(pdf_path)

    regions = []
    page_images = convert_from_path(pdf_path, first_page=first_page, last_page=last_page)

    for page_idx, page_img in enumerate(page_images):
        page_no = first_page + page_idx
        img_width, img_height = page_img.size
        mid_x = img_width / 2

        # Get document items for this page
        for item in result.document.iterate_items():
            if hasattr(item, 'prov') and item.prov:
                for prov in item.prov:
                    if prov.page_no == page_no:
                        bbox = prov.bbox
                        # Convert to top-left origin
                        x0, y0, x1, y1 = bbox.l, img_height - bbox.t, bbox.r, img_height - bbox.b
                        if y0 > y1:
                            y0, y1 = y1, y0

                        text = ""
                        if hasattr(item, 'text'):
                            text = item.text[:80] if item.text else ""

                        label = item.label if hasattr(item, 'label') else "text"
                        column = "left" if (x0 + x1) / 2 < mid_x else "right"

                        regions.append({
                            "page": page_no,
                            "label": label,
                            "bbox_topleft": [x0, y0, x1, y1],
                            "text": text,
                            "column": column
                        })

    return regions


def load_existing_layout(layout_dir="layout_test_results"):
    """Load existing layout detection results."""
    json_path = os.path.join(layout_dir, "layout_summary.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def setup_dataset_dirs(output_dir="yolo_dataset"):
    """Create YOLO dataset directory structure."""
    dirs = [
        os.path.join(output_dir, "images", "train"),
        os.path.join(output_dir, "images", "val"),
        os.path.join(output_dir, "labels", "train"),
        os.path.join(output_dir, "labels", "val"),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return output_dir


def create_dataset_yaml(output_dir):
    """Create dataset.yaml for YOLOv8."""
    yaml_content = f"""# YOLO Dataset Configuration
path: {os.path.abspath(output_dir)}
train: images/train
val: images/val

# Classes
names:
  0: entry
  1: subentry
  2: guidewords
  3: page_number

# Number of classes
nc: 4
"""
    yaml_path = os.path.join(output_dir, "dataset.yaml")
    with open(yaml_path, "w") as f:
        f.write(yaml_content)
    print(f"Created: {yaml_path}")

    # Also create classes.txt for annotation tools
    classes_path = os.path.join(output_dir, "classes.txt")
    with open(classes_path, "w") as f:
        f.write("\n".join(CLASSES))
    print(f"Created: {classes_path}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    pdf_path = sys.argv[1]
    first_page = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    last_page = int(sys.argv[3]) if len(sys.argv) > 3 else first_page + 2

    if not os.path.exists(pdf_path):
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)

    print(f"Preparing YOLO dataset from: {pdf_path} (pages {first_page}-{last_page})")

    # Setup directories
    output_dir = setup_dataset_dirs()

    # Get layout regions (try Docling first, fall back to existing)
    regions = run_docling_detection(pdf_path, first_page, last_page)
    if regions is None:
        print("Loading existing layout data...")
        regions = load_existing_layout()
        if regions is None:
            print("Error: No layout data available. Run test_layout.py first or install docling.")
            sys.exit(1)

    # Deduplicate
    regions = deduplicate_regions(regions)
    print(f"Total regions after deduplication: {len(regions)}")

    # Convert PDF pages to images
    print("Converting PDF pages to images...")
    page_images = convert_from_path(pdf_path, first_page=first_page, last_page=last_page)

    # Group regions by page
    by_page = defaultdict(list)
    for r in regions:
        if first_page <= r["page"] <= last_page:
            by_page[r["page"]].append(r)

    # Process each page
    for page_idx, page_img in enumerate(page_images):
        page_no = first_page + page_idx
        img_width, img_height = page_img.size

        # Save image
        img_filename = f"page_{page_no}.png"
        img_path = os.path.join(output_dir, "images", "train", img_filename)
        page_img.save(img_path)
        print(f"  Saved: {img_path}")

        # Generate YOLO labels
        label_filename = f"page_{page_no}.txt"
        label_path = os.path.join(output_dir, "labels", "train", label_filename)

        labels = []
        page_regions = by_page.get(page_no, [])

        for entry in page_regions:
            bbox = entry["bbox_topleft"]
            class_id = classify_to_yolo_class(entry, img_height)
            x_c, y_c, w, h = bbox_to_yolo(bbox, img_width, img_height)

            # Skip invalid boxes
            if w > 0 and h > 0:
                labels.append(f"{class_id} {x_c:.6f} {y_c:.6f} {w:.6f} {h:.6f}")

        with open(label_path, "w") as f:
            f.write("\n".join(labels))
        print(f"  Saved: {label_path} ({len(labels)} boxes)")

    # Create dataset.yaml
    create_dataset_yaml(output_dir)

    # Summary
    print(f"\n{'='*50}")
    print("Dataset prepared successfully!")
    print(f"Output directory: {os.path.abspath(output_dir)}")
    print(f"Images: {output_dir}/images/train/")
    print(f"Labels: {output_dir}/labels/train/")
    print(f"\nClasses: {CLASSES}")
    print(f"\nNext steps:")
    print("1. Review/correct annotations:")
    print("   - Open https://www.makesense.ai/")
    print(f"   - Import images from: {os.path.abspath(output_dir)}/images/train/")
    print(f"   - Import labels (YOLO format) from: {os.path.abspath(output_dir)}/labels/train/")
    print(f"   - Also import classes.txt")
    print("   - Correct boxes, add missing ones, delete wrong ones")
    print("   - Export corrected labels back to labels/train/")
    print("2. Split some images to val/ for validation (optional for quick test)")
    print("3. Run: python train_yolo.py")


if __name__ == "__main__":
    main()
