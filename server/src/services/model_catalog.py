"""
Live model catalog for the cloud OCR providers.

Instead of hardcoding model IDs in the frontend (which go stale every time a
provider ships a new model), we ask each provider's ``/models`` endpoint what
the user's API key can actually call, filter to vision-capable chat models, and
group them into *families* (``claude-opus``, ``gemini-flash``, ``gpt-mini``...).

Families power the ``latest:<family>`` sub-model alias: a job configured with
``latest:claude-sonnet`` is resolved at start time to the newest Sonnet the key
can see, so saved settings keep tracking new releases without code changes.

Results are cached in memory per (provider, api key) for ``_CACHE_TTL`` seconds.
"""

import hashlib
import logging
import re
import time
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

LATEST_PREFIX = "latest:"
_CACHE_TTL = 3600
_TIMEOUT = 15.0

# Frontend model value -> canonical provider key
PROVIDER_ALIASES = {
    "gemini_vision": "gemini", "gemini": "gemini",
    "claude_vision": "anthropic", "claude": "anthropic", "anthropic": "anthropic",
    "gpt4_vision": "openai", "openai": "openai", "gpt": "openai",
    "grok_xai": "grok", "grok": "grok", "xai": "grok",
}

_cache: Dict[Tuple[str, str], Tuple[float, List[dict]]] = {}

# Tokens that carry no family information (versions, dates, release channels)
_VERSION_TOKEN = re.compile(r"^(\d+(\.\d+)*o?|\d{6,8})$")
_CHANNEL_TOKENS = {"preview", "latest", "exp", "experimental"}


def canonical_provider(provider: str) -> Optional[str]:
    return PROVIDER_ALIASES.get((provider or "").lower().split(":")[0])


def model_family(model_id: str) -> str:
    """Strip version numbers / dates / channels: ``claude-3-5-sonnet-20241022`` -> ``claude-sonnet``."""
    tokens = []
    for tok in model_id.lower().split("-"):
        if _VERSION_TOKEN.match(tok) or tok in _CHANNEL_TOKENS:
            continue
        if re.match(r"^o\d+$", tok):  # OpenAI o-series: o3, o4 -> o
            tok = "o"
        tokens.append(tok)
    return "-".join(tokens)


def _family_label(family: str) -> str:
    words = []
    for w in family.split("-"):
        words.append({"gpt": "GPT", "o": "o-series"}.get(w, w.capitalize()))
    return " ".join(words)


def _version_key(model_id: str) -> Tuple:
    """Sort key for providers without timestamps (Gemini): numeric version, then stable > preview."""
    m = re.search(r"-(\d+(?:\.\d+)*)-", model_id + "-")
    version = tuple(int(p) for p in m.group(1).split(".")) if m else (0,)
    is_stable = "preview" not in model_id and "exp" not in model_id
    return (version, is_stable, -len(model_id))


# ── Provider fetchers ────────────────────────────────────────────────────────
# Each returns a list of {"value", "label", "created"} for vision-capable models,
# newest first.

async def _fetch_anthropic(client: httpx.AsyncClient, api_key: str) -> List[dict]:
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    models, after = [], None
    while True:
        params = {"limit": 1000}
        if after:
            params["after_id"] = after
        r = await client.get("https://api.anthropic.com/v1/models", headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
        for m in data.get("data", []):
            # Every current Claude model accepts image input; skip only pre-vision Claude 2.x
            if m["id"].startswith("claude-2"):
                continue
            models.append({
                "value": m["id"],
                "label": m.get("display_name") or m["id"],
                "created": m.get("created_at") or "",
            })
        if not data.get("has_more"):
            break
        after = data.get("last_id")
    models.sort(key=lambda m: m["created"], reverse=True)
    return models


_GEMINI_EXCLUDE = ("embedding", "tts", "image", "live", "audio", "aqa", "robotics", "computer-use", "veo", "imagen")


async def _fetch_gemini(client: httpx.AsyncClient, api_key: str) -> List[dict]:
    headers = {"x-goog-api-key": api_key}
    models, page_token = [], None
    while True:
        params = {"pageSize": 1000}
        if page_token:
            params["pageToken"] = page_token
        r = await client.get("https://generativelanguage.googleapis.com/v1beta/models", headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
        for m in data.get("models", []):
            model_id = m.get("name", "").removeprefix("models/")
            if not model_id.startswith("gemini-"):
                continue
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if any(x in model_id for x in _GEMINI_EXCLUDE):
                continue
            models.append({
                "value": model_id,
                "label": m.get("displayName") or model_id,
                "created": "",
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    models.sort(key=lambda m: _version_key(m["value"]), reverse=True)
    return models


# Chat-completions + image input capable families only
_OPENAI_INCLUDE = re.compile(r"^(gpt-(4o|4\.1|4\.5|[5-9])|o[1-9])")
_OPENAI_EXCLUDE = (
    "audio", "realtime", "transcribe", "tts", "search", "image", "codex",
    "deep-research", "-pro", "instruct", "embedding", "moderation", "o1-mini", "o3-mini",
)
_DATED_SNAPSHOT = re.compile(r"-\d{4}-\d{2}-\d{2}$")


async def _fetch_openai(client: httpx.AsyncClient, api_key: str) -> List[dict]:
    r = await client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    r.raise_for_status()
    models = []
    for m in r.json().get("data", []):
        model_id = m["id"]
        if not _OPENAI_INCLUDE.match(model_id) or any(x in model_id for x in _OPENAI_EXCLUDE):
            continue
        # Dated snapshots duplicate their alias (gpt-4o-2024-08-06 == gpt-4o); keep the list short
        if _DATED_SNAPSHOT.search(model_id):
            continue
        models.append({"value": model_id, "label": model_id, "created": m.get("created", 0)})
    models.sort(key=lambda m: m["created"], reverse=True)
    return models


async def _fetch_grok(client: httpx.AsyncClient, api_key: str) -> List[dict]:
    r = await client.get("https://api.x.ai/v1/language-models", headers={"Authorization": f"Bearer {api_key}"})
    r.raise_for_status()
    models = []
    for m in r.json().get("models", []):
        if "image" not in (m.get("input_modalities") or []):
            continue
        models.append({"value": m["id"], "label": m["id"], "created": m.get("created", 0)})
    models.sort(key=lambda m: m["created"], reverse=True)
    return models


_FETCHERS = {
    "anthropic": _fetch_anthropic,
    "gemini": _fetch_gemini,
    "openai": _fetch_openai,
    "grok": _fetch_grok,
}


# ── Public API ───────────────────────────────────────────────────────────────

async def list_models(provider: str, api_key: str, refresh: bool = False) -> List[dict]:
    """Vision-capable models for ``provider`` visible to ``api_key``, newest first.

    Each entry: ``{"value", "label", "family", "created"}``. Raises on HTTP / auth errors.
    """
    canonical = canonical_provider(provider)
    if canonical not in _FETCHERS:
        raise ValueError(f"Provider '{provider}' has no model catalog")
    if not api_key:
        raise ValueError("An API key is required to list models")

    cache_key = (canonical, hashlib.sha256(api_key.encode()).hexdigest()[:16])
    cached = _cache.get(cache_key)
    if cached and not refresh and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        models = await _FETCHERS[canonical](client, api_key)
    for m in models:
        m["family"] = model_family(m["value"])

    _cache[cache_key] = (time.time(), models)
    logger.info(f"Model catalog: fetched {len(models)} {canonical} models")
    return models


def latest_aliases(models: List[dict]) -> List[dict]:
    """One ``latest:<family>`` entry per family (in order of the family's newest model)."""
    seen = {}
    for m in models:
        # Provider-side "-latest" aliases have no comparable version; don't let them head a family
        if "latest" in m["value"]:
            continue
        seen.setdefault(m["family"], m)
    return [
        {
            "value": f"{LATEST_PREFIX}{family}",
            "label": f"Latest {_family_label(family)}",
            "family": family,
            "resolves_to": m["value"],
        }
        for family, m in seen.items()
    ]


async def resolve_sub_model(provider: str, sub_model: Optional[str], api_key: Optional[str]) -> Optional[str]:
    """Turn ``latest:<family>`` into a concrete model ID; pass anything else through unchanged."""
    if not sub_model or not sub_model.startswith(LATEST_PREFIX):
        return sub_model
    family = sub_model[len(LATEST_PREFIX):]
    models = await list_models(provider, api_key)
    for alias in latest_aliases(models):
        if alias["family"] == family:
            logger.info(f"Resolved {sub_model} -> {alias['resolves_to']}")
            return alias["resolves_to"]
    raise ValueError(f"No '{family}' model is available for this API key")
