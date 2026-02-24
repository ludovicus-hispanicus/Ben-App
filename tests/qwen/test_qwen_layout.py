"""
Test Qwen2-VL for layout/section detection on dictionary page.
"""
import sys
import os
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add server src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

import base64
import time
from PIL import Image
from io import BytesIO

def main():
    image_path = "yolo_dataset/images/train/page_3.png"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 60)
    print("Qwen2-VL Layout/Section Detection Test")
    print("=" * 60)
    print(f"Image: {image_path}")
    print()

    # Import and setup
    import torch
    from transformers import Qwen2VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
    from qwen_vl_utils import process_vision_info

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    # Load model - use base Qwen2-VL-2B-Instruct (outputs bounding boxes)
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
    model.generation_config.temperature = None
    model.generation_config.top_p = None
    model.generation_config.top_k = None

    print("Model loaded!")
    print()

    # Load and resize image
    image = Image.open(image_path).convert("RGB")
    original_size = image.size

    # Resize to fit GPU
    max_dim = 1024
    if max(image.width, image.height) > max_dim:
        ratio = max_dim / max(image.width, image.height)
        new_w = int(image.width * ratio)
        new_h = int(image.height * ratio)
        image = image.resize((new_w, new_h), Image.LANCZOS)

    print(f"Image size: {original_size} -> {image.size}")
    print()

    # Test different prompts for section detection
    prompts = [
        "Detect each dictionary entry on this page. Output bounding box for each entry.",
        "This is a dictionary page. Find all separate entries/sections and give their coordinates.",
        "Identify the distinct text blocks or sections on this page. Output coordinates for each.",
    ]

    for i, prompt in enumerate(prompts):
        print(f"--- Test {i+1}: {prompt[:50]}... ---")

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

        start = time.time()
        with torch.no_grad():
            generated_ids = model.generate(**inputs, max_new_tokens=1024)

        generated_ids_trimmed = [
            out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False
        )[0]

        elapsed = time.time() - start
        print(f"Time: {elapsed:.1f}s")
        print(f"Output: {output_text[:200]}...")
        print()

if __name__ == "__main__":
    main()
