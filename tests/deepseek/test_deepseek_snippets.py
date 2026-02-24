"""
Test DeepSeek OCR on the extracted YOLO snippets.
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

    if not os.path.exists(snippets_dir):
        print(f"Snippets directory not found: {snippets_dir}")
        print("Run test_yolo_snippets.py first to extract snippets.")
        return

    # Get entry snippets (skip overview and non-entry files)
    snippet_files = sorted([
        f for f in os.listdir(snippets_dir)
        if f.endswith('.png') and 'entry' in f
    ])

    if not snippet_files:
        print("No entry snippets found!")
        return

    print("=" * 70)
    print("DeepSeek OCR on YOLO Snippets")
    print("=" * 70)
    print(f"Snippets directory: {snippets_dir}")
    print(f"Entry snippets found: {len(snippet_files)}")
    print()

    # Load DeepSeek
    print("Loading DeepSeek-OCR-2...")
    from services import deepseek_ocr_service

    if not deepseek_ocr_service.load_model():
        print("ERROR: Failed to load DeepSeek")
        return
    print("DeepSeek loaded!")
    print()

    # Process snippets
    results = []
    total_time = 0

    for i, filename in enumerate(snippet_files):
        filepath = os.path.join(snippets_dir, filename)

        # Load image
        image = Image.open(filepath)
        width, height = image.size

        # Convert to base64
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Run OCR
        print(f"  [{i+1}/{len(snippet_files)}] {filename} ({width}x{height}px)...", end=" ", flush=True)
        start = time.time()
        result = deepseek_ocr_service.ocr_from_base64(image_base64)
        elapsed = time.time() - start
        total_time += elapsed

        if result["success"]:
            text = result["text"].strip()
            print(f"{elapsed:.1f}s - {len(text)} chars")
            results.append({
                "filename": filename,
                "text": text,
                "time": elapsed,
                "size": f"{width}x{height}"
            })
        else:
            print(f"FAILED: {result.get('error', 'Unknown')}")
            results.append({
                "filename": filename,
                "text": "",
                "time": elapsed,
                "error": result.get("error"),
                "size": f"{width}x{height}"
            })

    # Summary
    print()
    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"Processed: {len(snippet_files)} snippets")
    print(f"Total OCR time: {total_time:.1f}s")
    print(f"Average per snippet: {total_time/len(snippet_files):.1f}s")
    successful = sum(1 for r in results if r.get("text"))
    print(f"Successful: {successful}/{len(results)}")
    print()

    # Show extracted text
    print("=" * 70)
    print("EXTRACTED TEXT")
    print("=" * 70)
    for r in results:
        print(f"\n--- {r['filename']} ({r['size']}) ---")
        text = r.get("text", "")
        if r.get("error"):
            print(f"[ERROR: {r['error']}]")
        elif text:
            # Show first 400 chars
            if len(text) > 400:
                print(text[:400] + "...")
            else:
                print(text)
        else:
            print("[No text extracted]")

    # Save full output
    output_file = "deepseek_snippets_output.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("DeepSeek OCR Results on YOLO Snippets\n")
        f.write(f"Total snippets: {len(snippet_files)}\n")
        f.write(f"Total time: {total_time:.1f}s\n")
        f.write("=" * 70 + "\n\n")

        for r in results:
            f.write(f"=== {r['filename']} ===\n")
            f.write(f"Size: {r['size']}\n")
            f.write(f"Time: {r['time']:.1f}s\n")
            if r.get("error"):
                f.write(f"Error: {r['error']}\n")
            f.write(r.get("text", "") + "\n\n")

    print(f"\nFull output saved to: {output_file}")


if __name__ == "__main__":
    main()
