"""
Qwen3-VL LoRA In-Process OCR Service

Loads Qwen3-VL base model with 4-bit quantization, then applies LoRA adapters
trained via QwenTrainingService for cuneiform OCR.
"""

import base64
import logging
import os
import time
from io import BytesIO
from typing import Optional, Dict, Any

from PIL import Image

logger = logging.getLogger(__name__)

# ── Global state ──
_model = None
_processor = None
_device = None
_loaded = False
_active_adapter_name: Optional[str] = None
_current_base_model_key: Optional[str] = None

from services.ocr_prompts import OUTPUT_MODES, PROMPT_PLAIN_TEXT


def is_available() -> bool:
    """Check if Qwen3-VL inference is possible."""
    try:
        import torch
        from transformers import Qwen3VLForConditionalGeneration, AutoProcessor
        return torch.cuda.is_available()
    except ImportError:
        return False


def is_loaded() -> bool:
    return _loaded


def load_model(base_model_key: str = "qwen3-vl-2b") -> bool:
    """Load a Qwen3-VL base model with 4-bit quantization."""
    global _model, _processor, _device, _loaded, _current_base_model_key

    from services.qwen_training_service import QwenTrainingService
    model_info = QwenTrainingService.BASE_MODELS.get(base_model_key)
    if not model_info:
        logger.error(f"Unknown base model key: {base_model_key}")
        return False
    hf_model_id = model_info["hf_id"]

    if _loaded and _current_base_model_key == base_model_key:
        logger.info(f"Qwen3-VL {base_model_key} already loaded")
        return True

    if _loaded:
        logger.info(f"Switching base model from {_current_base_model_key} to {base_model_key}")
        unload_model()

    try:
        import torch
        from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig

        _device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading Qwen3-VL from {hf_model_id}, device={_device}")

        torch.cuda.empty_cache()

        quantization_config = None
        if _device == "cuda":
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )

        _processor = AutoProcessor.from_pretrained(hf_model_id, trust_remote_code=True)

        model_kwargs = {
            "trust_remote_code": True,
            "torch_dtype": torch.bfloat16 if _device == "cuda" else torch.float32,
            "attn_implementation": "eager",
        }
        if quantization_config:
            model_kwargs["quantization_config"] = quantization_config
            model_kwargs["device_map"] = "auto"
        else:
            model_kwargs["device_map"] = _device

        _model = Qwen3VLForConditionalGeneration.from_pretrained(hf_model_id, **model_kwargs)
        _model.eval()

        if hasattr(_model, 'generation_config'):
            _model.generation_config.max_new_tokens = 4096
            _model.generation_config.do_sample = False

        _loaded = True
        _current_base_model_key = base_model_key
        logger.info(f"Qwen3-VL {base_model_key} loaded successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to load Qwen3-VL: {e}")
        import traceback
        traceback.print_exc()
        return False


def unload_model() -> None:
    """Unload the model to free GPU memory."""
    global _model, _processor, _device, _loaded, _active_adapter_name, _current_base_model_key

    if _model is not None:
        del _model
        _model = None
    if _processor is not None:
        del _processor
        _processor = None
    _loaded = False
    _active_adapter_name = None
    _current_base_model_key = None

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except:
        pass
    logger.info("Qwen3-VL model unloaded")


def load_adapter(adapter_path: str, adapter_name: str = None) -> bool:
    """Load a QLoRA adapter on top of the loaded base model."""
    global _model, _active_adapter_name

    if not _loaded or _model is None:
        logger.error("Cannot load adapter -- base model not loaded")
        return False

    try:
        from peft import PeftModel

        logger.info(f"Loading QLoRA adapter from {adapter_path}...")
        _model = PeftModel.from_pretrained(_model, adapter_path)
        _model.eval()
        _active_adapter_name = adapter_name or os.path.basename(adapter_path)
        logger.info(f"QLoRA adapter '{_active_adapter_name}' loaded")
        return True

    except ImportError:
        logger.error("peft library required. Install with: pip install peft")
        return False
    except Exception as e:
        logger.error(f"Failed to load QLoRA adapter: {e}")
        import traceback
        traceback.print_exc()
        return False


def unload_adapter() -> bool:
    """Unload current adapter by reloading the base model."""
    global _active_adapter_name

    if _active_adapter_name is None:
        return True

    prev = _active_adapter_name
    base_key = _current_base_model_key
    _active_adapter_name = None
    unload_model()
    load_model(base_model_key=base_key)
    logger.info(f"Adapter '{prev}' unloaded, base model restored")
    return True


def get_active_adapter() -> Optional[str]:
    return _active_adapter_name


def ocr_from_base64(
    image_base64: str,
    adapter_name: Optional[str] = None,
    prompt: Optional[str] = None,
    output_mode: str = "plain",
    max_new_tokens: int = 4096,
) -> Dict[str, Any]:
    """
    Perform OCR on a base64-encoded image using Qwen3-VL + optional LoRA adapter.
    """
    global _model, _processor

    start_time = time.time()

    try:
        # ── Resolve adapter and ensure correct model is loaded ──
        if adapter_name:
            from services.qwen_training_service import qwen_training_service
            adapters = qwen_training_service.get_adapters()
            adapter_info = next((a for a in adapters if a["name"] == adapter_name), None)

            if not adapter_info:
                return _error_result(f"Adapter '{adapter_name}' not found in registry", start_time, output_mode)

            required_base = adapter_info.get("base_model", "qwen3-vl-2b")
            adapter_path = adapter_info["path"]

            if not _loaded or _current_base_model_key != required_base:
                if not load_model(base_model_key=required_base):
                    return _error_result("Failed to load base model", start_time, output_mode)

            if _active_adapter_name != adapter_name:
                if _active_adapter_name is not None:
                    unload_adapter()
                    load_model(base_model_key=required_base)
                if not load_adapter(adapter_path, adapter_name):
                    return _error_result(f"Failed to load adapter '{adapter_name}'", start_time, output_mode)
        else:
            if not _loaded:
                if not load_model():
                    return _error_result("Failed to load Qwen3-VL base model", start_time, output_mode)

        # ── Prepare image ──
        import torch

        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]

        image_bytes = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_bytes)).convert("RGB")

        # ── Build prompt ──
        if prompt is None:
            prompt_text = OUTPUT_MODES.get(output_mode, PROMPT_PLAIN_TEXT)
        else:
            prompt_text = prompt

        # ── Build chat-template messages (Qwen3-VL format) ──
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt_text},
                ],
            }
        ]

        text_input = _processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = _processor(
            text=[text_input],
            images=[image],
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(_model.device) if hasattr(v, 'to') else v for k, v in inputs.items()}

        # ── Generate ──
        logger.info(f"Starting generation with max_new_tokens={max_new_tokens}...")
        with torch.no_grad():
            output_ids = _model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                use_cache=True,
            )

        input_len = inputs["input_ids"].shape[1]
        generated_ids = output_ids[:, input_len:]
        logger.info(f"Generated {generated_ids.shape[1]} tokens")

        generated_text = _processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0].strip()

        lines = [line.strip() for line in generated_text.split("\n") if line.strip()]

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Qwen3-VL OCR completed in {processing_time_ms}ms, {len(lines)} lines")

        del inputs, output_ids, generated_ids
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return {
            "success": True,
            "text": generated_text,
            "lines": lines,
            "processing_time_ms": processing_time_ms,
            "output_mode": output_mode,
        }

    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Qwen3-VL OCR failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "text": "",
            "lines": [],
            "processing_time_ms": processing_time_ms,
            "output_mode": output_mode,
            "error": str(e),
        }


def _error_result(msg: str, start_time: float, output_mode: str) -> Dict[str, Any]:
    return {
        "success": False,
        "text": "",
        "lines": [],
        "processing_time_ms": int((time.time() - start_time) * 1000),
        "output_mode": output_mode,
        "error": msg,
    }


def get_model_info() -> Dict[str, Any]:
    info = {
        "loaded": _loaded,
        "device": _device,
        "base_model": _current_base_model_key,
        "active_adapter": _active_adapter_name,
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
