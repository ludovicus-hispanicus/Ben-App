"""
VLM OCR Client - Communicates with Ollama service for vision-based OCR
Optimized for 4GB VRAM GPUs using LLaVA
"""
import logging
import os
import time
from typing import Optional

import httpx

from common.env_vars import VLM_OCR_URL

# Default prompts for dictionary OCR
PROMPT_DICTIONARY_OCR = """You are an expert in reading Assyriological dictionaries (AHw, CAD).

Transcribe all text from this dictionary page image.

Rules:
1. Read left column completely first, then right column
2. Preserve reading order within each entry
3. Include all special characters exactly: š, ṣ, ṭ, ḫ, ā, ē, ī, ū
4. Headwords (lemmas) should be clearly identifiable
5. Preserve abbreviations as-is: RA, AfO, CT, ARM, etc.
6. Keep citation formats: ia-bi-le, ia-a-nu, etc.

Output plain text only, no markdown formatting."""

PROMPT_GENERIC_OCR = """Transcribe all text from this image.
Preserve the reading order and layout.
Include all special characters exactly as shown.
Output plain text only."""


class VlmOcrClient:
    """Client for communicating with Ollama VLM service"""

    DEFAULT_URL = "http://vlm-ocr:5003"
    TIMEOUT_SECONDS = 180  # OCR can take a while for large images

    def __init__(self):
        self.base_url = os.environ.get(VLM_OCR_URL, self.DEFAULT_URL)
        self.model = "llava:13b"  # LLaVA 13B - better accuracy, fits in 8GB VRAM
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> bool:
        """Check if the Ollama service is available"""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                # Check if our model is available
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return any(self.model in m for m in models)
            return False
        except Exception as e:
            logging.warning(f"VLM OCR health check failed: {e}")
            return False

    async def process_image(
        self,
        image_base64: str,
        source_type: str = "generic",
        custom_prompt: Optional[str] = None
    ) -> dict:
        """
        Process an image with Ollama LLaVA

        Args:
            image_base64: Base64 encoded image (without data:image prefix)
            source_type: Type of source document (ahw, cad, generic)
            custom_prompt: Optional custom prompt to override default

        Returns:
            dict with keys: success, text, processing_time_ms, error (if any)
        """
        start_time = time.time()

        # Select appropriate prompt
        if custom_prompt:
            prompt = custom_prompt
        elif source_type in ("ahw", "cad"):
            prompt = PROMPT_DICTIONARY_OCR
        else:
            prompt = PROMPT_GENERIC_OCR

        # Build Ollama API request
        # Ollama expects images as base64 strings in the "images" array
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [image_base64],  # Ollama expects raw base64, no data URI prefix
            "stream": False,
            "options": {
                "temperature": 0.1,  # Low temperature for more deterministic OCR
                "num_predict": 8000   # Max tokens
            }
        }

        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json=payload
            )

            processing_time_ms = int((time.time() - start_time) * 1000)

            if response.status_code != 200:
                error_text = response.text
                logging.error(f"VLM OCR request failed: {response.status_code} - {error_text}")
                return {
                    "success": False,
                    "text": "",
                    "processing_time_ms": processing_time_ms,
                    "error": f"VLM service error: {response.status_code}"
                }

            result = response.json()

            # Extract text from Ollama response
            text = result.get("response", "")

            logging.info(f"VLM OCR completed in {processing_time_ms}ms, output length: {len(text)}")

            return {
                "success": True,
                "text": text,
                "processing_time_ms": processing_time_ms,
                "model": self.model
            }

        except httpx.TimeoutException:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logging.error("VLM OCR request timed out")
            return {
                "success": False,
                "text": "",
                "processing_time_ms": processing_time_ms,
                "error": "Request timed out. The image may be too large."
            }
        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logging.error(f"VLM OCR request failed: {e}")
            return {
                "success": False,
                "text": "",
                "processing_time_ms": processing_time_ms,
                "error": str(e)
            }


# Global client instance
vlm_ocr_client = VlmOcrClient()
