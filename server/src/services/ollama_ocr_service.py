"""
Ollama OCR Service

Connects to a local Ollama server for OCR using DeepSeek-OCR or other vision models.
This is the recommended approach for desktop deployment as Ollama handles GPU/CUDA setup.
"""

import json
import logging
import os
import threading
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


# ── GPU layers per model ───────────────────────────────────────────────
# On a small GPU a vision model can fit while loading but leave too little memory
# for reading the image: Ollama then fails with e.g. "CUDA error: device not ready"
# (DeepSeek-OCR on an 8 GB laptop GPU: 13 of 13 layers fit, the image did not).
# Keeping a layer or two in main memory fixes it at a small cost in speed. BEn
# steps the number of GPU layers down after such an error and remembers the
# number that worked, per model, in data/ollama_gpu_layers.json.

_gpu_layers_lock = threading.Lock()
_gpu_layers: Optional[Dict[str, int]] = None


def _gpu_layers_file() -> str:
    from utils.storage_utils import StorageUtils
    return os.path.join(StorageUtils.BASE_PATH or "data", "ollama_gpu_layers.json")


def get_gpu_layers(model: str) -> Optional[int]:
    """Number of GPU layers that worked for this model, or None (Ollama decides)."""
    global _gpu_layers
    with _gpu_layers_lock:
        if _gpu_layers is None:
            try:
                with open(_gpu_layers_file(), encoding="utf-8") as f:
                    _gpu_layers = {k: int(v) for k, v in json.load(f).items()}
            except Exception:
                _gpu_layers = {}
        return _gpu_layers.get(model)


def set_gpu_layers(model: str, layers: Optional[int]) -> None:
    global _gpu_layers
    get_gpu_layers(model)  # load the file first
    with _gpu_layers_lock:
        if layers is None:
            _gpu_layers.pop(model, None)
        else:
            _gpu_layers[model] = int(layers)
        try:
            path = _gpu_layers_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_gpu_layers, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save GPU layers for {model}: {e}")


def is_gpu_memory_error(response: httpx.Response) -> bool:
    return response.status_code == 500 and "CUDA error" in response.text


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

    def _layer_count(self, model: str) -> Optional[int]:
        """Number of layers Ollama can put on the GPU (transformer blocks + output)."""
        try:
            response = self.client.post(f"{self.base_url}/api/show", json={"model": model}, timeout=10)
            info = response.json().get("model_info", {}) or {}
            arch = info.get("general.architecture")
            blocks = info.get(f"{arch}.block_count")  # not the vision encoder's ("<arch>.vision.block_count")
            return int(blocks) + 1 if isinstance(blocks, int) else None
        except Exception:
            return None

    def _fewer_gpu_layers(self, model: str, current: Optional[int]) -> List[int]:
        """GPU layer counts to try after a GPU memory error, largest first."""
        total = self._layer_count(model) or 32
        start = min(current, total) if current is not None else total
        steps = [start - 1, start - 2, total * 2 // 3, total // 3, 0]
        tries: List[int] = []
        for n in steps:
            if 0 <= n < start and n not in tries:
                tries.append(n)
        return sorted(tries, reverse=True)

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

            # DeepSeek-OCR (and models trained from it) has only a raw template ({{ .Prompt }}):
            # through /api/chat it starts with a stray "<|im_end|>" and reads about half the
            # page (AHw G p. 10: 2,938 instead of 5,566 characters). /api/generate is its format.
            is_deepseek_ocr = model.lower().startswith("deepseek-ocr")

            # Ollama's default context is 4,096 tokens for the image AND the answer: a
            # Qwen3-VL reading of a long AHw entry (image 2,826 tokens) stopped after 1,270
            # tokens, half the entry (lamassu: 55.7 % CER; with 16,384: 3.1 %).
            from services.ollama_gpu import is_ollama_cloud_model
            num_ctx = None if (is_deepseek_ocr or is_ollama_cloud_model(model)) else 16384

            def send(gpu_layers: Optional[int]):
                options = {}
                if gpu_layers is not None:
                    options["num_gpu"] = gpu_layers
                if num_ctx:
                    options["num_ctx"] = num_ctx
                options = options or None
                if is_deepseek_ocr:
                    body = {"model": model, "prompt": prompt, "images": [image_base64], "stream": False}
                    if options:
                        body["options"] = options
                    return self.client.post(f"{self.base_url}/api/generate", json=body)
                # Call Ollama chat API with image
                body = {
                    "model": model,
                    "messages": [{
                        "role": "user",
                        "content": prompt,
                        "images": [image_base64]
                    }],
                    "stream": False
                }
                if options:
                    body["options"] = options
                return self.client.post(f"{self.base_url}/api/chat", json=body)

            gpu_layers = get_gpu_layers(model)
            response = send(gpu_layers)
            if is_gpu_memory_error(response):
                # Too little GPU memory left for the image (see get_gpu_layers):
                # retry with fewer layers on the GPU and keep what works.
                for fewer in self._fewer_gpu_layers(model, gpu_layers):
                    logger.warning(f"Ollama GPU error with {model} ({response.text[:120]}); "
                                   f"trying again with {fewer} layers on the GPU")
                    response = send(fewer)
                    if not is_gpu_memory_error(response):
                        if response.status_code == 200:
                            set_gpu_layers(model, fewer)
                            logger.info(f"{model}: {fewer} GPU layers work; using that from now on")
                        break

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
            if is_deepseek_ocr:
                text = result.get("response", "").replace("<|im_end|>", "")
            else:
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
