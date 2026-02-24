"""
Test Qwen2-VL on multiple PDF pages for OCR.
Qwen2-VL-2B is well-supported and fits in 8GB VRAM.
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
MODEL_ID = "Qwen/Qwen2-VL-2B-Instruct"


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
            dpi=150
        )
        if page_images:
            images.append((page_num, page_images[0]))
            print(f"  Page {page_num}: {page_images[0].size}")

    return images


def load_model():
    """Load Qwen2-VL model"""
    from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

    print("=" * 60)
    print(f"Loading Qwen2-VL model: {MODEL_ID}")
    print("=" * 60)
    print("This may take a few minutes on first run...")

    start = time.time()

    # Load processor
    processor = AutoProcessor.from_pretrained(MODEL_ID)

    # Load model with memory optimizations for 8GB VRAM
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        low_cpu_mem_usage=True
    )

    print(f"Model loaded in {time.time() - start:.1f}s")

    # Print memory usage
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        print(f"GPU memory used: {allocated:.2f} GB")

    print()

    return model, processor


def process_image(model, processor, image, page_num: int) -> dict:
    """Process a single image with Qwen2-VL"""
    from qwen_vl_utils import process_vision_info

    # Save image temporarily
    temp_image_path = f"temp_page_{page_num}.png"
    image.save(temp_image_path)

    # Dictionary-optimized prompt using Qwen2-VL format
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": f"file://{os.path.abspath(temp_image_path)}"},
                {"type": "text", "text": """You are an expert in reading Assyriological dictionaries (AHw, CAD).

Transcribe all text from this dictionary page image.

Rules:
1. Read left column completely first, then right column
2. Preserve reading order within each entry
3. Include all special characters exactly: š, ṣ, ṭ, ḫ, ā, ē, ī, ū
4. Headwords (lemmas) should be clearly identifiable
5. Preserve abbreviations as-is: RA, AfO, CT, ARM, etc.
6. Keep citation formats exactly as shown

Output the complete text transcription:"""}
            ]
        }
    ]

    print(f"Processing page {page_num}...")
    start = time.time()

    try:
        # Apply chat template
        text = processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        # Process vision info
        image_inputs, video_inputs = process_vision_info(messages)

        # Prepare inputs
        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
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

        # Decode - skip input tokens
        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(inputs.input_ids, outputs)
        ]
        result = processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False
        )[0]

        processing_time = time.time() - start

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        result = f"ERROR: {str(e)}"
        processing_time = time.time() - start

    finally:
        # Cleanup temp file
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)

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
        output_file = os.path.join(output_dir, f"qwen2vl_ocr_page_{result['page']}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Model: Qwen2-VL-2B-Instruct\n")
            f.write(f"Page: {result['page']}\n")
            f.write(f"Processing Time: {result['processing_time_s']:.1f}s\n")
            f.write("=" * 50 + "\n\n")
            f.write(result["text"])
        print(f"Saved: {output_file}")

    # Save combined results
    combined_file = os.path.join(output_dir, "qwen2vl_ocr_combined.txt")
    with open(combined_file, "w", encoding="utf-8") as f:
        f.write("Qwen2-VL-2B OCR Results\n")
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
    print(f"Model: {MODEL_ID}")
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
