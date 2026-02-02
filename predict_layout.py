"""
Run trained YOLOv8 model on PDF pages to detect dictionary layout regions.

Usage:
    python predict_layout.py <pdf_path> [first_page] [last_page] [--model MODEL]

Example:
    python predict_layout.py "Q_II 886-931.pdf" 1 5
    python predict_layout.py "Q_II 886-931.pdf" 1 5 --model runs/detect/dictionary_layout/weights/best.pt

Output:
    - yolo_predictions/predictions.json - detected regions in JSON format
    - yolo_predictions/page_X_pred.png - visualization images with bounding boxes
"""

import argparse
import json
import os
import sys
from collections import defaultdict

from pdf2image import convert_from_path
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


# Class definitions (must match training)
CLASSES = ["entry", "subentry", "guidewords", "page_number", "root_index"]

# Color scheme for visualization
CLASS_COLORS = {
    "entry": "blue",
    "subentry": "cyan",
    "guidewords": "gray",
    "page_number": "orange",
    "root_index": "red",
}


def main():
    parser = argparse.ArgumentParser(description="Run YOLOv8 inference on PDF pages")
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument("first_page", nargs="?", type=int, default=1,
                        help="First page to process")
    parser.add_argument("last_page", nargs="?", type=int, default=None,
                        help="Last page to process")
    parser.add_argument("--model", default="runs/detect/dictionary_layout/weights/best.pt",
                        help="Path to trained model weights")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="Confidence threshold")
    parser.add_argument("--iou", type=float, default=0.45,
                        help="IoU threshold for NMS")
    parser.add_argument("--imgsz", type=int, default=1024,
                        help="Image size for inference")
    parser.add_argument("--output", default="yolo_predictions",
                        help="Output directory")
    args = parser.parse_args()

    if args.last_page is None:
        args.last_page = args.first_page + 2

    if not os.path.exists(args.pdf_path):
        print(f"Error: PDF not found: {args.pdf_path}")
        sys.exit(1)

    if not os.path.exists(args.model):
        print(f"Error: Model not found: {args.model}")
        print("Train a model first with: python train_yolo.py")
        sys.exit(1)

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    # Load model
    print(f"Loading model: {args.model}")
    model = YOLO(args.model)

    # Convert PDF to images
    print(f"Converting PDF pages {args.first_page}-{args.last_page} to images...")
    page_images = convert_from_path(
        args.pdf_path,
        first_page=args.first_page,
        last_page=args.last_page
    )

    all_predictions = []

    # Process each page
    for page_idx, page_img in enumerate(page_images):
        page_no = args.first_page + page_idx
        img_width, img_height = page_img.size
        mid_x = img_width / 2

        print(f"\nProcessing page {page_no} ({img_width}x{img_height})...")

        # Run inference
        results = model.predict(
            page_img,
            conf=args.conf,
            iou=args.iou,
            imgsz=args.imgsz,
            verbose=False
        )

        # Parse results
        page_regions = []
        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes

            for i in range(len(boxes)):
                # Get box coordinates (xyxy format)
                x0, y0, x1, y1 = boxes.xyxy[i].tolist()
                conf = boxes.conf[i].item()
                class_id = int(boxes.cls[i].item())
                class_name = CLASSES[class_id] if class_id < len(CLASSES) else "unknown"

                # Determine column
                center_x = (x0 + x1) / 2
                column = "left" if center_x < mid_x else "right"

                region = {
                    "page": page_no,
                    "class_id": class_id,
                    "class_name": class_name,
                    "confidence": round(conf, 4),
                    "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                    "column": column
                }
                page_regions.append(region)

        all_predictions.extend(page_regions)

        # Count by class
        class_counts = defaultdict(int)
        for r in page_regions:
            class_counts[r["class_name"]] += 1
        print(f"  Found {len(page_regions)} regions: {dict(class_counts)}")

        # Create visualization
        viz_img = page_img.copy()
        draw = ImageDraw.Draw(viz_img)

        for region in page_regions:
            x0, y0, x1, y1 = region["bbox"]
            class_name = region["class_name"]
            conf = region["confidence"]
            color = CLASS_COLORS.get(class_name, "green")

            # Draw box
            draw.rectangle([x0, y0, x1, y1], outline=color, width=3)

            # Draw label
            label = f"{class_name} {conf:.2f}"
            draw.text((x0 + 4, y0 + 2), label, fill=color)

        # Save visualization
        viz_path = os.path.join(args.output, f"page_{page_no}_pred.png")
        viz_img.save(viz_path)
        print(f"  Saved: {viz_path}")

    # Save predictions JSON
    json_path = os.path.join(args.output, "predictions.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_predictions, f, indent=2, ensure_ascii=False)
    print(f"\nSaved predictions to: {json_path}")

    # Summary
    print(f"\n{'='*50}")
    print("Inference complete!")
    print(f"{'='*50}")
    print(f"Total regions detected: {len(all_predictions)}")

    total_counts = defaultdict(int)
    for r in all_predictions:
        total_counts[r["class_name"]] += 1
    print(f"By class: {dict(total_counts)}")

    print(f"\nResults in: {os.path.abspath(args.output)}/")


if __name__ == "__main__":
    main()
