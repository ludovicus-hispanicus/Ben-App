"""
Test Florence-2 on multiple PDF pages for OCR.
Florence-2 is a small (~0.5GB) but powerful vision model from Microsoft.
Works well with document OCR tasks.
"""

import os
import sys
import time
import torch
from pathlib import Path

# Settings
PDF_PATH = "Q_II 886-931.pdf"
PAGES_TO_TEST = [0, 1, 2]
OUTPUT_DIR = "ocr_test_results"
MODEL_ID = "microsoft/Florence-2-base"  # ~0.5GB, fits easily in 8GB VRAM


def check_environment():
    """Check GPU and dependencies"""
    print("=" * 60)
    print("Environment Check")
    print("=" * 60)

    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")

    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"VRAM: {vram:.1f} GB")
        torch.cuda.empty_cache()
    else:
        print("WARNING: No GPU. Running on CPU (slower).")

    print()


def load_pdf_pages(pdf_path: str, pages: list):
    """Load specific pages from PDF"""
    from pdf2image import convert_from_path

    print(f"Loading pages {pages} from {pdf_path}...")

    images = []
    for page_num in pages:
        page_images = convert_from_path(
            pdf_path,
            first_page=page_num + 1,
            last_page=page_num + 1,
            dpi=150
        )
        if page_images:
            images.append((page_num, page_images[0]))
            print(f"  Page {page_num}: {page_images[0].size}")

    return images


def load_model():
    """Load Florence-2 model"""
    from transformers import AutoModelForCausalLM, AutoProcessor

    print("=" * 60)
    print(f"Loading Florence-2 model: {MODEL_ID}")
    print("=" * 60)
    print("This is a small model (~0.5GB), should load quickly...")

    start = time.time()

    # Load processor
    processor = AutoProcessor.from_pretrained(
        MODEL_ID,
        trust_remote_code=True
    )

    # Load model - use float32 to avoid dtype issues
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float32,  # Use float32 for compatibility
        trust_remote_code=True
    ).to(device)

    print(f"Model loaded in {time.time() - start:.1f}s")

    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        print(f"GPU memory used: {allocated:.2f} GB")

    print()

    return model, processor, device


def process_image(model, processor, device, image, page_num: int) -> dict:
    """Process a single image with Florence-2"""

    print(f"Processing page {page_num}...")
    start = time.time()

    results_text = []

    try:
        # Florence-2 uses task prompts
        # For OCR, we use <OCR> task
        task_prompt = "<OCR>"

        # Process image
        inputs = processor(
            text=task_prompt,
            images=image,
            return_tensors="pt"
        ).to(device)

        # Generate
        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=4096,
                num_beams=3,
                do_sample=False
            )

        # Decode
        generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]

        # Parse Florence output
        parsed = processor.post_process_generation(
            generated_text,
            task=task_prompt,
            image_size=(image.width, image.height)
        )

        # Extract OCR text
        if task_prompt in parsed:
            ocr_result = parsed[task_prompt]
            results_text.append(f"=== OCR Result ===\n{ocr_result}")

        # Also try OCR_WITH_REGION for more detailed output
        task_prompt2 = "<OCR_WITH_REGION>"
        inputs2 = processor(
            text=task_prompt2,
            images=image,
            return_tensors="pt"
        ).to(device)

        with torch.no_grad():
            generated_ids2 = model.generate(
                input_ids=inputs2["input_ids"],
                pixel_values=inputs2["pixel_values"],
                max_new_tokens=4096,
                num_beams=3,
                do_sample=False
            )

        generated_text2 = processor.batch_decode(generated_ids2, skip_special_tokens=False)[0]
        parsed2 = processor.post_process_generation(
            generated_text2,
            task=task_prompt2,
            image_size=(image.width, image.height)
        )

        if task_prompt2 in parsed2:
            ocr_with_regions = parsed2[task_prompt2]
            if "labels" in ocr_with_regions:
                # Extract just the text labels
                text_labels = ocr_with_regions.get("labels", [])
                results_text.append(f"\n=== Text Regions ({len(text_labels)} found) ===")
                results_text.append("\n".join(text_labels))

        result = "\n\n".join(results_text)
        processing_time = time.time() - start

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        result = f"ERROR: {str(e)}"
        processing_time = time.time() - start

    finally:
        torch.cuda.empty_cache() if torch.cuda.is_available() else None

    return {
        "page": page_num,
        "text": result.strip(),
        "processing_time_s": processing_time
    }


def save_results(results: list, output_dir: str):
    """Save results to files"""
    os.makedirs(output_dir, exist_ok=True)

    for result in results:
        output_file = os.path.join(output_dir, f"florence2_ocr_page_{result['page']}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Model: Florence-2-base\n")
            f.write(f"Page: {result['page']}\n")
            f.write(f"Processing Time: {result['processing_time_s']:.1f}s\n")
            f.write("=" * 50 + "\n\n")
            f.write(result["text"])
        print(f"Saved: {output_file}")

    combined_file = os.path.join(output_dir, "florence2_ocr_combined.txt")
    with open(combined_file, "w", encoding="utf-8") as f:
        f.write("Florence-2 OCR Results\n")
        f.write("=" * 60 + "\n\n")
        for result in results:
            f.write(f"--- PAGE {result['page']} ({result['processing_time_s']:.1f}s) ---\n\n")
            f.write(result["text"])
            f.write("\n\n")
    print(f"Saved combined: {combined_file}")


def main():
    check_environment()

    if not os.path.exists(PDF_PATH):
        print(f"ERROR: PDF not found: {PDF_PATH}")
        sys.exit(1)

    try:
        pages = load_pdf_pages(PDF_PATH, PAGES_TO_TEST)
    except Exception as e:
        print(f"ERROR loading PDF: {e}")
        print("\nMake sure poppler is installed.")
        sys.exit(1)

    model, processor, device = load_model()

    print("=" * 60)
    print("Processing Pages")
    print("=" * 60)

    results = []
    for page_num, image in pages:
        try:
            result = process_image(model, processor, device, image, page_num)
            results.append(result)
            print(f"  Page {page_num}: {result['processing_time_s']:.1f}s, {len(result['text'])} chars")
        except Exception as e:
            print(f"  Page {page_num}: ERROR - {e}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 60)
    print("Saving Results")
    print("=" * 60)
    save_results(results, OUTPUT_DIR)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_time = sum(r["processing_time_s"] for r in results)
    total_chars = sum(len(r["text"]) for r in results)
    print(f"Model: {MODEL_ID}")
    print(f"Pages processed: {len(results)}")
    print(f"Total time: {total_time:.1f}s")
    print(f"Total characters: {total_chars}")
    if results:
        print(f"Avg time per page: {total_time / len(results):.1f}s")
        print()
        print("=" * 60)
        print(f"Preview (Page {results[0]['page']}, first 1000 chars):")
        print("=" * 60)
        print(results[0]["text"][:1000])


if __name__ == "__main__":
    main()
