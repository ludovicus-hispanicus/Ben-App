"""
Ollama OCR Service

Connects to a local Ollama server for OCR using DeepSeek-OCR or other vision models.
This is the recommended approach for desktop deployment as Ollama handles GPU/CUDA setup.
"""

import logging
import time
import base64
import httpx
from typing import Optional, Dict, Any, List
from common.ocr_prompts import (
    PROMPTS, BUILTIN_PROMPT_KEYS,
    get_default_prompt, set_default_prompt,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default Ollama configuration
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"  # not "localhost": on Windows that tries IPv6 first (slow per request)
DEFAULT_MODEL = "deepseek-ocr"


class OllamaOcrService:
    """Service for OCR via local Ollama server."""

    def __init__(self, base_url: str = DEFAULT_OLLAMA_URL, model: str = DEFAULT_MODEL):
        self.base_url = base_url
        self.model = model
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=300.0)  # 5 min timeout for OCR
        return self._client

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def is_available(self) -> bool:
        """Check if Ollama server is running and responsive."""
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama not available: {e}")
            return False

    def is_model_available(self, model: Optional[str] = None) -> bool:
        """Check if the specified model is downloaded in Ollama."""
        model = model or self.model
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            if response.status_code != 200:
                return False

            data = response.json()
            models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
            return model.split(":")[0] in models
        except Exception as e:
            logger.warning(f"Failed to check model availability: {e}")
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        """List all available models in Ollama."""
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                return response.json().get("models", [])
            return []
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    def show_model(self, name: str) -> Dict[str, Any]:
        """Model details from Ollama (/api/show): capabilities, family, parameters.

        Returns {"error": "..."} when Ollama can't describe the model (for example
        a cloud model that has been retired).
        """
        try:
            response = self.client.post(f"{self.base_url}/api/show", json={"model": name})
            data = response.json()
            if response.status_code != 200 and "error" not in data:
                data = {"error": f"HTTP {response.status_code}"}
            return data
        except Exception as e:
            return {"error": str(e)}

    def get_running_models(self) -> List[Dict[str, Any]]:
        """Get currently running/loaded models with GPU info."""
        try:
            response = self.client.get(f"{self.base_url}/api/ps")
            if response.status_code == 200:
                return response.json().get("models", [])
            return []
        except Exception as e:
            logger.warning(f"Failed to get running models: {e}")
            return []

    def log_gpu_status(self, model: str) -> None:
        """Log GPU usage status for a model."""
        try:
            running = self.get_running_models()
            for m in running:
                if model in m.get("name", ""):
                    size = m.get("size", 0)
                    size_vram = m.get("size_vram", 0)
                    if size > 0:
                        gpu_percent = int((size_vram / size) * 100)
                        size_gb = size / (1024 ** 3)
                        vram_gb = size_vram / (1024 ** 3)
                        logger.info(f"GPU Status: {model} - {gpu_percent}% GPU ({vram_gb:.1f}GB VRAM / {size_gb:.1f}GB total)")
                    return
            logger.info(f"GPU Status: {model} - not currently loaded")
        except Exception as e:
            logger.warning(f"Could not get GPU status: {e}")

    def pull_model(self, model: Optional[str] = None) -> bool:
        """Pull/download a model to Ollama."""
        model = model or self.model
        try:
            logger.info(f"Pulling model: {model}")
            response = self.client.post(
                f"{self.base_url}/api/pull",
                json={"name": model},
                timeout=None  # No timeout for large downloads
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to pull model: {e}")
            return False

    def ocr_from_base64(
        self,
        image_base64: str,
        output_mode: str = "plain",
        custom_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Perform OCR on a base64-encoded image using Ollama.

        Args:
            image_base64: Base64 encoded image (with or without data:image prefix)
            output_mode: "plain", "markdown", or "tei_lex0"
            custom_prompt: Override the default prompt
            model: Override the default model

        Returns:
            Dict with keys: success, text, processing_time_ms, lines, error
        """
        start_time = time.time()
        model = model or self.model

        # Check Ollama availability
        if not self.is_available():
            return {
                "success": False,
                "text": "",
                "lines": [],
                "processing_time_ms": 0,
                "error": "Ollama server not running. Please start Ollama."
            }

        # Check model availability
        if not self.is_model_available(model):
            return {
                "success": False,
                "text": "",
                "lines": [],
                "processing_time_ms": 0,
                "error": f"Model '{model}' not found. Run: ollama pull {model}"
            }

        try:
            # Clean base64 string (remove data:image prefix if present)
            if "," in image_base64:
                image_base64 = image_base64.split(",", 1)[1]

            # Select prompt
            prompt = custom_prompt or PROMPTS.get(output_mode, PROMPTS["plain"])

            logger.info(f"Running Ollama OCR with model={model}, mode={output_mode}, prompt_length={len(prompt)} chars")

            # Call Ollama chat API with image
            response = self.client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [{
                        "role": "user",
                        "content": prompt,
                        "images": [image_base64]
                    }],
                    "stream": False
                }
            )

            processing_time_ms = int((time.time() - start_time) * 1000)

            if response.status_code != 200:
                return {
                    "success": False,
                    "text": "",
                    "lines": [],
                    "processing_time_ms": processing_time_ms,
                    "error": f"Ollama error: {response.status_code} - {response.text}"
                }

            result = response.json()
            text = result.get("message", {}).get("content", "")

            # Split into lines
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            logger.info(f"Ollama OCR completed in {processing_time_ms}ms, {len(lines)} lines")

            # Log GPU status after OCR
            self.log_gpu_status(model)

            return {
                "success": True,
                "text": text,
                "lines": lines,
                "processing_time_ms": processing_time_ms,
                "model": model,
                "output_mode": output_mode,
            }

        except httpx.TimeoutException:
            processing_time_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "text": "",
                "lines": [],
                "processing_time_ms": processing_time_ms,
                "error": "OCR request timed out. The image may be too large."
            }
        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Ollama OCR failed: {e}")
            return {
                "success": False,
                "text": "",
                "lines": [],
                "processing_time_ms": processing_time_ms,
                "error": str(e)
            }

    def ocr_from_file(
        self,
        file_path: str,
        output_mode: str = "plain",
        custom_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Perform OCR on an image file.

        Args:
            file_path: Path to image file
            output_mode: "plain", "markdown", or "tei_lex0"
            custom_prompt: Override the default prompt
            model: Override the default model

        Returns:
            Dict with keys: success, text, processing_time_ms, lines, error
        """
        try:
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            return self.ocr_from_base64(image_base64, output_mode, custom_prompt, model)
        except Exception as e:
            logger.error(f"Failed to read image file: {e}")
            return {
                "success": False,
                "text": "",
                "lines": [],
                "processing_time_ms": 0,
                "error": f"Failed to read image file: {e}"
            }

    def get_status(self) -> Dict[str, Any]:
        """Get Ollama service status and available models."""
        available = self.is_available()
        status = {
            "ollama_running": available,
            "base_url": self.base_url,
            "default_model": self.model,
        }

        if available:
            status["model_available"] = self.is_model_available()
            status["models"] = [
                {"name": m.get("name"), "size": m.get("size")}
                for m in self.list_models()
            ]

        return status


# Global service instance
ollama_ocr_service = OllamaOcrService()


# Convenience functions for direct use
# ── Vision-model discovery ──────────────────────────────────────────

# name|digest -> description; failures are kept only briefly (a cloud model can come back)
_model_info_cache: Dict[str, Dict[str, Any]] = {}
_FAILED_INFO_TTL = 600


def _describe_model(service: "OllamaOcrService", tag: Dict[str, Any]) -> Dict[str, Any]:
    name = tag.get("name", "")
    details = tag.get("details") or {}
    cloud = bool(tag.get("remote_host"))
    entry = {
        "name": name,
        "cloud": cloud,
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "size_gb": None if cloud else round((tag.get("size") or 0) / 1e9, 1),
    }
    info = service.show_model(name)
    if "error" in info:
        entry["error"] = str(info["error"])
        return entry
    capabilities = info.get("capabilities")
    if capabilities is None:
        # Ollama before capabilities were reported: vision models carry a CLIP/mllama projector
        families = (info.get("details") or {}).get("families") or []
        capabilities = ["vision"] if any(f in ("clip", "mllama") for f in families) else []
    entry["vision"] = "vision" in capabilities
    entry["capabilities"] = capabilities
    return entry


def list_vision_models() -> Dict[str, Any]:
    """Installed Ollama models that accept images, as Ollama reports them (no fixed list).

    Returns {"ollama_available", "models": [...], "unavailable": [{"name", "cloud", "error"}],
    "text_only": [{"name", "cloud"}]} -- the last are installed models without image input.
    """
    import time
    service = OllamaOcrService()
    if not service.is_available():
        return {"ollama_available": False, "models": [], "unavailable": [], "text_only": []}

    models, unavailable, text_only = [], [], []
    now = time.time()
    for tag in service.list_models():
        key = f"{tag.get('name', '')}|{tag.get('digest', '')}"
        entry = _model_info_cache.get(key)
        if entry is None or ("error" in entry and now - entry["_checked"] > _FAILED_INFO_TTL):
            entry = _describe_model(service, tag)
            entry["_checked"] = now
            _model_info_cache[key] = entry
        public = {k: v for k, v in entry.items() if not k.startswith("_")}
        if "error" in entry:
            unavailable.append({k: public[k] for k in ("name", "cloud", "error")})
        elif entry.get("vision"):
            models.append(public)
        else:
            text_only.append({"name": public["name"], "cloud": public["cloud"]})
    service.close()
    models.sort(key=lambda m: (m["cloud"], m["name"]))
    return {"ollama_available": True, "models": models, "unavailable": unavailable, "text_only": text_only}


def is_available() -> bool:
    """Check if Ollama is available."""
    return ollama_ocr_service.is_available()


def ocr_from_base64(
    image_base64: str,
    output_mode: str = "plain",
    custom_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform OCR on a base64 image using Ollama."""
    return ollama_ocr_service.ocr_from_base64(image_base64, output_mode, custom_prompt)


def ocr_from_file(
    file_path: str,
    output_mode: str = "plain",
    custom_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform OCR on an image file using Ollama."""
    return ollama_ocr_service.ocr_from_file(file_path, output_mode, custom_prompt)


def get_status() -> Dict[str, Any]:
    """Get Ollama service status."""
    return ollama_ocr_service.get_status()
