"""
Which optional modules are installed.

A module counts as installed when its own code and the libraries it needs can
be found. Both are checked with importlib.util.find_spec, which locates a
module without importing it, so the check is cheap even for torch.

The code check matters for the base installer: it ships CPU torch, Kraken and
Ultralytics (which pulls in torchvision), so the libraries alone would make
CuRe look installed. The base build leaves the module code out instead.
"""
import importlib.util
import logging
from functools import lru_cache

# module id -> modules that must be present (its own code first, then libraries)
OPTIONAL_MODULES = {
    "cure": ["api.routers.cure", "torch", "torchvision", "sklearn"],
    "yolo": ["api.routers.yolo_training", "ultralytics", "torch"],
    "line_segmentation": ["api.routers.segmentation", "kraken"],
    "qwen": ["services.qwen_training_service", "torch", "transformers", "peft"],
}

CORE_MODULES = ("cured", "library")


def _present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@lru_cache(maxsize=1)
def get_installed_modules() -> dict:
    """Installed state of every module (core modules are always installed)."""
    result = {m: True for m in CORE_MODULES}
    for module_id, requirements in OPTIONAL_MODULES.items():
        missing = [r for r in requirements if not _present(r)]
        result[module_id] = not missing
        if missing:
            logging.info(f"Module '{module_id}' not installed (missing: {', '.join(missing)})")
    return result


def is_module_available(module_id: str) -> bool:
    """Installed and enabled in Settings."""
    from common.app_settings import get_enabled_modules
    return get_installed_modules().get(module_id, False) and get_enabled_modules().get(module_id, True)
