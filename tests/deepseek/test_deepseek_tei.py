"""
Test DeepSeek-OCR-2 with TEI Lex-0 output on snippet images.
"""
import sys
import os
import io
import base64
import time

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add server src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

from PIL import Image
from io import BytesIO
from services import deepseek_ocr_service

def main():
    # Test on snippets (faster than full page)
    snippets_dir = "yolo_snippets"
    test_file = "06_entry_0.89.png"  # A good-sized entry
    image_path = os.path.join(snippets_dir, test_file)

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 70)
    print("DeepSeek-OCR-2 TEI Lex-0 Test")
    print("=" * 70)
    print(f"Image: {image_path}")
    print()

    # Load DeepSeek
    print("Loading DeepSeek-OCR-2...")
    if not deepseek_ocr_service.load_model():
        print("ERROR: Failed to load DeepSeek")
        return
    print("DeepSeek loaded!")
    print()

    # Load image and convert to base64
    image = Image.open(image_path)
    print(f"Image size: {image.size}")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    # Test 1: Plain text mode
    print("=" * 70)
    print("TEST 1: Plain Text Mode")
    print("=" * 70)

    start = time.time()
    result = deepseek_ocr_service.ocr_from_base64(image_base64, output_mode="plain")
    elapsed = time.time() - start

    if result["success"]:
        print(f"Time: {elapsed:.1f}s")
        print(f"\n--- Plain Text Output ---")
        print(result["text"][:1500])
    else:
        print(f"ERROR: {result.get('error')}")

    print()

    # Test 2: TEI Lex-0 mode
    print("=" * 70)
    print("TEST 2: TEI Lex-0 XML Mode")
    print("=" * 70)

    start = time.time()
    result_tei = deepseek_ocr_service.ocr_from_base64(image_base64, output_mode="tei_lex0")
    elapsed = time.time() - start

    if result_tei["success"]:
        print(f"Time: {elapsed:.1f}s")
        print(f"\n--- TEI Lex-0 XML Output ---")
        print(result_tei["text"])

        # Save TEI result
        with open("test_tei_output.xml", "w", encoding="utf-8") as f:
            f.write(result_tei["text"])
        print("\nSaved to: test_tei_output.xml")
    else:
        print(f"ERROR: {result_tei.get('error')}")


if __name__ == "__main__":
    main()
