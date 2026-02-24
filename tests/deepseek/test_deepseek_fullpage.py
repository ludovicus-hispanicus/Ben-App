"""
Test DeepSeek-OCR-2 on FULL PAGE to check if generation limits work.
"""
import sys
import os
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add server src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

from services import deepseek_ocr_service
import base64
import time

def main():
    image_path = "yolo_dataset/images/train/page_3.png"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 60)
    print("DeepSeek-OCR-2 FULL PAGE Test")
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

    # Load image as base64
    print("Loading image...")
    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("utf-8")

    print(f"Image loaded, base64 length: {len(image_base64)} chars")
    print()

    # Run OCR on full page
    print("Running DeepSeek OCR on FULL PAGE...")
    print("(This tests if max_new_tokens=2048 prevents infinite generation)")
    print()

    start = time.time()
    result = deepseek_ocr_service.ocr_from_base64(image_base64)
    elapsed = time.time() - start

    print("=" * 60)
    print("Results")
    print("=" * 60)

    if result["success"]:
        print(f"Status: SUCCESS")
        print(f"Processing time: {result['processing_time_ms']}ms ({elapsed:.1f}s)")
        print(f"Lines detected: {len(result['lines'])}")
        print(f"Total chars: {len(result['text'])}")
        print()

        # Save full output to file
        with open("test_deepseek_output.txt", "w", encoding="utf-8") as f:
            f.write(result["text"])
        print("Full output saved to: test_deepseek_output.txt")
        print()

        print("--- First 10 lines ---")
        for i, line in enumerate(result['lines'][:10]):
            print(f"{i+1}. {line[:80]}{'...' if len(line) > 80 else ''}")
    else:
        print(f"Status: FAILED")
        print(f"Error: {result.get('error', 'Unknown')}")

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
