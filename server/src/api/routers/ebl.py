"""
eBL (Electronic Babylonian Literature) API Integration Router

Provides endpoints to:
1. Configure eBL access with manual token
2. Validate ATF text against eBL's parser
3. Export/upload transliterations to the eBL platform
"""

import logging
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
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
    # Validation source:
    # - "ebl_api": Full eBL API validation with sign verification
    # - "local_lark": Local Lark parser validation (syntax only)
    # - "local_basic": Basic bracket checking fallback
    validation_source: str = "local_basic"


class ExportToEblRequest(BaseModel):
    """Request to export transliteration to eBL."""
    fragment_number: str
    atf_text: str
    notes: Optional[str] = None
    introduction: Optional[str] = None
    skip_validation: bool = False


class ExportToEblResponse(BaseModel):
    """Response from eBL export."""
    success: bool
    message: str
    fragment_url: Optional[str] = None
    error_code: Optional[str] = None
    status_code: Optional[int] = None
    help: Optional[str] = None
    validation_errors: Optional[List[str]] = None
    validation_details: Optional[List[dict]] = None


class EblConfigRequest(BaseModel):
    """Request to configure eBL with manual access token."""
    api_url: str = "https://www.ebl.lmu.de/api"
    access_token: str


class TokenInfo(BaseModel):
    """Token info with scopes and permissions."""
    class Config:
        extra = "allow"

    scopes: Optional[list] = None
    permissions: Optional[list] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    sub: Optional[str] = None
    aud: Optional[Any] = None  # Can be string or list in JWT
    error: Optional[str] = None


class EblStatusResponse(BaseModel):
    """Response with eBL connection status."""
    configured: bool
    connected: bool
    api_url: Optional[str] = None
    error: Optional[str] = None
    token_info: Optional[TokenInfo] = None
    auth_method: Optional[str] = None
    oauth_pending: bool = False


@router.get("/status")
async def get_ebl_status():
    """Check if eBL API is configured and accessible."""
    return await ebl_handler.get_status()


@router.post("/configure")
async def configure_ebl(config: EblConfigRequest):
    """Configure eBL API with manual access token."""
    try:
        await ebl_handler.configure(
            api_url=config.api_url,
            access_token=config.access_token
        )
        return {"success": True, "message": "eBL configuration saved successfully"}
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
    Uses the /fragments/{number}/edition endpoint.
    Requires valid eBL access token with transliterate:fragments scope.
    """
    try:
        result = await ebl_handler.export_to_ebl(
            fragment_number=request.fragment_number,
            atf_text=request.atf_text,
            notes=request.notes,
            introduction=request.introduction,
            skip_validation=request.skip_validation
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


# ==========================================
# OAuth PKCE Endpoints
# ==========================================

@router.post("/oauth/start")
async def start_oauth():
    """Start the Auth0 PKCE login flow. Opens the system browser for eBL login."""
    port = int(os.environ.get("APP_PORT", 5001))
    result = ebl_handler.start_oauth_flow(callback_port=port)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(code: str = "", state: str = "", error: str = "", error_description: str = ""):
    """
    Auth0 redirect callback. This is hit by the system browser after login.
    Returns an HTML page telling the user they can close the tab.
    """
    if error:
        ebl_handler._oauth_pending = False
        ebl_handler._oauth_error = error_description or error
        logging.error(f"OAuth callback error: {error} - {error_description}")
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html><head><title>eBL Login Failed</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#fef2f2}}
.card{{text-align:center;padding:40px;border-radius:12px;background:white;box-shadow:0 2px 12px rgba(0,0,0,.1)}}
h1{{color:#dc2626;font-size:24px}} p{{color:#666;margin-top:12px}}</style></head>
<body><div class="card"><h1>Login Failed</h1><p>{error_description or error}</p><p>You can close this tab and try again in BEn.</p></div></body></html>""")

    if not code:
        return HTMLResponse(content="""<!DOCTYPE html>
<html><head><title>eBL Login Error</title>
<style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#fef2f2}
.card{text-align:center;padding:40px;border-radius:12px;background:white;box-shadow:0 2px 12px rgba(0,0,0,.1)}
h1{color:#dc2626;font-size:24px} p{color:#666;margin-top:12px}</style></head>
<body><div class="card"><h1>Login Error</h1><p>No authorization code received.</p><p>You can close this tab and try again in BEn.</p></div></body></html>""")

    result = await ebl_handler.handle_oauth_callback(code=code, state=state)

    if result.get("success"):
        return HTMLResponse(content="""<!DOCTYPE html>
<html><head><title>eBL Login Successful</title>
<style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#f0fdf4}
.card{text-align:center;padding:40px;border-radius:12px;background:white;box-shadow:0 2px 12px rgba(0,0,0,.1)}
h1{color:#16a34a;font-size:24px} p{color:#666;margin-top:12px}
.check{font-size:48px;margin-bottom:16px}</style></head>
<body><div class="card"><div class="check">&#10003;</div><h1>Login Successful!</h1><p>You are now connected to eBL.</p><p>You can close this tab and return to BEn.</p></div></body></html>""")
    else:
        error_msg = result.get("error", "Unknown error")
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html><head><title>eBL Login Failed</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#fef2f2}}
.card{{text-align:center;padding:40px;border-radius:12px;background:white;box-shadow:0 2px 12px rgba(0,0,0,.1)}}
h1{{color:#dc2626;font-size:24px}} p{{color:#666;margin-top:12px}}</style></head>
<body><div class="card"><h1>Login Failed</h1><p>{error_msg}</p><p>You can close this tab and try again in BEn.</p></div></body></html>""")


@router.get("/oauth/status")
async def get_oauth_status():
    """Get the current OAuth flow status. Frontend polls this after starting OAuth."""
    return ebl_handler.get_oauth_status()


class LoginRequest(BaseModel):
    """Login with eBL credentials."""
    username: str
    password: str


@router.post("/auth/login")
async def login_with_credentials(request: LoginRequest):
    """Log in to eBL using email/password (Auth0 Password Grant)."""
    result = await ebl_handler.login_with_credentials(
        username=request.username,
        password=request.password
    )
    if not result.get("success"):
        raise HTTPException(status_code=401, detail=result.get("error", "Login failed"))
    return {"success": True, "message": "Logged in to eBL successfully"}


@router.post("/disconnect")
async def disconnect_ebl():
    """Disconnect from eBL by clearing all tokens."""
    ebl_handler.disconnect()
    return {"success": True, "message": "Disconnected from eBL"}
