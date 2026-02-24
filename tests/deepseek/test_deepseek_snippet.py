"""
Test DeepSeek-OCR-2 on a small snippet of the dictionary page.
This should be much faster than processing the full page.
"""
import sys
import os
import io
import base64
from PIL import Image

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add server src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

from services import deepseek_ocr_service


def test_snippet(image_path: str, crop_box: tuple, description: str):
    """Test OCR on a cropped region of the image."""
    print(f"\n{'=' * 60}")
    print(f"Testing: {description}")
    print(f"Crop region: {crop_box}")
    print('=' * 60)

    # Load and crop image
    img = Image.open(image_path)
    cropped = img.crop(crop_box)

    print(f"Cropped size: {cropped.size}")

    # Save cropped image temporarily for reference
    crop_filename = f"test_crop_{crop_box[0]}_{crop_box[1]}_{crop_box[2]}_{crop_box[3]}.png"
    cropped.save(crop_filename)
    print(f"Saved cropped image to: {crop_filename}")

    # Convert to base64
    buffer = io.BytesIO()
    cropped.save(buffer, format='PNG')
    image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    # Run OCR
    print("\nRunning DeepSeek OCR...")
    result = deepseek_ocr_service.ocr_from_base64(
        image_base64,
        prompt="Free OCR.",
        output_mode="plain"
    )

    print(f"\nSuccess: {result['success']}")
    print(f"Processing time: {result['processing_time_ms']} ms ({result['processing_time_ms']/1000:.1f} sec)")
    print(f"Lines detected: {len(result['lines'])}")

    if result['success']:
        print("\n--- OCR Output ---")
        print(result['text'][:1500] if len(result['text']) > 1500 else result['text'])
    else:
        print(f"Error: {result.get('error')}")

    return result


def main():
    image_path = "yolo_dataset/images/train/page_3.png"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    # Load model first
    print("Loading DeepSeek-OCR-2 model...")
    if not deepseek_ocr_service.load_model():
        print("Failed to load model!")
        return

    print("Model loaded successfully!")
    info = deepseek_ocr_service.get_model_info()
    print(f"VRAM: {info.get('gpu_memory_allocated_mb', 'N/A')} MB")

    # Test 1: Small snippet (top-left, ~2 dictionary entries)
    test_snippet(
        image_path,
        crop_box=(0, 0, 700, 250),  # Small region
        description="Small snippet (top-left corner)"
    )

    # Test 2: Medium snippet (first column, several entries)
    # test_snippet(
    #     image_path,
    #     crop_box=(0, 0, 700, 500),
    #     description="Medium snippet (first column top)"
    # )


if __name__ == "__main__":
    main()
