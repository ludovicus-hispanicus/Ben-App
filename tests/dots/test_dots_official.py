"""
Test dots.ocr using official repository approach.
Modified for Windows (no flash-attn, uses eager attention).
Includes image resizing to fit in limited VRAM.
"""
import os
import sys

# Set environment variable for local rank
if "LOCAL_RANK" not in os.environ:
    os.environ["LOCAL_RANK"] = "0"

import torch
from transformers import AutoModelForCausalLM, AutoProcessor
from qwen_vl_utils import process_vision_info
from PIL import Image
import time

# Use our local model path
MODEL_PATH = "./models/DotsOCR"

# Max pixels to avoid OOM (reduce if still OOM)
MAX_PIXELS = 1024 * 1024  # 1 megapixel

def resize_image_if_needed(image_path, max_pixels=MAX_PIXELS):
    """Resize image if it exceeds max_pixels."""
    img = Image.open(image_path)
    current_pixels = img.width * img.height

    if current_pixels > max_pixels:
        scale = (max_pixels / current_pixels) ** 0.5
        new_width = int(img.width * scale)
        new_height = int(img.height * scale)
        print(f"Resizing image from {img.width}x{img.height} to {new_width}x{new_height}")
        img = img.resize((new_width, new_height), Image.LANCZOS)

        # Save resized image temporarily
        temp_path = "temp_resized.png"
        img.save(temp_path)
        return temp_path, img

    return image_path, img

def inference(image_path, prompt, model, processor):
    """Run inference on a single image."""
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": image_path
                },
                {"type": "text", "text": prompt}
            ]
        }
    ]

    # Preparation for inference
    text = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )

    inputs = inputs.to("cuda")

    # Clear cache before generation
    torch.cuda.empty_cache()

    # Inference
    start = time.time()
    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=4096)

    generated_ids_trimmed = [
        out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )[0]

    print(f"Generation time: {time.time() - start:.1f}s")
    return output_text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_dots_official.py <image_path> [prompt]")
        print("Example: python test_dots_official.py page1.png")
        sys.exit(1)

    image_path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else "OCR this image."

    print(f"Loading model from: {MODEL_PATH}")
    start = time.time()

    # Load model with eager attention (no flash-attn required)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        attn_implementation="eager",  # Use eager instead of flash_attention_2
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True
    )

    processor = AutoProcessor.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True
    )

    print(f"Model loaded in {time.time() - start:.1f}s")
    print(f"GPU memory: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

    # Resize image if needed
    processed_path, img = resize_image_if_needed(image_path)
    print(f"Image: {image_path} -> {img.width}x{img.height} ({img.width * img.height / 1e6:.2f} MP)")

    # Run inference
    print(f"Prompt: {prompt}")
    print("Generating...")

    try:
        result = inference(processed_path, prompt, model, processor)

        print("\n" + "=" * 60)
        print("RESULT:")
        print("=" * 60)
        print(result)

        # Save result
        output_file = os.path.splitext(os.path.basename(image_path))[0] + "_ocr_result.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"\nResult saved to: {output_file}")
    finally:
        # Cleanup temp file
        if processed_path != image_path and os.path.exists(processed_path):
            os.remove(processed_path)
