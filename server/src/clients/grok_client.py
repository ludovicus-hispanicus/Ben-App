"""xAI Grok OCR client.

Grok exposes an OpenAI-compatible chat-completions endpoint at
https://api.x.ai/v1, so we reuse the `openai` SDK with a custom base_url —
no extra dependency. The wire format for vision (`type: image_url` with a
data URL) matches OpenAI's GPT-4 Vision exactly.

Docs: https://docs.x.ai/developers/models
       https://docs.x.ai/developers/model-capabilities/images/understanding
"""

from openai import OpenAI
from typing import Dict, Any, List, Tuple, Optional
import logging

from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from common.ocr_prompts import resolve_prompt, wrap_prompt_for_batch, parse_batch_response


XAI_BASE_URL = "https://api.x.ai/v1"


class GrokOcrClient(BaseOcrClient):
    def __init__(self, api_key: str, model: str = None):
        self.client = OpenAI(api_key=api_key, base_url=XAI_BASE_URL)
        # Default to Grok 4.1 Fast (non-reasoning) — cheap and quick for OCR.
        self.model_name = model if model else "grok-4-1-fast-non-reasoning"
        logging.info(f"GrokOcrClient initialized with model: {self.model_name}")

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

            content = response.choices[0].message.content or ""
            text_lines = [line.strip() for line in content.split('\n') if line.strip()]

            line_height = image_height // max(1, len(text_lines))
            dimensions = [
                Dimensions(x=0, y=i * line_height, width=image_width, height=line_height)
                for i in range(len(text_lines))
            ]

            return {"lines": text_lines, "dimensions": dimensions}

        except Exception as e:
            logging.error(f"Grok OCR extraction failed: {e}")
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
            text = response.choices[0].message.content or ""
            return parse_batch_response(text, len(images), dims)
        except Exception as e:
            logging.error(f"Grok multi-image OCR failed: {e}")
            return [{"lines": [], "dimensions": []} for _ in images]
