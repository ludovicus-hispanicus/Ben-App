"""
What Ollama offers beyond the installed models: its cloud models and the
downloadable vision models of its library on ollama.com.

Fetched only when asked (the Ollama model dropdown), kept for 12 hours, and
modest: the pages of the vision search (~85 KB each, about 4), the cloud list
(~10 KB) and one registry manifest (~1 KB) per model size, which gives the exact
download size.
"""
import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

SEARCH_URL = "https://ollama.com/search?c=vision"
CLOUD_URL = "https://ollama.com/api/tags"
MANIFEST_URL = "https://registry.ollama.ai/v2/library/{name}/manifests/{tag}"

_TTL = 12 * 3600
_FAILED_TTL = 300
_cache: Dict[str, Any] = {"at": 0.0, "data": None}

# Size labels on the search page: "4b", "0.8b", "270m", "e4b" (Gemma), "16x17b".
# Lowercase only: download counts look alike but are uppercase ("8.8M").
_SIZE_RE = re.compile(r"^(e?\d+(\.\d+)?[bm]|\d+x\d+(\.\d+)?b)$")
_CAPABILITIES = {"vision", "tools", "thinking", "embedding", "audio", "cloud"}
_MAX_PAGES = 8


def _cloud_models(client: httpx.Client) -> List[Dict[str, Any]]:
    """Ollama's cloud models that accept images, under the name the local Ollama uses."""
    data = client.get(CLOUD_URL).json()
    models = []
    for m in data.get("models", []):
        if "vision" not in (m.get("capabilities") or []):
            continue
        name = m.get("name", "")
        # "gemma4:31b" -> "gemma4:31b-cloud"; "kimi-k3" -> "kimi-k3:cloud"
        local_name = f"{name}-cloud" if ":" in name else f"{name}:cloud"
        models.append({"name": local_name, "updated": (m.get("modified_at") or "")[:10]})
    return models


def _library_models(client: httpx.Client) -> List[Dict[str, Any]]:
    """Downloadable vision models from the search pages: name, description, sizes.

    The search shows 20 models per page; further pages come from ?page=N (the
    site loads them with htmx as you scroll).
    """
    models, seen = [], set()
    for page_no in range(1, _MAX_PAGES + 1):
        page = client.get(SEARCH_URL + (f"&page={page_no}" if page_no > 1 else ""),
                          headers={"HX-Request": "true"} if page_no > 1 else None).text
        entries = page.split('<a href="/library/')[1:]
        if not entries:
            break
        for entry in entries:
            name = entry.split('"', 1)[0]
            if name in seen:
                continue
            seen.add(name)
            content = entry.split(">", 1)[1].split("</a>", 1)[0]  # skip the tag's attributes
            body = re.sub(r"<svg.*?</svg>", "", content, flags=re.S)
            texts = [html.unescape(t).strip() for t in re.split(r"<[^>]+>", body)]
            texts = [t for t in texts if t]
            if "vision" not in texts or "embedding" in texts:  # embedding models can't transcribe
                continue
            # No size labels (e.g. glm-ocr): offer "latest"; the registry tells whether it
            # exists as a download (cloud-only models have no download and are dropped)
            sizes = [t for t in texts if _SIZE_RE.match(t)] or ["latest"]
            description = next((t for t in texts if len(t) > 40 and t not in _CAPABILITIES), "")
            models.append({"model": name, "description": description, "sizes": sizes})
    return models


def _download_size_gb(client: httpx.Client, name: str, tag: str) -> Optional[float]:
    try:
        response = client.get(
            MANIFEST_URL.format(name=name, tag=tag),
            headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
        )
        if response.status_code != 200:
            return None
        layers = response.json().get("layers", [])
        return round(sum(layer.get("size", 0) for layer in layers) / 1e9, 1)
    except Exception:
        return None


def get_catalog(refresh: bool = False) -> Dict[str, Any]:
    """Ollama cloud vision models and downloadable library vision models (cached)."""
    now = time.time()
    cached = _cache["data"]
    if cached and not refresh:
        ttl = _FAILED_TTL if cached.get("error") else _TTL
        if now - _cache["at"] < ttl:
            return cached

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            cloud = _cloud_models(client)
            library = _library_models(client)
            wanted = [(m, size) for m in library for size in m["sizes"]]
            with ThreadPoolExecutor(max_workers=8) as pool:
                sizes_gb = list(pool.map(lambda ms: _download_size_gb(client, ms[0]["model"], ms[1]), wanted))
        downloads = sorted((
            {"name": f"{m['model']}:{size}", "model": m["model"], "description": m["description"], "size_gb": gb}
            for (m, size), gb in zip(wanted, sizes_gb)
            if gb  # skip sizes the registry doesn't know (e.g. cloud-only)
        ), key=lambda d: (d["model"], d["size_gb"]))
        data = {"cloud": cloud, "downloads": downloads, "error": None}
    except Exception as e:
        logging.warning(f"Could not fetch the Ollama catalog: {e}")
        data = {"cloud": [], "downloads": [], "error": f"Could not reach ollama.com: {e}"}

    data["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _cache.update(at=now, data=data)
    return data
