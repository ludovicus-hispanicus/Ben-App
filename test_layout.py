
import os
import json
import sys
from pathlib import Path
from docling.document_converter import DocumentConverter
from PIL import Image, ImageDraw, ImageFont
from pdf2image import convert_from_path


# Color map for different layout labels
LABEL_COLORS = {
    "title": "blue",
    "section_header": "darkblue",
    "paragraph": "green",
    "text": "green",
    "caption": "orange",
    "footnote": "purple",
    "page_header": "gray",
    "page_footer": "gray",
    "reference": "brown",
    "list_item": "cyan",
    "picture": "magenta",
    "table": "red",
}


def test_layout(pdf_path, output_dir="layout_test_results", first_page=1, last_page=3):
    print(f"Testing layout recognition on: {pdf_path} (pages {first_page}-{last_page})")

    converter = DocumentConverter()
    os.makedirs(output_dir, exist_ok=True)

    # Convert PDF pages to images for visualization
    print("Converting PDF pages to images for visualization...")
    try:
        page_images = convert_from_path(pdf_path, first_page=first_page, last_page=last_page)
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return

    layout_data = []

    # Process each page as a separate image through Docling
    for i, page_img in enumerate(page_images):
        page_no = first_page + i
        page_width, page_height = page_img.size
        print(f"\nAnalyzing Page {page_no} ({page_width}x{page_height})...")

        # Save temp image for Docling
        temp_img_path = os.path.join(output_dir, f"temp_page_{page_no}.png")
        page_img.save(temp_img_path)

        try:
            result = converter.convert(temp_img_path)
            doc = result.document

            draw = ImageDraw.Draw(page_img)
            page_items = []

            for item, level in doc.iterate_items():
                if not hasattr(item, 'prov') or not item.prov:
                    continue

                label = str(item.label) if hasattr(item, 'label') else "unknown"
                text_preview = ""
                if hasattr(item, 'text'):
                    text_preview = item.text[:80]

                for prov in item.prov:
                    bbox = prov.bbox

                    # Convert BOTTOMLEFT origin to TOPLEFT for PIL drawing
                    tl_bbox = bbox.to_top_left_origin(page_height)
                    x0, y0, x1, y1 = tl_bbox.l, tl_bbox.t, tl_bbox.r, tl_bbox.b

                    # Ensure coordinates are valid for drawing
                    x0, x1 = min(x0, x1), max(x0, x1)
                    y0, y1 = min(y0, y1), max(y0, y1)

                    color = LABEL_COLORS.get(label, "red")
                    draw.rectangle([x0, y0, x1, y1], outline=color, width=3)

                    # Draw label text
                    try:
                        draw.text((x0 + 4, y0 + 2), label, fill=color)
                    except Exception:
                        pass

                    entry = {
                        "page": page_no,
                        "label": label,
                        "bbox_topleft": [round(x0, 1), round(y0, 1),
                                         round(x1, 1), round(y1, 1)],
                        "text": text_preview
                    }

                    # Detect column position based on x-coordinate midpoint
                    mid_x = (x0 + x1) / 2
                    if mid_x < page_width / 2:
                        entry["column"] = "left"
                    else:
                        entry["column"] = "right"

                    page_items.append(entry)
                    layout_data.append(entry)

            # Cleanup temp file
            os.remove(temp_img_path)

            # Save visualization
            viz_path = os.path.join(output_dir, f"page_{page_no}_viz.png")
            page_img.save(viz_path)

            # Print summary
            labels_found = {}
            for e in page_items:
                labels_found[e["label"]] = labels_found.get(e["label"], 0) + 1
            left_count = sum(1 for e in page_items if e.get("column") == "left")
            right_count = sum(1 for e in page_items if e.get("column") == "right")
            print(f"  Found {len(page_items)} regions: {labels_found}")
            print(f"  Columns: left={left_count}, right={right_count}")
            print(f"  Saved: {viz_path}")

        except Exception as e:
            print(f"Error analyzing Page {page_no}: {e}")
            import traceback
            traceback.print_exc()

    # Save JSON summary
    json_path = os.path.join(output_dir, "layout_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(layout_data, f, indent=2, ensure_ascii=False)
    print(f"\nTotal regions found: {len(layout_data)}")
    print(f"Results saved to: {output_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_layout.py <path_to_pdf> [first_page] [last_page]")
    else:
        try:
            import docling
            import pdf2image
        except ImportError:
            print("Missing dependencies. Run: pip install docling pdf2image pillow")
            sys.exit(1)

        first_page = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        last_page = int(sys.argv[3]) if len(sys.argv) > 3 else first_page + 2
        test_layout(sys.argv[1], first_page=first_page, last_page=last_page)
