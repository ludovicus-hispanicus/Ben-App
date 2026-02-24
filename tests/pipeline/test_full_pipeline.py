"""
Test full OCR pipeline:
1. Qwen2-VL detects dictionary entry sections (bounding boxes)
2. Crop each section
3. DeepSeek OCR on each snippet
4. Combine results
"""
import sys
import os
import io
import re
import time

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add server src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

import base64
from PIL import Image
from io import BytesIO


def detect_sections_qwen(image, processor, model, device):
    """Use Qwen2-VL to detect dictionary entry sections."""
    from qwen_vl_utils import process_vision_info
    import torch

    prompt = "Detect each dictionary entry on this page. Output bounding box for each entry."

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": image,
                    "min_pixels": 256 * 28 * 28,
                    "max_pixels": 512 * 28 * 28,
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]

    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(messages)

    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=2048)

    generated_ids_trimmed = [
        out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False
    )[0]

    return output_text


def parse_bounding_boxes(text, image_width, image_height, resized_width, resized_height):
    """Parse bounding box coordinates from Qwen output and scale to original image."""
    boxes = []
    # Pattern: (x1,y1),(x2,y2)
    pattern = r'\((\d+),(\d+)\),\((\d+),(\d+)\)'

    for match in re.finditer(pattern, text):
        x1, y1, x2, y2 = map(int, match.groups())

        # Scale from resized to original coordinates
        scale_x = image_width / resized_width
        scale_y = image_height / resized_height

        boxes.append({
            'x1': int(x1 * scale_x),
            'y1': int(y1 * scale_y),
            'x2': int(x2 * scale_x),
            'y2': int(y2 * scale_y),
        })

    return boxes


def main():
    image_path = "yolo_dataset/images/train/page_3.png"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 70)
    print("FULL PIPELINE TEST: Qwen2-VL (layout) + DeepSeek (OCR)")
    print("=" * 70)
    print(f"Image: {image_path}")
    print()

    # ==================== STAGE 1: Layout Detection ====================
    print("=" * 70)
    print("STAGE 1: Layout Detection (Qwen2-VL)")
    print("=" * 70)

    import torch
    from transformers import Qwen2VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig

    device = "cuda"
    print(f"Loading Qwen2-VL-2B-Instruct...")

    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )

    qwen_processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-2B-Instruct")
    qwen_model = Qwen2VLForConditionalGeneration.from_pretrained(
        "Qwen/Qwen2-VL-2B-Instruct",
        torch_dtype=torch.float16,
        quantization_config=quantization_config,
        device_map="auto",
    )
    qwen_model.generation_config.max_new_tokens = 2048
    qwen_model.generation_config.do_sample = False
    qwen_model.generation_config.repetition_penalty = 1.2

    print("Qwen2-VL loaded!")

    # Load and resize image for Qwen
    original_image = Image.open(image_path).convert("RGB")
    original_width, original_height = original_image.size
    print(f"Original image size: {original_width}x{original_height}")

    # Resize for Qwen
    max_dim = 1024
    ratio = max_dim / max(original_width, original_height)
    resized_width = int(original_width * ratio)
    resized_height = int(original_height * ratio)
    resized_image = original_image.resize((resized_width, resized_height), Image.LANCZOS)
    print(f"Resized for Qwen: {resized_width}x{resized_height}")

    # Detect sections
    print("Detecting dictionary entry sections...")
    start = time.time()
    qwen_output = detect_sections_qwen(resized_image, qwen_processor, qwen_model, device)
    layout_time = time.time() - start
    print(f"Layout detection time: {layout_time:.1f}s")
    print(f"Raw output: {qwen_output[:300]}...")

    # Parse bounding boxes
    boxes = parse_bounding_boxes(qwen_output, original_width, original_height, resized_width, resized_height)
    print(f"Detected {len(boxes)} sections")

    if len(boxes) == 0:
        print("ERROR: No sections detected!")
        return

    # Show first few boxes
    for i, box in enumerate(boxes[:5]):
        print(f"  Box {i+1}: ({box['x1']},{box['y1']}) -> ({box['x2']},{box['y2']})")

    # Unload Qwen to free memory
    print("\nUnloading Qwen2-VL to free GPU memory...")
    del qwen_model, qwen_processor
    torch.cuda.empty_cache()
    print(f"GPU memory after unload: {torch.cuda.memory_allocated() / 1024 / 1024:.0f} MB")

    # ==================== STAGE 2: OCR with DeepSeek ====================
    print()
    print("=" * 70)
    print("STAGE 2: OCR (DeepSeek-OCR-2)")
    print("=" * 70)

    from services import deepseek_ocr_service

    print("Loading DeepSeek-OCR-2...")
    if not deepseek_ocr_service.load_model():
        print("ERROR: Failed to load DeepSeek")
        return
    print("DeepSeek loaded!")

    # Process each section
    results = []
    total_ocr_time = 0

    # Limit to first 10 boxes for testing
    test_boxes = boxes[:10]
    print(f"\nProcessing {len(test_boxes)} sections...")

    for i, box in enumerate(test_boxes):
        # Add padding
        padding = 10
        x1 = max(0, box['x1'] - padding)
        y1 = max(0, box['y1'] - padding)
        x2 = min(original_width, box['x2'] + padding)
        y2 = min(original_height, box['y2'] + padding)

        # Crop snippet
        snippet = original_image.crop((x1, y1, x2, y2))

        # Convert to base64
        buffer = BytesIO()
        snippet.save(buffer, format="PNG")
        snippet_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # OCR
        print(f"  Section {i+1}/{len(test_boxes)} ({x2-x1}x{y2-y1}px)...", end=" ")
        start = time.time()
        result = deepseek_ocr_service.ocr_from_base64(snippet_base64)
        ocr_time = time.time() - start
        total_ocr_time += ocr_time

        if result["success"]:
            text = result["text"].strip()
            print(f"{ocr_time:.1f}s - {len(text)} chars")
            results.append({
                "box": box,
                "text": text,
                "time": ocr_time,
            })
        else:
            print(f"FAILED: {result.get('error', 'Unknown')}")
            results.append({
                "box": box,
                "text": "",
                "time": ocr_time,
                "error": result.get("error"),
            })

    # ==================== RESULTS ====================
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Layout detection (Qwen): {layout_time:.1f}s")
    print(f"OCR time (DeepSeek): {total_ocr_time:.1f}s for {len(test_boxes)} sections")
    print(f"Average per section: {total_ocr_time/len(test_boxes):.1f}s")
    print(f"Total pipeline time: {layout_time + total_ocr_time:.1f}s")
    print()

    # Show extracted text
    print("=" * 70)
    print("EXTRACTED TEXT (first 5 sections)")
    print("=" * 70)
    for i, r in enumerate(results[:5]):
        print(f"\n--- Section {i+1} ---")
        print(r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"])

    # Save full output
    output_file = "test_pipeline_output.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        for i, r in enumerate(results):
            f.write(f"=== Section {i+1} ===\n")
            f.write(f"Box: ({r['box']['x1']},{r['box']['y1']}) -> ({r['box']['x2']},{r['box']['y2']})\n")
            f.write(r["text"] + "\n\n")
    print(f"\nFull output saved to: {output_file}")


if __name__ == "__main__":
    main()
