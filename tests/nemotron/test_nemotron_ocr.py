"""
Test script for NVIDIA Nemotron-Parse v1.1 local inference.
Updated based on official Hugging Face usage example.
"""

import argparse
import time
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor, AutoTokenizer, GenerationConfig

def main():
    parser = argparse.ArgumentParser(description="Test NVIDIA Nemotron Parse locally")
    parser.add_argument("image", help="Path to image file to parse")
    args = parser.parse_args()

    model_path = "nvidia/NVIDIA-Nemotron-Parse-v1.1"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    print(f"Loading {model_path} on {device}...")
    start_time = time.time()

    # Load model and processor
    # Note: Usage example uses AutoModel, typically VLM requires trust_remote_code=True
    model = AutoModel.from_pretrained(
        model_path,
        trust_remote_code=True,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32
    ).to(device).eval()

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
    generation_config = GenerationConfig.from_pretrained(model_path, trust_remote_code=True)

    print(f"Model loaded in {time.time() - start_time:.2f}s")

    # Load image
    try:
        image = Image.open(args.image).convert("RGB")
    except Exception as e:
        print(f"Error opening image: {e}")
        return

    # Task prompt specific to Nemotron Parse
    task_prompt = "</s><s><predict_bbox><predict_classes><output_markdown>" 

    print("Processing image...")
    start_time = time.time()

    # Process image
    inputs = processor(
        images=[image], 
        text=task_prompt, 
        return_tensors="pt", 
        add_special_tokens=False
    ).to(device)

    # Generate text
    with torch.no_grad():
        outputs = model.generate(**inputs, generation_config=generation_config)

    # Decode the generated text
    generated_text = processor.batch_decode(outputs, skip_special_tokens=True)[0]

    processing_time = (time.time() - start_time) * 1000

    # Save to file to ensure correct encoding
    output_file = "final_ocr_result.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("="*50 + "\n")
        f.write("RESULT\n")
        f.write("="*50 + "\n")
        f.write(generated_text + "\n")
        f.write("="*50 + "\n")
        f.write(f"Time: {processing_time:.2f}ms on {device}\n")

    print(f"Results saved to {output_file}")

if __name__ == "__main__":
    main()
