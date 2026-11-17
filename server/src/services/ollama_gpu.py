"""
Sharing the GPU between Ollama and BEn's own GPU work (Kraken, trainings).

Ollama manages its own models (it unloads one when another needs the memory) but
knows nothing about Kraken or a training in BEn's processes. On a small GPU
(8 GB) DeepSeek-OCR alone fills most of it, so BEn keeps one user at a time:

- before a training starts, Ollama's models are unloaded (the training has priority);
- while a training runs, local Ollama OCR is refused (cloud models still work);
- before Kraken reads on the GPU, Ollama's models are unloaded, unless a Batch job
  holds the GPU (it may be using them).
"""

import logging
import re
from typing import List

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434"  # not "localhost": on Windows that tries IPv6 first


def is_ollama_cloud_model(name: str) -> bool:
    """Ollama cloud models (e.g. "qwen3-vl:235b-cloud") run on Ollama's servers."""
    return bool(re.search(r"[:-]cloud$", name or "", re.I))


def ollama_models_on_gpu() -> List[str]:
    """Names of Ollama models currently holding GPU memory ([] if Ollama is not running)."""
    try:
        response = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=1.0)
        return [m["name"] for m in response.json().get("models", []) if m.get("size_vram", 0) > 0]
    except Exception:
        return []


def unload_ollama_models(reason: str) -> List[str]:
    """Unload every Ollama model that holds GPU memory. Returns the unloaded names."""
    unloaded = []
    for name in ollama_models_on_gpu():
        try:
            # keep_alive 0 without a prompt unloads the model right away
            httpx.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30.0)
            unloaded.append(name)
        except Exception as e:
            logger.warning(f"Could not unload Ollama model {name}: {e}")
    if unloaded:
        logger.info(f"Unloaded Ollama models from the GPU ({reason}): {', '.join(unloaded)}")
    return unloaded


def training_on_gpu() -> str:
    """Name of the GPU lock owner if it is a training, else ""."""
    from services.gpu_lock import current_owner
    owner = current_owner() or ""
    return owner if "training" in owner else ""


TRAINING_BUSY_MESSAGE = ("The GPU is in use by a training. Use a cloud model, or wait until "
                         "the training has finished.")
