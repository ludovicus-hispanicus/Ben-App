"""
Simple DeepSeek-OCR-2 test - crops regions manually and runs OCR.
"""
import sys
import os

# Add server src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

from PIL import Image
from services import deepseek_ocr_service
import base64
from io import BytesIO
import time

def main():
    image_path = "yolo_dataset/images/train/page_3.png"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 60)
    print("DeepSeek-OCR-2 Simple Test")
    print("=" * 60)
    print(f"Image: {image_path}")
    print()

    # Check availability
    print("Checking GPU availability...")
    if not deepseek_ocr_service.is_available():
        print("ERROR: DeepSeek OCR not available (no GPU or missing dependencies)")
        return

    print("GPU available!")
    print()

    # Load image
    image = Image.open(image_path)
    print(f"Image size: {image.width}x{image.height}")
    print()

    # Define some approximate line regions (manually estimated)
    # Format: (left, top, right, bottom)
    regions = [
        (50, 100, 750, 150),   # Line 1
        (50, 160, 750, 210),   # Line 2
        (50, 220, 750, 270),   # Line 3
        (50, 280, 750, 330),   # Line 4
        (50, 340, 750, 390),   # Line 5
    ]

    print(f"Testing DeepSeek on {len(regions)} regions...")
    print("=" * 60)

    total_ocr_time = 0
    results = []

    for i, (left, top, right, bottom) in enumerate(regions):
        # Crop region
        snippet = image.crop((left, top, right, bottom))
        snippet_size = f"{right-left}x{bottom-top}"

        # Convert to base64
        buffer = BytesIO()
        snippet.save(buffer, format="PNG")
        snippet_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Run OCR
        print(f"\nRegion {i+1}/{len(regions)} ({snippet_size}px):")
        result = deepseek_ocr_service.ocr_from_base64(snippet_base64)

        if result["success"]:
            text = result["lines"][0] if result["lines"] else result["text"].split("\n")[0]
            text = text.strip()
            ocr_time = result["processing_time_ms"]
            total_ocr_time += ocr_time
            print(f"  Time: {ocr_time}ms")
            print(f"  Text: {text[:100]}{'...' if len(text) > 100 else ''}")
            results.append(text)
        else:
            print(f"  ERROR: {result.get('error', 'Unknown error')}")
            results.append("")

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Regions processed: {len(regions)}")
    print(f"DeepSeek OCR total: {total_ocr_time/1000:.2f}s")
    print(f"Average per region: {total_ocr_time/len(regions):.0f}ms")
    print()

    # Show all results
    print("=" * 60)
    print("OCR Results")
    print("=" * 60)
    for i, text in enumerate(results):
        print(f"{i+1}. {text}")

    # Model info
    print()
    print("=" * 60)
    print("Model Info")
    print("=" * 60)
    info = deepseek_ocr_service.get_model_info()
    for key, value in info.items():
        print(f"  {key}: {value}")

if __name__ == "__main__":
    main()
