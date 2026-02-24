"""
Test Nemotron OCR on YOLO snippets.
"""
import sys
import os
import io
import time
import base64

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add server src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

from PIL import Image
from io import BytesIO


def main():
    snippets_dir = "yolo_snippets"

    # Test with a few entry snippets
    test_files = [
        "05_entry_1.00.png",  # Smaller entry
        "06_entry_0.89.png",  # Larger entry
        "13_entry_1.00.png",  # Medium entry
    ]

    print("=" * 70)
    print("Nemotron OCR on YOLO Snippets")
    print("=" * 70)
    print()

    # Load Nemotron
    print("Loading Nemotron-Parse...")
    from services import nemotron_ocr_service

    if not nemotron_ocr_service.load_model():
        print("ERROR: Failed to load Nemotron")
        return
    print("Nemotron loaded!")
    print()

    # Process snippets
    results = []

    for filename in test_files:
        filepath = os.path.join(snippets_dir, filename)
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            continue

        # Load image
        image = Image.open(filepath)
        width, height = image.size

        # Convert to base64
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        print("=" * 70)
        print(f"Testing: {filename} ({width}x{height}px)")
        print("=" * 70)

        # Run OCR
        start = time.time()
        result = nemotron_ocr_service.ocr_from_base64(image_base64)
        elapsed = time.time() - start

        if result["success"]:
            text = result["text"].strip()
            print(f"Time: {elapsed:.1f}s")
            print(f"Lines: {len(result.get('lines', []))}")
            print(f"Boxes: {len(result.get('boxes', []))}")
            print(f"\n--- Output (first 800 chars) ---")
            print(text[:800] if text else "[No text]")

            results.append({
                "filename": filename,
                "text": text,
                "time": elapsed,
                "lines": result.get("lines", []),
                "boxes": result.get("boxes", []),
            })
        else:
            print(f"FAILED: {result.get('error', 'Unknown')}")
            results.append({
                "filename": filename,
                "error": result.get("error"),
                "time": elapsed,
            })

        print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    successful = sum(1 for r in results if "text" in r)
    total_time = sum(r["time"] for r in results)
    print(f"Processed: {len(results)} snippets")
    print(f"Successful: {successful}/{len(results)}")
    print(f"Total time: {total_time:.1f}s")

    # Save results
    output_file = "nemotron_snippets_output.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        for r in results:
            f.write(f"=== {r['filename']} ===\n")
            f.write(f"Time: {r['time']:.1f}s\n")
            if "error" in r:
                f.write(f"Error: {r['error']}\n")
            else:
                f.write(r.get("text", "") + "\n")
            f.write("\n")
    print(f"\nOutput saved to: {output_file}")


if __name__ == "__main__":
    main()
