"""
Nemotron Parse OCR Service

Loads NVIDIA Nemotron-Parse-v1.1 for OCR tasks.
This is a small model (~885M params, ~1.7GB VRAM in float16).
Optimized for document parsing with structured output (text + bounding boxes).
"""

import logging
import os
import re
import time
import base64
from io import BytesIO
from typing import Optional, Dict, Any, List

from PIL import Image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
_model = None
_processor = None
_device = None
_loaded = False

# Model ID
MODEL_ID = "nvidia/NVIDIA-Nemotron-Parse-v1.1"

# Task prompt for Nemotron Parse - tells it to predict bboxes, classes, and output markdown
TASK_PROMPT = "</s><s><predict_bbox><predict_classes><output_markdown>"

# Regex for parsing local model output: <x_0.29><y_0.33>text<x_0.48><y_0.35><class_List-item>
_LINE_PATTERN = re.compile(
    r"<x_([\d.]+)><y_([\d.]+)>"  # start x, y
    r"(.*?)"                      # text content
    r"<x_([\d.]+)><y_([\d.]+)>"  # end x, y
    r"<class_([^>]+)>"           # class label
)


def is_available() -> bool:
    """Check if Nemotron is available (dependencies installed)"""
    try:
        import torch
        from transformers import AutoModel, AutoProcessor
        return torch.cuda.is_available()
    except ImportError:
        return False


def is_loaded() -> bool:
    """Check if the model is currently loaded"""
    return _loaded


def load_model() -> bool:
    """
    Load Nemotron Parse model in float16.

    The model is small enough (~1.7GB) to run in float16 without quantization.

    Returns:
        True if loaded successfully, False otherwise
    """
    global _model, _processor, _device, _loaded

    if _loaded:
        logger.info("Nemotron Parse model already loaded")
        return True

    try:
        import torch
        from transformers import AutoModel, AutoProcessor

        _device = "cuda" if torch.cuda.is_available() else "cpu"

        if _device == "cpu":
            logger.warning("CUDA not available — Nemotron will run on CPU (very slow)")
        else:
            gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logger.info(f"GPU: {torch.cuda.get_device_name(0)}, VRAM: {gpu_mem:.1f} GB")

        logger.info(f"Loading {MODEL_ID} with float16...")

        # Load processor
        _processor = AutoProcessor.from_pretrained(
            MODEL_ID, trust_remote_code=True
        )

        # Clear GPU cache before loading
        if _device == "cuda":
            torch.cuda.empty_cache()

        # Nemotron-Parse is <1B params (~885M), ~1.7GB in float16
        # Load entirely on GPU for fastest inference
        if _device == "cuda":
            _model = AutoModel.from_pretrained(
                MODEL_ID,
                trust_remote_code=True,
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True,
            ).to("cuda")
            logger.info("Model loaded entirely on GPU (float16, ~1.7GB VRAM)")
        else:
            _model = AutoModel.from_pretrained(
                MODEL_ID,
                trust_remote_code=True,
                torch_dtype=torch.float32,
                low_cpu_mem_usage=True,
            )

        _model.eval()
        _loaded = True
        logger.info("Nemotron Parse model ready")
        return True

    except Exception as e:
        logger.error(f"Failed to load Nemotron Parse: {e}")
        import traceback
        traceback.print_exc()
        return False


def unload_model() -> None:
    """Unload the model to free GPU memory"""
    global _model, _processor, _device, _loaded

    if _model is not None:
        del _model
        _model = None
    if _processor is not None:
        del _processor
        _processor = None
    _loaded = False

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except:
        pass

    logger.info("Nemotron Parse model unloaded")


def ocr_from_base64(
    image_base64: str,
) -> Dict[str, Any]:
    """
    Perform OCR on a base64-encoded image.

    Args:
        image_base64: Base64 encoded image (with or without data:image prefix)

    Returns:
        Dict with keys: success, text, processing_time_ms, lines, boxes, error
        - boxes contains list of {x, y, width, height} for each line
    """
    global _model, _processor, _device, _loaded

    start_time = time.time()

    # Ensure model is loaded
    if not _loaded:
        if not load_model():
            return {
                "success": False,
                "text": "",
                "lines": [],
                "boxes": [],
                "processing_time_ms": 0,
                "error": "Failed to load Nemotron Parse model"
            }

    try:
        import torch

        # Clean base64 string
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]

        # Decode image
        image_bytes = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        original_width, original_height = image.size

        # Resize image to fit in GPU memory
        # Nemotron uses significant memory during generation, limit to ~512px for 8GB GPU
        max_dim = 512
        if max(image.width, image.height) > max_dim:
            ratio = max_dim / max(image.width, image.height)
            new_w = int(image.width * ratio)
            new_h = int(image.height * ratio)
            image = image.resize((new_w, new_h), Image.LANCZOS)
            logger.info(f"Resized image from {original_width}x{original_height} to {new_w}x{new_h}")

        image_width, image_height = image.size
        logger.info(f"Processing image {image_width}x{image_height}")

        # Clear GPU cache before inference
        if _device == "cuda":
            torch.cuda.empty_cache()

        # Process inputs
        inputs = _processor(
            images=[image],
            text=TASK_PROMPT,
            return_tensors="pt",
            add_special_tokens=False
        )
        inputs = {k: v.to(_device) if hasattr(v, 'to') else v for k, v in inputs.items()}

        # Generate
        logger.info("Running Nemotron Parse inference...")
        with torch.no_grad():
            output_ids = _model.generate(
                **inputs,
                max_new_tokens=4096,
                do_sample=False,
                use_cache=False,
            )

        # Decode
        raw_text = _processor.batch_decode(output_ids, skip_special_tokens=True)[0]

        # Clean up GPU memory
        del inputs, output_ids
        if _device == "cuda":
            torch.cuda.empty_cache()

        # Parse the structured output
        lines, boxes = _parse_response(raw_text, image_width, image_height)

        # Join lines for full text
        full_text = "\n".join(lines)

        processing_time_ms = int((time.time() - start_time) * 1000)

        logger.info(f"Nemotron Parse completed in {processing_time_ms}ms, {len(lines)} lines")

        return {
            "success": True,
            "text": full_text,
            "lines": lines,
            "boxes": boxes,
            "processing_time_ms": processing_time_ms,
            "raw_output": raw_text,  # Include raw for debugging
        }

    except RuntimeError as e:
        if "out of memory" in str(e).lower() or "CUDA" in str(e):
            logger.error(f"CUDA out of memory error: {e}")
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except:
                pass
            return {
                "success": False,
                "text": "",
                "lines": [],
                "boxes": [],
                "processing_time_ms": int((time.time() - start_time) * 1000),
                "error": f"GPU out of memory. Try a smaller image."
            }
        raise
    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Nemotron Parse OCR failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "text": "",
            "lines": [],
            "boxes": [],
            "processing_time_ms": processing_time_ms,
            "error": str(e)
        }


def _parse_response(raw_text: str, image_width: int, image_height: int) -> tuple:
    """Parse Nemotron's structured output into lines and bounding boxes."""
    lines: List[str] = []
    boxes: List[Dict] = []

    for match in _LINE_PATTERN.finditer(raw_text):
        x_start = float(match.group(1))
        y_start = float(match.group(2))
        text = match.group(3).strip()
        x_end = float(match.group(4))
        y_end = float(match.group(5))
        # class_label = match.group(6)  # available if needed

        if not text:
            continue

        lines.append(text)
        boxes.append({
            "x": int(x_start * image_width),
            "y": int(y_start * image_height),
            "width": int((x_end - x_start) * image_width),
            "height": int((y_end - y_start) * image_height),
        })

    return lines, boxes


def get_model_info() -> Dict[str, Any]:
    """Get information about the loaded model"""
    info = {
        "model_id": MODEL_ID,
        "loaded": _loaded,
        "device": _device,
        "params": "~885M",
        "vram": "~1.7GB (float16)",
    }

    if _loaded:
        try:
            import torch
            if torch.cuda.is_available():
                info["gpu_memory_allocated_mb"] = round(torch.cuda.memory_allocated() / 1024 / 1024, 2)
                info["gpu_memory_reserved_mb"] = round(torch.cuda.memory_reserved() / 1024 / 1024, 2)
        except:
            pass

    return info
