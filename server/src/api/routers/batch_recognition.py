"""
Batch Recognition Router - REST endpoints for batch OCR processing.
"""

import logging
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Request

from api.dto.batch_recognition import BatchRecognitionRequest
from handlers.batch_recognition_handler import batch_recognition_handler

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/batch-recognition",
    tags=["batch-recognition"],
)


@router.post("/start")
async def start_batch(request: Request, body: BatchRecognitionRequest):
    """Start a batch recognition job."""
    user_id = getattr(request.state, "user_id", "admin")

    result = await batch_recognition_handler.start_batch(
        source_project_id=body.source_project_id,
        source_folder_path=body.source_folder_path,
        include_classes=body.include_classes,
        model=body.model,
        prompt=body.prompt,
        custom_prompt=body.custom_prompt,
        api_key=body.api_key,
        sub_model=body.sub_model,
        batch_size=body.batch_size,
        destination_dataset_id=body.destination_dataset_id,
        destination_folder_path=body.destination_folder_path,
        export_images=body.export_images,
        user_id=user_id,
        correction_rules=body.correction_rules,
        image_scale=body.image_scale,
        target_dpi=body.target_dpi,
        include_filenames=body.include_filenames,
        exclude_filenames=body.exclude_filenames,
        box_mode=body.box_mode,
        tiling_mode=body.tiling_mode or "none",
    )
    return result


@router.get("/{job_id}/status")
async def get_batch_status(job_id: str):
    """Get the current status of a batch recognition job."""
    return batch_recognition_handler.get_batch_status(job_id)


@router.get("/jobs")
async def list_batch_jobs(limit: int = 20):
    """List recent batch recognition jobs."""
    return batch_recognition_handler.list_batch_jobs(limit=limit)


@router.post("/{job_id}/cancel")
async def cancel_batch(job_id: str):
    """Cancel a running batch recognition job."""
    return batch_recognition_handler.cancel_batch(job_id)


@router.get("/usage")
async def get_usage(days: int = 7):
    """Get API usage stats for the last N days."""
    from services import usage_tracker
    return usage_tracker.get_usage(days=days)


@router.get("/usage/reset-hours")
async def get_reset_hours():
    """Get configured quota reset hours per provider."""
    from services.usage_tracker import _load_reset_hours
    return _load_reset_hours()


@router.put("/usage/reset-hours/{provider}")
async def set_reset_hour(provider: str, hour: int):
    """Set the quota reset hour (0-23) for a provider prefix (e.g. 'gemini')."""
    from services import usage_tracker
    usage_tracker.set_reset_hour(provider, hour)
    return {"provider": provider, "reset_hour": max(0, min(23, hour))}


@router.get("/vllm-status")
async def get_vllm_status():
    """Check if a vLLM server is reachable and list available models/adapters."""
    vllm_url = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{vllm_url}/models")
            if response.status_code == 200:
                data = response.json()
                models = [m["id"] for m in data.get("data", [])]
                return {"available": True, "models": models, "url": vllm_url}
    except Exception:
        pass
    return {"available": False, "models": [], "url": vllm_url}


@router.get("/browse-local")
async def browse_local_folder(path: str = ""):
    """Browse local filesystem directories and count images."""
    if not path:
        # Return filesystem roots / home directory
        home = str(Path.home())
        return {"path": home, "folders": _list_folders(home), "image_count": _count_images(home)}

    folder = Path(path)
    if not folder.exists() or not folder.is_dir():
        return {"path": path, "folders": [], "image_count": 0, "error": "Directory not found"}

    return {
        "path": str(folder),
        "parent": str(folder.parent) if folder.parent != folder else None,
        "folders": _list_folders(str(folder)),
        "image_count": _count_images(str(folder)),
    }


def _list_folders(directory: str):
    """List subdirectories in a directory."""
    folders = []
    try:
        for entry in sorted(os.scandir(directory), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith("."):
                try:
                    img_count = _count_images(entry.path)
                except PermissionError:
                    img_count = 0
                folders.append({"name": entry.name, "path": entry.path, "image_count": img_count})
    except PermissionError:
        pass
    return folders


def _count_images(directory: str) -> int:
    """Count image files in a directory (non-recursive)."""
    count = 0
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTENSIONS:
                count += 1
    except PermissionError:
        pass
    return count
