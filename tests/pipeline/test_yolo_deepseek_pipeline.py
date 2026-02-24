"""
Full OCR Pipeline: YOLO (layout detection) + DeepSeek (OCR)
1. YOLO detects dictionary entry bounding boxes
2. Crop each detected entry
3. DeepSeek OCR transcribes each snippet
4. Combine results
"""
import sys
import os
import io
import time
import base64

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add server src to path for DeepSeek service
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server", "src"))

from PIL import Image
from io import BytesIO
from ultralytics import YOLO


def main():
    image_path = "yolo_dataset/images/train/page_3.png"
    model_path = "runs/detect/runs/detect/dictionary_layout/weights/best.pt"

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    if not os.path.exists(model_path):
        print(f"Model not found: {model_path}")
        return

    print("=" * 70)
    print("FULL PIPELINE: YOLO (layout) + DeepSeek (OCR)")
    print("=" * 70)
    print(f"Image: {image_path}")
    print(f"YOLO Model: {model_path}")
    print()

    # ==================== STAGE 1: Layout Detection with YOLO ====================
    print("=" * 70)
    print("STAGE 1: Layout Detection (YOLO)")
    print("=" * 70)

    # Load YOLO model
    print("Loading YOLO model...")
    yolo_model = YOLO(model_path)
    print(f"Classes: {yolo_model.names}")

    # Load image
    original_image = Image.open(image_path).convert("RGB")
    original_width, original_height = original_image.size
    print(f"Image size: {original_width}x{original_height}")

    # Run YOLO detection
    print("Running YOLO detection...")
    start_yolo = time.time()
    results = yolo_model(original_image, conf=0.5, device='cpu')  # Higher confidence threshold
    yolo_time = time.time() - start_yolo
    print(f"YOLO detection time: {yolo_time:.2f}s")

    # Extract entry boxes (class 0 = 'entry')
    result = results[0]
    entry_boxes = []
    for box in result.boxes:
        cls = int(box.cls[0].item())
        if cls == 0:  # entry class
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = box.conf[0].item()
            entry_boxes.append({
                'x1': int(x1),
                'y1': int(y1),
                'x2': int(x2),
                'y2': int(y2),
                'conf': conf
            })

    # Sort by y position (top to bottom), then x (left to right)
    entry_boxes.sort(key=lambda b: (b['y1'], b['x1']))

    print(f"Detected {len(entry_boxes)} dictionary entries")
    for i, box in enumerate(entry_boxes):
        print(f"  {i+1}. ({box['x1']},{box['y1']})->({box['x2']},{box['y2']}) conf={box['conf']:.2f}")

    if len(entry_boxes) == 0:
        print("ERROR: No entries detected!")
        return

    # ==================== STAGE 2: OCR with DeepSeek ====================
    print()
    print("=" * 70)
    print("STAGE 2: OCR (DeepSeek-OCR-2)")
    print("=" * 70)

    # Re-initialize CUDA after YOLO CPU inference
    import torch
    if torch.cuda.is_available():
        torch.cuda.init()
        torch.cuda.set_device(0)
        torch.cuda.empty_cache()
        print(f"CUDA initialized: device {torch.cuda.current_device()}")

    from services import deepseek_ocr_service

    print("Loading DeepSeek-OCR-2...")
    if not deepseek_ocr_service.load_model():
        print("ERROR: Failed to load DeepSeek")
        return
    print("DeepSeek loaded!")
    print()

    # Process each entry
    results_list = []
    total_ocr_time = 0

    # Limit to first 10 entries for testing
    test_entries = entry_boxes[:10]
    print(f"Processing {len(test_entries)} entries...")
    print()

    for i, box in enumerate(test_entries):
        # Add padding
        padding = 5
        x1 = max(0, box['x1'] - padding)
        y1 = max(0, box['y1'] - padding)
        x2 = min(original_width, box['x2'] + padding)
        y2 = min(original_height, box['y2'] + padding)

        # Crop snippet
        snippet = original_image.crop((x1, y1, x2, y2))
        snippet_width = x2 - x1
        snippet_height = y2 - y1

        # Convert to base64
        buffer = BytesIO()
        snippet.save(buffer, format="PNG")
        snippet_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # OCR
        print(f"  Entry {i+1}/{len(test_entries)} ({snippet_width}x{snippet_height}px)...", end=" ", flush=True)
        start_ocr = time.time()
        ocr_result = deepseek_ocr_service.ocr_from_base64(snippet_base64)
        ocr_time = time.time() - start_ocr
        total_ocr_time += ocr_time

        if ocr_result["success"]:
            text = ocr_result["text"].strip()
            print(f"{ocr_time:.1f}s - {len(text)} chars")
            results_list.append({
                "entry_num": i + 1,
                "box": box,
                "text": text,
                "ocr_time": ocr_time,
            })
        else:
            print(f"FAILED: {ocr_result.get('error', 'Unknown')}")
            results_list.append({
                "entry_num": i + 1,
                "box": box,
                "text": "",
                "ocr_time": ocr_time,
                "error": ocr_result.get("error"),
            })

    # ==================== RESULTS ====================
    print()
    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"Layout detection (YOLO): {yolo_time:.2f}s")
    print(f"OCR time (DeepSeek): {total_ocr_time:.1f}s for {len(test_entries)} entries")
    print(f"Average per entry: {total_ocr_time/len(test_entries):.1f}s")
    print(f"Total pipeline time: {yolo_time + total_ocr_time:.1f}s")
    print()

    # Show extracted text
    print("=" * 70)
    print("EXTRACTED TEXT (first 5 entries)")
    print("=" * 70)
    for r in results_list[:5]:
        print(f"\n--- Entry {r['entry_num']} ---")
        text = r["text"]
        if len(text) > 300:
            print(text[:300] + "...")
        else:
            print(text if text else "[No text extracted]")

    # Save full output
    output_file = "yolo_deepseek_pipeline_output.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"YOLO + DeepSeek OCR Pipeline Results\n")
        f.write(f"Image: {image_path}\n")
        f.write(f"Total entries: {len(entry_boxes)}\n")
        f.write(f"Processed: {len(test_entries)}\n")
        f.write(f"YOLO time: {yolo_time:.2f}s\n")
        f.write(f"OCR time: {total_ocr_time:.1f}s\n")
        f.write("=" * 70 + "\n\n")

        for r in results_list:
            f.write(f"=== Entry {r['entry_num']} ===\n")
            f.write(f"Box: ({r['box']['x1']},{r['box']['y1']}) -> ({r['box']['x2']},{r['box']['y2']})\n")
            f.write(f"Confidence: {r['box']['conf']:.2f}\n")
            f.write(r["text"] + "\n\n")

    print(f"\nFull output saved to: {output_file}")


if __name__ == "__main__":
    main()
