"""
eBL (Electronic Babylonian Literature) API Integration Router

Provides endpoints to:
1. Validate ATF text against eBL's parser
2. Export/upload transliterations to the eBL platform

Requires eBL credentials to be configured in environment variables:
- EBL_API_URL: Base URL of the eBL API (default: https://www.ebl.lmu.de/api)
- EBL_AUTH0_DOMAIN: Auth0 domain for eBL
- EBL_AUTH0_CLIENT_ID: Auth0 client ID
- EBL_AUTH0_CLIENT_SECRET: Auth0 client secret
- EBL_AUTH0_AUDIENCE: Auth0 API audience
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from handlers.ebl_handler import EblHandler

router = APIRouter(
    prefix="/api/v1/ebl",
    tags=["ebl"],
    responses={404: {"description": "Not found"}}
)

# Initialize handler
ebl_handler = EblHandler()


class ValidateAtfRequest(BaseModel):
    """Request to validate ATF text."""
    atf_text: str
    fragment_number: Optional[str] = None


class ValidateAtfResponse(BaseModel):
    """Response from ATF validation."""
    valid: bool
    errors: list = []
    warnings: list = []
    parsed_lines: int = 0


class ExportToEblRequest(BaseModel):
    """Request to export transliteration to eBL."""
    fragment_number: str
    atf_text: str
    notes: Optional[str] = None


class ExportToEblResponse(BaseModel):
    """Response from eBL export."""
    success: bool
    message: str
    fragment_url: Optional[str] = None


class EblConfigRequest(BaseModel):
    """Request to configure eBL credentials."""
    api_url: str = "https://www.ebl.lmu.de/api"
    auth0_domain: str
    auth0_client_id: str
    auth0_client_secret: str
    auth0_audience: str


class EblStatusResponse(BaseModel):
    """Response with eBL connection status."""
    configured: bool
    connected: bool
    api_url: Optional[str] = None
    error: Optional[str] = None


@router.get("/status", response_model=EblStatusResponse)
async def get_ebl_status():
    """Check if eBL API is configured and accessible."""
    return await ebl_handler.get_status()


@router.post("/configure")
async def configure_ebl(config: EblConfigRequest):
    """Configure eBL API credentials."""
    try:
        await ebl_handler.configure(
            api_url=config.api_url,
            auth0_domain=config.auth0_domain,
            auth0_client_id=config.auth0_client_id,
            auth0_client_secret=config.auth0_client_secret,
            auth0_audience=config.auth0_audience
        )
        return {"success": True, "message": "eBL configuration saved"}
    except Exception as e:
        logging.error(f"Failed to configure eBL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate", response_model=ValidateAtfResponse)
async def validate_atf(request: ValidateAtfRequest):
    """
    Validate ATF text against eBL's ATF parser.

    This checks if the ATF text is valid according to eBL-ATF specification.
    """
    try:
        result = await ebl_handler.validate_atf(
            atf_text=request.atf_text,
            fragment_number=request.fragment_number
        )
        return result
    except Exception as e:
        logging.error(f"ATF validation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export", response_model=ExportToEblResponse)
async def export_to_ebl(request: ExportToEblRequest):
    """
    Export transliteration to the eBL platform.

    This uploads the ATF text to eBL for the specified fragment.
    Requires valid eBL credentials with write:texts scope.
    """
    try:
        result = await ebl_handler.export_to_ebl(
            fragment_number=request.fragment_number,
            atf_text=request.atf_text,
            notes=request.notes
        )
        return result
    except Exception as e:
        logging.error(f"eBL export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fragment/{fragment_number}")
async def get_fragment(fragment_number: str):
    """
    Get a fragment from eBL by its number.

    This fetches the current state of a fragment from eBL.
    """
    try:
        result = await ebl_handler.get_fragment(fragment_number)
        return result
    except Exception as e:
        logging.error(f"Failed to get fragment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_fragments(query: str, limit: int = 10):
    """
    Search for fragments in eBL.

    This searches eBL's fragment database.
    """
    try:
        result = await ebl_handler.search_fragments(query, limit)
        return result
    except Exception as e:
        logging.error(f"Fragment search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
