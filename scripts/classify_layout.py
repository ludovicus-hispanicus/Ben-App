import json
import os
import re
import sys
from collections import defaultdict
from PIL import Image, ImageDraw, ImageFont
from pdf2image import convert_from_path


# Color scheme for classified section types
SECTION_COLORS = {
    "page_header": "gray",
    "index_table": "red",
    "headword": "blue",
    "sub_entry": "cyan",
    "definition": "orange",
    "reference": "purple",
    "lexical_list": "magenta",
    "text": "green",
}

# Common Assyriological reference abbreviations
REFERENCE_ABBREVS = [
    r"RA\s+\d", r"ARM\s+\d", r"MSL\s+\d", r"ABL\s+\d", r"CT\s+\d",
    r"AfO\s+\d", r"JCS\s+\d", r"AHw", r"CAD\s+", r"YOS\s+\d",
    r"BIN\s+\d", r"VAB\s+\d", r"ACh\.", r"Iraq\s+\d", r"Or\.\s+\d",
    r"SVAT\s+\d", r"AGS\s+\d", r"TBP\s+", r"PBS\s+\d", r"ADD\s+\d",
    r"ND\s+\d", r"TCL\s+\d", r"VAS\s+\d", r"KAR\s+\d", r"LKA\s+\d",
    r"BHRM\s+\d", r"TDP\s+\d", r"STT\s+\d", r"AOT\s+\d",
    r"CCT\s+\d", r"JKTC\s+\d", r"BWL\s+\d", r"Sn\.\s+\d",
    r"UCP\s+\d", r"PBS\s+\d", r"KTS\s+\d",
]
REFERENCE_PATTERN = re.compile("|".join(REFERENCE_ABBREVS))

# Headword pattern: Akkadian lemma, optionally with (m)/(f), often followed by Roman numeral
# Examples: qabaltu(m), qablu(m) I, qabbūtu, qab/psu
HEADWORD_PATTERN = re.compile(
    r"^[a-zA-ZšṣṭḫāēīūŠṢṬḪĀĒĪŪ][a-zA-ZšṣṭḫāēīūŠṢṬḪĀĒĪŪ/]*"
    r"(?:\([mf]\))?"
    r"\s*(?:I{1,3}V?|IV|V)?"
    r"\s+"
)

# Sub-entry patterns: numbered 1) 2) or lettered a) b)
SUB_ENTRY_PATTERN = re.compile(r"^\d+\)\s|^[a-z]\)\s")

# Lexical list: contains = sign (Sumerian = Akkadian equations)
LEXICAL_PATTERN = re.compile(r"\w+\s*=\s*\w+")

# Definition: contains quoted German/English text
DEFINITION_PATTERN = re.compile(
    r'[„,\u201e][^"\']+["\u201c\u201d\']'  # German-style quotes
    r"|'[A-Z][^']+'"                         # English-style single quotes
)


def compute_iou(box_a, box_b):
    """Compute Intersection over Union for two [x0, y0, x1, y1] boxes."""
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

    removed = len(regions) - len(deduplicated)
    if removed > 0:
        print(f"Deduplication: removed {removed} duplicate regions")
    return deduplicated


def classify_region(entry, page_height=2075):
    """Classify a region based on text patterns and position."""
    text = entry.get("text", "").strip()
    label = entry.get("label", "")
    bbox = entry.get("bbox_topleft", [0, 0, 0, 0])
    y_top = bbox[1]

    # Keep existing table label
    if label == "table":
        return "index_table"

    # Page header: very top of page, short text
    if y_top < 165 and len(text) < 40:
        return "page_header"

    # Empty text — can't classify further
    if not text:
        return "text"

    # Count reference abbreviation matches
    ref_matches = len(REFERENCE_PATTERN.findall(text))

    # Headword: starts with Akkadian lemma pattern and is relatively short
    # or starts a new dictionary entry
    if HEADWORD_PATTERN.match(text) and len(text) < 120:
        return "headword"

    # Sub-entry: starts with numbered or lettered pattern
    if SUB_ENTRY_PATTERN.match(text):
        return "sub_entry"

    # Lexical list: contains Sumerian = Akkadian equations
    if LEXICAL_PATTERN.search(text):
        # But only if it's not dominated by references
        if ref_matches < 3:
            return "lexical_list"

    # Definition: contains quoted translations
    if DEFINITION_PATTERN.search(text):
        return "definition"

    # Reference-heavy: many abbreviation matches relative to text length
    if ref_matches >= 3:
        return "reference"

    return "text"


def render_classified_viz(classified_regions, pdf_path, output_dir, first_page=1, last_page=3):
    """Re-render page visualizations with classified section type colors."""
    print("\nRendering classified visualizations...")
    page_images = convert_from_path(pdf_path, first_page=first_page, last_page=last_page)

    by_page = defaultdict(list)
    for r in classified_regions:
        by_page[r["page"]].append(r)

    for i, page_img in enumerate(page_images):
        page_no = first_page + i
        draw = ImageDraw.Draw(page_img)
        items = by_page.get(page_no, [])

        for entry in items:
            bbox = entry["bbox_topleft"]
            x0, y0, x1, y1 = bbox
            section = entry.get("section_type", "text")
            color = SECTION_COLORS.get(section, "green")

            draw.rectangle([x0, y0, x1, y1], outline=color, width=3)
            try:
                draw.text((x0 + 4, y0 + 2), section, fill=color)
            except Exception:
                pass

        viz_path = os.path.join(output_dir, f"page_{page_no}_classified.png")
        page_img.save(viz_path)
        print(f"  Saved: {viz_path}")


def main():
    input_dir = "layout_test_results"
    json_path = os.path.join(input_dir, "layout_summary.json")

    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found. Run test_layout.py first.")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        regions = json.load(f)

    print(f"Loaded {len(regions)} regions from {json_path}")

    # Step 1: Deduplicate
    regions = deduplicate_regions(regions)

    # Step 2: Classify each region
    for entry in regions:
        entry["section_type"] = classify_region(entry)

    # Print summary
    type_counts = defaultdict(int)
    for entry in regions:
        type_counts[entry["section_type"]] += 1
    print(f"\nClassification results ({len(regions)} regions):")
    for stype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {stype}: {count}")

    # Step 3: Save classified JSON
    out_path = os.path.join(input_dir, "classified_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(regions, f, indent=2, ensure_ascii=False)
    print(f"\nSaved classified data to: {out_path}")

    # Step 4: Re-render visualizations if PDF is available
    pdf_path = "Q_II 886-931.pdf"
    if os.path.exists(pdf_path):
        pages = sorted(set(r["page"] for r in regions))
        render_classified_viz(regions, pdf_path, input_dir,
                              first_page=min(pages), last_page=max(pages))
    else:
        print(f"\nPDF not found at '{pdf_path}', skipping visualization.")
        print("Pass PDF path as argument to render: python classify_layout.py <pdf_path>")

    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        pdf_path = sys.argv[1]
        pages = sorted(set(r["page"] for r in regions))
        render_classified_viz(regions, pdf_path, input_dir,
                              first_page=min(pages), last_page=max(pages))


if __name__ == "__main__":
    main()
