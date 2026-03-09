from google import genai
from google.genai import types
import base64
import logging
import time
from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from typing import List, Dict, Any, Tuple, Optional
from common.ocr_prompts import resolve_prompt, wrap_prompt_for_batch, parse_batch_response

# Retry config for rate-limit (429) errors
_MAX_RETRIES = 4
_INITIAL_BACKOFF = 15  # seconds — Gemini RPM resets quickly, RPD is the real constraint


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a 429 / rate-limit error."""
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "resource exhausted" in msg or "rate" in msg


class GeminiOcrClient(BaseOcrClient):
    def __init__(self, api_key: str, model: str = None):
        # The new SDK uses a Client object
        self.client = genai.Client(api_key=api_key)
        # Use provided model or default to gemini-3.1-pro-preview
        self.model_id = model if model else 'gemini-3.1-pro-preview'
        logging.info(f"GeminiOcrClient initialized with model: {self.model_id}")

    def _call_with_retry(self, contents, label: str = ""):
        """Call generate_content with exponential backoff on rate-limit errors."""
        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return self.client.models.generate_content(
                    model=self.model_id,
                    contents=contents,
                )
            except Exception as e:
                if _is_rate_limit_error(e) and attempt < _MAX_RETRIES:
                    logging.warning(
                        f"Gemini rate-limited{' (' + label + ')' if label else ''}, "
                        f"attempt {attempt+1}/{_MAX_RETRIES+1}, waiting {backoff}s..."
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 120)  # cap at 2 minutes
                    continue
                raise

    def ocr_image(self, image_base64: str, image_width: int, image_height: int, prompt: str = None) -> dict:
        ocr_prompt = resolve_prompt(prompt)

        try:
            # Decode base64 to bytes
            image_bytes = base64.b64decode(image_base64)

            response = self._call_with_retry(
                contents=[
                    ocr_prompt,
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/png"
                    )
                ],
                label=f"{image_width}x{image_height}",
            )

            # Check for blocked/empty responses
            if not response.candidates:
                reason = getattr(response, 'prompt_feedback', None)
                logging.warning(f"Gemini returned no candidates. Feedback: {reason}")
                return {"lines": [], "dimensions": []}

            candidate = response.candidates[0]
            finish = getattr(candidate, 'finish_reason', None)
            truncated = False
            if finish and str(finish) not in ('STOP', 'FinishReason.STOP', '1'):
                logging.warning(f"Gemini finish_reason={finish} for image {image_width}x{image_height}")
                truncated = True

            text_lines = [line.strip() for line in response.text.split('\n') if line.strip()]

            line_height = image_height // max(1, len(text_lines))
            dimensions = [
                Dimensions(x=0, y=i * line_height, width=image_width, height=line_height)
                for i in range(len(text_lines))
            ]

            result = {"lines": text_lines, "dimensions": dimensions}
            if truncated:
                result["truncated"] = True
            return result

        except Exception as e:
            logging.error(f"Gemini OCR extraction failed: {type(e).__name__}: {e}")
            return {"lines": [], "dimensions": []}

    def ocr_images(self, images: List[Tuple[str, int, int]], prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        ocr_prompt = resolve_prompt(prompt)
        wrapped = wrap_prompt_for_batch(ocr_prompt, len(images))

        contents: list = [wrapped]
        dims = []
        for img_b64, w, h in images:
            contents.append(types.Part.from_bytes(data=base64.b64decode(img_b64), mime_type="image/png"))
            dims.append((w, h))

        try:
            response = self._call_with_retry(
                contents=contents,
                label=f"batch({len(images)} images)",
            )

            if not response.candidates:
                reason = getattr(response, 'prompt_feedback', None)
                logging.warning(f"Gemini batch: no candidates. Feedback: {reason}")
                return [{"lines": [], "dimensions": []} for _ in images]

            candidate = response.candidates[0]
            finish = getattr(candidate, 'finish_reason', None)
            if finish and str(finish) not in ('STOP', 'FinishReason.STOP', '1'):
                logging.warning(f"Gemini batch finish_reason={finish} for {len(images)} images")

            return parse_batch_response(response.text, len(images), dims)
        except Exception as e:
            logging.error(f"Gemini multi-image OCR failed: {type(e).__name__}: {e}")
            return [{"lines": [], "dimensions": []} for _ in images]
