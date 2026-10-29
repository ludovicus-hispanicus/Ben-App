"""
BEn news and update check for the dashboard.

Reads NEWS.md from the GitHub repository and the latest release tag, at most
once a day and in the background (the app never waits for it). The result is
cached in data/db/news_cache.json, so the dashboard also shows news offline.
Settings can switch it off ("news_enabled"), since it contacts GitHub.

NEWS.md format: one "## YYYY-MM-DD — Title" heading per entry, newest first,
followed by Markdown text.
"""
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

REPO = "ludovicus-hispanicus/Ben-App"
NEWS_URL = f"https://raw.githubusercontent.com/{REPO}/main/NEWS.md"
RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
REFRESH_EVERY = timedelta(days=1)

_CACHE_FILE = os.path.join(os.environ.get("STORAGE_PATH", "data"), "db", "news_cache.json")
_refresh_lock = threading.Lock()
_ENTRY_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*[—–-]+\s*(.+?)\s*$")


def installed_version() -> str:
    """The app version (Electron passes it in BEN_VERSION; 'dev' when run from source)."""
    return os.environ.get("BEN_VERSION", "dev")


def parse_news(markdown: str) -> List[Dict[str, str]]:
    """Entries from NEWS.md: [{"date", "title", "body"}], in file order (newest first)."""
    entries: List[Dict[str, str]] = []
    for line in markdown.splitlines():
        match = _ENTRY_RE.match(line)
        if match:
            entries.append({"date": match.group(1), "title": match.group(2), "body": ""})
        elif entries and not line.startswith("# "):
            entries[-1]["body"] += line + "\n"
    for entry in entries:
        entry["body"] = entry["body"].strip()
    return entries


def _version_tuple(version: str) -> Optional[tuple]:
    numbers = re.findall(r"\d+", version or "")
    return tuple(int(n) for n in numbers[:3]) if numbers else None


def _load_cache() -> Dict[str, Any]:
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    tmp = _CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _CACHE_FILE)


def _news_enabled() -> bool:
    from common.app_settings import get_setting
    return get_setting("news_enabled") is not False


def _due(cache: Dict[str, Any]) -> bool:
    fetched = cache.get("fetched_at")
    if not fetched:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(fetched) > REFRESH_EVERY
    except ValueError:
        return True


def refresh(force: bool = False) -> None:
    """Fetch NEWS.md and the latest release (if enabled and due). Never raises."""
    if not _news_enabled():
        return
    if not _refresh_lock.acquire(blocking=False):
        return  # a refresh is already running
    try:
        cache = _load_cache()
        if not force and not _due(cache):
            return
        result = dict(cache)
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                news = client.get(NEWS_URL)
                if news.status_code == 200:
                    result["entries"] = parse_news(news.text)
                release = client.get(RELEASE_URL, headers={"Accept": "application/vnd.github+json"})
                if release.status_code == 200:
                    data = release.json()
                    result["latest_version"] = data.get("tag_name")
                    result["release_url"] = data.get("html_url")
            result["error"] = None
        except Exception as e:
            logging.info(f"News: GitHub not reachable ({e}); showing the cached news")
            result["error"] = "GitHub not reachable"
        result["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save_cache(result)
    finally:
        _refresh_lock.release()


def refresh_in_background(force: bool = False) -> None:
    threading.Thread(target=refresh, kwargs={"force": force}, daemon=True).start()


def get_news() -> Dict[str, Any]:
    """Cached news plus the update check; starts a background refresh when due."""
    enabled = _news_enabled()
    cache = _load_cache()
    if enabled and _due(cache):
        refresh_in_background()
    installed = installed_version()
    latest = cache.get("latest_version")
    installed_t, latest_t = _version_tuple(installed), _version_tuple(latest)
    return {
        "enabled": enabled,
        "entries": cache.get("entries", [])[:3] if enabled else [],
        "fetched_at": cache.get("fetched_at"),
        "error": cache.get("error"),
        "installed_version": installed,
        "latest_version": latest,
        "release_url": cache.get("release_url"),
        "update_available": bool(enabled and installed_t and latest_t and latest_t > installed_t),
    }
