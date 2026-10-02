import anthropic
import base64
import logging
import threading
from typing import Dict, Any, List, Tuple, Optional
from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from common.ocr_prompts import resolve_prompt, wrap_prompt_for_batch, parse_batch_response
from services import usage_tracker

# Room for thinking + answer (thinking counts toward max_tokens). Kept at 16K so
# non-streaming requests stay under the SDK's long-request limit.
_MAX_TOKENS = 16000


class AnthropicCancelledError(Exception):
    """Raised when an OCR call is cancelled via the cancel event."""
    pass


def _sniff_media_type(image_base64: str) -> str:
    # Anthropic rejects requests where declared media_type doesn't match the bytes.
    try:
        header = base64.b64decode(image_base64[:24], validate=False)
    except Exception:
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"GIF8"):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class AnthropicOcrClient(BaseOcrClient):
    def __init__(self, api_key: str, model: str = None):
        self.client = anthropic.Anthropic(api_key=api_key)
        # Use provided model or default to Claude Haiku 4.5 (fastest and most cost-effective)
        self.model_id = model if model else 'claude-haiku-4-5-20251001'
        self._cancel_event: Optional[threading.Event] = None
        logging.info(f"AnthropicOcrClient initialized with model: {self.model_id}")

    def set_cancel_event(self, event: threading.Event):
        """Set an event that, when set, will abort processing."""
        self._cancel_event = event

    def _create(self, **kwargs):
        """messages.create + usage tracking; returns (message, text)."""
        message = self.client.messages.create(model=self.model_id, **kwargs)
        try:
            usage_tracker.record(
                model=self.model_id,
                input_tokens=message.usage.input_tokens or 0,
                output_tokens=message.usage.output_tokens or 0,
            )
        except Exception:
            pass  # never let tracking break OCR
        if message.stop_reason == "max_tokens":
            logging.warning(f"Claude hit max_tokens ({self.model_id}); output is truncated")
        # Thinking models return a thinking block first: join only the text blocks
        text = "".join(b.text for b in message.content if b.type == "text")
        return message, text

    def _check_cancelled(self):
        if self._cancel_event and self._cancel_event.is_set():
            raise AnthropicCancelledError("OCR cancelled")

    def ocr_image(self, image_base64: str, image_width: int, image_height: int, prompt: str = None) -> Dict[str, Any]:
        ocr_prompt = resolve_prompt(prompt)
        self._check_cancelled()

        try:
            # Create message with image
            message, response_text = self._create(
                max_tokens=_MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": _sniff_media_type(image_base64),
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": ocr_prompt
                            }
                        ],
                    }
                ],
            )

            text_lines = [line.strip() for line in response_text.split('\n') if line.strip()]

            # Anthropic doesn't return bounding boxes, so create estimated full-width boxes
            dimensions = [
                Dimensions(x=0, y=i * (image_height // max(1, len(text_lines))),
                          width=image_width,
                          height=image_height // max(1, len(text_lines)))
                for i in range(len(text_lines))
            ]

            return {"lines": text_lines, "dimensions": dimensions}

        except AnthropicCancelledError:
            raise
        except Exception as e:
            logging.error(f"Anthropic OCR extraction failed: {e}")
            return {"lines": [], "dimensions": []}

    def ocr_images(self, images: List[Tuple[str, int, int]], prompt: Optional[str] = None) -> List[Dict[str, Any]]:
        ocr_prompt = resolve_prompt(prompt)
        wrapped = wrap_prompt_for_batch(ocr_prompt, len(images))

        content: list = []
        dims = []
        for img_b64, w, h in images:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": _sniff_media_type(img_b64), "data": img_b64},
            })
            dims.append((w, h))
        content.append({"type": "text", "text": wrapped})

        try:
            self._check_cancelled()
            message, text = self._create(
                max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": content}],
            )
            return parse_batch_response(text, len(images), dims)
        except AnthropicCancelledError:
            raise
        except Exception as e:
            logging.error(f"Anthropic multi-image OCR failed: {e}")
            return [{"lines": [], "dimensions": []} for _ in images]
