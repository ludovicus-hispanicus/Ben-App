"""
Segmentation API Router

Provides unified line segmentation endpoints for all components (CuReD, CuRe, etc.).
Auto-detects image type (lineart vs photo) and routes to the appropriate pipeline.
Also serves test tablet data from Shahar's cuneiform dataset for development.
"""

import base64
import csv
import logging
import os
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services.segmentation_service import SegmentationService, ImageType, SegmentationResult

logger = logging.getLogger()

router = APIRouter(
    prefix="/api/v1/segmentation",
    tags=["segmentation"],
    responses={404: {"description": "Not found"}},
)

segmentation_service = SegmentationService()


# ── DTOs ───────────────────────────────────────────────────────────────

class SegmentRequest(BaseModel):
    image: str  # base64 encoded image (with or without data URI prefix)
    image_type: Optional[ImageType] = None  # force lineart or photo; None = auto-detect


class ClassifyRequest(BaseModel):
    image: str  # base64 encoded image


class ClassifyResponse(BaseModel):
    image_type: ImageType


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/segment", response_model=SegmentationResult)
async def segment(dto: SegmentRequest):
    """
    Segment an image into text lines.

    If image_type is not provided, the service auto-detects whether the image
    is a lineart (hand copy) or a photograph and applies the appropriate pipeline.
    """
    return segmentation_service.segment(dto.image, image_type=dto.image_type)


@router.post("/segment/lineart", response_model=SegmentationResult)
async def segment_lineart(dto: SegmentRequest):
    """Force the lineart segmentation pipeline."""
    return segmentation_service.segment(dto.image, image_type=ImageType.LINEART)


@router.post("/segment/photo", response_model=SegmentationResult)
async def segment_photo(dto: SegmentRequest):
    """Force the photo segmentation pipeline."""
    return segmentation_service.segment(dto.image, image_type=ImageType.PHOTO)


@router.post("/classify", response_model=ClassifyResponse)
async def classify(dto: ClassifyRequest):
    """
    Classify an image as lineart or photo without running segmentation.
    Uses histogram bimodality and edge density analysis.
    """
    image_type = segmentation_service.classify_image(dto.image)
    return ClassifyResponse(image_type=image_type)


# ── Test Tablet Data ──────────────────────────────────────────────────

# Shahar's dataset paths
DATASET_CSV = r"C:\Users\wende\Documents\Shahar\cuneiform_dataset-20260319T204135Z-1-002\cuneiform_dataset\dataset.csv"
IMAGE_DIR = r"C:\Users\wende\Documents\Shahar\file"

# Pre-selected test tablets — 20 strictly-successive Neo-Assyrian SAA 19
# administrative letters starting from P393645 (skipping only the two CDLI
# IDs in this range that don't exist: P393660, P393665). 13 have photo files,
# 7 are lineart-only — the line-segmentation tool prefers photo when
# available and falls back to lineart otherwise.
TEST_TABLETS = [
    "P393645", "P393646", "P393647", "P393648", "P393649",
    "P393650", "P393651", "P393652", "P393653", "P393654",
    "P393655", "P393656", "P393657", "P393658", "P393659",
    "P393661", "P393662", "P393663", "P393664", "P393666",
]


class TabletSummary(BaseModel):
    p_number: str
    designation: str
    period: str
    genre: str
    line_count: int
    has_lineart: bool
    has_photo: bool
    has_translation: bool


class TabletDetail(BaseModel):
    p_number: str
    designation: str
    period: str
    genre: str
    transliteration: str
    translation: str
    has_lineart: bool
    has_photo: bool


def _load_tablet_row(p_number: str) -> dict:
    """Load a single row from the dataset CSV by P-number."""
    if not os.path.exists(DATASET_CSV):
        raise HTTPException(status_code=404, detail="Dataset CSV not found")
    with open(DATASET_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["p_number"] == p_number:
                return row
    raise HTTPException(status_code=404, detail=f"Tablet {p_number} not found")


@router.get("/tablets", response_model=List[TabletSummary])
async def list_test_tablets():
    """List the pre-selected test tablets for segmentation development."""
    if not os.path.exists(DATASET_CSV):
        return []

    results = []
    with open(DATASET_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["p_number"] not in TEST_TABLETS:
                continue
            translit = row.get("transliteration", "")
            line_count = len([l for l in translit.split("\n") if l.strip()])
            results.append(TabletSummary(
                p_number=row["p_number"],
                designation=row.get("designation", ""),
                period=row.get("period", ""),
                genre=row.get("genre", ""),
                line_count=line_count,
                has_lineart=row.get("has_lineart") == "True",
                has_photo=row.get("has_photo") == "True",
                has_translation=bool(row.get("translation", "").strip()),
            ))
    # Sort by the pre-defined order
    order = {p: i for i, p in enumerate(TEST_TABLETS)}
    results.sort(key=lambda t: order.get(t.p_number, 999))
    return results


@router.get("/tablets/{p_number}", response_model=TabletDetail)
async def get_tablet(p_number: str):
    """Get full detail for a tablet (transliteration, translation, image availability)."""
    row = _load_tablet_row(p_number)
    return TabletDetail(
        p_number=row["p_number"],
        designation=row.get("designation", ""),
        period=row.get("period", ""),
        genre=row.get("genre", ""),
        transliteration=row.get("transliteration", ""),
        translation=row.get("translation", ""),
        has_lineart=row.get("has_lineart") == "True",
        has_photo=row.get("has_photo") == "True",
    )


@router.get("/tablets/{p_number}/lineart")
async def get_tablet_lineart(p_number: str):
    """Serve the lineart image for a tablet."""
    path = os.path.join(IMAGE_DIR, "lineart", f"{p_number}.jpg")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Lineart not found")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/tablets/{p_number}/photo")
async def get_tablet_photo(p_number: str):
    """Serve the photo image for a tablet."""
    path = os.path.join(IMAGE_DIR, "photos", f"{p_number}.jpg")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(path, media_type="image/jpeg")
