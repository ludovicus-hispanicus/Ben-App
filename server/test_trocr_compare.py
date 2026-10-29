"""
Compare TrOCR base model vs fine-tuned model on cuneiform line images.
Run after training to see the improvement.

Usage:
    python test_trocr_compare.py                    # auto-detect latest model
    python test_trocr_compare.py <model_name>       # specific model
"""
import glob
import json
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import torch
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

DATA_DIR = os.path.join(os.path.dirname(__file__), "src", "data", "kraken-training")
MODELS_DIR = os.path.join(os.environ.get("STORAGE_PATH", "data"), "trocr_models")


def load_model(model_path_or_hf_id):
    processor = TrOCRProcessor.from_pretrained(model_path_or_hf_id)
    model = VisionEncoderDecoderModel.from_pretrained(model_path_or_hf_id)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    return processor, model, device


def predict(processor, model, device, img):
    pixel_values = processor(images=img, return_tensors="pt").pixel_values.to(device)
    with torch.no_grad():
        generated_ids = model.generate(pixel_values, max_new_tokens=128)
    return processor.batch_decode(generated_ids, skip_special_tokens=True)[0]


def find_latest_model():
    registry_path = os.path.join(MODELS_DIR, "registry.json")
    if not os.path.exists(registry_path):
        return None
    with open(registry_path, "r") as f:
        registry = json.load(f)
    if not registry:
        return None
    latest = sorted(registry, key=lambda x: x.get("created", ""), reverse=True)[0]
    return latest["name"], latest["path"]


def find_pairs():
    pairs = []
    for pattern_dir in sorted(glob.glob(os.path.join(DATA_DIR, "*"))):
        if os.path.isdir(pattern_dir):
            for gt_file in sorted(glob.glob(os.path.join(pattern_dir, "*.gt.txt")))[:5]:
                png_file = gt_file.replace(".gt.txt", ".png")
                if os.path.exists(png_file):
                    with open(gt_file, "r", encoding="utf-8") as f:
                        gt_text = f.read().strip()
                    pairs.append((png_file, gt_text))
        if len(pairs) >= 10:
            break

    if not pairs:
        for gt_file in sorted(glob.glob(os.path.join(DATA_DIR, "**", "*.gt.txt"), recursive=True))[:10]:
            png_file = gt_file.replace(".gt.txt", ".png")
            if os.path.exists(png_file):
                with open(gt_file, "r", encoding="utf-8") as f:
                    gt_text = f.read().strip()
                pairs.append((png_file, gt_text))

    return pairs[:10]


def char_accuracy(pred, gt):
    """Simple character-level accuracy (Levenshtein-based)."""
    if not gt:
        return 1.0 if not pred else 0.0
    matches = sum(1 for a, b in zip(pred, gt) if a == b)
    return matches / max(len(pred), len(gt))


def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else None

    # Find fine-tuned model
    if model_name:
        ft_path = os.path.join(MODELS_DIR, model_name)
        if not os.path.exists(ft_path):
            print(f"Model not found: {ft_path}")
            return
        ft_name = model_name
    else:
        result = find_latest_model()
        if not result:
            print("No fine-tuned models found. Run training first.")
            return
        ft_name, ft_path = result

    print(f"Fine-tuned model: {ft_name}")
    print(f"Path: {ft_path}\n")

    # Load both models
    print("Loading base model (microsoft/trocr-base-handwritten)...")
    base_proc, base_model, base_device = load_model("microsoft/trocr-base-handwritten")

    print(f"Loading fine-tuned model ({ft_name})...")
    ft_proc, ft_model, ft_device = load_model(ft_path)

    # Find test pairs
    pairs = find_pairs()
    if not pairs:
        print("No test pairs found!")
        return

    print(f"\nComparing on {len(pairs)} line images...\n")
    print("=" * 90)

    base_accs = []
    ft_accs = []

    for png_path, gt_text in pairs:
        img = Image.open(png_path).convert("RGB")
        w, h = img.size

        base_pred = predict(base_proc, base_model, base_device, img)
        ft_pred = predict(ft_proc, ft_model, ft_device, img)

        base_acc = char_accuracy(base_pred, gt_text)
        ft_acc = char_accuracy(ft_pred, gt_text)
        base_accs.append(base_acc)
        ft_accs.append(ft_acc)

        improved = "+" if ft_acc > base_acc else ("-" if ft_acc < base_acc else "=")

        name = os.path.basename(png_path)
        print(f"Image: {name} ({w}x{h})")
        print(f"  GT:       {gt_text}")
        print(f"  Base:     {base_pred}  ({base_acc:.0%})")
        print(f"  Finetuned:{ft_pred}  ({ft_acc:.0%}) {improved}")
        print()

    print("=" * 90)
    avg_base = sum(base_accs) / len(base_accs)
    avg_ft = sum(ft_accs) / len(ft_accs)
    print(f"\nAverage char accuracy:")
    print(f"  Base model:      {avg_base:.1%}")
    print(f"  Fine-tuned ({ft_name}): {avg_ft:.1%}")
    print(f"  Improvement:     {avg_ft - avg_base:+.1%}")

    # Cleanup
    del base_model, ft_model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
