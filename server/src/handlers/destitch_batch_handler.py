"""
Destitch Batch Handler

Folder-level destitch: walks a source folder, classifies each image, and either
splits composites into per-view crops or passes single-view images through
unchanged. Background thread + in-memory job state + poll-based status endpoint.

Deliberately simpler than batch_recognition_handler: no MongoDB persistence,
no rate limiting, no model selection. Local CV only.
"""

import base64
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

import cv2

from services.destitch_service import destitch_service

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


class DestitchBatchHandler:

    def __init__(self):
        self._jobs: Dict[str, Dict] = {}
        self._cancelled: Set[str] = set()
        self._lock = threading.Lock()

    # Public API ────────────────────────────────────────────────────────

    def start_batch(
        self,
        source_folder_path: str,
        destination_folder_path: str,
        passthrough_non_composites: bool = True,
        include_masks: bool = False,
        overwrite_existing: bool = False,
        include_filenames: Optional[List[str]] = None,
        exclude_filenames: Optional[List[str]] = None,
    ) -> Dict:
        src = Path(source_folder_path)
        if not src.exists() or not src.is_dir():
            return {"success": False, "error": f"Source folder not found: {source_folder_path}"}

        dst = Path(destination_folder_path)
        dst.mkdir(parents=True, exist_ok=True)

        files = sorted(
            p for p in src.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        )
        if include_filenames:
            include_set = set(include_filenames)
            files = [p for p in files if p.name in include_set]
        if exclude_filenames:
            exclude_set = set(exclude_filenames)
            files = [p for p in files if p.name not in exclude_set]

        if not files:
            return {"success": False, "error": "No image files in source folder"}

        job_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "pending",
                "source_folder_path": str(src),
                "destination_folder_path": str(dst),
                "total_images": len(files),
                "processed_images": 0,
                "failed_images": 0,
                "current_image": 0,
                "current_filename": "",
                "results": [],
                "failed_results": [],
                "created_at": now,
                "started_at": None,
                "completed_at": None,
                "error": None,
                "options": {
                    "passthrough_non_composites": passthrough_non_composites,
                    "include_masks": include_masks,
                    "overwrite_existing": overwrite_existing,
                },
            }

        t = threading.Thread(
            target=self._run_job,
            args=(job_id, files, dst, passthrough_non_composites, include_masks, overwrite_existing),
            daemon=True,
        )
        t.start()

        return {
            "success": True,
            "job_id": job_id,
            "total_images": len(files),
            "message": f"Queued {len(files)} images for destitch.",
        }

    def get_batch_status(self, job_id: str) -> Dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return {"success": False, "error": f"Job {job_id} not found"}
            total = max(1, job["total_images"])
            return {
                **job,
                "success": True,
                "progress_percent": round(100.0 * job["processed_images"] / total, 1),
            }

    def list_batch_jobs(self, limit: int = 20) -> List[Dict]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda j: j.get("created_at") or "",
                reverse=True,
            )
            return [
                {
                    "job_id": j["job_id"],
                    "status": j["status"],
                    "source_folder_path": j.get("source_folder_path", ""),
                    "destination_folder_path": j.get("destination_folder_path", ""),
                    "total_images": j["total_images"],
                    "processed_images": j["processed_images"],
                    "failed_images": j["failed_images"],
                    "progress_percent": round(
                        100.0 * j["processed_images"] / max(1, j["total_images"]), 1),
                    "created_at": j.get("created_at"),
                    "completed_at": j.get("completed_at"),
                }
                for j in jobs[:limit]
            ]

    def cancel_batch(self, job_id: str) -> Dict:
        with self._lock:
            if job_id not in self._jobs:
                return {"success": False, "error": f"Job {job_id} not found"}
            self._cancelled.add(job_id)
            self._jobs[job_id]["status"] = "cancelled"
        return {"success": True, "message": f"Job {job_id} cancelled."}

    # Worker ─────────────────────────────────────────────────────────────

    def _run_job(
        self,
        job_id: str,
        files: List[Path],
        dst: Path,
        passthrough: bool,
        include_masks: bool,
        overwrite: bool,
    ):
        self._update(job_id, status="running",
                     started_at=datetime.utcnow().isoformat() + "Z")

        for idx, file_path in enumerate(files, start=1):
            with self._lock:
                if job_id in self._cancelled:
                    self._cancelled.discard(job_id)
                    return

            self._update(job_id, current_image=idx, current_filename=file_path.name)
            try:
                outputs = self._process_one(file_path, dst, passthrough, include_masks, overwrite)
                self._append_result(job_id, {
                    "input": file_path.name,
                    "status": outputs["status"],
                    "output_count": outputs["output_count"],
                    "outputs": outputs["outputs"],
                    "view_codes": outputs.get("view_codes", []),
                })
                self._update_counters(job_id, processed_delta=1)
            except Exception as e:
                logger.exception(f"destitch batch: failed on {file_path.name}")
                self._append_failed(job_id, {"input": file_path.name, "error": str(e)})
                self._update_counters(job_id, processed_delta=1, failed_delta=1)

        self._update(job_id, status="completed",
                     completed_at=datetime.utcnow().isoformat() + "Z",
                     current_filename="")

    def _process_one(
        self,
        file_path: Path,
        dst: Path,
        passthrough: bool,
        include_masks: bool,
        overwrite: bool,
    ) -> Dict:
        img_bgr = cv2.imread(str(file_path), cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise RuntimeError(f"unreadable image: {file_path.name}")

        with open(file_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("ascii")

        classification = destitch_service.classify(image_b64)
        tablet_id = file_path.stem

        if not classification.is_composite:
            if not passthrough:
                return {"status": "skipped", "output_count": 0, "outputs": []}
            dst_dir = dst / tablet_id
            dst_dir.mkdir(parents=True, exist_ok=True)
            out = dst_dir / file_path.name
            if out.exists() and not overwrite:
                return {"status": "passthrough_exists", "output_count": 0, "outputs": []}
            shutil.copy2(file_path, out)
            return {"status": "passthrough", "output_count": 1,
                    "outputs": [str(out.relative_to(dst))]}

        result = destitch_service.split(image_b64, include_crops=False,
                                        include_masks=include_masks)
        if result.error:
            raise RuntimeError(result.error)

        dst_dir = dst / tablet_id
        dst_dir.mkdir(parents=True, exist_ok=True)

        outputs: List[str] = []
        view_codes: List[str] = []
        ext = file_path.suffix.lower() or ".jpg"
        if ext == ".jpeg":
            ext = ".jpg"

        for view in result.views:
            out_path = dst_dir / f"{tablet_id}{view.code}{ext}"
            if out_path.exists() and not overwrite:
                view_codes.append(view.code)
                outputs.append(str(out_path.relative_to(dst)))
                continue
            crop = img_bgr[view.bbox.y: view.bbox.y + view.bbox.height,
                           view.bbox.x: view.bbox.x + view.bbox.width]
            if ext in {".jpg", ".jpeg"}:
                cv2.imwrite(str(out_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
            else:
                cv2.imwrite(str(out_path), crop)
            outputs.append(str(out_path.relative_to(dst)))
            view_codes.append(view.code)

            if include_masks and view.mask_base64:
                mask_path = dst_dir / f"{tablet_id}{view.code}_mask.png"
                if not mask_path.exists() or overwrite:
                    with open(mask_path, "wb") as f:
                        f.write(base64.b64decode(view.mask_base64))
                    outputs.append(str(mask_path.relative_to(dst)))

        return {
            "status": "destitched",
            "output_count": len(result.views),
            "outputs": outputs,
            "view_codes": view_codes,
        }

    # State helpers ──────────────────────────────────────────────────────

    def _update(self, job_id: str, **patch):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(patch)

    def _update_counters(self, job_id: str, *, processed_delta: int = 0, failed_delta: int = 0):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job["processed_images"] += processed_delta
                job["failed_images"] += failed_delta

    def _append_result(self, job_id: str, entry: Dict):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job["results"].append(entry)

    def _append_failed(self, job_id: str, entry: Dict):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job["failed_results"].append(entry)


destitch_batch_handler = DestitchBatchHandler()
