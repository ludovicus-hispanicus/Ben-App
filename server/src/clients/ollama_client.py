"""
Ollama OCR Client

Wraps the OllamaOcrService to follow the BaseOcrClient interface.
Supports various vision models via Ollama (qwen2-vl, llava, minicpm-v, etc.)
"""

import logging
from typing import Dict, Any, List, Tuple, Optional

from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from services.ollama_ocr_service import OllamaOcrService
from common.ocr_prompts import get_default_prompt, PROMPTS, resolve_prompt, wrap_prompt_for_batch, parse_batch_response

logger = logging.getLogger(__name__)

# Model name mapping from UI values to Ollama model names
OLLAMA_MODELS = {
    # Local GPU models - powerful VLMs for OCR with markdown
    "deepseek_ocr": "deepseek-ocr",              # DeepSeek OCR - fast, 3B
    "llama4_vision": "llama4:scout",             # Llama 4 Scout - Meta's latest
    "qwen3_vl_32b": "qwen3-vl:32b",              # Qwen3-VL 32B - best OCR quality (21GB)
    "qwen3_vl_8b": "qwen3-vl:8b",                # Qwen3-VL 8B - balanced (6GB)
    "qwen3_vl_4b": "qwen3-vl:4b",                # Qwen3-VL 4B - fast, light (2.5GB)
    "mistral_small_vision": "mistral-small3.1",  # Mistral Small 24B with vision
    "llava_34b": "llava:34b",                    # LLaVA 34B - vision specialist
    # Ollama Cloud models - runs on Ollama's servers (free, no download)
    "qwen3_vl_235b_cloud": "qwen3-vl:235b-cloud",           # Qwen3-VL 235B Cloud - best quality
    "qwen3_vl_235b_thinking": "qwen3-vl:235b-thinking-cloud",  # Qwen3-VL 235B Thinking - STEM/math
}

# DeepSeek-OCR (and models trained from it, e.g. deepseek-ocr-ahw) answers BEn's long prompts
# with nothing; it only knows its own short commands.
DEEPSEEK_OCR_PROMPT = "Free OCR."


class OllamaOcrClient(BaseOcrClient):
    """OCR client using Ollama for vision model inference."""

    def __init__(self, model: str = "qwen2-vl"):
        """
        Initialize Ollama OCR client.

        Args:
            model: Ollama model name (qwen2-vl, llava, minicpm-v, etc.)
        """
        # Map UI model names to actual Ollama model names
        self.model = OLLAMA_MODELS.get(model, model)
        self._service = OllamaOcrService(model=self.model)
        logger.info(f"Initialized OllamaOcrClient with model: {self.model}")

    def _is_deepseek_ocr(self) -> bool:
        return self.model.lower().startswith("deepseek-ocr")

    def _gpu_busy_message(self) -> Optional[str]:
        """Refuse local models while a training holds the GPU (cloud models still run).

        Loading e.g. DeepSeek-OCR (~6.9 GB) next to a training on an 8 GB GPU makes
        one of them fail.
        """
        from services.ollama_gpu import training_on_gpu, is_ollama_cloud_model, TRAINING_BUSY_MESSAGE
        if training_on_gpu() and not is_ollama_cloud_model(self.model):
            logger.info(f"Ollama OCR with {self.model} refused: a training holds the GPU")
            return TRAINING_BUSY_MESSAGE
        return None

    def ocr_image(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
        prompt: str = None,
    ) -> Dict[str, Any]:
        """
        Process image with Ollama vision model.

        Args:
            image_base64: Base64 encoded image
            image_width: Width of the image (not used by Ollama)
            image_height: Height of the image (not used by Ollama)
            prompt: OCR prompt mode ("plain", "markdown", "dictionary")

        Returns:
            Dict with "lines" (List[str]) and optionally "dimensions"
        """
        busy = self._gpu_busy_message()
        if busy:
            return {"lines": [], "dimensions": [], "error": busy}

        # Use provided prompt or fall back to the configured default
        output_mode = prompt if prompt else get_default_prompt()
        logger.info(f"Running Ollama OCR with model: {self.model}, prompt: {output_mode}")

        # If prompt is raw text (not a known key), pass as custom_prompt
        custom_prompt = None
        if prompt and prompt not in PROMPTS and len(prompt) > 30:
            custom_prompt = prompt
            output_mode = "plain"  # fallback mode key
        if self._is_deepseek_ocr():
            custom_prompt, output_mode = DEEPSEEK_OCR_PROMPT, "plain"

        result = self._service.ocr_from_base64(
            image_base64=image_base64,
            output_mode=output_mode,
            custom_prompt=custom_prompt,
            model=self.model
        )

        if not result.get("success", False):
            error_msg = result.get("error", "Unknown Ollama error")
            logger.error(f"Ollama OCR failed: {error_msg}")
            return {
                "lines": [],
                "dimensions": [],
                "error": error_msg
            }

        lines = result.get("lines", [])
        logger.info(f"Ollama OCR completed: {len(lines)} lines")

        # Estimated evenly-spaced dimensions (Ollama doesn't provide bounding boxes)
        line_height = image_height // max(1, len(lines)) if lines else 0
        dimensions = [
            Dimensions(x=0, y=i * line_height, width=image_width, height=line_height)
            for i in range(len(lines))
        ]

        return {
            "lines": lines,
            "dimensions": dimensions,
        }

    def ocr_images(self, images: List[Tuple[str, int, int]], prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        busy = self._gpu_busy_message()
        if busy:
            return [{"lines": [], "dimensions": [], "error": busy} for _ in images]
        if self._is_deepseek_ocr():
            # DeepSeek-OCR reads one image per request with its own command ("Free OCR."),
            # not a multi-image prompt through the chat endpoint
            return super().ocr_images(images, prompt)
        output_mode = prompt if prompt else get_default_prompt()

        custom_prompt = None
        if prompt and prompt not in PROMPTS and len(prompt) > 30:
            custom_prompt = prompt
            output_mode = "plain"

        base_prompt = custom_prompt or PROMPTS.get(output_mode, PROMPTS["plain"])
        if self._is_deepseek_ocr():
            base_prompt = DEEPSEEK_OCR_PROMPT
        wrapped = wrap_prompt_for_batch(base_prompt, len(images))

        image_list = []
        dims = []
        for img_b64, w, h in images:
            if "," in img_b64:
                img_b64 = img_b64.split(",", 1)[1]
            image_list.append(img_b64)
            dims.append((w, h))

        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": wrapped, "images": image_list}],
            "stream": False,
        }
        from services.ollama_gpu import is_ollama_cloud_model
        if not is_ollama_cloud_model(self.model):
            # Ollama's default 4,096-token context holds the images AND the answer: too small
            body["options"] = {"num_ctx": 32768}
        try:
            response = self._service.client.post(f"{self._service.base_url}/api/chat", json=body)
            if response.status_code != 200:
                logger.error(f"Ollama multi-image OCR failed: {response.status_code}")
                return [{"lines": [], "dimensions": []} for _ in images]

            text = response.json().get("message", {}).get("content", "")
            return parse_batch_response(text, len(images), dims)
        except Exception as e:
            logger.error(f"Ollama multi-image OCR failed: {e}")
            return [{"lines": [], "dimensions": []} for _ in images]

    @staticmethod
    def is_available() -> bool:
        """Check if Ollama is installed and running."""
        service = OllamaOcrService()
        return service.is_available()

    @staticmethod
    def list_available_models():
        """List all vision models available in Ollama."""
        service = OllamaOcrService()
        if not service.is_available():
            return []

        models = service.list_models()
        # Filter for vision-capable models
        vision_models = []
        for m in models:
            name = m.get("name", "")
            # Common vision model patterns - VLMs with OCR capability
            if any(v in name.lower() for v in [
                "llava", "qwen", "minicpm", "bakllava", "moondream", "deepseek",
                "llama4", "mistral-small", "granite", "phi3"
            ]):
                vision_models.append(name)

        return vision_models
