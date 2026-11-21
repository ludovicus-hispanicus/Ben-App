"""
Keep PDF extractions in BEn itself, through the BEn server's HTTP API.

Every page becomes a CuReD text (page image + text lines) in a dataset named
after the PDF, under one parent dataset ("PDF extractions"). People see and
correct the pages in BEn like any other CuReD text; AI clients read them back
from BEn, so they get the corrected version.

Writes go through the running BEn server, never to its JSON database files
directly: two processes writing those files at once would overwrite each
other. If no server is running, one is started (headless).
"""

import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

BEN_URL = os.environ.get("BEN_URL", "http://127.0.0.1:5001")
DEFAULT_PARENT = "PDF extractions"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # server/src


class BenStore:
    def __init__(self, base_url: str = BEN_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=120)

    # ── server ─────────────────────────────────────────────────────────

    def is_up(self) -> bool:
        try:
            return self.client.get("/api/v1/datasets/tree", timeout=10).status_code == 200
        except Exception:
            return False

    def ensure_running(self, wait_s: int = 120) -> None:
        """Start the BEn server headless (from server/src, where its data lives) if it is not up."""
        if self.is_up():
            return
        if not self.base_url.startswith(("http://127.0.0.1", "http://localhost")):
            raise RuntimeError(f"BEn server at {self.base_url} is not reachable")
        log = open(os.path.join(HERE, "data", "ben_headless.log"), "a", encoding="utf-8")
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, "run_server.py"], cwd=HERE, stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags)
        logger.warning("BEn server was not running; started it headless")
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if self.is_up():
                return
            time.sleep(2)
        raise RuntimeError(f"BEn server did not come up within {wait_s} s (see data/ben_headless.log)")

    def _ok(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise RuntimeError(f"BEn {r.request.method} {r.request.url.path}: {r.status_code} {r.text[:200]}")
        return r.json()

    # ── datasets ───────────────────────────────────────────────────────

    def tree(self) -> List[Dict[str, Any]]:
        return self._ok(self.client.get("/api/v1/datasets/tree"))

    def find_dataset(self, name: str, parent_id: Optional[int]) -> Optional[Dict[str, Any]]:
        def walk(nodes):
            for n in nodes:
                if n["name"] == name and n.get("parent_id") == parent_id:
                    return n
                found = walk(n.get("children") or [])
                if found:
                    return found
            return None
        return walk(self.tree())

    def dataset_for(self, name: str, parent_name: str = DEFAULT_PARENT) -> int:
        """Id of dataset <parent_name>/<name>, created if missing."""
        parent = self.find_dataset(parent_name, None)
        parent_id = parent["dataset_id"] if parent else self._ok(
            self.client.post("/api/v1/datasets/create", json={"name": parent_name}))
        child = self.find_dataset(name, parent_id)
        if child:
            return child["dataset_id"]
        return self._ok(self.client.post("/api/v1/datasets/create", json={"name": name, "parent_id": parent_id}))

    def documents(self, parent_name: str = DEFAULT_PARENT) -> List[Dict[str, Any]]:
        parent = self.find_dataset(parent_name, None)
        if not parent:
            return []
        return [{"dataset_id": c["dataset_id"], "name": c["name"], "pages": c.get("text_count", 0),
                 "curated_pages": c.get("curated_count", 0)} for c in parent.get("children") or []]

    def texts(self, dataset_id: int) -> List[Dict[str, Any]]:
        items, skip = [], 0
        while True:
            page = self._ok(self.client.get(f"/api/v1/datasets/{dataset_id}/texts",
                                            params={"skip": skip, "limit": 500}))
            items += page["items"]
            skip += len(page["items"])
            if not page["items"] or skip >= page["total"]:
                return items

    # ── pages ──────────────────────────────────────────────────────────

    @staticmethod
    def publication(item: Dict[str, Any]) -> Optional[str]:
        pub = (item.get("text_identifiers") or {}).get("publication")
        if not pub:
            return None
        return pub["name"] if not pub.get("number") else f"{pub['name']}-{pub['number']}"

    @staticmethod
    def corrected(item: Dict[str, Any]) -> bool:
        return any(item.get(k) for k in ("is_curated", "is_curated_kraken", "is_curated_vlm", "is_reviewed"))

    def save_page(self, dataset_id: int, publication: str, image_jpeg: bytes, lines: List[str],
                  boxes: List[Dict[str, float]], labels: List[str], metadata: Dict[str, Any],
                  existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Store one page as a CuReD text. An existing text gets a new transliteration,
        unless someone corrected it in BEn: that is never overwritten."""
        if existing and self.corrected(existing):
            return {"text_id": existing["text_id"], "skipped": "corrected in BEn; left unchanged"}
        if existing:
            text_id = existing["text_id"]
        else:
            text_id = self._ok(self.client.post("/api/v1/text/create", json={
                "text_identifiers": {"publication": {"name": publication, "number": 0}},
                "metadata": [metadata],
                "dataset_id": dataset_id,
            }))
        image_name = self._ok(self.client.post(
            "/api/v1/cured/saveImage/", data={"text_id": str(text_id)},
            files={"file": (f"{publication.replace('/', '_')}.jpg", image_jpeg, "image/jpeg")}))
        transliteration_id = self._ok(self.client.post("/api/v1/cured/createSubmission", json={
            "text_id": text_id, "lines": lines, "boxes": boxes, "image_name": image_name}))
        self._ok(self.client.patch(f"/api/v1/text/{text_id}/labels", json={"labels": labels}))
        return {"text_id": text_id, "transliteration_id": transliteration_id, "image_name": image_name}

    def latest_lines(self, text_id: int) -> Optional[List[str]]:
        """The lines of a text's newest transliteration (what CuReD shows), or None."""
        items = self._ok(self.client.get(f"/api/v1/cured/{text_id}/transliterations"))
        items = items if isinstance(items, list) else (items or {}).get("transliterations", [])
        if not items:
            return None
        return self.lines(text_id, items[-1]["transliteration_id"])

    def lines(self, text_id: int, transliteration_id: int) -> List[str]:
        return self._ok(self.client.get(f"/api/v1/cured/transliteration/{text_id}/{transliteration_id}"))["lines"]
