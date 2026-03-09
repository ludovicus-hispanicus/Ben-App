"""Settings API - get/set application settings."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from common.app_settings import get_all_settings, update_settings

router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"],
)


class SettingsUpdateRequest(BaseModel):
    image_scale: Optional[float] = None


@router.get("")
async def get_settings():
    """Get all application settings."""
    return get_all_settings()


@router.put("")
async def save_settings(body: SettingsUpdateRequest):
    """Update application settings. Only provided fields are updated."""
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        return get_all_settings()
    return update_settings(updates)
