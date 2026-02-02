"""
Test script to compare dots.ocr vs DeepSeek-OCR on dictionary images.

Requirements:
    pip install torch transformers accelerate pillow pdf2image qwen-vl-utils

For dots.ocr:
    pip install flash-attn --no-build-isolation

For DeepSeek-OCR:
    pip install unsloth

Usage:
    python test_ocr_models.py --image path/to/image.png
    python test_ocr_models.py --pdf path/to/file.pdf --page 0
    python test_ocr_models.py --model dots  # Test only dots.ocr
    python test_ocr_models.py --model deepseek  # Test only DeepSeek-OCR
"""

import argparse
import base64
import time
import os
from pathlib import Path

# Check GPU availability
def check_gpu():
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
            print(f"GPU: {gpu_name} ({gpu_mem:.1f} GB)")
            return True
        else:
            print("WARNING: No GPU available. Models will run on CPU (very slow).")
            return False
    except ImportError:
        print("PyTorch not installed. Run: pip install torch")
        return False


def load_image(image_path: str):
    """Load an image and return PIL Image"""
    from PIL import Image
    return Image.open(image_path).convert("RGB")


def load_pdf_page(pdf_path: str, page_num: int = 0):
    """Extract a page from PDF as PIL Image"""
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(pdf_path, first_page=page_num + 1, last_page=page_num + 1)
        if pages:
            return pages[0]
        raise ValueError(f"Could not extract page {page_num} from PDF")
    except ImportError:
        print("pdf2image not installed. Run: pip install pdf2image")
        print("Also install poppler: https://github.com/osminber/pdf2image#installing-poppler")
        raise


def image_to_base64(image) -> str:
    """Convert PIL Image to base64 string"""
    import io
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class DotsOCR:
    """dots.ocr model wrapper"""

    MODEL_ID = "rednote-hilab/dots.ocr"

    def __init__(self):
        self.model = None
        self.processor = None

    def load(self):
        """Load the dots.ocr model"""
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        print(f"Loading dots.ocr from {self.MODEL_ID}...")
        start = time.time()

        self.processor = AutoProcessor.from_pretrained(
            self.MODEL_ID,
            trust_remote_code=True
        )

        # Try flash attention first, fall back to eager
        try:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.MODEL_ID,
                attn_implementation="flash_attention_2",
                torch_dtype=torch.bfloat16,
                device_map="auto",
                trust_remote_code=True
            )
        except Exception as e:
            print(f"Flash attention not available, using eager: {e}")
            self.model = AutoModelForCausalLM.from_pretrained(
                self.MODEL_ID,
                torch_dtype=torch.bfloat16,
                device_map="auto",
                trust_remote_code=True
            )

        print(f"dots.ocr loaded in {time.time() - start:.1f}s")

    def process(self, image, prompt_mode: str = "layout_all") -> dict:
        """
        Process an image with dots.ocr

        Args:
            image: PIL Image
            prompt_mode: "layout_all" (text + layout) or "layout_only" (detection only)

        Returns:
            dict with text, processing_time_ms
        """
        import torch

        if self.model is None:
            self.load()

        # dots.ocr prompts
        if prompt_mode == "layout_all":
            prompt = "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>Parse all text and layout elements from this document image.<|im_end|>\n<|im_start|>assistant\n"
        else:
            prompt = "<|im_start|>user\n<|vision_start|><|image_pad|><|vision_end|>Detect layout elements only.<|im_end|>\n<|im_start|>assistant\n"

        start = time.time()

        # Process image
        inputs = self.processor(
            text=prompt,
            images=[image],
            return_tensors="pt"
        ).to(self.model.device)

        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=8192,
                do_sample=False,
                temperature=None,
                top_p=None,
            )

        # Decode
        result = self.processor.decode(outputs[0], skip_special_tokens=False)

        # Extract assistant response
        if "<|im_start|>assistant" in result:
            result = result.split("<|im_start|>assistant")[-1]
        if "<|im_end|>" in result:
            result = result.split("<|im_end|}")[0]

        processing_time_ms = int((time.time() - start) * 1000)

        return {
            "text": result.strip(),
            "processing_time_ms": processing_time_ms,
            "model": "dots.ocr"
        }


class DeepSeekOCR:
    """DeepSeek-OCR model wrapper"""

    MODEL_ID = "deepseek-ai/DeepSeek-OCR"

    def __init__(self):
        self.model = None
        self.processor = None

    def load(self):
        """Load the DeepSeek-OCR model"""
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        print(f"Loading DeepSeek-OCR from {self.MODEL_ID}...")
        start = time.time()

        self.processor = AutoProcessor.from_pretrained(
            self.MODEL_ID,
            trust_remote_code=True
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            self.MODEL_ID,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True
        )

        print(f"DeepSeek-OCR loaded in {time.time() - start:.1f}s")

    def process(self, image) -> dict:
        """
        Process an image with DeepSeek-OCR

        Args:
            image: PIL Image

        Returns:
            dict with text, processing_time_ms
        """
        import torch

        if self.model is None:
            self.load()

        # DeepSeek-OCR specific prompt for dictionary
        prompt = """Transcribe all text from this dictionary page image.

Rules:
1. Read left column completely first, then right column
2. Preserve reading order within each entry
3. Include all special characters exactly: š, ṣ, ṭ, ḫ, ā, ē, ī, ū
4. Headwords (lemmas) should be clearly identifiable
5. Preserve abbreviations as-is

Output the transcribed text:"""

        start = time.time()

        # Process
        inputs = self.processor(
            text=prompt,
            images=[image],
            return_tensors="pt"
        ).to(self.model.device)

        # Generate
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=8192,
                do_sample=False,
            )

        # Decode
        result = self.processor.decode(outputs[0], skip_special_tokens=True)

        # Remove the prompt from output if present
        if prompt in result:
            result = result.split(prompt)[-1]

        processing_time_ms = int((time.time() - start) * 1000)

        return {
            "text": result.strip(),
            "processing_time_ms": processing_time_ms,
            "model": "DeepSeek-OCR"
        }


def save_results(results: list, output_dir: str = "ocr_test_results"):
    """Save OCR results to files"""
    os.makedirs(output_dir, exist_ok=True)

    for result in results:
        model_name = result["model"].replace(".", "_").replace("-", "_")
        output_file = os.path.join(output_dir, f"{model_name}_result.txt")

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"Model: {result['model']}\n")
            f.write(f"Processing Time: {result['processing_time_ms']}ms\n")
            f.write("=" * 50 + "\n\n")
            f.write(result["text"])

        print(f"Saved: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Compare OCR models")
    parser.add_argument("--image", type=str, help="Path to image file")
    parser.add_argument("--pdf", type=str, help="Path to PDF file")
    parser.add_argument("--page", type=int, default=0, help="PDF page number (0-indexed)")
    parser.add_argument("--model", type=str, choices=["dots", "deepseek", "both"],
                       default="both", help="Which model to test")
    parser.add_argument("--output", type=str, default="ocr_test_results",
                       help="Output directory for results")

    args = parser.parse_args()

    # Check GPU
    check_gpu()

    # Load image
    if args.image:
        print(f"\nLoading image: {args.image}")
        image = load_image(args.image)
    elif args.pdf:
        print(f"\nLoading PDF page {args.page} from: {args.pdf}")
        image = load_pdf_page(args.pdf, args.page)
    else:
        print("Please provide --image or --pdf argument")
        print("\nExample usage:")
        print('  python test_ocr_models.py --image "path/to/dictionary_page.png"')
        print('  python test_ocr_models.py --pdf "Q_II 886-931.pdf" --page 0')
        return

    print(f"Image size: {image.size}")

    results = []

    # Test dots.ocr
    if args.model in ["dots", "both"]:
        print("\n" + "=" * 50)
        print("Testing dots.ocr")
        print("=" * 50)
        try:
            dots = DotsOCR()
            result = dots.process(image)
            results.append(result)
            print(f"\nProcessing time: {result['processing_time_ms']}ms")
            print(f"\nOutput preview (first 500 chars):\n{result['text'][:500]}...")
        except Exception as e:
            print(f"dots.ocr failed: {e}")
            import traceback
            traceback.print_exc()

    # Test DeepSeek-OCR
    if args.model in ["deepseek", "both"]:
        print("\n" + "=" * 50)
        print("Testing DeepSeek-OCR")
        print("=" * 50)
        try:
            deepseek = DeepSeekOCR()
            result = deepseek.process(image)
            results.append(result)
            print(f"\nProcessing time: {result['processing_time_ms']}ms")
            print(f"\nOutput preview (first 500 chars):\n{result['text'][:500]}...")
        except Exception as e:
            print(f"DeepSeek-OCR failed: {e}")
            import traceback
            traceback.print_exc()

    # Save results
    if results:
        print("\n" + "=" * 50)
        print("Saving results")
        print("=" * 50)
        save_results(results, args.output)

        # Summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        for r in results:
            print(f"{r['model']}: {r['processing_time_ms']}ms, {len(r['text'])} chars")


if __name__ == "__main__":
    main()
