"""
TEI Lex-0 Encoding Service (Stage 2 of the two-stage pipeline)

Takes plain/markdown OCR text and converts it to TEI Lex-0 XML
using a text LLM (no vision needed).

Supports:
- Ollama local models (qwen3:8b, llama3.1, etc.) — text-only chat
- Cloud APIs (Gemini, Claude, OpenAI) — via existing clients
"""

import logging
import time
import httpx
from typing import Optional, Dict, Any

from services.tei_prompt_builder import tei_prompt_builder

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_URL = "http://localhost:11434"


class TeiEncodingService:
    """Converts OCR text to TEI Lex-0 XML using a text LLM."""

    def __init__(self, ollama_url: str = DEFAULT_OLLAMA_URL):
        self.ollama_url = ollama_url
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=300.0)
        return self._client

    def encode_to_tei(
        self,
        ocr_text: str,
        model: str = "qwen3:8b",
        provider: str = "ollama",
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert OCR text to TEI Lex-0 XML.

        Args:
            ocr_text: Plain text or markdown from OCR stage
            model: Model name (Ollama model or cloud model)
            provider: "ollama", "gemini", "openai", or "anthropic"
            api_key: API key for cloud providers

        Returns:
            Dict with: success, text, lines, processing_time_ms, error
        """
        start_time = time.time()

        # Build the prompt: system prompt + OCR text to encode
        system_prompt = tei_prompt_builder.build_system_prompt()
        user_message = (
            f"Convert the following OCR transcription of an Akkadian dictionary page "
            f"into TEI Lex-0 XML. Return only raw <entry> elements.\n\n"
            f"--- OCR TEXT ---\n{ocr_text}\n--- END OCR TEXT ---"
        )

        logger.info(
            f"TEI encoding: provider={provider}, model={model}, "
            f"ocr_text_length={len(ocr_text)}, system_prompt_length={len(system_prompt)}"
        )

        try:
            if provider == "ollama":
                result = self._encode_ollama(system_prompt, user_message, model)
            elif provider == "gemini":
                result = self._encode_gemini(system_prompt, user_message, model, api_key)
            elif provider in ("openai", "gpt"):
                result = self._encode_openai(system_prompt, user_message, model, api_key)
            elif provider in ("anthropic", "claude"):
                result = self._encode_anthropic(system_prompt, user_message, model, api_key)
            else:
                # Default to Ollama
                result = self._encode_ollama(system_prompt, user_message, model)

            processing_time_ms = int((time.time() - start_time) * 1000)
            result["processing_time_ms"] = processing_time_ms

            if result.get("success"):
                text = result.get("text", "")
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                result["lines"] = lines
                logger.info(f"TEI encoding completed in {processing_time_ms}ms, {len(lines)} lines")
            else:
                logger.error(f"TEI encoding failed: {result.get('error')}")

            return result

        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"TEI encoding error: {e}")
            return {
                "success": False,
                "text": "",
                "lines": [],
                "processing_time_ms": processing_time_ms,
                "error": str(e),
            }

    def _encode_ollama(
        self, system_prompt: str, user_message: str, model: str
    ) -> Dict[str, Any]:
        """Use Ollama text-only chat for TEI encoding."""
        try:
            response = self.client.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "stream": False,
                },
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "text": "",
                    "error": f"Ollama error {response.status_code}: {response.text}",
                }

            data = response.json()
            text = data.get("message", {}).get("content", "")
            return {"success": True, "text": text}

        except httpx.TimeoutException:
            return {"success": False, "text": "", "error": "Ollama request timed out"}
        except httpx.ConnectError:
            return {
                "success": False,
                "text": "",
                "error": "Cannot connect to Ollama. Is it running?",
            }

    def _encode_gemini(
        self, system_prompt: str, user_message: str, model: str, api_key: str
    ) -> Dict[str, Any]:
        """Use Gemini API for TEI encoding."""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            model_id = model or "gemini-2.5-flash-lite"

            response = client.models.generate_content(
                model=model_id,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    max_output_tokens=8192,
                ),
            )

            text = response.text or ""
            return {"success": True, "text": text}

        except Exception as e:
            return {"success": False, "text": "", "error": f"Gemini error: {e}"}

    def _encode_openai(
        self, system_prompt: str, user_message: str, model: str, api_key: str
    ) -> Dict[str, Any]:
        """Use OpenAI API for TEI encoding."""
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            model_name = model or "gpt-4o-mini"

            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=8192,
            )

            text = response.choices[0].message.content or ""
            return {"success": True, "text": text}

        except Exception as e:
            return {"success": False, "text": "", "error": f"OpenAI error: {e}"}

    def _encode_anthropic(
        self, system_prompt: str, user_message: str, model: str, api_key: str
    ) -> Dict[str, Any]:
        """Use Anthropic API for TEI encoding."""
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            model_id = model or "claude-haiku-4-5-20251001"

            message = client.messages.create(
                model=model_id,
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            text = message.content[0].text if message.content else ""
            return {"success": True, "text": text}

        except Exception as e:
            return {"success": False, "text": "", "error": f"Anthropic error: {e}"}


# Global singleton
tei_encoding_service = TeiEncodingService()
