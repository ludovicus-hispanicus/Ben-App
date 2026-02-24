"""
Test DeepSeek-OCR-2 with markdown output prompt.
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

# Grounding prompt for markdown output (activates DeepEncoder V2)
PROMPT_MARKDOWN_GROUNDING = "<|grounding|>Convert the document to markdown."


def main():
    snippets_dir = "yolo_snippets"
    test_file = "06_entry_0.89.png"
    image_path = os.path.join(snippets_dir, test_file)

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 70)
    print("DeepSeek-OCR-2 Markdown Test")
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
    original_size = image.size
    print(f"Original size: {original_size}")

    # Upscale to 1024px for better style detection
    max_dim = max(image.size)
    if max_dim < 1024:
        scale = 1024 / max_dim
        new_size = (int(image.width * scale), int(image.height * scale))
        image = image.resize(new_size, Image.LANCZOS)
        print(f"Upscaled to: {image.size} (for style detection)")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    # Test 1: Plain text (baseline)
    print("=" * 70)
    print("TEST 1: Plain Text (baseline)")
    print("=" * 70)

    start = time.time()
    result_plain = deepseek_ocr_service.ocr_from_base64(image_base64, output_mode="plain")
    elapsed = time.time() - start

    if result_plain["success"]:
        print(f"Time: {elapsed:.1f}s")
        print(f"\n--- Plain Text ---")
        print(result_plain["text"][:800])
    else:
        print(f"ERROR: {result_plain.get('error')}")

    print()

    # Test 2: Grounding + Markdown prompt
    print("=" * 70)
    print("TEST 2: Grounding Markdown Prompt")
    print("=" * 70)
    print(f"Prompt: {PROMPT_MARKDOWN_GROUNDING}")

    start = time.time()
    result_md = deepseek_ocr_service.ocr_from_base64(
        image_base64,
        prompt=PROMPT_MARKDOWN_GROUNDING
    )
    elapsed = time.time() - start

    if result_md["success"]:
        print(f"Time: {elapsed:.1f}s")
        print(f"\n--- Markdown Output ---")
        print(result_md["text"])

        # Save result
        with open("test_markdown_output.md", "w", encoding="utf-8") as f:
            f.write(result_md["text"])
        print("\nSaved to: test_markdown_output.md")
    else:
        print(f"ERROR: {result_md.get('error')}")


if __name__ == "__main__":
    main()
