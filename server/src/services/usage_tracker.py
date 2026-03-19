"""Track daily API usage (inferences, tokens, data size) per model."""
import json
import logging
import os
import threading
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from common.env_vars import STORAGE_PATH

logger = logging.getLogger(__name__)

_USAGE_FILE = os.path.join(
    os.environ.get(STORAGE_PATH, ""), "data", "db", "api_usage.json"
)
_RESET_HOURS_FILE = os.path.join(
    os.environ.get(STORAGE_PATH, ""), "data", "db", "quota_reset_hours.json"
)
_lock = threading.Lock()

# Default quota reset hours per provider prefix.
# E.g. Gemini resets at 8:00 local time, so usage between 00:00-07:59
# should count toward the previous billing day.
_DEFAULT_RESET_HOURS: Dict[str, int] = {
    "gemini": 8,
}


def _load_reset_hours() -> Dict[str, int]:
    """Load provider reset hours from config file, falling back to defaults."""
    hours = dict(_DEFAULT_RESET_HOURS)
    if os.path.isfile(_RESET_HOURS_FILE):
        try:
            with open(_RESET_HOURS_FILE, "r", encoding="utf-8") as f:
                custom = json.load(f)
            hours.update(custom)
        except (json.JSONDecodeError, IOError):
            pass
    return hours


def set_reset_hour(provider_prefix: str, hour: int):
    """Persist a custom quota reset hour for a provider (0-23)."""
    hour = max(0, min(23, hour))
    existing = {}
    if os.path.isfile(_RESET_HOURS_FILE):
        try:
            with open(_RESET_HOURS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    existing[provider_prefix] = hour
    os.makedirs(os.path.dirname(_RESET_HOURS_FILE), exist_ok=True)
    with open(_RESET_HOURS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)


def _billing_day(model: str) -> str:
    """Return the billing day string for the given model, accounting for
    provider-specific quota reset hours."""
    reset_hours = _load_reset_hours()
    # Find matching reset hour by provider prefix
    reset_hour = 0
    model_lower = model.lower()
    for prefix, hour in reset_hours.items():
        if model_lower.startswith(prefix.lower()):
            reset_hour = hour
            break
    if reset_hour == 0:
        return date.today().isoformat()
    # If current time is before the reset hour, count toward previous day
    now = datetime.now()
    if now.hour < reset_hour:
        return (now - timedelta(days=1)).date().isoformat()
    return now.date().isoformat()


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
    """Record an API call. Thread-safe.
    Uses billing-day logic: if the provider has a non-midnight quota reset,
    usage before the reset hour counts toward the previous day."""
    day = _billing_day(model)
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
    """Get today's billing-day totals, optionally filtered by model prefix (e.g. 'gemini').
    Uses the provider's reset hour to determine the current billing day."""
    # Use billing day for the prefix if given, otherwise calendar today
    if model_prefix:
        billing = _billing_day(model_prefix)
    else:
        billing = _today()
    with _lock:
        data = _read()
    day_data = data.get(billing, {})
    total = {"inferences": 0, "input_tokens": 0, "output_tokens": 0, "data_bytes": 0}
    for model, stats in day_data.items():
        if model_prefix and not model.lower().startswith(model_prefix.lower()):
            continue
        for k in total:
            total[k] += stats.get(k, 0)
    return total
