"""
Destitch Router

Endpoints for splitting a stitched tablet composite into labeled view crops.
Paired with `destitch_batch` router for folder-level jobs.
"""

import base64
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.dto.destitch import (
    DestitchClassifyRequest,
    DestitchSplitByPathRequest,
    DestitchSplitRequest,
)
from services.destitch_service import (
    DestitchClassification,
    DestitchResult,
    destitch_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/destitch",
    tags=["destitch"],
)


@router.post("/classify", response_model=DestitchClassification)
async def classify(dto: DestitchClassifyRequest):
    """Fast is-this-a-stitched-composite check. Returns a confidence score.
    The frontend uses this on image load to decide whether to auto-split."""
    return destitch_service.classify(dto.image)


@router.post("/split", response_model=DestitchResult)
async def split(dto: DestitchSplitRequest):
    """Detect views and return labeled bboxes in composite pixel space.
    Optionally embed per-view PNG crops and/or tablet-only binary masks."""
    return destitch_service.split(
        dto.image,
        include_crops=dto.include_crops,
        include_masks=dto.include_masks,
    )


@router.post("/split-by-path", response_model=DestitchResult)
async def split_by_path(dto: DestitchSplitByPathRequest):
    """Like /split but reads the image from a server-local filesystem path.
    Used by the Datasets pane so we don't round-trip 100 MB composites
    through HTTP just to slice them up."""
    file_path = Path(dto.path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {dto.path}")
    try:
        with open(file_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")
    return destitch_service.split(
        image_b64,
        include_crops=dto.include_crops,
        include_masks=dto.include_masks,
    )
