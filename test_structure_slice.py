import os
from PIL import Image

def slice_structural_components(image_path, output_dir):
    print(f"Loading image from {image_path}")
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    print(f"Original image size: {w}x{h}")

    # Define approximate ratios based on typical CAD volumes
    # You might need to adjust these percentages slightly based on the exact margins
    header_ratio = 0.08  # Top 8%
    footer_ratio = 0.94  # Bottom 6%

    header_y = int(h * header_ratio)
    footer_y = int(h * footer_ratio)

    print(f"Slice points (Y-axis): Header ends at {header_y}, Footer starts at {footer_y}")

    # 1. Extract Header (Guidewords)
    # Box: (left, upper, right, lower)
    header_box = (0, 0, w, header_y)
    header_img = image.crop(header_box)
    
    # 2. Extract Body
    body_box = (0, header_y, w, footer_y)
    body_img = image.crop(body_box)

    # 3. Extract Footer (Page Number)
    footer_box = (0, footer_y, w, h)
    footer_img = image.crop(footer_box)

    # Create output dir if needed
    os.makedirs(output_dir, exist_ok=True)
    basename = os.path.basename(image_path).split('.')[0]

    h_path = os.path.join(output_dir, f"{basename}_1_header.png")
    b_path = os.path.join(output_dir, f"{basename}_2_body.png")
    f_path = os.path.join(output_dir, f"{basename}_3_footer.png")

    header_img.save(h_path)
    body_img.save(b_path)
    footer_img.save(f_path)
    
    print(f"Saved Header: {h_path} (Size: {header_img.size})")
    print(f"Saved Body: {b_path} (Size: {body_img.size})")
    print(f"Saved Footer: {f_path} (Size: {footer_img.size})")
    
    # Optional: Also slice the body into 2 columns just to show
    col_w = w // 2
    col1_img = body_img.crop((0, 0, col_w, body_img.height))
    col2_img = body_img.crop((col_w, 0, w, body_img.height))
    
    c1_path = os.path.join(output_dir, f"{basename}_2_body_col1.png")
    c2_path = os.path.join(output_dir, f"{basename}_2_body_col2.png")
    col1_img.save(c1_path)
    col2_img.save(c2_path)
    print(f"Saved Body Col1: {c1_path}")
    print(f"Saved Body Col2: {c2_path}")


if __name__ == "__main__":
    test_image = "C:/Users/wende/Documents/GitHub/BEn-app/server/src/data/pages/CAD_PDF_bilojz/page_016.png"
    out_dir = "C:/Users/wende/Documents/GitHub/BEn-app/slices_output"
    slice_structural_components(test_image, out_dir)
