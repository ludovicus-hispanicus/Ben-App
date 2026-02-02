"""
Test dots.ocr inference with local model.
Uses the repackaged model with working processor (same as HuggingFace Space).
"""
import os
import sys
import time
import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoProcessor

# Use the repackaged model that has working processor files
# Will cache locally after first download
MODEL_ID = "prithivMLmods/Dots.OCR-Latest-BF16"

def test_inference(image_path: str, query: str = "OCR this image."):
    """Process a single image with dots.ocr"""

    print(f"Loading model: {MODEL_ID}")
    start = time.time()

    # Load processor
    processor = AutoProcessor.from_pretrained(
        MODEL_ID,
        trust_remote_code=True,
    )

    # Load model
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    ).eval()

    print(f"Model loaded in {time.time() - start:.1f}s")
    print(f"GPU memory: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

    # Load image
    image = Image.open(image_path).convert("RGB")
    print(f"Image size: {image.size}")

    # Format message (same as HuggingFace Space)
    messages = [{
        "role": "user",
        "content": [
            {"type": "image"},
            {"type": "text", "text": query},
        ]
    }]

    # Apply chat template
    prompt = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    # Process inputs
    inputs = processor(
        text=[prompt],
        images=[image],
        return_tensors="pt",
        padding=True
    ).to(model.device)

    # Generate
    print("Generating...")
    gen_start = time.time()

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=4096,
            do_sample=False,
        )

    # Decode only new tokens
    generated_ids = output_ids[:, inputs.input_ids.shape[1]:]
    result = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

    # Clean up
    result = result.replace("<|im_end|>", "").strip()

    print(f"Generation time: {time.time() - gen_start:.1f}s")
    print(f"Total time: {time.time() - start:.1f}s")

    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_dots_ocr_local.py <image_path> [query]")
        print("Example: python test_dots_ocr_local.py page1.png")
        print("Example: python test_dots_ocr_local.py page1.png 'Parse all text from this document.'")
        sys.exit(1)

    image_path = sys.argv[1]
    query = sys.argv[2] if len(sys.argv) > 2 else "OCR this image."

    result = test_inference(image_path, query)

    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(result)

    # Save result to file
    output_file = os.path.splitext(os.path.basename(image_path))[0] + "_ocr_result.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"\nResult saved to: {output_file}")
