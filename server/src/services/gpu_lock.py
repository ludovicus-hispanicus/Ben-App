"""
Simple GPU activity tracker.
Prevents GPU resource conflicts between training and inference.
"""

import threading
import logging

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_gpu_owner: str | None = None  # e.g. "qwen_training", "kraken_training", "batch_recognition"


def acquire(owner: str) -> tuple[bool, str | None]:
    """Try to claim GPU. Returns (success, current_owner)."""
    with _lock:
        global _gpu_owner
        if _gpu_owner is None:
            _gpu_owner = owner
            logger.info(f"GPU acquired by: {owner}")
            return True, None
        if _gpu_owner == owner:
            return True, None
        logger.warning(f"GPU busy: {_gpu_owner} (requested by {owner})")
        return False, _gpu_owner


def release(owner: str) -> None:
    """Release GPU claim."""
    with _lock:
        global _gpu_owner
        if _gpu_owner == owner:
            logger.info(f"GPU released by: {owner}")
            _gpu_owner = None


def current_owner() -> str | None:
    """Check who currently holds the GPU."""
    return _gpu_owner
