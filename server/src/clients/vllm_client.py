import os
import logging
from typing import Dict, Any, Optional, List, Tuple

from openai import OpenAI
from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from common.ocr_prompts import resolve_prompt, wrap_prompt_for_batch, parse_batch_response


class VllmOcrClient(BaseOcrClient):
    """OCR client that connects to a vLLM server via OpenAI-compatible API.

    vLLM serves Qwen3-VL models with continuous batching and LoRA adapter support.
    Multiple concurrent requests are automatically batched at the GPU level.
    """

    def __init__(self, vllm_base_url: str = None, model_name: str = None, adapter_name: str = None):
        self.vllm_base_url = vllm_base_url or os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
        self.base_model_name = model_name or os.environ.get("VLLM_MODEL_NAME", "Qwen/Qwen3-VL-8B-Instruct")
        # vLLM serves LoRA adapters by name — use adapter as model if specified
        self.model_name = adapter_name or self.base_model_name
        self.client = OpenAI(base_url=self.vllm_base_url, api_key="not-needed", timeout=120.0)
        logging.info(f"VllmOcrClient initialized: url={self.vllm_base_url}, model={self.model_name}")

    def ocr_image(self, image_base64: str, image_width: int, image_height: int, prompt: str = None) -> Dict[str, Any]:
        ocr_prompt = resolve_prompt(prompt)

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": ocr_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            },
                        ],
                    }
                ],
                max_tokens=2048,
            )

            content = response.choices[0].message.content
            text_lines = [line.strip() for line in content.split('\n') if line.strip()]

            # Estimated evenly-spaced dimensions (same as OpenAIOcrClient)
            line_height = image_height // max(1, len(text_lines))
            dimensions = [
                Dimensions(x=0, y=i * line_height, width=image_width, height=line_height)
                for i in range(len(text_lines))
            ]

            return {"lines": text_lines, "dimensions": dimensions}

        except Exception as e:
            logging.error(f"vLLM OCR extraction failed: {e}")
            return {"lines": [], "dimensions": []}

    def ocr_images(self, images: List[Tuple[str, int, int]], prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        ocr_prompt = resolve_prompt(prompt)
        wrapped = wrap_prompt_for_batch(ocr_prompt, len(images))

        content: list = [{"type": "text", "text": wrapped}]
        dims = []
        for img_b64, w, h in images:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
            dims.append((w, h))

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
                max_tokens=2048 * len(images),
            )
            text = response.choices[0].message.content
            return parse_batch_response(text, len(images), dims)
        except Exception as e:
            logging.error(f"vLLM multi-image OCR failed: {e}")
            return [{"lines": [], "dimensions": []} for _ in images]
