"""
Test Kraken BLLA (Baseline Layout Analysis) for region/layout detection.
"""
import sys
import os
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from PIL import Image, ImageDraw
from kraken import blla
from kraken.lib import vgsl

def main():
    image_path = "yolo_dataset/images/train/page_3.png"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("=" * 60)
    print("Kraken BLLA Layout Detection Test")
    print("=" * 60)
    print(f"Image: {image_path}")
    print()

    # Load image
    image = Image.open(image_path).convert("RGB")
    print(f"Image size: {image.size}")
    print()

    # Run BLLA segmentation
    print("Running BLLA segmentation...")
    print("(Using default model)")

    try:
        # Run baseline segmentation
        result = blla.segment(image)

        print(f"\nSegmentation result type: {type(result)}")
        print(f"Result attributes: {dir(result)}")

        # Check what's in the result
        if hasattr(result, 'regions'):
            print(f"\nRegions detected: {len(result.regions)}")
            for i, (region_type, regions) in enumerate(result.regions.items()):
                print(f"  {region_type}: {len(regions)} regions")
                for j, region in enumerate(regions[:3]):  # Show first 3
                    print(f"    Region {j+1}: {region}")

        if hasattr(result, 'lines'):
            print(f"\nLines detected: {len(result.lines)}")
            for i, line in enumerate(result.lines[:5]):  # Show first 5
                print(f"  Line {i+1}: {line}")

        # Visualize
        print("\nDrawing detected elements...")
        img_vis = image.copy()
        draw = ImageDraw.Draw(img_vis)

        # Draw regions if available
        if hasattr(result, 'regions'):
            colors = {'text': 'red', 'paragraph': 'blue', 'default': 'green'}
            for region_type, regions in result.regions.items():
                color = colors.get(region_type, 'yellow')
                for region in regions:
                    if hasattr(region, 'boundary'):
                        # Draw polygon
                        points = [(p[0], p[1]) for p in region.boundary]
                        if len(points) >= 3:
                            draw.polygon(points, outline=color, width=2)

        # Draw lines/baselines if available
        if hasattr(result, 'lines'):
            for i, line in enumerate(result.lines[:50]):  # Limit to 50 lines
                if hasattr(line, 'baseline'):
                    points = [(p[0], p[1]) for p in line.baseline]
                    if len(points) >= 2:
                        draw.line(points, fill='cyan', width=2)
                if hasattr(line, 'boundary'):
                    points = [(p[0], p[1]) for p in line.boundary]
                    if len(points) >= 3:
                        draw.polygon(points, outline='magenta', width=1)

        # Save visualization
        output_path = "kraken_blla_detected.png"
        img_vis.save(output_path)
        print(f"Visualization saved to: {output_path}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
