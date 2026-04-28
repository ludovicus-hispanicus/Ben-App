import os
import time
from PIL import Image
import torch
from transformers import AutoProcessor, AutoModel

MODEL_ID = "nvidia/NVIDIA-Nemotron-Parse-v1.1"

def test_tiling_idea(image_path):
    print(f"Loading image {image_path}")
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    print(f"Original image size: {w}x{h}")

    # The idea is "four parts, two per column"
    # This likely means 2 columns, each split in half vertically. So a 2x2 grid.
    w_mid = w // 2
    h_mid = h // 2

    tiles = [
        ("top_left", image.crop((0, 0, w_mid, h_mid))),
        ("bottom_left", image.crop((0, h_mid, w_mid, h))),
        ("top_right", image.crop((w_mid, 0, w, h_mid))),
        ("bottom_right", image.crop((w_mid, h_mid, w, h)))
    ]

    print("Loading Nemotron model...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
    
    if device == "cuda":
        torch.cuda.empty_cache()
        # Loading similar to the test_nemotron_ocr.py
        model = AutoModel.from_pretrained(
            MODEL_ID,
            trust_remote_code=True,
            torch_dtype=torch.float16,  # Use float16 as per nemotron_ocr_service
            low_cpu_mem_usage=True,
        ).to("cuda")
    else:
        model = AutoModel.from_pretrained(
            MODEL_ID,
            trust_remote_code=True,
            torch_dtype=torch.float32,
            low_cpu_mem_usage=True,
        )

    print("Model loaded. Testing first tile (top left)...")
    name, tile_img = tiles[0]
    
    # Resize if needed to prevent memory issues
    max_dim = 1024
    if max(tile_img.width, tile_img.height) > max_dim:
        ratio = max_dim / max(tile_img.width, tile_img.height)
        new_w = int(tile_img.width * ratio)
        new_h = int(tile_img.height * ratio)
        tile_img = tile_img.resize((new_w, new_h), Image.LANCZOS)
        print(f"Resized {name} tile to {new_w}x{new_h}")
        
    task_prompt = "</s><s><predict_bbox><predict_classes><output_markdown>"
    
    start_time = time.time()
    inputs = processor(
        images=[tile_img],
        text=task_prompt,
        return_tensors="pt",
        add_special_tokens=False
    )
    inputs = {k: v.to(device) if hasattr(v, 'to') else v for k, v in inputs.items()}
    
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=4096,
            do_sample=False,
            use_cache=False,
        )
        
    raw_text = processor.batch_decode(output_ids, skip_special_tokens=True)[0]
    elapsed = time.time() - start_time
    
    print(f"Inference took {elapsed:.2f}s")
    print("\n--- RAW TEXT ---")
    
    output_path = "explore_ocr_output.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"Tile: {name}\n")
        f.write(raw_text)
    print(f"Saved OCR to {output_path}")

if __name__ == "__main__":
    test_tiling_idea("C:/Users/wende/Documents/GitHub/BEn-app/server/src/data/yolo/datasets/D_auto/images/train/page_002.png")
