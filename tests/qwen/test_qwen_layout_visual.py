"""
Test Qwen2-VL for layout detection and visualize the detected boxes.
"""
import sys
import os
import io
import re
import time

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import base64
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO


def parse_bounding_boxes(text):
    """Parse bounding box coordinates from Qwen output."""
    boxes = []
    # Pattern: (x1,y1),(x2,y2)
    pattern = r'\((\d+),(\d+)\),\((\d+),(\d+)\)'

    for match in re.finditer(pattern, text):
        x1, y1, x2, y2 = map(int, match.groups())
        boxes.append({'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2})

    return boxes


def draw_boxes_on_image(image, boxes, scale_x=1.0, scale_y=1.0):
    """Draw bounding boxes on the image."""
    # Create a copy to draw on
    img_with_boxes = image.copy()
    draw = ImageDraw.Draw(img_with_boxes)

    # Colors for different boxes
    colors = ['red', 'blue', 'green', 'orange', 'purple', 'cyan', 'magenta', 'yellow']

    for i, box in enumerate(boxes):
        # Scale coordinates to original image size
        x1 = int(box['x1'] * scale_x)
        y1 = int(box['y1'] * scale_y)
        x2 = int(box['x2'] * scale_x)
        y2 = int(box['y2'] * scale_y)

        color = colors[i % len(colors)]

        # Draw rectangle
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)

        # Draw label
        label = f"{i+1}"
        draw.text((x1 + 5, y1 + 5), label, fill=color)

    return img_with_boxes


def main():
    image_path = "yolo_dataset/images/train/page_3.png"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 60)
    print("Qwen2-VL Layout Detection with Visualization")
    print("=" * 60)
    print(f"Image: {image_path}")
    print()

    # Import and setup
    import torch
    from transformers import Qwen2VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
    from qwen_vl_utils import process_vision_info

    device = "cuda"
    print(f"Device: {device}")

    # Load model
    model_id = "Qwen/Qwen2-VL-2B-Instruct"
    print(f"Loading {model_id}...")

    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )

    processor = AutoProcessor.from_pretrained(model_id)
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=torch.float16,
        quantization_config=quantization_config,
        device_map="auto",
    )

    # Set generation config
    model.generation_config.max_new_tokens = 2048
    model.generation_config.do_sample = False
    model.generation_config.repetition_penalty = 1.2

    print("Model loaded!")
    print()

    # Load original image
    original_image = Image.open(image_path).convert("RGB")
    original_width, original_height = original_image.size
    print(f"Original image size: {original_width}x{original_height}")

    # Resize for Qwen processing
    max_dim = 1024
    ratio = max_dim / max(original_width, original_height)
    resized_width = int(original_width * ratio)
    resized_height = int(original_height * ratio)
    resized_image = original_image.resize((resized_width, resized_height), Image.LANCZOS)
    print(f"Resized for processing: {resized_width}x{resized_height}")

    # Layout detection prompt
    prompt = "Detect each dictionary entry on this page. Output bounding box for each entry."

    print(f"\nPrompt: {prompt}")
    print("\nRunning layout detection...")

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": resized_image,
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

    start = time.time()
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

    elapsed = time.time() - start
    print(f"Detection time: {elapsed:.1f}s")

    # Parse boxes
    boxes = parse_bounding_boxes(output_text)
    print(f"\nDetected {len(boxes)} sections")

    # Save raw output
    with open("qwen_layout_output.txt", "w", encoding="utf-8") as f:
        f.write(output_text)
    print(f"Raw output saved to: qwen_layout_output.txt")

    if len(boxes) == 0:
        print("\nNo boxes detected! Raw output:")
        print(output_text[:500])
        return

    # Print boxes
    print("\nBounding boxes (in resized image coordinates):")
    for i, box in enumerate(boxes[:20]):
        print(f"  {i+1}. ({box['x1']},{box['y1']}) -> ({box['x2']},{box['y2']})")

    if len(boxes) > 20:
        print(f"  ... and {len(boxes) - 20} more")

    # Scale factors
    scale_x = original_width / resized_width
    scale_y = original_height / resized_height

    # Draw boxes on original image
    print("\nDrawing boxes on image...")
    img_with_boxes = draw_boxes_on_image(original_image, boxes, scale_x, scale_y)

    # Save visualization
    output_path = "qwen_layout_detected.png"
    img_with_boxes.save(output_path)
    print(f"Visualization saved to: {output_path}")

    # Also save on resized image for comparison
    img_resized_with_boxes = draw_boxes_on_image(resized_image, boxes, 1.0, 1.0)
    img_resized_with_boxes.save("qwen_layout_detected_resized.png")
    print(f"Resized visualization saved to: qwen_layout_detected_resized.png")


if __name__ == "__main__":
    main()
