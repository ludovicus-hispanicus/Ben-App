from google import genai
from google.genai import types
import base64
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from .base_ocr_client import BaseOcrClient
from entities.dimensions import Dimensions
from typing import List, Dict, Any, Tuple, Optional
from common.ocr_prompts import resolve_prompt, wrap_prompt_for_batch, parse_batch_response
from services import usage_tracker

# Retry config for rate-limit (429) errors
_MAX_RETRIES = 4
_INITIAL_BACKOFF = 15  # seconds — Gemini RPM resets quickly, RPD is the real constraint


class GeminiCancelledError(Exception):
    """Raised when an OCR call is cancelled via the cancel event."""
    pass


class GeminiRateLimitError(Exception):
    """Raised when rate-limit retries are exhausted."""
    pass


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a 429 / rate-limit error."""
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "resource exhausted" in msg or "rate" in msg


class GeminiOcrClient(BaseOcrClient):
    _REQUEST_TIMEOUT = 300  # seconds — abort if Gemini hasn't responded in 5 minutes

    def __init__(self, api_key: str, model: str = None):
        # The new SDK uses a Client object
        self.client = genai.Client(api_key=api_key)
        # Use provided model or default to gemini-3.1-pro-preview
        self.model_id = model if model else 'gemini-3.1-pro-preview'
        self._cancel_event: Optional[threading.Event] = None
        logging.info(f"GeminiOcrClient initialized with model: {self.model_id}")

    def set_cancel_event(self, event: threading.Event):
        """Set an event that, when set, will abort retry waits."""
        self._cancel_event = event

    def _call_with_retry(self, contents, label: str = "", data_bytes: int = 0):
        """Call generate_content with exponential backoff on rate-limit errors."""
        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_RETRIES + 1):
            # Check cancellation before each attempt
            if self._cancel_event and self._cancel_event.is_set():
                raise GeminiCancelledError("OCR cancelled")
            try:
                # Use a thread pool to enforce a timeout on the API call
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        self.client.models.generate_content,
                        model=self.model_id,
                        contents=contents,
                    )
                    try:
                        response = future.result(timeout=self._REQUEST_TIMEOUT)
                    except FuturesTimeoutError:
                        raise TimeoutError(
                            f"Gemini API call timed out after {self._REQUEST_TIMEOUT}s"
                            f"{' (' + label + ')' if label else ''}"
                        )
                # Track usage
                try:
                    meta = getattr(response, 'usage_metadata', None)
                    input_tokens = getattr(meta, 'prompt_token_count', 0) or 0 if meta else 0
                    output_tokens = getattr(meta, 'candidates_token_count', 0) or 0 if meta else 0
                    usage_tracker.record(
                        model=self.model_id,
                        inferences=1,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        data_bytes=data_bytes,
                    )
                except Exception:
                    pass  # never let tracking break OCR
                return response
            except Exception as e:
                if _is_rate_limit_error(e):
                    if attempt < _MAX_RETRIES:
                        logging.warning(
                            f"Gemini rate-limited{' (' + label + ')' if label else ''}, "
                            f"attempt {attempt+1}/{_MAX_RETRIES+1}, waiting {backoff}s..."
                        )
                        # Sleep in small increments so we can respond to cancellation
                        for _ in range(int(backoff)):
                            if self._cancel_event and self._cancel_event.is_set():
                                raise GeminiCancelledError("OCR cancelled during rate-limit wait")
                            time.sleep(1)
                        backoff = min(backoff * 2, 120)  # cap at 2 minutes
                        continue
                    # Retries exhausted — raise specific error so batch handler can stop
                    raise GeminiRateLimitError(f"Rate limit exceeded after {_MAX_RETRIES} retries: {e}") from e
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
                data_bytes=len(image_bytes),
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

        except (GeminiCancelledError, GeminiRateLimitError):
            raise  # let cancellation and rate-limit propagate
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

        # Estimate total data size from base64 length (avoids re-decoding)
        total_data_bytes = sum(len(img_b64) * 3 // 4 for img_b64, _, _ in images)

        try:
            response = self._call_with_retry(
                contents=contents,
                label=f"batch({len(images)} images)",
                data_bytes=total_data_bytes,
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
        except (GeminiCancelledError, GeminiRateLimitError):
            raise  # let cancellation and rate-limit propagate
        except Exception as e:
            # If batch has multiple images, retry as individual calls
            if len(images) > 1:
                logging.warning(
                    f"Gemini multi-image OCR failed ({type(e).__name__}: {e}), "
                    f"retrying {len(images)} images individually"
                )
                individual_results = []
                for img_b64, w, h in images:
                    try:
                        individual_results.append(self.ocr_image(img_b64, w, h, prompt))
                    except (GeminiCancelledError, GeminiRateLimitError):
                        raise
                    except Exception as ind_err:
                        logging.error(f"Gemini individual retry failed: {type(ind_err).__name__}: {ind_err}")
                        individual_results.append({"lines": [], "dimensions": []})
                return individual_results
            logging.error(f"Gemini multi-image OCR failed: {type(e).__name__}: {e}")
            return [{"lines": [], "dimensions": []}]
