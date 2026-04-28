import os
import glob
from PIL import Image

def tile_image_with_margin_reduction(image_path, output_dir, margins, overlap_ratio=0.05):
    """
    margins: dict with 'left', 'right', 'top', 'bottom' as percentages (e.g., 0.10 for 10%)
    overlap_ratio: percentage of the active height to use as overlap between top and bottom tiles
    """
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    
    # 1. Calculate active area based on margins
    left_px = int(w * margins['left'])
    right_px = int(w * (1.0 - margins['right']))
    top_px = int(h * margins['top'])
    bottom_px = int(h * (1.0 - margins['bottom']))
    
    # 2. Crop out the margins (this leaves just the core text block)
    active_area = image.crop((left_px, top_px, right_px, bottom_px))
    aw, ah = active_area.size
    
    # 3. Tile the active area (2x2 grid -> 4 parts) with vertical overlap
    col_w = aw // 2
    row_h_mid = ah // 2
    overlap_px = int(ah * overlap_ratio)
    
    # Top tiles go a bit further down than the middle
    top_tile_bottom = min(ah, row_h_mid + overlap_px)
    # Bottom tiles start a bit higher than the middle
    bottom_tile_top = max(0, row_h_mid - overlap_px)
    
    tiles = {
        "1_top_left": active_area.crop((0, 0, col_w, top_tile_bottom)),
        "2_bottom_left": active_area.crop((0, bottom_tile_top, col_w, ah)),
        "3_top_right": active_area.crop((col_w, 0, aw, top_tile_bottom)),
        "4_bottom_right": active_area.crop((col_w, bottom_tile_top, aw, ah))
    }
    
    # 4. Save the tiles
    os.makedirs(output_dir, exist_ok=True)
    basename = os.path.basename(image_path).split('.')[0]
    
    saved_paths = []
    
    # Optional: save the whole active area to verify
    active_path = os.path.join(output_dir, f"{basename}_0_core_block.png")
    active_area.save(active_path)
    
    for suffix, tile_img in tiles.items():
        out_path = os.path.join(output_dir, f"{basename}_{suffix}.png")
        tile_img.save(out_path)
        saved_paths.append(out_path)
        
    return active_path, saved_paths

if __name__ == "__main__":
    test_image = "C:/Users/wende/Documents/GitHub/BEn-app/server/src/data/pages/CAD_PDF_bilojz/page_016.png"
    out_dir = "C:/Users/wende/Documents/GitHub/BEn-app/tiled_images_output"
    
    # Adjusted margins based on feedback:
    # Cut less on left/right (was 12%, down to 8%)
    # Cut more on top/bottom (was 5%, up to 10%)
    margins = {
        'left': 0.08,   
        'right': 0.08,  
        'top': 0.10,    
        'bottom': 0.10  
    }
    
    # Vertical overlap ratio (e.g. 5% means top and bottom tiles share the middle 10% of height)
    overlap_ratio = 0.05 
    
    print(f"Processing single test image: {test_image}")
    core, tiles = tile_image_with_margin_reduction(test_image, out_dir, margins, overlap_ratio)
    
    print(f"\nSaved cropped core block (margins removed) to:")
    print(f"  {core}")
    print("\nSaved 4 tiles (with vertical overlap) to:")
    for t in tiles:
        print(f"  {t}")
        
    print("\nLook in the 'tiled_images_output' folder to verify the crops!")
