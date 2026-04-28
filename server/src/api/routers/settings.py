"""Settings API - get/set application settings."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Dict
from common.app_settings import get_all_settings, update_settings, get_enabled_modules, update_enabled_modules

router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"],
)


class SettingsUpdateRequest(BaseModel):
    image_scale: Optional[float] = None


class ModulesUpdateRequest(BaseModel):
    modules: Dict[str, bool]


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


@router.get("/modules")
async def get_modules():
    """Get enabled/disabled state of all modules."""
    return get_enabled_modules()


@router.put("/modules")
async def save_modules(body: ModulesUpdateRequest):
    """Update which modules are enabled."""
    return update_enabled_modules(body.modules)
