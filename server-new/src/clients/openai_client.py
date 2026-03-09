from openai import OpenAI
from typing import Dict, Any, List, Tuple, Optional
import logging
from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from common.ocr_prompts import resolve_prompt, wrap_prompt_for_batch, parse_batch_response


class OpenAIOcrClient(BaseOcrClient):
    def __init__(self, api_key: str, model: str = None):
        self.client = OpenAI(api_key=api_key)
        # Use provided model or default to gpt-4o
        self.model_name = model if model else "gpt-4o"
        logging.info(f"OpenAIOcrClient initialized with model: {self.model_name}")

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

            # Estimated evenly-spaced dimensions
            line_height = image_height // max(1, len(text_lines))
            dimensions = [
                Dimensions(x=0, y=i * line_height, width=image_width, height=line_height)
                for i in range(len(text_lines))
            ]
            
            return {"lines": text_lines, "dimensions": dimensions}

        except Exception as e:
            logging.error(f"OpenAI OCR extraction failed: {e}")
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
            logging.error(f"OpenAI multi-image OCR failed: {e}")
            return [{"lines": [], "dimensions": []} for _ in images]
