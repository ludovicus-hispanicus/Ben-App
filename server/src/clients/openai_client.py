import re
from openai import OpenAI
from typing import Dict, Any, List, Tuple, Optional
import logging
from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from common.ocr_prompts import resolve_prompt, wrap_prompt_for_batch, parse_batch_response
from services import usage_tracker


def record_chat_usage(model: str, response) -> None:
    """Record token usage of a chat completion (OpenAI or xAI). completion_tokens
    already includes reasoning tokens. Never raises."""
    try:
        usage = response.usage
        usage_tracker.record(
            model=model,
            input_tokens=usage.prompt_tokens or 0,
            output_tokens=usage.completion_tokens or 0,
        )
    except Exception:
        pass


def openai_token_params(model: str, budget: int) -> Dict[str, Any]:
    """Output-length params for an OpenAI chat completion.

    ``max_completion_tokens`` works on every current model (gpt-5 / o-series reject
    the legacy ``max_tokens``). Reasoning models spend hidden reasoning tokens from
    the same budget, so give them headroom and keep reasoning effort low for OCR.
    Pass via ``extra_body`` so older ``openai`` SDKs don't reject unknown kwargs.
    """
    if re.match(r"^(o\d|gpt-5)", model) and "-chat" not in model:
        return {"max_completion_tokens": budget * 4, "reasoning_effort": "low"}
    return {"max_completion_tokens": budget}


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
                extra_body=openai_token_params(self.model_name, 2048),
            )

            record_chat_usage(self.model_name, response)
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
                extra_body=openai_token_params(self.model_name, 2048 * len(images)),
            )
            record_chat_usage(self.model_name, response)
            text = response.choices[0].message.content
            return parse_batch_response(text, len(images), dims)
        except Exception as e:
            logging.error(f"OpenAI multi-image OCR failed: {e}")
            return [{"lines": [], "dimensions": []} for _ in images]
