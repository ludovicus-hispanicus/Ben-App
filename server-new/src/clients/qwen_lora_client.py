"""
Qwen3-VL LoRA OCR Client

Wraps qwen_ocr_service to follow the BaseOcrClient interface.
Supports fine-tuned Qwen3-VL LoRA adapters for cuneiform OCR.
"""

import logging
from typing import Dict, Any, Optional

from clients.base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions

logger = logging.getLogger(__name__)


class QwenLoraOcrClient(BaseOcrClient):
    """OCR client using Qwen3-VL + LoRA adapter for local GPU inference."""

    def __init__(self, adapter_name: Optional[str] = None):
        self.adapter_name = adapter_name
        logger.info(f"Initialized QwenLoraOcrClient with adapter: {adapter_name or 'base'}")

    def ocr_image(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        import services.qwen_ocr_service as qwen_ocr

        output_mode = prompt if prompt in ("plain", "markdown", "tei_lex0", "tei_epidoc", "dictionary") else "plain"

        logger.info(f"Running Qwen LoRA OCR, adapter={self.adapter_name}, mode={output_mode}")

        result = qwen_ocr.ocr_from_base64(
            image_base64=image_base64,
            adapter_name=self.adapter_name,
            output_mode=output_mode,
            max_new_tokens=512,
        )

        if not result.get("success", False):
            error_msg = result.get("error", "Unknown Qwen OCR error")
            logger.error(f"Qwen LoRA OCR failed: {error_msg}")
            return {"lines": [], "dimensions": [], "error": error_msg}

        lines = result.get("lines", [])

        # Estimated evenly-spaced dimensions (VLM doesn't produce bounding boxes)
        line_height = image_height // max(1, len(lines)) if lines else 0
        dimensions = [
            Dimensions(x=0, y=i * line_height, width=image_width, height=line_height)
            for i in range(len(lines))
        ]

        return {
            "lines": lines,
            "dimensions": dimensions,
            "text": result.get("text", ""),
        }
