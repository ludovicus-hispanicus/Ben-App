"""
Test Nemotron-Parse OCR service on dictionary page.
"""
import sys
import os
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add server src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

from services import nemotron_ocr_service
import base64
import time

def main():
    image_path = "yolo_dataset/images/train/page_3.png"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 60)
    print("Nemotron-Parse OCR Test")
    print("=" * 60)
    print(f"Image: {image_path}")
    print()

    # Check availability
    print("Checking GPU availability...")
    if not nemotron_ocr_service.is_available():
        print("ERROR: Nemotron not available (no GPU or missing dependencies)")
        return

    print("GPU available!")
    print()

    # Load image as base64
    print("Loading image...")
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    print(f"Image loaded, base64 length: {len(image_base64)} chars")
    print()

    # Run OCR on full page
    print("Running Nemotron-Parse OCR on FULL PAGE...")
    print()

    start = time.time()
    result = nemotron_ocr_service.ocr_from_base64(image_base64)
    elapsed = time.time() - start

    print("=" * 60)
    print("Results")
    print("=" * 60)

    if result["success"]:
        print(f"Status: SUCCESS")
        print(f"Processing time: {result['processing_time_ms']}ms ({elapsed:.1f}s)")
        print(f"Lines detected: {len(result['lines'])}")
        print(f"Boxes detected: {len(result['boxes'])}")
        print(f"Total chars: {len(result['text'])}")
        print()

        # Save full output to file
        with open("test_nemotron_output.txt", "w", encoding="utf-8") as f:
            f.write(result["text"])
        print("Full output saved to: test_nemotron_output.txt")
        print()

        print("--- First 15 lines ---")
        for i, line in enumerate(result['lines'][:15]):
            box = result['boxes'][i] if i < len(result['boxes']) else {}
            print(f"{i+1}. [{box.get('x',0)},{box.get('y',0)}] {line[:80]}{'...' if len(line) > 80 else ''}")

        # Show raw output snippet for debugging
        if "raw_output" in result:
            print()
            print("--- Raw output (first 500 chars) ---")
            print(result["raw_output"][:500])
    else:
        print(f"Status: FAILED")
        print(f"Error: {result.get('error', 'Unknown')}")

    # Model info
    print()
    print("=" * 60)
    print("Model Info")
    print("=" * 60)
    info = nemotron_ocr_service.get_model_info()
    for key, value in info.items():
        print(f"  {key}: {value}")

if __name__ == "__main__":
    main()
