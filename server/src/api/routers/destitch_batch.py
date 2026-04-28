"""
Destitch Batch Router

Folder-level destitch: queue a folder of images, each classified and either
split into per-view crops or passed through unchanged.
"""

import logging
import os
from pathlib import Path

from fastapi import APIRouter

from api.dto.destitch import DestitchBatchStartRequest
from handlers.destitch_batch_handler import destitch_batch_handler

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

router = APIRouter(
    prefix="/api/v1/destitch-batch",
    tags=["destitch-batch"],
)


@router.post("/start")
async def start_batch(body: DestitchBatchStartRequest):
    """Queue a folder of images for destitch processing."""
    return destitch_batch_handler.start_batch(
        source_folder_path=body.source_folder_path,
        destination_folder_path=body.destination_folder_path,
        passthrough_non_composites=body.passthrough_non_composites,
        include_masks=body.include_masks,
        overwrite_existing=body.overwrite_existing,
        include_filenames=body.include_filenames,
        exclude_filenames=body.exclude_filenames,
    )


@router.get("/{job_id}/status")
async def get_batch_status(job_id: str):
    return destitch_batch_handler.get_batch_status(job_id)


@router.get("/jobs")
async def list_batch_jobs(limit: int = 20):
    return destitch_batch_handler.list_batch_jobs(limit=limit)


@router.post("/{job_id}/cancel")
async def cancel_batch(job_id: str):
    return destitch_batch_handler.cancel_batch(job_id)


@router.get("/browse-local")
async def browse_local_folder(path: str = "", include_images: bool = False):
    """Browse local filesystem to pick source/destination folders.
    Mirrors the shape of batch-recognition/browse-local for UI reuse.

    When include_images=true, also returns the list of image filenames in the
    folder (sorted, non-recursive). Used by the Datasets pane to show contents.
    """
    if not path:
        home = str(Path.home())
        body = {"path": home, "folders": _list_folders(home), "image_count": _count_images(home)}
        if include_images:
            body["images"] = _list_images(home)
        return body

    folder = Path(path)
    if not folder.exists() or not folder.is_dir():
        return {"path": path, "folders": [], "image_count": 0, "error": "Directory not found"}

    body = {
        "path": str(folder),
        "parent": str(folder.parent) if folder.parent != folder else None,
        "folders": _list_folders(str(folder)),
        "image_count": _count_images(str(folder)),
    }
    if include_images:
        body["images"] = _list_images(str(folder))
    return body


def _list_folders(directory: str):
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
    count = 0
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTENSIONS:
                count += 1
    except PermissionError:
        pass
    return count


def _list_images(directory: str):
    names = []
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTENSIONS:
                names.append(entry.name)
    except PermissionError:
        pass
    names.sort(key=str.lower)
    return names
