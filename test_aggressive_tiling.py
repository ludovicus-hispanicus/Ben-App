import os
from PIL import Image
from io import BytesIO
from pathlib import Path

# Paths
SOURCE_DIR = r"C:\Users\wende\Documents\GitHub\BEn-app\server\src\data\pages\S_4fqqm1"
OUTPUT_DIR = r"C:\Users\wende\Documents\GitHub\BEn-app\test_aggressive_output"

def _split_image_into_tiles(image_path, mode="full_page_clipped"):
    img = Image.open(image_path)
    width, height = img.size
    fmt = img.format or "PNG"
    tiles = []
    
    if mode == "full_page_clipped":
        # Aggressive margin reduction (refined to 10/10)
        mx = int(width * 0.10)
        my = int(height * 0.10)
        inner_w = width - 2 * mx
        inner_h = height - 2 * my
        
        crop = img.crop((mx, my, mx + inner_w, my + inner_h))
        tiles.append(crop)
    
    return tiles

def run_test():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    images = [f for f in os.listdir(SOURCE_DIR) if f.endswith(".png")]
    test_images = images[:10]
    
    print(f"Processing {len(test_images)} images from {SOURCE_DIR}...")
    
    for filename in test_images:
        path = os.path.join(SOURCE_DIR, filename)
        tiles = _split_image_into_tiles(path, mode="full_page_clipped")
        
        for i, tile in enumerate(tiles):
            output_name = f"clipped_{filename}"
            output_path = os.path.join(OUTPUT_DIR, output_name)
            tile.save(output_path)
            print(f"  Saved {output_name}")

if __name__ == "__main__":
    run_test()
