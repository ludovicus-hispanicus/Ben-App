"""Dashboard API: one summary for the start page, and the news / update check."""
import json
import logging
import os
import re
import time
from typing import Any, Dict, List

from fastapi import APIRouter

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
)

_DB = os.path.join(os.environ.get("STORAGE_PATH", "data"), "db")
_RECENT_TTL = 60  # seconds; listing every text to find the newest is not free
_recent_cache: Dict[str, Any] = {"at": 0.0, "items": []}


def _read_jobs(filename: str) -> List[dict]:
    try:
        with open(os.path.join(_DB, filename), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else list(data.values())
    except Exception:
        return []


def _text_label(t) -> str:
    """Short name of a text: its first identifier without folders or file extension."""
    ids = t.text_identifiers
    for ident in (ids.publication, ids.museum, ids.p_number):
        if ident and ident.name:
            value = str(ident.get_value() if hasattr(ident, "get_value") else ident.name)
            value = re.split(r"[\\/]", value)[-1]
            return re.sub(r"\.(png|jpe?g|pdf|tiff?)$", "", value, flags=re.I)
    return f"BEN {t.text_id}"


def _recent_texts(dataset_names: Dict[int, str]) -> List[dict]:
    """The last 5 edited texts (cached for a minute)."""
    if time.time() - _recent_cache["at"] > _RECENT_TTL:
        from common.global_handlers import global_new_text_handler
        texts = global_new_text_handler.list_texts(limit=1_000_000)
        texts.sort(key=lambda t: t.last_modified or "", reverse=True)
        _recent_cache["items"] = texts[:5]
        _recent_cache["at"] = time.time()
    items = []
    for t in _recent_cache["items"]:
        items.append({
            "text_id": t.text_id,
            "transliteration_id": t.latest_transliteration_id,
            "label": _text_label(t),
            "dataset": dataset_names.get(t.dataset_id) if t.dataset_id else None,
            "last_modified": t.last_modified,
            "lines": t.lines_count,
            "curated": t.is_curated,
        })
    return items


def _your_data() -> Dict[str, Any]:
    from common.global_handlers import global_datasets_handler, global_new_text_handler
    datasets = global_datasets_handler.list_datasets()
    stats = global_new_text_handler.get_stats_per_dataset()
    rows = []
    for d in datasets:
        s = stats.get(d.dataset_id, {})
        rows.append({"dataset_id": d.dataset_id, "name": d.name, "texts": s.get("count", 0),
                     "curated": s.get("curated_count", 0), "curated_lines": s.get("curated_lines", 0)})
    rows.sort(key=lambda r: r["name"].lower())
    return {
        "datasets": len(rows),
        "texts": sum(r["texts"] for r in rows),
        "curated_texts": sum(r["curated"] for r in rows),
        "curated_lines": sum(r["curated_lines"] for r in rows),
        "per_dataset": rows,
    }


def _engines() -> Dict[str, Any]:
    from common.module_status import is_module_available
    engines: Dict[str, Any] = {}
    try:
        from services.kraken_training_service import kraken_training_service
        engines["kraken"] = {"active_model": kraken_training_service.get_active_model_name() or None}
    except Exception as e:
        engines["kraken"] = {"active_model": None, "error": str(e)}
    if is_module_available("yolo"):
        try:
            from clients.yolo_training_client import yolo_training_client
            active = yolo_training_client.get_active_model() or {}
            engines["layout"] = {"active_model": active.get("model_name") or active.get("name")}
        except Exception as e:
            engines["layout"] = {"active_model": None, "error": str(e)}
    try:
        from services.ollama_ocr_service import list_vision_models
        ollama = list_vision_models()
        engines["ollama"] = {"running": ollama["ollama_available"], "vision_models": len(ollama["models"])}
    except Exception:
        engines["ollama"] = {"running": False, "vision_models": 0}
    return engines


def _activity() -> List[dict]:
    """Recent batch jobs, layout trainings and Kraken models, newest first."""
    events: List[dict] = []
    for job in _read_jobs("batch_recognition_jobs.json"):
        events.append({
            "kind": "batch", "when": job.get("created_at"),
            "title": job.get("source_project_name") or job.get("source_folder_path") or "Batch OCR",
            "detail": f"{job.get('effective_model') or job.get('model')} · "
                      f"{job.get('processed_images', 0)}/{job.get('total_images', '?')} images",
            "status": job.get("status"),
        })
    for job in _read_jobs("yolo_training_jobs.json"):
        events.append({
            "kind": "layout_training", "when": job.get("created_at") or job.get("started_at"),
            "title": job.get("output_name") or job.get("dataset_name") or "Layout training",
            "detail": f"layout model · {job.get('current_epoch', 0)}/{job.get('total_epochs', '?')} epochs",
            "status": job.get("status"),
        })
    try:
        from services.kraken_training_service import kraken_training_service
        for m in kraken_training_service.get_models():
            accuracy = m.get("accuracy")
            events.append({
                "kind": "kraken_model", "when": m.get("created"), "title": m.get("name"),
                "detail": "Kraken model" + (f" · {accuracy * 100:.1f}% character accuracy" if accuracy else ""),
                "status": "completed",
            })
    except Exception as e:
        logging.warning(f"Dashboard: Kraken models unavailable: {e}")
    events = [e for e in events if e["when"]]
    events.sort(key=lambda e: str(e["when"]), reverse=True)
    return events[:6]


@router.get("/summary")
def get_summary():
    """Everything the dashboard shows except the news (cards: recent texts, data, engines, activity)."""
    data = _your_data()
    names = {r["dataset_id"]: r["name"] for r in data["per_dataset"]}
    return {
        "recent_texts": _recent_texts(names),
        "data": data,
        "engines": _engines(),
        "activity": _activity(),
    }


@router.get("/news")
def get_news():
    """The newest BEn news from GitHub (cached, refreshed at most daily) and the update check."""
    from services.news_service import get_news as news
    return news()
