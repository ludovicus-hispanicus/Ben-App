"""
Test DeepSeek-OCR on multiple PDF pages.
DeepSeek-OCR is a 3B parameter model optimized for document OCR.
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
MODEL_ID = "deepseek-ai/deepseek-vl2-tiny"  # Smaller model that fits in 8GB


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

        # Clear any existing cache
        torch.cuda.empty_cache()
        free_mem = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()
        print(f"Free VRAM: {free_mem / 1024**3:.1f} GB")
    else:
        print("ERROR: No GPU available. Exiting.")
        sys.exit(1)

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
            dpi=150  # Lower DPI to reduce memory usage
        )
        if page_images:
            images.append((page_num, page_images[0]))
            print(f"  Page {page_num}: {page_images[0].size}")

    return images


def load_model():
    """Load DeepSeek-VL2-Tiny model"""
    from transformers import AutoModelForCausalLM, AutoProcessor

    print("=" * 60)
    print(f"Loading DeepSeek model: {MODEL_ID}")
    print("=" * 60)
    print("This may take a few minutes on first run...")

    start = time.time()

    # Load processor
    processor = AutoProcessor.from_pretrained(
        MODEL_ID,
        trust_remote_code=True
    )

    # Load model with memory optimizations
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        low_cpu_mem_usage=True
    )

    print(f"Model loaded in {time.time() - start:.1f}s")
    print()

    return model, processor


def process_image(model, processor, image, page_num: int) -> dict:
    """Process a single image with DeepSeek-VL2"""

    # Dictionary-optimized prompt
    prompt = """<image>
You are an expert in reading Assyriological dictionaries (AHw, CAD).

Transcribe all text from this dictionary page image.

Rules:
1. Read left column completely first, then right column
2. Preserve reading order within each entry
3. Include all special characters exactly: š, ṣ, ṭ, ḫ, ā, ē, ī, ū
4. Headwords (lemmas) should be clearly identifiable
5. Preserve abbreviations as-is: RA, AfO, CT, ARM, etc.
6. Keep citation formats: ia-bi-le, ia-a-nu, etc.

Output plain text transcription:"""

    print(f"Processing page {page_num}...")
    start = time.time()

    try:
        # Process with the model's processor
        inputs = processor(
            text=prompt,
            images=[image],
            return_tensors="pt"
        ).to(model.device)

        # Generate
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=4096,
                do_sample=False,
                use_cache=True
            )

        # Decode - skip the input tokens
        input_len = inputs["input_ids"].shape[1]
        result = processor.decode(outputs[0][input_len:], skip_special_tokens=True)

        processing_time = time.time() - start

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        result = f"ERROR: {str(e)}"
        processing_time = time.time() - start

    finally:
        # Clear cache to free memory
        torch.cuda.empty_cache()

    return {
        "page": page_num,
        "text": result.strip(),
        "processing_time_s": processing_time
    }


def save_results(results: list, output_dir: str):
    """Save results to files"""
    os.makedirs(output_dir, exist_ok=True)

    # Save individual page results
    for result in results:
        output_file = os.path.join(output_dir, f"deepseek_ocr_page_{result['page']}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Page: {result['page']}\n")
            f.write(f"Processing Time: {result['processing_time_s']:.1f}s\n")
            f.write("=" * 50 + "\n\n")
            f.write(result["text"])
        print(f"Saved: {output_file}")

    # Save combined results
    combined_file = os.path.join(output_dir, "deepseek_ocr_combined.txt")
    with open(combined_file, "w", encoding="utf-8") as f:
        f.write("DeepSeek OCR Results\n")
        f.write("=" * 60 + "\n\n")
        for result in results:
            f.write(f"--- PAGE {result['page']} ({result['processing_time_s']:.1f}s) ---\n\n")
            f.write(result["text"])
            f.write("\n\n")
    print(f"Saved combined: {combined_file}")


def main():
    check_environment()

    # Check if PDF exists
    if not os.path.exists(PDF_PATH):
        print(f"ERROR: PDF not found: {PDF_PATH}")
        print("Please ensure the PDF is in the current directory.")
        sys.exit(1)

    # Load PDF pages
    try:
        pages = load_pdf_pages(PDF_PATH, PAGES_TO_TEST)
    except Exception as e:
        print(f"ERROR loading PDF: {e}")
        print("\nMake sure poppler is installed:")
        print("  Windows: Download from https://github.com/osminber/pdf2image#installing-poppler")
        sys.exit(1)

    # Load model
    model, processor = load_model()

    # Process each page
    print("=" * 60)
    print("Processing Pages")
    print("=" * 60)

    results = []
    for page_num, image in pages:
        try:
            result = process_image(model, processor, image, page_num)
            results.append(result)
            print(f"  Page {page_num}: {result['processing_time_s']:.1f}s, {len(result['text'])} chars")
        except Exception as e:
            print(f"  Page {page_num}: ERROR - {e}")
            import traceback
            traceback.print_exc()

    # Save results
    print()
    print("=" * 60)
    print("Saving Results")
    print("=" * 60)
    save_results(results, OUTPUT_DIR)

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total_time = sum(r["processing_time_s"] for r in results)
    total_chars = sum(len(r["text"]) for r in results)
    print(f"Pages processed: {len(results)}")
    print(f"Total time: {total_time:.1f}s")
    print(f"Total characters: {total_chars}")
    if results:
        print(f"Avg time per page: {total_time / len(results):.1f}s")

        # Preview first result
        print()
        print("=" * 60)
        print(f"Preview (Page {results[0]['page']}, first 1000 chars):")
        print("=" * 60)
        print(results[0]["text"][:1000])


if __name__ == "__main__":
    main()
