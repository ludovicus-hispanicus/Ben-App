"""
Quick test: Run TrOCR (base-handwritten) on cuneiform line images
to see if the vision encoder can distinguish different lines.
"""
import glob
import os
import sys
import io

# Fix Windows console encoding for cuneiform characters
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

DATA_DIR = os.path.join(os.path.dirname(__file__), "src", "data", "kraken-training")

def main():
    print("Loading TrOCR base-handwritten model...")
    processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-handwritten")
    model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-handwritten")
    model.eval()
    print("Model loaded.\n")

    # Find line images with ground truth
    pairs = []
    for gt_file in sorted(glob.glob(os.path.join(DATA_DIR, "*.gt.txt")))[:10]:
        png_file = gt_file.replace(".gt.txt", ".png")
        if os.path.exists(png_file):
            with open(gt_file, "r", encoding="utf-8") as f:
                gt_text = f.read().strip()
            pairs.append((png_file, gt_text))

    if not pairs:
        # Try merged directory
        for gt_file in sorted(glob.glob(os.path.join(DATA_DIR, "merged", "*.gt.txt")))[:10]:
            png_file = gt_file.replace(".gt.txt", ".png")
            if os.path.exists(png_file):
                with open(gt_file, "r", encoding="utf-8") as f:
                    gt_text = f.read().strip()
                pairs.append((png_file, gt_text))

    if not pairs:
        print("No training pairs found!")
        return

    print(f"Testing {len(pairs)} line images...\n")
    print("=" * 80)

    for png_path, gt_text in pairs:
        img = Image.open(png_path).convert("RGB")
        w, h = img.size

        pixel_values = processor(images=img, return_tensors="pt").pixel_values
        generated_ids = model.generate(pixel_values, max_new_tokens=128)
        predicted = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

        name = os.path.basename(png_path)
        print(f"Image: {name} ({w}x{h})")
        print(f"  GT:   {gt_text}")
        print(f"  Pred: {predicted}")
        print()

    print("=" * 80)
    print("\nKey things to check:")
    print("1. Are predictions DIFFERENT for each image? (vs Qwen repeating same line)")
    print("2. Does output length roughly match input image width?")
    print("3. Any structure in the output? (even wrong text is a good sign)")

if __name__ == "__main__":
    main()
