"""
CuRe Router — API endpoints for CuRe cuneiform sign classification.

Separate from CuReD (/api/v1/cured). CuRe operates at the sign level
(individual cuneiform signs), while CuReD operates at the text line level.
"""
import asyncio
import base64
import io
import logging
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.dto.cure import (
    CuReAnnotationUploadRequest,
    CuReClassifyRequest,
    CuReClassifyResponse,
    CuReCropClassifyRequest,
    CuReCropClassifyResponse,
    CuReDetectRequest,
    CuReDetectResponse,
    CuReGuess,
    CuReLabelUploadRequest,
    CuReSignResult,
    CuReTrainingStartRequest,
)
from entities.dimensions import Dimensions
from api.dto.index import Index
from api.dto.project import CreateProjectDto, RenameProjectDto, ProjectPreviewDto
from handlers.cure_handler import cure_handler
from handlers.cure_projects_handler import cure_projects_handler

router = APIRouter(
    prefix="/api/v1/cure",
    tags=["cure"],
    responses={404: {"description": "Not found"}},
)


# ──────────────────────────────────────────────
# Project management endpoints (separate from CuReD)
# ──────────────────────────────────────────────


@router.get("/projects/list")
async def list_cure_projects() -> list[ProjectPreviewDto]:
    """List all CuRe projects (separate from CuReD projects)."""
    projects = cure_projects_handler.list_projects()
    return [
        ProjectPreviewDto(
            project_id=p.project_id,
            name=p.name,
            created_at=p.created_at,
            text_count=0,
            curated_count=0,
        )
        for p in projects
    ]


@router.post("/projects/create")
async def create_cure_project(dto: CreateProjectDto) -> int:
    """Create a new CuRe project."""
    return cure_projects_handler.create_project(name=dto.name)


@router.patch("/projects/{project_id}/rename")
async def rename_cure_project(project_id: int, dto: RenameProjectDto):
    """Rename a CuRe project."""
    project = cure_projects_handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="CuRe project not found")
    cure_projects_handler.rename_project(project_id=project_id, name=dto.name)
    return {"updated": True}


@router.delete("/projects/{project_id}")
async def delete_cure_project(project_id: int):
    """Delete a CuRe project."""
    project = cure_projects_handler.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="CuRe project not found")
    cure_projects_handler.delete_project(project_id=project_id)
    return {"deleted": True}


# ──────────────────────────────────────────────
# Inference endpoints
# ──────────────────────────────────────────────


@router.post("/classify", response_model=CuReClassifyResponse)
async def classify_image(request: CuReClassifyRequest):
    """
    Detect and classify cuneiform signs in a tablet image.

    Returns sign-level results with bounding boxes, labels, unicode,
    confidence scores, and top-3 predictions per sign.
    """
    try:
        from clients.cure_client import CuReOcrClient
        client = CuReOcrClient(model_name=request.model)
        result = client.ocr_image(
            image_base64=request.image,
            image_width=0,  # not needed, detected internally
            image_height=0,
        )

        # Convert raw dict result to typed response
        signs = []
        for s in result.get("signs", []):
            signs.append(CuReSignResult(
                label=s["label"],
                unicode=s["unicode"],
                confidence=s["confidence"],
                line=s["line"],
                position=s["position"],
                bbox=Dimensions(
                    x=s["bbox"]["x"],
                    y=s["bbox"]["y"],
                    width=s["bbox"]["width"],
                    height=s["bbox"]["height"],
                ),
                top3=[CuReGuess(**g) for g in s.get("top3", [])],
            ))

        return CuReClassifyResponse(
            lines=result.get("lines", []),
            dimensions=result.get("dimensions", []),
            signs=signs,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"CuRe classify error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect", response_model=CuReDetectResponse)
async def detect_signs(request: CuReDetectRequest):
    """
    Detect cuneiform sign bounding boxes without classification.
    Uses OpenCV contour detection only — no model needed.
    """
    try:
        from clients.cure_client import CuReOcrClient
        logging.info(f"CuRe detect: received image data, length={len(request.image)}, starts_with={request.image[:30]}")
        image_np = CuReOcrClient._decode_image(request.image)
        logging.info(f"CuRe detect: decoded image shape={image_np.shape}")

        from services.cure_detection import detect_signs as run_detection
        detections = run_detection(image_np)

        dimensions = []
        for det in detections:
            dimensions.append(Dimensions(
                x=float(det.x),
                y=float(det.y),
                width=float(det.width),
                height=float(det.height),
                index=Index(row=det.line_number, col=det.position_in_line),
            ))

        line_count = max((d.line_number for d in detections), default=-1) + 1

        return CuReDetectResponse(
            dimensions=dimensions,
            line_count=line_count,
            sign_count=len(detections),
        )
    except Exception as e:
        logging.error(f"CuRe detect error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/classify-crop", response_model=CuReCropClassifyResponse)
async def classify_crop(request: CuReCropClassifyRequest):
    """
    Classify a single pre-cropped cuneiform sign image.
    Returns top-k predictions with confidence scores.
    """
    try:
        from clients.cure_client import CuReOcrClient
        client = CuReOcrClient(model_name=request.model)
        client._ensure_loaded()

        # Decode crop
        image_np = CuReOcrClient._decode_image(request.image)
        preds = client._classifier.classify_single(image_np, top_k=request.top_k)

        predictions = []
        for label, conf in preds:
            predictions.append(CuReGuess(
                label=label,
                unicode=client._label_service.get_unicode(label),
                confidence=round(conf, 4),
            ))

        return CuReCropClassifyResponse(predictions=predictions)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"CuRe classify-crop error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────
# Model management endpoints
# ──────────────────────────────────────────────


@router.get("/models")
async def list_models():
    """List all trained CuRe models."""
    import json
    import os

    models_dir = cure_handler.models_dir
    registry_path = os.path.join(models_dir, "registry.json")

    if not os.path.exists(registry_path):
        return {"models": []}

    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    # Check which model is active
    active_model = None
    active_path = os.path.join(models_dir, "active_model.pt")
    if os.path.exists(active_path):
        # Read the active model name from a marker file
        active_marker = os.path.join(models_dir, "active_model_name.txt")
        if os.path.exists(active_marker):
            with open(active_marker, "r", encoding="utf-8") as f:
                active_model = f.read().strip()

    for model in registry:
        model["is_active"] = (model.get("name") == active_model)

    return {"models": registry, "active_model": active_model}


@router.get("/models/active")
async def get_active_model():
    """Get information about the currently active CuRe model."""
    import json
    import os

    models_dir = cure_handler.models_dir
    active_path = os.path.join(models_dir, "active_model.pt")

    if not os.path.exists(active_path):
        return {"active": False, "message": "No active model. Train or import a model first."}

    active_marker = os.path.join(models_dir, "active_model_name.txt")
    active_name = None
    if os.path.exists(active_marker):
        with open(active_marker, "r", encoding="utf-8") as f:
            active_name = f.read().strip()

    # Load mapping to get class count
    mapping_path = os.path.join(models_dir, "active_label_mapping.json")
    num_classes = 0
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping = json.load(f)
            num_classes = len(mapping.get("label_list", []))

    return {
        "active": True,
        "model_name": active_name,
        "num_classes": num_classes,
    }


@router.post("/models/{model_name}/activate")
async def activate_model(model_name: str):
    """Activate a trained CuRe model for inference."""
    import os
    import shutil

    models_dir = cure_handler.models_dir
    model_path = os.path.join(models_dir, f"{model_name}.pt")
    mapping_path = os.path.join(models_dir, f"{model_name}_label_mapping.json")

    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_name}")
    if not os.path.exists(mapping_path):
        raise HTTPException(status_code=404, detail=f"Label mapping not found for: {model_name}")

    # Copy to active
    shutil.copy2(model_path, os.path.join(models_dir, "active_model.pt"))
    shutil.copy2(mapping_path, os.path.join(models_dir, "active_label_mapping.json"))

    # Write active model name marker
    with open(os.path.join(models_dir, "active_model_name.txt"), "w", encoding="utf-8") as f:
        f.write(model_name)

    # Clear cached classifier so next request loads the new model
    from services.cure_classifier import clear_cached_classifier
    clear_cached_classifier()

    logging.info(f"CuRe model activated: {model_name}")
    return {"message": f"Model '{model_name}' activated", "model_name": model_name}


@router.delete("/models/{model_name}")
async def delete_model(model_name: str):
    """Delete a trained CuRe model."""
    import json
    import os

    models_dir = cure_handler.models_dir
    model_path = os.path.join(models_dir, f"{model_name}.pt")
    mapping_path = os.path.join(models_dir, f"{model_name}_label_mapping.json")

    if not os.path.exists(model_path):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_name}")

    # Check if this is the active model
    active_marker = os.path.join(models_dir, "active_model_name.txt")
    if os.path.exists(active_marker):
        with open(active_marker, "r", encoding="utf-8") as f:
            if f.read().strip() == model_name:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot delete the active model. Activate a different model first.",
                )

    # Delete files
    os.remove(model_path)
    if os.path.exists(mapping_path):
        os.remove(mapping_path)

    # Remove from registry
    registry_path = os.path.join(models_dir, "registry.json")
    if os.path.exists(registry_path):
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        registry = [m for m in registry if m.get("name") != model_name]
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)

    logging.info(f"CuRe model deleted: {model_name}")
    return {"message": f"Model '{model_name}' deleted"}


# ──────────────────────────────────────────────
# Training endpoints
# ──────────────────────────────────────────────


@router.get("/training/status")
async def get_training_status():
    """Get training data statistics and readiness."""
    stats = cure_handler.get_annotation_stats()

    from services.cure_training_service import cure_training_service
    min_signs = cure_training_service.MIN_SIGNS

    return {
        **stats,
        "min_signs_required": min_signs,
        "is_ready": stats["total_crops"] >= min_signs,
        "progress_pct": min(100, int(stats["total_crops"] / max(1, min_signs) * 100)),
    }


@router.post("/training/start")
async def start_training(
    request: CuReTrainingStartRequest,
    background_tasks: BackgroundTasks,
):
    """Start CuRe model training as a background task."""
    from services.cure_training_service import cure_training_service

    # Check if training is already running
    if cure_training_service.progress.status.value == "training":
        raise HTTPException(status_code=409, detail="Training is already in progress")

    # Check if enough data
    stats = cure_handler.get_annotation_stats()
    if stats["total_crops"] < cure_training_service.MIN_SIGNS:
        raise HTTPException(
            status_code=400,
            detail=f"Not enough training data. Need {cure_training_service.MIN_SIGNS} sign crops, "
                   f"have {stats['total_crops']}.",
        )

    # Generate model name if not provided
    if not request.model_name:
        import datetime
        request.model_name = f"cure_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def run_training_sync():
        asyncio.run(cure_training_service.start_training(
            epochs=request.epochs,
            model_name=request.model_name,
            batch_size=request.batch_size,
            learning_rate=request.learning_rate,
            base_model=request.base_model,
        ))

    background_tasks.add_task(run_training_sync)

    logging.info(f"CuRe training started: {request.model_name}, {request.epochs} epochs")
    return {
        "message": "Training started",
        "model_name": request.model_name,
        "epochs": request.epochs,
    }


@router.get("/training/progress")
async def get_training_progress():
    """Get current training progress."""
    from services.cure_training_service import cure_training_service
    return cure_training_service.progress.to_dict()


@router.post("/training/cancel")
async def cancel_training():
    """Cancel the current training run."""
    from services.cure_training_service import cure_training_service
    cure_training_service.cancel_training()
    return {"message": "Training cancellation requested"}


# ──────────────────────────────────────────────
# Training data management endpoints
# ──────────────────────────────────────────────


@router.post("/annotations/upload")
async def upload_annotations(request: CuReAnnotationUploadRequest):
    """
    Upload a tablet image with sign-level annotations for training.
    Annotations CSV must have columns: x1, y1, x2, y2, label
    """
    try:
        result = cure_handler.upload_annotation(
            image_base64=request.image,
            annotations_csv=request.annotations_csv,
            image_name=request.image_name,
        )
        return result
    except Exception as e:
        logging.error(f"CuRe annotation upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/annotations/stats")
async def get_annotation_stats():
    """Get statistics about the current training annotations."""
    return cure_handler.get_annotation_stats()


@router.get("/labels")
async def get_labels():
    """Get the current label/unicode mapping from the active model."""
    import json
    import os

    models_dir = cure_handler.models_dir
    mapping_path = os.path.join(models_dir, "active_label_mapping.json")

    if not os.path.exists(mapping_path):
        return {"labels": [], "label_to_unicode": {}}

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    return {
        "labels": mapping.get("label_list", []),
        "label_to_unicode": mapping.get("label_to_unicode", {}),
        "num_classes": len(mapping.get("label_list", [])),
    }


@router.post("/labels/upload")
async def upload_labels(request: CuReLabelUploadRequest):
    """Upload a label-to-unicode CSV mapping."""
    import csv as csv_module
    import io
    import json
    import os

    reader = csv_module.DictReader(io.StringIO(request.csv_content))
    mapping = {}
    for row in reader:
        label = row.get("label", "").strip()
        unicode_char = row.get("unicode", "").strip()
        if label and unicode_char:
            mapping[label] = unicode_char

    # Merge with existing active mapping if present
    models_dir = cure_handler.models_dir
    mapping_path = os.path.join(models_dir, "active_label_mapping.json")

    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_unicode = existing.get("label_to_unicode", {})
        existing_unicode.update(mapping)
        existing["label_to_unicode"] = existing_unicode
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

    return {"message": f"Uploaded {len(mapping)} label-unicode mappings", "count": len(mapping)}
