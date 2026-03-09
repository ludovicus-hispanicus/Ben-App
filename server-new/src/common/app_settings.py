"""
Application-wide settings persistence.
Simple JSON file for key-value settings.
"""
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

_SETTINGS_FILE = os.path.join(os.environ.get("STORAGE_PATH", "data"), "db", "app_settings.json")
_lock = threading.Lock()

_DEFAULTS = {
    "image_scale": 1.0,
}

_settings: dict = {}


def _load() -> dict:
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {**_DEFAULTS, **data}
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
    return dict(_DEFAULTS)


def _save(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
        tmp = _SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _SETTINGS_FILE)
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")


def init_settings() -> None:
    """Load settings into memory. Call once at startup."""
    global _settings
    with _lock:
        _settings = _load()
    logger.info(f"Settings loaded: {_settings}")


def get_setting(key: str):
    with _lock:
        if not _settings:
            _settings.update(_load())
        return _settings.get(key, _DEFAULTS.get(key))


def get_all_settings() -> dict:
    with _lock:
        if not _settings:
            _settings.update(_load())
        return dict(_settings)


def update_settings(updates: dict) -> dict:
    global _settings
    with _lock:
        if not _settings:
            _settings.update(_load())
        _settings.update(updates)
        _save(_settings)
    logger.info(f"Settings updated: {updates}")
    return dict(_settings)


def get_image_scale() -> float:
    """Convenience: get the global image scale factor."""
    val = get_setting("image_scale")
    try:
        return float(val)
    except (TypeError, ValueError):
        return 1.0
