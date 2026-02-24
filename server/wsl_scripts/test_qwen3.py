#!/usr/bin/env python3
"""
Test script for Qwen3-VL OCR

Tests the model on a sample AHw dictionary entry.
"""

import sys
import json
import base64
from pathlib import Path


def test_ocr():
    """Test OCR on a sample image."""

    # Path to test image (adjust as needed)
    test_images = [
        "/mnt/c/Users/wende/Documents/GitHub/BEn-app/yolo_snippets/07_entry_1.00.png",
    ]

    # Find first available image
    image_path = None
    for img in test_images:
        if Path(img).exists():
            image_path = img
            break

    if not image_path:
        print("No test image found!")
        return

    print(f"Testing with image: {image_path}")

    # Read and encode image
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode()

    # Prepare args
    args = {
        "model_id": "Qwen/Qwen3-VL-4B",
        "use_4bit": True,
        "image_base64": image_base64,
        "prompt": """This is a dictionary entry from AHw (Akkadisches Handwörterbuch).
OCR this image with careful attention to typography:
- The headword at the beginning is in BOLD - use **bold**
- Akkadian words and forms are in ITALIC - use *italic* for ALL of them
- German translations are in regular text
- Apply formatting consistently throughout the ENTIRE text, not just the first line.

Output the complete text with markdown formatting."""
    }

    # Import and run OCR
    print("Loading model (this may take a minute)...")

    from qwen3_ocr import run_ocr
    result = run_ocr(args)

    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)

    if result.get("success"):
        print(result["text"])

        # Save to file
        output_file = "/mnt/c/Users/wende/Documents/GitHub/BEn-app/qwen3_local_test_output.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("# Qwen3-VL-4B Local Test\n\n")
            f.write(f"Model: {result.get('model', 'unknown')}\n\n")
            f.write("## Output:\n\n")
            f.write(result["text"])

        print(f"\nSaved to: {output_file}")
    else:
        print(f"ERROR: {result.get('error')}")
        if result.get("traceback"):
            print(result["traceback"])


if __name__ == "__main__":
    test_ocr()
