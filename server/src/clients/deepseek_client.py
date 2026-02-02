"""
DeepSeek-OCR-2 Client - Communicates with the DeepSeek-OCR service for dictionary OCR.
Optimized for Assyriological dictionaries (AHw, CAD) with special characters.
"""
import logging
import os
import time
from typing import Optional, Dict, Any, List

import httpx

from common.env_vars import DEEPSEEK_OCR_URL


class DeepSeekOcrClient:
    """Client for communicating with DeepSeek-OCR-2 service"""

    DEFAULT_URL = "http://deepseek-ocr:5004"
    TIMEOUT_SECONDS = 300  # 5 minutes - model inference can be slow

    def __init__(self):
        self.base_url = os.environ.get(DEEPSEEK_OCR_URL, self.DEFAULT_URL)
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

    async def health_check(self) -> Dict[str, Any]:
        """Check if the DeepSeek-OCR service is available and get its status"""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            if response.status_code == 200:
                return response.json()
            return {
                "status": "unhealthy",
                "error": f"Status code: {response.status_code}"
            }
        except Exception as e:
            logging.warning(f"DeepSeek-OCR health check failed: {e}")
            return {
                "status": "unavailable",
                "error": str(e)
            }

    async def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model"""
        try:
            response = await self.client.get(f"{self.base_url}/model/info")
            if response.status_code == 200:
                return response.json()
            return {"error": f"Status code: {response.status_code}"}
        except Exception as e:
            logging.error(f"Failed to get model info: {e}")
            return {"error": str(e)}

    async def list_adapters(self) -> List[Dict[str, str]]:
        """List available LoRA adapters"""
        try:
            response = await self.client.get(f"{self.base_url}/adapters")
            if response.status_code == 200:
                return response.json().get("adapters", [])
            return []
        except Exception as e:
            logging.error(f"Failed to list adapters: {e}")
            return []

    async def process_image(
        self,
        image_base64: str,
        dictionary_type: str = "general",
        custom_prompt: Optional[str] = None,
        max_new_tokens: int = 2048,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """
        Process an image with DeepSeek-OCR-2

        Args:
            image_base64: Base64 encoded image (without data:image prefix)
            dictionary_type: Type of dictionary (ahw, cad, general)
            custom_prompt: Optional custom prompt to override default
            max_new_tokens: Maximum tokens to generate
            temperature: Generation temperature (lower = more deterministic)

        Returns:
            dict with keys: success, text, processing_time_ms, error (if any)
        """
        start_time = time.time()

        try:
            # Use dictionary-specific endpoint if applicable
            if custom_prompt:
                # Use base64 endpoint with custom prompt
                payload = {
                    "image_base64": image_base64,
                    "prompt": custom_prompt,
                    "max_new_tokens": max_new_tokens,
                    "temperature": temperature
                }
                response = await self.client.post(
                    f"{self.base_url}/ocr/base64",
                    json=payload
                )
            else:
                # Use dictionary-specific endpoint
                # Need to convert base64 to file upload
                import base64
                import io

                image_bytes = base64.b64decode(image_base64)
                files = {
                    "file": ("image.png", io.BytesIO(image_bytes), "image/png")
                }
                data = {
                    "max_new_tokens": str(max_new_tokens),
                    "temperature": str(temperature)
                }

                response = await self.client.post(
                    f"{self.base_url}/ocr/dictionary/{dictionary_type}",
                    files=files,
                    data=data
                )

            processing_time_ms = int((time.time() - start_time) * 1000)

            if response.status_code != 200:
                error_text = response.text
                logging.error(f"DeepSeek-OCR request failed: {response.status_code} - {error_text}")
                return {
                    "success": False,
                    "text": "",
                    "processing_time_ms": processing_time_ms,
                    "error": f"DeepSeek-OCR service error: {response.status_code}"
                }

            result = response.json()

            # Extract text from response
            text = result.get("text", "")
            server_time = result.get("processing_time_ms", processing_time_ms)

            logging.info(f"DeepSeek-OCR completed in {server_time}ms, output length: {len(text)}")

            return {
                "success": True,
                "text": text,
                "processing_time_ms": server_time,
                "dictionary_type": dictionary_type
            }

        except httpx.TimeoutException:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logging.error("DeepSeek-OCR request timed out")
            return {
                "success": False,
                "text": "",
                "processing_time_ms": processing_time_ms,
                "error": "Request timed out. The image may be too large or the model needs more time."
            }
        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logging.error(f"DeepSeek-OCR request failed: {e}")
            return {
                "success": False,
                "text": "",
                "processing_time_ms": processing_time_ms,
                "error": str(e)
            }

    async def process_image_upload(
        self,
        file_content: bytes,
        filename: str,
        content_type: str,
        dictionary_type: str = "general",
        max_new_tokens: int = 2048,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """
        Process an uploaded image file directly

        Args:
            file_content: Raw file bytes
            filename: Original filename
            content_type: MIME type of the file
            dictionary_type: Type of dictionary (ahw, cad, general)
            max_new_tokens: Maximum tokens to generate
            temperature: Generation temperature

        Returns:
            dict with keys: success, text, processing_time_ms, error (if any)
        """
        start_time = time.time()

        try:
            import io

            files = {
                "file": (filename, io.BytesIO(file_content), content_type)
            }
            data = {
                "max_new_tokens": str(max_new_tokens),
                "temperature": str(temperature)
            }

            response = await self.client.post(
                f"{self.base_url}/ocr/dictionary/{dictionary_type}",
                files=files,
                data=data
            )

            processing_time_ms = int((time.time() - start_time) * 1000)

            if response.status_code != 200:
                error_text = response.text
                logging.error(f"DeepSeek-OCR request failed: {response.status_code} - {error_text}")
                return {
                    "success": False,
                    "text": "",
                    "processing_time_ms": processing_time_ms,
                    "error": f"DeepSeek-OCR service error: {response.status_code}"
                }

            result = response.json()
            text = result.get("text", "")
            server_time = result.get("processing_time_ms", processing_time_ms)

            logging.info(f"DeepSeek-OCR completed in {server_time}ms, output length: {len(text)}")

            return {
                "success": True,
                "text": text,
                "processing_time_ms": server_time,
                "dictionary_type": dictionary_type
            }

        except httpx.TimeoutException:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logging.error("DeepSeek-OCR request timed out")
            return {
                "success": False,
                "text": "",
                "processing_time_ms": processing_time_ms,
                "error": "Request timed out."
            }
        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logging.error(f"DeepSeek-OCR request failed: {e}")
            return {
                "success": False,
                "text": "",
                "processing_time_ms": processing_time_ms,
                "error": str(e)
            }


# Global client instance
deepseek_ocr_client = DeepSeekOcrClient()
