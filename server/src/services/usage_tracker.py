"""Track daily API usage (inferences, tokens, data size) per model."""
import json
import logging
import os
import threading
from datetime import date, datetime
from typing import Dict, List, Optional

from common.env_vars import STORAGE_PATH

logger = logging.getLogger(__name__)

_USAGE_FILE = os.path.join(
    os.environ.get(STORAGE_PATH, ""), "data", "db", "api_usage.json"
)
_lock = threading.Lock()


def _today() -> str:
    return date.today().isoformat()


def _read() -> Dict:
    """Read the usage file. Returns {date_str: {model: {inferences, input_tokens, output_tokens, data_bytes}}}"""
    if not os.path.isfile(_USAGE_FILE):
        return {}
    try:
        with open(_USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _write(data: Dict):
    os.makedirs(os.path.dirname(_USAGE_FILE), exist_ok=True)
    with open(_USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def record(
    model: str,
    inferences: int = 1,
    input_tokens: int = 0,
    output_tokens: int = 0,
    data_bytes: int = 0,
):
    """Record an API call. Thread-safe."""
    day = _today()
    with _lock:
        data = _read()
        if day not in data:
            data[day] = {}
        if model not in data[day]:
            data[day][model] = {
                "inferences": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "data_bytes": 0,
            }
        entry = data[day][model]
        entry["inferences"] += inferences
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["data_bytes"] += data_bytes
        _write(data)


def get_usage(days: int = 7) -> List[Dict]:
    """Return usage for the last N days, sorted newest first.
    Returns [{date, models: {model: {inferences, input_tokens, output_tokens, data_bytes}}}, ...]"""
    with _lock:
        data = _read()

    today = date.today()
    results = []
    for i in range(days):
        d = date.fromordinal(today.toordinal() - i)
        day_str = d.isoformat()
        models = data.get(day_str, {})
        if models:
            results.append({"date": day_str, "models": models})

    return results


def get_today_total(model_prefix: Optional[str] = None) -> Dict:
    """Get today's totals, optionally filtered by model prefix (e.g. 'gemini')."""
    with _lock:
        data = _read()
    day_data = data.get(_today(), {})
    total = {"inferences": 0, "input_tokens": 0, "output_tokens": 0, "data_bytes": 0}
    for model, stats in day_data.items():
        if model_prefix and not model.lower().startswith(model_prefix.lower()):
            continue
        for k in total:
            total[k] += stats.get(k, 0)
    return total
