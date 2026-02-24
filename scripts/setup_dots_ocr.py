"""
Setup script for dots.ocr on Windows.
Handles the model name issue (periods cause import errors).

Run: python setup_dots_ocr.py
"""

import os
import sys
import shutil
from pathlib import Path

def main():
    print("=" * 60)
    print("dots.ocr Setup for Windows")
    print("=" * 60)

    # Check Python version
    print(f"\nPython: {sys.version}")

    # Check PyTorch and CUDA
    try:
        import torch
        print(f"PyTorch: {torch.__version__}")
        print(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"GPU: {torch.cuda.get_device_name(0)}")
            print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    except ImportError:
        print("ERROR: PyTorch not installed!")
        print("Run: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        return False

    # Create local model directory (without periods!)
    model_dir = Path("./models/DotsOCR")
    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nModel directory: {model_dir.absolute()}")

    # Download model using huggingface_hub
    print("\n" + "=" * 60)
    print("Downloading dots.ocr model...")
    print("This will take a few minutes (~4GB)")
    print("=" * 60)

    try:
        from huggingface_hub import snapshot_download

        # Download to local directory with clean name
        local_path = snapshot_download(
            repo_id="rednote-hilab/dots.ocr",
            local_dir=str(model_dir),
            local_dir_use_symlinks=False,  # Important for Windows
            ignore_patterns=["*.md", "*.txt", ".git*"]
        )

        print(f"\nModel downloaded to: {local_path}")

    except Exception as e:
        print(f"ERROR downloading model: {e}")
        print("\nTrying alternative method...")

        # Alternative: use git clone
        import subprocess
        try:
            subprocess.run([
                "git", "clone",
                "https://huggingface.co/rednote-hilab/dots.ocr",
                str(model_dir)
            ], check=True)
            print(f"Model cloned to: {model_dir}")
        except Exception as e2:
            print(f"Git clone also failed: {e2}")
            return False

    # Verify model files exist
    print("\n" + "=" * 60)
    print("Verifying model files...")
    print("=" * 60)

    required_files = ["config.json", "tokenizer.json"]
    missing = []
    for f in required_files:
        if not (model_dir / f).exists():
            missing.append(f)

    if missing:
        print(f"WARNING: Missing files: {missing}")
    else:
        print("All required files present!")

    # Create test script
    test_script = '''"""
Test dots.ocr inference with local model.
"""
import os
import sys
import time
import torch

# Use local model path (no periods!)
MODEL_PATH = "./models/DotsOCR"

def test_inference(image_path: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from PIL import Image

    print(f"Loading model from: {MODEL_PATH}")
    start = time.time()

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True,
        local_files_only=True
    )

    # Load model
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        local_files_only=True
    )

    print(f"Model loaded in {time.time() - start:.1f}s")
    print(f"GPU memory: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

    # Load image
    image = Image.open(image_path).convert("RGB")
    print(f"Image size: {image.size}")

    # Save temp image for processing
    temp_path = "temp_test_image.png"
    image.save(temp_path)

    # Create prompt
    from qwen_vl_utils import process_vision_info

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": f"file://{os.path.abspath(temp_path)}"},
                {"type": "text", "text": "Parse all text from this document image. Output the transcribed text."}
            ]
        }
    ]

    # Apply chat template
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    # Process vision
    image_inputs, video_inputs = process_vision_info(messages)

    # Load processor
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True,
        local_files_only=True
    )

    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt"
    ).to(model.device)

    # Generate
    print("Generating...")
    gen_start = time.time()

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=4096,
            do_sample=False
        )

    # Decode
    result = tokenizer.decode(outputs[0], skip_special_tokens=False)

    # Extract response
    if "<|im_start|>assistant" in result:
        result = result.split("<|im_start|>assistant")[-1]
    if "<|im_end|>" in result:
        result = result.split("<|im_end|>")[0]

    print(f"Generation time: {time.time() - gen_start:.1f}s")

    # Cleanup
    if os.path.exists(temp_path):
        os.remove(temp_path)

    return result.strip()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_dots_ocr_local.py <image_path>")
        print("Example: python test_dots_ocr_local.py page1.png")
        sys.exit(1)

    result = test_inference(sys.argv[1])
    print("\\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(result)
'''

    test_script_path = Path("test_dots_ocr_local.py")
    test_script_path.write_text(test_script)
    print(f"\nCreated test script: {test_script_path}")

    print("\n" + "=" * 60)
    print("SETUP COMPLETE!")
    print("=" * 60)
    print(f"""
Next steps:

1. Convert a PDF page to PNG:
   python -c "from pdf2image import convert_from_path; convert_from_path('Q_II 886-931.pdf', first_page=1, last_page=1)[0].save('page1.png')"

2. Test dots.ocr:
   python test_dots_ocr_local.py page1.png

Model location: {model_dir.absolute()}
""")

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
